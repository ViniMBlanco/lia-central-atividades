import pytest

from app import sync
from app.drive import GDOC_MIME
from app.google_auth import NotConnected

from .conftest import FIXTURES, ROOT_ID

CARGA = [
    "INDEX.md", "ESTADO-ATUAL.md", "GUIA_INICIAL.md",
    "PLANO_EDITORIAL_ANTIGO.md", "Ata_registro.xlsx", "Ata_2026-10-01.md",
]


def run(cfg, drive, trigger="manual"):
    result = sync.run_sync(cfg, trigger, client_factory=lambda: drive)
    assert result is not None
    return result


def carga_inicial(drive):
    return {name: drive.add_fixture(f"01_CARGA_INICIAL/{name}") for name in CARGA}


def source(conn, fid):
    return conn.execute("SELECT * FROM sources WHERE file_id=?", (fid,)).fetchone()


def n_versions(conn, fid=None):
    if fid:
        return conn.execute("SELECT COUNT(*) FROM source_versions WHERE file_id=?", (fid,)).fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM source_versions").fetchone()[0]


def test_carga_inicial_processa_os_seis_arquivos_com_link(cfg, drive, conn):
    ids = carga_inicial(drive)
    r = run(cfg, drive)
    assert r.ok and r.error is None
    assert r.counts["seen"] == 6 and r.counts["processed"] == 6 and r.counts["new"] == 6
    assert sorted(r.changed) == sorted(ids.values())
    for name, fid in ids.items():
        s = source(conn, fid)
        assert s["sync_status"] == "processed", name
        assert s["web_url"] == f"https://drive/{fid}"
        assert s["path"] == f"LIA case teste/{name}"
        assert s["content_hash"]
    assert source(conn, ids["Ata_registro.xlsx"])["kind"] == "xlsx"
    state = conn.execute("SELECT * FROM sync_state").fetchone()
    assert state["folder_name"] == "LIA case teste" and state["last_success_at"] and state["last_error"] is None


def test_segunda_sincronizacao_sem_mudancas_nao_baixa_nem_duplica(cfg, drive, conn):
    carga_inicial(drive)
    run(cfg, drive)
    downloads, versions = drive.download_count, n_versions(conn)
    r = run(cfg, drive)
    assert r.ok and r.changed == []
    assert drive.download_count == downloads
    assert n_versions(conn) == versions


def test_edicao_gera_nova_versao_da_mesma_fonte(cfg, drive, conn):
    ids = carga_inicial(drive)
    run(cfg, drive)
    fid = ids["Ata_2026-10-01.md"]
    old_hash = source(conn, fid)["content_hash"]
    drive.edit(fid, (FIXTURES / "01_CARGA_INICIAL/Ata_2026-10-01.md").read_bytes() + "\nAdendo.\n".encode())
    r = run(cfg, drive)
    assert r.changed == [fid] and r.counts["changed"] == 1
    assert source(conn, fid)["content_hash"] != old_hash
    assert n_versions(conn, fid) == 2
    assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 6  # sem fonte duplicada


def test_renomear_preserva_identidade_e_nao_reprocessa_conteudo(cfg, drive, conn):
    ids = carga_inicial(drive)
    run(cfg, drive)
    fid = ids["GUIA_INICIAL.md"]
    drive.rename(fid, "GUIA_INICIAL_v2.md")
    r = run(cfg, drive)
    assert r.changed == []
    s = source(conn, fid)
    assert s["name"] == "GUIA_INICIAL_v2.md" and s["sync_status"] == "processed"
    assert n_versions(conn, fid) == 1


def test_formatos_nao_suportados_ficam_ignorados_com_motivo(cfg, drive, conn):
    docx = drive.add_fixture("02_ADICIONAR_DEPOIS_DA_CARGA/Ata_2026-10-03.docx")
    img = drive.add_file("quadro.jpg", b"\xff\xd8", mime="image/jpeg")
    r = run(cfg, drive)
    assert r.counts["ignored"] == 2 and r.changed == []
    assert source(conn, docx)["sync_status"] == "ignored"
    assert "Documentos Google" in source(conn, docx)["status_reason"]
    assert "OCR" in source(conn, img)["status_reason"]
    assert n_versions(conn) == 0  # nenhum conteúdo inventado


def test_google_doc_nativo_e_exportado_como_texto(cfg, drive, conn):
    texto = (FIXTURES / "02_ADICIONAR_DEPOIS_DA_CARGA/Ata_2026-10-03.md").read_text(encoding="utf-8").lstrip("# ")
    fid = drive.add_file("Ata_2026-10-03", texto.encode("utf-8"), mime=GDOC_MIME)
    r = run(cfg, drive)
    s = source(conn, fid)
    assert r.changed == [fid]
    assert s["kind"] == "gdoc" and s["sync_status"] == "processed"
    assert s["doc_title"] == "Ata de reunião de 3 de outubro de 2026"
    assert '"data_da_reuniao": "2026-10-03"' in s["doc_meta"]


def test_subpastas_sao_lidas_recursivamente(cfg, drive, conn):
    sub = drive.add_folder("Atas")
    subsub = drive.add_folder("2026", parent=sub)
    fid = drive.add_fixture("02_ADICIONAR_DEPOIS_DA_CARGA/Ata_2026-10-04.md", parent=subsub)
    run(cfg, drive)
    assert source(conn, fid)["path"] == "LIA case teste/Atas/2026/Ata_2026-10-04.md"


def test_falha_em_um_arquivo_nao_derruba_os_outros(cfg, drive, conn):
    ids = carga_inicial(drive)
    bad = ids["INDEX.md"]
    drive.fail_ids.add(bad)
    r = run(cfg, drive)
    assert r.ok and r.counts["failed"] == 1 and r.counts["processed"] == 5
    s = source(conn, bad)
    assert s["sync_status"] == "failed" and "HTTP 500" in s["status_reason"]
    # Na próxima execução, o arquivo é tentado de novo.
    drive.fail_ids.clear()
    run(cfg, drive)
    assert source(conn, bad)["sync_status"] == "processed"


def test_falha_na_listagem_nao_vira_ausencia_de_arquivos(cfg, drive, conn):
    ids = carga_inicial(drive)
    run(cfg, drive)
    last_success = conn.execute("SELECT last_success_at FROM sync_state").fetchone()[0]
    drive.fail_listing = True
    r = run(cfg, drive)
    assert not r.ok and "HTTP 503" in r.error
    statuses = {row[0] for row in conn.execute("SELECT sync_status FROM sources")}
    assert statuses == {"processed"}  # nada marcado como indisponível
    state = conn.execute("SELECT * FROM sync_state").fetchone()
    assert state["last_success_at"] == last_success and state["last_error"] == r.error
    assert len(ids) == conn.execute("SELECT COUNT(*) FROM source_versions").fetchone()[0]


def test_arquivo_removido_na_lixeira_ou_movido_fica_indisponivel(cfg, drive, conn):
    ids = carga_inicial(drive)
    run(cfg, drive)
    removido, lixeira, movido = ids["INDEX.md"], ids["GUIA_INICIAL.md"], ids["Ata_2026-10-01.md"]
    del drive.files[removido]
    drive.files[lixeira]["trashed"] = True
    drive.files[movido]["parents"] = ["OUTRA_PASTA"]
    r = run(cfg, drive)
    assert r.ok and r.counts["unavailable"] == 3
    assert "Removido" in source(conn, removido)["status_reason"]
    assert "lixeira" in source(conn, lixeira)["status_reason"]
    assert "movido" in source(conn, movido)["status_reason"]
    s = source(conn, removido)
    assert s["sync_status"] == "unavailable" and s["content_hash"]  # último conteúdo confirmado mantido
    # Voltando para a pasta, volta a ser processado (sem nova versão se o conteúdo é o mesmo).
    drive.files[movido]["parents"] = [ROOT_ID]
    run(cfg, drive)
    assert source(conn, movido)["sync_status"] == "processed"
    assert n_versions(conn, movido) == 1


def test_sem_conta_conectada_a_execucao_falha_com_mensagem(cfg, conn):
    def factory():
        raise NotConnected("Nenhuma conta do Google conectada.")

    r = sync.run_sync(cfg, "auto", client_factory=factory)
    assert not r.ok and "Nenhuma conta" in r.error
    row = conn.execute("SELECT * FROM sync_runs").fetchone()
    assert row["ok"] == 0 and row["trigger"] == "auto"


def test_pasta_inacessivel_aborta(cfg, drive, conn):
    del drive.files[ROOT_ID]
    r = run(cfg, drive)
    assert not r.ok and "não foi encontrada" in r.error


def test_execucoes_nao_se_sobrepoem(cfg, drive):
    sync._lock.acquire()
    try:
        assert sync.run_sync(cfg, "manual", client_factory=lambda: drive) is None
    finally:
        sync._lock.release()


@pytest.mark.parametrize("relpath", ["03_CONFLITO/Ata - copia vazia.xlsx"])
def test_planilha_vazia_e_processada_com_observacao(cfg, drive, conn, relpath):
    fid = drive.add_fixture(relpath)
    run(cfg, drive)
    s = source(conn, fid)
    assert s["sync_status"] == "processed" and "sem linhas de dados" in s["status_reason"]
