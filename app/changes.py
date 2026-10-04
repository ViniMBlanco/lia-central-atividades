"""Novidades: "o que mudou para mim" (resumo pessoal) e a linha do tempo dos documentos.

Tudo vem dos registros do banco, com link para a atividade, a sugestão ou o documento no
Drive. Nada é deduzido, e cada coisa fica no seu grupo:
- confirmado = evento no histórico de uma atividade (só existe com autor);
- proposto = sugestão pendente (ainda não vale) ou revisada sem mudar nada (rejeitada);
- incerto = prazo ou responsável a definir, fonte indisponível, ponto a conferir numa
  sugestão, conflito de fonte aberto, ata ainda sem análise, leitura do Drive com falha;
- atenção = atividades da pessoa bloqueadas, vencidas ou vencendo em até 7 dias.

Marco temporal: a última vez que a pessoa clicou em "Marcar como visto" ou um período
escolhido. Abrir a página não grava visita (recarregar não apaga o resumo).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from . import activities, analysis, conflicts, db, suggestions
from .activities import FIELD_LABELS, FIELDS, STATUSES
from .authority import normalize

PERIODS = {
    "marca": "Desde a sua última visita marcada",
    "24h": "Últimas 24 horas",
    "7d": "Últimos 7 dias",
    "tudo": "Desde o início",
}
_DELTAS = {"24h": timedelta(days=1), "7d": timedelta(days=7)}
ATTENTION_DAYS = 7

EVENT_LABELS = {
    "import": "Importada da planilha",
    "create": "Criada na aplicação",
    "update": "Editada na aplicação",
    "suggestion_accepted": "Sugestão aceita",
}


# ---------------------------------------------------------------------------
# Marco temporal
# ---------------------------------------------------------------------------


@dataclass
class Period:
    key: str
    since: str | None  # ISO/UTC; None = desde o início
    last_visit: str | None

    @property
    def label(self) -> str:
        return PERIODS[self.key]


def last_visit(conn: sqlite3.Connection, member_id: str) -> str | None:
    row = conn.execute("SELECT last_seen_at FROM visits WHERE member_id = ?", (member_id,)).fetchone()
    return row["last_seen_at"] if row else None


def mark_visit(conn: sqlite3.Connection, member_id: str) -> str:
    now = db.utcnow()
    conn.execute(
        """INSERT INTO visits (member_id, last_seen_at) VALUES (?, ?)
           ON CONFLICT(member_id) DO UPDATE SET last_seen_at = excluded.last_seen_at""",
        (member_id, now),
    )
    return now


def resolve_period(conn: sqlite3.Connection, member: sqlite3.Row | None, requested: str | None) -> Period:
    """Período pedido; sem pedido: desde a última visita marcada ou, se não houver, desde o início."""
    visit = last_visit(conn, member["member_id"]) if member else None
    key = requested if requested in PERIODS else ("marca" if visit else "tudo")
    if key == "marca" and not visit:
        key = "tudo"
    if key == "marca":
        since = visit
    elif key in _DELTAS:
        since = (datetime.now(timezone.utc) - _DELTAS[key]).isoformat(timespec="seconds")
    else:
        since = None
    return Period(key, since, visit)


def _after(ts: str | None, since: str | None) -> bool:
    return bool(ts) and (since is None or ts > since)


# ---------------------------------------------------------------------------
# O que mudou para mim
# ---------------------------------------------------------------------------


def _owners(conn: sqlite3.Connection) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for r in conn.execute("SELECT activity_id, member_id FROM activity_owners"):
        out.setdefault(r["activity_id"], set()).add(r["member_id"])
    return out


def _confirmed(conn: sqlite3.Connection, member_id: str, since: str | None) -> tuple[list[dict], list[dict]]:
    """Eventos do histórico nas atividades da pessoa (responsável agora, antes ou depois do evento)."""
    owners = _owners(conn)
    rows = conn.execute(
        """SELECT e.*, a.title, m.display_name AS actor_name, s.name AS source_name, s.web_url AS source_url,
                  s.sync_status AS source_status
           FROM activity_events e JOIN activities a ON a.activity_id = e.activity_id
           LEFT JOIN members m ON m.member_id = e.actor_id
           LEFT JOIN sources s ON s.file_id = e.source_file_id
           WHERE (? IS NULL OR e.ts > ?) ORDER BY e.ts DESC, e.event_id DESC""",
        (since, since),
    ).fetchall()
    changes, imported = [], []
    for r in rows:
        ev = dict(r)
        before = json.loads(ev["before"]) if ev["before"] else {}
        after = json.loads(ev["after"]) if ev["after"] else {}
        was, now = member_id in (before.get("owners") or []), member_id in (after.get("owners") or [])
        if member_id not in owners.get(ev["activity_id"], set()) and not was and not now:
            continue
        if ev["action"] == "import":
            imported.append(ev)
            continue
        if ev["action"] == "create":
            ev["fields"] = [(f, None, after.get(f)) for f in ("owners", "due_date", "status", "next_step", "front") if after.get(f)]
        else:
            ev["fields"] = [(f, before.get(f), after.get(f)) for f in FIELDS if f in before or f in after]
        ev["became_owner"] = now and not was and ev["action"] != "create"
        ev["left_owner"] = was and not now
        ev["by_me"] = ev["actor_id"] == member_id
        ev["label"] = ("Criada a partir de sugestão" if ev["action"] == "create" and ev["suggestion_id"]
                       else EVENT_LABELS.get(ev["action"], ev["action"]))
        changes.append(ev)
    imported.sort(key=lambda ev: ev["activity_id"])
    return changes, imported


def personal(conn: sqlite3.Connection, member: sqlite3.Row, period: Period, today: date,
             health: dict[str, Any] | None = None) -> dict[str, Any]:
    member_id = member["member_id"]
    since = period.since
    confirmed, imported = _confirmed(conn, member_id, since)

    members = conn.execute("SELECT * FROM members ORDER BY display_name").fetchall()
    pending_all = suggestions.list_all(conn, pending=True)
    pending = [s for s in pending_all if member_id in s["affected_ids"]]
    for s in pending:
        s["is_new"] = _after(s["created_at"], since)
        s["reviewers"] = suggestions.reviewers_for(members, s)
        s["i_can_review"] = suggestions.can_review(member, s)
    to_review = [s for s in pending_all if suggestions.can_review(member, s) and s not in pending]
    closed = [s for s in suggestions.list_all(conn, pending=False)
              if s["review_status"] == "rejeitada" and member_id in s["affected_ids"] and _after(s["reviewed_at"], since)]

    mine = activities.list_activities(conn, today, owner=member_id, status="abertas", order="prazo")
    attention = []
    for a in mine:
        info = activities.due_info(a["due_date"], a["status"], today)
        days = (date.fromisoformat(a["due_date"]) - today).days if a["due_date"] else None
        if a["status"] == "bloqueada" or (days is not None and days <= ATTENTION_DAYS):
            attention.append({**a, "due": info})

    uncertain: list[dict[str, Any]] = []
    for a in mine:
        if not a["due_date"]:
            uncertain.append({"text": f"{a['activity_id']} ({a['title']}): prazo a definir — não está registrado.",
                              "href": f"/atividades/{a['activity_id']}"})
        if a["stale_sources"]:
            uncertain.append({"text": f"{a['activity_id']} ({a['title']}): documento de origem indisponível no Drive; "
                                      "os dados são o último estado confirmado e podem estar desatualizados.",
                              "href": f"/atividades/{a['activity_id']}"})
    for a in activities.list_activities(conn, today, owner="nenhum", status="abertas"):
        if (a["front"] or "").casefold() == member["front"].casefold():
            uncertain.append({"text": f"{a['activity_id']} ({a['title']}), da sua frente: responsável a confirmar.",
                              "href": f"/atividades/{a['activity_id']}"})
    for s in pending:
        points = s["alerts"] + s["uncertainties"]
        if s["source_status"] == "unavailable":
            points.append(f"o documento de origem ({s['source_name']}) está indisponível no Drive")
        for p in points:
            uncertain.append({"text": f"Proposta #{s['suggestion_id']} ({_subject(s)}): {p}", "href": f"/sugestoes/{s['suggestion_id']}"})
    for c in conflicts.list_conflicts(conn):
        if c["status"] == "aberto":
            uncertain.append({"text": f"Conflito de fonte aguardando decisão humana: {c['description']}",
                              "href": "/sincronizacao#conflitos"})
    for w in analysis.waiting(conn):
        reason = f" ({w['error']})" if w["error"] else ""
        uncertain.append({"text": f"A ata {w['name']} ainda não foi analisada{reason}: pode haver propostas sobre "
                                  "as suas atividades que ainda não apareceram.", "href": "/sugestoes#analises"})
    if health and (health.get("error") or health.get("stale")):
        uncertain.append({"text": "A última leitura do Drive falhou ou está atrasada: mudanças recentes nos documentos "
                                  "podem não aparecer aqui.", "href": "/sincronizacao"})

    nothing_changed = not confirmed and not any(s["is_new"] for s in pending) and not closed
    return {
        "member": member, "period": period, "confirmed": confirmed, "imported": imported,
        "pending": pending, "closed": closed, "to_review": to_review, "uncertain": uncertain,
        "attention": attention, "open_count": len(mine), "nothing_changed": nothing_changed,
    }


def _subject(s: dict[str, Any]) -> str:
    return s["target_activity_id"] if s["kind"] == "update" else f"criar “{s['proposed_fields'].get('title')}”"


def counts(p: dict[str, Any]) -> dict[str, int]:
    return {"confirmed": len(p["confirmed"]), "pending": len(p["pending"]),
            "new_pending": sum(1 for s in p["pending"] if s["is_new"]), "uncertain": len(p["uncertain"]),
            "attention": len(p["attention"]), "to_review": len(p["to_review"])}


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " e " + parts[-1]


def headline(p: dict[str, Any], fmt_ts: Callable[[str | None], str]) -> list[str]:
    """Resumo curto, sem IA: a primeira frase diz o que mudou (ou que nada mudou); as outras, o que pede atenção."""
    name, period = p["member"]["display_name"], p["period"]
    since = f"desde {fmt_ts(period.since)}" if period.since else "desde o início"
    if p["nothing_changed"]:
        first = f"Nada mudou nas atividades de {name} {since}."
    else:
        c, new, rejected = len(p["confirmed"]), sum(1 for s in p["pending"] if s["is_new"]), len(p["closed"])
        parts = [f"{c} mudança(s) confirmada(s)" if c else "nenhuma mudança confirmada"]
        if new:
            parts.append(f"{new} proposta(s) nova(s) aguardando revisão")
        if rejected:
            parts.append(f"{rejected} proposta(s) rejeitada(s)")
        first = _join(parts) + f" {since}."
        first = first[0].upper() + first[1:]
    out = [first]
    older = sum(1 for s in p["pending"] if not s["is_new"])
    if older:
        out.append(f"{older} proposta(s) de antes desse período segue(m) aguardando revisão.")
    if p["attention"]:
        out.append(f"{len(p['attention'])} atividade(s) com prazo em até {ATTENTION_DAYS} dias ou bloqueada(s).")
    if p["uncertain"]:
        out.append(f"{len(p['uncertain'])} dado(s) incerto(s) ou em conflito.")
    return out


# ---------------------------------------------------------------------------
# Parágrafo escrito pela IA: só a partir dos itens acima, e conferido
# ---------------------------------------------------------------------------

_HEDGE = re.compile(r"propost|sugest|pendente|aguard|revis|ainda nao|aprovad|aprovac|nao vale|nao foi", re.IGNORECASE)


def facts(p: dict[str, Any], fmt_value: Callable[[Any, str], str], fmt_ts: Callable[[str | None], str],
          today: date) -> dict[str, Any]:
    """O que vai para a IA: só os itens já mostrados na tela (nada de texto de documento além das evidências)."""
    def fields(items, create):
        return [f"{FIELD_LABELS[f]}: {fmt_value(after, f)}" if create
                else f"{FIELD_LABELS[f]}: {fmt_value(before, f)} → {fmt_value(after, f)}" for f, before, after in items]

    period = p["period"]
    return {
        "pessoa": p["member"]["display_name"],
        "periodo": f"{period.label} ({fmt_ts(period.since)})" if period.since else period.label,
        "hoje": today.strftime("%d/%m/%Y"),
        "mudancas_confirmadas": [{
            "atividade": f"{ev['activity_id']} — {ev['title']}", "tipo": ev["label"],
            "quem": ev["actor_name"] or ev["actor_id"], "quando": fmt_ts(ev["ts"]),
            "campos": fields(ev["fields"], ev["action"] == "create"),
            "fonte": ev["source_name"] or "edição na aplicação"} for ev in p["confirmed"]],
        "propostas_pendentes": [{
            "proposta": f"#{s['suggestion_id']}", "sobre": _subject(s),
            "campos": fields([(f, s["base_fields"].get(f), v) for f, v in s["proposed_fields"].items()], s["kind"] == "create"),
            "fonte": s["source_name"], "aguarda_revisao_de": " ou ".join(s["reviewers"]) or "Bruno"} for s in p["pending"]],
        "propostas_rejeitadas": [{
            "proposta": f"#{s['suggestion_id']}", "sobre": _subject(s), "rejeitada_por": s["reviewer_name"],
            "motivo": s["review_reason"]} for s in p["closed"]],
        "prazos_e_bloqueios": [{
            "atividade": f"{a['activity_id']} — {a['title']}",
            "prazo": a["due"]["label"] + (f" ({a['due']['relative']})" if a["due"]["relative"] else ""),
            "estado": STATUSES[a["status"]], **({"bloqueio": a["notes"]} if a["status"] == "bloqueada" and a["notes"] else {}),
        } for a in p["attention"]],
        "incertezas": [u["text"] for u in p["uncertain"]],
    }


def facts_hash(f: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(f, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _dates(text: str) -> set[tuple[int, int]]:
    """(dia, mês) de cada data escrita: 07/10, 07/10/2026, 2026-10-07, 7 de outubro."""
    found = {(int(d), int(m)) for d, m in re.findall(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/\d{2,4})?(?![\d/])", text)}
    found |= {(int(d), int(m)) for _, m, d in re.findall(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)}
    months = "|".join(suggestions.MONTHS)
    found |= {(int(d), suggestions.MONTHS.index(m) + 1) for d, m in re.findall(rf"\b(\d{{1,2}})o? de ({months})\b", normalize(text))}
    return found


def check_summary(text: str, f: dict[str, Any], member_names: list[str]) -> list[str]:
    """Problemas do parágrafo; vazio = pode ser mostrado. Qualquer problema descarta o parágrafo inteiro."""
    problems: list[str] = []
    if not text.strip():
        return ["a IA devolveu um texto vazio"]
    if len(text) > 1200:
        problems.append("o texto passou de 1.200 caracteres (pedido: de 2 a 4 frases)")
    everything = json.dumps(f, ensure_ascii=False)
    for act in sorted(set(re.findall(r"\bACT-\d+\b", text)) - set(re.findall(r"\bACT-\d+\b", everything))):
        problems.append(f"cita {act}, que não está nos itens")
    known_dates = _dates(everything)
    for d, m in sorted(_dates(text) - known_dates, key=lambda x: (x[1], x[0])):
        problems.append(f"cita a data {d:02d}/{m:02d}, que não está nos itens")
    flat = normalize(everything)
    for name in member_names:
        if re.search(rf"\b{re.escape(normalize(name))}\b", normalize(text)) and not re.search(rf"\b{re.escape(normalize(name))}\b", flat):
            problems.append(f"cita {name}, que não aparece nos itens")
    # Valor que só existe numa proposta pendente não pode aparecer como se já valesse.
    rest = {k: v for k, v in f.items() if k != "propostas_pendentes"}
    proposed_only = _dates(json.dumps(f["propostas_pendentes"], ensure_ascii=False)) - _dates(json.dumps(rest, ensure_ascii=False))
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        hits = _dates(sentence) & proposed_only
        if hits and not _HEDGE.search(normalize(sentence)):
            d, m = sorted(hits)[0]
            problems.append(f"apresenta {d:02d}/{m:02d}, que só existe numa proposta pendente, como se já valesse")
    return problems


def get_summary(conn: sqlite3.Connection, member_id: str, h: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM personal_summaries WHERE member_id = ? AND facts_hash = ?", (member_id, h)).fetchone()


def save_summary(conn: sqlite3.Connection, member_id: str, h: str, status: str, text: str | None, notes: list[str],
                 generated_by: str, raw: Any = None) -> None:
    conn.execute(
        """INSERT INTO personal_summaries (member_id, facts_hash, status, text, notes, generated_by, tokens_in, tokens_out,
               duration_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(member_id, facts_hash) DO UPDATE SET status = excluded.status, text = excluded.text,
               notes = excluded.notes, generated_by = excluded.generated_by, tokens_in = excluded.tokens_in,
               tokens_out = excluded.tokens_out, duration_ms = excluded.duration_ms, created_at = excluded.created_at""",
        (member_id, h, status, text, json.dumps(notes, ensure_ascii=False), generated_by,
         getattr(raw, "tokens_in", None), getattr(raw, "tokens_out", None), getattr(raw, "duration_ms", None), db.utcnow()),
    )


# ---------------------------------------------------------------------------
# Novidades dos documentos (linha do tempo por arquivo)
# ---------------------------------------------------------------------------

_SOURCE_EVENTS = {
    "renomeado": ("Renomeado", "neutro"),
    "movido": ("Movido dentro da pasta", "neutro"),
    "indisponivel": ("Ficou indisponível", "alerta"),
    "voltou": ("Voltou a ficar disponível", "ok"),
    "falhou": ("Falha ao ler", "erro"),
}


def generator_label(label: str) -> str:
    """Quem gerou as sugestões, como na tela de sugestões."""
    if label.startswith("gemini:"):
        return f"IA (Gemini, {label[7:]})"
    return "comparação com a versão anterior (sem IA)" if label == "comparacao" else "regras simples (sem IA)"


def document_feed(conn: sqlite3.Connection, since: str | None) -> list[dict[str, Any]]:
    """Documentos com alguma novidade no período, cada um com seus acontecimentos em ordem."""
    sources = {r["file_id"]: r for r in conn.execute("SELECT * FROM sources")}
    feed: dict[str, dict[str, Any]] = {}

    def add(file_id: str, ts: str, title: str, detail: str | None = None, tone: str = "neutro",
            links: list[tuple[str, str]] | None = None) -> None:
        if file_id not in sources or not _after(ts, since):
            return
        entry = feed.setdefault(file_id, {"source": sources[file_id], "events": []})
        entry["events"].append({"ts": ts, "title": title, "detail": detail, "tone": tone, "links": links or []})

    for s in sources.values():
        if s["sync_status"] == "ignored":
            add(s["file_id"], s["first_seen_at"], "Apareceu na pasta", f"Formato ainda não processado: {s['status_reason']}")
        else:
            add(s["file_id"], s["first_seen_at"], "Apareceu na pasta", s["authority_reason"])
    first_version: dict[str, int] = {}
    for v in conn.execute("SELECT version_id, file_id, content_hash, processed_at, name_at_version FROM source_versions ORDER BY version_id"):
        if v["file_id"] not in first_version:
            first_version[v["file_id"]] = v["version_id"]
            continue
        add(v["file_id"], v["processed_at"], "Conteúdo alterado no Drive",
            f"Nova versão lida (versão {v['content_hash'][:8]}); a mesma fonte, sem documento duplicado.")
    for e in conn.execute("SELECT * FROM source_events ORDER BY event_id"):
        title, tone = _SOURCE_EVENTS[e["kind"]]
        add(e["file_id"], e["ts"], title, e["detail"], tone)

    for a in conn.execute("SELECT * FROM analyses ORDER BY analysis_id"):
        made = conn.execute("SELECT suggestion_id FROM suggestions WHERE analysis_id = ? ORDER BY suggestion_id",
                            (a["analysis_id"],)).fetchall()
        links = [(f"sugestão #{r['suggestion_id']}", f"/sugestoes/{r['suggestion_id']}") for r in made]
        who = generator_label("comparacao" if a["origin"] == "planilha" else a["generated_by"])
        if a["status"] == "ok":
            notes = json.loads(a["notes"] or "[]")
            detail = f"{a['n_suggestions']} sugestão(ões) nova(s) para revisão." + (f" {len(notes)} observação(ões) da validação." if notes else "")
            add(a["file_id"], a["updated_at"], f"Analisado por {who}", detail, "info", links)
        else:
            add(a["file_id"], a["updated_at"], "Análise falhou", f"{a['error']} Nada foi concluído a partir desta versão.", "erro")

    for s in conn.execute(
        """SELECT s.*, m.display_name AS reviewer_name FROM suggestions s LEFT JOIN members m ON m.member_id = s.reviewer_id
           WHERE s.review_status != 'pendente' ORDER BY s.reviewed_at"""
    ):
        link = [(f"sugestão #{s['suggestion_id']}", f"/sugestoes/{s['suggestion_id']}")]
        target = s["result_activity_id"] or s["target_activity_id"]
        if target:
            link.append((target, f"/atividades/{target}"))
        if s["review_status"] in ("aceita", "ajustada"):
            verb = "aceita" if s["review_status"] == "aceita" else "ajustada e aceita"
            what = f"virou a atividade {target}" if s["kind"] == "create" else f"{target} atualizada"
            add(s["source_file_id"], s["reviewed_at"], f"Sugestão #{s['suggestion_id']} {verb} por {s['reviewer_name']}", f"{what}.", "ok", link)
        elif s["review_status"] == "rejeitada":
            add(s["source_file_id"], s["reviewed_at"], f"Sugestão #{s['suggestion_id']} rejeitada por {s['reviewer_name']}",
                f"Motivo: {s['review_reason']}. Nenhuma atividade mudou.", "neutro", link)
        else:
            add(s["source_file_id"], s["reviewed_at"], f"Sugestão #{s['suggestion_id']} substituída", s["review_reason"], "neutro", link)

    for c in conn.execute(
        """SELECT c.*, m.display_name AS resolver_name FROM conflicts c LEFT JOIN members m ON m.member_id = c.resolved_by
           WHERE c.file_id IS NOT NULL"""
    ):
        kind = conflicts.KIND_LABELS.get(c["kind"], c["kind"])
        add(c["file_id"], c["created_at"], "Conflito de fonte aberto", f"{kind}: {c['description']}", "alerta",
            [("ver conflitos", "/sincronizacao#conflitos")])
        if c["status"] == "resolvido":
            add(c["file_id"], c["closed_at"], f"Conflito decidido por {c['resolver_name'] or c['resolved_by']}", c["resolution"], "ok")
        elif c["status"] == "superado":
            add(c["file_id"], c["closed_at"], "Conflito superado", "A situação deixou de existir (o arquivo saiu da pasta ou mudou).")

    imported = conn.execute("SELECT * FROM register_import WHERE id = 1").fetchone()
    if imported:
        add(imported["file_id"], imported["imported_at"], "Atividades importadas",
            f"{imported['n_imported']} atividade(s) da aba {imported['sheet_name']}: a partir daqui, o app é a referência oficial.", "ok",
            [("ver todas as atividades", "/atividades")])
    for sw in conn.execute(
        """SELECT s.*, m.display_name FROM register_switches s LEFT JOIN members m ON m.member_id = s.decided_by"""
    ):
        add(sw["to_file_id"], sw["decided_at"], f"Passou a ser a fonte das atividades (decisão de {sw['display_name']})",
            f"{sw['n_suggestions']} diferença(s) com o app viraram sugestões.", "info")

    out = list(feed.values())
    for entry in out:
        entry["events"].sort(key=lambda e: e["ts"])
        entry["last"] = entry["events"][-1]["ts"]
    out.sort(key=lambda e: e["last"], reverse=True)
    return out
