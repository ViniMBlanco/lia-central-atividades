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
4. **Editar a planilha no Drive não sobrescreve nada.** O app compara a versão nova da planilha com a **versão anterior da própria planilha** (e não com o banco) e transforma cada diferença em **sugestão** para revisão humana: célula mudada → atualização; linha nova → criação (com o ID da linha, se estiver livre); linha apagada → só um aviso, nada é apagado. Comparar com a versão anterior evita que uma edição feita no app (ex.: prazo aprovado pelo Bruno) vire sugestão de "voltar" ao valor antigo da planilha. Se a planilha contradiz um campo que já tem decisão humana no app, a sugestão traz o alerta "definido no app por X em DD/MM".
5. **Planilha que o `INDEX` não aponta nunca importa nem apaga.** É o caso de `Ata - copia vazia.xlsx`: aparece como "sem autoridade" na tela de sincronização, e as atividades continuam intactas. Se ela puder ser confundida com a fonte — **nome parecido** (palavra em comum com a planilha apontada, como "Ata - copia vazia" × "Ata_registro") **ou** cabeçalho de registro de atividades (colunas ID e Atividade) —, vazia ou não, vira um **conflito de fonte** visível (ver seção 5). Uma planilha sem nenhuma das duas coisas fica só como "sem autoridade". A data do arquivo não importa: "mais recente" não significa "mais confiável".
6. **Ambiguidade não é resolvida por palpite.** Dois `INDEX`, duas planilhas com o nome apontado, `INDEX` citando duas planilhas ou passando a apontar outra depois da importação: nada é importado nem trocado; vira conflito de fonte, com o motivo em "Todas as atividades" e em "Estado da sincronização", até uma pessoa registrar a decisão.
   - **Troca de fonte.** Quando o `INDEX` passa a apontar outra planilha, Bruno escolhe entre **Manter a fonte atual** e **Aceitar a nova fonte** (com motivo escrito). Aceitar **não muda nenhuma atividade**: a nova planilha passa a ser a fonte vigente e cada diferença entre ela e o app vira sugestão para revisão — linha só na planilha → criação (com o ID dela, se livre); atividade só no app → aviso, nunca apagada; célula vazia → ignorada (a troca não apaga valores); campo que já tem decisão humana no app → sugestão com alerta "definido no app por X". As sugestões pendentes da planilha anterior ficam "substituídas", e a planilha anterior passa a aparecer como histórico. Depois disso, edições da nova planilha seguem a regra do item 4.
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

**Como funciona.** Enquanto o app está aberto, ele lê a pasta inteira do Drive (com subpastas) **ao iniciar e depois a cada 5 minutos** (`SYNC_INTERVAL_SECONDS`). O botão **Sincronizar agora**, em "Estado da sincronização", faz a mesma leitura na hora; as duas usam a mesma trava, então nunca rodam ao mesmo tempo. Um arquivo novo ou editado aparece em até ~5 minutos sem nenhum envio pela aplicação (o enunciado pede até 15).

O app só **lê**: nunca cria, move, renomeia nem apaga arquivos no Drive.

| Situação no Drive | O que o app faz |
|---|---|
| Arquivo novo | Baixa (ou exporta, se for Google Docs), extrai o texto e guarda a versão |
| Arquivo editado | Nova versão da **mesma** fonte (o ID do Drive é a identidade); o conteúdo só é reprocessado se o texto mudou (hash SHA-256) |
| Renomeado ou movido dentro da pasta | Atualiza nome e caminho; não reprocessa nem duplica |
| Removido, na lixeira, movido para fora da pasta ou sem acesso | Fonte marcada **indisponível**, com o motivo. O último conteúdo lido fica guardado; atividades ligadas a ela continuam e aparecem como **possivelmente desatualizadas** |
| Falha ao ler um arquivo (erro do Drive, arquivo corrompido, > 10 MB) | Só esse arquivo fica **com falha**, com o motivo; os outros seguem. A versão anterior continua valendo |
| Falha geral (sem internet, autorização expirada, pasta inacessível) | Nada é marcado como removido — falha de leitura nunca vira "não há atividades". Todas as telas avisam que os dados são o último estado confirmado; criar e editar atividades continua funcionando |
| Formato não suportado (`.docx`, PDF, imagem, vídeo) | **Ignorado**, com o motivo; nenhum conteúdo é inventado |

**Falhas e novas tentativas.** Depois de uma falha, a próxima tentativa automática vem mais cedo (30 s, 1, 2 e 4 min) e volta aos 5 minutos quando dá certo. Se nenhuma leitura der certo por mais de dois intervalos, todas as telas mostram "Dados possivelmente desatualizados".

**Conflitos de fonte.** Quando os arquivos não deixam claro qual é a verdade — planilha não apontada pelo `INDEX` com nome parecido ou com cabeçalho de registro de atividades (como `Ata - copia vazia.xlsx`), dois `INDEX`, duas planilhas com o nome apontado, ou o `INDEX` passando a apontar outra planilha —, o app registra um conflito. O conflito **nunca altera atividades**: fica visível em "Estado da sincronização" (e com aviso em "Todas as atividades") até uma pessoa que revisa todas as frentes (Bruno, nos dados de teste) registrar a decisão por escrito. No caso de o `INDEX` apontar outra planilha, a decisão pode ser **aceitar a nova fonte** (ver seção 2, item 6). Se a situação desaparece sozinha (o arquivo sai da pasta), o conflito fica como "superado". Uma versão nova do mesmo arquivo abre um conflito novo, porque a decisão anterior valia para outro conteúdo.

**Por que ler a pasta inteira, e não a API de mudanças do Drive.** A pasta é pequena, a leitura completa é barata (arquivos sem mudança não são baixados de novo) e deixa óbvio o que saiu da pasta: é o que não apareceu na leitura. A `changes.list` seria uma otimização para acervos grandes.

## 6. Formatos suportados

| Formato | Como é lido |
|---|---|
| Markdown (`.md`) e texto (`.txt`) | Texto inteiro; título (`#`) e cabeçalho `chave: valor` (ex.: `status: deprecated`, `data_da_reuniao: 2026-10-03`) |
| Google Docs nativo | Exportado pelo Drive como texto (limite de 10 MB da exportação) |
| Planilha `.xlsx` e Google Planilhas | Todas as abas e células (Google Planilhas é exportado como `.xlsx`); datas do Excel viram datas |
| `.docx`, PDF, imagem, vídeo, áudio, `.pptx`, `.csv`, `.xls` | **Ignorados, com o motivo** na tela de sincronização ("formato ainda não processado"); nenhum conteúdo é inventado. Um `.docx` convertido para Google Docs no Drive passa a ser lido |

O tipo é decidido pela extensão do nome e pelo tipo nativo do Google (o Drive costuma marcar `.md` como texto genérico). Arquivos acima de 10 MB ficam como falha, com o motivo.

**Quais documentos viram sugestões:** só as **atas** — documento de texto com `data_da_reuniao` no cabeçalho ou com a palavra "ata" ou "reunião" no nome ou no título. Documentos de orientação (`INDEX`, `ESTADO-ATUAL`, `GUIA_INICIAL`), o plano antigo (`status: deprecated`) e textos sem autoridade são lidos, mas não geram sugestões. Da planilha, só a apontada pelo `INDEX` gera sugestões (por comparação, sem IA).

## 7. IA no produto e custo estimado por uso

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
4. **Revisão.** Bruno revisa sugestões de todas as frentes; Carla, só da Formação; Ana e Davi veem, só para leitura, as que afetam suas atividades. A frente de uma atualização é a da atividade; a de uma criação é a do responsável proposto (marcada como inferida). Aceitar grava um evento no histórico com autor, hora, antes/depois, a ata como fonte e o número da sugestão; clicar de novo ou recarregar não repete nada. Quem é responsável pela atividade pode revisar, com aviso de auto-revisão registrado.
5. **Idempotência e edição.** Cada versão de documento é analisada uma única vez (arquivo + hash do conteúdo). Se a ata é editada no Drive, as sugestões pendentes da versão antiga ficam "substituídas" e a versão nova é analisada.
6. **Falhas.** Sem resposta do modelo, cota esgotada ou resposta fora do formato: a análise fica "falhou", com o motivo, na tela de sugestões e no Estado da sincronização; os dados oficiais não mudam e criar/editar atividades continua funcionando. O app tenta de novo nas próximas sincronizações (até 3 vezes por versão) e há o botão **Tentar de novo**.

**Provedor.** Gemini API, modelo `gemini-3.6-flash` (configurável em `GEMINI_MODEL`), pelo SDK oficial `google-genai` com saída estruturada (`response_json_schema`). Sem `GEMINI_API_KEY`, o app usa **regras simples sem IA** (ID `ACT-*` + data escrita + "Próximo passo:"), que cobrem os casos do pacote de teste mas não textos livres.

**Custo medido (04/10/2026, atas do pacote de teste, `gemini-3.6-flash`):** por ata, cerca de **1 mil tokens de entrada** e **2 a 2,6 mil de saída** (a maior parte é o raciocínio do modelo), em 10 a 20 segundos.

| Cenário | Custo |
|---|---|
| Camada gratuita do Gemini (usada no protótipo) | **US$ 0**. Os limites não são publicados como números fixos (ver Google AI Studio); para `gemini-3.8-flash` a API informou em 04/10 **5 pedidos por minuto e 20 por dia** por projeto e por modelo. Uma demonstração completa usa de 3 a 6 pedidos |
| Camada paga (US$ 0,75 por milhão de tokens de entrada e US$ 3,75 por milhão de saída até 31/12/2026; o dobro a partir de 2027 — tabela oficial consultada em 04/10) | cerca de **US$ 0,01 por ata**; 100 atas por mês ≈ US$ 1 (≈ US$ 2 em 2027) |
| Reprocessar, recarregar, sincronizar de novo | **US$ 0**: o resultado fica guardado por versão do documento |
| Planilha editada | **US$ 0**: comparação célula a célula, sem IA |

Na camada gratuita, o Google pode usar o conteúdo enviado para melhorar seus produtos: aceitável com os dados fictícios do case, **não** com documentos reais (ver seção 9).

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

Por cima da lista, o botão **Resumir com IA** pede ao Gemini um parágrafo de 2 a 4 frases escrito **só a partir dos itens da lista** (nenhum texto de documento além do que já está na tela). O app confere o parágrafo antes de mostrar e o **descarta inteiro** se ele citar uma data, um `ACT-*` ou uma pessoa que não estão nos itens, ou se escrever um valor que só existe numa proposta pendente sem dizer que é proposta (ex.: "o prazo passou para 07/10" antes do aceite). O parágrafo fica guardado por pessoa e conjunto de itens: pedir de novo com os mesmos itens não chama a IA; quando os itens mudam, o parágrafo antigo some. Medido em 04/10 (`gemini-3.6-flash`, raciocínio "baixo"): ~650 tokens de entrada, ~100 de saída, 1,5 a 4 s → cerca de **US$ 0,001 por resumo** na camada paga.

## 8. Limitações conhecidas

*Em construção.*

- A sincronização só roda com o app aberto; não há notificação do Drive (webhook).
- "Aceitar a nova fonte" só existe quando o `INDEX` passa a apontar outra planilha. Para uma planilha com nome parecido (sem autoridade) ou uma fonte ambígua, a decisão é só registrada: aceitá-las contrariaria o `INDEX` ou exigiria escolher entre duas planilhas, um fluxo que não foi feito.
- A camada gratuita do Gemini tem cota diária pequena (20 pedidos por dia e por modelo, no limite informado para o `gemini-3.8-flash`). Esgotada a cota, as atas ficam com análise pendente (visível) até a cota voltar ou até trocar o modelo em `GEMINI_MODEL`.
- A IA lê só atas. Ela pode errar quem é responsável quando a ata cita várias pessoas (ex.: quem aprova × quem executa); a validação garante só que o nome está escrito no trecho, e a decisão final é do revisor.
- Sem chave de IA, as regras simples só reconhecem frases no formato do pacote de teste (ID `ACT-*`, data `AAAA-MM-DD`, "Próximo passo:").
- A evidência é conferida como texto (ignorando marcação Markdown e espaços); um trecho parafraseado pelo modelo é descartado, mesmo que o sentido esteja certo.
- **Comece aqui** reconhece os documentos de orientação pelo nome: o `INDEX`, o de estado atual ("estado" no nome) e o guia ("guia" no nome ou título "Comece aqui"). Propósito = primeiro parágrafo do estado atual; frentes = frases que começam pelo nome da frente e itens "Frente: …" do guia. Documentos com outra estrutura aparecem na lista de referência, mas o propósito ou as frentes ficam "a confirmar" — o app não escreve esses textos por conta própria.
- A conferência do parágrafo da IA no resumo pessoal pega datas, IDs e nomes fora dos itens e propostas ditas como fato quando há data; uma frase que exagere sem citar data (ex.: "tudo foi aprovado") não é detectada. Por isso a lista com os links continua sendo a referência, logo abaixo do parágrafo.
- "Marcar como visto" vale por pessoa de demonstração (não por navegador), porque não há login de verdade. Horários são gravados ao segundo: algo que acontece no mesmo segundo da marcação fica fora do "desde a última visita".
- A linha do tempo de "Novidades dos documentos" registra renomeação, saída da pasta, volta e falha de leitura a partir da Fase 5; em bancos anteriores, a saída de um arquivo é reconstruída do histórico de sincronizações (e marcada como reconstruída).

## 9. Antes de usar dados reais

*Em construção.*

- **IA:** usar a camada paga do Gemini (ou outro provedor com contrato que não use os dados para treino) e revisar o que é enviado: hoje vai o texto inteiro da ata e a lista de atividades.
- **Visibilidade por pessoa:** no protótipo, todas as pessoas veem todas as fontes lidas (uma conta do Google lê a pasta). Com dados reais, "Comece aqui", "Novidades" e o resumo pessoal (inclusive o parágrafo da IA) precisam mostrar só trechos de arquivos que a pessoa pode abrir no Drive — por exemplo, conferindo as permissões do arquivo para a conta da pessoa antes de exibir ou enviar o trecho à IA.

## 10. Ferramentas de IA usadas no desenvolvimento

Claude Code (plano Claude Pro), para análise do material, planejamento e programação em par. Detalhes em [`docs/DIARIO_DE_BORDO.md`](docs/DIARIO_DE_BORDO.md).

## 11. Documentação complementar

- [`docs/DIARIO_DE_BORDO.md`](docs/DIARIO_DE_BORDO.md): decisões, dificuldades e verificações.
- [`docs/VALIDACAO.md`](docs/VALIDACAO.md): casos testados.
