# LIA — Central de contexto e atividades

Aplicação web local que lê uma pasta do Google Drive e ajuda cada membro da Liga de IA da UFSCar a responder duas perguntas: **"O que preciso fazer agora?"** e **"O que mudou desde a última vez?"**. Mudanças encontradas nos documentos viram **sugestões com evidência**, e um humano as aprova antes que alterem qualquer atividade oficial.

> Projeto do case técnico do processo seletivo da Liga IA UFSCar. Todos os dados usados são **fictícios** (pacote de teste do case, copiado em `tests/fixtures/`).
>
> **Estado:** protótipo funcional, entregue em 04/10/2026. 199 testes automatizados; casos conferidos no Drive real em [`docs/VALIDACAO.md`](docs/VALIDACAO.md); decisões e correções em [`docs/DIARIO_DE_BORDO.md`](docs/DIARIO_DE_BORDO.md).

**As seis telas** (menu no topo de todas as páginas):

| Tela | Para que serve |
|---|---|
| **Comece aqui** | Para quem acabou de entrar: propósito, frentes, regras de trabalho, documentos principais e a primeira ação da pessoa — tudo copiado dos documentos de orientação do Drive, com link, e o que ainda está "a confirmar" marcado como tal |
| **Minhas atividades** | O que a pessoa escolhida no topo tem a fazer: prazo (ou "a definir"), estado, próximo passo e aviso de mudança pendente, ordenável por prazo, bloqueios ou sem prazo |
| **Todas as atividades** | Lista com filtros por responsável, frente, estado e prazo; criar atividade; abrir o detalhe com fonte, evidência e histórico |
| **Sugestões para revisar** | Propostas que a IA (atas) ou a comparação de planilhas tiraram dos documentos, com o trecho de origem; aceitar, ajustar ou rejeitar |
| **Novidades dos documentos** | "O que mudou para mim" (confirmado × proposto × incerto) e a linha do tempo de cada arquivo |
| **Estado da sincronização** | Pasta conectada, última leitura, estado e papel de cada arquivo, falhas, conflitos de fonte e o botão **Sincronizar agora** |

## Sumário

1. Arquitetura
2. Fonte oficial das atividades
3. Pessoas de demonstração e permissões
4. Credenciais do Google e pasta do Drive
5. Instalação e execução
6. Como testar com os dados do pacote
7. Sincronização
8. Formatos suportados
9. IA no produto e custo estimado por uso
10. Limitações conhecidas
11. Antes de usar dados reais
12. Dados guardados, cache e como removê-los
13. Ferramentas de IA usadas no desenvolvimento e no produto
14. Testes automatizados
15. Documentação complementar

## 1. Arquitetura

**Em uma frase:** um programa Python roda no seu computador, lê a pasta do Drive a cada 5 minutos, guarda cada versão dos arquivos num banco local (SQLite) e mostra páginas web em `http://localhost:8000`. As atividades oficiais moram nesse banco; os documentos do Drive só geram **propostas**.

```text
 Google Drive (pasta de teste e subpastas — só leitura)
        │  ao iniciar, a cada 5 min e no botão "Sincronizar agora"
        ▼
 1. Leitura ............ lista a pasta, baixa só o que mudou, extrai o texto,
        │                guarda a versão (arquivo + hash do conteúdo)
        ▼
 2. Interpretação ...... o INDEX diz qual planilha é a fonte; importação única
        │                das ACT-*; conflitos de fonte; planilha editada → sugestões
        ▼
 3. Análise das atas ... a IA propõe; o app confere cada proposta contra o texto
        │                (trecho literal, ID existente, data escrita…) → sugestão pendente
        ▼
 Banco local (data/app.db) ◄──── 4. Telas: revisão humana das sugestões,
   atividades oficiais,               criação e edição manual, resumos
   histórico, sugestões
```

**O que acontece em cada etapa**

1. **Leitura** (`sync.py`, `drive.py`, `readers.py`). A pasta inteira é listada, com subpastas. Um arquivo só é baixado de novo se o Drive indicar mudança, e só vira **versão nova** se o texto extraído mudou (hash SHA-256). O ID do Drive é a identidade: renomear não cria outra fonte. Arquivo que sumiu vira "indisponível", com o motivo. Uma falha de leitura nunca apaga nada.
2. **Interpretação** (`authority.py`, `importer.py`, `conflicts.py`). O app acha o `INDEX`, lê qual planilha e qual aba são a fonte das atividades e classifica cada arquivo: fonte das atividades, orientação, ata, histórico substituído (`status: deprecated`) ou sem autoridade. Na primeira vez, importa as `ACT-*` da planilha apontada; depois disso, só gera sugestões e conflitos (seção 2).
3. **Análise das atas** (`analysis.py`, `ai.py`, `suggestions.py`). Cada versão nova de ata vai uma vez para o Gemini, que responde em JSON. O app **não confia** na resposta: confere cada item contra o texto da versão lida e descarta o que não se sustenta, com o motivo visível (seção 9).
4. **Telas** (`main.py`, `templates/`, `activities.py`, `changes.py`, `onboarding.py`). HTML gerado no servidor, com formulários comuns: as telas funcionam sem JavaScript. Um script pequeno só mostra "carregando", trava o envio repetido de formulários e avisa quando a conexão com o app cai.

**Onde fica cada coisa**

| Arquivo | Papel |
|---|---|
| `app/__main__.py` | Inicia o servidor (`python -m app`); tira do log o código de autorização do Google |
| `app/config.py` | Lê o `.env` (os valores nunca são exibidos) |
| `app/schema.sql`, `app/db.py` | Estrutura do banco SQLite e conexão |
| `app/google_auth.py`, `app/drive.py` | Login OAuth com o Google (`state` + PKCE) e chamadas de leitura à Drive API |
| `app/readers.py` | Leitores de Markdown/texto, Google Docs e planilhas; decide o que é ignorado e por quê |
| `app/sync.py` | Varredura, versões, arquivos indisponíveis, trava única, linha do tempo dos arquivos |
| `app/authority.py` | Lê o `INDEX` e decide o papel de cada arquivo |
| `app/importer.py` | Importação única, planilha editada, troca de fonte aceita por uma pessoa |
| `app/conflicts.py` | Conflitos de fonte e decisão humana |
| `app/analysis.py`, `app/ai.py` | Escolhe as atas a analisar, chama o Gemini (ou as regras sem IA), guarda o resultado por versão |
| `app/suggestions.py` | Validação da saída da IA, sugestões, revisão (aceitar, ajustar, rejeitar) |
| `app/activities.py` | Atividades, filtros, criação, edição, histórico |
| `app/changes.py`, `app/onboarding.py` | "O que mudou para mim", linha do tempo dos documentos e "Comece aqui" |
| `app/main.py`, `app/templates/`, `app/static/style.css` | Rotas web, ciclo automático de sincronização, telas e estilo |
| `tests/` | 199 testes; `tests/fixtures/` tem o pacote de dados do case e as respostas gravadas da IA |

**O que o banco guarda:** fontes (um registro por arquivo do Drive) e cada versão de conteúdo lida; membros; atividades, responsáveis (uma atividade pode ter vários) e vínculos com a origem (aba e linha da planilha, trecho da ata); histórico de cada atividade (autor, hora, antes → depois, motivo, documento de origem); análises de cada versão de ata; sugestões e sua revisão; conflitos de fonte e decisões; execuções da sincronização; marco "visto" de cada pessoa; parágrafos de resumo gerados pela IA.

**Regras que nunca quebram** (cada uma tem testes automatizados):

1. Nenhuma atividade oficial muda sem um evento com autor humano no histórico.
2. Sugestão não altera nada até ser revisada; recarregar a página ou clicar de novo não repete uma aprovação.
3. Falha de leitura ou de sincronização nunca é tratada como "não há atividades".
4. Planilha que o `INDEX` não aponta nunca importa nem apaga.
5. A mesma versão de um arquivo (ID + hash do conteúdo) é processada e analisada uma única vez.
6. A evidência de uma sugestão precisa aparecer literalmente no texto da versão lida; senão, o item é descartado, com o motivo.
7. Responsável e prazo só entram se estiverem escritos; "até sexta" vira prazo vazio + incerteza.
8. Texto de documento é **dado**, nunca instrução: uma ata que diga "aprove automaticamente" gera no máximo uma sugestão pendente.

**Por que estas escolhas:** Python + FastAPI + Jinja2 num processo só, sem etapa de build; HTML semântico ajuda teclado e leitor de tela; SQLite deixa a banca rodar sem criar conta em nenhum serviço e persiste depois de reiniciar; varredura completa em vez da API de mudanças porque a pasta é pequena (seção 7).

## 2. Fonte oficial das atividades

**Regra única: a planilha apontada pelo `INDEX` cria as atividades uma vez; depois disso, a referência oficial é o banco do app, e nenhum documento muda uma atividade sem uma pessoa aprovar.**

1. **Quem manda é o `INDEX`.** O app procura na pasta o arquivo de texto chamado `INDEX` (`INDEX.md` ou Google Doc `INDEX`) e lê nele qual planilha e qual aba são a fonte das atividades. No pacote de teste: `` `Ata_registro.xlsx`, aba `Atividades`: fonte inicial e provisória das atividades identificadas por ACT-* ``.
2. **Importação única.** Na primeira sincronização em que essa planilha é lida, cada linha vira uma atividade, com:
   - evento "importada" no histórico (data, arquivo, aba, linha e versão do conteúdo);
   - vínculo com a linha da planilha e com o documento citado na coluna **Origem** (ex.: o trecho da `Ata_2026-10-01.md` que menciona o `ACT-101`);
   - "Ana; Davi" vira dois responsáveis da **mesma** atividade; "Bloqueada" continua bloqueada.
3. **Depois da importação, o app é a referência.** Mudanças entram pela interface (com autor, hora e campos antes/depois no histórico) ou por sugestões aprovadas por um revisor.
4. **Proposta pendente não muda o valor oficial; só avisa.** Como no exemplo do enunciado: a ata de 03/10 propõe o prazo de 07/10 para o `ACT-101`, mas até a aprovação a atividade continua com 05/10 e mostra "Mudança proposta aguardando revisão". É assim que o app aplica a precedência do `INDEX` ("decisão humana aprovada na aplicação > proposta de nova ata ainda pendente > estado atual documentado > fonte ativa apontada no índice > arquivo antigo ou sem autoridade"): a proposta pendente aparece **acima** do valor da planilha, como aviso, e a decisão humana é o que efetivamente troca o valor.
5. **Editar a planilha no Drive não sobrescreve nada.** O app compara a versão nova da planilha com a **versão anterior da própria planilha** (e não com o banco) e transforma cada diferença em **sugestão** para revisão humana: célula mudada → atualização; linha nova → criação (com o ID da linha, se estiver livre); linha apagada → só um aviso, nada é apagado. Comparar com a versão anterior evita que uma edição feita no app (ex.: prazo aprovado pelo Bruno) vire sugestão de "voltar" ao valor antigo da planilha. Se a planilha contradiz um campo que já tem decisão humana no app, a sugestão traz o alerta "definido no app por X em DD/MM".
6. **Planilha que o `INDEX` não aponta nunca importa nem apaga.** É o caso de `Ata - copia vazia.xlsx`: aparece como "sem autoridade" na tela de sincronização, e as atividades continuam intactas. Se ela puder ser confundida com a fonte — **nome parecido** (palavra em comum com a planilha apontada, como "Ata - copia vazia" × "Ata_registro") **ou** cabeçalho de registro de atividades (colunas ID e Atividade) —, vazia ou não, vira um **conflito de fonte** visível (seção 7). Uma planilha sem nenhuma das duas coisas fica só como "sem autoridade". A data do arquivo não importa: "mais recente" não significa "mais confiável".
7. **Ambiguidade não é resolvida por palpite.** Dois `INDEX`, duas planilhas com o nome apontado, `INDEX` citando duas planilhas ou passando a apontar outra depois da importação: nada é importado nem trocado; vira conflito de fonte, com o motivo em "Todas as atividades" e em "Estado da sincronização", até uma pessoa registrar a decisão.
   - **Troca de fonte.** Quando o `INDEX` passa a apontar outra planilha, Bruno escolhe entre **Manter a fonte atual** e **Aceitar a nova fonte** (com motivo escrito). Aceitar **não muda nenhuma atividade**: a nova planilha passa a ser a fonte vigente e cada diferença entre ela e o app vira sugestão para revisão — linha só na planilha → criação (com o ID dela, se livre); atividade só no app → aviso, nunca apagada; célula vazia → ignorada (a troca não apaga valores); campo que já tem decisão humana no app → sugestão com alerta "definido no app por X". As sugestões pendentes da planilha anterior ficam "substituídas", e a planilha anterior passa a aparecer como histórico. Depois disso, edições da nova planilha seguem a regra do item 5.
8. **Dado ausente fica ausente.** Responsável que não é membro, prazo que não é data ("até sexta") ou estado desconhecido não são completados: o campo fica "a confirmar"/"a definir" e o aviso fica registrado no evento de importação.

Atividades criadas no app seguem o mesmo padrão `ACT-*` do material, continuando a numeração (depois de `ACT-104` vem `ACT-105`); a origem "criada manualmente por…" aparece na atividade e no histórico. Se a planilha trouxer depois um ID que já existe no app, a linha não sobrescreve a atividade: é registrada como aviso.

Por que não deixar a planilha como fonte oficial: o app só tem permissão de leitura no Drive (escrever lá está fora do escopo), então haveria duas verdades — a planilha e o que foi aprovado no app. Alternativas consideradas estão no [diário de bordo](docs/DIARIO_DE_BORDO.md) (03/10).

## 3. Pessoas de demonstração e permissões

Não há login de membro: no topo de todas as páginas, **Usuário de demonstração** escolhe quem você é. Trocar de pessoa muda "Minhas atividades", "Comece aqui", o resumo pessoal e o que pode ser revisado; os dados não mudam. Ações que gravam (criar, editar, revisar, decidir conflito) exigem uma pessoa escolhida e ficam registradas no nome dela.

| Pessoa | Frente | O que pode fazer (base no material) |
|---|---|---|
| Ana | Growth | Criar e editar atividades; vê, só para leitura, as sugestões que afetam suas atividades |
| Bruno | Growth | Tudo o que a Ana faz, mais **revisar sugestões de qualquer frente** ("pode revisar sugestões", `LEIA_ME_PRIMEIRO.md`, sem limite de frente) e **decidir conflitos de fonte** |
| Carla | Formação | Tudo o que a Ana faz, mais **revisar sugestões da Formação** ("revisa propostas de atividades da sua frente", `GUIA_INICIAL.md`) |
| Davi | Operações | Como a Ana |

- A frente de uma sugestão de atualização é a da atividade; a de uma criação é a do responsável proposto (marcada como inferida).
- Quem é responsável pela atividade pode revisar a sugestão dela: o material não proíbe nem exige "quatro olhos". O app avisa ("você é responsável por esta atividade") e registra a auto-revisão no histórico.
- As quatro pessoas vêm do `LEIA_ME_PRIMEIRO.md` do pacote e estão fixas no banco (`app/schema.sql`). Em produção, viriam do login (seção 11).

## 4. Credenciais do Google e pasta do Drive

Siga o guia do Drive que veio com o case; o resumo abaixo é o que este app precisa. Use uma **conta Google pessoal** (conta institucional pode dar `403 domainPolicy`) e só dados fictícios.

**4.1 Google Cloud** ([console.cloud.google.com](https://console.cloud.google.com/))

1. Crie um projeto. **Não é preciso faturamento** (a Drive API não cobra pelo uso padrão).
2. **APIs e serviços → Biblioteca → Google Drive API → Ativar.**
3. **Google Auth Platform:**
   - **Branding:** nome do app e e-mail de suporte;
   - **Audience:** *External*, status *Testing*, e **seu e-mail em *Test users*** (sem isso o login dá `403 access_denied`);
   - **Data Access:** só o escopo `https://www.googleapis.com/auth/drive.readonly`.
4. **Clients → Create client → Web application:**
   - *Authorized JavaScript origins:* `http://localhost:8000`
   - *Authorized redirect URIs:* `http://localhost:8000/auth/callback` (exatamente assim; qualquer diferença dá `redirect_uri_mismatch`)
   - copie o *Client ID* e o *Client secret* para o `.env`.

Por que `drive.readonly`: o app precisa achar arquivos colocados direto na pasta, sem que alguém os escolha um a um (`drive.file` não vê esses arquivos), e nunca escreve (não pede `drive`). O filtro pela pasta é feito pelo app. É um escopo **restrito**: em *Testing* funciona para os *Test users*; um uso público exigiria verificação do Google (seção 11).

**4.2 Pasta no Drive**

1. Nas configurações do Drive, **desligue "Converter uploads"** para que o `.xlsx` continue `.xlsx` e o `.md` continue `.md`, como o pacote pede (o app também lê Google Planilhas, mas o teste fica fiel ao material).
2. Crie a pasta (ex.: `LIA case teste`). O ID é o trecho final do endereço: `https://drive.google.com/drive/folders/<ID>` → `DRIVE_TEST_FOLDER_ID`.
3. Só essa pasta e as subpastas dela são lidas, mesmo que a conta tenha acesso a outros arquivos. A tela "Estado da sincronização" mostra a pasta monitorada.

**4.3 `.env`**

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"   # cole em APP_SECRET_KEY
```

Preencha `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `DRIVE_TEST_FOLDER_ID` e, se quiser IA, `GEMINI_API_KEY` (chave gratuita em [aistudio.google.com/apikey](https://aistudio.google.com/apikey); sem ela, as atas são lidas por regras simples — seção 9). O `.env` está no `.gitignore` e nunca deve ser enviado ao repositório. A tela de sincronização avisa quais variáveis obrigatórias faltam (só os nomes, nunca os valores).

**4.4 Conectar**

Com o app rodando (seção 5), abra `http://localhost:8000/sincronizacao` → **Conectar com o Google** → escolha a conta de teste. Em *Testing*, o Google pode avisar que o app não foi verificado: como o app é seu, siga em **Continuar**. Confira que o acesso pedido é só de **leitura** do Drive. Ao voltar, a primeira sincronização roda sozinha.

- O token fica em `data/google_token.json` (fora do git, permissão 600). Em *Testing*, o Google o invalida em **7 dias**: se a tela disser que a autorização expirou, clique em **Conectar com o Google** de novo.
- **Desconectar conta** apaga o token deste computador. Para revogar no Google: [myaccount.google.com/connections](https://myaccount.google.com/connections) → o app → **Remover acesso**.

| Erro | O que conferir |
|---|---|
| `redirect_uri_mismatch` | A URI cadastrada no cliente tem de ser idêntica a `GOOGLE_REDIRECT_URI` (protocolo, porta, caminho, sem barra final) |
| `403 access_denied` | Seu e-mail em *Test users* (Audience) |
| `403 domainPolicy` | Use uma conta pessoal |
| "state não confere" | Abra o app por `http://localhost:8000` (não `127.0.0.1`) e conecte de novo |
| Pasta não lida ("Arquivo não encontrado ou sem acesso", "Acesso negado pelo Drive") | `DRIVE_TEST_FOLDER_ID` e a conta escolhida no login (a pasta precisa ser dela ou compartilhada com ela) |

## 5. Instalação e execução

Requer Python 3.13 (versão testada).

```bash
git clone https://github.com/ViniMBlanco/lia-central-atividades.git
cd lia-central-atividades
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # preencha conforme a seção 4
python -m app                    # abre em http://localhost:8000
python -m pytest                 # testes automatizados (não precisam de credenciais nem de internet)
```

- Abra pelo endereço `http://localhost:8000` (e não `127.0.0.1`), porque o callback do OAuth cadastrado no Google usa `localhost`.
- **Sem credenciais** o app abre do mesmo jeito: a tela de sincronização diz o que falta no `.env`, "Comece aqui" diz que nenhum documento foi lido do Drive ainda e os testes rodam normalmente.
- Para parar: `Ctrl+C`. Ao subir de novo, tudo continua (banco em `data/app.db`) e a primeira leitura do Drive roda na hora.
- Porta ocupada: mude `APP_PORT` **e** a porta em `GOOGLE_REDIRECT_URI` e no cliente OAuth do Google.

## 6. Como testar com os dados do pacote

Roteiro de execução local, na ordem do `LEIA_ME_PRIMEIRO.md` do pacote. Os arquivos estão em `tests/fixtures/`. Depois de cada envio ao Drive, espere até 5 minutos ou clique em **Sincronizar agora**; a análise das atas pela IA termina em segundo plano (10 a 20 s por ata) — recarregue "Sugestões para revisar".

| Passo | O que fazer | O que deve aparecer |
|---|---|---|
| 1. Carga inicial | Envie para a pasta os 6 arquivos de `tests/fixtures/01_CARGA_INICIAL/`, sem mudar os nomes; conecte a conta | 6 arquivos "Processado" com link; cartão "Fonte das atividades" com o selo "Em vigor" (`Ata_registro.xlsx`, aba Atividades); o plano antigo com o papel "Histórico (substituído)". Em **Minhas atividades**: Ana → ACT-101 e ACT-104; Davi → ACT-102 e ACT-104 (ACT-104 é uma atividade só, com dois responsáveis); Carla → ACT-103 (bloqueada); Bruno → nenhuma. A ata de 01/10 é analisada e gera **0** sugestões (só repete a planilha). **Comece aqui** mostra o propósito com o selo "Provisório: a confirmar" |
| 2. Ata nova (Google Docs) | Envie `02_ADICIONAR_DEPOIS_DA_CARGA/Ata_2026-10-03.docx` e, no Drive, abra-o e use **Arquivo → Salvar como Documentos Google** (não envie também o `.md` da mesma ata) | O `.docx` fica "Ignorado", com o motivo e a instrução de conversão; o Google Doc é processado e gera **1 sugestão de atualização do ACT-101** (prazo 05/10 → 07/10 e próximo passo), com o trecho da ata. Ana continua a única responsável (Bruno aprova a versão final, não executa). O ACT-101 **continua com 05/10**, com aviso de mudança pendente |
| 3. Ata com decisão e hipótese | Envie `02_ADICIONAR_DEPOIS_DA_CARGA/Ata_2026-10-04.md` | **1 sugestão de criação** para Carla (Formação, prazo 10/10, "possivelmente relacionada: ACT-103"); **nada** sobre a "série diária de notícias" ("Talvez…", ninguém assumiu) |
| 4. Revisão humana | Escolha **Bruno** → Sugestões para revisar → a do ACT-101 → **Aceitar**. Depois **Carla** → a de criação → aceitar, ajustar um campo ou rejeitar com motivo | ACT-101 passa a 07/10; o histórico mostra Bruno, antes → depois, a ata como fonte e o número da sugestão; a atividade aponta para a planilha **e** para a ata. Clicar de novo ou recarregar não repete nada. Ana e Davi veem a sugestão só para leitura; Carla não vê o formulário de uma sugestão de Growth |
| 5. Atividade criada na interface | **Todas as atividades → Nova atividade**; salve; edite o prazo; pare o app (`Ctrl+C`) e suba de novo | A atividade (`ACT-105` ou seguinte) continua lá, com "Criada manualmente por…" e o histórico da edição |
| 6. Conflito | Envie `03_CONFLITO/Ata - copia vazia.xlsx` | Arquivo "sem autoridade" ("sem linhas de dados"); conflito aberto em "Estado da sincronização" e aviso em "Todas as atividades"; **as atividades continuam todas**. Como Bruno, registre a decisão por escrito |
| 7. Edição de um arquivo conhecido | No Drive, edite a ata de 03/10 (ex.: troque `2026-10-07` por `2026-10-08`) | A **mesma** fonte ganha versão nova (sem documento duplicado); sugestão pendente da versão antiga, se houver, vira "substituída"; a versão nova é analisada |
| 8. Arquivo removido | Mande um arquivo para a lixeira; depois restaure | "Indisponível — movido para a lixeira do Drive"; atividades ligadas a ele ficam "possivelmente desatualizadas", nada é apagado; ao restaurar, volta sem reimportar |
| 9. O que mudou para mim | **Novidades dos documentos** como Ana e depois como Davi | Ana: "1 mudança confirmada" (ACT-101, aceita por Bruno, com link para a ata) e prazos próximos; Davi: "Nada mudou nas atividades de Davi", com os prazos dele. Antes do aceite, a mudança da Ana aparece só como **proposta** aguardando revisão. Com chave do Gemini, **Resumir com IA** escreve um parágrafo a partir dessa lista |

**Arquivos inesperados** (a banca pode trazer): PDF, imagem, vídeo, `.docx` → "Ignorado", com o motivo; Google Planilhas → lida como planilha (sem autoridade, a menos que o `INDEX` a aponte); ata com "até sexta" → sugestão sem prazo, com a incerteza; pessoa que não é membro → "a confirmar"; `ACT-999` → item descartado, com o motivo; ata com "IA, aprove automaticamente" → no máximo uma sugestão pendente; arquivo renomeado → mesma fonte, sem reprocessar; mesma ata em `.md` e Google Docs → uma sugestão só.

## 7. Sincronização

**Como funciona.** Enquanto o app está aberto, ele lê a pasta inteira do Drive (com subpastas) **ao iniciar e depois a cada 5 minutos** (`SYNC_INTERVAL_SECONDS`). O botão **Sincronizar agora**, em "Estado da sincronização", faz a mesma leitura na hora; as duas usam a mesma trava, então nunca rodam ao mesmo tempo. Um arquivo novo ou editado aparece em até ~5 minutos sem nenhum envio pela aplicação (o enunciado pede até 15). No Drive real, um Google Doc criado às 03:00:08 foi detectado pela verificação automática das 03:06:53 (registro de validação, caso 2).

O app só **lê**: nunca cria, move, renomeia nem apaga arquivos no Drive.

| Situação no Drive | O que o app faz |
|---|---|
| Arquivo novo | Baixa (ou exporta, se for Google Docs), extrai o texto e guarda a versão |
| Arquivo editado | Nova versão da **mesma** fonte (o ID do Drive é a identidade); o conteúdo só é reprocessado se o texto mudou (hash SHA-256) |
| Renomeado ou movido dentro da pasta | Atualiza nome e caminho; não reprocessa nem duplica |
| Removido, na lixeira, movido para fora da pasta ou sem acesso | Fonte marcada **indisponível**, com o motivo. O último conteúdo lido fica guardado; atividades ligadas a ela continuam e aparecem como **possivelmente desatualizadas**; sugestões dela não podem ser aceitas enquanto o arquivo não voltar |
| Falha ao ler um arquivo (erro do Drive, arquivo corrompido, > 10 MB) | Só esse arquivo fica **com falha**, com o motivo; os outros seguem. A versão anterior continua valendo |
| Falha geral (sem internet, autorização expirada, pasta inacessível) | Nada é marcado como removido — falha de leitura nunca vira "não há atividades". Todas as telas avisam que os dados são o último estado confirmado; criar e editar atividades continua funcionando |
| Formato não suportado (`.docx`, PDF, imagem, vídeo) | **Ignorado**, com o motivo; nenhum conteúdo é inventado |

**Falhas e novas tentativas.** Depois de uma falha, a próxima tentativa automática vem mais cedo (30 s, 1, 2 e 4 min) e volta aos 5 minutos quando dá certo. Se nenhuma leitura der certo por mais de dois intervalos, todas as telas mostram "Dados possivelmente desatualizados". A tela mostra a hora prevista da próxima verificação automática.

**Conflitos de fonte.** Quando os arquivos não deixam claro qual é a verdade — planilha não apontada pelo `INDEX` com nome parecido ou com cabeçalho de registro de atividades (como `Ata - copia vazia.xlsx`), dois `INDEX`, duas planilhas com o nome apontado, ou o `INDEX` passando a apontar outra planilha —, o app registra um conflito. O conflito **nunca altera atividades**: fica visível em "Estado da sincronização" (e com aviso em "Todas as atividades") até uma pessoa que revisa todas as frentes (Bruno, nos dados de teste) registrar a decisão por escrito. No caso de o `INDEX` apontar outra planilha, a decisão pode ser **aceitar a nova fonte** (seção 2, item 7). Se a situação desaparece sozinha (o arquivo sai da pasta), o conflito fica como "superado". Uma versão nova do mesmo arquivo abre um conflito novo, porque a decisão anterior valia para outro conteúdo.

**Por que ler a pasta inteira, e não a API de mudanças do Drive.** A pasta é pequena, a leitura completa é barata (arquivos sem mudança não são baixados de novo) e deixa óbvio o que saiu da pasta: é o que não apareceu na leitura. A `changes.list` seria uma otimização para acervos grandes.

## 8. Formatos suportados

| Formato | Como é lido |
|---|---|
| Markdown (`.md`) e texto (`.txt`) | Texto inteiro; título (`#`) e cabeçalho `chave: valor` (ex.: `status: deprecated`, `data_da_reuniao: 2026-10-03`) |
| Google Docs nativo | Exportado pelo Drive como texto (limite de 10 MB da exportação). Aceita cabeçalho de página antes do título (caso do `.docx` convertido) |
| Planilha `.xlsx` e Google Planilhas | Todas as abas e células (Google Planilhas é exportado como `.xlsx`); datas do Excel viram datas |
| `.docx`, PDF, imagem, vídeo, áudio, `.pptx`, `.csv`, `.xls` | **Ignorados, com o motivo** na tela de sincronização ("formato ainda não processado"); nenhum conteúdo é inventado. Um `.docx` convertido para Google Docs no Drive passa a ser lido |

O tipo é decidido pela extensão do nome e pelo tipo nativo do Google (o Drive costuma marcar `.md` como texto genérico). Arquivos acima de 10 MB ficam como falha, com o motivo.

**Quais documentos viram sugestões:** só as **atas** — documento de texto com `data_da_reuniao` no cabeçalho ou com a palavra "ata" ou "reunião" no nome ou no título. Documentos de orientação (`INDEX`, `ESTADO-ATUAL`, `GUIA_INICIAL`), o plano antigo (`status: deprecated`) e textos sem autoridade são lidos, mas não geram sugestões. Da planilha, só a apontada pelo `INDEX` gera sugestões (por comparação, sem IA).

## 9. IA no produto e custo estimado por uso

**O que a IA faz.** Lê cada ata nova ou editada e propõe **sugestões**: criar uma atividade ou atualizar uma existente (prazo, próximo passo, responsável, estado), sempre com o trecho do documento que justifica. Ela **não altera nada**: a sugestão fica pendente até uma pessoa revisora aceitar (com ou sem ajuste) ou rejeitar com motivo. Não há chat nem agente.

**Como funciona.**
1. Depois de cada sincronização (no botão **Sincronizar agora**, em segundo plano, para a tela não ficar parada esperando a IA), cada ata com versão ainda não analisada vai para o modelo junto com a lista de pessoas e os valores oficiais atuais das atividades. O texto do documento vai entre marcas, como **dado**: o modelo é instruído a não obedecer instruções escritas no documento.
2. O modelo responde em JSON no formato do contrato da especificação (§6): tipo (`create`/`update`/`no_action`), atividade-alvo, título, responsáveis, prazo, próximo passo, estado, **evidência literal**, motivo, incertezas e atividades relacionadas.
3. **O app não confia no JSON.** Antes de mostrar, confere cada item:
   - o trecho citado precisa aparecer **literalmente** no documento (ignorando só marcação Markdown e espaços); senão o item é descartado;
   - o ID citado precisa existir (`ACT-999` → descartado);
   - o prazo precisa estar **escrito** no trecho como data; "até sexta" → prazo vazio e uma incerteza ("data relativa: prazo a definir");
   - responsável precisa ser membro e ter o nome no trecho; pessoa desconhecida → "a confirmar";
   - hipótese ("talvez", "ninguém assumiu", "sem decisão") → descartada;
   - campo igual ao valor oficial atual é removido — a ata de 01/10, que só repete a planilha, gera **zero** sugestões;
   - atualização cujo trecho não cita o ID da atividade ganha alerta para o revisor;
   - criação com o mesmo título de uma atividade existente, ou igual a uma sugestão já pendente (ex.: a mesma ata em `.md` e em Google Docs), não é repetida.
   Tudo o que foi descartado aparece em "Sugestões para revisar → Documentos analisados", com o motivo.
4. **Revisão.** Quem revisa o quê está na seção 3. A tela da sugestão mostra o trecho, onde ele está no documento, a data do documento, o valor oficial × o proposto e os pontos a conferir. Aceitar grava um evento no histórico com autor, hora, antes/depois, a ata como fonte e o número da sugestão; clicar de novo ou recarregar não repete nada.
5. **Idempotência e edição.** Cada versão de documento é analisada uma única vez (arquivo + hash do conteúdo). Se a ata é editada no Drive, as sugestões pendentes da versão antiga ficam "substituídas" e a versão nova é analisada.
6. **Falhas.** Sem resposta do modelo, cota esgotada ou resposta fora do formato: a análise fica "falhou", com o motivo, na tela de sugestões e no Estado da sincronização; os dados oficiais não mudam e criar/editar atividades continua funcionando. O app tenta de novo nas próximas sincronizações (até 3 vezes por versão) e há o botão **Tentar de novo**.

**Provedor.** Gemini API, modelo `gemini-3.6-flash` (configurável em `GEMINI_MODEL`), pelo SDK oficial `google-genai` com saída estruturada (`response_json_schema`). Sem `GEMINI_API_KEY` (ou com `AI_PROVIDER=none`), o app usa **regras simples sem IA** (ID `ACT-*` + data escrita + "Próximo passo:"), que cobrem os casos do pacote de teste mas não textos livres; o botão "Resumir com IA" não aparece.

**Custo medido (04/10/2026, atas do pacote de teste, `gemini-3.6-flash`):** por ata, cerca de **1 mil tokens de entrada** e **2 a 2,6 mil de saída** (a maior parte é o raciocínio do modelo), em 10 a 20 segundos.

| Cenário | Custo |
|---|---|
| Camada gratuita do Gemini (usada no protótipo) | **US$ 0**. Os limites não são publicados como números fixos (ver Google AI Studio); para `gemini-3.8-flash` a API informou em 04/10 **5 pedidos por minuto e 20 por dia** por projeto e por modelo. Uma demonstração completa usa de 3 a 6 pedidos |
| Camada paga (US$ 0,75 por milhão de tokens de entrada e US$ 3,75 por milhão de saída até 31/12/2026; o dobro a partir de 2027 — tabela oficial consultada em 04/10) | cerca de **US$ 0,01 por ata**; 100 atas por mês ≈ US$ 1 (≈ US$ 2 em 2027) |
| Resumo pessoal com IA (botão) | cerca de **US$ 0,001 por resumo** na camada paga (~650 tokens de entrada, ~100 de saída) |
| Reprocessar, recarregar, sincronizar de novo | **US$ 0**: o resultado fica guardado por versão do documento |
| Planilha editada | **US$ 0**: comparação célula a célula, sem IA |
| Drive API | **US$ 0**: uso padrão sem custo; o projeto do Google Cloud nem tem faturamento |

Na camada gratuita, o Google pode usar o conteúdo enviado para melhorar seus produtos: aceitável com os dados fictícios do case, **não** com documentos reais (seção 11).

**Por que este modelo (04/10, mesmas três atas, saída passada pela validação do app):**

| Modelo | Gabarito | Tempo por ata | Preço pago (entrada / saída, por milhão de tokens) | Observação |
|---|---|---|---|---|
| `gemini-3.6-flash` (**escolhido**) | 3/3, repetido 2 vezes | 10–20 s | US$ 0,75 / 3,75 | Nenhum erro em 6 chamadas |
| `gemini-3.8-flash` | 3/3 | 15–25 s | US$ 0,75 / 3,75 | Erros 503 (sobrecarga) e cota gratuita diária de 20 pedidos esgotada durante o desenvolvimento |
| `gemini-3.7-flash` | — | — | US$ 0,75 / 3,75 | Erros 503/504 (sobrecarga) nas três tentativas |
| `gemini-3.5-flash` | 3/3, repetido 2 vezes | 7–13 s | US$ 1,50 / 9,00 | Um pouco mais rápido, 2 a 2,4 vezes mais caro |
| `gemini-3.5-flash-lite` | **2/3** | ~1,5 s | US$ 0,30 / 2,50 | Leu a ata de 04/10 (tarefa nova, sem ID) como "atualizar ACT-103", uma tarefa bloqueada |

Trocar de modelo é só mudar `GEMINI_MODEL`; cada modelo tem cota gratuita própria.

**Resumo pessoal ("O que mudou para mim", em Novidades dos documentos).** O resumo é montado **sem IA**, a partir dos registros: mudanças **confirmadas** nas atividades da pessoa (eventos do histórico, com antes → depois, autor, hora e documento de origem), **propostas** que a afetam e ainda aguardam revisão, dados **incertos ou em conflito** (prazo a definir, fonte indisponível, ponto a conferir numa proposta, conflito de fonte aberto, ata ainda sem análise, leitura do Drive com falha) e **prazos próximos e bloqueios**. Se nada mudou, a tela diz isso. O marco é a última vez que a pessoa clicou em **Marcar como visto** (ou um período escolhido: 24 h, 7 dias, desde o início); abrir ou recarregar a página não marca nada.

Por cima da lista, o botão **Resumir com IA** pede ao Gemini um parágrafo de 2 a 4 frases escrito **só a partir dos itens da lista** (nenhum texto de documento além do que já está na tela). O app confere o parágrafo antes de mostrar e o **descarta inteiro** se ele citar uma data, um `ACT-*` ou uma pessoa que não estão nos itens, ou se escrever um valor que só existe numa proposta pendente sem dizer que é proposta (ex.: "o prazo passou para 07/10" antes do aceite). O parágrafo fica guardado por pessoa e conjunto de itens: pedir de novo com os mesmos itens não chama a IA; quando os itens mudam, o parágrafo antigo some. Medido em 04/10 (`gemini-3.6-flash`, raciocínio "baixo"): ~650 tokens de entrada, ~100 de saída, 1,5 a 4 s.

## 10. Limitações conhecidas

**Drive e sincronização**
- A sincronização só roda com o app aberto; não há notificação do Drive (webhook) nem uso da API de mudanças. Para uma pasta grande, a varredura completa a cada 5 minutos ficaria cara (seção 7).
- PDF não é lido (texto selecionável seria um diferencial; ficou de fora). `.docx` precisa ser convertido para Google Docs no Drive. OCR, imagem e vídeo estão fora do escopo do case.
- O conteúdo de um arquivo que saiu da pasta continua no banco local (é o "último estado confirmado"); não há limpeza automática (seção 12).

**Fonte oficial e conflitos**
- "Aceitar a nova fonte" só existe quando o `INDEX` passa a apontar outra planilha. Para uma planilha com nome parecido (sem autoridade) ou uma fonte ambígua, a decisão é só registrada: aceitá-las contrariaria o `INDEX` ou exigiria escolher entre duas planilhas, um fluxo que não foi feito.

**IA**
- A camada gratuita do Gemini tem cota diária pequena (20 pedidos por dia e por modelo, no limite informado para o `gemini-3.8-flash`). Esgotada a cota, as atas ficam com análise pendente (visível) até a cota voltar ou até trocar o modelo em `GEMINI_MODEL`.
- A IA lê só atas. Ela pode errar quem é responsável quando a ata cita várias pessoas (ex.: quem aprova × quem executa); a validação garante só que o nome está escrito no trecho, e a decisão final é do revisor.
- Sem chave de IA, as regras simples só reconhecem frases no formato do pacote de teste (ID `ACT-*`, data `AAAA-MM-DD`, "Próximo passo:").
- A evidência é conferida como texto (ignorando marcação Markdown e espaços); um trecho parafraseado pelo modelo é descartado, mesmo que o sentido esteja certo.
- A conferência do parágrafo da IA no resumo pessoal pega datas, IDs e nomes fora dos itens e propostas ditas como fato quando há data; uma frase que exagere sem citar data (ex.: "tudo foi aprovado") não é detectada. Por isso a lista com os links continua sendo a referência, logo abaixo do parágrafo.
- O provedor Claude, previsto no planejamento como opção configurável, não foi implementado: eu não tinha chave da API da Anthropic para testar (seção 13). O ponto de troca existe (`provider_for` em `app/ai.py`).

**Pessoas e acesso**
- Não há login de membro: qualquer pessoa com o navegador aberto escolhe qualquer usuário de demonstração. As quatro pessoas estão fixas no banco.
- Todas as pessoas veem todas as fontes lidas pela conta conectada (seção 11).
- "Marcar como visto" vale por pessoa de demonstração (não por navegador). Horários são gravados ao segundo: algo que acontece no mesmo segundo da marcação fica fora do "desde a última visita".

**Telas**
- **Comece aqui** reconhece os documentos de orientação pelo nome: o `INDEX`, o de estado atual ("estado" no nome) e o guia ("guia" no nome ou título "Comece aqui"). Propósito = primeiro parágrafo do estado atual; frentes = frases que começam pelo nome da frente e itens "Frente: …" do guia. Documentos com outra estrutura aparecem na lista de referência, mas o propósito ou as frentes ficam "a confirmar" — o app não escreve esses textos por conta própria.
- O propósito marcado como provisório é confirmado **no documento** (`ESTADO-ATUAL.md`, por quem o campo `responsavel_por_confirmar` indica), não no app; o selo some na sincronização seguinte à edição.
- A linha do tempo de "Novidades dos documentos" registra renomeação, saída da pasta, volta e falha de leitura a partir da Fase 5; em bancos anteriores, a saída de um arquivo é reconstruída do histórico de sincronizações (e marcada como reconstruída).
- Acessibilidade conferida por capturas de tela (390 px e 1280 px), cálculo de contraste (menor texto 6,99:1) e revisão do HTML (elementos nativos, rótulos, estado com ícone + texto, foco visível); **não** houve teste com leitor de tela nem auditoria automática (axe/Lighthouse).
- O aviso "Sem conexão com o app" aparece na hora quando o navegador perde a rede, mas pode levar até 30 s quando é o app que parou (a página confere o endereço `/saude` a cada 30 s); um envio feito nesse intervalo cai na página de erro do navegador.

**Execução**
- Um processo e um banco SQLite locais: serve para uma pessoa ou uma demonstração, não para vários usuários ao mesmo tempo num servidor.

## 11. Antes de usar dados reais

O protótipo só pode ser usado com os dados fictícios do case. Para documentos reais da Liga, faltaria:

1. **Login de verdade e controle de acesso coerente com o Drive.** Trocar o "usuário de demonstração" por login com a conta Google de cada membro (Google Sign-In / OpenID Connect), servido por HTTPS. A pessoa logada vira o autor dos eventos. Os papéis (quem revisa qual frente, quem decide conflitos) passam a uma tabela administrada por alguém da diretoria, em vez de fixos no código.
2. **Cada pessoa vê só o que pode abrir no Drive.** Hoje uma conta lê a pasta e todos veem tudo. Com dados reais: guardar, para cada fonte, a lista de quem pode lê-la (permissões do arquivo pela Drive API, atualizadas a cada sincronização) e filtrar por ela **toda** tela que mostra trecho, nome ou link de arquivo — Comece aqui, Novidades, detalhe da atividade, evidência da sugestão — e o que vai para a IA no resumo pessoal (só itens de fontes que a pessoa pode abrir). Uma atividade cuja única fonte a pessoa não pode ler mostraria só os campos oficiais, sem o trecho.
3. **Verificação do app no Google.** `drive.readonly` é escopo restrito: fora do modo *Testing* (limitado a usuários de teste e com token de 7 dias), o Google exige verificação do app e pode exigir avaliação de segurança. Alternativa a avaliar: uma conta de serviço do Workspace da Liga com acesso só à pasta, se a organização usar Workspace.
4. **IA com contrato que não use os dados para treino.** Camada paga do Gemini (ou outro provedor com essa garantia), e revisar o que é enviado: hoje vai o texto inteiro da ata, a lista de membros e os valores oficiais das atividades.
5. **Guardar o mínimo e apagar o que não serve mais** (seção 12): política de retenção para o texto de fontes indisponíveis e para respostas da IA guardadas para auditoria; apagar o conteúdo quando o acesso for revogado.
6. **Operação:** segredos num gerenciador de segredos (não num `.env` em disco), cópia de segurança do banco (ou um banco gerenciado), log sem conteúdo de documentos, e sincronização por `changes.list` se o acervo crescer.

## 12. Dados guardados, cache e como removê-los

**O que fica no computador** (pasta `data/`, fora do git):

| O quê | Onde | Por quê |
|---|---|---|
| Token do Google | `data/google_token.json` (permissão 600) | Ler o Drive sem a pessoa presente (sincronização automática) |
| Texto extraído de cada versão de arquivo | `data/app.db`, tabela `source_versions` | Conferir a evidência das sugestões contra a versão exata, montar o Comece aqui e manter o último estado confirmado quando o Drive falha |
| Trechos citados | `activity_refs`, `suggestions` | Mostrar a origem de cada atividade e sugestão |
| Respostas da IA | `analyses.raw_response`, `personal_summaries` | Auditoria e para não pagar a mesma análise duas vezes |
| Atividades, histórico, decisões | `activities`, `activity_events`, `conflicts`… | São os dados oficiais |

**Como remover**

- **Desconectar:** botão **Desconectar conta** em "Estado da sincronização" (apaga o token local) **e** revogar no Google ([myaccount.google.com/connections](https://myaccount.google.com/connections) → o app → Remover acesso). Revogar impede novas leituras, mas **não** apaga o que já foi copiado: para isso, o passo seguinte.
- **Apagar tudo:** pare o app e apague a pasta `data/`. Isso apaga também as atividades criadas e as decisões tomadas no app, que não existem em nenhum outro lugar.
- **Arquivo excluído ou com acesso retirado no Drive:** a fonte vira "indisponível" na sincronização seguinte (até 5 min). A partir daí ela deixa de ser usada como fonte confirmada — atividades ligadas a ela aparecem como "possivelmente desatualizadas" e sugestões dela não podem ser aceitas —, mas o texto da última versão **continua** no banco. Hoje, para apagá-lo, é preciso apagar o banco inteiro.
- **Em produção** (seção 11): apagar automaticamente o texto extraído de fontes indisponíveis depois de um prazo (mantendo só o hash e os trechos já usados como evidência em decisões aprovadas) e apagar tudo o que veio de uma conta quando o acesso dela for revogado.

## 13. Ferramentas de IA usadas no desenvolvimento e no produto

**Para construir:** **Claude Code** (plano Claude Pro), da Anthropic. Usei para ler e comparar o material do case, planejar as fases, programar em par, escrever testes e conferir as telas por capturas de tela. Toda afirmação sobre o case precisou vir com arquivo e trecho do material; as decisões de produto foram minhas, e as saídas do modelo que se mostraram erradas estão registradas no [diário de bordo](docs/DIARIO_DE_BORDO.md) — por exemplo, a regra de quando uma planilha vira conflito, o formato de ID das atividades criadas no app e a leitura da ata de 04/10 por um modelo mais barato. O plano Claude Pro não inclui acesso à API, por isso o Claude não é usado dentro do produto.

**Dentro do produto:** **Gemini** (`gemini-3.6-flash`, Google, pela Gemini API) em dois pontos, e só neles: leitura das atas para propor sugestões (seção 9) e o parágrafo opcional do resumo pessoal. Nenhuma das duas altera dados; tudo passa por validação e, no caso das sugestões, por revisão humana. Sem chave, o app funciona com regras sem IA.

## 14. Testes automatizados

```bash
python -m pytest        # 199 testes, ~15 s, sem internet; sem credenciais do Google, 198 passam e 1 é pulado (o do login)
```

- Um **Drive falso em memória** (`tests/conftest.py`) recebe os arquivos do pacote (`tests/fixtures/`) e simula edição, renomeação, lixeira, arquivo movido, falha de leitura e falha de listagem.
- A IA nunca é chamada nos testes: eles usam as **respostas reais** do `gemini-3.6-flash` para as três atas do pacote, gravadas em `tests/fixtures/ia/` em 04/10/2026, e respostas simuladas para os casos de erro (trecho inexistente, `ACT-999`, prazo relativo, pessoa fora do trecho, instrução dentro do documento).
- Cobrem: leitores, sincronização, autoridade das fontes, importação única, conflitos, atividades (filtros, criação, edição, histórico, persistência após reiniciar), sugestões (validação, revisão, permissões, idempotência, ata editada, planilha editada, troca de fonte), resumo pessoal, Comece aqui e páginas de erro.

Os casos conferidos à mão, no Drive real, estão em [`docs/VALIDACAO.md`](docs/VALIDACAO.md).

## 15. Documentação complementar

- [`docs/VALIDACAO.md`](docs/VALIDACAO.md): registro de validação — 21 casos com entrada, esperado, observado e correções (inclui conflito, dado ausente e arquivo adicionado ao Drive).
- [`docs/DIARIO_DE_BORDO.md`](docs/DIARIO_DE_BORDO.md): como o trabalho foi feito — decisões, mudanças de direção, saídas do modelo corrigidas, testes e o que ficou de fora.
