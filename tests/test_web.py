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

