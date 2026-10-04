"""Sugestões: validação do que a IA (ou a comparação da planilha) propõe, e revisão humana.

Regras (invariantes do projeto):
- uma sugestão nunca altera atividade sozinha; só o aceite de uma pessoa revisora altera;
- a evidência precisa aparecer literalmente no texto da versão processada, senão o item é
  descartado (e o descarte fica visível, com motivo);
- responsável e prazo só entram se estiverem escritos no trecho; data relativa → vazio + incerteza;
- ID citado precisa existir; hipótese ("talvez") não vira sugestão;
- campo igual ao valor oficial atual é removido (uma ata que só repete o registro gera zero sugestões);
- revisar de novo uma sugestão já revisada não repete nada (recarregar a página é seguro).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from . import activities, db
from .activities import FIELD_LABELS, STATUSES
from .ai import is_hypothesis
from .authority import normalize
from .config import settings

REVIEW_LABELS = {
    "pendente": ("Pendente", "alerta", "?"),
    "aceita": ("Aceita", "ok", "✓"),
    "ajustada": ("Ajustada e aceita", "ok", "✓"),
    "rejeitada": ("Rejeitada", "neutro", "✕"),
    "substituida": ("Substituída", "neutro", "↻"),
}
MONTHS = ("janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro",
          "outubro", "novembro", "dezembro")
_STOPWORDS = {"o", "a", "os", "as", "um", "uma", "de", "da", "do", "das", "dos", "e", "em", "no", "na",
              "nos", "nas", "para", "com", "por", "ao", "aos"}


class NotAllowed(Exception):
    pass


class AlreadyReviewed(Exception):
    pass


class SourceUnavailable(ValueError):
    """O documento da sugestão saiu do Drive (ou perdeu o acesso): não pode ser aceita até voltar."""


# ---------------------------------------------------------------------------
# Comparação de textos
# ---------------------------------------------------------------------------


def flat(text: str) -> str:
    """Texto para conferir evidência: sem marcação Markdown, aspas/traços unificados, espaços simples."""
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"[*_`#>]", "", text)
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    text = text.replace("–", "-").replace("—", "-")
    return " ".join(text.split()).casefold()


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", normalize(text or "")) if w not in _STOPWORDS}


def same_text(a: str | None, b: str | None) -> bool:
    """Mesmo conteúdo, ignorando maiúsculas, acentos, pontuação e artigos ("o", "a"...)."""
    return words(a or "") == words(b or "")


def same_value(fieldname: str, a: Any, b: Any) -> bool:
    if fieldname in ("title", "next_step", "notes", "description"):
        return same_text(a, b)
    if fieldname == "owners":
        return sorted(a or []) == sorted(b or [])
    return (a or None) == (b or None)


def _date_written(iso: str, text: str) -> bool:
    d = date.fromisoformat(iso)
    t = normalize(text)
    forms = [iso, f"{d.day:02d}/{d.month:02d}/{d.year}", f"{d.day}/{d.month}/{d.year}",
             f"{d.day:02d}/{d.month:02d}", f"{d.day}/{d.month}",
             f"{d.day} de {MONTHS[d.month - 1]}", f"{d.day:02d} de {MONTHS[d.month - 1]}"]
    return any(re.search(rf"(?<![\d/-]){re.escape(f)}(?![\d/-])", t) for f in forms)


def _name_written(name: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(normalize(name))}\b", normalize(text)) is not None


def locate(quote: str, document: str) -> str | None:
    """Seção e linha onde o trecho começa (para a pessoa revisora achar no documento)."""
    start = flat(quote)[:40]
    heading = None
    lines = document.split("\n")
    for n, line in enumerate(lines, start=1):
        if line.strip().startswith("#"):
            heading = line.strip().lstrip("#").strip()
        if start and start in flat(line):
            return f"seção “{heading}”, linha {n}" if heading else f"linha {n}"
    return "trecho em mais de uma linha"


def evidence_found(quote: str, document: str) -> bool:
    """O trecho aparece literalmente no documento (aceita reticências entre partes)."""
    parts = [p for p in re.split(r"\s*(?:\.\.\.|…|\[\.\.\.\])\s*", quote or "") if p.strip()]
    doc = flat(document)
    return bool(parts) and all(len(flat(p)) >= 8 and flat(p) in doc for p in parts)


# ---------------------------------------------------------------------------
# Validação da saída do provedor
# ---------------------------------------------------------------------------


@dataclass
class Draft:
    kind: str
    target_activity_id: str | None
    proposed: dict[str, Any]
    base: dict[str, Any]
    evidence: list[dict[str, str]]
    rationale: str | None
    uncertainties: list[str]
    related: list[str]
    front: str | None = None
    front_inferred: bool = False
    alerts: list[str] = field(default_factory=list)
    proposed_id: str | None = None  # criação vinda da planilha: ID da linha


@dataclass
class Validation:
    drafts: list[Draft]
    notes: list[str]  # descartes e observações, sempre com o motivo


def _clip(value: Any, limit: int) -> str | None:
    text = " ".join(str(value or "").split())
    return text[:limit] or None


def validate(items: list[dict[str, Any]], document: str, current: dict[str, dict[str, Any]],
             members: list[sqlite3.Row]) -> Validation:
    """Confere cada item contra o documento e o registro atual. Nada aqui grava no banco."""
    notes: list[str] = []
    by_name = {normalize(m["display_name"]): m for m in members}
    by_id = {m["member_id"]: m for m in members}
    updates: dict[str, Draft] = {}
    creates: list[Draft] = []

    for n, item in enumerate(items, start=1):
        kind = item.get("kind")
        quote = (item.get("evidence") or "").strip()
        label = f"Item {n}"
        if kind == "no_action":
            continue
        if kind not in ("create", "update"):
            notes.append(f"{label} descartado: tipo “{kind}” desconhecido.")
            continue
        if not evidence_found(quote, document):
            notes.append(f"{label} descartado: o trecho citado não aparece no documento (“{_clip(quote, 120) or 'vazio'}”).")
            continue
        if is_hypothesis(quote):
            notes.append(f"{label} descartado: o trecho é uma hipótese, não uma decisão (“{_clip(quote, 120)}”).")
            continue
        uncertainties = [u for u in (_clip(x, 240) for x in (item.get("uncertainties") or [])[:5]) if u]
        proposed: dict[str, Any] = {}

        owners: list[str] = []
        target_now = current.get(str(item.get("target_activity_id") or "").strip().upper(), {})
        for raw in item.get("owners") or []:
            name = _clip(raw, 80) or ""
            member = by_name.get(normalize(name)) or by_id.get(name.upper())
            if member is None:
                uncertainties.append(f"“{name}” não corresponde a nenhum membro: responsável a confirmar.")
            elif not _name_written(member["display_name"], quote) and member["member_id"] not in (target_now.get("owners") or []):
                # Quem já é responsável pode ser repetido sem estar no trecho (não é mudança); pessoa nova, não.
                uncertainties.append(f"Responsável proposto ({member['display_name']}) não aparece no trecho citado: não incluído.")
            elif member["member_id"] not in owners:
                owners.append(member["member_id"])
        if owners:
            proposed["owners"] = sorted(owners)

        due = item.get("due_date")
        if due:
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(due)):
                    raise ValueError
                date.fromisoformat(str(due))
            except ValueError:
                uncertainties.append(f"Prazo “{_clip(due, 40)}” não é uma data válida: prazo a definir.")
            else:
                if _date_written(str(due), quote):
                    proposed["due_date"] = str(due)
                else:
                    uncertainties.append(f"O prazo {due} não está escrito no trecho (data relativa ou inferida): prazo a definir.")
        if step := _clip(item.get("next_step"), 300):
            proposed["next_step"] = step
        status = item.get("status")
        if status in STATUSES:
            proposed["status"] = status
        elif status:
            uncertainties.append(f"Estado “{_clip(status, 40)}” não reconhecido: ignorado.")

        evidence = [{"quote": _clip(quote, 1500), "locator": locate(quote, document)}]
        rationale = _clip(item.get("rationale"), 300)
        related = [r for r in (item.get("related_activity_ids") or []) if r in current]

        if kind == "update":
            target = str(item.get("target_activity_id") or "").strip().upper()
            if target not in current:
                notes.append(f"{label} descartado: a atividade “{target or 'sem ID'}” não existe no app (“{_clip(quote, 120)}”).")
                continue
            draft = updates.get(target)
            if draft is None:
                updates[target] = Draft("update", target, proposed, {}, evidence, rationale, uncertainties, related)
                continue
            for f, v in proposed.items():  # um item por atividade: junta mudanças da mesma atividade
                if f in draft.proposed and not same_value(f, draft.proposed[f], v):
                    draft.uncertainties.append(f"O documento traz valores diferentes para {FIELD_LABELS[f].lower()}: conferir.")
                draft.proposed.setdefault(f, v)
            draft.evidence += [e for e in evidence if e not in draft.evidence]
            draft.uncertainties += [u for u in uncertainties if u not in draft.uncertainties]
        else:
            title = _clip(item.get("title"), 200)
            if not title:
                notes.append(f"{label} descartado: criação sem título (“{_clip(quote, 120)}”).")
                continue
            duplicate = next((aid for aid, a in current.items() if same_text(a["title"], title)), None)
            if duplicate:
                notes.append(f"{label} descartado: “{title}” já existe como {duplicate}.")
                continue
            if any(same_text(c.proposed["title"], title) for c in creates):
                continue
            proposed = {"title": title, **proposed}
            if "owners" not in proposed:
                uncertainties.append("Responsável não escrito no documento: a confirmar.")
            if "due_date" not in proposed:
                uncertainties.append("Prazo não escrito no documento: a definir.")
            creates.append(Draft("create", None, proposed, {}, evidence, rationale, uncertainties, related))

    drafts: list[Draft] = []
    for target, d in updates.items():
        a = current[target]
        unchanged = [f for f in list(d.proposed) if same_value(f, a.get(f), d.proposed[f])]
        for f in unchanged:
            del d.proposed[f]
        if not d.proposed:
            notes.append(f"{target}: o documento repete o registro atual; nenhuma mudança a sugerir.")
            continue
        d.base = {f: a.get(f) for f in d.proposed}
        d.front = a.get("front")
        if not any(re.search(rf"\b{re.escape(target)}\b", e["quote"] or "") for e in d.evidence):
            # Visto em 04/10 com gemini-3.5-flash-lite: a ata de 04/10 (tarefa nova, sem ID) virou "atualizar ACT-103".
            d.alerts.append(f"O trecho não cita {target}: a IA concluiu que se trata da mesma atividade. "
                            "Confira; se for uma tarefa nova, rejeite e crie a atividade.")
        drafts.append(d)
    for d in creates:
        fronts = {by_id[m]["front"] for m in d.proposed.get("owners", [])}
        if len(fronts) == 1:
            d.front, d.front_inferred = fronts.pop(), True
            d.proposed["front"] = d.front
        # Dica para a pessoa revisora: atividades abertas da mesma pessoa podem ser a mesma tarefa.
        # (Palavras em comum no título geravam falso alarme: "Revisar…" × "Revisar…".)
        for aid, a in current.items():
            if a.get("status") == "concluida" or aid in d.related:
                continue
            if set(a.get("owners") or []) & set(d.proposed.get("owners", [])):
                d.related.append(aid)
        d.related = d.related[:3]
        drafts.append(d)
    return Validation(drafts=drafts, notes=notes)


# ---------------------------------------------------------------------------
# Gravação
# ---------------------------------------------------------------------------


def current_activities(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Valores oficiais atuais de todas as atividades (para o contexto e a validação)."""
    out = {}
    for (aid,) in conn.execute("SELECT activity_id FROM activities ORDER BY activity_id"):
        a = activities.get(conn, aid)
        snap = activities.snapshot(conn, aid)
        out[aid] = {**snap, "activity_id": aid, "owner_names": [o["display_name"] for o in a["owners"]]}
    return out


def human_decisions(conn: sqlite3.Connection, activity_id: str) -> dict[str, tuple[str, str]]:
    """Último autor humano de cada campo: {campo: (nome, data)}; importação não conta."""
    latest: dict[str, tuple[str, str, bool]] = {}
    for ev in conn.execute(
        """SELECT e.actor_id, e.ts, e.after, m.display_name FROM activity_events e
           LEFT JOIN members m ON m.member_id = e.actor_id
           WHERE e.activity_id = ? AND e.action NOT IN ('import') ORDER BY e.ts, e.event_id""",
        (activity_id,),
    ):
        for f in json.loads(ev["after"] or "{}"):
            latest[f] = (ev["display_name"] or ev["actor_id"], ev["ts"], not ev["actor_id"].startswith("sistema:"))
    return {f: (name, ts) for f, (name, ts, human) in latest.items() if human}


def _br(value: str | None) -> str:
    try:
        return datetime.fromisoformat(value).astimezone(settings.timezone).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return value or "?"


def dedupe_key(file_id: str, version: str, d: Draft) -> str:
    target = d.target_activity_id or d.proposed_id or normalize(d.proposed.get("title", ""))
    raw = json.dumps([file_id, version, d.kind, target, d.proposed], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def insert_drafts(conn: sqlite3.Connection, drafts: list[Draft], *, analysis_id: int, origin: str, source_file_id: str,
                  source_version: str, doc_date: str | None, generated_by: str) -> tuple[int, list[str]]:
    """Grava as sugestões (sem duplicar). Devolve (quantas novas, observações)."""
    notes: list[str] = []
    n = 0
    now = db.utcnow()
    source = conn.execute("SELECT name FROM sources WHERE file_id = ?", (source_file_id,)).fetchone()
    for d in drafts:
        same = _same_pending(conn, d)
        if same is not None and same["source_status"] != "unavailable":
            notes.append(f"Igual à sugestão #{same['suggestion_id']} já pendente (de outro documento ou versão): não repetida.")
            continue
        if same is not None:
            # A pendente perdeu o documento de origem (removido, lixeira, sem acesso): a nova fica no lugar.
            supersede(conn, [same["suggestion_id"]],
                      f"O documento de origem ({same['source_name']}) não está mais disponível no Drive; a mesma "
                      f"proposta veio de {source['name'] if source else 'outro documento'} e substitui esta.")
            notes.append(f"Substitui a sugestão #{same['suggestion_id']}, cujo documento ({same['source_name']}) saiu do Drive.")
        if d.target_activity_id:
            for f, (who, ts) in human_decisions(conn, d.target_activity_id).items():
                if f in d.proposed:
                    d.alerts.append(f"{FIELD_LABELS[f]} foi definido no app por {who} em {_br(ts)}; aceitar substitui essa decisão.")
        cur = conn.execute(
            """INSERT OR IGNORE INTO suggestions (analysis_id, origin, source_file_id, source_version, doc_date, kind,
                   target_activity_id, proposed_id, front, front_inferred, proposed_fields, base_fields, evidence,
                   rationale, uncertainties, alerts, related_activity_ids, generated_by, dedupe_key, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (analysis_id, origin, source_file_id, source_version, doc_date, d.kind, d.target_activity_id,
             d.proposed_id, d.front,
             int(d.front_inferred), _json(d.proposed), _json(d.base), _json(d.evidence), d.rationale,
             _json(d.uncertainties), _json(d.alerts), _json(d.related), generated_by,
             dedupe_key(source_file_id, source_version, d), now),
        )
        n += cur.rowcount
    return n, notes


def _equivalent(row: sqlite3.Row, d: Draft) -> bool:
    """Mesma proposta, mesmo que a IA tenha escrito de outro jeito (ex.: a mesma ata em .md e Google Docs)."""
    proposed = json.loads(row["proposed_fields"])
    same_quote = {flat(e["quote"] or "") for e in json.loads(row["evidence"])} == {flat(e["quote"] or "") for e in d.evidence}
    if d.kind == "update":
        same_values = set(proposed) == set(d.proposed) and all(same_value(f, proposed[f], d.proposed[f]) for f in proposed)
        return row["target_activity_id"] == d.target_activity_id and (same_values or same_quote)
    return same_text(proposed.get("title"), d.proposed.get("title")) or same_quote


def _same_pending(conn: sqlite3.Connection, d: Draft) -> sqlite3.Row | None:
    """Sugestão pendente equivalente, com a situação da fonte dela (para saber se ainda vale)."""
    for row in conn.execute(
        """SELECT s.suggestion_id, s.kind, s.target_activity_id, s.proposed_fields, s.evidence,
                  src.name AS source_name, src.sync_status AS source_status
           FROM suggestions s JOIN sources src ON src.file_id = s.source_file_id
           WHERE s.review_status = 'pendente' AND s.kind = ?""", (d.kind,)):
        if _equivalent(row, d):
            return row
    return None


def supersede(conn: sqlite3.Connection, suggestion_ids: list[int], reason: str) -> int:
    if not suggestion_ids:
        return 0
    marks = ",".join("?" * len(suggestion_ids))
    cur = conn.execute(
        f"""UPDATE suggestions SET review_status = 'substituida', review_reason = ?, reviewed_at = ?
            WHERE review_status = 'pendente' AND suggestion_id IN ({marks})""",
        (reason, db.utcnow(), *suggestion_ids),
    )
    return cur.rowcount


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Consulta e permissões
# ---------------------------------------------------------------------------


def can_review(member: sqlite3.Row | dict | None, s: dict[str, Any]) -> bool:
    """Bruno (todas as frentes) revisa tudo; Carla só a Formação; Ana e Davi não revisam."""
    if member is None:
        return False
    if member["review_scope"] == "all":
        return True
    return member["review_scope"] == "front" and bool(s.get("front")) and normalize(s["front"]) == normalize(member["front"])


def reviewers_for(members: list[sqlite3.Row], s: dict[str, Any]) -> list[str]:
    return [m["display_name"] for m in members if can_review(m, s)]


def _load(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    s = dict(row)
    for k in ("proposed_fields", "base_fields", "evidence", "uncertainties", "alerts", "related_activity_ids"):
        s[k] = json.loads(s[k] or ("{}" if k.endswith("fields") else "[]"))
    s["applied_fields"] = json.loads(s["applied_fields"]) if s["applied_fields"] else None
    target = activities.get(conn, s["target_activity_id"]) if s["target_activity_id"] else None
    s["target"] = target
    s["target_owner_ids"] = [o["member_id"] for o in target["owners"]] if target else []
    s["affected_ids"] = sorted(set(s["target_owner_ids"]) | set(s["proposed_fields"].get("owners", [])))
    if target:
        snap = activities.snapshot(conn, s["target_activity_id"])
        s["current_fields"] = {f: snap.get(f) for f in s["proposed_fields"]}
    else:
        s["current_fields"] = {}
    s["changed_since"] = [f for f in s["base_fields"] if not same_value(f, s["base_fields"][f], s["current_fields"].get(f))]
    return s


_SELECT = """SELECT s.*, src.name AS source_name, src.web_url AS source_url, src.sync_status AS source_status,
                    src.status_reason AS source_status_reason, src.content_hash AS source_current_hash,
                    m.display_name AS reviewer_name
             FROM suggestions s
             JOIN sources src ON src.file_id = s.source_file_id
             LEFT JOIN members m ON m.member_id = s.reviewer_id"""


def get(conn: sqlite3.Connection, suggestion_id: int) -> dict[str, Any] | None:
    row = conn.execute(_SELECT + " WHERE s.suggestion_id = ?", (suggestion_id,)).fetchone()
    return _load(conn, row) if row else None


def list_all(conn: sqlite3.Connection, *, pending: bool) -> list[dict[str, Any]]:
    if pending:
        rows = conn.execute(_SELECT + " WHERE s.review_status = 'pendente' ORDER BY s.created_at, s.suggestion_id")
    else:
        rows = conn.execute(_SELECT + " WHERE s.review_status != 'pendente' "
                            "ORDER BY COALESCE(s.reviewed_at, s.created_at) DESC, s.suggestion_id DESC LIMIT 30")
    return [_load(conn, r) for r in rows]


def pending_for(conn: sqlite3.Connection, member: sqlite3.Row | None) -> int:
    if member is None or member["review_scope"] == "none":
        return 0
    rows = conn.execute("SELECT front FROM suggestions WHERE review_status = 'pendente'").fetchall()
    return sum(1 for r in rows if can_review(member, dict(r)))


def pending_for_activity(conn: sqlite3.Connection, activity_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(_SELECT + " WHERE s.review_status = 'pendente' AND s.target_activity_id = ? "
                        "ORDER BY s.created_at", (activity_id,))
    return [_load(conn, r) for r in rows]


# ---------------------------------------------------------------------------
# Revisão
# ---------------------------------------------------------------------------


def is_adjusted(s: dict[str, Any], final: dict[str, Any]) -> bool:
    """A pessoa revisora mudou algum valor ou deixou de aplicar algum campo proposto?"""
    proposed = s["proposed_fields"]

    def norm(f: str, v: Any) -> Any:
        if f == "status" and s["kind"] == "create" and not v:
            return "a_fazer"
        if isinstance(v, list):
            return sorted(v) or None
        return v or None

    return any(norm(f, final.get(f)) != norm(f, proposed.get(f)) for f in set(final) | set(proposed))


@dataclass
class ReviewResult:
    status: str
    activity_id: str | None
    changed: dict[str, tuple[Any, Any]] = field(default_factory=dict)


def review(conn: sqlite3.Connection, suggestion_id: int, member: sqlite3.Row | None, action: str,
           final: dict[str, Any] | None = None, reason: str | None = None) -> ReviewResult:
    """Aceita (com ou sem ajuste) ou rejeita. Só a pessoa revisora com permissão; uma vez só."""
    if member is None:
        raise NotAllowed("Escolha no topo da página quem você é antes de revisar.")
    reason = _clip(reason, 500)
    conn.execute("BEGIN IMMEDIATE")  # duas abas aprovando ao mesmo tempo: só a primeira vale
    s = get(conn, suggestion_id)
    if s is None:
        raise LookupError("Sugestão não encontrada.")
    if s["review_status"] != "pendente":
        who = f" por {s['reviewer_name']}" if s["reviewer_name"] else ""
        raise AlreadyReviewed(
            f"Esta sugestão já está “{REVIEW_LABELS[s['review_status']][0].lower()}”{who} "
            f"({_br(s['reviewed_at'])}). Nada foi repetido.")
    if not can_review(member, s):
        raise NotAllowed(f"{member['display_name']} não pode revisar sugestões da frente "
                         f"{s['front'] or '(a confirmar)'}. Quem pode: Bruno (todas as frentes) e, na Formação, Carla.")
    if action == "aceitar" and s["source_status"] == "unavailable":
        raise SourceUnavailable(
            f"O documento de origem ({s['source_name']}) está indisponível: {s['source_status_reason'] or 'saiu do Drive'} "
            "Não dá para aceitar com base num documento que não pode ser conferido; rejeite com o motivo ou espere ele voltar.")
    self_review = int(member["member_id"] in s["affected_ids"])
    now = db.utcnow()

    if action == "rejeitar":
        if not reason or len(reason) < 3:
            raise ValueError("Escreva o motivo da rejeição.")
        conn.execute(
            """UPDATE suggestions SET review_status = 'rejeitada', reviewer_id = ?, reviewed_at = ?, review_reason = ?,
                   self_review = ? WHERE suggestion_id = ?""",
            (member["member_id"], now, reason, self_review, suggestion_id),
        )
        return ReviewResult("rejeitada", s["target_activity_id"])
    if action != "aceitar":
        raise ValueError("Ação desconhecida.")
    if not final:
        raise ValueError("Nenhum campo selecionado. Para não aplicar nada, use “Rejeitar” com o motivo.")

    status = "ajustada" if is_adjusted(s, final) else "aceita"
    source = conn.execute("SELECT name FROM sources WHERE file_id = ?", (s["source_file_id"],)).fetchone()
    what = f"sugestão #{suggestion_id} ({'ata' if s['origin'] == 'ata' else 'planilha'} {source['name']})"
    text = f"{'Aceita' if status == 'aceita' else 'Ajustada e aceita'}: {what}." + (f" Motivo: {reason}" if reason else "")
    if self_review:
        text += " Revisão feita por pessoa responsável pela atividade."
    quote = "\n".join(e["quote"] for e in s["evidence"] if e.get("quote"))
    locator = "; ".join(e["locator"] for e in s["evidence"] if e.get("locator"))
    source_args = dict(source_file_id=s["source_file_id"], source_version=s["source_version"], suggestion_id=suggestion_id)

    if s["kind"] == "update":
        activity_id = s["target_activity_id"]
        changed = activities.update(conn, activity_id, final, member["member_id"], reason=text,
                                    action="suggestion_accepted", begin=False, **source_args)
        relation = "changed_by"
    else:
        data = {"title": final.get("title") or s["proposed_fields"].get("title"), "status": final.get("status") or "a_fazer",
                **{f: final.get(f) for f in ("owners", "front", "due_date", "next_step", "priority", "notes")}}
        data["owners"] = data["owners"] or []
        activity_id = activities.create(conn, data, member["member_id"], reason=text, origin="suggestion",
                                        begin=False, requested_id=s["proposed_id"], **source_args)
        changed = {}
        relation = "created_from"
    conn.execute(
        """INSERT INTO activity_refs (activity_id, file_id, version_or_hash, locator, quote, relation_type, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (activity_id, s["source_file_id"], s["source_version"], locator or None, quote or None, relation, now),
    )
    conn.execute(
        """UPDATE suggestions SET review_status = ?, reviewer_id = ?, reviewed_at = ?, review_reason = ?,
               applied_fields = ?, result_activity_id = ?, self_review = ? WHERE suggestion_id = ?""",
        (status, member["member_id"], now, reason, _json(final), activity_id if s["kind"] == "create" else None,
         self_review, suggestion_id),
    )
    return ReviewResult(status, activity_id, changed)
