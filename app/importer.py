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
from datetime import date, timedelta
from typing import Any

from . import activities, db
from .activities import IMPORT_ACTOR, PRIORITIES
from .authority import TEXT_KINDS, Resolution, normalize, refresh, stem

HEADER_ALIASES = {
    "id": ("id", "codigo", "identificador"),
    "title": ("atividade", "titulo", "tarefa"),
    "owners": ("responsaveis", "responsavel"),
    "due_date": ("prazo", "data limite", "vencimento", "entrega"),
    "front": ("frente",),
    "priority": ("prioridade",),
    "status": ("status", "estado", "situacao"),
    "next_step": ("proximo passo", "proximos passos"),
    "origin": ("origem",),
    "notes": ("notas e bloqueios", "notas", "observacoes", "bloqueios"),
}
STATUS_ALIASES = {
    "a fazer": "a_fazer", "pendente": "a_fazer", "nao iniciada": "a_fazer", "aberta": "a_fazer",
    "em andamento": "em_andamento", "em progresso": "em_andamento", "fazendo": "em_andamento",
    "bloqueada": "bloqueada", "bloqueado": "bloqueada", "impedida": "bloqueada",
    "concluida": "concluida", "concluido": "concluida", "feita": "concluida", "feito": "concluida",
    "finalizada": "concluida",
}


def after_sync(conn: sqlite3.Connection, folder_id: str) -> None:
    res = refresh(conn, folder_id)
    imported = conn.execute("SELECT * FROM register_import WHERE id = 1").fetchone()
    if imported is None:
        state, message = _try_import(conn, res)
    else:
        state, message = _check_after_import(conn, res, imported)
    conn.execute(
        """INSERT INTO register_status (id, state, message, checked_at) VALUES (1, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET state = excluded.state, message = excluded.message,
               checked_at = excluded.checked_at""",
        (state, message, db.utcnow()),
    )


# ---------------------------------------------------------------------------
# Antes da importação
# ---------------------------------------------------------------------------


def _try_import(conn: sqlite3.Connection, res: Resolution) -> tuple[str, str]:
    nothing = " Nenhuma atividade foi importada."
    if res.register is None:
        return ("atencao" if res.ambiguous else "aguardando"), (res.problem or "") + nothing
    src = res.register
    if src["sync_status"] != "processed" or not src["content_hash"]:
        reason = src["status_reason"] or "ainda não lida"
        return "atencao", f"A planilha {src['name']} não pôde ser lida ({reason}). Nova tentativa na próxima sincronização." + nothing
    version = conn.execute(
        "SELECT structured_json FROM source_versions WHERE file_id = ? AND content_hash = ?",
        (src["file_id"], src["content_hash"]),
    ).fetchone()
    sheets = json.loads(version["structured_json"]).get("sheets", []) if version else []

    wanted = res.pointer.sheet if res.pointer else None
    if wanted:
        sheet = next((s for s in sheets if normalize(s["name"]) == normalize(wanted)), None)
        if sheet is None:
            found = ", ".join(s["name"] for s in sheets) or "nenhuma"
            return "atencao", f"A aba “{wanted}” não existe em {src['name']} (abas: {found})." + nothing
    else:
        sheet = next((s for s in sheets if _columns(s) is not None), None)
        if sheet is None:
            return "atencao", f"Nenhuma aba de {src['name']} tem as colunas ID e Atividade." + nothing

    columns = _columns(sheet)
    if columns is None:
        return "atencao", f"A aba “{sheet['name']}” de {src['name']} não tem as colunas ID e Atividade." + nothing
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


def _columns(sheet: dict[str, Any]) -> dict[str, int] | None:
    if not sheet.get("rows"):
        return None
    header = [normalize(str(c)) if c is not None else "" for c in sheet["rows"][0]["cells"]]
    columns: dict[str, int] = {}
    for field, aliases in HEADER_ALIASES.items():
        for i, name in enumerate(header):
            if name in aliases and field not in columns:
                columns[field] = i
    return columns if "id" in columns and "title" in columns else None


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
    if res.register is not None and res.register["file_id"] != imported["file_id"]:
        return "atencao", (
            f"O INDEX agora aponta {res.register['name']}, diferente da planilha importada "
            f"({imported['file_name']}). A troca de fonte não é automática e depende de decisão humana." + keep
        )
    if src is None or src["sync_status"] == "unavailable":
        reason = src["status_reason"] if src else "arquivo não encontrado"
        return "atencao", f"A planilha importada ({imported['file_name']}) não está disponível no Drive: {reason}" + keep
    if src["content_hash"] != imported["content_hash"]:
        return "alterada", (
            f"{src['name']} foi alterada no Drive depois da importação. Nada foi aplicado automaticamente: "
            "as diferenças precisam de revisão humana." + keep
        )
    if res.register is None and res.problem:
        return "atencao", f"Atenção ao INDEX: {res.problem}" + keep
    return "importada", f"Importação de {imported['file_name']} em vigor; a planilha não mudou desde então."


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
