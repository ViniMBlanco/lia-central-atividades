# Diário de bordo

Registro de como o trabalho foi feito: decisões, mudanças de direção, dificuldades, verificações e resultados. Não é um relatório formal.

**Ferramenta de IA usada para construir:** Claude Code (plano Claude Pro), para leitura e análise do material, planejamento e programação em par. As conversas completas não estão aqui, só o que foi relevante.

---

## 28/09/2026 — Leitura do material e árvore de questões

- Li o material na ordem indicada (00 → 05) com o Claude Code.
- Para entender o problema antes de pensar em tela, montei uma **issue tree** (árvore de questões MECE) com cinco ramos:
  1. verdade e autoridade (qual valor é oficial);
  2. entrada pelo Drive;
  3. interpretação com IA;
  4. uso e interface;
  5. prova e entrega.
- Conclusão principal: o problema não é "fazer um painel", e sim **proveniência e autoridade**. Existem várias fontes com pesos diferentes, e nenhuma pode mudar o dado oficial em silêncio.
- Percebi que os dados de teste formam um roteiro de armadilhas:
  - planilha vazia com nome parecido;
  - datas como número serial do Excel;
  - uma tarefa com dois responsáveis;
  - aprovador que não é responsável;
  - ata antiga que repete a planilha;
  - ideia com "talvez" que não é decisão.

## 29/09/2026 — Verificação completa do material

- Comparei todas as versões dos documentos frase a frase. O PDF do enunciado de 24/09 é o vigente: tem as seções **"Diário de bordo"**, **"Execução e repositório"** e **"Como conduzir o desafio"**, que faltam na versão de 23/09 do pacote.
- Testei a leitura das duas planilhas com `openpyxl`, antes de escolher a biblioteca:
  - funciona com o formato gerado pelo OpenXML SDK;
  - as datas vêm como `datetime` ao meio-dia;
  - a planilha vazia devolve uma linha só com `None`.
- Descobri que o `.docx` da ata de 03/10 tem cabeçalho e rodapé. O texto exportado do Google Doc pode trazer ou não esse conteúdo, então a validação da evidência compara com o texto realmente extraído.

## 29/09/2026 — Saídas do modelo que corrigi após verificar

1. **"Operações não tem revisor."** O assistente afirmou isso. Pedi o trecho e o arquivo, e na conferência nenhum texto diz isso: o `LEIA_ME_PRIMEIRO.md` dá ao Bruno permissão de revisar sugestões sem limitar a frente. A regra foi corrigida para: Bruno revisa qualquer frente; Carla, só a Formação.
2. **Ata de 04/10 como possível atualização do ACT-103.** Pedi o raciocínio completo. Os argumentos mostram que é uma tarefa nova:
   - a ata não cita ID, e as outras citam;
   - a seção se chama "Nova decisão";
   - a entrega é outra (exercício prático, não briefing);
   - o bloqueio da sala não é mencionado.

   Decisão: sugerir **criação**, com uma dica de relação com o ACT-103 para o revisor.
3. **Prazo.** O assistente estimou o prazo como 30/09 ou 01/10 a partir das datas dos arquivos. O prazo real, comunicado pela equipe, é 04/10.

Lição: toda afirmação sobre o material precisa vir com arquivo e trecho. Passei a exigir isso.

## 29/09/2026 — Decisões da Fase 0

- **Stack:** Python + FastAPI + Jinja2/HTMX + SQLite.
  - Um processo só e sem etapa de build.
  - HTML semântico facilita teclado e acessibilidade.
  - O SQLite deixa a banca rodar sem criar conta em nenhum serviço.
- **Repositório:** `lia-central-atividades`. Criado **privado** em 30/09 e será tornado **público na entrega**, para ter backup desde o início sem expor o trabalho em andamento. Commits com o e-mail noreply do GitHub, para não expor e-mail pessoal.
- **Conta Google do teste:** uma conta Gmail pessoal, a mesma no Google Cloud e no Drive. A conta institucional pode ser bloqueada por política da organização (erro `403 domainPolicy`, citado no guia do Drive).
- **IA dentro do produto:** Gemini (camada gratuita) como provedor principal e Claude como opção configurável. Sem chave, o app funciona em modo determinístico.
  - Motivo: a banca vai rodar no próprio ambiente e consegue uma chave Gemini grátis.
  - Ressalva registrada: na camada gratuita o Google pode usar o conteúdo para melhorar produtos. Com dados fictícios isso é aceitável; com dados reais, seria obrigatório usar a camada paga.
- **Porta e callback do OAuth:** `http://localhost:8000/auth/callback`. A porta 8080 já estava ocupada na minha máquina.
- **Demo:** preparada para três cenários, porque o material não diz como a banca vai inserir arquivos:
  - eu subo o arquivo que a banca me entregar;
  - compartilho a pasta com a banca;
  - a banca roda no ambiente dela.

  Por isso: README reproduzível, pasta pronta para compartilhar e botão de sincronização manual.

## 30/09/2026 — Dificuldade: erro de faturamento no Google Cloud

- Ao entrar no Google Cloud, tentei ativar o faturamento (período de teste) e recebi **"Não foi possível concluir a configuração de faturamento [OR_BACR2_59]"**, além de um e-mail do Google dizendo que a tentativa de cadastro foi negada.
- Verificação: o faturamento **não é necessário** para este projeto.
  - O pré-requisito do quickstart da Drive API é só "um projeto no Google Cloud".
  - A página de limites da Drive API diz: "All standard use of the Google Drive API is available at no additional cost".
  - Criar um projeto não exige conta de faturamento.
- Decisão: criar o projeto **sem faturamento**, ignorando a oferta de teste gratuito, e não tentar o faturamento de novo.

## 03/10/2026 — Fase 0 concluída

- Configurei o Google Cloud (projeto sem faturamento, Drive API, tela de consentimento External/Testing com meu e-mail como usuário de teste, escopo só `drive.readonly`, cliente Web com callback `http://localhost:8000/auth/callback`), a pasta de teste no Drive e a chave do Gemini no mesmo projeto.
- Credenciais ficam só no `.env` local, ignorado pelo git. A conferência foi só de presença e tamanho das variáveis, sem ler os valores.
- Ao criar o cliente OAuth, deixei desmarcada a opção "usado por um agente de IA": o app faz um OAuth comum e a IA só lê texto.
- Próximo passo: Fase 1 (estrutura do app, `schema.sql`, OAuth, varredura do Drive, tela de estado da sincronização).

## 03/10/2026 — Fase 1: leitura do Drive e tela de sincronização

- **Construído:** estrutura do app (`python -m app`), `schema.sql` com todas as tabelas do plano, login com o Google, varredura da pasta, leitores de `.md`, `.xlsx` e Google Docs, e a tela "Estado da sincronização".
- **Decisões:**
  - **Varredura completa e recursiva** a cada execução, em vez da Changes API. A pasta é pequena, e "sumiu da varredura" já cobre remoção, lixeira e arquivo movido. Para dizer qual dos três aconteceu, o app consulta o arquivo individualmente.
  - **Mudança detectada pelo hash do conteúdo extraído.** O `version` do Drive muda até quando o arquivo só é renomeado. Por isso o app só baixa de novo quando `version`/`modifiedTime` mudam, e só registra versão nova quando o hash muda. Resultado: renomear não gera reprocessamento, e editar gera uma versão nova da **mesma** fonte.
  - **Falha de listagem aborta a execução antes de mexer no estado dos arquivos.** Se uma pasta não puder ser listada, nada é marcado como removido (invariante "falha ≠ não há atividades").
  - O tipo do arquivo é decidido pela **extensão**: o Drive marcou meus `.md` como `text/markdown`, mas isso varia conforme a forma de envio.
  - Google Planilhas nativo é exportado como `.xlsx` e lido pelo mesmo leitor (proteção caso alguém suba a planilha com conversão ligada). `.docx`, PDF, imagem e vídeo aparecem como "Ignorado", com o motivo.
  - **OAuth:** confere o `state`, usa PKCE e acesso offline (o sync roda sem a pessoa presente). O token fica em `data/google_token.json`, com permissão 600 e fora do git.
  - **Sincronização automática** a cada 5 min já entrou nesta fase (estava prevista para a Fase 3). Ela usa a mesma trava do botão "Sincronizar agora", então duas execuções nunca se sobrepõem.
- **Erros e correções:**
  - Primeiro login: **`Erro 403: access_denied`** ("só pode ser acessado por testadores aprovados"). Minha conta não estava em *Test users* no Google Auth Platform. Adicionei e funcionou.
  - Revisando o código gerado, o assistente percebeu que as credenciais eram recarregadas **sem a data de expiração**. Assim a biblioteca consideraria o token sempre válido e o sync passaria a falhar depois de 1 hora. Corrigido antes do primeiro teste real.
  - O log de acesso do servidor gravaria a URL do callback com o código de autorização do Google, e o guia do Drive pede para não registrar isso. Adicionei um filtro que troca a query do `/auth/callback` por `[omitido]`, e conferi no log.
- **Testes:** 42 testes automatizados com um Drive falso em memória e os arquivos do pacote. No Drive real: 6 arquivos processados com link, 0 falhas. A sincronização automática seguinte não baixou nada nem duplicou versões. Registro no caso 0 de `docs/VALIDACAO.md`.

## 03/10/2026 — Decisões: fonte oficial e revisores

- **Fonte oficial das atividades.** A planilha apontada pelo `INDEX.md` cria as ACT-\* **uma única vez**. A partir daí, o banco do app é a verdade.
  - Se essa planilha for editada depois, cada diferença vira **sugestão** para revisão humana: linha nova vira sugestão de criação; linha removida não apaga nada, só gera aviso.
  - Uma planilha que o INDEX não aponta nunca importa nem apaga dados.
  - Alternativas que considerei:
    - deixar a planilha como fonte oficial: exigiria escrever no Drive, que está fora do escopo;
    - espelhar e sobrescrever o banco: um documento mudaria o dado oficial sem revisão;
    - importar e ignorar edições posteriores;
    - aplicar sozinho as mudanças de campos que ninguém decidiu no app. Esta é a mais defensável, porque segue a precedência do INDEX.

    Fiquei com a regra única ("nada muda sem um humano aprovar") porque o INDEX chama a planilha de "fonte inicial e provisória" e o GUIA diz que o aplicativo exibe as alterações aprovadas "depois da importação da planilha".
- **Revisores.**
  - Bruno revisa sugestões de qualquer frente: o LEIA_ME diz que ele "pode revisar sugestões", sem limite.
  - Carla revisa só a Formação: o GUIA diz que ela "revisa propostas de atividades da sua frente".
  - Quando a sugestão é sobre uma tarefa da própria Carla, a revisão é permitida, com aviso e registro no histórico.

  Alternativas que considerei: deixar os dois revisarem tudo (repetiria a regra depreciada do plano antigo), deixar cada líder só na sua frente (Operações ficaria sem revisor) e proibir a auto-revisão. Esta última é plausível, mas o material não exige.

## 03/10/2026 — Fase 2: importação, atividades e histórico

- **Construído:**
  - classificação de cada arquivo da pasta a partir do `INDEX` (fonte das atividades, orientação, ata, histórico substituído, sem autoridade), com o motivo visível em "Estado da sincronização";
  - importação única da planilha apontada pelo INDEX, executada depois de cada sincronização concluída;
  - os quatro membros de demonstração do `LEIA_ME` e a troca de usuário no topo de todas as páginas;
  - telas "Minhas atividades" (ordenável por prazo, bloqueios e sem prazo), "Todas as atividades" (filtros por responsável, frente, estado e prazo), detalhe com fonte, evidência e histórico, criação, edição e mudança de estado.
- **Decisões:**
  - **Como achar a fonte no INDEX:** o app procura a linha que cita uma planilha `.xlsx`; se houver mais de uma, vale a que fala de "fonte" ou "atividades". Se ainda sobrar ambiguidade (duas planilhas citadas, dois INDEX, dois arquivos com o nome apontado), nada é importado e o motivo aparece na tela. Preferi parar e avisar a escolher sozinho.
  - **Ordem das regras de autoridade:** `status: deprecated` vem antes de tudo; a ata vem antes de "citado no INDEX". Sem essa ordem, a `Ata_2026-10-01.md`, que o INDEX cita, viraria documento de orientação.
  - **Proveniência na importação:** cada atividade guarda a linha da planilha (aba, número da linha, valores) e o trecho da ata citada na coluna Origem que menciona o ID. Assim o detalhe do `ACT-101` mostra a frase "Ana seguirá com o carrossel sobre ferramentas…" com link para a ata.
  - **IDs das atividades criadas no app:** seguem o padrão `ACT-*`, continuando a numeração (ver a correção abaixo).
  - **Dado ausente fica ausente:** responsável que não é membro, prazo que não é data e estado desconhecido não são completados; o campo fica "a confirmar"/"a definir" e o aviso vai para o evento de importação.
  - **Edição concorrente:** o formulário de edição leva a hora da última atualização; se outra pessoa salvou antes, o app avisa em vez de sobrescrever em silêncio.
  - **Sem HTMX por enquanto:** formulários HTML simples já resolvem as telas desta fase, funcionam sem JavaScript e são mais previsíveis para teclado e leitor de tela.
- **Pendente para a Fase 4:** quando a planilha importada é editada no Drive, o app já detecta e avisa ("nada foi aplicado automaticamente"), mas ainda não transforma cada diferença em sugestão revisável.
- **Erros e correções:**
  - Nas capturas de tela, o botão "Trocar" aparecia sem fundo: a regra do botão claro vinha antes da regra geral de botão no CSS e era sobrescrita. Corrigido mudando a ordem.
  - A mensagem "Alterações salvas (…)" listava os campos na ordem do formulário, e não na ordem usada no resto da tela. Padronizado.
- **Testes:** 88 testes automatizados (46 novos). Incluem o gabarito da carga inicial (Ana: ACT-101 e ACT-104; Davi: ACT-102 e ACT-104; Carla: ACT-103; Bruno: nenhuma), a planilha vazia homônima, a planilha não apontada com dados, a planilha editada depois da importação, a falha de leitura da planilha, o INDEX trocando de fonte, dados ausentes e a persistência depois de reiniciar o app.
  - No Drive real: 6 arquivos lidos, 4 atividades importadas com o mesmo gabarito.
  - No navegador (Firefox sem interface, via Selenium), em largura de computador e de celular: sem rolagem lateral em nenhuma tela; tentativa de criar sem escolher usuário é recusada com aviso; criar, editar e reiniciar o servidor mantêm a atividade e o histórico (antes/depois, autor e motivo).

## 03/10/2026 — Correção: ID das atividades criadas no app

- **Saída do modelo:** o assistente implementou as atividades criadas pela interface com IDs `LIA-001`, `LIA-002`…, para que nunca colidissem com um `ACT-*` acrescentado depois na planilha. Apresentou isso como decisão já tomada, sem me consultar.
- **Verificação:** pedi que ele buscasse no material de onde vinha `LIA-`. Não vem de lugar nenhum:
  - `ACT-*` é o padrão de ID de atividade em todo o material: o `INDEX.md` fala em "atividades identificadas por ACT-*", o enunciado em "registros ACT-*" e a especificação usa `"target_activity_id": "ACT-101 | null"` no contrato da IA;
  - para a criação pela interface, a especificação (§5 B) só pede "atividade persistida com ID, autoria, horário e indicação de criação manual", sem definir formato;
  - "LIA" só aparece como sigla da organização e no nome da pasta de teste.
- **Decisão:** atividades criadas no app continuam a numeração `ACT-*` (depois de `ACT-104` vem `ACT-105`). A origem manual já aparece na atividade e no histórico. O risco de colisão é tratado sem trocar o padrão: se a planilha trouxer um ID que já existe no app, a linha não sobrescreve a atividade e vira aviso. Há teste automatizado para esse caso.
- **Lição:** escolha sem base no material deve ser apresentada como proposta, com a justificativa, antes de virar código.

## 03/10/2026 — Fase 3: conflitos de fonte e falhas da sincronização

- **Construído:**
  - **conflitos de fonte** registrados no banco: planilha parecida com a fonte das atividades e não apontada pelo `INDEX` (vazia ou com dados), fonte ambígua e `INDEX` passando a apontar outra planilha. Aparecem em "Estado da sincronização" e com aviso em "Todas as atividades" e "Minhas atividades";
  - **decisão humana** do conflito: só quem revisa todas as frentes (Bruno) registra, por escrito, com nome e hora. A decisão não altera atividades nem arquivos;
  - atividades cuja fonte ficou indisponível ou falhou na última leitura aparecem como **possivelmente desatualizadas** (na lista e no detalhe), mantendo o último estado confirmado;
  - aviso em **todas as telas** quando a última leitura do Drive falhou ou está atrasada, lembrando que criar e editar continuam funcionando;
  - leitura **ao iniciar o app** e **nova tentativa mais cedo** depois de falha (30 s, 1, 2, 4 min; depois volta aos 5 min). A tela mostra a hora prevista da próxima verificação.
- **Decisões:**
  - **Qual planilha vira conflito:** a que não é apontada pelo INDEX mas pode ser confundida com a fonte — **nome parecido** (alguma palavra em comum com a planilha apontada, ignorando extensão, números e marcas como "cópia" ou "v2") **ou** cabeçalho de registro de atividades (ID e Atividade). Uma planilha sem nenhuma das duas coisas (ex.: orçamento) fica só como "sem autoridade". Ver a correção abaixo: a primeira versão usava só o cabeçalho.
  - **Ciclo do conflito:** aberto → decidido (por uma pessoa) ou superado (a situação sumiu sozinha, por exemplo o arquivo saiu da pasta). Uma falha de leitura **não** encerra conflito. Uma versão nova do mesmo arquivo abre um conflito novo, porque a decisão anterior valia para outro conteúdo; a mesma situação nunca é registrada duas vezes.
  - **O que a decisão faz:** só registra. O app não troca a fonte das atividades depois da importação; isso ficou como limitação documentada. Quando a ambiguidade ou a troca de fonte já foi decidida, a situação da fonte deixa de pedir atenção e mostra a decisão.
- **Erros e correções:**
  - Um teste mostrou que o conflito da planilha vazia não era encerrado quando ela ia para a lixeira. Causa: com a lista de conflitos atuais vazia, a consulta virava `NOT IN (NULL)`, que em SQL nunca é verdadeiro. Corrigido e coberto por teste.
- **Testes:** 111 testes automatizados (23 novos): conflito da planilha vazia, cópia com nome parecido sem cabeçalho, sem apagar nada, sem duplicar em novas leituras, superado na lixeira e reaberto ao voltar, falha de leitura que não encerra conflito, permissão (Ana, Carla e Davi não decidem), decisão que não altera atividades, versão nova abrindo conflito novo, troca de fonte decidida, ambiguidade, fonte removida marcando atividades como possivelmente desatualizadas e aviso de falha em todas as telas.
  - No Drive real: a leitura com o banco já existente atualizou a estrutura sem perder dados (6 arquivos, 4 atividades, nenhum conflito). Os testes de renomear, remover, tirar acesso e subir a planilha vazia no Drive real estão no registro de validação.

## 03/10/2026 — Correção: quando uma planilha vira conflito

- **Saída do modelo:** na primeira versão da Fase 3, o assistente fez virar conflito só a planilha com cabeçalho de registro de atividades (colunas ID e Atividade), sem olhar o nome. O argumento era que "nome parecido" é vago e que o cabeçalho é objetivo.
- **Verificação:** pedi que ele mostrasse de onde vinha a escolha. Relendo o material, o critério do case é o **nome**: o R10 do enunciado fala em "planilha vazia com **nome parecido**"; a especificação (§3) em "planilha posterior e vazia com **nome semelhante**" e "arquivos **homônimos** sem indicação de autoridade"; o `LEIA_CONFLITO.md` em arquivo que "tem **nome parecido** com o registro de atividades". A `Ata - copia vazia.xlsx` só passava no teste porque, por acaso, tem o mesmo cabeçalho. Uma cópia totalmente vazia, sem cabeçalho (como `Ata_registro_v2.xlsx`), não geraria conflito visível — exatamente o tipo de "caso novo da mesma natureza" que o `LEIA_ME` avisa que a banca pode trazer.
- **Decisão:** vira conflito a planilha não apontada com **nome parecido ou** cabeçalho de registro. O nome cobre o que o material descreve; o cabeçalho cobre listas paralelas com outro nome (ex.: `Tarefas.xlsx` com linhas `ACT-*`). Alternativas consideradas: toda planilha não apontada (geraria alarme para qualquer orçamento) e só o nome (não pegaria listas paralelas).
- **O que a decisão do conflito faz:** por enquanto, só registra a decisão (texto, autor e hora) e encerra o conflito; nenhuma atividade muda. Na Fase 4, quando existirem as sugestões por campo, a ideia é acrescentar "aceitar a nova fonte", em que as diferenças viram sugestões para revisão — fluxo a detalhar antes de implementar.
- **Teste:** cópia vazia sem cabeçalho e planilha de outro conteúdo com nome parecido agora geram conflito; orçamento sem relação continua sem conflito.

## 04/10/2026 — Decisões antes da Fase 4

- **Fluxo das sugestões:** pedi ao assistente que explicasse o fluxo antes de implementar. São três entradas que geram sugestões — ata nova ou editada (IA), planilha importada editada no Drive (comparação célula a célula) e conflito de troca de fonte — e todas caem na mesma tela de revisão, com aceitar, ajustar ou rejeitar com motivo.
- **Planilha editada:** a comparação é entre a versão nova e a versão anterior **da planilha**, e não contra o banco. Assim, uma edição feita no app (ex.: prazo aprovado pelo Bruno) não gera sugestão para "voltar" ao valor antigo da planilha.
- **"Aceitar a nova fonte":** só no conflito em que o INDEX passa a apontar outra planilha. Numa planilha com nome parecido, aceitar contrariaria o INDEX; na fonte ambígua, seria outro fluxo ("escolher qual das duas").
- **Planilha nova contradizendo uma decisão humana:** o assistente recomendou não gerar sugestão, com base na precedência do `INDEX.md` ("decisão humana aprovada na aplicação" vem primeiro). Preferi gerar a sugestão **com um alerta** ("contraria a decisão de X em DD/MM") e deixar o revisor decidir: fica mais perto do R10 ("o conflito fica visível e requer decisão humana") e não esconde informação.
- **Atas da carga inicial:** também passam pela IA, para a regra ser a mesma para qualquer ata. A validação remove campos que já têm o valor proposto; a ata de 01/10, que só repete a planilha, deve gerar zero sugestões.
- **Modelo:** `gemini-3.8-flash`, o modelo estável mais recente na documentação oficial do Gemini em 04/10, com camada gratuita. Na camada gratuita o Google pode usar o conteúdo para melhorar seus produtos: aceitável com dados fictícios, mas dados reais exigiriam a camada paga (README, "Antes de usar dados reais").

## 04/10/2026 — Fase 4: sugestões das atas, validação e revisão humana

- **Construído:**
  - **análise das atas** depois de cada sincronização: cada ata com versão ainda não analisada vai para o Gemini (`gemini-3.8-flash`) com a lista de pessoas e os valores oficiais atuais das atividades; a resposta vem em JSON no formato do contrato da especificação (§6). Cada versão (arquivo + hash do conteúdo) é analisada uma única vez;
  - **validação antes de mostrar**: trecho citado precisa estar literalmente no documento; ID precisa existir; prazo precisa estar escrito no trecho (data relativa vira prazo vazio + incerteza); responsável precisa ser membro e estar no trecho; hipótese ("talvez", "ninguém assumiu") é descartada; campo igual ao oficial é removido; itens da mesma atividade viram uma sugestão; proposta igual a outra já pendente não se repete. Os descartes aparecem na tela com o motivo;
  - tela **Sugestões para revisar**, filtrada pela permissão (Bruno: todas as frentes; Carla: Formação; Ana e Davi: só leitura do que os afeta), com contador no menu. O detalhe mostra evidência, onde está no documento, data do documento, valor oficial × proposto e pontos a conferir; dá para **aceitar** (desmarcando ou ajustando campos) ou **rejeitar com motivo**. O aceite grava evento com autor, antes/depois, a ata como fonte e o número da sugestão; recarregar não repete;
  - **ata editada**: sugestões pendentes da versão antiga ficam "substituídas" e a versão nova é analisada;
  - **planilha importada editada**: comparação com a versão anterior da planilha; célula mudada → atualização, linha nova → criação, linha apagada → aviso; alerta quando a planilha contradiz uma decisão humana já registrada no app;
  - **falha da IA** (sem resposta, cota, formato errado): análise "falhou" com o motivo, novas tentativas automáticas (até 3) e botão "Tentar de novo"; sincronização e edição manual seguem funcionando;
  - **sem chave de IA**: regras simples (ID `ACT-*`, data escrita, "Próximo passo:") dão o mesmo resultado nas atas do pacote.
- **Verificação com o modelo real** (dados fictícios): `gemini-3.8-flash` acertou as três atas do pacote — 01/10 → nenhuma ação; 03/10 → atualizar ACT-101 (prazo 07/10 e próximo passo), sem pôr Bruno como responsável; 04/10 → criar tarefa para Carla até 10/10, relacionada ao ACT-103, ignorando o "talvez". As respostas foram gravadas em `tests/fixtures/ia/` e os testes as reutilizam sem rede. Por ata: ~1 mil tokens de entrada, 1 a 1,5 mil de saída, 15 a 25 s.
- **Erros e correções:**
  - A primeira chamada deu HTTP 400 nas três atas. Causa: para limpar o esquema JSON, o código removia a chave `title` em todo lugar — inclusive a propriedade `title` da atividade. Passou a remover só `default`.
  - **Cota:** a camada gratuita do `gemini-3.8-flash` tem 5 pedidos por minuto e **20 por dia** por projeto (mensagem da API). As chamadas com o esquema quebrado e as repetições automáticas gastaram a cota do dia; o teste seguinte com o Drive real ficou com a análise "falhou — cota esgotada", sem sugestão inventada e com a sincronização ok. O app deixou de repetir um erro de cota diária (só repete sobrecarga e cota por minuto com espera curta) e o README passou a declarar o limite.
  - A regra de "atividades relacionadas" escrita pelo assistente (palavra em comum no título) marcou ACT-104 como relacionada à ata de 04/10 só por causa do verbo "revisar". Ficou só "mesmo responsável".
  - O contador do menu sumia na própria tela de sugestões (duas variáveis com o mesmo nome); um teste pegou.

## 04/10/2026 — Saída incorreta do modelo: o plano B errou a ata de 04/10

- **Contexto:** com a cota diária do `gemini-3.8-flash` esgotada, o assistente rodou as três atas no plano B anotado no planejamento, `gemini-3.5-flash-lite` (cota separada, ~1,5 s por ata, mais barato), e conferimos as respostas contra o gabarito.
- **Saída incorreta:** na ata de 04/10, ele propôs **atualizar o ACT-103** (prazo 10/10 e novo próximo passo) em vez de criar uma tarefa nova. É a leitura que eu já tinha descartado em 29/09: a ata não cita ID, a seção é "Nova decisão", a entrega (exercício prático) é diferente do briefing e o bloqueio da sala não é mencionado; aceitar mexeria numa tarefa bloqueada sem base. Na ata de 03/10 ele também citou como evidência só a frase do prazo, deixando o próximo passo sem trecho.
- **Decisão:** manter `gemini-3.8-flash`, que acertou as três atas, e abandonar o flash-lite como plano B. Também entrou uma proteção que vale para qualquer modelo: atualização cujo trecho **não cita o ID** da atividade ganha o alerta "a IA concluiu que se trata da mesma atividade; confira" para o revisor.

## 04/10/2026 — Decisões de implementação da Fase 4

- **Estado também pode ser proposto** ("foi concluída", "está bloqueada"): o contrato da especificação não tem esse campo, mas é uma decisão que uma ata registra. Como os outros, só vale com aceite.
- **ID inexistente** citado pela IA (ex.: `ACT-999`) é descartado com motivo, não convertido em criação: o revisor vê o descarte e pode criar a atividade à mão.
- **O que é ata:** cabeçalho `data_da_reuniao` ou a palavra "ata"/"reunião" no nome ou no título (antes: só nome começando por "Ata"), para cobrir arquivos inesperados como "Reunião de alinhamento".
- **Testes:** 152 automatizados (41 novos): gabarito das três atas com as respostas reais gravadas e com as regras sem IA, idempotência, mesma ata em `.md` e Google Docs, aceite com histórico e fontes, ajuste, rejeição com motivo, criação com auto-revisão, permissões, ata editada, falha da IA com novas tentativas, trecho inexistente, ID desconhecido, hipótese, prazo relativo, pessoa não escrita, instrução dentro do documento, planilha editada (atualização, criação, linha apagada, edição do app preservada, alerta de decisão humana, planilha que volta atrás) e telas.

## 04/10/2026 — Troca de modelo: `gemini-3.6-flash`

- **Problema:** com a cota gratuita diária do `gemini-3.8-flash` esgotada (volta só à noite, perto do prazo), eu precisava de outro modelo para testar com o Drive real. Pedi ao assistente que comparasse as opções em vez de escolher pelo nome.
- **Como comparamos:** as três atas do pacote em cada modelo estável da família Flash, com a resposta passando pela mesma validação do app; as duas atas que exigem interpretação (03/10 e 04/10) rodaram duas vezes nos finalistas. Preços conferidos na tabela oficial do Gemini no mesmo dia.
- **Resultado:** `gemini-3.6-flash` e `gemini-3.5-flash` acertaram 5 de 5; `gemini-3.7-flash` falhou nas três chamadas por sobrecarga (503/504); o `gemini-3.5-flash-lite` já tinha errado a ata de 04/10. O 3.5-flash é um pouco mais rápido (7–13 s × 10–20 s), mas custa 2 a 2,4 vezes mais na camada paga.
- **Decisão:** `gemini-3.6-flash` passa a ser o modelo do produto: mesmo preço do 3.8, gabarito completo duas vezes e nenhuma falha de disponibilidade nos testes. As respostas gravadas para os testes automatizados foram trocadas pelas do 3.6. Custo pago medido: ~US$ 0,01 por ata (mais tokens de raciocínio que o 3.8).

## 04/10/2026 — Conflito de troca de fonte: "aceitar a nova fonte"

- **Construído** (opção b decidida antes da Fase 4): no conflito "o INDEX aponta outra planilha", Bruno escolhe **Manter a fonte atual** ou **Aceitar a nova fonte**, sempre com motivo escrito. Aceitar não muda nenhuma atividade: a nova planilha passa a ser a fonte vigente e cada diferença entre ela e o app vira sugestão (linha só na planilha → criação com o ID dela; atividade só no app → aviso; campo já decidido por uma pessoa no app → sugestão com alerta, como eu tinha escolhido). Decisão e troca são gravadas na mesma transação: ou acontecem as duas, ou nenhuma.
- **Detalhes que surgiram na implementação:** célula vazia na nova planilha é ignorada (a troca nunca apaga valor do app); sugestões pendentes da planilha anterior ficam "substituídas"; a planilha anterior passa a "Histórico (substituído)" e não abre conflito de "nome parecido" (sem isso, a antiga fonte apareceria como planilha suspeita logo depois da troca); edições posteriores da nova planilha são comparadas com a versão aceita na troca.
- **Testes:** 157 automatizados (5 novos): troca aceita gerando 3 sugestões sem mudar atividades, alerta de decisão humana, aviso de atividade que só existe no app, ID da planilha mantido na criação, planilha antiga como histórico, edição da nova planilha depois da troca, "manter" sem troca, troca negada para planilha com nome parecido e a tela (só Bruno vê os botões).

## 04/10/2026 — Ensaio com o banco real antes de reiniciar o app

- Uma cópia do banco real foi aberta com o código novo (porta separada): a estrutura foi atualizada sem perder dados (4 atividades, conflito da cópia vazia preservado) e o `gemini-3.6-flash` analisou a ata de 01/10 → 0 sugestões.
- **O que o ensaio mostrou:** o 3.6 também respondeu 503 (sobrecarga) duas vezes antes de responder; a repetição automática resolveu, e passou de 3 para 4 tentativas. E o "Sincronizar agora" ficou 43 s parado esperando a IA — numa demonstração isso parece travado. Agora o botão responde assim que a leitura do Drive termina, avisa que a análise está em andamento e a IA roda em segundo plano (com a mesma trava da sincronização); a tela de sugestões mostra "Análise em andamento". O ciclo automático continua analisando na própria sincronização.

## 04/10/2026 — Falha encontrada no Drive real: sugestão de ata que foi para a lixeira

- **O que aconteceu:** ao subir a pasta 02, subi por engano o `Ata_2026-10-03.md` junto (o LEIA_ME pede só a versão Google Docs) e o mandei para a lixeira em seguida. O app fez o que devia com o arquivo: leu, analisou (1 sugestão para o ACT-101) e, na sincronização seguinte, marcou "Indisponível — movido para a lixeira", mantendo o último conteúdo.
- **A falha:** a sugestão continuava pendente e **podia ser aceita**, mesmo com a ata na lixeira; e, quando o Google Doc da mesma ata chegasse, a proposta dele seria descartada como "igual à sugestão já pendente". A única proposta ficaria presa a um arquivo apagado — contra a especificação (§4: fonte removida não pode ser apresentada como confirmada).
- **Correção:** sugestão com documento indisponível não pode ser aceita (pode ser rejeitada; se o arquivo voltar, o aceite é liberado) e aparece marcada na lista, no detalhe e na atividade; uma proposta equivalente vinda de outro arquivo **substitui** a que perdeu a fonte. "Equivalente" passou a aceitar o mesmo trecho citado, além dos mesmos valores, porque a IA pode escrever o mesmo próximo passo com outra pontuação.
- **Também observado:** a análise da ata de 04/10 falhou na primeira tentativa (Gemini sobrecarregado) e deu certo sozinha na sincronização automática seguinte, sem ação manual.

## 04/10/2026 — Revisão no Drive real e duas correções

- **Teste:** como Bruno, aceitei a sugestão do ACT-101 (prazo 07/10 e próximo passo); como Carla, aceitei a criação da tarefa da oficina, que virou ACT-105, com o aviso de auto-revisão. O histórico registrou autor, antes/depois, a ata como fonte e o número da sugestão.
- **Correção 1 — data do documento:** a sugestão da ata de 03/10 aparecia como "documento de 04/10". O Google Doc convertido do `.docx` exporta o cabeçalho de página ("LIGA IA UFSCAR / CASE TÉCNICO") antes do título, e o leitor considerava o bloco `chave: valor` terminado ali, perdendo `data_da_reuniao`; a data caía para a de modificação no Drive. O leitor passou a aceitar até duas linhas antes do bloco quando não há `# título`. Como o texto lido fica guardado, o cabeçalho de todas as fontes é recalculado a cada sincronização sem acessar o Drive, e a data das sugestões daquela versão é corrigida. Um teste escrito junto com a correção mostrou que a primeira versão dela (do assistente) aceitava `chave: valor` em qualquer das 12 primeiras linhas, o que transformaria "Nota: …" no corpo em cabeçalho; restringi a posição.
- **Correção 2:** o selo "ponto a conferir" contava "o valor oficial mudou desde a sugestão" também depois do aceite — que é justamente quando o valor muda. Agora só conta em sugestões pendentes.


## 04/10/2026 — Fase 5: Comece aqui, Novidades dos documentos e "o que mudou para mim"

- **Decisões (minhas, a partir de opções que o assistente apresentou):**
  - **Marco do "o que mudou para mim":** botão "Marcar como visto" + escolha de período (desde a última visita marcada, 24 h, 7 dias, desde o início). Descartei gravar a visita automaticamente ao abrir a página: recarregar apagaria o resumo, o que confunde e atrapalha a demonstração.
  - **IA no resumo:** primeiro a lista montada dos registros (já atende o R09 sozinha); por cima, um botão "Resumir com IA" que pede um parágrafo escrito **só a partir dos itens da lista**, conferido antes de aparecer. O enunciado põe "resumo de mudanças" na camada de IA esperada, e a especificação (§5 E) aceita texto de IA desde que os fatos venham dos registros com links.
- **Construído:**
  - **Comece aqui:** cartão pessoal (primeira ação = atividade aberta de prazo mais próximo; sem atividade, as sugestões a revisar; contagens de abertas, prazos, mudanças e propostas), quatro passos, propósito, frentes, regras de trabalho, documentos de referência, fonte das atividades e "O que ainda está a confirmar". Tudo vem dos documentos de orientação lidos do Drive, como **trecho copiado com link**: o app não escreve propósito nem frentes. O que o próprio documento marca como parcial (`status: parcial`, "descrição provisória") aparece com o selo "Provisório: a confirmar".
  - **O que mudou para mim:** confirmado (eventos do histórico com antes → depois, autor e fonte), propostas aguardando revisão (marcadas "proposto", com quem pode revisar), dados incertos ou em conflito, prazos próximos e bloqueios; "Nada mudou nas atividades de X" quando for o caso.
  - **Novidades dos documentos:** linha do tempo por arquivo — apareceu, conteúdo alterado, renomeado, movido, ficou indisponível, voltou, falha de leitura, análise da IA, sugestões aceitas/rejeitadas/substituídas, conflitos e importação. A sincronização passou a registrar esses eventos (tabela `source_events`).
  - **Carregando:** botões demorados (sincronizar, analisar, resumir com IA) mostram que estão trabalhando e não aceitam segundo clique.
- **Verificação com o modelo real (`gemini-3.6-flash`, 4 chamadas, dados fictícios):** Ana depois do aceite do Bruno, Davi, Ana com a proposta ainda pendente e Carla. Os quatro parágrafos passaram na conferência e trataram a proposta como proposta. ~650 tokens de entrada, ~100 de saída, 1,5 a 4 s (raciocínio "baixo").
- **Saída do modelo corrigida:** no primeiro parágrafo da Ana, o modelo escreveu "Fique **atenta**" — deduziu o gênero pelo nome, coisa que o material não informa. Acrescentei ao pedido a regra de linguagem neutra; as respostas seguintes saíram neutras ("você deve atenção…"). Ficou também a conferência automática, que vale para qualquer modelo: o parágrafo é descartado se citar data, `ACT-*` ou pessoa fora dos itens, ou se escrever um valor que só existe numa proposta pendente sem dizer que é proposta.
- **Testes com uma cópia do banco do Drive real** (código novo numa porta separada, sem acesso ao Drive) e capturas de tela em 1280 px e 390 px. Correções que saíram daí:
  - A saída da pasta da `Ata_2026-10-03.md` (que mandei para a lixeira de madrugada) não estava na linha do tempo, porque aconteceu antes do registro de eventos existir. A primeira reconstrução usava a última vez que o arquivo foi visto (02:40) e o evento aparecia **antes** da análise; passou a usar a sincronização que detectou a saída (02:47), marcada como "reconstruída".
  - A mensagem do `.docx` ainda mandava "abrir com Documentos Google", que no teste do caso 2 não converte; passou a "Arquivo → Salvar como Documentos Google".
  - Espaço entre a tabela de frentes e o cartão seguinte; no celular, o nome da frente ocupa a largura do cartão; datas do cabeçalho dos documentos em DD/MM/AAAA.
- **Testes:** 194 automatizados (31 novos): Comece aqui vindo dos documentos e sem o estado atual, primeira ação de cada pessoa, lacunas, resumo de Ana × Davi, proposta pendente que não aparece como confirmada, marco "marcar como visto", incertezas (conflito, ata sem análise, atividade sem responsável), linha do tempo (renomear, lixeira, voltar, editar, falha), reconstrução em banco antigo, conferência do parágrafo da IA (respostas reais aceitas; data, ID e pessoa inventados e proposta dita como fato descartados), cache do parágrafo e falha da IA.

## 04/10/2026 — Fase 6: celular, teclado e estados de tela

- **Como conferi:** capturas de tela com o Firefox sem interface, em 390 px (celular) e 1280 px, de todas as telas, com o usuário de demonstração escolhido. Um script injetado na cópia da página marcava em vermelho qualquer elemento que passasse da largura da tela e escrevia no topo a largura total da página. Rodei com uma cópia do banco do Drive real e com um banco vazio (sem conta conectada), numa porta separada, sem tocar no app da porta 8000. Contraste calculado pela fórmula da WCAG para todas as combinações de cor do CSS.
- **O que estava errado e foi corrigido:**
  - No celular, o selo "2 com prazo em até 7 dias ou bloqueada(s)" do Comece aqui não quebrava linha e fazia a página rolar 7 px para o lado. Os selos passaram a quebrar linha no celular.
  - Com o banco vazio, o Comece aqui dizia "Nenhuma atividade aberta com Davi" antes de qualquer leitura do Drive — falha de leitura parecendo ausência de atividade (invariante 3). Agora diz que as atividades ainda não foram importadas e aponta o Estado da sincronização.
  - Endereço inexistente mostrava o JSON cru do FastAPI; `/sugestoes/abc`, um erro de validação em JSON; um erro interno, texto puro. Agora há páginas do app para 404, 405 e 500, com caminho de volta; a de 500 não mostra detalhe técnico (fica no log) e lembra que os dados salvos não se perdem.
  - Criar atividade, editar, mudar estado, aceitar/rejeitar sugestão e decidir conflito não travavam o segundo clique: um duplo clique em "Criar" poderia criar duas atividades. Todo formulário que grava passou a travar o envio repetido (e destrava ao voltar pelo navegador).
  - Conexão perdida não tinha tratamento: aviso fixo "Sem conexão com o app" quando o navegador perde a rede ou quando a página não alcança o app (verificação a cada 30 s em `/saude`); enquanto o aviso está na tela, nada é enviado.
  - Formulário com erro: o resumo dos erros já existia com links para os campos, mas não recebia o foco; agora recebe, e o leitor de tela o lê primeiro.
  - Menu e filtros ocupavam quase uma tela inteira no celular antes da lista; passaram a duas colunas.
  - No modo de alto contraste do sistema, os selos perdiam o fundo e viravam texto solto: ganharam borda.
- **Conferido e mantido:** contraste de todos os textos ≥ 6,99:1 (o enunciado pede 4,5:1); ciano só como acento ou com texto preto (11,6:1); estado sempre com ícone + texto; link "Pular para o conteúdo"; foco visível em todos os elementos (contorno azul de 3 px; ciano dentro do topo azul); alvos de toque com 44 px nos botões e campos.
- **Não feito:** teste com leitor de tela e auditoria automática (axe/Lighthouse) — registrados como limitação no README.
- **Testes:** 198 automatizados (4 novos: páginas 404/405, erro interno sem detalhe técnico, `/saude` com o aviso de conexão, trava de envio no formulário de criação).
