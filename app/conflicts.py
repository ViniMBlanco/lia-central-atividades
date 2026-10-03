"""Conflitos de fonte: quando os arquivos não deixam claro qual é a verdade.

Três situações viram conflito:
- planilha que não é a apontada pelo INDEX mas pode ser confundida com ela: nome parecido
  (palavra em comum com a planilha apontada, como "Ata - copia vazia" × "Ata_registro") ou
  cabeçalho de registro de atividades (colunas ID e Atividade), vazia ou não. Ela nunca
  importa nem apaga nada. Uma planilha sem nenhuma das duas coisas fica só "sem autoridade";
- fonte ambígua: dois INDEX, duas planilhas com o nome apontado, INDEX citando duas planilhas;
- o INDEX passa a apontar outra planilha depois da importação.

Um conflito nunca muda atividade. Ele fica visível até uma pessoa com permissão registrar a
decisão (estado "resolvido"); se a situação some sozinha (arquivo removido, INDEX corrigido),
o conflito aberto vira "superado". A mesma situação não é registrada duas vezes; uma versão
nova do arquivo abre um conflito novo, porque a decisão anterior valia para outro conteúdo.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass

from . import db
from .authority import SHEET_KINDS, Resolution, normalize, register_columns, stem

KIND_LABELS = {
    "planilha_sem_autoridade": "Planilha sem autoridade parecida com a fonte das atividades",
    "fonte_ambigua": "Fonte das atividades ambígua",
    "troca_de_fonte": "O INDEX aponta outra planilha",
}
STATUS_LABELS = {"aberto": "Aguardando decisão", "resolvido": "Decidido", "superado": "Superado"}

# Palavras que não contam para "nome parecido" (marcas de cópia/versão e ligações).
_NAME_NOISE = {"copia", "copy", "de", "da", "do", "das", "dos", "e", "final", "novo", "nova", "versao", "vazia", "vazio"}


class NotAllowed(Exception):
    pass


@dataclass
class Finding:
    kind: str
    key: str
    description: str
    file_id: str | None = None
    source_version: str | None = None


def can_decide(member: sqlite3.Row | None) -> bool:
    """Conflitos de fonte afetam todas as frentes: só quem revisa todas as frentes decide."""
    return member is not None and member["review_scope"] == "all"


# ---------------------------------------------------------------------------
# Detecção (chamada a cada sincronização concluída, na transação da interpretação)
# ---------------------------------------------------------------------------


def detect(conn: sqlite3.Connection, res: Resolution, imported: sqlite3.Row | None) -> list[Finding]:
    findings: list[Finding] = []
    if imported is not None:
        current = f"as atividades continuam as importadas de {imported['file_name']}"
    elif res.register is not None:
        current = f"a fonte apontada pelo INDEX continua sendo {res.register['name']}"
    else:
        current = "nenhuma fonte foi importada ainda"

    official = {imported["file_id"]} if imported is not None else set()
    if res.register is not None:
        official.add(res.register["file_id"])
    # Nomes com que uma planilha pode ser confundida: a apontada pelo INDEX e a importada.
    reference = {n for n in (res.pointer.name if res.pointer else None,
                             imported["file_name"] if imported is not None else None) if n}
    # 'failed' entra com o último conteúdo lido: falha de leitura não encerra conflito.
    for src in conn.execute(
        f"""SELECT * FROM sources WHERE kind IN ({','.join('?' * len(SHEET_KINDS))})
            AND content_hash IS NOT NULL AND sync_status IN ('processed', 'failed')""",
        SHEET_KINDS,
    ):
        if src["file_id"] in official:
            continue
        summary = _lookalike(conn, src, reference)
        if summary is None:
            continue
        findings.append(Finding(
            kind="planilha_sem_autoridade",
            key=f"{src['file_id']}:{src['content_hash']}",
            file_id=src["file_id"],
            source_version=src["content_hash"],
            description=f"{summary} Ela não é a planilha apontada pelo INDEX: nada foi importado nem apagado, "
                        f"e {current}.",
        ))

    if res.ambiguous and res.problem:
        keep = ("As atividades já importadas continuam valendo." if imported is not None
                else "Nenhuma atividade foi importada por causa disso.")
        findings.append(Finding(
            kind="fonte_ambigua",
            key=hashlib.sha256(res.problem.encode("utf-8")).hexdigest()[:16],
            file_id=res.index["file_id"] if res.index is not None else None,
            description=f"{res.problem} {keep}",
        ))

    if imported is not None and res.register is not None and res.register["file_id"] != imported["file_id"]:
        findings.append(Finding(
            kind="troca_de_fonte",
            key=f"{res.register['file_id']}:{res.register['content_hash'] or ''}",
            file_id=res.register["file_id"],
            source_version=res.register["content_hash"],
            description=f"O INDEX agora aponta {res.register['name']} como fonte das atividades, mas as atividades "
                        f"foram importadas de {imported['file_name']}. A troca não é automática: nada foi "
                        "importado da nova planilha e nenhuma atividade mudou.",
        ))
    return findings


def name_words(name: str) -> set[str]:
    """Palavras significativas do nome, sem extensão, acentos, números e marcas de cópia."""
    words = re.split(r"[^a-z0-9]+", normalize(stem(name)))
    return {w for w in words if len(w) >= 3 and not w.isdigit() and not re.fullmatch(r"v\d+", w)
            and w not in _NAME_NOISE}


def _lookalike(conn: sqlite3.Connection, src: sqlite3.Row, reference: set[str]) -> str | None:
    """Resumo da planilha se ela puder ser confundida com a fonte das atividades; senão None."""
    shared = sorted(set().union(*(name_words(src["name"]) & name_words(n) for n in reference))) if reference else []
    version = conn.execute(
        "SELECT structured_json FROM source_versions WHERE file_id = ? AND content_hash = ?",
        (src["file_id"], src["content_hash"]),
    ).fetchone()
    sheets = json.loads(version["structured_json"]).get("sheets", []) if version else []
    tabs, ids = [], []
    for sheet in sheets:
        columns = register_columns(sheet)
        if columns is None:
            continue
        tabs.append(sheet["name"])
        for r in sheet["rows"][1:]:
            cells = r["cells"]
            value = cells[columns["id"]] if columns["id"] < len(cells) else None
            if value not in (None, ""):
                ids.append(str(value).strip())
    if not tabs and not shared:
        return None

    why = []
    if shared:
        names = " / ".join(sorted(reference))
        why.append(f"tem nome parecido com {names} (em comum: {', '.join(f'“{w}”' for w in shared)})")
    if tabs:
        why.append(f"tem o cabeçalho de um registro de atividades (aba {', '.join(tabs)})")
    text = f"{src['name']} " + " e ".join(why)
    if ids:
        listed = ", ".join(ids[:5]) + (f" e mais {len(ids) - 5}" if len(ids) > 5 else "")
        return f"{text}, com {len(ids)} linha(s) de atividade ({listed})."
    if tabs:
        return f"{text}, mas nenhuma linha preenchida."
    if not any(sheet.get("rows") for sheet in sheets):
        return f"{text}, mas está vazia."
    return f"{text}, mas não tem as colunas de um registro de atividades (ID e Atividade)."


def refresh(conn: sqlite3.Connection, res: Resolution, imported: sqlite3.Row | None) -> list[sqlite3.Row]:
    """Registra os conflitos atuais (sem duplicar) e encerra os abertos que sumiram."""
    now = db.utcnow()
    current_ids = []
    for f in detect(conn, res, imported):
        row = conn.execute(
            "SELECT conflict_id FROM conflicts WHERE kind = ? AND conflict_key = ?", (f.kind, f.key)
        ).fetchone()
        if row is None:
            cur = conn.execute(
                """INSERT INTO conflicts (kind, conflict_key, file_id, source_version, description, created_at, last_seen_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (f.kind, f.key, f.file_id, f.source_version, f.description, now, now),
            )
            current_ids.append(cur.lastrowid)
        else:
            # Um conflito superado que volta a acontecer reabre; um decidido continua decidido.
            conn.execute(
                """UPDATE conflicts SET description = ?, last_seen_at = ?,
                       closed_at = CASE WHEN status = 'superado' THEN NULL ELSE closed_at END,
                       status = CASE WHEN status = 'superado' THEN 'aberto' ELSE status END
                   WHERE conflict_id = ?""",
                (f.description, now, row["conflict_id"]),
            )
            current_ids.append(row["conflict_id"])
    # Sem lista vazia em SQL ("NOT IN (NULL)" nunca é verdadeiro): -1 não é id válido.
    placeholders = ",".join("?" * len(current_ids)) or "-1"
    conn.execute(
        f"""UPDATE conflicts SET status = 'superado', closed_at = ?
            WHERE status = 'aberto' AND conflict_id NOT IN ({placeholders})""",
        (now, *current_ids),
    )
    if not current_ids:
        return []
    return conn.execute(
        f"""SELECT c.*, m.display_name AS resolver_name FROM conflicts c
            LEFT JOIN members m ON m.member_id = c.resolved_by
            WHERE c.conflict_id IN ({placeholders})""",
        current_ids,
    ).fetchall()


# ---------------------------------------------------------------------------
# Consulta e decisão
# ---------------------------------------------------------------------------


def list_conflicts(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    """Abertos primeiro; depois os encerrados mais recentes."""
    return conn.execute(
        """SELECT c.*, s.name AS source_name, s.web_url, m.display_name AS resolver_name
           FROM conflicts c
           LEFT JOIN sources s ON s.file_id = c.file_id
           LEFT JOIN members m ON m.member_id = c.resolved_by
           ORDER BY c.status != 'aberto', COALESCE(c.closed_at, c.created_at) DESC, c.conflict_id DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()


def count_open(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM conflicts WHERE status = 'aberto'").fetchone()[0]


def decide(conn: sqlite3.Connection, conflict_id: int, member: sqlite3.Row | None, resolution: str) -> None:
    """Registra a decisão humana. Não altera atividades nem arquivos: só encerra o conflito."""
    if not can_decide(member):
        raise NotAllowed("Só quem revisa sugestões de todas as frentes (Bruno) pode decidir conflitos de fonte.")
    text = " ".join((resolution or "").split())[:500]
    if len(text) < 3:
        raise ValueError("Escreva a decisão e o motivo antes de registrar.")
    row = conn.execute("SELECT status FROM conflicts WHERE conflict_id = ?", (conflict_id,)).fetchone()
    if row is None:
        raise LookupError("Conflito não encontrado.")
    if row["status"] != "aberto":
        raise ValueError("Este conflito já foi encerrado; nada foi registrado de novo.")
    conn.execute(
        """UPDATE conflicts SET status = 'resolvido', resolved_by = ?, resolution = ?, closed_at = ?
           WHERE conflict_id = ? AND status = 'aberto'""",
        (member["member_id"], text, db.utcnow(), conflict_id),
    )
