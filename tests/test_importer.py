"""Autoridade das fontes e importação única da planilha apontada pelo INDEX."""

import io
import json
from datetime import date

from openpyxl import Workbook

from app import activities, sync
from app.drive import GSHEET_MIME

from .conftest import FIXTURES
from .test_sync import carga_inicial, run

INDEX = FIXTURES / "01_CARGA_INICIAL/INDEX.md"
REGISTRO = FIXTURES / "01_CARGA_INICIAL/Ata_registro.xlsx"
HOJE = date(2026, 10, 3)


def ids(rows):
    return sorted(r["activity_id"] for r in rows)


def status(conn):
    return conn.execute("SELECT * FROM register_status").fetchone()


def xlsx(rows, sheet="Atividades"):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


CABECALHO = ["ID", "Atividade", "Responsáveis", "Prazo", "Frente", "Prioridade", "Status",
             "Próximo passo", "Origem", "Notas e bloqueios"]


def test_carga_inicial_gabarito(cfg, drive, conn):
    carga_inicial(drive)
    run(cfg, drive)
    assert ids(activities.list_activities(conn, HOJE)) == ["ACT-101", "ACT-102", "ACT-103", "ACT-104"]
    # Gabarito do LEIA_ME: Ana 101+104, Davi 102+104, Carla 103, Bruno nenhuma.
    assert ids(activities.list_activities(conn, HOJE, owner="U-A")) == ["ACT-101", "ACT-104"]
    assert ids(activities.list_activities(conn, HOJE, owner="U-D")) == ["ACT-102", "ACT-104"]
    assert ids(activities.list_activities(conn, HOJE, owner="U-C")) == ["ACT-103"]
    assert ids(activities.list_activities(conn, HOJE, owner="U-B")) == []
    a = activities.get(conn, "ACT-104")
    assert [o["display_name"] for o in a["owners"]] == ["Ana", "Davi"]  # dois responsáveis, uma atividade
    b = activities.get(conn, "ACT-103")
    assert b["status"] == "bloqueada" and b["notes"] == "Sala ainda não confirmada"
    c = activities.get(conn, "ACT-101")
    assert c["due_date"] == "2026-10-05" and c["status"] == "em_andamento" and c["front"] == "Growth"
    assert c["next_step"] == "Preparar roteiro e selecionar exemplos" and c["origin"] == "import"
    assert status(conn)["state"] == "importada"


def test_importacao_registra_evento_e_proveniencia(cfg, drive, conn):
    fids = carga_inicial(drive)
    run(cfg, drive)
    hist = activities.history(conn, "ACT-101")
    assert len(hist) == 1
    ev = hist[0]
    assert ev["action"] == "import" and ev["actor_id"] == activities.IMPORT_ACTOR
    assert ev["source_file_id"] == fids["Ata_registro.xlsx"] and ev["source_version"]
    assert "aba Atividades, linha 2" in ev["reason"]
    refs = {r["relation_type"]: r for r in activities.references(conn, "ACT-101")}
    assert refs["imported_from"]["locator"] == "aba Atividades, linha 2"
    assert refs["origin"]["file_id"] == fids["Ata_2026-10-01.md"]
    assert refs["origin"]["quote"].startswith("`ACT-101`: Ana seguirá com o carrossel")
    imp = conn.execute("SELECT * FROM register_import").fetchone()
    assert imp["file_id"] == fids["Ata_registro.xlsx"] and imp["n_imported"] == 4 and imp["sheet_name"] == "Atividades"


def test_autoridade_das_fontes(cfg, drive, conn):
    fids = carga_inicial(drive)
    vazia = drive.add_fixture("03_CONFLITO/Ata - copia vazia.xlsx")
    docx = drive.add_fixture("02_ADICIONAR_DEPOIS_DA_CARGA/Ata_2026-10-03.docx")
    run(cfg, drive)
    auth = dict(conn.execute("SELECT file_id, authority FROM sources").fetchall())
    assert auth[fids["Ata_registro.xlsx"]] == "activity_register"
    assert auth[fids["INDEX.md"]] == "direction"
    assert auth[fids["ESTADO-ATUAL.md"]] == "direction"
    assert auth[fids["GUIA_INICIAL.md"]] == "direction"
    assert auth[fids["PLANO_EDITORIAL_ANTIGO.md"]] == "deprecated"
    assert auth[fids["Ata_2026-10-01.md"]] == "minutes"
    assert auth[vazia] == "none" and auth[docx] == "none"
    reason = conn.execute("SELECT authority_reason FROM sources WHERE file_id=?", (vazia,)).fetchone()[0]
    assert "não apontada pelo INDEX.md" in reason


def test_importa_uma_unica_vez(cfg, drive, conn):
    carga_inicial(drive)
    run(cfg, drive)
    run(cfg, drive)
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM activity_events").fetchone()[0] == 4


def test_edicao_da_planilha_depois_da_importacao_nao_sobrescreve(cfg, drive, conn):
    fids = carga_inicial(drive)
    run(cfg, drive)
    drive.edit(fids["Ata_registro.xlsx"], xlsx([
        CABECALHO,
        ["ACT-101", "Preparar carrossel sobre ferramentas", "Davi", "2026-12-01", "Growth", "Alta", "Concluída",
         "outro", "Ata_2026-10-01.md", ""],
    ]))
    r = run(cfg, drive)
    assert r.changed == [fids["Ata_registro.xlsx"]]
    a = activities.get(conn, "ACT-101")
    assert a["due_date"] == "2026-10-05" and [o["member_id"] for o in a["owners"]] == ["U-A"]
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 4  # linhas removidas não apagam
    st = status(conn)
    assert st["state"] == "alterada" and "Nada foi aplicado automaticamente" in st["message"]


def test_planilha_vazia_homonima_nao_apaga_nem_importa(cfg, drive, conn):
    carga_inicial(drive)
    run(cfg, drive)
    drive.add_fixture("03_CONFLITO/Ata - copia vazia.xlsx")
    run(cfg, drive)
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 4
    assert status(conn)["state"] == "importada"


def test_planilha_nao_apontada_com_dados_nao_importa(cfg, drive, conn):
    drive.add_file("INDEX.md", INDEX.read_bytes())
    drive.add_file("Ata_registro (1).xlsx", REGISTRO.read_bytes())
    run(cfg, drive)
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 0
    st = status(conn)
    assert st["state"] == "aguardando" and "Ata_registro.xlsx, que não está na pasta" in st["message"]


def test_sem_index_nada_e_importado(cfg, drive, conn):
    drive.add_file("Ata_registro.xlsx", REGISTRO.read_bytes())
    run(cfg, drive)
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 0
    assert "Nenhum arquivo INDEX" in status(conn)["message"]
    # Quando o INDEX chega, a importação acontece.
    drive.add_file("INDEX.md", INDEX.read_bytes())
    run(cfg, drive)
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 4


def test_duas_planilhas_com_o_nome_apontado_e_ambiguo(cfg, drive, conn):
    drive.add_file("INDEX.md", INDEX.read_bytes())
    drive.add_file("Ata_registro.xlsx", REGISTRO.read_bytes())
    sub = drive.add_folder("copias")
    drive.add_file("Ata_registro.xlsx", REGISTRO.read_bytes(), parent=sub)
    run(cfg, drive)
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 0
    st = status(conn)
    assert st["state"] == "atencao" and "Há 2 planilhas" in st["message"]


def test_falha_de_leitura_da_planilha_nao_vira_lista_vazia(cfg, drive, conn):
    fids = carga_inicial(drive)
    drive.fail_ids.add(fids["Ata_registro.xlsx"])
    run(cfg, drive)
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 0
    st = status(conn)
    assert st["state"] == "atencao" and "não pôde ser lida" in st["message"]
    drive.fail_ids.clear()
    run(cfg, drive)
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 4


def test_planilha_removida_depois_da_importacao_mantem_atividades(cfg, drive, conn):
    fids = carga_inicial(drive)
    run(cfg, drive)
    del drive.files[fids["Ata_registro.xlsx"]]
    run(cfg, drive)
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 4
    st = status(conn)
    assert st["state"] == "atencao" and "não está disponível" in st["message"]


def test_index_apontando_outra_planilha_nao_troca_a_fonte(cfg, drive, conn):
    fids = carga_inicial(drive)
    run(cfg, drive)
    drive.add_file("Registro_novo.xlsx", xlsx([CABECALHO, ["ACT-900", "Outra", "Ana", None, "Growth"]]))
    novo_index = INDEX.read_text(encoding="utf-8").replace("Ata_registro.xlsx", "Registro_novo.xlsx")
    drive.edit(fids["INDEX.md"], novo_index.encode("utf-8"))
    run(cfg, drive)
    assert ids(activities.list_activities(conn, HOJE)) == ["ACT-101", "ACT-102", "ACT-103", "ACT-104"]
    st = status(conn)
    assert st["state"] == "atencao" and "não é automática" in st["message"]


def test_aba_inexistente_nao_importa(cfg, drive, conn):
    drive.add_file("INDEX.md", INDEX.read_bytes())
    drive.add_file("Ata_registro.xlsx", xlsx([CABECALHO, ["ACT-1", "X"]], sheet="Ata"))
    run(cfg, drive)
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 0
    assert "A aba “Atividades” não existe" in status(conn)["message"]


def test_dados_ausentes_ficam_a_confirmar_sem_inventar(cfg, drive, conn):
    drive.add_file("INDEX.md", INDEX.read_bytes())
    drive.add_file("Ata_registro.xlsx", xlsx([
        CABECALHO,
        ["ACT-201", "Tarefa sem dono", None, "até sexta", "Growth", "Média", "A fazer"],
        ["ACT-202", "Tarefa de pessoa desconhecida", "Eduardo; Ana", 46300.5, "Formacao", None, "Talvez"],
        [None, "Linha sem ID"],
    ]))
    run(cfg, drive)
    a = activities.get(conn, "ACT-201")
    assert a["owners"] == [] and a["due_date"] is None
    reason = activities.history(conn, "ACT-201")[0]["reason"]
    assert "responsável a confirmar" in reason and "prazo “até sexta” não é uma data" in reason
    b = activities.get(conn, "ACT-202")
    assert [o["member_id"] for o in b["owners"]] == ["U-A"] and b["front"] == "Formação"
    assert b["due_date"] == "2026-10-05" and b["status"] == "a_fazer"
    reason = activities.history(conn, "ACT-202")[0]["reason"]
    assert "“Eduardo” não corresponde" in reason and "“Talvez” não reconhecido" in reason
    warnings = json.loads(conn.execute("SELECT warnings FROM register_import").fetchone()[0])
    assert warnings == ["Linha 4 sem ID: não importada."]


def test_planilha_convertida_para_google_planilhas_e_aceita(cfg, drive, conn, monkeypatch):
    drive.add_file("INDEX.md", INDEX.read_bytes())
    fid = drive.add_file("Ata_registro", b"", mime=GSHEET_MIME)
    # O FakeDrive só exporta Google Docs; aqui a exportação devolve o próprio .xlsx.
    monkeypatch.setattr(drive, "export", lambda file_id, mime: REGISTRO.read_bytes())
    run(cfg, drive)
    assert conn.execute("SELECT authority FROM sources WHERE file_id=?", (fid,)).fetchone()[0] == "activity_register"
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 4


def test_falha_na_interpretacao_nao_derruba_a_sincronizacao(cfg, drive, conn, monkeypatch):
    carga_inicial(drive)

    def explode(conn, folder_id):
        raise RuntimeError("bug")

    monkeypatch.setattr(sync.importer, "after_sync", explode)
    r = run(cfg, drive)
    assert r.ok
    assert conn.execute("SELECT COUNT(*) FROM sources WHERE sync_status='processed'").fetchone()[0] == 6
    st = status(conn)
    assert st["state"] == "atencao" and "não foram alteradas" in st["message"]


def test_id_criado_no_app_continua_a_numeracao_act(cfg, drive, conn):
    carga_inicial(drive)
    run(cfg, drive)
    assert activities.next_manual_id(conn) == "ACT-105"


def test_linha_da_planilha_com_id_ja_criado_no_app_nao_sobrescreve(cfg, drive, conn):
    # Atividade criada na interface antes de a planilha chegar recebe ACT-001.
    aid = activities.create(conn, {"title": "Criada no app", "status": "a_fazer", "owners": ["U-B"]}, "U-B")
    conn.commit()
    assert aid == "ACT-001"
    drive.add_file("INDEX.md", INDEX.read_bytes())
    drive.add_file("Ata_registro.xlsx", xlsx([
        CABECALHO,
        ["ACT-001", "Mesmo ID na planilha", "Ana", None, "Growth"],
        ["ACT-002", "Outra", "Davi", None, "Operações"],
    ]))
    run(cfg, drive)
    a = activities.get(conn, "ACT-001")
    assert a["title"] == "Criada no app" and a["origin"] == "manual"
    assert len(activities.history(conn, "ACT-001")) == 1
    assert activities.get(conn, "ACT-002")["origin"] == "import"
    warnings = json.loads(conn.execute("SELECT warnings FROM register_import").fetchone()[0])
    assert warnings == ["Linha 2: ACT-001 já existe no app; linha não importada."]
