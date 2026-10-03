# LIA — Central de contexto e atividades

Aplicação web local que lê uma pasta do Google Drive e ajuda cada membro da Liga de IA da UFSCar a responder duas perguntas: **"O que preciso fazer agora?"** e **"O que mudou desde a última vez?"**. Mudanças encontradas nos documentos viram **sugestões com evidência**, e um humano as aprova antes que alterem qualquer atividade oficial.

> Projeto do case técnico do processo seletivo da Liga IA UFSCar. Todos os dados usados são **fictícios**.
>
> **Estado: em construção.** As seções abaixo serão preenchidas ao longo do desenvolvimento.

## Sumário

1. Arquitetura
2. Fonte oficial das atividades
3. Credenciais do Google e pasta do Drive
4. Instalação e execução
5. Sincronização
6. Formatos suportados
7. IA no produto e custo estimado por uso
8. Limitações conhecidas
9. Antes de usar dados reais
10. Ferramentas de IA usadas no desenvolvimento
11. Documentação complementar

## 1. Arquitetura

*A preencher.*

## 2. Fonte oficial das atividades

**Regra única: a planilha apontada pelo `INDEX` cria as atividades uma vez; depois disso, a referência oficial é o banco do app, e nenhum documento muda uma atividade sem uma pessoa aprovar.**

1. **Quem manda é o `INDEX`.** O app procura na pasta o arquivo de texto chamado `INDEX` (`INDEX.md` ou Google Doc `INDEX`) e lê nele qual planilha e qual aba são a fonte das atividades. No pacote de teste: `` `Ata_registro.xlsx`, aba `Atividades`: fonte inicial e provisória das atividades identificadas por ACT-* ``.
2. **Importação única.** Na primeira sincronização em que essa planilha é lida, cada linha vira uma atividade, com:
   - evento "importada" no histórico (data, arquivo, aba, linha e versão do conteúdo);
   - vínculo com a linha da planilha e com o documento citado na coluna **Origem** (ex.: o trecho da `Ata_2026-10-01.md` que menciona o `ACT-101`);
   - "Ana; Davi" vira dois responsáveis da **mesma** atividade; "Bloqueada" continua bloqueada.
3. **Depois da importação, o app é a referência.** Mudanças entram pela interface (com autor, hora e campos antes/depois no histórico) ou por sugestões aprovadas por um revisor.
4. **Editar a planilha no Drive não sobrescreve nada.** O app detecta a nova versão e avisa que ela diverge; as diferenças são tratadas como sugestão para revisão humana. Linha apagada na planilha não apaga atividade.
5. **Planilha que o `INDEX` não aponta nunca importa nem apaga.** É o caso de `Ata - copia vazia.xlsx`: aparece como "sem autoridade" na tela de sincronização, e as atividades continuam intactas. A data do arquivo não importa: "mais recente" não significa "mais confiável".
6. **Ambiguidade não é resolvida por palpite.** Dois `INDEX`, duas planilhas com o nome apontado, `INDEX` citando duas planilhas ou passando a apontar outra depois da importação: nada é importado nem trocado, e o motivo aparece em "Todas as atividades" e em "Estado da sincronização".
7. **Dado ausente fica ausente.** Responsável que não é membro, prazo que não é data ("até sexta") ou estado desconhecido não são completados: o campo fica "a confirmar"/"a definir" e o aviso fica registrado no evento de importação.

Atividades criadas no app seguem o mesmo padrão `ACT-*` do material, continuando a numeração (depois de `ACT-104` vem `ACT-105`); a origem "criada manualmente por…" aparece na atividade e no histórico. Se a planilha trouxer depois um ID que já existe no app, a linha não sobrescreve a atividade: é registrada como aviso.

Por que não deixar a planilha como fonte oficial: o app só tem permissão de leitura no Drive (escrever lá está fora do escopo), então haveria duas verdades — a planilha e o que foi aprovado no app. Alternativas consideradas estão no [diário de bordo](docs/DIARIO_DE_BORDO.md) (03/10).

## 3. Credenciais do Google e pasta do Drive

*A preencher.* Variáveis em `.env.example`.

## 4. Instalação e execução

Requer Python 3.13.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # preencha conforme a seção 3
python -m app                    # abre em http://localhost:8000
python -m pytest                 # testes automatizados
```

Abra pelo endereço `http://localhost:8000` (e não `127.0.0.1`), porque o callback do OAuth cadastrado no Google usa `localhost`. Em **Estado da sincronização**, clique em **Conectar com o Google**.

Dados locais ficam em `data/` (fora do git): `app.db` (banco SQLite) e `google_token.json` (autorização do Google, permissão 600). Apagar `google_token.json` desconecta a conta; apagar a pasta `data/` zera o cache e o banco.

## 5. Sincronização

*A preencher.*

## 6. Formatos suportados

*A preencher.*

## 7. IA no produto e custo estimado por uso

*A preencher.*

## 8. Limitações conhecidas

*A preencher.*

## 9. Antes de usar dados reais

*A preencher.*

## 10. Ferramentas de IA usadas no desenvolvimento

Claude Code (plano Claude Pro), para análise do material, planejamento e programação em par. Detalhes em [`docs/DIARIO_DE_BORDO.md`](docs/DIARIO_DE_BORDO.md).

## 11. Documentação complementar

- [`docs/DIARIO_DE_BORDO.md`](docs/DIARIO_DE_BORDO.md): decisões, dificuldades e verificações.
- [`docs/VALIDACAO.md`](docs/VALIDACAO.md): casos testados.
