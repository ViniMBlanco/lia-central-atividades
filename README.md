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

*A preencher.*

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
