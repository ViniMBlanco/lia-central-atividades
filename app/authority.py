"""Autoridade das fontes, decidida a partir do INDEX da pasta.

O INDEX é o arquivo de texto chamado `INDEX` (qualquer extensão, ou Google Doc sem
extensão). Dele saem duas coisas:
- qual planilha (e aba) é a fonte das atividades: a única que pode ser importada;
- quais documentos são de orientação (citados no INDEX).

Nenhuma regra usa a data do arquivo: "mais recente" não significa "mais confiável".
Ambiguidade (dois INDEX, duas planilhas com o mesmo nome, duas fontes citadas) nunca é
resolvida por palpite: nada é importado e o motivo aparece na tela.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass

TEXT_KINDS = ("markdown", "text", "gdoc")
SHEET_KINDS = ("xlsx", "gsheet")

AUTHORITY_LABELS = {
    "activity_register": "Fonte das atividades",
    "direction": "Orientação",
    "minutes": "Ata",
    "deprecated": "Histórico (substituído)",
    "none": "Sem autoridade confirmada",
}

_DEPRECATED = {"deprecated", "obsoleto", "substituido", "superado", "arquivado"}

# Cabeçalhos aceitos numa planilha de atividades (comparados sem acento e em minúsculas).
HEADER_ALIASES = {
    "id": ("id", "codigo", "identificador"),
    "title": ("atividade", "titulo", "tarefa"),
    "owners": ("responsaveis", "responsavel"),
    "due_date": ("prazo", "data limite", "vencimento", "entrega"),
    "front": ("frente",),
    "priority": ("prioridade",),
    "status": ("status", "estado", "situacao"),
    "next_step": ("proximo passo", "proximos passos"),
    "origin": ("origem",),
    "notes": ("notas e bloqueios", "notas", "observacoes", "bloqueios"),
}


def normalize(text: str) -> str:
    """Minúsculas, sem acentos e com espaços simples (para comparar nomes e rótulos)."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.lower().split())


def stem(name: str) -> str:
    return re.sub(r"\.[A-Za-z0-9]{1,8}$", "", name or "")


@dataclass
class RegisterPointer:
    name: str  # nome do arquivo como escrito no INDEX
    sheet: str | None  # aba citada, se houver
    line: str  # linha do INDEX que aponta a fonte (evidência)


@dataclass
class Resolution:
    """Resultado de "qual é a fonte das atividades agora?"."""

    index: sqlite3.Row | None = None
    pointer: RegisterPointer | None = None
    register: sqlite3.Row | None = None
    problem: str | None = None  # motivo legível quando não há fonte utilizável
    ambiguous: bool = False  # mais de um candidato: exige decisão humana


# ---------------------------------------------------------------------------
# Leitura do INDEX
# ---------------------------------------------------------------------------

_BACKTICK = re.compile(r"`([^`\n]+)`")
_SHEET_FILE = re.compile(r"`([^`\n]+\.xlsx)`|([\w.\-]+\.xlsx)\b", re.IGNORECASE)
_SHEET_TAB = re.compile(r"\baba\s+(?:`([^`\n]+)`|[\"“]([^\"”\n]+)[\"”]|([\wÀ-ÿ]+))", re.IGNORECASE)


class Unresolved(Exception):
    """Não há fonte utilizável; a mensagem explica por quê."""

    def __init__(self, message: str, ambiguous: bool = False):
        super().__init__(message)
        self.ambiguous = ambiguous


def parse_register_pointer(index_text: str) -> RegisterPointer:
    """Acha no INDEX a planilha indicada como fonte das atividades.

    Considera as linhas que citam uma planilha `.xlsx`. Se mais de uma for citada, vale a
    que estiver numa linha que fala de "fonte" ou "atividades"; se ainda sobrar mais de
    uma, é ambíguo.
    """
    mentions: list[RegisterPointer] = []
    for raw in index_text.split("\n"):
        line = raw.strip()
        for m in _SHEET_FILE.finditer(line):
            name = (m.group(1) or m.group(2)).strip()
            tab = _SHEET_TAB.search(line)
            sheet = next((g for g in tab.groups() if g), None) if tab else None
            mentions.append(RegisterPointer(name=name, sheet=sheet.strip() if sheet else None, line=line))
    if not mentions:
        raise Unresolved("O INDEX não cita nenhuma planilha como fonte das atividades.")
    flagged = [p for p in mentions if re.search(r"\bfonte\b|\batividade", normalize(p.line))]
    candidates = flagged or mentions
    names = {normalize(p.name) for p in candidates}
    if len(names) > 1:
        listed = ", ".join(sorted({p.name for p in candidates}))
        raise Unresolved(f"O INDEX cita mais de uma planilha como fonte ({listed}); nenhuma foi escolhida.", True)
    return candidates[0]


def register_columns(sheet: dict) -> dict[str, int] | None:
    """Colunas de uma aba com cara de registro de atividades (precisa de ID e Atividade)."""
    if not sheet.get("rows"):
        return None
    header = [normalize(str(c)) if c is not None else "" for c in sheet["rows"][0]["cells"]]
    columns: dict[str, int] = {}
    for field, aliases in HEADER_ALIASES.items():
        for i, name in enumerate(header):
            if name in aliases and field not in columns:
                columns[field] = i
    return columns if "id" in columns and "title" in columns else None


def mentioned_names(index_text: str) -> set[str]:
    """Nomes de arquivo citados no INDEX (normalizados, com e sem extensão)."""
    names: set[str] = set()
    for token in _BACKTICK.findall(index_text):
        if "." in token:
            names.add(normalize(token))
            names.add(normalize(stem(token)))
    return names


# ---------------------------------------------------------------------------
# Resolução contra as fontes do banco
# ---------------------------------------------------------------------------


def _readable(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Fontes com algum conteúdo já lido (inclusive indisponíveis: último estado confirmado)."""
    return conn.execute("SELECT * FROM sources WHERE content_hash IS NOT NULL").fetchall()


def find_index(conn: sqlite3.Connection, folder_id: str) -> sqlite3.Row:
    candidates = [
        s for s in _readable(conn) if s["kind"] in TEXT_KINDS and normalize(stem(s["name"])) == "index"
    ]
    if not candidates:
        raise Unresolved("Nenhum arquivo INDEX foi encontrado na pasta.")
    available = [s for s in candidates if s["sync_status"] == "processed"] or candidates
    if len(available) > 1:
        at_root = [s for s in available if s["parent_id"] == folder_id]
        available = at_root or available
    if len(available) > 1:
        raise Unresolved(f"Há {len(available)} arquivos INDEX na pasta; nenhum foi usado até alguém decidir qual vale.", True)
    return available[0]


def _index_text(conn: sqlite3.Connection, index: sqlite3.Row) -> str:
    row = conn.execute(
        "SELECT extracted_text FROM source_versions WHERE file_id=? AND content_hash=?",
        (index["file_id"], index["content_hash"]),
    ).fetchone()
    return row["extracted_text"] if row else ""


def resolve(conn: sqlite3.Connection, folder_id: str) -> Resolution:
    try:
        index = find_index(conn, folder_id)
    except Unresolved as exc:
        return Resolution(problem=str(exc), ambiguous=exc.ambiguous)
    try:
        pointer = parse_register_pointer(_index_text(conn, index))
    except Unresolved as exc:
        return Resolution(index=index, problem=str(exc), ambiguous=exc.ambiguous)

    # Casa pelo nome exato; Google Planilhas convertido perde a extensão. A planilha entra
    # mesmo se a leitura falhou, para a tela mostrar o motivo certo.
    wanted = normalize(pointer.name)
    matches = [
        s
        for s in conn.execute("SELECT * FROM sources WHERE kind IN ('xlsx', 'gsheet')").fetchall()
        if normalize(s["name"]) == wanted
        or (s["kind"] == "gsheet" and normalize(s["name"]) == normalize(stem(pointer.name)))
    ]
    matches = [s for s in matches if s["sync_status"] != "unavailable"] or matches
    if not matches:
        return Resolution(index=index, pointer=pointer, problem=f"O INDEX aponta {pointer.name}, que não está na pasta.")
    if len(matches) > 1:
        return Resolution(
            index=index, pointer=pointer, ambiguous=True,
            problem=f"Há {len(matches)} planilhas chamadas {pointer.name}; nenhuma foi usada até alguém decidir qual vale.",
        )
    return Resolution(index=index, pointer=pointer, register=matches[0])


# ---------------------------------------------------------------------------
# Classificação de todas as fontes
# ---------------------------------------------------------------------------


def _is_minutes(source: sqlite3.Row, meta: dict) -> bool:
    if source["kind"] not in TEXT_KINDS:
        return False
    title = normalize(source["doc_title"] or "")
    return "data_da_reuniao" in meta or title.startswith("ata ") or normalize(source["name"]).startswith("ata")


def classify(source: sqlite3.Row, res: Resolution, mentioned: set[str]) -> tuple[str, str]:
    meta = json.loads(source["doc_meta"] or "{}")
    index_name = res.index["name"] if res.index else "INDEX"
    if normalize(meta.get("status", "")) in _DEPRECATED:
        return "deprecated", f"O próprio arquivo diz “status: {meta['status']}”: aparece só como histórico, nunca como regra atual."
    if res.register is not None and source["file_id"] == res.register["file_id"]:
        sheet = f" (aba {res.pointer.sheet})" if res.pointer and res.pointer.sheet else ""
        return "activity_register", f"Apontada pelo {index_name} como fonte das atividades{sheet}."
    if res.index is not None and source["file_id"] == res.index["file_id"]:
        return "direction", "Índice do acervo: define as fontes e a ordem de precedência."
    if _is_minutes(source, meta):
        return "minutes", "Ata de reunião: pode originar sugestões, que só valem depois de revisão humana."
    if source["kind"] in TEXT_KINDS and normalize(source["name"]) in mentioned:
        return "direction", f"Documento de orientação citado no {index_name}."
    if source["kind"] in SHEET_KINDS:
        return "none", f"Planilha não apontada pelo {index_name}: sem autoridade sobre as atividades (nunca importa nem apaga)."
    if source["kind"] in TEXT_KINDS:
        return "none", f"Documento não citado no {index_name}: lido como contexto, sem autoridade confirmada."
    return "none", None


def refresh(conn: sqlite3.Connection, folder_id: str) -> Resolution:
    """Recalcula a autoridade de todas as fontes e devolve a fonte das atividades."""
    res = resolve(conn, folder_id)
    mentioned = mentioned_names(_index_text(conn, res.index)) if res.index else set()
    for source in conn.execute("SELECT * FROM sources").fetchall():
        if source["content_hash"] is None:
            authority, reason = "none", None
        else:
            authority, reason = classify(source, res, mentioned)
        conn.execute(
            "UPDATE sources SET authority=?, authority_reason=? WHERE file_id=?",
            (authority, reason, source["file_id"]),
        )
    return res
