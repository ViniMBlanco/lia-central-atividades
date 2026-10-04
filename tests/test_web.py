import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import sync


@pytest.fixture
def client(cfg, monkeypatch):
    monkeypatch.setattr(main, "settings", cfg)
    with TestClient(main.app, base_url="http://localhost:8000") as c:
        yield c


def test_paginas_do_menu_respondem(client):
    for path in ["/", "/minhas", "/atividades", "/sugestoes", "/novidades", "/sincronizacao"]:
        r = client.get(path)
        assert r.status_code == 200, path
        for rotulo in ["Comece aqui", "Minhas atividades", "Todas as atividades",
                       "Sugestões para revisar", "Novidades dos documentos", "Estado da sincronização"]:
            assert rotulo in r.text


def test_estado_vazio_sem_conta(client):
    r = client.get("/sincronizacao")
    assert "Não conectada" in r.text and "Conectar com o Google" in r.text
    assert "Nenhum arquivo lido ainda" in r.text


def test_sincronizar_sem_conta_avisa(client):
    r = client.post("/sincronizacao/agora")
    assert r.status_code == 200
    assert "Conecte uma conta do Google" in r.text


def test_tela_mostra_arquivos_com_link_e_estado(client, cfg, drive):
    drive.add_fixture("01_CARGA_INICIAL/INDEX.md")
    drive.add_fixture("02_ADICIONAR_DEPOIS_DA_CARGA/Ata_2026-10-03.docx")
    sync.run_sync(cfg, "manual", client_factory=lambda: drive)
    r = client.get("/sincronizacao")
    assert "https://drive/ROOT" in r.text  # pasta conectada com link
    assert 'href="https://drive/f1"' in r.text
    assert "Processado" in r.text and "Ignorado" in r.text
    assert cfg.google_client_secret not in r.text or not cfg.google_client_secret


def test_callback_com_state_invalido_e_recusado(client):
    r = client.get("/auth/callback?state=forjado&code=x")
    assert "state não confere" in r.text


def test_login_redireciona_para_o_google_com_state(client, cfg):
    if not cfg.google_configured:
        pytest.skip("sem credenciais do Google no .env")
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("https://accounts.google.com/") and "state=" in loc
    assert "code_challenge=" in loc and "access_type=offline" in loc
    assert cfg.google_client_secret not in loc



def test_endereco_inexistente_mostra_pagina_do_app(client):
    for path in ["/nao-existe", "/sugestoes/abc"]:
        r = client.get(path)
        assert r.status_code == 404, path
        assert r.headers["content-type"].startswith("text/html")
        assert "Página não encontrada" in r.text and "Comece aqui" in r.text
    r = client.get("/sincronizacao/agora")  # só aceita POST
    assert r.status_code == 405 and "Ação indisponível" in r.text


def test_erro_inesperado_mostra_pagina_sem_detalhe_tecnico(cfg, monkeypatch):
    monkeypatch.setattr(main, "settings", cfg)

    def quebra(*args, **kwargs):
        raise RuntimeError("segredo interno")

    monkeypatch.setattr(main.onboarding, "build", quebra)
    with TestClient(main.app, base_url="http://localhost:8000", raise_server_exceptions=False) as c:
        r = c.get("/")
    assert r.status_code == 500
    assert "Algo deu errado" in r.text and "não se perdem" in r.text
    assert "segredo interno" not in r.text and "Traceback" not in r.text


def test_saude_e_aviso_de_conexao_perdida(client):
    assert client.get("/saude").status_code == 204
    r = client.get("/atividades")
    assert 'id="sem-conexao"' in r.text and "Sem conexão com o app" in r.text


def test_formularios_que_gravam_travam_o_segundo_envio(client):
    r = client.get("/atividades/nova")
    assert 'data-carregando="Salvando…"' in r.text
