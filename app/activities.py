"""Atividades oficiais: consulta, criação e edição.

Regra central: toda mudança grava um evento no histórico com autor, hora, campos
alterados (antes/depois) e fonte. Não existe caminho de escrita que pule o evento.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from . import db

STATUSES = {
    "a_fazer": "A fazer",
    "em_andamento": "Em andamento",
    "bloqueada": "Bloqueada",
    "concluida": "Concluída",
}
PRIORITIES = ("Alta", "Média", "Baixa")
FIELDS = ("title", "owners", "front", "status", "due_date", "next_step", "priority", "description", "notes")
FIELD_LABELS = {
    "title": "Título",
    "owners": "Responsáveis",
    "front": "Frente",
    "status": "Estado",
    "due_date": "Prazo",
    "next_step": "Próximo passo",
    "priority": "Prioridade",
    "description": "Descrição",
    "notes": "Notas e bloqueios",
}
ORDERS = {
    "prazo": "CASE WHEN a.due_date IS NULL THEN 1 ELSE 0 END, a.due_date, a.activity_id",
    "bloqueios": "CASE a.status WHEN 'bloqueada' THEN 0 ELSE 1 END, "
    "CASE WHEN a.due_date IS NULL THEN 1 ELSE 0 END, a.due_date, a.activity_id",
    "sem_prazo": "CASE WHEN a.due_date IS NULL THEN 0 ELSE 1 END, a.due_date, a.activity_id",
}
DUE_FILTERS = {
    "vencidas": "Vencidas",
    "7dias": "Vencem nos próximos 7 dias",
    "sem_prazo": "Sem prazo definido",
}
ID_PREFIX = "ACT"  # padrão de ID das atividades no material ("atividades identificadas por ACT-*", INDEX.md)
IMPORT_ACTOR = "sistema:importacao"


class StaleEdit(Exception):
    """A atividade mudou depois que o formulário foi aberto."""


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------


def _owners_by_activity(conn: sqlite3.Connection, ids: list[str]) -> dict[str, list[sqlite3.Row]]:
    result: dict[str, list[sqlite3.Row]] = {i: [] for i in ids}
    if not ids:
        return result
    marks = ",".join("?" * len(ids))
    for row in conn.execute(
        f"""SELECT o.activity_id, m.* FROM activity_owners o JOIN members m ON m.member_id = o.member_id
            WHERE o.activity_id IN ({marks}) ORDER BY m.display_name""",
        ids,
    ):
        result[row["activity_id"]].append(row)
    return result


def list_activities(
    conn: sqlite3.Connection,
    today: date,
    *,
    owner: str | None = None,
    front: str | None = None,
    status: str | None = None,
    due: str | None = None,
    order: str = "prazo",
) -> list[dict[str, Any]]:
    """Lista com filtros. owner='nenhum' = sem responsável; status='abertas' = não concluídas."""
    where, args = [], []
    if owner == "nenhum":
        where.append("NOT EXISTS (SELECT 1 FROM activity_owners o WHERE o.activity_id = a.activity_id)")
    elif owner:
        where.append("EXISTS (SELECT 1 FROM activity_owners o WHERE o.activity_id = a.activity_id AND o.member_id = ?)")
        args.append(owner)
    if front == "nenhuma":
        where.append("(a.front IS NULL OR a.front = '')")
    elif front:
        where.append("a.front = ?")
        args.append(front)
    if status == "abertas":
        where.append("a.status != 'concluida'")
    elif status:
        where.append("a.status = ?")
        args.append(status)
    if due == "vencidas":
        where.append("a.status != 'concluida' AND a.due_date < ?")
        args.append(today.isoformat())
    elif due == "7dias":
        where.append("a.status != 'concluida' AND a.due_date BETWEEN ? AND ?")
        args += [today.isoformat(), (today + timedelta(days=7)).isoformat()]
    elif due == "sem_prazo":
        where.append("a.due_date IS NULL")
    sql = """SELECT a.*,
                    (SELECT COUNT(*) FROM suggestions s
                      WHERE s.target_activity_id = a.activity_id AND s.review_status = 'pendente') AS pending
             FROM activities a"""
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY " + ORDERS.get(order, ORDERS["prazo"])
    rows = [dict(r) for r in conn.execute(sql, args)]
    owners = _owners_by_activity(conn, [r["activity_id"] for r in rows])
    for r in rows:
        r["owners"] = owners[r["activity_id"]]
    return rows


def get(conn: sqlite3.Connection, activity_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM activities WHERE activity_id = ?", (activity_id,)).fetchone()
    if row is None:
        return None
    a = dict(row)
    a["owners"] = _owners_by_activity(conn, [activity_id])[activity_id]
    a["pending"] = conn.execute(
        "SELECT COUNT(*) FROM suggestions WHERE target_activity_id = ? AND review_status = 'pendente'",
        (activity_id,),
    ).fetchone()[0]
    return a


def snapshot(conn: sqlite3.Connection, activity_id: str) -> dict[str, Any] | None:
    """Valores dos campos editáveis, no formato gravado no histórico."""
    a = get(conn, activity_id)
    if a is None:
        return None
    snap = {f: a[f] for f in FIELDS if f != "owners"}
    snap["owners"] = sorted(o["member_id"] for o in a["owners"])
    return snap


def history(conn: sqlite3.Connection, activity_id: str) -> list[dict[str, Any]]:
    events = []
    for row in conn.execute(
        """SELECT e.*, m.display_name AS actor_name, s.name AS source_name, s.web_url AS source_url
           FROM activity_events e
           LEFT JOIN members m ON m.member_id = e.actor_id
           LEFT JOIN sources s ON s.file_id = e.source_file_id
           WHERE e.activity_id = ? ORDER BY e.ts DESC, e.event_id DESC""",
        (activity_id,),
    ):
        ev = dict(row)
        ev["before"] = json.loads(ev["before"]) if ev["before"] else {}
        ev["after"] = json.loads(ev["after"]) if ev["after"] else {}
        ev["fields"] = [f for f in FIELDS if f in ev["after"] or f in ev["before"]]
        events.append(ev)
    return events


def references(conn: sqlite3.Connection, activity_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT r.*, s.name AS source_name, s.web_url, s.sync_status, s.status_reason
           FROM activity_refs r JOIN sources s ON s.file_id = r.file_id
           WHERE r.activity_id = ? ORDER BY r.ref_id""",
        (activity_id,),
    ).fetchall()


def known_fronts(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """SELECT front FROM members UNION SELECT front FROM activities
           WHERE front IS NOT NULL AND front != '' ORDER BY 1"""
    ).fetchall()
    return [r[0] for r in rows]


def due_info(due_date: str | None, status: str, today: date) -> dict[str, str]:
    """Texto do prazo para a tela. Datas vencidas são sinalizadas, nunca alteradas."""
    if not due_date:
        return {"label": "A definir", "relative": "", "tone": "neutro"}
    d = date.fromisoformat(due_date)
    label = d.strftime("%d/%m/%Y")
    if status == "concluida":
        return {"label": label, "relative": "", "tone": "neutro"}
    days = (d - today).days
    if days < 0:
        return {"label": label, "relative": f"vencida há {-days} dia(s)", "tone": "erro"}
    if days == 0:
        return {"label": label, "relative": "vence hoje", "tone": "alerta"}
    if days <= 3:
        return {"label": label, "relative": f"vence em {days} dia(s)", "tone": "alerta"}
    return {"label": label, "relative": f"em {days} dias", "tone": "neutro"}


# ---------------------------------------------------------------------------
# Escrita (sempre com evento)
# ---------------------------------------------------------------------------


def record_event(
    conn: sqlite3.Connection,
    activity_id: str,
    actor_id: str,
    action: str,
    before: dict | None,
    after: dict | None,
    *,
    reason: str | None = None,
    source_file_id: str | None = None,
    source_version: str | None = None,
    suggestion_id: int | None = None,
    ts: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO activity_events (activity_id, actor_id, ts, action, before, after, reason,
               source_file_id, source_version, suggestion_id)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (activity_id, actor_id, ts or db.utcnow(), action,
         json.dumps(before, ensure_ascii=False) if before is not None else None,
         json.dumps(after, ensure_ascii=False) if after is not None else None,
         reason, source_file_id, source_version, suggestion_id),
    )


def insert(conn: sqlite3.Connection, activity_id: str, data: dict[str, Any], *, origin: str, created_by: str, now: str) -> None:
    conn.execute(
        """INSERT INTO activities (activity_id, title, description, next_step, front, status, due_date,
               priority, notes, origin, created_by, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (activity_id, data["title"], data.get("description"), data.get("next_step"), data.get("front"),
         data["status"], data.get("due_date"), data.get("priority"), data.get("notes"),
         origin, created_by, now, now),
    )
    conn.executemany(
        "INSERT INTO activity_owners (activity_id, member_id) VALUES (?, ?)",
        [(activity_id, m) for m in data.get("owners", [])],
    )


def next_manual_id(conn: sqlite3.Connection) -> str:
    """Continua a numeração ACT-* (depois de ACT-104 vem ACT-105).

    Se a planilha trouxer depois um ID que já existe no app, a linha não sobrescreve a
    atividade: vira aviso (importação) ou conflito para revisão humana.
    """
    numbers = [
        int(m.group(1))
        for (aid,) in conn.execute("SELECT activity_id FROM activities WHERE activity_id LIKE ?", (f"{ID_PREFIX}-%",))
        if (m := re.fullmatch(rf"{ID_PREFIX}-(\d+)", aid))
    ]
    return f"{ID_PREFIX}-{max(numbers, default=0) + 1:03d}"


def create(conn: sqlite3.Connection, data: dict[str, Any], actor_id: str, *, reason: str | None = None) -> str:
    """Criação manual pela interface. Devolve o ID gerado."""
    conn.execute("BEGIN IMMEDIATE")  # serializa a geração do ID
    activity_id = next_manual_id(conn)
    now = db.utcnow()
    insert(conn, activity_id, data, origin="manual", created_by=actor_id, now=now)
    record_event(conn, activity_id, actor_id, "create", None, snapshot(conn, activity_id),
                 reason=reason or "Criação manual na aplicação", ts=now)
    return activity_id


def update(
    conn: sqlite3.Connection,
    activity_id: str,
    changes: dict[str, Any],
    actor_id: str,
    *,
    expected_updated_at: str | None = None,
    reason: str | None = None,
    action: str = "update",
) -> dict[str, tuple[Any, Any]]:
    """Aplica só os campos que mudaram. Devolve {campo: (antes, depois)}; vazio = nada mudou."""
    conn.execute("BEGIN IMMEDIATE")
    current = get(conn, activity_id)
    if current is None:
        raise KeyError(activity_id)
    if expected_updated_at and current["updated_at"] != expected_updated_at:
        raise StaleEdit(activity_id)
    before_all = snapshot(conn, activity_id)
    diff = {f: (before_all[f], changes[f]) for f in FIELDS if f in changes and before_all[f] != changes[f]}
    if not diff:
        return {}
    now = db.utcnow()
    columns = [f for f in diff if f != "owners"]
    if columns:
        conn.execute(
            f"UPDATE activities SET {', '.join(f'{c} = ?' for c in columns)}, updated_at = ? WHERE activity_id = ?",
            [diff[c][1] for c in columns] + [now, activity_id],
        )
    else:
        conn.execute("UPDATE activities SET updated_at = ? WHERE activity_id = ?", (now, activity_id))
    if "owners" in diff:
        conn.execute("DELETE FROM activity_owners WHERE activity_id = ?", (activity_id,))
        conn.executemany(
            "INSERT INTO activity_owners (activity_id, member_id) VALUES (?, ?)",
            [(activity_id, m) for m in diff["owners"][1]],
        )
    record_event(conn, activity_id, actor_id, action,
                 {f: b for f, (b, _) in diff.items()}, {f: a for f, (_, a) in diff.items()},
                 reason=reason, ts=now)
    return diff


# ---------------------------------------------------------------------------
# Formulário
# ---------------------------------------------------------------------------


@dataclass
class FormResult:
    data: dict[str, Any]
    errors: dict[str, str]
    reason: str | None


def _clean(value: Any, limit: int, multiline: bool = False) -> str | None:
    text = str(value or "")
    if multiline:
        text = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").strip().split("\n"))
    else:
        text = " ".join(text.split())
    return text[:limit] or None


def parse_form(form: Any, member_ids: set[str]) -> FormResult:
    """Valida o formulário de criação/edição. `form` é o FormData do Starlette."""
    errors: dict[str, str] = {}
    data: dict[str, Any] = {
        "title": _clean(form.get("title"), 200),
        "description": _clean(form.get("description"), 4000, multiline=True),
        "next_step": _clean(form.get("next_step"), 300),
        "front": _clean(form.get("front"), 80),
        "status": form.get("status") or "a_fazer",
        "due_date": (form.get("due_date") or "").strip() or None,
        "priority": form.get("priority") or None,
        "notes": _clean(form.get("notes"), 4000, multiline=True),
        "owners": sorted(set(form.getlist("owners"))),
    }
    if not data["title"]:
        errors["title"] = "Informe um título."
    if data["status"] not in STATUSES:
        errors["status"] = "Escolha um estado da lista."
    if data["priority"] not in (None, *PRIORITIES):
        errors["priority"] = "Escolha uma prioridade da lista."
    if data["due_date"]:
        try:
            date.fromisoformat(data["due_date"])
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["due_date"]):
                raise ValueError
        except ValueError:
            errors["due_date"] = "Use uma data válida (dia/mês/ano) ou deixe em branco para “a definir”."
    unknown = [m for m in data["owners"] if m not in member_ids]
    if unknown:
        errors["owners"] = "Responsável desconhecido."
    return FormResult(data=data, errors=errors, reason=_clean(form.get("reason"), 300))
