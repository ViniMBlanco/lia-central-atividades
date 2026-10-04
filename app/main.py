"""Aplicação web (FastAPI + Jinja2). Execute com:  python -m app"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import activities, analysis, conflicts, db, google_auth, importer, suggestions, sync
from .activities import DUE_FILTERS, FIELD_LABELS, ORDERS, PRIORITIES, STATUSES, StaleEdit
from .authority import AUTHORITY_LABELS
from .config import Settings, settings

log = logging.getLogger(__name__)
APP_DIR = Path(__file__).resolve().parent

KIND_LABELS = {
    "markdown": "Markdown",
    "text": "Texto",
    "xlsx": "Planilha .xlsx",
    "gdoc": "Google Docs",
    "gsheet": "Google Planilhas",
    "": "Não suportado",
}
STATUS_LABELS = {
    "processed": ("Processado", "ok"),
    "failed": ("Falhou", "erro"),
    "ignored": ("Ignorado", "neutro"),
    "unavailable": ("Indisponível", "alerta"),
    "pending": ("Pendente", "neutro"),
}


# ---------------------------------------------------------------------------
# Datas: registro em ISO/UTC, exibição em America/Sao_Paulo
# ---------------------------------------------------------------------------


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fmt_dt(value: str | None) -> str:
    dt = _parse(value)
    return dt.astimezone(settings.timezone).strftime("%d/%m/%Y %H:%M") if dt else "—"


def fmt_date(value: str | None) -> str:
    """AAAA-MM-DD → DD/MM/AAAA (prazos não têm hora nem fuso)."""
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y") if value else ""
    except ValueError:
        return value or ""


def today() -> date:
    return datetime.now(settings.timezone).date()


def fmt_field(value: Any, field: str, names: dict[str, str]) -> str:
    """Valor de um campo de atividade como aparece na tela e no histórico."""
    if value in (None, "", []):
        return {"owners": "a confirmar", "due_date": "a definir", "front": "a confirmar"}.get(field, "—")
    if field == "status":
        return STATUSES.get(value, value)
    if field == "due_date":
        return fmt_date(value)
    if field == "owners":
        return ", ".join(names.get(m, m) for m in value)
    return str(value)


def fmt_ago(value: str | None) -> str:
    dt = _parse(value)
    if not dt:
        return ""
    seconds = int((datetime.now(timezone.utc) - dt).total_seconds())
    if seconds < 60:
        return "agora há pouco"
    if seconds < 3600:
        return f"há {seconds // 60} min"
    if seconds < 86400:
        return f"há {seconds // 3600} h"
    return f"há {seconds // 86400} dia(s)"


templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.filters["dt"] = fmt_dt
templates.env.filters["ago"] = fmt_ago
templates.env.filters["data"] = fmt_date
templates.env.filters["campo"] = fmt_field
templates.env.globals.update(
    KIND_LABELS=KIND_LABELS,
    STATUS_LABELS=STATUS_LABELS,
    STATUSES=STATUSES,
    FIELD_LABELS=FIELD_LABELS,
    PRIORITIES=PRIORITIES,
    DUE_FILTERS=DUE_FILTERS,
    AUTHORITY_LABELS=AUTHORITY_LABELS,
    CONFLICT_KINDS=conflicts.KIND_LABELS,
    CONFLICT_DECISIONS=conflicts.DECISIONS,
    REVIEW_LABELS=suggestions.REVIEW_LABELS,
    IMPORT_ACTOR=activities.IMPORT_ACTOR,
    due=lambda a: activities.due_info(a["due_date"], a["status"], today()),
)


# ---------------------------------------------------------------------------
# Ciclo de vida: banco + sincronização automática periódica
# ---------------------------------------------------------------------------


def retry_delay(interval: int, failures: int) -> int:
    """Espera até a próxima verificação: o intervalo normal, ou menos depois de falhas
    (30 s, 1, 2, 4 min…), sem nunca passar do intervalo normal."""
    if failures <= 0:
        return interval
    return min(interval, 30 * 2 ** (failures - 1))


async def _auto_sync_loop(cfg: Settings) -> None:
    """Primeira verificação ao iniciar; depois a cada intervalo, com nova tentativa mais cedo se falhar."""
    delay, failures, trigger = 0, 0, "startup"
    while True:
        sync.next_auto_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(timespec="seconds")
        await asyncio.sleep(delay)
        if google_auth.is_connected(cfg) and not sync.is_running():
            try:
                result = await asyncio.to_thread(sync.run_sync, cfg, trigger)
            except Exception:  # noqa: BLE001 — o ciclo nunca pode morrer
                log.exception("Erro no ciclo de sincronização automática")
                failures += 1
            else:
                if result is not None:
                    failures = 0 if result.ok else failures + 1
        trigger = "auto"
        delay = retry_delay(cfg.sync_interval_seconds, failures)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db(settings.database_path)
    task = None
    if settings.sync_interval_seconds > 0:
        task = asyncio.create_task(_auto_sync_loop(settings))
    try:
        yield
    finally:
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="LIA — Central de contexto e atividades", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key or secrets.token_urlsafe(32),  # sem chave: sessão vale até reiniciar
    session_cookie="lia_sessao",
    same_site="lax",
    https_only=False,
)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


def _flash(request: Request, message: str, kind: str = "info") -> None:
    request.session.setdefault("flash", []).append({"message": message, "kind": kind})


def _me(request: Request, conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Usuário de demonstração escolhido nesta sessão (não é login: ver README)."""
    member_id = request.session.get("member_id")
    if not member_id:
        return None
    return conn.execute("SELECT * FROM members WHERE member_id = ?", (member_id,)).fetchone()


def _sync_health(conn: sqlite3.Connection) -> dict[str, Any]:
    """Última leitura confirmada do Drive e se ela pode estar desatualizada (aparece em todas as telas)."""
    state = conn.execute("SELECT * FROM sync_state WHERE folder_id=?", (settings.drive_folder_id,)).fetchone()
    has_sources = conn.execute("SELECT 1 FROM sources LIMIT 1").fetchone() is not None
    stale = False
    if has_sources and settings.sync_interval_seconds > 0:
        last_success = _parse(state["last_success_at"]) if state else None
        limit = timedelta(seconds=settings.sync_interval_seconds * 2 + 60)
        stale = last_success is None or datetime.now(timezone.utc) - last_success > limit
    return {
        "state": state,
        "error": state["last_error"] if state else None,
        "stale": stale,
        "last_success_at": state["last_success_at"] if state else None,
    }


def render(request: Request, template: str, active: str, status_code: int = 200, **ctx) -> HTMLResponse:
    flashes = request.session.pop("flash", [])
    with db.session(settings.database_path) as conn:
        members = conn.execute("SELECT * FROM members ORDER BY display_name").fetchall()
        health = _sync_health(conn)
        me = next((m for m in members if m["member_id"] == request.session.get("member_id")), None)
        to_review = suggestions.pending_for(conn, me)
    return templates.TemplateResponse(
        request,
        template,
        {
            "active": active,
            "flashes": flashes,
            "members": members,
            "member_names": {m["member_id"]: m["display_name"] for m in members},
            "me": me,
            "menu_to_review": to_review,
            "health": health,
            **ctx,
        },
        status_code=status_code,
    )


def _local_path(target: str | None) -> str:
    """Só redireciona para caminhos deste app (evita redirecionamento aberto)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------

PLACEHOLDERS = {
    "/": ("comece", "Comece aqui"),
    "/novidades": ("novidades", "Novidades dos documentos"),
}


def _placeholder(path: str):
    key, title = PLACEHOLDERS[path]

    async def page(request: Request):
        return render(request, "placeholder.html", key, title=title)

    return page


for _path in PLACEHOLDERS:
    app.add_api_route(_path, _placeholder(_path), methods=["GET"], response_class=HTMLResponse)


# ---------------------------------------------------------------------------
# Usuário de demonstração
# ---------------------------------------------------------------------------


@app.post("/usuario")
async def switch_user(request: Request):
    form = await request.form()
    member_id = str(form.get("member_id") or "")
    with db.session(settings.database_path) as conn:
        member = conn.execute("SELECT * FROM members WHERE member_id = ?", (member_id,)).fetchone()
    if member:
        request.session["member_id"] = member["member_id"]
        _flash(request, f"Agora você está vendo o app como {member['display_name']} ({member['front']}).", "ok")
    else:
        request.session.pop("member_id", None)
    return RedirectResponse(_local_path(str(form.get("next") or "")), status_code=303)


# ---------------------------------------------------------------------------
# Atividades
# ---------------------------------------------------------------------------


def _register_info(conn: sqlite3.Connection) -> dict[str, Any]:
    """De onde vieram as atividades e se a fonte mudou depois (aparece nas listas)."""
    imported = conn.execute(
        """SELECT r.*, s.web_url, s.sync_status FROM register_import r
           LEFT JOIN sources s ON s.file_id = r.file_id WHERE r.id = 1"""
    ).fetchone()
    status = conn.execute("SELECT * FROM register_status WHERE id = 1").fetchone()
    warnings = json.loads(imported["warnings"]) if imported else []
    switches = conn.execute(
        """SELECT s.*, m.display_name FROM register_switches s LEFT JOIN members m ON m.member_id = s.decided_by
           ORDER BY s.switch_id"""
    ).fetchall()
    return {"imported": imported, "status": status, "warnings": warnings,
            "open_conflicts": conflicts.count_open(conn),
            "first_switch": switches[0] if switches else None, "last_switch": switches[-1] if switches else None}


def _summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    infos = [activities.due_info(r["due_date"], r["status"], today()) for r in rows]
    return {
        "abertas": len(rows),
        "vencidas": sum(1 for i in infos if i["tone"] == "erro"),
        "proximas": sum(1 for i in infos if i["tone"] == "alerta"),
        "bloqueadas": sum(1 for r in rows if r["status"] == "bloqueada"),
        "sem_prazo": sum(1 for r in rows if not r["due_date"]),
    }


@app.get("/minhas", response_class=HTMLResponse)
async def my_activities(request: Request, ordem: str = "prazo"):
    ordem = ordem if ordem in ORDERS else "prazo"
    with db.session(settings.database_path) as conn:
        me = _me(request, conn)
        rows = (
            activities.list_activities(conn, today(), owner=me["member_id"], status="abertas", order=ordem)
            if me else []
        )
        register = _register_info(conn)
    return render(request, "minhas.html", "minhas", title="Minhas atividades", rows=rows, ordem=ordem,
                  summary=_summary(rows), register=register)


@app.get("/atividades", response_class=HTMLResponse)
async def all_activities(request: Request, responsavel: str = "", frente: str = "", estado: str = "",
                         prazo: str = "", ordem: str = "prazo"):
    with db.session(settings.database_path) as conn:
        member_ids = {r[0] for r in conn.execute("SELECT member_id FROM members")}
        fronts = activities.known_fronts(conn)
        filters = {
            "responsavel": responsavel if responsavel in member_ids | {"nenhum"} else "",
            "frente": frente if frente in set(fronts) | {"nenhuma"} else "",
            "estado": estado if estado in set(STATUSES) | {"abertas"} else "",
            "prazo": prazo if prazo in DUE_FILTERS else "",
            "ordem": ordem if ordem in ORDERS else "prazo",
        }
        rows = activities.list_activities(
            conn, today(), owner=filters["responsavel"] or None, front=filters["frente"] or None,
            status=filters["estado"] or None, due=filters["prazo"] or None, order=filters["ordem"],
        )
        total = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
        register = _register_info(conn)
    active_filters = any(filters[k] for k in ("responsavel", "frente", "estado", "prazo"))
    return render(request, "atividades.html", "todas", title="Todas as atividades", rows=rows, total=total,
                  filters=filters, active_filters=active_filters, fronts=fronts, register=register)


def _form_context(conn: sqlite3.Connection, values: dict[str, Any], errors: dict[str, str], **extra) -> dict:
    return {"values": values, "errors": errors, "fronts": activities.known_fronts(conn), **extra}


EMPTY_FORM = {"title": "", "owners": [], "front": "", "status": "a_fazer", "due_date": "", "next_step": "",
              "priority": "", "description": "", "notes": ""}


@app.get("/atividades/nova", response_class=HTMLResponse)
async def new_activity_form(request: Request):
    with db.session(settings.database_path) as conn:
        ctx = _form_context(conn, dict(EMPTY_FORM), {})
    return render(request, "atividade_form.html", "todas", title="Nova atividade", mode="criar", **ctx)


@app.post("/atividades/nova", response_class=HTMLResponse)
async def create_activity(request: Request):
    form = await request.form()
    with db.session(settings.database_path) as conn:
        me = _me(request, conn)
        member_ids = {r[0] for r in conn.execute("SELECT member_id FROM members")}
        parsed = activities.parse_form(form, member_ids)
        errors = dict(parsed.errors)
        if me is None:
            errors["usuario"] = "Escolha no topo da página quem você é antes de criar uma atividade."
        if errors:
            ctx = _form_context(conn, parsed.data | {"reason": parsed.reason}, errors)
        else:
            activity_id = activities.create(conn, parsed.data, me["member_id"], reason=parsed.reason)
    if errors:
        return render(request, "atividade_form.html", "todas", status_code=422, title="Nova atividade", mode="criar", **ctx)
    _flash(request, f"Atividade {activity_id} criada por {me['display_name']}.", "ok")
    return RedirectResponse(f"/atividades/{activity_id}", status_code=303)


def _not_found(request: Request, activity_id: str) -> HTMLResponse:
    return render(request, "nao_encontrada.html", "todas", status_code=404, title="Atividade não encontrada",
                  activity_id=activity_id)


@app.get("/atividades/{activity_id}", response_class=HTMLResponse)
async def activity_detail(request: Request, activity_id: str):
    with db.session(settings.database_path) as conn:
        a = activities.get(conn, activity_id)
        if a is None:
            return _not_found(request, activity_id)
        events = activities.history(conn, activity_id)
        refs = activities.references(conn, activity_id)
        creator = conn.execute("SELECT display_name FROM members WHERE member_id = ?", (a["created_by"],)).fetchone()
        pending = suggestions.pending_for_activity(conn, activity_id)
    return render(request, "atividade.html", "todas", title=a["title"], a=a, events=events, refs=refs,
                  creator=creator["display_name"] if creator else None, pending=pending)


@app.get("/atividades/{activity_id}/editar", response_class=HTMLResponse)
async def edit_activity_form(request: Request, activity_id: str):
    with db.session(settings.database_path) as conn:
        a = activities.get(conn, activity_id)
        if a is None:
            return _not_found(request, activity_id)
        values = activities.snapshot(conn, activity_id)
        ctx = _form_context(conn, values, {}, a=a, updated_at=a["updated_at"])
    return render(request, "atividade_form.html", "todas", title=f"Editar {activity_id}", mode="editar", **ctx)


@app.post("/atividades/{activity_id}/editar", response_class=HTMLResponse)
async def edit_activity(request: Request, activity_id: str):
    form = await request.form()
    with db.session(settings.database_path) as conn:
        a = activities.get(conn, activity_id)
        if a is None:
            return _not_found(request, activity_id)
        me = _me(request, conn)
        member_ids = {r[0] for r in conn.execute("SELECT member_id FROM members")}
        parsed = activities.parse_form(form, member_ids)
        errors = dict(parsed.errors)
        if me is None:
            errors["usuario"] = "Escolha no topo da página quem você é antes de editar."
        diff = None
        if not errors:
            try:
                diff = activities.update(conn, activity_id, parsed.data, me["member_id"],
                                         expected_updated_at=str(form.get("updated_at") or ""), reason=parsed.reason)
            except StaleEdit:
                errors["stale"] = (
                    "Esta atividade foi alterada por outra pessoa depois que você abriu o formulário. "
                    "Abra a atividade em outra aba para ver os valores atuais; se salvar de novo, os seus valores prevalecem."
                )
                a = activities.get(conn, activity_id)
        if errors:
            ctx = _form_context(conn, parsed.data | {"reason": parsed.reason}, errors, a=a, updated_at=a["updated_at"])
    if errors:
        return render(request, "atividade_form.html", "todas", status_code=422, title=f"Editar {activity_id}",
                      mode="editar", **ctx)
    if diff:
        changed = ", ".join(FIELD_LABELS[f].lower() for f in diff)
        _flash(request, f"Alterações salvas ({changed}) e registradas no histórico.", "ok")
    else:
        _flash(request, "Nenhum campo foi alterado; nada foi registrado.", "info")
    return RedirectResponse(f"/atividades/{activity_id}", status_code=303)


@app.post("/atividades/{activity_id}/estado")
async def change_status(request: Request, activity_id: str):
    form = await request.form()
    new_status = str(form.get("status") or "")
    reason = " ".join(str(form.get("reason") or "").split())[:300] or None
    with db.session(settings.database_path) as conn:
        me = _me(request, conn)
        if activities.get(conn, activity_id) is None:
            return _not_found(request, activity_id)
        if me is None:
            _flash(request, "Escolha no topo da página quem você é antes de mudar o estado.", "erro")
        elif new_status not in STATUSES:
            _flash(request, "Estado inválido.", "erro")
        elif activities.update(conn, activity_id, {"status": new_status}, me["member_id"], reason=reason):
            _flash(request, f"Estado alterado para “{STATUSES[new_status]}” e registrado no histórico.", "ok")
        else:
            _flash(request, f"A atividade já estava “{STATUSES[new_status]}”.", "info")
    return RedirectResponse(f"/atividades/{activity_id}", status_code=303)


# ---------------------------------------------------------------------------
# Sugestões para revisar
# ---------------------------------------------------------------------------


@app.get("/sugestoes", response_class=HTMLResponse)
async def suggestions_page(request: Request):
    with db.session(settings.database_path) as conn:
        me = _me(request, conn)
        members = conn.execute("SELECT * FROM members ORDER BY display_name").fetchall()
        pending = suggestions.list_all(conn, pending=True)
        reviewed = suggestions.list_all(conn, pending=False)
        analyses = analysis.list_analyses(conn)
        waiting = analysis.waiting(conn)
    for s in pending + reviewed:
        s["reviewers"] = suggestions.reviewers_for(members, s)
    mine = (lambda s: me["member_id"] in s["affected_ids"]) if me else (lambda s: False)
    to_review = [s for s in pending if suggestions.can_review(me, s)]
    affecting = [s for s in pending if s not in to_review and mine(s)]
    others = [s for s in pending if s not in to_review and s not in affecting]
    if me:
        reviewed = [s for s in reviewed if suggestions.can_review(me, s) or mine(s)]
    return render(request, "sugestoes.html", "sugestoes", title="Sugestões para revisar", to_review=to_review,
                  affecting=affecting, others=others, reviewed=reviewed[:15], analyses=analyses, waiting=waiting,
                  ai_label=settings.ai_label, running=sync.is_running())


def _review_values(form: Any, s: dict[str, Any], member_ids: set[str]) -> tuple[dict[str, Any], dict[str, str]]:
    """Valores escolhidos pela pessoa revisora. Atualização: só os campos marcados como "aplicar"."""
    errors: dict[str, str] = {}
    if s["kind"] == "update":
        fields = [f for f in s["proposed_fields"] if form.get(f"aplicar_{f}")]
    else:
        fields = ["title", "owners", "front", "status", "due_date", "next_step"] + [
            f for f in ("priority", "notes") if f in s["proposed_fields"]]
    values: dict[str, Any] = {}
    for f in fields:
        raw = form.get(f)
        if f == "owners":
            chosen = sorted(set(form.getlist("owners")))
            if any(m not in member_ids for m in chosen):
                errors[f] = "Responsável desconhecido."
            values[f] = chosen
        elif f == "due_date":
            text = str(raw or "").strip()
            try:
                values[f] = date.fromisoformat(text).isoformat() if text else None
            except ValueError:
                errors[f] = "Use uma data válida ou deixe em branco para “a definir”."
        elif f == "status":
            if raw not in STATUSES:
                errors[f] = "Escolha um estado da lista."
            values[f] = raw
        elif f == "priority":
            values[f] = raw if raw in PRIORITIES else None
        else:
            limit = 4000 if f == "notes" else 300 if f == "next_step" else 200 if f == "title" else 80
            values[f] = " ".join(str(raw or "").split())[:limit] or None
    if s["kind"] == "create" and not values.get("title"):
        errors["title"] = "Informe um título."
    return values, errors


def _suggestion_context(conn: sqlite3.Connection, s: dict[str, Any], me: sqlite3.Row | None) -> dict[str, Any]:
    members = conn.execute("SELECT * FROM members ORDER BY display_name").fetchall()
    related = [activities.get(conn, aid) for aid in s["related_activity_ids"]]
    analysis_row = conn.execute("SELECT * FROM analyses WHERE analysis_id = ?", (s["analysis_id"],)).fetchone()
    return {
        "s": s,
        "can_review": suggestions.can_review(me, s),
        "reviewers": suggestions.reviewers_for(members, s),
        "self_review": bool(me and me["member_id"] in s["affected_ids"]),
        "related": [r for r in related if r],
        "fronts": activities.known_fronts(conn),
        "analysis": analysis_row,
    }


@app.get("/sugestoes/{suggestion_id}", response_class=HTMLResponse)
async def suggestion_detail(request: Request, suggestion_id: int):
    with db.session(settings.database_path) as conn:
        s = suggestions.get(conn, suggestion_id)
        if s is None:
            return render(request, "nao_encontrada.html", "sugestoes", status_code=404,
                          title="Sugestão não encontrada", activity_id=f"#{suggestion_id}")
        ctx = _suggestion_context(conn, s, _me(request, conn))
    return render(request, "sugestao.html", "sugestoes", title=f"Sugestão #{suggestion_id}",
                  values=None, errors={}, **ctx)


@app.post("/sugestoes/{suggestion_id}/revisao", response_class=HTMLResponse)
async def review_suggestion(request: Request, suggestion_id: int):
    form = await request.form()
    action = str(form.get("acao") or "")
    reason = str(form.get("motivo") or "")
    with db.session(settings.database_path) as conn:
        me = _me(request, conn)
        s = suggestions.get(conn, suggestion_id)
        if s is None:
            return render(request, "nao_encontrada.html", "sugestoes", status_code=404,
                          title="Sugestão não encontrada", activity_id=f"#{suggestion_id}")
        values, errors = None, {}
        if action == "aceitar":
            member_ids = {r[0] for r in conn.execute("SELECT member_id FROM members")}
            values, errors = _review_values(form, s, member_ids)
        if errors:
            ctx = _suggestion_context(conn, s, me)
        else:
            try:
                result = suggestions.review(conn, suggestion_id, me, action, values, reason)
            except suggestions.AlreadyReviewed as exc:
                conn.rollback()
                _flash(request, str(exc), "info")
                return RedirectResponse(f"/sugestoes/{suggestion_id}", status_code=303)
            except (suggestions.NotAllowed, ValueError, LookupError) as exc:
                conn.rollback()
                if action == "rejeitar" or isinstance(exc, suggestions.NotAllowed):
                    _flash(request, str(exc), "erro")
                    return RedirectResponse(f"/sugestoes/{suggestion_id}", status_code=303)
                errors = {"geral": str(exc)}
                ctx = _suggestion_context(conn, s, me)
    if errors:
        return render(request, "sugestao.html", "sugestoes", status_code=422, title=f"Sugestão #{suggestion_id}",
                      values=values, errors=errors, **ctx)
    if result.status == "rejeitada":
        _flash(request, f"Sugestão #{suggestion_id} rejeitada por {me['display_name']}; o motivo ficou registrado. "
                        "Nenhuma atividade mudou.", "ok")
        return RedirectResponse("/sugestoes", status_code=303)
    if s["kind"] == "create":
        _flash(request, f"Sugestão #{suggestion_id} {REVIEW_VERB[result.status]} por {me['display_name']}: "
                        f"atividade {result.activity_id} criada, com a ata como fonte no histórico.", "ok")
    elif result.changed:
        changed = ", ".join(FIELD_LABELS[f].lower() for f in result.changed)
        _flash(request, f"Sugestão #{suggestion_id} {REVIEW_VERB[result.status]} por {me['display_name']}: "
                        f"{changed} de {result.activity_id} atualizado(s) e registrado(s) no histórico.", "ok")
    else:
        _flash(request, f"Sugestão #{suggestion_id} {REVIEW_VERB[result.status]}; os valores já eram esses, "
                        "nenhum campo mudou.", "info")
    return RedirectResponse(f"/atividades/{result.activity_id}", status_code=303)


REVIEW_VERB = {"aceita": "aceita", "ajustada": "ajustada e aceita"}


@app.post("/analises/tentar")
async def retry_analysis(request: Request):
    form = await request.form()
    file_id = str(form.get("file_id") or "") or None
    run = await asyncio.to_thread(sync.run_analysis, settings, file_id)
    if run is None:
        _flash(request, "Há uma sincronização em andamento; a análise roda logo depois dela. Recarregue em instantes.", "info")
    elif run.failed:
        _flash(request, "A análise falhou de novo: " + " ".join(run.errors) +
               " Os dados oficiais não mudaram; criar e editar atividades continua funcionando.", "erro")
    else:
        _flash(request, f"Análise concluída: {run.created} sugestão(ões) nova(s).", "ok")
    return RedirectResponse("/sugestoes#analises", status_code=303)


@app.get("/sincronizacao", response_class=HTMLResponse)
async def sync_status(request: Request):
    with db.session(settings.database_path) as conn:
        health = _sync_health(conn)
        state = health["state"]
        sources = conn.execute(
            """SELECT * FROM sources
               ORDER BY CASE sync_status WHEN 'failed' THEN 0 WHEN 'unavailable' THEN 1
                        WHEN 'processed' THEN 2 ELSE 3 END, path COLLATE NOCASE"""
        ).fetchall()
        runs = conn.execute("SELECT * FROM sync_runs ORDER BY run_id DESC LIMIT 10").fetchall()
        register_status = conn.execute("SELECT * FROM register_status WHERE id = 1").fetchone()
        conflict_rows = conflicts.list_conflicts(conn)
        analyses_by_source = analysis.by_source(conn)
        me = _me(request, conn)
    counts = {k: 0 for k in STATUS_LABELS}
    for s in sources:
        counts[s["sync_status"]] = counts.get(s["sync_status"], 0) + 1
    connected = google_auth.is_connected(settings)

    return render(
        request,
        "sync.html",
        "sync",
        state=state,
        sources=sources,
        runs=runs,
        register_status=register_status,
        counts=counts,
        stale=health["stale"],
        running=sync.is_running(),
        connected=connected,
        next_auto_at=sync.next_auto_at if connected and settings.sync_interval_seconds > 0 else None,
        conflict_rows=conflict_rows,
        analyses_by_source=analyses_by_source,
        can_decide=conflicts.can_decide(me),
        missing=settings.missing_settings(),
        interval_min=settings.sync_interval_seconds // 60,
        folder_configured=bool(settings.drive_folder_id),
    )


_background: set[asyncio.Task] = set()  # análises em segundo plano (referência evita coleta antes do fim)


@app.post("/sincronizacao/agora")
async def sync_now(request: Request):
    if not google_auth.is_connected(settings):
        _flash(request, "Conecte uma conta do Google antes de sincronizar.", "erro")
        return RedirectResponse("/sincronizacao", status_code=303)
    result = await asyncio.to_thread(sync.run_sync, settings, "manual", analyze=False)
    if result is None:
        _flash(request, "Já havia uma sincronização em andamento. Aguarde alguns segundos e recarregue.", "info")
    elif result.ok:
        c = result.counts
        with db.session(settings.database_path) as conn:
            pending = len(analysis.waiting(conn))
        message = (f"Sincronização concluída: {c['seen']} arquivo(s) na pasta, {len(result.changed)} com conteúdo novo, "
                   f"{c['failed']} com falha, {c['unavailable']} indisponível(is).")
        if pending:
            # A IA pode levar de segundos a um minuto: roda em segundo plano, com a mesma trava da sincronização.
            task = asyncio.create_task(asyncio.to_thread(sync.run_analysis, settings, None, False))
            _background.add(task)
            task.add_done_callback(_background.discard)
            message += (f" Análise de {pending} ata(s) pela IA em andamento: as sugestões aparecem em "
                        "“Sugestões para revisar” em alguns segundos (recarregue a página).")
        _flash(request, message, "ok")
    else:
        _flash(request, f"A sincronização falhou: {result.error} Os dados exibidos são os da última leitura confirmada.", "erro")
    return RedirectResponse("/sincronizacao", status_code=303)


@app.post("/conflitos/{conflict_id}/decisao")
async def decide_conflict(request: Request, conflict_id: int):
    form = await request.form()
    action = str(form.get("acao") or "registrar")
    with db.session(settings.database_path) as conn:
        me = _me(request, conn)
        try:
            conflicts.decide(conn, conflict_id, me, str(form.get("resolution") or ""), action)
            if action == "aceitar_nova_fonte":  # mesma transação: decisão e troca juntas, ou nenhuma
                n, _ = importer.accept_new_source(conn, conflict_id, me, settings.drive_folder_id)
        except (conflicts.NotAllowed, ValueError, LookupError) as exc:
            conn.rollback()
            _flash(request, str(exc), "erro")
            return RedirectResponse("/sincronizacao#conflitos", status_code=303)
    if action == "aceitar_nova_fonte":
        _flash(request, f"Nova fonte aceita por {me['display_name']}. Nenhuma atividade mudou: {n} diferença(s) entre a "
                        "nova planilha e o app viraram sugestões para revisão.", "ok")
    else:
        _flash(request, f"Decisão registrada por {me['display_name']}. Nenhuma atividade nem arquivo do Drive foi alterado.", "ok")
    # Atualiza a situação da fonte das atividades sem esperar a próxima sincronização (só banco).
    try:
        with db.session(settings.database_path) as conn:
            importer.after_sync(conn, settings.drive_folder_id)
    except Exception:  # noqa: BLE001 — a decisão já foi gravada; a próxima sincronização recalcula
        log.exception("Falha ao recalcular a fonte das atividades após decisão de conflito")
    return RedirectResponse("/sincronizacao#conflitos", status_code=303)


# ---------------------------------------------------------------------------
# OAuth com o Google
# ---------------------------------------------------------------------------


@app.get("/auth/login")
async def auth_login(request: Request):
    if not settings.google_configured:
        _flash(request, "Credenciais do Google ausentes no .env (veja o README).", "erro")
        return RedirectResponse("/sincronizacao", status_code=303)
    # O cookie de sessão precisa estar no mesmo host do callback (localhost × 127.0.0.1).
    callback = urlparse(settings.google_redirect_uri)
    if request.url.netloc != callback.netloc:
        return RedirectResponse(f"{callback.scheme}://{callback.netloc}/auth/login", status_code=303)
    url, state, verifier = google_auth.start_authorization(settings)
    request.session["oauth_state"] = state
    request.session["oauth_verifier"] = verifier
    return RedirectResponse(url, status_code=303)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    expected_state = request.session.pop("oauth_state", None)
    verifier = request.session.pop("oauth_verifier", None)
    params = request.query_params
    if params.get("error"):
        _flash(request, f"O Google não autorizou o acesso ({params.get('error')}).", "erro")
        return RedirectResponse("/sincronizacao", status_code=303)
    if not expected_state or params.get("state") != expected_state:
        _flash(request, "Resposta de autorização inválida (state não confere). Tente conectar de novo.", "erro")
        return RedirectResponse("/sincronizacao", status_code=303)
    # Reconstrói a URL com o redirect_uri configurado (evita divergência localhost × 127.0.0.1).
    authorization_response = f"{settings.google_redirect_uri}?{request.url.query}"
    try:
        await asyncio.to_thread(
            google_auth.finish_authorization, settings, expected_state, verifier, authorization_response
        )
    except PermissionError as exc:
        _flash(request, str(exc), "erro")
        return RedirectResponse("/sincronizacao", status_code=303)
    except Exception as exc:  # noqa: BLE001 — não exibir detalhes que possam conter tokens
        log.warning("Falha ao concluir OAuth: %s", exc.__class__.__name__)
        _flash(request, "Não foi possível concluir a autorização com o Google. Tente novamente.", "erro")
        return RedirectResponse("/sincronizacao", status_code=303)

    _flash(request, "Conta do Google conectada. Primeira sincronização executada.", "ok")
    await asyncio.to_thread(sync.run_sync, settings, "manual")
    return RedirectResponse("/sincronizacao", status_code=303)


@app.post("/auth/desconectar")
async def auth_disconnect(request: Request):
    google_auth.disconnect(settings)
    _flash(
        request,
        "Conta desconectada neste computador. Os dados já lidos continuam no banco local. "
        "Para revogar o acesso no Google, use myaccount.google.com/permissions.",
        "info",
    )
    return RedirectResponse("/sincronizacao", status_code=303)
