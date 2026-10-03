"""Telas de atividades: minhas, todas, filtros, detalhe, criação, edição e histórico."""

import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import activities, sync

from .test_sync import carga_inicial


@pytest.fixture
def client(cfg, drive, monkeypatch):
    monkeypatch.setattr(main, "settings", cfg)
    monkeypatch.setattr(main, "today", lambda: date(2026, 10, 3))
    carga_inicial(drive)
    sync.run_sync(cfg, "manual", client_factory=lambda: drive)
    with TestClient(main.app, base_url="http://localhost:8000") as c:
        yield c


def como(client, member_id):
    r = client.post("/usuario", data={"member_id": member_id, "next": "/minhas"})
    assert r.status_code == 200
    return r


def ids_na_tela(html):
    return sorted(set(re.findall(r'href="/atividades/(ACT-\d+)"', html)))


def test_minhas_sem_usuario_pede_escolha(client):
    r = client.get("/minhas")
    assert "Escolha quem você é" in r.text and ids_na_tela(r.text) == []


def test_minhas_muda_com_o_usuario_sem_mudar_os_dados(client, conn):
    antes = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    r = como(client, "U-A")
    assert "Agora você está vendo o app como Ana" in r.text
    assert ids_na_tela(r.text) == ["ACT-101", "ACT-104"]
    assert ids_na_tela(como(client, "U-D").text) == ["ACT-102", "ACT-104"]
    assert ids_na_tela(como(client, "U-C").text) == ["ACT-103"]
    r = como(client, "U-B")
    assert ids_na_tela(r.text) == [] and "Nenhuma atividade aberta com Bruno" in r.text
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == antes


def test_minhas_mostra_prazo_estado_e_proximo_passo(client):
    r = como(client, "U-A")
    assert "05/10/2026" in r.text and "vence em 2 dia(s)" in r.text
    assert "Em andamento" in r.text and "Preparar roteiro e selecionar exemplos" in r.text
    assert "Ana, Davi" in r.text  # ACT-104 com os dois responsáveis


def test_minhas_ordena_bloqueadas_primeiro(client):
    como(client, "U-C")
    client.post("/atividades/nova", data={"title": "Tarefa sem bloqueio", "owners": "U-C", "due_date": "2026-10-04"})
    r = client.get("/minhas?ordem=bloqueios")
    assert ids_na_tela(r.text) == ["ACT-103", "ACT-105"]
    assert r.text.index("ACT-103") < r.text.index("ACT-105")
    r = client.get("/minhas?ordem=prazo")
    assert r.text.index("ACT-105") < r.text.index("ACT-103")


@pytest.mark.parametrize("query, esperado", [
    ("", ["ACT-101", "ACT-102", "ACT-103", "ACT-104"]),
    ("responsavel=U-D", ["ACT-102", "ACT-104"]),
    ("frente=Operações", ["ACT-102", "ACT-104"]),
    ("estado=bloqueada", ["ACT-103"]),
    ("estado=a_fazer&frente=Operações", ["ACT-102", "ACT-104"]),
    ("prazo=7dias", ["ACT-101", "ACT-102", "ACT-103"]),
    ("prazo=vencidas", []),
    ("responsavel=nenhum", []),
    ("responsavel=invalido", ["ACT-101", "ACT-102", "ACT-103", "ACT-104"]),
])
def test_filtros_de_todas(client, query, esperado):
    r = client.get(f"/atividades?{query}")
    assert r.status_code == 200
    assert ids_na_tela(r.text) == esperado


def test_todas_mostra_momento_e_vinculo_da_importacao(client):
    r = client.get("/atividades")
    assert "foram importadas de" in r.text and "Ata_registro.xlsx" in r.text and "(aba Atividades)" in r.text
    assert 'href="https://drive/' in r.text


def test_detalhe_com_fonte_evidencia_e_historico(client):
    r = client.get("/atividades/ACT-101")
    assert r.status_code == 200
    assert "Preparar carrossel sobre ferramentas" in r.text
    assert "aba Atividades, linha 2" in r.text
    assert "Ana seguirá com o carrossel sobre ferramentas" in r.text  # trecho da ata de origem
    assert "Importada da planilha" in r.text and "importação automática (regra do INDEX)" in r.text


def test_detalhe_inexistente_da_404(client):
    assert client.get("/atividades/ACT-999").status_code == 404


def test_criar_exige_usuario(client, conn):
    r = client.post("/atividades/nova", data={"title": "X"})
    assert r.status_code == 422 and "Escolha no topo da página quem você é" in r.text
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 4


def test_criar_valida_campos(client):
    como(client, "U-A")
    r = client.post("/atividades/nova", data={"title": " ", "due_date": "05/10/2026", "owners": "U-Z", "status": "x"})
    assert r.status_code == 422
    for msg in ["Informe um título", "Use uma data válida", "Responsável desconhecido", "Escolha um estado"]:
        assert msg in r.text
    assert 'aria-invalid="true"' in r.text


def test_criar_persiste_apos_reiniciar(client, cfg, conn):
    como(client, "U-D")
    r = client.post("/atividades/nova", data={
        "title": "Organizar planilha de presença", "owners": ["U-D", "U-A"], "front": "Operações",
        "status": "a_fazer", "due_date": "2026-10-20", "next_step": "Listar participantes",
    })
    assert r.status_code == 200 and "Atividade ACT-105 criada por Davi" in r.text
    a = activities.get(conn, "ACT-105")
    assert a["origin"] == "manual" and a["created_by"] == "U-D"
    ev = activities.history(conn, "ACT-105")[0]
    assert ev["action"] == "create" and ev["actor_id"] == "U-D" and ev["after"]["owners"] == ["U-A", "U-D"]
    # "Reinício": um novo ciclo de vida do app lê o mesmo banco.
    with TestClient(main.app, base_url="http://localhost:8000") as novo:
        novo.post("/usuario", data={"member_id": "U-A", "next": "/minhas"})
        r = novo.get("/minhas")
        assert "ACT-105" in ids_na_tela(r.text)
        r = novo.get("/atividades/ACT-105")
        assert "Criada manualmente por Davi" in r.text and "feita na própria aplicação" in r.text


def test_criar_sem_responsavel_nem_prazo_fica_a_confirmar(client):
    como(client, "U-B")
    r = client.post("/atividades/nova", data={"title": "Ideia a detalhar"})
    assert "Responsável a confirmar" in r.text and "A definir" in r.text


def test_editar_registra_antes_e_depois(client, conn):
    como(client, "U-B")
    a = activities.get(conn, "ACT-101")
    form = {**activities.snapshot(conn, "ACT-101"), "updated_at": a["updated_at"], "due_date": "2026-10-07",
            "next_step": "Fechar o roteiro e enviar para Bruno", "reason": "Combinado na reunião"}
    form = {k: v for k, v in form.items() if v is not None}
    r = client.post("/atividades/ACT-101/editar", data=form)
    assert r.status_code == 200 and "Alterações salvas (prazo, próximo passo)" in r.text
    ev = activities.history(conn, "ACT-101")[0]
    assert ev["actor_id"] == "U-B" and ev["action"] == "update"
    assert ev["before"] == {"due_date": "2026-10-05", "next_step": "Preparar roteiro e selecionar exemplos"}
    assert ev["after"] == {"due_date": "2026-10-07", "next_step": "Fechar o roteiro e enviar para Bruno"}
    assert ev["reason"] == "Combinado na reunião"
    assert "05/10/2026" in r.text and "07/10/2026" in r.text and "por Bruno" in r.text
    # Responsáveis continuam os mesmos (o formulário reenviou os mesmos valores).
    assert [o["member_id"] for o in activities.get(conn, "ACT-101")["owners"]] == ["U-A"]


def test_editar_sem_mudanca_nao_gera_evento(client, conn):
    como(client, "U-A")
    a = activities.get(conn, "ACT-104")
    form = {k: v for k, v in activities.snapshot(conn, "ACT-104").items() if v is not None}
    r = client.post("/atividades/ACT-104/editar", data={**form, "updated_at": a["updated_at"]})
    assert "Nenhum campo foi alterado" in r.text
    assert len(activities.history(conn, "ACT-104")) == 1


def test_edicao_concorrente_e_detectada(client, conn):
    como(client, "U-A")
    form = {k: v for k, v in activities.snapshot(conn, "ACT-102").items() if v is not None}
    r = client.post("/atividades/ACT-102/editar", data={**form, "title": "Outro título", "updated_at": "2000-01-01T00:00:00+00:00"})
    assert r.status_code == 422 and "alterada por outra pessoa" in r.text
    assert activities.get(conn, "ACT-102")["title"] == "Montar checklist inicial de onboarding"


def test_mudar_estado_concluir_e_bloquear(client, conn):
    como(client, "U-A")
    r = client.post("/atividades/ACT-101/estado", data={"status": "concluida", "reason": "Entregue"})
    assert "Estado alterado para “Concluída”" in r.text
    assert "ACT-101" not in ids_na_tela(client.get("/minhas").text)
    assert "ACT-101" in ids_na_tela(client.get("/atividades?responsavel=U-A&estado=concluida").text)
    client.post("/atividades/ACT-104/estado", data={"status": "bloqueada", "reason": "Aguardando Davi"})
    ev = activities.history(conn, "ACT-104")[0]
    assert ev["before"] == {"status": "a_fazer"} and ev["after"] == {"status": "bloqueada"}
    assert ev["reason"] == "Aguardando Davi" and ev["actor_id"] == "U-A"


def test_mudar_estado_sem_usuario_nao_altera(client, conn):
    r = client.post("/atividades/ACT-101/estado", data={"status": "concluida"})
    assert "Escolha no topo da página" in r.text
    assert activities.get(conn, "ACT-101")["status"] == "em_andamento"


def test_toda_atividade_tem_evento_com_autor(client, conn):
    como(client, "U-A")
    client.post("/atividades/nova", data={"title": "Nova"})
    client.post("/atividades/ACT-102/estado", data={"status": "em_andamento"})
    sem_evento = conn.execute(
        "SELECT COUNT(*) FROM activities a WHERE NOT EXISTS (SELECT 1 FROM activity_events e WHERE e.activity_id = a.activity_id)"
    ).fetchone()[0]
    assert sem_evento == 0
    atores = {r[0] for r in conn.execute("SELECT actor_id FROM activity_events WHERE action != 'import'")}
    assert atores == {"U-A"}


def test_troca_de_usuario_nao_redireciona_para_fora(client):
    r = client.post("/usuario", data={"member_id": "U-A", "next": "//exemplo.com/x"}, follow_redirects=False)
    assert r.headers["location"] == "/"


def test_tela_de_sincronizacao_mostra_papel_das_fontes(client):
    r = client.get("/sincronizacao")
    assert "Fonte das atividades" in r.text and "Em vigor" in r.text
    assert "Histórico (substituído)" in r.text and "Orientação" in r.text
