"""Interpretação depois de cada sincronização: autoridade das fontes e importação.

Regra da fonte oficial (README, seção 2):
- a planilha apontada pelo INDEX cria as atividades ACT-* **uma única vez**;
- daí em diante o banco do app é a fonte oficial: editar a planilha não sobrescreve
  nada, e a diferença fica sinalizada para revisão humana;
- planilha não apontada pelo INDEX nunca importa nem apaga;
- se o INDEX passar a apontar outra planilha, não há troca automática.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from . import activities, analysis, conflicts, db, suggestions
from .activities import IMPORT_ACTOR, PRIORITIES
from .authority import TEXT_KINDS, Resolution, normalize, refresh, register_columns, resolve, stem
from .config import settings
from .readers import parse_header

STATUS_ALIASES = {
    "a fazer": "a_fazer", "pendente": "a_fazer", "nao iniciada": "a_fazer", "aberta": "a_fazer",
    "em andamento": "em_andamento", "em progresso": "em_andamento", "fazendo": "em_andamento",
    "bloqueada": "bloqueada", "bloqueado": "bloqueada", "impedida": "bloqueada",
    "concluida": "concluida", "concluido": "concluida", "feita": "concluida", "feito": "concluida",
    "finalizada": "concluida",
}


def after_sync(conn: sqlite3.Connection, folder_id: str) -> None:
    """Também é chamada depois de uma decisão de conflito (não lê o Drive, só o banco)."""
    _refresh_headers(conn)
    res = refresh(conn, folder_id)
    imported = conn.execute("SELECT * FROM register_import WHERE id = 1").fetchone()
    if imported is None:
        state, message = _try_import(conn, res)
        imported = conn.execute("SELECT * FROM register_import WHERE id = 1").fetchone()
    else:
        state, message = _check_after_import(conn, res, imported)

    found = conflicts.refresh(conn, res, imported)
    # Ambiguidade ou troca de fonte já decididas por uma pessoa deixam de pedir atenção.
    about_source = [c for c in found if c["kind"] in ("fonte_ambigua", "troca_de_fonte")]
    if state == "atencao" and about_source and all(c["status"] == "resolvido" for c in about_source):
        state = "importada" if imported is not None else "aguardando"
        message += "".join(
            f" Decisão registrada por {c['resolver_name'] or c['resolved_by']} em {_br(c['closed_at'])}: {c['resolution']}"
            for c in about_source
        )
    conn.execute(
        """INSERT INTO register_status (id, state, message, checked_at) VALUES (1, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET state = excluded.state, message = excluded.message,
               checked_at = excluded.checked_at""",
        (state, message, db.utcnow()),
    )


def _refresh_headers(conn: sqlite3.Connection) -> None:
    """Relê título e cabeçalho do texto já guardado (barato; não acessa o Drive).

    Assim uma melhoria no leitor vale também para arquivos lidos antes dela, e a data do
    documento nas sugestões daquela versão é corrigida.
    """
    rows = conn.execute(
        f"""SELECT s.file_id, s.content_hash, s.doc_title, s.doc_meta, v.extracted_text FROM sources s
            JOIN source_versions v ON v.file_id = s.file_id AND v.content_hash = s.content_hash
            WHERE s.kind IN ({','.join('?' * len(TEXT_KINDS))})""", TEXT_KINDS,
    ).fetchall()
    for r in rows:
        title, meta = parse_header(r["extracted_text"])
        meta_json = json.dumps(meta, ensure_ascii=False)
        if title == r["doc_title"] and meta_json == (r["doc_meta"] or "{}"):
            continue
        conn.execute("UPDATE sources SET doc_title = ?, doc_meta = ? WHERE file_id = ?", (title, meta_json, r["file_id"]))
        written = str(meta.get("data_da_reuniao") or "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", written):
            conn.execute("UPDATE suggestions SET doc_date = ? WHERE source_file_id = ? AND source_version = ? AND origin = 'ata'",
                         (written, r["file_id"], r["content_hash"]))


# ---------------------------------------------------------------------------
# Antes da importação
# ---------------------------------------------------------------------------


def _pick_sheet(conn: sqlite3.Connection, src: sqlite3.Row, pointer: Any) -> tuple[dict | None, str | None]:
    """Aba de atividades da planilha: a citada no INDEX ou, sem citação, a primeira com ID e Atividade."""
    version = conn.execute(
        "SELECT structured_json FROM source_versions WHERE file_id = ? AND content_hash = ?",
        (src["file_id"], src["content_hash"]),
    ).fetchone()
    sheets = json.loads(version["structured_json"]).get("sheets", []) if version else []
    wanted = pointer.sheet if pointer else None
    if wanted:
        sheet = next((s for s in sheets if normalize(s["name"]) == normalize(wanted)), None)
        if sheet is None:
            found = ", ".join(s["name"] for s in sheets) or "nenhuma"
            return None, f"A aba “{wanted}” não existe em {src['name']} (abas: {found})."
    else:
        sheet = next((s for s in sheets if register_columns(s) is not None), None)
        if sheet is None:
            return None, f"Nenhuma aba de {src['name']} tem as colunas ID e Atividade."
    if register_columns(sheet) is None:
        return None, f"A aba “{sheet['name']}” de {src['name']} não tem as colunas ID e Atividade."
    return sheet, None


def _try_import(conn: sqlite3.Connection, res: Resolution) -> tuple[str, str]:
    nothing = " Nenhuma atividade foi importada."
    if res.register is None:
        return ("atencao" if res.ambiguous else "aguardando"), (res.problem or "") + nothing
    src = res.register
    if src["sync_status"] != "processed" or not src["content_hash"]:
        reason = src["status_reason"] or "ainda não lida"
        return "atencao", f"A planilha {src['name']} não pôde ser lida ({reason}). Nova tentativa na próxima sincronização." + nothing
    sheet, problem = _pick_sheet(conn, src, res.pointer)
    if sheet is None:
        return "atencao", problem + nothing
    columns = register_columns(sheet)
    members = conn.execute("SELECT * FROM members").fetchall()
    rows, skipped = [], []
    for r in sheet["rows"][1:]:
        cells = {f: (r["cells"][i] if i < len(r["cells"]) else None) for f, i in columns.items()}
        if all(v in (None, "") for v in cells.values()):
            continue
        if not cells.get("id"):
            skipped.append(f"Linha {r['row']} sem ID: não importada.")
            continue
        rows.append((r, cells))
    if not rows:
        return "aguardando", (
            f"A planilha {src['name']} (aba {sheet['name']}) ainda não tem atividades. "
            "Nada foi importado e nada foi apagado."
        )

    now = db.utcnow()
    n = 0
    for r, cells in rows:
        activity_id = str(cells["id"]).strip().upper()
        if conn.execute("SELECT 1 FROM activities WHERE activity_id = ?", (activity_id,)).fetchone():
            skipped.append(f"Linha {r['row']}: {activity_id} já existe no app; linha não importada.")
            continue
        _import_row(conn, src, sheet["name"], r, cells, activity_id, members, now)
        n += 1
    conn.execute(
        """INSERT INTO register_import (id, file_id, file_name, sheet_name, content_hash, imported_at, n_imported, warnings)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?)""",
        (src["file_id"], src["name"], sheet["name"], src["content_hash"], now, n,
         json.dumps(skipped, ensure_ascii=False)),
    )
    return "importada", f"{n} atividade(s) importada(s) de {src['name']} (aba {sheet['name']})."


def _import_row(conn, src, sheet_name, r, cells, activity_id, members, now) -> None:
    warnings: list[str] = []
    owners, w = _parse_owners(cells.get("owners"), members)
    warnings += w
    due, w = _parse_due(cells.get("due_date"))
    warnings += w
    status, w = _parse_status(cells.get("status"))
    warnings += w
    title = _text(cells.get("title"))
    if not title:
        title = f"(sem título na planilha) {activity_id}"
        warnings.append("sem título na planilha")
    data = {
        "title": title,
        "owners": owners,
        "front": _front(cells.get("front"), members),
        "status": status,
        "due_date": due,
        "next_step": _text(cells.get("next_step")),
        "priority": _priority(cells.get("priority")),
        "description": None,
        "notes": _text(cells.get("notes")),
    }
    activities.insert(conn, activity_id, data, origin="import", created_by=IMPORT_ACTOR, now=now)

    locator = f"aba {sheet_name}, linha {r['row']}"
    quote = " | ".join("" if c is None else str(c) for c in r["cells"])
    conn.execute(
        """INSERT INTO activity_refs (activity_id, file_id, version_or_hash, locator, quote, relation_type, created_at)
           VALUES (?,?,?,?,?, 'imported_from', ?)""",
        (activity_id, src["file_id"], src["content_hash"], locator, quote, now),
    )
    origin = _text(cells.get("origin"))
    if origin and not _link_origin(conn, activity_id, origin, now):
        warnings.append(f"origem “{origin}” citada na planilha não foi encontrada na pasta")

    reason = f"Importada de {src['name']} ({locator}): a planilha apontada pelo INDEX cria as atividades uma única vez."
    if warnings:
        reason += " Avisos: " + "; ".join(warnings) + "."
    activities.record_event(conn, activity_id, IMPORT_ACTOR, "import", None, activities.snapshot(conn, activity_id),
                            reason=reason, source_file_id=src["file_id"], source_version=src["content_hash"], ts=now)


def _link_origin(conn: sqlite3.Connection, activity_id: str, origin: str, now: str) -> bool:
    """Liga a atividade ao documento citado na coluna Origem, com a linha que cita o ID."""
    wanted = normalize(origin)
    source = next(
        (s for s in conn.execute("SELECT * FROM sources WHERE content_hash IS NOT NULL")
         if normalize(s["name"]) == wanted or (s["kind"] == "gdoc" and normalize(s["name"]) == normalize(stem(origin)))),
        None,
    )
    if source is None:
        return False
    quote, locator = None, None
    if source["kind"] in TEXT_KINDS:
        text = conn.execute(
            "SELECT extracted_text FROM source_versions WHERE file_id = ? AND content_hash = ?",
            (source["file_id"], source["content_hash"]),
        ).fetchone()
        for n, line in enumerate((text["extracted_text"] if text else "").split("\n"), start=1):
            if re.search(rf"\b{re.escape(activity_id)}\b", line):
                quote, locator = line.strip().lstrip("-* ").strip(), f"linha {n}"
                break
    conn.execute(
        """INSERT INTO activity_refs (activity_id, file_id, version_or_hash, locator, quote, relation_type, created_at)
           VALUES (?,?,?,?,?, 'origin', ?)""",
        (activity_id, source["file_id"], source["content_hash"], locator, quote, now),
    )
    return True


# ---------------------------------------------------------------------------
# Depois da importação: só sinaliza, nunca sobrescreve
# ---------------------------------------------------------------------------


def _check_after_import(conn: sqlite3.Connection, res: Resolution, imported: sqlite3.Row) -> tuple[str, str]:
    src = conn.execute("SELECT * FROM sources WHERE file_id = ?", (imported["file_id"],)).fetchone()
    keep = " As atividades do app não mudaram."
    if src is not None and src["sync_status"] == "processed" and src["content_hash"]:
        compare_register_versions(conn, src, imported)
    if res.register is not None and res.register["file_id"] != imported["file_id"]:
        return "atencao", (
            f"O INDEX agora aponta {res.register['name']}, diferente da planilha importada "
            f"({imported['file_name']}). A troca de fonte não é automática e depende de decisão humana." + keep
        )
    if src is None or src["sync_status"] == "unavailable":
        reason = src["status_reason"] if src else "arquivo não encontrado"
        return "atencao", f"A planilha importada ({imported['file_name']}) não está disponível no Drive: {reason}" + keep
    if src["content_hash"] != imported["content_hash"]:
        pending = conn.execute(
            "SELECT COUNT(*) FROM suggestions WHERE origin = 'planilha' AND source_file_id = ? AND review_status = 'pendente'",
            (src["file_id"],),
        ).fetchone()[0]
        return "alterada", (
            f"{src['name']} foi alterada no Drive depois da importação. Nada foi aplicado automaticamente: "
            f"{pending} sugestão(ões) da planilha aguardando revisão humana em “Sugestões para revisar”." + keep
        )
    if res.register is None and res.problem:
        return "atencao", f"Atenção ao INDEX: {res.problem}" + keep
    switch = conn.execute(
        """SELECT s.*, m.display_name FROM register_switches s LEFT JOIN members m ON m.member_id = s.decided_by
           ORDER BY s.switch_id DESC LIMIT 1"""
    ).fetchone()
    if switch is not None and switch["to_file_id"] == imported["file_id"]:
        return "importada", (
            f"Fonte vigente: {imported['file_name']} (aba {imported['sheet_name']}), desde {_br(switch['decided_at'])}, "
            f"quando {switch['display_name']} aceitou a troca de {switch['from_file_name']}. "
            "As diferenças viraram sugestões para revisão; a planilha não mudou desde então."
        )
    return "importada", f"Importação de {imported['file_name']} em vigor; a planilha não mudou desde então."


def _br(value: str | None) -> str:
    try:
        return datetime.fromisoformat(value).astimezone(settings.timezone).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return value or "?"


# ---------------------------------------------------------------------------
# Planilha importada editada no Drive → sugestões (comparação, sem IA)
# ---------------------------------------------------------------------------

REGISTER_FIELDS = ("title", "owners", "due_date", "front", "priority", "status", "next_step", "notes")


def _register_rows(conn: sqlite3.Connection, file_id: str, content_hash: str, sheet_name: str,
                   members: list[sqlite3.Row]) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Linhas da aba de atividades numa versão: {ID: {row, fields, raw, labels, warnings}}."""
    version = conn.execute(
        "SELECT structured_json FROM source_versions WHERE file_id = ? AND content_hash = ?", (file_id, content_hash)
    ).fetchone()
    sheets = json.loads(version["structured_json"]).get("sheets", []) if version else []
    sheet = next((s for s in sheets if normalize(s["name"]) == normalize(sheet_name)), None)
    if sheet is None:
        return {}, f"A aba “{sheet_name}” não existe nesta versão da planilha; nada foi comparado."
    columns = register_columns(sheet)
    if columns is None:
        return {}, f"A aba “{sheet_name}” não tem mais as colunas ID e Atividade; nada foi comparado."
    header = sheet["rows"][0]["cells"]
    out: dict[str, dict[str, Any]] = {}
    for r in sheet["rows"][1:]:
        cells = {f: (r["cells"][i] if i < len(r["cells"]) else None) for f, i in columns.items()}
        if not cells.get("id"):
            continue
        fields: dict[str, Any] = {"title": _text(cells.get("title"))}
        warnings: list[str] = []
        if "owners" in columns:
            fields["owners"], w = _parse_owners(cells.get("owners"), members)
            warnings += [x for x in w if not x.startswith("sem responsável")]
        if "due_date" in columns:
            due, w = _parse_due(cells.get("due_date"))
            if any("não é uma data" in x for x in w):
                warnings += w  # não propõe apagar o prazo por causa de uma célula ilegível
            else:
                fields["due_date"] = due
        if "status" in columns:
            status, w = _parse_status(cells.get("status"))
            if w:
                warnings += w
            else:
                fields["status"] = status
        if "front" in columns:
            fields["front"] = _front(cells.get("front"), members)
        if "priority" in columns:
            fields["priority"] = _priority(cells.get("priority"))
        for f in ("next_step", "notes"):
            if f in columns:
                fields[f] = _text(cells.get(f))
        out[str(cells["id"]).strip().upper()] = {
            "row": r["row"], "fields": fields, "warnings": warnings,
            "raw": {f: cells.get(f) for f in fields},
            "labels": {f: str(header[columns[f]]) for f in fields},
        }
    return out, None


def _cell_text(value: Any) -> str:
    return "vazio" if value in (None, "") else str(value)


def compare_register_versions(conn: sqlite3.Connection, src: sqlite3.Row, imported: sqlite3.Row) -> None:
    """Compara a versão atual da planilha importada com a anterior (não com o banco).

    Assim uma edição feita no app nunca vira sugestão de "voltar" ao valor antigo da planilha.
    Célula mudada → sugestão de atualização; linha nova → sugestão de criação; linha apagada →
    só aviso (nada é apagado). Sugestão pendente que a planilha não sustenta mais → substituída.
    """
    file_id, current_hash = src["file_id"], src["content_hash"]
    if conn.execute("SELECT 1 FROM analyses WHERE file_id = ? AND content_hash = ? AND status = 'ok'",
                    (file_id, current_hash)).fetchone():
        return
    last = conn.execute(
        "SELECT content_hash FROM analyses WHERE file_id = ? AND origin = 'planilha' AND status = 'ok' "
        "ORDER BY analysis_id DESC LIMIT 1", (file_id,),
    ).fetchone()
    base_hash = last["content_hash"] if last else imported["content_hash"]
    if base_hash == current_hash:
        return
    members = conn.execute("SELECT * FROM members").fetchall()
    sheet = imported["sheet_name"]
    before, _ = _register_rows(conn, file_id, base_hash, sheet, members)
    after, problem = _register_rows(conn, file_id, current_hash, sheet, members)
    notes = [problem] if problem else []
    current = suggestions.current_activities(conn)

    stale = []
    for s in conn.execute(
        """SELECT suggestion_id, target_activity_id, proposed_id, proposed_fields FROM suggestions
           WHERE origin = 'planilha' AND source_file_id = ? AND review_status = 'pendente' AND source_version != ?""",
        (file_id, current_hash),
    ):
        row = after.get(s["target_activity_id"] or s["proposed_id"] or "")
        proposed = json.loads(s["proposed_fields"])
        if row is None or any(not suggestions.same_value(f, row["fields"].get(f), v) for f, v in proposed.items()):
            stale.append(s["suggestion_id"])
    suggestions.supersede(conn, stale, "A planilha mudou de novo no Drive: o valor proposto não está mais nela.")

    rationale = "A planilha importada foi editada no Drive; a mudança só vale no app depois de revisão humana."
    drafts = []
    for aid, row in ([] if problem else after.items()):
        prev = before.get(aid)
        if prev is None and aid not in current:
            proposed = {f: v for f, v in row["fields"].items() if v not in (None, "", [])}
            if not proposed.get("title"):
                notes.append(f"Linha {row['row']} ({aid}) é nova, mas está sem título: nenhuma sugestão.")
                continue
            quote = " | ".join(f"{row['labels'][f]}: {_cell_text(row['raw'][f])}" for f in row["fields"])
            d = suggestions.Draft("create", None, proposed, {}, [{"quote": f"{aid} | {quote}",
                                  "locator": f"aba {sheet}, linha {row['row']} (linha nova)"}],
                                  rationale, list(row["warnings"]), [], front=proposed.get("front"))
            d.proposed_id = aid
            drafts.append(d)
            continue
        if aid not in current:
            notes.append(f"Linha {row['row']} ({aid}) mudou, mas essa atividade não existe no app: nenhuma sugestão.")
            continue
        old = prev["fields"] if prev else {}
        changed = [f for f in row["fields"] if prev is None or not suggestions.same_value(f, old.get(f), row["fields"][f])]
        changed = [f for f in changed if not suggestions.same_value(f, current[aid].get(f), row["fields"][f])]
        if not changed:
            continue
        evidence = [{"quote": f"{row['labels'][f]}: {_cell_text(row['raw'][f])}",
                     "locator": f"aba {sheet}, linha {row['row']} ({aid}), coluna {row['labels'][f]}"
                                + (f"; na versão anterior: {_cell_text(prev['raw'].get(f))}" if prev else "")}
                    for f in changed]
        d = suggestions.Draft("update", aid, {f: row["fields"][f] for f in changed},
                              {f: current[aid].get(f) for f in changed}, evidence, rationale,
                              list(row["warnings"]), [], front=current[aid].get("front"))
        if prev is None:
            d.alerts.append(f"A linha {aid} apareceu agora na planilha; no app, {aid} é “{current[aid]['title']}”. "
                            "Confira se é a mesma atividade.")
        drafts.append(d)
    for aid, row in before.items():
        if aid not in after and not problem:
            notes.append(f"{aid} saiu da planilha (estava na linha {row['row']}): nada foi apagado no app.")

    now = db.utcnow()
    cur = conn.execute(
        """INSERT INTO analyses (file_id, content_hash, origin, base_hash, status, generated_by, attempts, notes,
               created_at, updated_at)
           VALUES (?, ?, 'planilha', ?, 'ok', 'comparacao', 1, '[]', ?, ?)""",
        (file_id, current_hash, base_hash, now, now),
    )
    n, more = suggestions.insert_drafts(conn, drafts, analysis_id=cur.lastrowid, origin="planilha",
                                        source_file_id=file_id, source_version=current_hash,
                                        doc_date=analysis.doc_date(src, settings), generated_by="comparacao")
    conn.execute("UPDATE analyses SET n_suggestions = ?, notes = ? WHERE analysis_id = ?",
                 (n, json.dumps(notes + more, ensure_ascii=False), cur.lastrowid))


# ---------------------------------------------------------------------------
# Troca de fonte aceita por uma pessoa (conflito "o INDEX aponta outra planilha")
# ---------------------------------------------------------------------------


def _app_value(f: str, value: Any, names: dict[str, str]) -> str:
    if value in (None, "", []):
        return "vazio"
    if f == "owners":
        return ", ".join(names.get(m, m) for m in value)
    if f == "status":
        return activities.STATUSES.get(value, value)
    if f == "due_date":
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    return str(value)


def accept_new_source(conn: sqlite3.Connection, conflict_id: int, member: sqlite3.Row, folder_id: str) -> tuple[int, list[str]]:
    """A planilha que o INDEX passou a apontar vira a fonte vigente. Nenhuma atividade muda.

    Cada diferença entre a nova planilha e o app vira sugestão: campo diferente → atualização
    (com alerta se contraria decisão humana registrada no app); linha só na planilha → criação;
    atividade só no app → aviso, nunca apagada. Célula vazia na planilha não propõe apagar valor.
    Chamada logo depois de `conflicts.decide(..., "aceitar_nova_fonte")`, na mesma transação.
    """
    conflict = conn.execute("SELECT * FROM conflicts WHERE conflict_id = ?", (conflict_id,)).fetchone()
    imported = conn.execute("SELECT * FROM register_import WHERE id = 1").fetchone()
    res = resolve(conn, folder_id)
    src = res.register
    if imported is None or src is None or src["file_id"] != conflict["file_id"]:
        raise ValueError("A situação mudou desde que o conflito foi aberto (o INDEX não aponta mais essa planilha). "
                         "Sincronize de novo e veja o conflito atual. Nada foi trocado.")
    if src["sync_status"] != "processed" or not src["content_hash"]:
        raise ValueError(f"A nova planilha {src['name']} não pôde ser lida ({src['status_reason'] or 'ainda não lida'}). "
                         "Nada foi trocado.")
    sheet, problem = _pick_sheet(conn, src, res.pointer)
    if sheet is None:
        raise ValueError(problem + " Nada foi trocado.")
    members = conn.execute("SELECT * FROM members").fetchall()
    names = {m["member_id"]: m["display_name"] for m in members}
    rows, _ = _register_rows(conn, src["file_id"], src["content_hash"], sheet["name"], members)
    current = suggestions.current_activities(conn)

    old = [r[0] for r in conn.execute(
        "SELECT suggestion_id FROM suggestions WHERE origin = 'planilha' AND source_file_id = ? AND review_status = 'pendente'",
        (imported["file_id"],))]
    suggestions.supersede(conn, old, f"A fonte das atividades passou a ser {src['name']} (decisão de "
                                     f"{member['display_name']}): sugestões da planilha anterior foram substituídas.")

    rationale = (f"O INDEX passou a apontar {src['name']} e {member['display_name']} aceitou a nova fonte; "
                 "a diferença só vale no app depois de revisão.")
    drafts, notes, empty = [], [], 0
    for aid, row in rows.items():
        if aid not in current:
            proposed = {f: v for f, v in row["fields"].items() if v not in (None, "", [])}
            if not proposed.get("title"):
                notes.append(f"Linha {row['row']} ({aid}) está sem título: nenhuma sugestão.")
                continue
            quote = " | ".join(f"{row['labels'][f]}: {_cell_text(row['raw'][f])}" for f in row["fields"])
            d = suggestions.Draft("create", None, proposed, {}, [{"quote": f"{aid} | {quote}",
                                  "locator": f"aba {sheet['name']}, linha {row['row']} (só na nova planilha)"}],
                                  rationale, list(row["warnings"]), [], front=proposed.get("front"))
            d.proposed_id = aid
            drafts.append(d)
            continue
        changed = []
        for f, v in row["fields"].items():
            if v in (None, "", []):
                empty += int(current[aid].get(f) not in (None, "", []))
            elif not suggestions.same_value(f, current[aid].get(f), v):
                changed.append(f)
        if not changed:
            continue
        evidence = [{"quote": f"{row['labels'][f]}: {_cell_text(row['raw'][f])}",
                     "locator": f"aba {sheet['name']}, linha {row['row']} ({aid}), coluna {row['labels'][f]}; "
                                f"valor no app: {_app_value(f, current[aid].get(f), names)}"}
                    for f in changed]
        drafts.append(suggestions.Draft("update", aid, {f: row["fields"][f] for f in changed},
                                        {f: current[aid].get(f) for f in changed}, evidence, rationale,
                                        list(row["warnings"]), [], front=current[aid].get("front")))
    for aid in current:
        if aid not in rows:
            notes.append(f"{aid} existe no app, mas não está em {src['name']}: nada foi apagado.")
    if empty:
        notes.append(f"{empty} célula(s) vazia(s) na nova planilha para campos preenchidos no app: ignoradas "
                     "(a troca de fonte nunca apaga valores).")

    now = db.utcnow()
    conn.execute(
        """INSERT INTO analyses (file_id, content_hash, origin, base_hash, status, generated_by, attempts, notes,
               created_at, updated_at)
           VALUES (?, ?, 'planilha', NULL, 'ok', 'comparacao', 1, '[]', ?, ?)
           ON CONFLICT(file_id, content_hash) DO UPDATE SET status = 'ok', error = NULL, base_hash = NULL,
               generated_by = 'comparacao', updated_at = excluded.updated_at""",
        (src["file_id"], src["content_hash"], now, now),
    )
    analysis_id = conn.execute("SELECT analysis_id FROM analyses WHERE file_id = ? AND content_hash = ?",
                               (src["file_id"], src["content_hash"])).fetchone()[0]
    n, more = suggestions.insert_drafts(conn, drafts, analysis_id=analysis_id, origin="planilha",
                                        source_file_id=src["file_id"], source_version=src["content_hash"],
                                        doc_date=analysis.doc_date(src, settings), generated_by="comparacao")
    notes = [f"Troca de fonte aceita por {member['display_name']}: comparação de {src['name']} com os valores do app."] + notes + more
    conn.execute("UPDATE analyses SET n_suggestions = ?, notes = ? WHERE analysis_id = ?",
                 (n, json.dumps(notes, ensure_ascii=False), analysis_id))
    conn.execute(
        """INSERT INTO register_switches (conflict_id, from_file_id, from_file_name, to_file_id, to_file_name, to_sheet,
               to_hash, decided_by, decided_at, n_suggestions)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (conflict_id, imported["file_id"], imported["file_name"], src["file_id"], src["name"], sheet["name"],
         src["content_hash"], member["member_id"], now, n),
    )
    # A partir daqui, a "fonte vigente" é a nova planilha; data e avisos da importação original ficam.
    conn.execute("UPDATE register_import SET file_id = ?, file_name = ?, sheet_name = ?, content_hash = ? WHERE id = 1",
                 (src["file_id"], src["name"], sheet["name"], src["content_hash"]))
    return n, notes


# ---------------------------------------------------------------------------
# Conversão de células
# ---------------------------------------------------------------------------


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _parse_owners(value: Any, members: list[sqlite3.Row]) -> tuple[list[str], list[str]]:
    text = _text(value)
    if not text:
        return [], ["sem responsável na planilha (responsável a confirmar)"]
    by_name = {normalize(m["display_name"]): m["member_id"] for m in members}
    ids, warnings = [], []
    for name in (p.strip() for p in re.split(r"[;,/]|\s+e\s+", text)):
        if not name:
            continue
        member_id = by_name.get(normalize(name))
        if member_id:
            if member_id not in ids:
                ids.append(member_id)
        else:
            warnings.append(f"responsável “{name}” não corresponde a nenhum membro (a confirmar)")
    return sorted(ids), warnings


def _parse_due(value: Any) -> tuple[str | None, list[str]]:
    if value is None or value == "":
        return None, []
    if isinstance(value, (int, float)) and 20000 < value < 80000:
        d = date(1899, 12, 30) + timedelta(days=int(value))
        return d.isoformat(), [f"prazo lido como número de data do Excel ({value})"]
    text = str(value).strip()
    try:
        if m := re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:[T ][\d:.]+)?", text):
            return date.fromisoformat(m.group(1)).isoformat(), []
        if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text):
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat(), []
    except ValueError:
        pass
    return None, [f"prazo “{text}” não é uma data (prazo a definir)"]


def _parse_status(value: Any) -> tuple[str, list[str]]:
    text = _text(value)
    status = STATUS_ALIASES.get(normalize(text or ""))
    if status:
        return status, []
    if not text:
        return "a_fazer", ["estado vazio na planilha; registrada como “A fazer”"]
    return "a_fazer", [f"estado “{text}” não reconhecido; registrada como “A fazer” até revisão"]


def _front(value: Any, members: list[sqlite3.Row]) -> str | None:
    text = _text(value)
    if not text:
        return None
    known = {normalize(m["front"]): m["front"] for m in members}
    return known.get(normalize(text), text)


def _priority(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    return next((p for p in PRIORITIES if normalize(p) == normalize(text)), text)
