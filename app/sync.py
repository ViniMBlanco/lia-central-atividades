"""Sincronização com a pasta do Drive.

Cada execução faz uma varredura completa e recursiva da pasta monitorada:
- arquivo novo ou com versão nova no Drive → baixa/exporta e extrai o conteúdo;
- conteúdo igual ao já processado (ex.: só renomeado) → só atualiza metadados;
- arquivo que sumiu da varredura → "indisponível", com o motivo, mantendo o último
  conteúdo confirmado;
- se a varredura falha (rede, autorização, pasta inacessível), nada é marcado como
  removido: falha de leitura nunca vira "não há atividades".

Execuções nunca se sobrepõem: o botão manual e o ciclo automático usam a mesma trava.
Depois de uma varredura concluída, `importer.after_sync` recalcula a autoridade das
fontes e faz a importação única da planilha de atividades; em seguida
`analysis.analyze_minutes` transforma atas novas ou editadas em sugestões para revisão.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from . import analysis, db, importer
from .config import Settings
from .drive import FOLDER_MIME, GDOC_MIME, GSHEET_MIME, XLSX_MIME, DriveClient, DriveClientProtocol, DriveError
from .google_auth import NotConnected, load_credentials
from .readers import MAX_BYTES, ReadError, classify, extract, file_ext

log = logging.getLogger(__name__)

_lock = threading.Lock()
next_auto_at: str | None = None  # próxima verificação automática (ISO/UTC), definida pelo ciclo do app

ClientFactory = Callable[[], DriveClientProtocol]


@dataclass
class SyncResult:
    run_id: int
    ok: bool
    error: str | None = None
    changed: list[str] = field(default_factory=list)  # file_ids com conteúdo novo ou alterado
    counts: dict[str, int] = field(default_factory=dict)


def is_running() -> bool:
    return _lock.locked()


def default_client_factory(settings: Settings) -> ClientFactory:
    return lambda: DriveClient(load_credentials(settings))


def run_sync(settings: Settings, trigger: str, client_factory: ClientFactory | None = None,
             analyze: bool = True) -> SyncResult | None:
    """Executa uma sincronização. Devolve None se já havia outra em andamento.

    analyze=False deixa a análise das atas para depois (o botão manual a roda em segundo plano,
    para a tela não ficar parada esperando a IA).
    """
    if not _lock.acquire(blocking=False):
        return None
    try:
        factory = client_factory or default_client_factory(settings)
        conn = db.connect(settings.database_path)
        try:
            result = _Sync(conn, settings, trigger, factory).run()
            if result.ok:
                _interpret(conn, settings)
                if analyze:
                    _analyze(conn, settings)
            return result
        finally:
            conn.close()
    finally:
        _lock.release()


def _analyze(conn: sqlite3.Connection, settings: Settings, **kwargs) -> analysis.AnalysisRun | None:
    """Atas novas ou editadas → sugestões. Falha aqui nunca derruba a sincronização."""
    try:
        return analysis.analyze_minutes(conn, settings, **kwargs)
    except Exception:  # noqa: BLE001
        conn.rollback()
        log.exception("Falha inesperada na análise das atas")
        return None


def run_analysis(settings: Settings, file_id: str | None = None, retry_failed: bool = True) -> analysis.AnalysisRun | None:
    """Análise fora da sincronização: botão "Tentar de novo" ou logo depois do "Sincronizar agora".

    None se uma sincronização está em andamento (usa a mesma trava).
    """
    if not _lock.acquire(blocking=False):
        return None
    try:
        conn = db.connect(settings.database_path)
        try:
            return _analyze(conn, settings, retry_failed=retry_failed, only_file_id=file_id) or analysis.AnalysisRun(
                errors=["Falha inesperada na análise; veja o log do servidor."])
        finally:
            conn.close()
    finally:
        _lock.release()


def _interpret(conn: sqlite3.Connection, settings: Settings) -> None:
    """Autoridade das fontes e importação, numa transação só (tudo ou nada)."""
    try:
        importer.after_sync(conn, settings.drive_folder_id)
        conn.commit()
    except Exception as exc:  # noqa: BLE001 — a leitura do Drive já foi gravada; não perder isso
        conn.rollback()
        log.exception("Falha ao interpretar as fontes")
        conn.execute(
            """INSERT INTO register_status (id, state, message, checked_at) VALUES (1, 'atencao', ?, ?)
               ON CONFLICT(id) DO UPDATE SET state = excluded.state, message = excluded.message,
                   checked_at = excluded.checked_at""",
            (f"Falha inesperada ao interpretar as fontes ({exc.__class__.__name__}). "
             "As atividades não foram alteradas; nova tentativa na próxima sincronização.", db.utcnow()),
        )
        conn.commit()


class _Sync:
    def __init__(self, conn: sqlite3.Connection, settings: Settings, trigger: str, factory: ClientFactory):
        self.conn = conn
        self.settings = settings
        self.folder_id = settings.drive_folder_id
        self.trigger = trigger
        self.factory = factory
        self.started_at = db.utcnow()
        self.counts = dict(seen=0, new=0, changed=0, processed=0, failed=0, ignored=0, unavailable=0)
        self.changed: list[str] = []

    # -- execução ---------------------------------------------------------------

    def run(self) -> SyncResult:
        cur = self.conn.execute(
            "INSERT INTO sync_runs (trigger, started_at) VALUES (?, ?)", (self.trigger, self.started_at)
        )
        run_id = cur.lastrowid
        self.conn.execute(
            """INSERT INTO sync_state (folder_id, last_attempt_at) VALUES (?, ?)
               ON CONFLICT(folder_id) DO UPDATE SET last_attempt_at = excluded.last_attempt_at""",
            (self.folder_id, self.started_at),
        )
        self.conn.commit()

        error: str | None = None
        try:
            if not self.folder_id:
                raise _SyncAbort("Pasta do Drive não configurada (DRIVE_TEST_FOLDER_ID vazio no .env).")
            client = self.factory()
            self._scan(client)
        except NotConnected as exc:
            error = str(exc)
        except _SyncAbort as exc:
            error = str(exc)
        except DriveError as exc:
            error = _drive_error_message(exc)
        except Exception as exc:  # noqa: BLE001 — registrar e manter o app de pé
            log.exception("Falha inesperada na sincronização")
            error = f"Falha inesperada na sincronização ({exc.__class__.__name__})."

        finished = db.utcnow()
        ok = error is None
        self.conn.execute(
            """UPDATE sync_runs SET finished_at=?, ok=?, error=?, n_seen=?, n_new=?, n_changed=?,
               n_processed=?, n_failed=?, n_ignored=?, n_unavailable=? WHERE run_id=?""",
            (finished, int(ok), error, *(self.counts[k] for k in
             ("seen", "new", "changed", "processed", "failed", "ignored", "unavailable")), run_id),
        )
        if ok:
            self.conn.execute(
                "UPDATE sync_state SET last_success_at=?, last_error=NULL WHERE folder_id=?",
                (finished, self.folder_id),
            )
        else:
            self.conn.execute("UPDATE sync_state SET last_error=? WHERE folder_id=?", (error, self.folder_id))
        self.conn.commit()
        return SyncResult(run_id=run_id, ok=ok, error=error, changed=self.changed, counts=dict(self.counts))

    # -- varredura --------------------------------------------------------------

    def _scan(self, client: DriveClientProtocol) -> None:
        try:
            root = client.get_file(self.folder_id)
        except DriveError as exc:
            if exc.status in (403, 404):
                raise _SyncAbort(
                    "A pasta monitorada não foi encontrada ou a conta conectada não tem acesso a ela. "
                    "Confira DRIVE_TEST_FOLDER_ID e o compartilhamento da pasta."
                ) from exc
            raise
        if root.get("mimeType") != FOLDER_MIME:
            raise _SyncAbort("DRIVE_TEST_FOLDER_ID não aponta para uma pasta.")
        if root.get("trashed"):
            raise _SyncAbort("A pasta monitorada está na lixeira do Drive.")

        account = None
        try:
            account = client.account_name()
        except DriveError:
            pass
        self.conn.execute(
            "UPDATE sync_state SET folder_name=?, folder_url=?, account_name=COALESCE(?, account_name) WHERE folder_id=?",
            (root.get("name"), root.get("webViewLink"), account, self.folder_id),
        )

        # 1) Listagem completa primeiro. Se qualquer pasta falhar, a execução aborta
        #    antes de tocar no estado dos arquivos.
        files: dict[str, tuple[dict[str, Any], str]] = {}
        visited = {self.folder_id}
        queue = [(self.folder_id, root.get("name") or "")]
        while queue:
            folder_id, folder_path = queue.pop(0)
            for item in client.list_children(folder_id):
                if item.get("mimeType") == FOLDER_MIME:
                    if item["id"] not in visited:
                        visited.add(item["id"])
                        queue.append((item["id"], f"{folder_path}/{item.get('name', '')}"))
                elif item["id"] not in files:
                    files[item["id"]] = (item, f"{folder_path}/{item.get('name', '')}")
        self.counts["seen"] = len(files)

        # 2) Processamento arquivo a arquivo (falha num arquivo não derruba os outros).
        for item, path in files.values():
            self._process_item(client, item, path)
            self.conn.commit()

        # 3) O que estava na pasta e não apareceu agora.
        self._mark_missing(client, set(files))
        self.conn.commit()

    def _process_item(self, client: DriveClientProtocol, item: dict[str, Any], path: str) -> None:
        now = db.utcnow()
        file_id = item["id"]
        name = item.get("name", "")
        mime = item.get("mimeType", "")
        kind, ignore_reason = classify(name, mime)
        existing = self.conn.execute("SELECT * FROM sources WHERE file_id=?", (file_id,)).fetchone()

        self.conn.execute(
            """INSERT INTO sources (file_id, name, mime_type, ext, kind, web_url, path, parent_id, size_bytes,
                   md5_checksum, modified_at, first_seen_at, last_seen_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(file_id) DO UPDATE SET name=excluded.name, mime_type=excluded.mime_type,
                   ext=excluded.ext, kind=excluded.kind, web_url=excluded.web_url, path=excluded.path,
                   parent_id=excluded.parent_id, size_bytes=excluded.size_bytes,
                   md5_checksum=excluded.md5_checksum, modified_at=excluded.modified_at,
                   last_seen_at=excluded.last_seen_at""",
            (file_id, name, mime, file_ext(name), kind or "", item.get("webViewLink"), path,
             (item.get("parents") or [None])[0], _int(item.get("size")), item.get("md5Checksum"),
             item.get("modifiedTime"), now, now),
        )
        if existing is None:
            self.counts["new"] += 1
        else:
            if existing["name"] != name:
                self._event(file_id, "renomeado", f"{existing['name']} → {name}")
            elif existing["parent_id"] != (item.get("parents") or [None])[0]:
                self._event(file_id, "movido", f"{existing['path']} → {path}")
            if existing["sync_status"] == "unavailable":
                self._event(file_id, "voltou", None)

        if kind is None:
            self._set_status(file_id, "ignored", ignore_reason)
            self.counts["ignored"] += 1
            return

        unchanged_in_drive = (
            existing is not None
            and existing["sync_status"] == "processed"
            and existing["kind"] == kind
            and existing["drive_version"] == item.get("version")
            and existing["modified_at"] == item.get("modifiedTime")
        )
        if unchanged_in_drive:
            self.counts["processed"] += 1
            return

        try:
            data = self._fetch(client, item, kind)
            extracted = extract(kind, data)
        except (DriveError, ReadError) as exc:
            reason = _drive_error_message(exc) if isinstance(exc, DriveError) else str(exc)
            if existing is None or existing["sync_status"] != "failed":  # só a passagem para "falhou", não cada nova tentativa
                self._event(file_id, "falhou", reason)
            self._set_status(file_id, "failed", reason)
            self.conn.execute("UPDATE sources SET last_error_at=? WHERE file_id=?", (now, file_id))
            self.counts["failed"] += 1
            return

        same_content = existing is not None and existing["content_hash"] == extracted.content_hash
        self.conn.execute(
            """INSERT OR IGNORE INTO source_versions (file_id, content_hash, drive_version, modified_at,
                   name_at_version, extracted_text, structured_json, processed_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (file_id, extracted.content_hash, item.get("version"), item.get("modifiedTime"), name,
             extracted.text, json.dumps(extracted.structured or {"meta": extracted.meta}, ensure_ascii=False), now),
        )
        self.conn.execute(
            """UPDATE sources SET drive_version=?, content_hash=?, doc_title=?, doc_meta=?, sync_status='processed',
                   status_reason=?, last_processed_at=? WHERE file_id=?""",
            (item.get("version"), extracted.content_hash, extracted.title,
             json.dumps(extracted.meta, ensure_ascii=False), extracted.note,
             now if not same_content else (existing["last_processed_at"] or now), file_id),
        )
        self.counts["processed"] += 1
        if not same_content:
            if existing is not None and existing["content_hash"]:
                self.counts["changed"] += 1
            self.changed.append(file_id)

    def _fetch(self, client: DriveClientProtocol, item: dict[str, Any], kind: str) -> bytes:
        caps = item.get("capabilities") or {}
        if caps.get("canDownload") is False:
            raise ReadError("A conta conectada não tem permissão para baixar este arquivo.")
        if kind == "gdoc":
            return client.export(item["id"], "text/plain")
        if kind == "gsheet":
            return client.export(item["id"], XLSX_MIME)
        size = _int(item.get("size"))
        if size is not None and size > MAX_BYTES:
            raise ReadError("Arquivo maior que 10 MB; não processado.")
        return client.download(item["id"])

    def _mark_missing(self, client: DriveClientProtocol, seen: set[str]) -> None:
        rows = self.conn.execute(
            "SELECT file_id, sync_status FROM sources WHERE sync_status != 'unavailable'"
        ).fetchall()
        for row in rows:
            if row["file_id"] in seen:
                continue
            reason = _missing_reason(client, row["file_id"], self.folder_id)
            self._set_status(row["file_id"], "unavailable", reason)
            self._event(row["file_id"], "indisponivel", reason)
            self.counts["unavailable"] += 1

    def _set_status(self, file_id: str, status: str, reason: str | None) -> None:
        self.conn.execute(
            "UPDATE sources SET sync_status=?, status_reason=? WHERE file_id=?", (status, reason, file_id)
        )

    def _event(self, file_id: str, kind: str, detail: str | None) -> None:
        """Linha do tempo de "Novidades dos documentos" (renomeado, movido, indisponível, voltou, falhou)."""
        self.conn.execute(
            "INSERT INTO source_events (file_id, ts, kind, detail) VALUES (?,?,?,?)", (file_id, db.utcnow(), kind, detail)
        )


class _SyncAbort(Exception):
    pass


def _missing_reason(client: DriveClientProtocol, file_id: str, root_id: str) -> str:
    suffix = " O último conteúdo lido foi mantido e pode estar desatualizado."
    try:
        meta = client.get_file(file_id)
    except DriveError as exc:
        if exc.status in (403, 404):
            return "Removido do Drive ou sem acesso para a conta conectada." + suffix
        return "Não apareceu na última varredura (não foi possível confirmar o motivo)." + suffix
    if meta.get("trashed"):
        return "Movido para a lixeira do Drive." + suffix
    return "Não está mais na pasta monitorada (movido para outro lugar)." + suffix


def _drive_error_message(exc: DriveError) -> str:
    if exc.reason == "exportSizeLimitExceeded":
        return "O Google Doc passa do limite de 10 MB da exportação do Drive."
    if exc.reason == "fileNotDownloadable":
        return "Arquivo nativo do Google não pode ser baixado diretamente."
    if exc.status == 401:
        return "A autorização do Google não foi aceita; conecte novamente."
    if exc.status == 403:
        return f"Acesso negado pelo Drive ({exc.reason or 'sem detalhe'})."
    if exc.status == 404:
        return "Arquivo não encontrado ou sem acesso."
    if exc.status == 429 or (exc.status and exc.status >= 500):
        return f"Drive indisponível ou limitando requisições (HTTP {exc.status}); nova tentativa na próxima sincronização."
    return f"Erro ao acessar o Drive: {exc}"


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
