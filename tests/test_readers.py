import pytest

from app.drive import FOLDER_MIME, GDOC_MIME, GSHEET_MIME
from app.readers import ReadError, classify, extract, parse_header, read_text, read_xlsx

from .conftest import FIXTURES


@pytest.mark.parametrize(
    "name, mime, kind",
    [
        ("INDEX.md", "application/octet-stream", "markdown"),  # Drive costuma não reconhecer .md
        ("INDEX.md", "text/plain", "markdown"),
        ("Ata_registro.xlsx", "application/octet-stream", "xlsx"),
        ("Ata_2026-10-03", GDOC_MIME, "gdoc"),  # Doc convertido não tem extensão
        ("Planilha", GSHEET_MIME, "gsheet"),
        ("sub", FOLDER_MIME, "folder"),
        ("notas.txt", "text/plain", "text"),
    ],
)
def test_classifica_formatos_suportados(name, mime, kind):
    assert classify(name, mime) == (kind, None)


@pytest.mark.parametrize(
    "name, mime, trecho",
    [
        ("Ata_2026-10-03.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "Documentos Google"),
        ("foto.png", "image/png", "OCR"),
        ("reuniao.mp4", "video/mp4", "transcrição"),
        ("scan.pdf", "application/pdf", "PDF"),
        ("slides", "application/vnd.google-apps.presentation", "Apresentação"),
        ("atalho", "application/vnd.google-apps.shortcut", "Atalho"),
        ("dados.bin", "application/octet-stream", "não processado"),
    ],
)
def test_formato_nao_suportado_e_ignorado_com_motivo(name, mime, trecho):
    kind, reason = classify(name, mime)
    assert kind is None
    assert trecho in reason


def test_cabecalho_dos_markdowns_da_carga_inicial():
    plano = read_text((FIXTURES / "01_CARGA_INICIAL/PLANO_EDITORIAL_ANTIGO.md").read_bytes())
    assert plano.title == "Rascunho antigo do plano editorial"
    assert plano.meta["status"] == "deprecated"  # sem os dois espaços do fim da linha
    assert plano.meta["substituido_por"] == "GUIA_INICIAL.md em 2026-10-01"

    estado = read_text((FIXTURES / "01_CARGA_INICIAL/ESTADO-ATUAL.md").read_bytes())
    assert estado.meta == {"status": "parcial", "atualizado_em": "2026-10-01", "responsavel_por_confirmar": "Bruno"}

    ata = read_text((FIXTURES / "01_CARGA_INICIAL/Ata_2026-10-01.md").read_bytes())
    assert ata.meta["data_da_reuniao"] == "2026-10-01"
    assert "Participaram" not in ata.meta  # o cabeçalho termina na primeira frase


def test_cabecalho_de_google_doc_exportado():
    # Exportação text/plain do Google: BOM, CRLF, sem "#", às vezes linhas em branco entre parágrafos.
    texto = "﻿Ata de reunião de 3 de outubro de 2026\r\n\r\nstatus: ativo\r\n\r\ndata_da_reuniao: 2026-10-03\r\n\r\nParticiparam Ana e Bruno.\r\n"
    title, meta = parse_header(read_text(texto.encode("utf-8")).text)
    assert title == "Ata de reunião de 3 de outubro de 2026"
    assert meta == {"status": "ativo", "data_da_reuniao": "2026-10-03"}


def test_hash_ignora_espacos_no_fim_da_linha_e_quebra_crlf():
    a = read_text("# T\n\nstatus: ativo  \nTexto.\n".encode())
    b = read_text("# T\r\n\r\nstatus: ativo\r\nTexto.".encode())
    assert a.content_hash == b.content_hash
    assert read_text("# T\nOutro texto".encode()).content_hash != a.content_hash


def test_texto_que_nao_e_utf8_falha_em_vez_de_virar_vazio():
    with pytest.raises(ReadError):
        read_text("Ação".encode("utf-16"))


def test_planilha_de_registro():
    x = read_xlsx((FIXTURES / "01_CARGA_INICIAL/Ata_registro.xlsx").read_bytes())
    (aba,) = x.structured["sheets"]
    assert aba["name"] == "Atividades"
    header, *linhas = aba["rows"]
    assert header["cells"][:4] == ["ID", "Atividade", "Responsáveis", "Prazo"]
    por_id = {r["cells"][0]: r["cells"] for r in linhas}
    assert sorted(por_id) == ["ACT-101", "ACT-102", "ACT-103", "ACT-104"]
    assert por_id["ACT-104"][2] == "Ana; Davi"  # dois responsáveis preservados
    assert por_id["ACT-103"][6] == "Bloqueada"
    assert por_id["ACT-101"][3] == "2026-10-05T12:00:00"  # serial 46300,5 do Excel
    assert x.note is None


def test_planilha_vazia_homonima_e_lida_sem_inventar_dados():
    x = read_xlsx((FIXTURES / "03_CONFLITO/Ata - copia vazia.xlsx").read_bytes())
    (aba,) = x.structured["sheets"]
    assert aba["name"] == "Ata"
    assert len(aba["rows"]) == 1  # só o cabeçalho; a linha 2 estilizada e vazia é descartada
    assert "sem linhas de dados" in x.note


def test_planilha_corrompida_falha():
    with pytest.raises(ReadError):
        read_xlsx(b"isto nao e um zip")


def test_arquivo_grande_demais_falha():
    with pytest.raises(ReadError):
        extract("markdown", b"x" * (10 * 1024 * 1024 + 1))


def test_cabecalho_depois_do_cabecalho_de_pagina_do_google_docs():
    """Google Doc convertido do .docx da ata de 03/10: o cabeçalho de página vem antes do título."""
    text = ("LIGA IA UFSCAR     /     CASE TÉCNICO\nAta de reunião de 3 de outubro de 2026\nstatus: ativo\n"
            "data_da_reuniao: 2026-10-03\nParticiparam Ana e Bruno.\nNota: isto é corpo, não cabeçalho.\n")
    title, meta = parse_header(text)
    assert title == "Ata de reunião de 3 de outubro de 2026"
    assert meta == {"status": "ativo", "data_da_reuniao": "2026-10-03"}


def test_dois_pontos_no_corpo_nao_viram_cabecalho():
    assert parse_header("# Título\n\nParágrafo de abertura.\n\nNota: com dois pontos no corpo.") == ("Título", {})
