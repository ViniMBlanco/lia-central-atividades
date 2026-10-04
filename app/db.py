"""Acesso ao SQLite. Uma conexão por uso (o sync roda em outra thread)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        # Bancos criados antes da Fase 3 têm uma tabela `conflicts` provisória (sempre vazia).
        columns = {r[1] for r in conn.execute("PRAGMA table_info(conflicts)")}
        if columns and "conflict_key" not in columns:
            conn.execute("DROP TABLE conflicts")
        # Bancos criados antes da Fase 4 têm uma tabela `suggestions` provisória (sempre vazia).
        columns = {r[1] for r in conn.execute("PRAGMA table_info(suggestions)")}
        if columns and "analysis_id" not in columns:
            if conn.execute("SELECT COUNT(*) FROM suggestions").fetchone()[0] == 0:
                conn.execute("DROP TABLE suggestions")
        had_source_events = bool(conn.execute("PRAGMA table_info(source_events)").fetchall())
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        if not had_source_events:
            _rebuild_source_events(conn)
        # Colunas acrescentadas depois que a tabela já existia (bancos da Fase 3).
        columns = {r[1] for r in conn.execute("PRAGMA table_info(conflicts)")}
        if "decision" not in columns:
            conn.execute("ALTER TABLE conflicts ADD COLUMN decision TEXT")
        conn.commit()
    finally:
        conn.close()


def _rebuild_source_events(conn: sqlite3.Connection) -> None:
    """Bancos de antes da Fase 5: a linha do tempo não tinha a saída de arquivos da pasta nem falhas.

    Reconstrói só o que dá para afirmar: a saída do arquivo foi detectada na primeira sincronização
    concluída depois da última vez em que ele foi visto e que marcou algum arquivo como indisponível
    (sem essa execução, fica o horário em que foi visto pela última vez, dito como aproximado);
    o arquivo com falha falhou em `last_error_at`.
    """
    conn.execute(
        """INSERT INTO source_events (file_id, ts, kind, detail)
           SELECT file_id, COALESCE(detected, last_seen_at), 'indisponivel', COALESCE(status_reason, '') ||
                  CASE WHEN detected IS NULL
                       THEN ' (registro reconstruído: horário aproximado, da última leitura em que o arquivo ainda estava na pasta)'
                       ELSE ' (registro reconstruído a partir do histórico de sincronizações)' END
           FROM (SELECT s.*, (SELECT MIN(r.finished_at) FROM sync_runs r
                              WHERE r.started_at > s.last_seen_at AND r.ok = 1 AND r.n_unavailable > 0) AS detected
                 FROM sources s WHERE s.sync_status = 'unavailable')""")
    conn.execute(
        """INSERT INTO source_events (file_id, ts, kind, detail)
           SELECT file_id, last_error_at, 'falhou', status_reason FROM sources
           WHERE sync_status = 'failed' AND last_error_at IS NOT NULL""")


@contextmanager
def session(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Abre conexão, confirma no fim se não houve erro, desfaz se houve."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
