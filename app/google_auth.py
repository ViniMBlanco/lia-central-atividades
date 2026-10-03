"""OAuth 2.0 (fluxo web server) com o Google e guarda do token.

- O segredo do cliente fica só no servidor (.env).
- `state` e o verificador PKCE ficam na sessão assinada e são conferidos no callback.
- O token (com refresh token, para a sincronização em segundo plano) fica em
  data/google_token.json, com permissão 600 e fora do git. Apagar esse arquivo
  desconecta a conta.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from urllib.parse import urlparse

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from .config import Settings

TOKEN_URI = "https://oauth2.googleapis.com/token"


class NotConnected(Exception):
    """Não há autorização do Google válida: é preciso conectar (de novo)."""


def _allow_http_localhost(settings: Settings) -> None:
    # oauthlib exige HTTPS; em http://localhost (desenvolvimento) liberamos explicitamente.
    host = urlparse(settings.google_redirect_uri).hostname
    if host in ("localhost", "127.0.0.1"):
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    # O Google pode devolver escopos já concedidos antes junto com o pedido.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


def _flow(settings: Settings, state: str | None = None, code_verifier: str | None = None) -> Flow:
    _allow_http_localhost(settings)
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": TOKEN_URI,
            "redirect_uris": [settings.google_redirect_uri],
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=[settings.google_drive_scope],
        state=state,
        redirect_uri=settings.google_redirect_uri,
        code_verifier=code_verifier,
    )


def start_authorization(settings: Settings) -> tuple[str, str, str]:
    """Devolve (url de autorização, state, code_verifier)."""
    flow = _flow(settings)
    url, state = flow.authorization_url(
        access_type="offline",  # refresh token: o sync roda sem a pessoa presente
        prompt="consent",  # garante novo refresh token ao reconectar
        include_granted_scopes="true",
    )
    return url, state, flow.code_verifier


def finish_authorization(settings: Settings, state: str, code_verifier: str, authorization_response: str) -> None:
    flow = _flow(settings, state=state, code_verifier=code_verifier)
    flow.fetch_token(authorization_response=authorization_response)
    creds = flow.credentials
    if settings.google_drive_scope not in (creds.granted_scopes or creds.scopes or []):
        raise PermissionError(
            "O Google não concedeu o escopo de leitura do Drive. "
            "Na tela de consentimento, marque a permissão de ver os arquivos do Drive."
        )
    save_credentials(settings, creds)


def save_credentials(settings: Settings, creds: Credentials) -> None:
    path = settings.token_path
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "scopes": list(creds.scopes or [settings.google_drive_scope]),
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def load_credentials(settings: Settings) -> Credentials:
    """Credenciais válidas (renovadas se preciso) ou NotConnected."""
    path = settings.token_path
    if not path.exists():
        raise NotConnected("Nenhuma conta do Google conectada.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NotConnected("Arquivo de autorização ilegível; conecte novamente.") from exc
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=TOKEN_URI,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=data.get("scopes"),
        # google-auth usa datetime "ingênuo" em UTC para a expiração.
        expiry=datetime.fromisoformat(data["expiry"]) if data.get("expiry") else None,
    )
    if not creds.valid:
        if not creds.refresh_token:
            raise NotConnected("A autorização não tem renovação automática; conecte novamente.")
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            # Em apps "External/Testing" o refresh token expira em 7 dias, ou foi revogado.
            raise NotConnected(
                "A autorização do Google expirou ou foi revogada; conecte novamente."
            ) from exc
        save_credentials(settings, creds)
    return creds


def is_connected(settings: Settings) -> bool:
    return settings.token_path.exists()


def disconnect(settings: Settings) -> None:
    """Apaga o token local. (A revogação no Google é feita em myaccount.google.com/permissions.)"""
    try:
        settings.token_path.unlink()
    except FileNotFoundError:
        pass
