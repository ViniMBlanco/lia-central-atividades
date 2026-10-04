"""Configuração lida do ambiente (.env). Segredos nunca são impressos nem exibidos."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    app_host: str
    app_port: int
    secret_key: str
    database_path: Path
    token_path: Path
    timezone: ZoneInfo
    sync_interval_seconds: int
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    google_drive_scope: str
    drive_folder_id: str
    ai_provider: str  # gemini | none
    gemini_api_key: str
    gemini_model: str
    ai_timeout_seconds: int

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.google_redirect_uri)

    @property
    def ai_label(self) -> str:
        """Quem gera as sugestões das atas (sem expor chaves)."""
        if self.ai_provider == "gemini" and self.gemini_api_key and self.gemini_model:
            return f"gemini:{self.gemini_model}"
        return "deterministico"

    def missing_settings(self) -> list[str]:
        """Nomes (nunca valores) das variáveis obrigatórias que estão vazias."""
        required = {
            "APP_SECRET_KEY": self.secret_key,
            "GOOGLE_CLIENT_ID": self.google_client_id,
            "GOOGLE_CLIENT_SECRET": self.google_client_secret,
            "GOOGLE_REDIRECT_URI": self.google_redirect_uri,
            "DRIVE_TEST_FOLDER_ID": self.drive_folder_id,
        }
        return [name for name, value in required.items() if not value]


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else BASE_DIR / p


def load_settings() -> Settings:
    db_path = _resolve(_get("DATABASE_PATH", "data/app.db"))
    return Settings(
        app_host=_get("APP_HOST", "127.0.0.1"),
        app_port=int(_get("APP_PORT", "8000")),
        secret_key=_get("APP_SECRET_KEY"),
        database_path=db_path,
        token_path=_resolve(_get("GOOGLE_TOKEN_PATH", str(db_path.parent / "google_token.json"))),
        timezone=ZoneInfo(_get("TIMEZONE", "America/Sao_Paulo")),
        sync_interval_seconds=int(_get("SYNC_INTERVAL_SECONDS", "300")),
        google_client_id=_get("GOOGLE_CLIENT_ID"),
        google_client_secret=_get("GOOGLE_CLIENT_SECRET"),
        google_redirect_uri=_get("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback"),
        google_drive_scope=_get("GOOGLE_DRIVE_SCOPE", "https://www.googleapis.com/auth/drive.readonly"),
        drive_folder_id=_get("DRIVE_TEST_FOLDER_ID"),
        ai_provider=_get("AI_PROVIDER", "gemini").lower(),
        gemini_api_key=_get("GEMINI_API_KEY"),
        gemini_model=_get("GEMINI_MODEL", "gemini-3.6-flash"),
        ai_timeout_seconds=int(_get("AI_TIMEOUT_SECONDS", "90")),
    )


settings = load_settings()
