"""Análise das atas depois de cada sincronização.

Para cada ata (autoridade 'minutes') com uma versão ainda não analisada:
1. sugestões pendentes de versões antigas do mesmo arquivo viram "substituída"
   (não se aplica conclusão antiga sobre texto alterado);
2. o provedor (Gemini ou modo sem IA) lê o texto, fora de qualquer transação;
3. `suggestions.validate` confere tudo contra o documento e o registro atual;
4. análise + sugestões são gravadas juntas. Mesma versão nunca é analisada duas vezes.

Falha do provedor fica registrada como análise "falhou", com o motivo, e é tentada de novo
nas próximas sincronizações (até 3 vezes; depois só pelo botão "Tentar de novo"). Falha
nunca vira "a ata não tem sugestões".
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from . import ai, db, suggestions
from .config import Settings

log = logging.getLogger(__name__)

MAX_AUTO_ATTEMPTS = 3


@dataclass
class AnalysisRun:
    analyzed: int = 0
    failed: int = 0
    created: int = 0
    superseded: int = 0
    errors: list[str] = field(default_factory=list)


def doc_date(source: sqlite3.Row, settings: Settings) -> str | None:
    """Data do documento: cabeçalho `data_da_reuniao` (se for data) ou modificação no Drive."""
    meta = json.loads(source["doc_meta"] or "{}")
    written = str(meta.get("data_da_reuniao") or meta.get("data") or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", written):
        return written
    try:
        dt = datetime.fromisoformat(str(source["modified_at"]).replace("Z", "+00:00"))
        return dt.astimezone(settings.timezone).date().isoformat()
    except ValueError:
        return None


def supersede_old_versions(conn: sqlite3.Connection) -> int:
    """Sugestões pendentes de uma versão de ata que já não é a atual."""
    rows = conn.execute(
        """SELECT s.suggestion_id FROM suggestions s JOIN sources src ON src.file_id = s.source_file_id
           WHERE s.origin = 'ata' AND s.review_status = 'pendente' AND src.content_hash IS NOT NULL
             AND src.sync_status = 'processed' AND s.source_version != src.content_hash"""
    ).fetchall()
    return suggestions.supersede(
        conn, [r[0] for r in rows],
        "O documento foi editado no Drive: esta sugestão era da versão anterior e foi substituída pela análise da versão atual.",
    )


def _todo(conn: sqlite3.Connection, retry_failed: bool, only_file_id: str | None) -> list[sqlite3.Row]:
    rows = conn.execute(
        """SELECT src.*, a.status AS analysis_status, a.attempts AS analysis_attempts
           FROM sources src
           LEFT JOIN analyses a ON a.file_id = src.file_id AND a.content_hash = src.content_hash
           WHERE src.authority = 'minutes' AND src.sync_status = 'processed' AND src.content_hash IS NOT NULL
           ORDER BY src.modified_at, src.name"""
    ).fetchall()
    out = []
    for r in rows:
        if only_file_id and r["file_id"] != only_file_id:
            continue
        if r["analysis_status"] is None:
            out.append(r)
        elif r["analysis_status"] == "falhou" and (retry_failed or r["analysis_attempts"] < MAX_AUTO_ATTEMPTS):
            out.append(r)
    return out


def analyze_minutes(conn: sqlite3.Connection, settings: Settings, provider: ai.Provider | None = None, *,
                    retry_failed: bool = False, only_file_id: str | None = None) -> AnalysisRun:
    run = AnalysisRun()
    provider = provider or ai.provider_for(settings)
    run.superseded = supersede_old_versions(conn)
    conn.commit()
    for src in _todo(conn, retry_failed, only_file_id):
        version = conn.execute(
            "SELECT extracted_text FROM source_versions WHERE file_id = ? AND content_hash = ?",
            (src["file_id"], src["content_hash"]),
        ).fetchone()
        if version is None:
            continue
        text = version["extracted_text"]
        members = conn.execute("SELECT * FROM members ORDER BY display_name").fetchall()
        context = list(suggestions.current_activities(conn).values())
        date = doc_date(src, settings)
        conn.commit()  # nenhuma transação aberta enquanto o provedor responde
        try:
            raw = provider.extract(text, doc_name=src["name"], doc_date=date, activities=context,
                                   members=[dict(m) for m in members])
        except ai.AIError as exc:
            _record_failure(conn, src, provider.label, str(exc))
            conn.commit()
            run.failed += 1
            run.errors.append(f"{src['name']}: {exc}")
            continue
        try:
            run.created += _save(conn, src, text, date, raw, members)
            conn.commit()
            run.analyzed += 1
        except Exception as exc:  # noqa: BLE001 — uma ata com problema não impede as outras
            conn.rollback()
            log.exception("Falha ao gravar a análise de %s", src["file_id"])
            _record_failure(conn, src, provider.label, f"Falha ao gravar a análise ({exc.__class__.__name__}).")
            conn.commit()
            run.failed += 1
    return run


def _save(conn: sqlite3.Connection, src: sqlite3.Row, text: str, date: str | None, raw: ai.RawResult,
          members: list[sqlite3.Row]) -> int:
    conn.execute("BEGIN IMMEDIATE")
    current = suggestions.current_activities(conn)  # valores do momento da gravação, não da chamada
    result = suggestions.validate(raw.items, text, current, members)
    now = db.utcnow()
    conn.execute(
        """INSERT INTO analyses (file_id, content_hash, origin, status, generated_by, attempts, created_at, updated_at)
           VALUES (?, ?, 'ata', 'ok', ?, 1, ?, ?)
           ON CONFLICT(file_id, content_hash) DO UPDATE SET status = 'ok', error = NULL,
               generated_by = excluded.generated_by, attempts = attempts + 1, updated_at = excluded.updated_at""",
        (src["file_id"], src["content_hash"], raw.generated_by, now, now),
    )
    analysis_id = conn.execute("SELECT analysis_id FROM analyses WHERE file_id = ? AND content_hash = ?",
                               (src["file_id"], src["content_hash"])).fetchone()[0]
    n, notes = suggestions.insert_drafts(conn, result.drafts, analysis_id=analysis_id, origin="ata",
                                         source_file_id=src["file_id"], source_version=src["content_hash"],
                                         doc_date=date, generated_by=raw.generated_by)
    conn.execute(
        """UPDATE analyses SET n_suggestions = ?, notes = ?, raw_response = ?, tokens_in = ?, tokens_out = ?,
               duration_ms = ? WHERE analysis_id = ?""",
        (n, json.dumps(raw.notes + result.notes + notes, ensure_ascii=False), raw.raw_response, raw.tokens_in,
         raw.tokens_out, raw.duration_ms, analysis_id),
    )
    return n


def _record_failure(conn: sqlite3.Connection, src: sqlite3.Row, generated_by: str, error: str) -> None:
    now = db.utcnow()
    conn.execute(
        """INSERT INTO analyses (file_id, content_hash, origin, status, generated_by, attempts, error, created_at, updated_at)
           VALUES (?, ?, 'ata', 'falhou', ?, 1, ?, ?, ?)
           ON CONFLICT(file_id, content_hash) DO UPDATE SET status = 'falhou', error = excluded.error,
               generated_by = excluded.generated_by, attempts = attempts + 1, updated_at = excluded.updated_at""",
        (src["file_id"], src["content_hash"], generated_by, error, now, now),
    )


# ---------------------------------------------------------------------------
# Consulta (telas)
# ---------------------------------------------------------------------------


def list_analyses(conn: sqlite3.Connection, limit: int = 30) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT a.*, s.name AS source_name, s.web_url, s.content_hash AS current_hash, s.sync_status
           FROM analyses a JOIN sources s ON s.file_id = a.file_id
           ORDER BY a.updated_at DESC, a.analysis_id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        a = dict(r)
        a["notes"] = json.loads(a["notes"] or "[]")
        a["is_current"] = a["content_hash"] == a["current_hash"]
        out.append(a)
    return out


def waiting(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Atas cuja versão atual ainda não tem análise concluída (para avisar na tela)."""
    return conn.execute(
        """SELECT src.file_id, src.name, a.status, a.error, a.attempts FROM sources src
           LEFT JOIN analyses a ON a.file_id = src.file_id AND a.content_hash = src.content_hash
           WHERE src.authority = 'minutes' AND src.sync_status = 'processed' AND src.content_hash IS NOT NULL
             AND (a.status IS NULL OR a.status = 'falhou')
           ORDER BY src.name"""
    ).fetchall()


def by_source(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    """Análise da versão atual de cada fonte (coluna Detalhe do Estado da sincronização)."""
    rows = conn.execute(
        """SELECT a.* FROM analyses a JOIN sources s ON s.file_id = a.file_id AND s.content_hash = a.content_hash"""
    ).fetchall()
    return {r["file_id"]: r for r in rows}
