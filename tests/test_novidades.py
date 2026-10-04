"""Fase 5: Comece aqui (R12), "o que mudou para mim" (R09) e Novidades dos documentos."""

import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import activities, ai, changes, db, sync

from .test_suggestions import ATA_1003, ATA_1004, Gravado, add_ata_1003, membro, pendentes, usar
from .test_sync import CARGA, carga_inicial, run

HOJE = date(2026, 10, 4)


@pytest.fixture
def web(cfg, drive, monkeypatch):
    """Carga inicial + atas de 03/10 (Google Docs) e 04/10, com as respostas reais gravadas da IA."""
    usar(monkeypatch, Gravado())
    monkeypatch.setattr(main, "settings", cfg)
    monkeypatch.setattr(main, "today", lambda: HOJE)
    ids = carga_inicial(drive)
    run(cfg, drive)
    ids["1003"] = add_ata_1003(drive)
    ids["1004"] = drive.add_fixture(ATA_1004)
    run(cfg, drive)
    with TestClient(main.app, base_url="http://localhost:8000") as c:
        c.ids = ids
        yield c


def como(client, member_id):
    client.post("/usuario", data={"member_id": member_id, "next": "/"})


def aceitar_act_101(conn):
    from app import suggestions
    upd = next(s for s in pendentes(conn) if s["kind"] == "update")
    suggestions.review(conn, upd["suggestion_id"], membro(conn, "U-B"), "aceitar", upd["proposed_fields"])
    conn.commit()
    return upd


def secao(html, inicio, fim):
    """Trecho da página entre dois marcadores (para conferir em que grupo um item aparece)."""
    return html.split(inicio, 1)[1].split(fim, 1)[0]


# ---------------------------------------------------------------------------
# Comece aqui
# ---------------------------------------------------------------------------


def test_comece_aqui_sem_documentos_explica_o_que_falta(client_vazio):
    r = client_vazio.get("/")
    assert r.status_code == 200
    assert "Nenhum documento foi lido do Drive ainda" in r.text and "Em quatro passos" in r.text


@pytest.fixture
def client_vazio(cfg, monkeypatch):
    monkeypatch.setattr(main, "settings", cfg)
    with TestClient(main.app, base_url="http://localhost:8000") as c:
        yield c


def test_comece_aqui_vem_dos_documentos_com_lacunas_marcadas(web):
    r = web.get("/")
    t = r.text
    # Propósito copiado do ESTADO-ATUAL, marcado como provisório (status: parcial), com quem confirma.
    assert "Esta organização fictícia treina pessoas para aplicar IA a problemas reais." in t
    assert "Provisório: a confirmar" in t and "Confirmação com Bruno" in t
    # Frentes: o que fazem (ESTADO-ATUAL) e pessoas/papéis (GUIA), com link para os originais.
    for trecho in ["Growth prepara e publica conteúdos aprovados pelo líder da frente.",
                   "Bruno é líder da frente e aprova posts antes de publicação.",
                   "Carla organiza oficinas e revisa propostas de atividades da sua frente.",
                   "Davi cuida do checklist de entrada de novos membros."]:
        assert trecho in t
    assert f'href="https://drive/{web.ids["ESTADO-ATUAL.md"]}"' in t
    # Regras: passos do guia, precedência do INDEX, plano antigo como histórico.
    assert "Abra a origem de uma atividade antes de assumir" in t
    assert "Precedência para este conjunto:" in t
    assert "PLANO_EDITORIAL_ANTIGO.md" in t and "Histórico (substituído)" in t
    # Lacunas: o próprio documento diz que o propósito é provisório.
    lacunas = secao(t, "O que ainda está a confirmar", "</section>")
    assert "descrição provisória" in lacunas
    # Nada da missão real da Liga (00_Comece_aqui) nem texto inventado.
    assert "missão oficial" not in t.lower()


def test_comece_aqui_sem_estado_atual_nao_inventa_proposito(cfg, drive, monkeypatch):
    monkeypatch.setattr(main, "settings", cfg)
    for name in CARGA:
        if name != "ESTADO-ATUAL.md":
            drive.add_fixture(f"01_CARGA_INICIAL/{name}")
    run(cfg, drive)
    with TestClient(main.app, base_url="http://localhost:8000") as c:
        t = c.get("/").text
    assert "O app não escreve um propósito por conta própria" in t
    assert "nenhum documento de estado atual" in t
    assert "ESTADO-ATUAL.md: citado no INDEX.md, mas não está na pasta do Drive." in t


@pytest.mark.parametrize("member_id, esperado", [
    ("U-A", "ACT-101"),  # prazo mais próximo: 05/10
    ("U-D", "ACT-102"),
    ("U-C", "ACT-103"),  # bloqueada: mostra o bloqueio
])
def test_primeira_acao_de_cada_pessoa(web, member_id, esperado):
    como(web, member_id)
    t = web.get("/").text
    acao = secao(t, "Sua primeira ação", "</dl>")
    assert f"<code>{esperado}</code>" in acao
    if esperado == "ACT-103":
        assert "Sala ainda não confirmada" in acao


def test_primeira_acao_de_quem_so_revisa(web):
    como(web, "U-B")
    t = web.get("/").text
    assert "Nenhuma atividade aberta com Bruno como responsável" in t
    assert "2 sugestão(ões)</strong> esperando você" in t


def test_atividade_sem_responsavel_vira_lacuna(web, conn):
    activities.create(conn, {"title": "Tarefa sem dono", "status": "a_fazer", "owners": [], "front": "Operações"}, "U-B")
    conn.commit()
    t = web.get("/").text
    assert "1 atividade(s) aberta(s) com responsável a confirmar." in secao(t, "O que ainda está a confirmar", "</section>")
    como(web, "U-D")  # Davi é de Operações: aparece como incerto no resumo dele
    assert "da sua frente: responsável a confirmar" in web.get("/novidades").text


# ---------------------------------------------------------------------------
# O que mudou para mim
# ---------------------------------------------------------------------------


def test_resumo_pessoal_distingue_ana_de_davi(web, conn):
    """Critério da spec §9: atualização relevante para Ana e não para Davi."""
    aceitar_act_101(conn)
    como(web, "U-A")
    t = web.get("/novidades").text
    confirmado = secao(t, "Confirmado no registro oficial (1)", "Propostas aguardando revisão")
    assert "ACT-101" in confirmado and "Sugestão aceita por Bruno" in confirmado
    assert "05/10/2026" in confirmado and "07/10/2026" in confirmado
    assert f'href="https://drive/{web.ids["1003"]}"' in confirmado  # fonte: a ata, com link
    como(web, "U-D")
    t = web.get("/novidades").text
    assert "Nada mudou nas atividades de Davi desde o início." in t
    assert "Confirmado no registro oficial (0)" in t


def test_proposta_pendente_nao_aparece_como_confirmada(web):
    como(web, "U-A")
    t = web.get("/novidades").text
    assert "Confirmado no registro oficial (0)" in t
    propostas = secao(t, "Propostas aguardando revisão (1)", "Dados incertos")
    assert "Atualizar ACT-101" in propostas and "07/10/2026" in propostas and "(proposto)" in propostas
    assert "aguarda revisão de Bruno" in propostas
    # O prazo oficial continua o antigo na lista de atenção.
    assert "05/10/2026" in secao(t, "Prazos próximos e bloqueios", "</section>")


def test_carla_ve_que_pode_revisar_a_propria_proposta(web):
    como(web, "U-C")
    propostas = secao(web.get("/novidades").text, "Propostas aguardando revisão (1)", "Dados incertos")
    assert "aguarda revisão de Bruno ou Carla" in propostas and "auto-revisão" in propostas


def test_marcar_como_visto_define_o_marco_e_abrir_a_pagina_nao(web, conn):
    como(web, "U-A")
    web.get("/novidades")
    assert conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == 0  # abrir não marca
    r = web.post("/novidades/visto")
    assert "Visita marcada em" in r.text and "Nada mudou nas atividades de Ana desde" in r.text
    # Algo muda depois da visita marcada: aparece.
    conn.execute("UPDATE visits SET last_seen_at = '2026-10-01T00:00:00+00:00'")  # visita anterior ao aceite
    conn.commit()
    aceitar_act_101(conn)
    t = web.get("/novidades").text
    assert "Desde a sua última visita marcada" in t and "Confirmado no registro oficial (1)" in t
    # Escolher outro período continua possível.
    assert "Confirmado no registro oficial (1)" in web.get("/novidades?desde=tudo").text


def test_periodo_invalido_volta_ao_padrao(web):
    como(web, "U-A")
    t = web.get("/novidades?desde=xyz").text
    assert 'value="tudo" selected' in t


def test_incertezas_conflito_e_ata_sem_analise(cfg, drive, conn, monkeypatch):
    from .test_suggestions import Falha
    usar(monkeypatch, Falha())
    monkeypatch.setattr(main, "settings", cfg)
    monkeypatch.setattr(main, "today", lambda: HOJE)
    carga_inicial(drive)
    drive.add_fixture("03_CONFLITO/Ata - copia vazia.xlsx")
    run(cfg, drive)
    with TestClient(main.app, base_url="http://localhost:8000") as c:
        como(c, "U-D")
        incertos = secao(c.get("/novidades").text, "Dados incertos ou em conflito", "Prazos próximos")
    assert "Conflito de fonte aguardando decisão humana" in incertos
    assert "A ata Ata_2026-10-01.md ainda não foi analisada" in incertos


def test_comece_aqui_resume_o_que_mudou(web, conn):
    aceitar_act_101(conn)
    como(web, "U-A")
    resumo = secao(web.get("/").text, 'aria-label="Resumo de Ana"', "</ul>")
    assert "1</strong> mudança(s) confirmada(s)" in resumo


# ---------------------------------------------------------------------------
# Novidades dos documentos (linha do tempo)
# ---------------------------------------------------------------------------


def test_linha_do_tempo_dos_documentos(cfg, drive, conn, web):
    fid = web.ids["Ata_2026-10-01.md"]
    drive.rename(fid, "Ata_2026-10-01_renomeada.md")
    run(cfg, drive)
    drive.files[web.ids["GUIA_INICIAL.md"]]["trashed"] = True
    drive.edit(web.ids["1003"], ATA_1003.read_bytes().replace(b"2026-10-07", b"2026-10-08"))
    run(cfg, drive)
    t = web.get("/novidades").text
    assert "Renomeado" in t and "Ata_2026-10-01.md → Ata_2026-10-01_renomeada.md" in t
    assert "Ficou indisponível" in t and "Movido para a lixeira do Drive" in t
    assert "Conteúdo alterado no Drive" in t and "Sugestão #1 substituída" in t
    assert "Apareceu na pasta" in t and "Analisado por IA (Gemini, gemini-3.6-flash)" in t
    drive.files[web.ids["GUIA_INICIAL.md"]]["trashed"] = False
    run(cfg, drive)
    assert "Voltou a ficar disponível" in web.get("/novidades").text


def test_falha_de_leitura_vira_um_evento_so(cfg, drive, conn):
    ids = carga_inicial(drive)
    run(cfg, drive)
    drive.fail_ids.add(ids["INDEX.md"])
    drive.edit(ids["INDEX.md"], b"# INDEX\n")
    run(cfg, drive)
    drive.edit(ids["INDEX.md"], b"# INDEX 2\n")
    run(cfg, drive)
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM source_events WHERE file_id = ?", (ids["INDEX.md"],))]
    assert kinds == ["falhou"]


def test_periodo_sem_novidades(web, conn):
    como(web, "U-A")
    web.post("/novidades/visto")
    t = web.get("/novidades?desde=marca").text
    assert "Nenhuma novidade nos documentos desde" in t


def test_docx_ignorado_na_linha_do_tempo(cfg, drive, web):
    drive.add_fixture("02_ADICIONAR_DEPOIS_DA_CARGA/Ata_2026-10-03.docx")
    run(cfg, drive)
    t = web.get("/novidades").text
    assert "Ata_2026-10-03.docx" in t and "Formato ainda não processado" in t


# ---------------------------------------------------------------------------
# Parágrafo escrito pela IA
# ---------------------------------------------------------------------------

# Respostas reais do gemini-3.6-flash (04/10/2026) para os fatos de Ana: depois do aceite e com a proposta pendente.
REAL_ANA_ACEITA = ("No registro oficial, foram confirmadas mudanças na atividade de preparar carrossel sobre ferramentas, "
                   "cujo prazo passou para 07/10/2026 e o próximo passo foi atualizado para fechar o roteiro e enviar "
                   "para Bruno. Além disso, a atividade de revisar fluxo de solicitação de materiais tem prazo definido "
                   "para 11/10/2026.")
REAL_ANA_PENDENTE = ("Nada mudou no registro oficial no período em relação a você. Há uma proposta pendente que aguarda "
                     "revisão, a qual sugere alterar o prazo e o próximo passo da atividade ACT-101. Além disso, você deve "
                     "atenção à atividade ACT-101, que tem prazo próximo para 05/10/2026.")


class Redator:
    """Imita o Gemini no resumo: devolve um texto fixo e conta as chamadas."""

    label = "gemini:gemini-3.6-flash"

    def __init__(self, texto=None, erro=None):
        self.texto, self.erro, self.calls = texto, erro, 0

    def summarize(self, facts):
        self.calls += 1
        if self.erro:
            raise ai.AIError(self.erro)
        return ai.RawResult(items=[{"resumo": self.texto}], generated_by=self.label, tokens_in=650, tokens_out=100)


def fatos(conn, member_id, desde="tudo"):
    me = membro(conn, member_id)
    names = {r["member_id"]: r["display_name"] for r in conn.execute("SELECT * FROM members")}
    p = changes.personal(conn, me, changes.resolve_period(conn, me, desde), HOJE)
    return changes.facts(p, lambda v, f: main.fmt_field(v, f, names), main.fmt_dt, HOJE), list(names.values())


def test_conferencia_aceita_as_respostas_reais(web, conn):
    f, names = fatos(conn, "U-A")
    assert changes.check_summary(REAL_ANA_PENDENTE, f, names) == []
    aceitar_act_101(conn)
    f, names = fatos(conn, "U-A")
    assert changes.check_summary(REAL_ANA_ACEITA, f, names) == []


@pytest.mark.parametrize("texto, problema", [
    ("O prazo do ACT-101 passou para 07/10/2026.", "só existe numa proposta pendente"),  # proposta dita como fato
    ("Seu prazo agora é 08/10/2026.", "cita a data 08/10"),
    ("A ACT-999 foi criada para você.", "cita ACT-999"),
    ("Davi mudou o prazo do ACT-101.", "cita Davi"),
    ("", "texto vazio"),
])
def test_conferencia_descarta_paragrafo_que_inventa(web, conn, texto, problema):
    f, names = fatos(conn, "U-A")
    assert any(problema in p for p in changes.check_summary(texto, f, names))


def test_proposta_dita_como_proposta_passa(web, conn):
    f, names = fatos(conn, "U-A")
    texto = "Há uma proposta, ainda não aprovada, de mudar o prazo do ACT-101 para 07/10/2026."
    assert changes.check_summary(texto, f, names) == []


def test_botao_resumir_com_ia_e_cache(web, conn, monkeypatch):
    redator = Redator(REAL_ANA_PENDENTE)
    monkeypatch.setattr(ai, "summarizer_for", lambda settings: redator)
    como(web, "U-A")
    assert "Resumir com IA" in web.get("/novidades").text
    t = web.post("/novidades/resumo-ia", data={"desde": "tudo"}).text
    assert "Resumo escrito pela IA" in t and "Há uma proposta pendente que aguarda revisão" in t
    t = web.post("/novidades/resumo-ia", data={"desde": "tudo"}).text
    assert redator.calls == 1 and "nada foi pedido de novo à IA" in t
    # Os itens mudam (Bruno aceita): o parágrafo antigo deixa de aparecer e dá para pedir outro.
    aceitar_act_101(conn)
    t = web.get("/novidades").text
    assert "Há uma proposta pendente que aguarda revisão" not in t and "Resumir com IA" in t


def test_paragrafo_que_inventa_e_descartado_na_tela(web, conn, monkeypatch):
    monkeypatch.setattr(ai, "summarizer_for", lambda settings: Redator("O prazo do ACT-101 passou para 07/10/2026."))
    como(web, "U-A")
    t = web.post("/novidades/resumo-ia", data={"desde": "tudo"}).text
    assert "O parágrafo escrito pela IA foi descartado" in t and "só existe numa proposta pendente" in t
    assert "Resumo escrito pela IA" not in t
    row = conn.execute("SELECT status FROM personal_summaries").fetchone()
    assert row["status"] == "descartado"


def test_falha_da_ia_no_resumo_nao_quebra_a_pagina(web, monkeypatch):
    redator = Redator(erro="Gemini indisponível (HTTP 503); nova tentativa na próxima sincronização.")
    monkeypatch.setattr(ai, "summarizer_for", lambda settings: redator)
    como(web, "U-A")
    t = web.post("/novidades/resumo-ia", data={"desde": "tudo"}).text
    assert "A IA não escreveu o resumo" in t and "Confirmado no registro oficial" in t
    assert "Tentar de novo" in t
    web.post("/novidades/resumo-ia", data={"desde": "tudo"})
    assert redator.calls == 2  # falha não fica em cache


def test_sem_ia_configurada_nao_ha_botao(web):
    como(web, "U-A")
    assert "Resumir com IA" not in web.get("/novidades").text


def test_banco_antigo_ganha_a_saida_do_arquivo_na_linha_do_tempo(cfg, drive, conn):
    """Banco de antes da Fase 5: o arquivo que já estava indisponível ganha o evento, marcado como aproximado."""
    ids = carga_inicial(drive)
    run(cfg, drive)
    drive.files[ids["GUIA_INICIAL.md"]]["trashed"] = True
    run(cfg, drive)
    conn.execute("DROP TABLE source_events")
    # No teste as duas leituras caem no mesmo segundo; na vida real a última vez visto é anterior à leitura que detecta.
    conn.execute("UPDATE sources SET last_seen_at = '2026-10-04T01:00:00+00:00' WHERE file_id = ?", (ids["GUIA_INICIAL.md"],))
    conn.commit()
    db.init_db(cfg.database_path)
    [ev] = conn.execute("SELECT * FROM source_events").fetchall()
    assert ev["file_id"] == ids["GUIA_INICIAL.md"] and ev["kind"] == "indisponivel"
    detected = conn.execute("SELECT finished_at FROM sync_runs ORDER BY run_id DESC").fetchone()[0]
    assert ev["ts"] == detected  # a sincronização que detectou a saída
    assert "lixeira" in ev["detail"] and "histórico de sincronizações" in ev["detail"]
    db.init_db(cfg.database_path)  # reiniciar de novo não duplica
    assert conn.execute("SELECT COUNT(*) FROM source_events").fetchone()[0] == 1
