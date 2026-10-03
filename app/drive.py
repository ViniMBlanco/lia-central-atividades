"""Cliente mínimo e somente leitura da Google Drive API v3.

O app nunca cria, move, renomeia nem apaga nada no Drive: só lista, baixa e exporta.
Um cliente por execução de sincronização (httplib2 não é seguro entre threads).
"""

from __future__ import annotations

import json
from typing import Any, Protocol

import httplib2
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

FOLDER_MIME = "application/vnd.google-apps.folder"
GDOC_MIME = "application/vnd.google-apps.document"
GSHEET_MIME = "application/vnd.google-apps.spreadsheet"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

FILE_FIELDS = (
    "id,name,mimeType,modifiedTime,version,webViewLink,size,md5Checksum,"
    "parents,trashed,capabilities(canDownload)"
)
TIMEOUT_SECONDS = 30
RETRIES = 2


class DriveError(Exception):
    """Falha ao falar com o Drive. `status` é o código HTTP, quando houver."""

    def __init__(self, message: str, status: int | None = None, reason: str | None = None):
        super().__init__(message)
        self.status = status
        self.reason = reason


class DriveClientProtocol(Protocol):
    def get_file(self, file_id: str) -> dict[str, Any]: ...
    def list_children(self, folder_id: str) -> list[dict[str, Any]]: ...
    def download(self, file_id: str) -> bytes: ...
    def export(self, file_id: str, mime_type: str) -> bytes: ...
    def account_name(self) -> str | None: ...


def _wrap(exc: HttpError) -> DriveError:
    status = getattr(exc.resp, "status", None)
    reason = None
    message = str(exc)
    try:
        payload = json.loads(exc.content.decode("utf-8"))
        err = payload.get("error", {})
        message = err.get("message", message)
        errors = err.get("errors") or []
        if errors:
            reason = errors[0].get("reason")
    except (ValueError, AttributeError):
        pass
    return DriveError(message, status=int(status) if status else None, reason=reason)


class DriveClient:
    def __init__(self, creds: Credentials):
        http = AuthorizedHttp(creds, http=httplib2.Http(timeout=TIMEOUT_SECONDS))
        self._svc = build("drive", "v3", http=http, cache_discovery=False)

    def _run(self, request) -> Any:
        try:
            return request.execute(num_retries=RETRIES)
        except HttpError as exc:
            raise _wrap(exc) from exc
        except (TimeoutError, OSError, httplib2.HttpLib2Error) as exc:
            raise DriveError(f"Falha de rede ao acessar o Drive: {exc.__class__.__name__}") from exc

    def get_file(self, file_id: str) -> dict[str, Any]:
        return self._run(
            self._svc.files().get(fileId=file_id, fields=FILE_FIELDS, supportsAllDrives=True)
        )

    def list_children(self, folder_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token = None
        while True:
            resp = self._run(
                self._svc.files().list(
                    q=f"'{folder_id}' in parents and trashed = false",
                    fields=f"nextPageToken, files({FILE_FIELDS})",
                    pageSize=1000,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    spaces="drive",
                )
            )
            items.extend(resp.get("files", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                return items

    def download(self, file_id: str) -> bytes:
        return self._run(self._svc.files().get_media(fileId=file_id, supportsAllDrives=True))

    def export(self, file_id: str, mime_type: str) -> bytes:
        return self._run(self._svc.files().export(fileId=file_id, mimeType=mime_type))

    def account_name(self) -> str | None:
        about = self._run(self._svc.about().get(fields="user(displayName)"))
        return (about.get("user") or {}).get("displayName")
