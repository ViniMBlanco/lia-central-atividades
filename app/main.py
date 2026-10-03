"""Aplicação web (FastAPI + Jinja2). Execute com:  python -m app"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import db, google_auth, sync
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
templates.env.globals["KIND_LABELS"] = KIND_LABELS
templates.env.globals["STATUS_LABELS"] = STATUS_LABELS


# ---------------------------------------------------------------------------
# Ciclo de vida: banco + sincronização automática periódica
# ---------------------------------------------------------------------------


async def _auto_sync_loop(cfg: Settings) -> None:
    while True:
        await asyncio.sleep(cfg.sync_interval_seconds)
        if not google_auth.is_connected(cfg) or sync.is_running():
            continue
        try:
            await asyncio.to_thread(sync.run_sync, cfg, "auto")
        except Exception:  # noqa: BLE001 — o ciclo nunca pode morrer
            log.exception("Erro no ciclo de sincronização automática")


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


def render(request: Request, template: str, active: str, **ctx) -> HTMLResponse:
    flashes = request.session.pop("flash", [])
    return templates.TemplateResponse(
        request, template, {"active": active, "flashes": flashes, **ctx}
    )


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------

PLACEHOLDERS = {
    "/": ("comece", "Comece aqui"),
    "/minhas": ("minhas", "Minhas atividades"),
    "/atividades": ("todas", "Todas as atividades"),
    "/sugestoes": ("sugestoes", "Sugestões para revisar"),
    "/novidades": ("novidades", "Novidades dos documentos"),
}


def _placeholder(path: str):
    key, title = PLACEHOLDERS[path]

    async def page(request: Request):
        return render(request, "placeholder.html", key, title=title)

    return page


for _path in PLACEHOLDERS:
    app.add_api_route(_path, _placeholder(_path), methods=["GET"], response_class=HTMLResponse)


@app.get("/sincronizacao", response_class=HTMLResponse)
async def sync_status(request: Request):
    with db.session(settings.database_path) as conn:
        state = conn.execute("SELECT * FROM sync_state WHERE folder_id=?", (settings.drive_folder_id,)).fetchone()
        sources = conn.execute(
            """SELECT * FROM sources
               ORDER BY CASE sync_status WHEN 'failed' THEN 0 WHEN 'unavailable' THEN 1
                        WHEN 'processed' THEN 2 ELSE 3 END, path COLLATE NOCASE"""
        ).fetchall()
        runs = conn.execute("SELECT * FROM sync_runs ORDER BY run_id DESC LIMIT 10").fetchall()
    counts = {k: 0 for k in STATUS_LABELS}
    for s in sources:
        counts[s["sync_status"]] = counts.get(s["sync_status"], 0) + 1

    stale = False
    last_success = _parse(state["last_success_at"]) if state else None
    if sources and settings.sync_interval_seconds > 0:
        limit = timedelta(seconds=settings.sync_interval_seconds * 2 + 60)
        stale = last_success is None or datetime.now(timezone.utc) - last_success > limit

    return render(
        request,
        "sync.html",
        "sync",
        state=state,
        sources=sources,
        runs=runs,
        counts=counts,
        stale=stale,
        running=sync.is_running(),
        connected=google_auth.is_connected(settings),
        missing=settings.missing_settings(),
        interval_min=settings.sync_interval_seconds // 60,
        folder_configured=bool(settings.drive_folder_id),
    )


@app.post("/sincronizacao/agora")
async def sync_now(request: Request):
    if not google_auth.is_connected(settings):
        _flash(request, "Conecte uma conta do Google antes de sincronizar.", "erro")
        return RedirectResponse("/sincronizacao", status_code=303)
    result = await asyncio.to_thread(sync.run_sync, settings, "manual")
    if result is None:
        _flash(request, "Já havia uma sincronização em andamento. Aguarde alguns segundos e recarregue.", "info")
    elif result.ok:
        c = result.counts
        _flash(
            request,
            f"Sincronização concluída: {c['seen']} arquivo(s) na pasta, {len(result.changed)} com conteúdo novo, "
            f"{c['failed']} com falha, {c['unavailable']} indisponível(is).",
            "ok",
        )
    else:
        _flash(request, f"A sincronização falhou: {result.error} Os dados exibidos são os da última leitura confirmada.", "erro")
    return RedirectResponse("/sincronizacao", status_code=303)


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
