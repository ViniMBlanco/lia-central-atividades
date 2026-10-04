"""Comece aqui: entrada para quem chega, montada a partir dos documentos de orientação.

Nada aqui é escrito pelo app sobre a Liga: propósito, frentes e regras são **trechos
copiados** dos documentos lidos do Drive (INDEX, estado atual, guia), com link para o
original. O que o próprio documento marca como parcial ou provisório aparece assim, e o
que falta vira item de "O que ainda está a confirmar" — nunca é completado por inferência.

Como cada documento é reconhecido (mesmas regras para arquivos novos):
- INDEX: o mesmo da autoridade das fontes (`authority.find_index`);
- estado atual: documento de orientação com "estado" no nome;
- guia: documento de orientação com "guia" no nome ou com o título "Comece aqui".
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import activities, authority, suggestions
from .authority import normalize, stem
from .readers import _META_LINE

# Status de cabeçalho que significam "vale como está"; os outros (parcial, rascunho...) são mostrados como parciais.
ACTIVE_STATUSES = {"ativo", "ativa", "vigente", "active", "aprovado", "aprovada", "oficial"}
_PROVISIONAL = re.compile(r"provis[oó]ri|a confirmar|ainda ser[aá] aprovad|n[aã]o (?:é )?(?:um )?texto oficial", re.IGNORECASE)
_LIST_ITEM = re.compile(r"^[-*•]\s+")
_NUMBERED = re.compile(r"^\d+[.)]\s+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý`])")
_DOC_ITEM = re.compile(r"^`([^`]+)`([^:]*):\s*(.+)$")  # - `ARQUIVO`, aba `X`: descrição


@dataclass
class Block:
    section: str
    kind: str  # p (parágrafo) | li (lista) | ol (lista numerada)
    text: str


@dataclass
class Doc:
    source: sqlite3.Row
    meta: dict[str, str]
    title: str | None
    blocks: list[Block]

    @property
    def status(self) -> str:
        return self.meta.get("status", "")

    @property
    def partial(self) -> bool:
        return bool(self.status) and normalize(self.status) not in ACTIVE_STATUSES


@dataclass
class Quote:
    text: str
    doc: Doc


@dataclass
class Front:
    name: str
    what: list[Quote] = field(default_factory=list)  # o que a frente faz (estado atual)
    who: list[Quote] = field(default_factory=list)   # pessoas e papéis (guia)
    members: list[str] = field(default_factory=list)
    open_count: int = 0


# ---------------------------------------------------------------------------
# Leitura dos documentos
# ---------------------------------------------------------------------------


def parse_blocks(text: str, title: str | None, meta: dict[str, str]) -> list[Block]:
    """Parágrafos e itens de lista do corpo (sem o título e sem o cabeçalho `chave: valor`)."""
    blocks: list[Block] = []
    section, buf, started = "", [], False

    def flush():
        if buf:
            blocks.append(Block(section, "p", " ".join(buf)))
            buf.clear()

    for raw in text.split("\n"):
        line = raw.strip()
        if not started:
            if not line or line.lstrip("#").strip() == (title or "").strip():
                continue
            m = _META_LINE.match(line)
            if m and m.group(1).lower() in meta:
                continue
            started = True
        if not line:
            flush()
        elif line.startswith("#"):
            flush()
            section = line.lstrip("#").strip()
        elif _LIST_ITEM.match(line) or _NUMBERED.match(line):
            flush()
            kind = "ol" if _NUMBERED.match(line) else "li"
            blocks.append(Block(section, kind, _NUMBERED.sub("", _LIST_ITEM.sub("", line))))
        elif blocks and blocks[-1].kind != "p" and not buf and raw[:1] in (" ", "\t"):
            blocks[-1].text += " " + line  # continuação indentada de um item de lista
        else:
            buf.append(line)
    flush()
    return blocks


def _load_docs(conn: sqlite3.Connection) -> list[Doc]:
    """Documentos de orientação e históricos, com o texto da versão atual (inclusive de fonte indisponível)."""
    rows = conn.execute(
        """SELECT s.*, v.extracted_text FROM sources s
           JOIN source_versions v ON v.file_id = s.file_id AND v.content_hash = s.content_hash
           WHERE s.authority IN ('direction', 'deprecated') AND s.kind IN ('markdown', 'text', 'gdoc')
           ORDER BY s.name"""
    ).fetchall()
    docs = []
    for r in rows:
        meta = json.loads(r["doc_meta"] or "{}")
        docs.append(Doc(source=r, meta=meta, title=r["doc_title"], blocks=parse_blocks(r["extracted_text"], r["doc_title"], meta)))
    return docs


def _name_has(doc: Doc, word: str) -> bool:
    return word in re.split(r"[^a-z0-9]+", normalize(stem(doc.source["name"])))


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text) if s.strip()]


def _starts_with(text: str, name: str) -> bool:
    t, n = normalize(text.replace("`", "")), normalize(name)
    return t == n or any(t.startswith(n + sep) for sep in (" ", ":", ","))


def match_source(name: str, sources: list[sqlite3.Row]) -> sqlite3.Row | None:
    """Arquivo da pasta com o nome citado (Google Docs/Planilhas perdem a extensão no Drive)."""
    wanted = normalize(name)
    found = [s for s in sources if normalize(s["name"]) == wanted
             or (s["kind"] in ("gdoc", "gsheet") and normalize(s["name"]) == normalize(stem(name)))]
    return ([s for s in found if s["sync_status"] != "unavailable"] or found or [None])[0]


# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------


def build(conn: sqlite3.Connection, folder_id: str, today: date) -> dict[str, Any]:
    docs = _load_docs(conn)
    sources = conn.execute("SELECT * FROM sources").fetchall()
    try:
        index_row = authority.find_index(conn, folder_id)
    except authority.Unresolved:
        index_row = None
    index = next((d for d in docs if index_row is not None and d.source["file_id"] == index_row["file_id"]), None)
    active = [d for d in docs if d.source["authority"] == "direction" and d is not index]
    state = next((d for d in active if _name_has(d, "estado")), None)
    guide = next((d for d in active if d is not state and (_name_has(d, "guia") or normalize(d.title or "") == "comece aqui")), None)
    state_paragraphs = [b for b in state.blocks if b.kind == "p"] if state else []
    guide_fronts = [b for b in guide.blocks if b.kind == "li" and "frente" in normalize(b.section) and ":" in b.text] if guide else []
    gaps: list[dict[str, str]] = []

    # Propósito: primeiro parágrafo do estado atual, copiado como está.
    purpose = Quote(state_paragraphs[0].text, state) if state_paragraphs else None
    provisional = bool(purpose and (state.partial or _PROVISIONAL.search(purpose.text)))
    if purpose is None:
        gaps.append({"text": "Propósito: nenhum documento de estado atual com uma descrição da Liga foi encontrado na pasta."})
    elif provisional:
        who = state.meta.get("responsavel_por_confirmar")
        gaps.append({"text": f"Propósito: o próprio {state.source['name']} diz que é uma descrição provisória"
                             + (f" (status: {state.status})" if state.status else "")
                             + (f"; quem confirma é {who}, editando o documento no Drive" if who else "") + "."})

    # Frentes: das pessoas cadastradas, das atividades e do guia; descrição e papéis copiados dos documentos,
    # na ordem em que o estado atual as cita.
    members = conn.execute("SELECT * FROM members ORDER BY display_name").fetchall()
    names = [m["front"] for m in members] + activities.known_fronts(conn) + [b.text.split(":", 1)[0].strip() for b in guide_fronts]
    state_text = normalize(" ".join(b.text for b in state_paragraphs))
    ordered = sorted(dict.fromkeys(n for n in names if n),
                     key=lambda n: (state_text.find(normalize(n)) if normalize(n) in state_text else 10**6, normalize(n)))
    open_rows = activities.list_activities(conn, today, status="abertas")
    front_blocks: set[int] = set()
    fronts: list[Front] = []
    for name in ordered:
        f = Front(name)
        for b in state_paragraphs[1:]:
            hits = [s for s in sentences(b.text) if _starts_with(s, name)]
            if hits:
                front_blocks.add(id(b))
                f.what += [Quote(s, state) for s in hits]
        f.who = [Quote(b.text.split(":", 1)[1].strip(), guide) for b in guide_fronts if _starts_with(b.text, name)]
        f.members = [m["display_name"] for m in members if normalize(m["front"]) == normalize(name)]
        f.open_count = sum(1 for a in open_rows if normalize(a["front"] or "") == normalize(name))
        if not f.what and not f.who:
            gaps.append({"text": f"Frente {name}: nenhum documento de orientação descreve o que ela faz."})
        fronts.append(f)

    # Regras de trabalho: parágrafos do INDEX e os do estado atual que não são propósito nem frentes;
    # passos numerados do guia.
    rules = [Quote(b.text, index) for b in index.blocks if b.kind == "p"] if index else []
    rules += [Quote(b.text, state) for b in state_paragraphs[1:] if id(b) not in front_blocks]
    steps = [Quote(b.text, guide) for b in guide.blocks if b.kind == "ol"] if guide else []

    # Documentos principais: a lista do INDEX (com a descrição dada por ele) e os demais de orientação.
    documents: list[dict[str, Any]] = []
    seen: set[str] = set()
    if index:
        documents.append({"source": index.source, "description": None, "doc": index})
        seen.add(index.source["file_id"])
        for b in index.blocks:
            m = _DOC_ITEM.match(b.text) if b.kind == "li" else None
            if not m:
                continue
            src = match_source(m.group(1), sources)
            if src is None:
                gaps.append({"text": f"{m.group(1)}: citado no {index.source['name']}, mas não está na pasta do Drive."})
                documents.append({"source": None, "name": m.group(1), "description": m.group(3), "doc": None})
                continue
            if src["sync_status"] == "unavailable":
                gaps.append({"text": f"{src['name']}: citado no {index.source['name']}, mas indisponível no Drive "
                                     "(o último conteúdo lido continua sendo usado)."})
            seen.add(src["file_id"])
            documents.append({"source": src, "description": m.group(3),
                              "doc": next((d for d in docs if d.source["file_id"] == src["file_id"]), None)})
    else:
        gaps.append({"text": "Nenhum INDEX foi encontrado na pasta: não há lista de documentos de referência "
                             "nem fonte das atividades confirmada."})
    for d in docs:
        if d.source["file_id"] not in seen:
            documents.append({"source": d.source, "description": None, "doc": d})
        if d.partial and d is not state and d.source["authority"] == "direction":
            gaps.append({"text": f"{d.source['name']} está marcado como “{d.status}”: trate o conteúdo como parcial."})

    # Atividades sem dono ou sem prazo: lacunas do registro, mostradas como tais.
    no_owner = sum(1 for a in open_rows if not a["owners"])
    no_due = sum(1 for a in open_rows if not a["due_date"])
    if no_owner:
        gaps.append({"text": f"{no_owner} atividade(s) aberta(s) com responsável a confirmar.",
                     "href": "/atividades?responsavel=nenhum&estado=abertas"})
    if no_due:
        gaps.append({"text": f"{no_due} atividade(s) aberta(s) sem prazo definido.",
                     "href": "/atividades?prazo=sem_prazo&estado=abertas"})

    # Nomes de arquivo citados entre crases viram link para o Drive.
    links = {normalize(s["name"]): s["web_url"] for s in sources if s["web_url"]}
    links |= {normalize(stem(s["name"])) + ext: s["web_url"] for s in sources if s["web_url"] and s["kind"] == "gdoc"
              for ext in (".md", ".txt", ".docx")}
    links |= {normalize(stem(s["name"])) + ".xlsx": s["web_url"] for s in sources if s["web_url"] and s["kind"] == "gsheet"}
    return {
        "has_sources": bool(sources),
        "index": index, "state": state, "guide": guide,
        "purpose": purpose, "purpose_provisional": provisional,
        "fronts": fronts, "rules": rules, "steps": steps, "documents": documents, "gaps": gaps,
        "reviewers": [(m["display_name"], "todas as frentes" if m["review_scope"] == "all" else f"frente {m['front']}")
                      for m in members if m["review_scope"] != "none"],
        "links": links,
    }


def first_action(conn: sqlite3.Connection, member: sqlite3.Row | None, today: date) -> dict[str, Any] | None:
    """Primeira ação de quem chega: a atividade aberta de prazo mais próximo; sem atividade, a revisão pendente."""
    if member is None:
        return None
    mine = activities.list_activities(conn, today, owner=member["member_id"], status="abertas", order="prazo")
    unowned = [a for a in activities.list_activities(conn, today, owner="nenhum", status="abertas")
               if normalize(a["front"] or "") == normalize(member["front"])]
    return {"activity": mine[0] if mine else None, "open": mine, "to_review": suggestions.pending_for(conn, member),
            "unowned_in_front": unowned}
