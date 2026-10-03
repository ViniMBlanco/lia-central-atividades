"""Fase 3: conflitos de fonte, fonte indisponível e falhas da sincronização."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import activities, conflicts

from .test_importer import CABECALHO, INDEX, ids, status, xlsx
from .test_sync import carga_inicial, run

HOJE = date(2026, 10, 3)
VAZIA = "03_CONFLITO/Ata - copia vazia.xlsx"


def todos(conn):
    return conn.execute("SELECT * FROM conflicts ORDER BY conflict_id").fetchall()


def membro(conn, member_id):
    return conn.execute("SELECT * FROM members WHERE member_id = ?", (member_id,)).fetchone()


def n_activities(conn):
    return conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]


# ---------------------------------------------------------------------------
# Planilha vazia com nome parecido (spec §9, "Arquivo homônimo")
# ---------------------------------------------------------------------------


def test_planilha_vazia_vira_conflito_visivel_sem_apagar(cfg, drive, conn):
    carga_inicial(drive)
    run(cfg, drive)
    fid = drive.add_fixture(VAZIA)
    run(cfg, drive)
    assert n_activities(conn) == 4
    assert status(conn)["state"] == "importada"
    [c] = todos(conn)
    assert c["kind"] == "planilha_sem_autoridade" and c["status"] == "aberto" and c["file_id"] == fid
    assert "Ata - copia vazia.xlsx" in c["description"] and "nenhuma linha preenchida" in c["description"]
    assert "nada foi importado nem apagado" in c["description"]
    assert "continuam as importadas de Ata_registro.xlsx" in c["description"]
    src = conn.execute("SELECT authority FROM sources WHERE file_id = ?", (fid,)).fetchone()
    assert src["authority"] == "none"


def test_conflito_nao_duplica_em_novas_sincronizacoes(cfg, drive, conn):
    carga_inicial(drive)
    drive.add_fixture(VAZIA)
    run(cfg, drive)
    run(cfg, drive)
    run(cfg, drive)
    assert len(todos(conn)) == 1


def test_vazia_antes_da_importacao_nao_atrapalha_a_importacao(cfg, drive, conn):
    drive.add_fixture(VAZIA)
    carga_inicial(drive)
    run(cfg, drive)
    assert n_activities(conn) == 4
    assert [c["kind"] for c in todos(conn)] == ["planilha_sem_autoridade"]


def test_planilha_nao_apontada_com_dados_lista_os_ids(cfg, drive, conn):
    carga_inicial(drive)
    run(cfg, drive)
    drive.add_file("Registro paralelo.xlsx", xlsx([CABECALHO, ["ACT-101", "Outra versão", "Davi"], ["ACT-900", "Nova"]]))
    run(cfg, drive)
    [c] = todos(conn)
    assert "2 linha(s) de atividade" in c["description"] and "ACT-101, ACT-900" in c["description"]
    assert activities.get(conn, "ACT-101")["owners"][0]["member_id"] == "U-A"
    assert activities.get(conn, "ACT-900") is None


def test_planilha_sem_cara_de_registro_nao_gera_conflito(cfg, drive, conn):
    carga_inicial(drive)
    drive.add_file("Orcamento.xlsx", xlsx([["Item", "Valor"], ["Café", 10]], sheet="Gastos"))
    run(cfg, drive)
    assert todos(conn) == []


def test_nome_parecido_sem_cabecalho_tambem_vira_conflito(cfg, drive, conn):
    # "Caso novo da mesma natureza": cópia totalmente vazia, sem nem o cabeçalho.
    carga_inicial(drive)
    run(cfg, drive)
    drive.add_file("Ata_registro_v2.xlsx", xlsx([]))
    drive.add_file("Ata_registro (1).xlsx", xlsx([["Item", "Valor"], ["Café", 10]], sheet="Gastos"))
    run(cfg, drive)
    descr = sorted(c["description"] for c in todos(conn))
    assert len(descr) == 2
    assert descr[0].startswith("Ata_registro (1).xlsx tem nome parecido com Ata_registro.xlsx")
    assert "não tem as colunas de um registro" in descr[0]
    assert descr[1].startswith("Ata_registro_v2.xlsx tem nome parecido") and "está vazia" in descr[1]
    assert n_activities(conn) == 4 and status(conn)["state"] == "importada"


def test_copia_vazia_do_material_tem_nome_parecido_e_cabecalho(cfg, drive, conn):
    carga_inicial(drive)
    drive.add_fixture(VAZIA)
    run(cfg, drive)
    [c] = todos(conn)
    assert "nome parecido com Ata_registro.xlsx (em comum: “ata”)" in c["description"]
    assert "cabeçalho de um registro de atividades (aba Ata)" in c["description"]


@pytest.mark.parametrize("name, words", [
    ("Ata - copia vazia.xlsx", {"ata"}),
    ("Ata_registro.xlsx", {"ata", "registro"}),
    ("Ata_registro (1).xlsx", {"ata", "registro"}),
    ("Cópia de Ata_registro v2.xlsx", {"ata", "registro"}),
    ("Orcamento 2026.xlsx", {"orcamento"}),
])
def test_palavras_do_nome(name, words):
    assert conflicts.name_words(name) == words


def test_remover_a_planilha_vazia_supera_o_conflito(cfg, drive, conn):
    carga_inicial(drive)
    fid = drive.add_fixture(VAZIA)
    run(cfg, drive)
    drive.files[fid]["trashed"] = True
    run(cfg, drive)
    [c] = todos(conn)
    assert c["status"] == "superado" and c["closed_at"] and c["resolved_by"] is None
    # Voltou para a pasta com o mesmo conteúdo: o mesmo conflito reabre.
    drive.files[fid]["trashed"] = False
    run(cfg, drive)
    [c] = todos(conn)
    assert c["status"] == "aberto" and c["closed_at"] is None


def test_falha_de_leitura_nao_encerra_o_conflito(cfg, drive, conn):
    carga_inicial(drive)
    fid = drive.add_fixture(VAZIA)
    run(cfg, drive)
    drive.fail_ids.add(fid)
    drive.edit(fid, drive.content[fid])  # versão nova no Drive força nova leitura, que falha
    run(cfg, drive)
    [c] = todos(conn)
    assert c["status"] == "aberto"


# ---------------------------------------------------------------------------
# Decisão humana
# ---------------------------------------------------------------------------


def test_so_bruno_decide_e_a_decisao_nao_altera_atividades(cfg, drive, conn):
    carga_inicial(drive)
    drive.add_fixture(VAZIA)
    run(cfg, drive)
    [c] = todos(conn)
    antes = [activities.snapshot(conn, i) for i in ("ACT-101", "ACT-102", "ACT-103", "ACT-104")]
    for quem in ("U-A", "U-C", "U-D"):
        with pytest.raises(conflicts.NotAllowed):
            conflicts.decide(conn, c["conflict_id"], membro(conn, quem), "manter a fonte atual")
    with pytest.raises(ValueError):
        conflicts.decide(conn, c["conflict_id"], membro(conn, "U-B"), "  ")
    conflicts.decide(conn, c["conflict_id"], membro(conn, "U-B"), "Manter Ata_registro.xlsx; cópia vazia sem autoridade.")
    conn.commit()
    [c] = todos(conn)
    assert c["status"] == "resolvido" and c["resolved_by"] == "U-B" and c["resolution"].startswith("Manter")
    with pytest.raises(ValueError, match="já foi encerrado"):
        conflicts.decide(conn, c["conflict_id"], membro(conn, "U-B"), "de novo")
    assert [activities.snapshot(conn, i) for i in ("ACT-101", "ACT-102", "ACT-103", "ACT-104")] == antes
    # A decisão vale para esta versão: novas sincronizações não reabrem.
    run(cfg, drive)
    assert [c["status"] for c in todos(conn)] == ["resolvido"]


def test_versao_nova_da_planilha_abre_conflito_novo(cfg, drive, conn):
    carga_inicial(drive)
    fid = drive.add_fixture(VAZIA)
    run(cfg, drive)
    [c] = todos(conn)
    conflicts.decide(conn, c["conflict_id"], membro(conn, "U-B"), "Cópia vazia sem autoridade.")
    conn.commit()
    drive.edit(fid, xlsx([CABECALHO, ["ACT-777", "Agora tem dado"]], sheet="Ata"))
    run(cfg, drive)
    velho, novo = todos(conn)
    assert velho["status"] == "resolvido"
    assert novo["status"] == "aberto" and "ACT-777" in novo["description"]
    assert n_activities(conn) == 4


def test_troca_de_fonte_decidida_deixa_de_pedir_atencao(cfg, drive, conn):
    fids = carga_inicial(drive)
    run(cfg, drive)
    drive.add_file("Registro_novo.xlsx", xlsx([CABECALHO, ["ACT-900", "Outra", "Ana"]]))
    drive.edit(fids["INDEX.md"], INDEX.read_text(encoding="utf-8").replace("Ata_registro.xlsx", "Registro_novo.xlsx").encode())
    run(cfg, drive)
    kinds = {c["kind"]: c for c in todos(conn)}
    # A planilha antiga deixou de ser apontada, mas é a importada: não vira "sem autoridade".
    assert set(kinds) == {"troca_de_fonte"}
    assert status(conn)["state"] == "atencao"
    conflicts.decide(conn, kinds["troca_de_fonte"]["conflict_id"], membro(conn, "U-B"), "Manter a importação atual.")
    conn.commit()
    run(cfg, drive)
    st = status(conn)
    assert st["state"] == "importada" and "Decisão registrada por Bruno" in st["message"]
    assert ids(activities.list_activities(conn, HOJE)) == ["ACT-101", "ACT-102", "ACT-103", "ACT-104"]


def test_ambiguidade_vira_conflito(cfg, drive, conn):
    drive.add_file("INDEX.md", INDEX.read_bytes())
    drive.add_fixture("01_CARGA_INICIAL/Ata_registro.xlsx")
    sub = drive.add_folder("copias")
    drive.add_fixture("01_CARGA_INICIAL/Ata_registro.xlsx", parent=sub)
    run(cfg, drive)
    kinds = [c["kind"] for c in todos(conn)]
    assert "fonte_ambigua" in kinds and n_activities(conn) == 0


# ---------------------------------------------------------------------------
# Fonte indisponível: último estado confirmado, marcado como possivelmente desatualizado
# ---------------------------------------------------------------------------


def test_fonte_removida_marca_atividades_como_possivelmente_desatualizadas(cfg, drive, conn):
    fids = carga_inicial(drive)
    run(cfg, drive)
    assert all(r["stale_sources"] == 0 for r in activities.list_activities(conn, HOJE))
    del drive.files[fids["Ata_registro.xlsx"]]  # apagado ou acesso retirado: o Drive responde 404
    run(cfg, drive)
    rows = activities.list_activities(conn, HOJE)
    assert len(rows) == 4 and all(r["stale_sources"] >= 1 for r in rows)
    a = activities.get(conn, "ACT-101")
    assert a["due_date"] == "2026-10-05"  # o último estado confirmado continua valendo
    assert [s["name"] for s in a["stale_sources"]] == ["Ata_registro.xlsx"]


def test_retry_delay_tenta_de_novo_mais_cedo_depois_de_falha():
    assert main.retry_delay(300, 0) == 300
    assert [main.retry_delay(300, n) for n in range(1, 6)] == [30, 60, 120, 240, 300]


# ---------------------------------------------------------------------------
# Telas
# ---------------------------------------------------------------------------


@pytest.fixture
def client(cfg, drive, monkeypatch):
    monkeypatch.setattr(main, "settings", cfg)
    monkeypatch.setattr(main, "today", lambda: HOJE)
    carga_inicial(drive)
    run(cfg, drive)
    with TestClient(main.app, base_url="http://localhost:8000") as c:
        yield c


def como(client, member_id):
    client.post("/usuario", data={"member_id": member_id, "next": "/sincronizacao"})


def test_tela_mostra_conflito_e_so_bruno_ve_o_formulario(client, cfg, drive, conn):
    drive.add_fixture(VAZIA)
    run(cfg, drive)
    r = client.get("/atividades")
    assert "1 conflito(s) de fonte aguardando decisão humana" in r.text
    como(client, "U-A")
    r = client.get("/sincronizacao")
    assert "Planilha sem autoridade parecida com a fonte das atividades" in r.text
    assert "Ata - copia vazia.xlsx" in r.text and "Registrar decisão" not in r.text
    [c] = todos(conn)
    r = client.post(f"/conflitos/{c['conflict_id']}/decisao", data={"resolution": "tentativa da Ana"})
    assert "Só quem revisa sugestões de todas as frentes" in r.text
    assert todos(conn)[0]["status"] == "aberto"
    como(client, "U-B")
    assert "Registrar decisão" in client.get("/sincronizacao").text
    r = client.post(f"/conflitos/{c['conflict_id']}/decisao", data={"resolution": "Manter Ata_registro.xlsx."})
    assert "Decisão registrada por Bruno" in r.text and "Decisão de Bruno" in r.text
    assert "conflito(s) de fonte aguardando" not in client.get("/atividades").text


def test_tela_da_atividade_avisa_fonte_indisponivel(client, cfg, drive):
    fid = next(f for f, d in drive.files.items() if d["name"] == "Ata_registro.xlsx")
    del drive.files[fid]
    run(cfg, drive)
    assert "Fonte indisponível: possivelmente desatualizada" in client.get("/atividades").text
    r = client.get("/atividades/ACT-101")
    assert "Possivelmente desatualizada." in r.text and "último estado confirmado" in r.text


def test_falha_da_sincronizacao_avisa_em_todas_as_telas(client, cfg, drive, conn):
    drive.fail_listing = True
    r = run(cfg, drive)
    assert not r.ok
    for path in ("/minhas", "/atividades", "/atividades/ACT-101"):
        page = client.get(path).text
        assert "A última leitura do Drive falhou" in page and "último estado confirmado" in page
    assert len(activities.list_activities(conn, HOJE)) == 4
