"""Infraestrutura de teste: Drive falso em memória e configurações isoladas."""

from __future__ import annotations

import dataclasses
import itertools
from pathlib import Path
from typing import Any

import pytest

from app import db
from app.config import settings as base_settings
from app.drive import FOLDER_MIME, GDOC_MIME, DriveError

FIXTURES = Path(__file__).parent / "fixtures"
ROOT_ID = "ROOT"

MIME_BY_EXT = {
    ".md": "text/markdown",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class FakeDrive:
    """Imita o necessário da Drive API: árvore de pastas, versões, lixeira e falhas."""

    def __init__(self) -> None:
        self.files: dict[str, dict[str, Any]] = {}
        self.content: dict[str, bytes] = {}
        self.fail_ids: set[str] = set()  # get_media/export desses IDs falham com HTTP 500
        self.fail_listing = False
        self.download_count = 0
        self._ids = itertools.count(1)
        self._clock = itertools.count(1)
        self.files[ROOT_ID] = {"id": ROOT_ID, "name": "LIA case teste", "mimeType": FOLDER_MIME,
                               "parents": [], "trashed": False, "webViewLink": "https://drive/ROOT"}

    def _stamp(self) -> str:
        return f"2026-10-03T12:{next(self._clock):02d}:00.000Z"

    def add_folder(self, name: str, parent: str = ROOT_ID) -> str:
        fid = f"F{next(self._ids)}"
        self.files[fid] = {"id": fid, "name": name, "mimeType": FOLDER_MIME, "parents": [parent], "trashed": False}
        return fid

    def add_file(self, name: str, data: bytes, mime: str | None = None, parent: str = ROOT_ID) -> str:
        fid = f"f{next(self._ids)}"
        if mime is None:
            mime = MIME_BY_EXT.get(Path(name).suffix.lower(), "application/octet-stream")
        self.files[fid] = {
            "id": fid, "name": name, "mimeType": mime, "parents": [parent], "trashed": False,
            "version": "1", "modifiedTime": self._stamp(), "webViewLink": f"https://drive/{fid}",
            "capabilities": {"canDownload": True},
        }
        if not mime.startswith("application/vnd.google-apps."):
            self.files[fid]["size"] = str(len(data))
        self.content[fid] = data
        return fid

    def add_fixture(self, relpath: str, parent: str = ROOT_ID) -> str:
        path = FIXTURES / relpath
        return self.add_file(path.name, path.read_bytes(), parent=parent)

    def edit(self, fid: str, data: bytes) -> None:
        self.content[fid] = data
        self._touch(fid)

    def rename(self, fid: str, name: str) -> None:
        self.files[fid]["name"] = name
        self._touch(fid)

    def _touch(self, fid: str) -> None:
        f = self.files[fid]
        f["version"] = str(int(f["version"]) + 1)
        f["modifiedTime"] = self._stamp()

    # -- API usada pelo app ----------------------------------------------------

    def get_file(self, file_id: str) -> dict[str, Any]:
        if file_id not in self.files:
            raise DriveError("File not found", status=404, reason="notFound")
        return dict(self.files[file_id])

    def list_children(self, folder_id: str) -> list[dict[str, Any]]:
        if self.fail_listing:
            raise DriveError("Backend Error", status=503, reason="backendError")
        return [dict(f) for f in self.files.values() if folder_id in f["parents"] and not f["trashed"]]

    def download(self, file_id: str) -> bytes:
        if file_id in self.fail_ids:
            raise DriveError("Backend Error", status=500, reason="backendError")
        if self.files[file_id]["mimeType"].startswith("application/vnd.google-apps."):
            raise DriveError("Only files with binary content can be downloaded", status=403, reason="fileNotDownloadable")
        self.download_count += 1
        return self.content[file_id]

    def export(self, file_id: str, mime_type: str) -> bytes:
        if file_id in self.fail_ids:
            raise DriveError("Backend Error", status=500, reason="backendError")
        assert self.files[file_id]["mimeType"] == GDOC_MIME and mime_type == "text/plain"
        self.download_count += 1
        return self.content[file_id]

    def account_name(self) -> str | None:
        return "Conta de teste"


@pytest.fixture
def cfg(tmp_path):
    s = dataclasses.replace(
        base_settings,
        database_path=tmp_path / "app.db",
        token_path=tmp_path / "google_token.json",
        drive_folder_id=ROOT_ID,
        sync_interval_seconds=0,
        ai_provider="none",  # testes nunca chamam a IA de verdade (respostas gravadas em fixtures/ia)
        gemini_api_key="",
    )
    db.init_db(s.database_path)
    return s


@pytest.fixture
def drive():
    return FakeDrive()


@pytest.fixture
def conn(cfg):
    c = db.connect(cfg.database_path)
    yield c
    c.close()
