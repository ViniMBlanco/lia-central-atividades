# Diário de bordo

Registro de como o trabalho foi feito: decisões, mudanças de direção, dificuldades, verificações e resultados. Não é um relatório formal: o funcionamento de cada tela está no README e os casos testados, em [`VALIDACAO.md`](VALIDACAO.md).

**IA usada para construir:** Claude Code (plano Claude Pro), para leitura e análise do material, planejamento e programação em par. **IA dentro do produto:** Gemini API (`gemini-3.6-flash`) para ler as atas e redigir o resumo pessoal, sempre com revisão humana; sem chave, regras simples sem IA. As conversas completas não estão aqui, só o que foi relevante.

## Como ler este diário

As entradas estão em ordem de data. Decisões que mudei depois de verificar que uma saída do modelo estava incorreta (o enunciado pede uma; registrei todas):

| Data | Saída do modelo | Como conferi | O que mudou |
|---|---|---|---|
| 29/09 | Claude Code: "Operações não tem revisor" | Pedi arquivo e trecho; nenhum texto diz isso | Bruno revisa todas as frentes; Carla, só a Formação |
| 29/09 | Claude Code: a ata de 04/10 seria atualização do ACT-103 | Pedi o raciocínio completo e comparei com a ata | Criar tarefa nova, com dica de relação com o ACT-103 |
| 03/10 | Claude Code: atividades criadas no app com ID `LIA-001` | Busca no material: `LIA-` não existe; `ACT-*` é o padrão | IDs `ACT-*` continuando a numeração |
| 03/10 | Claude Code: planilha só vira conflito pelo cabeçalho | Reli o R10, a especificação (§3) e o `LEIA_CONFLITO.md`: o critério é o **nome parecido** | Conflito por nome parecido **ou** cabeçalho |
| 04/10 | Gemini `3.5-flash-lite` (no produto): a ata de 04/10 como "atualizar ACT-103" | Conferência das respostas contra o gabarito das três atas | Abandonei esse modelo; alerta para atualização cujo trecho não cita o ID; comparação de modelos e troca para o `gemini-3.6-flash` |
| 04/10 | Gemini `3.6-flash` (no produto): "Fique **atenta**" para a Ana | Leitura dos parágrafos gerados: o gênero foi deduzido do nome | Regra de linguagem neutra no pedido e conferência automática do parágrafo |

A fonte oficial e os revisores estão em 03/10; os testes, no fim de cada fase; o que ficou de fora, na última seção.

---

## 28 e 29/09/2026 — Leitura e verificação do material

- Li o material na ordem indicada (00 → 05) com o Claude Code e montei uma **issue tree** (árvore de questões MECE) com cinco ramos: verdade e autoridade, entrada pelo Drive, interpretação com IA, uso e interface, prova e entrega.
- Conclusão principal: o problema não é "fazer um painel", e sim **proveniência e autoridade**. Há várias fontes com pesos diferentes, e nenhuma pode mudar o dado oficial em silêncio. Os dados de teste formam um roteiro de armadilhas: planilha vazia com nome parecido, datas como número serial do Excel, tarefa com dois responsáveis, aprovador que não é responsável, ata antiga que repete a planilha e ideia com "talvez" que não é decisão.
- Comparei as versões dos documentos frase a frase: o PDF do enunciado de 24/09 é o vigente, porque tem as seções "Diário de bordo", "Execução e repositório" e "Como conduzir o desafio", que faltam na versão de 23/09 do pacote.
- Testei a leitura das planilhas com `openpyxl` antes de escolher a biblioteca (as datas vêm como `datetime` ao meio-dia; a planilha vazia devolve uma linha só com `None`). Descobri que o `.docx` da ata de 03/10 tem cabeçalho e rodapé; por isso a evidência é comparada com o texto realmente extraído.

## 29/09/2026 — Saídas do modelo corrigidas na leitura

1. **"Operações não tem revisor."** Pedi o trecho e o arquivo: nenhum texto diz isso, e o `LEIA_ME_PRIMEIRO.md` dá ao Bruno permissão de revisar sugestões sem limitar a frente. Regra corrigida: Bruno revisa qualquer frente; Carla, só a Formação.
2. **Ata de 04/10 como atualização do ACT-103.** Pedi o raciocínio completo. A ata não cita ID (as outras citam), a seção se chama "Nova decisão", a entrega é outra (exercício prático, não briefing) e o bloqueio da sala não é mencionado. Decisão: sugerir **criação**, com uma dica de relação com o ACT-103 para o revisor.
3. **Prazo.** O assistente estimou 30/09 ou 01/10 a partir das datas dos arquivos; o prazo real, comunicado pela equipe, é 04/10.

Lição: toda afirmação sobre o material precisa vir com arquivo e trecho. Passei a exigir isso.

## 29/09 a 03/10/2026 — Fase 0: decisões e preparação

- **Stack:** Python + FastAPI + Jinja2 + SQLite: um processo só, sem etapa de build, HTML semântico (bom para teclado e acessibilidade) e um banco que a banca roda sem criar conta. Cheguei a prever HTMX, mas formulários HTML simples resolveram todas as telas.
- **Repositório** `lia-central-atividades`: privado desde 30/09 para ter backup, público na entrega; commits com o e-mail noreply do GitHub.
- **Google:** conta Gmail pessoal no Cloud e no Drive (a institucional pode ser bloqueada por política da organização, erro `403 domainPolicy` citado no guia). Escopo só `drive.readonly`; callback em `http://localhost:8000/auth/callback` (a 8080 estava ocupada na minha máquina). Credenciais só no `.env` local, fora do git.
- **IA no produto:** Gemini na camada gratuita, porque a banca consegue uma chave grátis para rodar no próprio ambiente; sem chave, o app funciona com regras. Ressalva: na camada gratuita o Google pode usar o conteúdo para melhorar produtos, o que é aceitável com dados fictícios, mas não com dados reais.
- **Demo** preparada para três cenários, porque o material não diz como a banca vai inserir arquivos (eu subo o arquivo, compartilho a pasta ou a banca roda no ambiente dela): README reproduzível, pasta pronta para compartilhar e botão de sincronização manual.
- **Dificuldade:** ao ativar o faturamento do Google Cloud, recebi "Não foi possível concluir a configuração de faturamento [OR_BACR2_59]". Conferi que ele não é necessário: a Drive API pede só um projeto, e "All standard use of the Google Drive API is available at no additional cost". Criei o projeto sem faturamento.

## 03/10/2026 — Fase 1: leitura do Drive e tela de sincronização

- **Decisões:**
  - **Varredura completa e recursiva** a cada execução, em vez da Changes API: a pasta é pequena, e "sumiu da varredura" já cobre remoção, lixeira e arquivo movido (o app consulta o arquivo para dizer qual dos três).
  - **Mudança detectada pelo hash do conteúdo extraído**, porque o `version` do Drive muda até num rename: renomear não reprocessa; editar gera uma versão nova da **mesma** fonte.
  - **Falha de listagem aborta antes de mexer no estado dos arquivos:** nada é marcado como removido (invariante "falha ≠ não há atividades").
  - Tipo do arquivo pela **extensão** (o mimeType do `.md` varia conforme o envio); `.docx`, PDF, imagem e vídeo aparecem como "Ignorado", com o motivo.
  - OAuth com `state`, PKCE e acesso offline. A sincronização automática a cada 5 min já entrou nesta fase, com a mesma trava do botão "Sincronizar agora".
- **Erros e correções:** o primeiro login deu `403: access_denied`, porque minha conta não estava em *Test users*. As credenciais eram recarregadas sem a data de expiração, e o sync falharia depois de 1 hora (o assistente percebeu ao revisar o próprio código). O log de acesso gravaria o código de autorização do callback; agora ele é omitido.
- **Testes:** 42 automatizados, com um Drive falso em memória e os arquivos do pacote. No Drive real: 6 arquivos processados com link, 0 falhas, e a sincronização seguinte não duplicou versões.

## 03/10/2026 — Decisões: fonte oficial e revisores

- **Fonte oficial das atividades:** a planilha apontada pelo `INDEX.md` cria as ACT-\* **uma única vez**; a partir daí, o banco do app é a verdade. Uma edição posterior da planilha vira **sugestão** (linha nova → criação; linha removida → só aviso). Uma planilha que o INDEX não aponta nunca importa nem apaga.
  - Alternativas: deixar a planilha como oficial (exigiria escrever no Drive), espelhar e sobrescrever (um documento mudaria dado oficial sem revisão), ignorar edições posteriores e aplicar sozinho os campos que ninguém decidiu no app. Esta última é a mais defensável pela precedência do INDEX. Fiquei com a regra única "nada muda sem um humano aprovar", porque o INDEX chama a planilha de "fonte inicial e provisória" e o GUIA fala em exibir as alterações aprovadas "depois da importação da planilha".
- **Revisores:** Bruno revisa qualquer frente (o LEIA_ME diz que ele "pode revisar sugestões", sem limite); Carla, só a Formação (o GUIA diz que ela "revisa propostas de atividades da sua frente"); a auto-revisão da Carla é permitida, com aviso e registro. Descartei: os dois revisarem tudo (repetiria a regra depreciada do plano antigo), cada líder só na sua frente (Operações ficaria sem revisor) e proibir a auto-revisão (plausível, mas o material não exige).

## 03/10/2026 — Fase 2: importação, atividades e histórico

- **Construído:** classificação de cada arquivo a partir do `INDEX`, importação única da planilha, os quatro membros de demonstração com troca de usuário, "Minhas atividades", "Todas as atividades" com filtros, detalhe com fonte e histórico, criação e edição.
- **Decisões:**
  - Ambiguidade na fonte (duas planilhas citadas, dois INDEX, dois arquivos com o nome apontado): nada é importado e o motivo aparece na tela. Preferi parar e avisar a escolher sozinho.
  - `status: deprecated` vem antes de tudo, e a ata vem antes de "citado no INDEX". Sem essa ordem, a ata de 01/10, que o INDEX cita, viraria documento de orientação.
  - Cada atividade importada guarda a linha da planilha e o trecho da ata citada na coluna Origem.
  - Dado ausente fica ausente: responsável que não é membro, prazo que não é data e estado desconhecido viram "a confirmar"/"a definir", com aviso.
  - Edição concorrente: se outra pessoa salvou antes, o app avisa em vez de sobrescrever.
- **Correção — ID das atividades criadas no app:** o assistente implementou IDs `LIA-001`… e apresentou isso como decisão tomada. Pedi a origem: `LIA-` não existe no material, e `ACT-*` é o padrão em todo ele (INDEX, enunciado e contrato da IA na especificação); a especificação (§5 B) só pede "persistida com ID". Decisão: continuar a numeração `ACT-*` (depois de `ACT-104` vem `ACT-105`). Se a planilha trouxer um ID que já existe, a linha não sobrescreve a atividade e vira aviso. Lição: escolha sem base no material é apresentada como proposta antes de virar código.
- **Testes:** 88 automatizados, incluindo o gabarito da carga inicial (Ana: 101 e 104; Davi: 102 e 104; Carla: 103; Bruno: nenhuma), a planilha vazia homônima e a persistência depois de reiniciar. No Drive real, o mesmo gabarito. No navegador (Firefox sem interface), em largura de computador e de celular: sem rolagem lateral; criar, editar e reiniciar mantêm a atividade e o histórico.

## 03/10/2026 — Fase 3: conflitos de fonte e falhas da sincronização

- **Construído:** conflitos de fonte registrados e visíveis (planilha parecida não apontada pelo INDEX, fonte ambígua, INDEX apontando outra planilha), decididos por escrito só pelo Bruno; atividades com fonte indisponível marcadas como **possivelmente desatualizadas**, mantendo o último estado confirmado; aviso em todas as telas quando a leitura do Drive falha ou atrasa; nova tentativa mais cedo depois de uma falha (30 s, 1, 2 e 4 min).
- **Correção — quando uma planilha vira conflito:** a primeira versão (do assistente) usava só o cabeçalho (colunas ID e Atividade), por ser "objetivo". Relendo o material, o critério do case é o **nome**: o R10 fala em "planilha vazia com nome parecido", a especificação (§3) em "nome semelhante" e "arquivos homônimos", e o `LEIA_CONFLITO.md` também cita o nome. A `Ata - copia vazia.xlsx` só passava por acaso, por ter o mesmo cabeçalho; uma cópia vazia sem cabeçalho não geraria conflito. Decisão: **nome parecido ou** cabeçalho de registro (o cabeçalho pega listas paralelas com outro nome). Um orçamento sem relação continua só como "sem autoridade".
- **Ciclo do conflito:** aberto → decidido por uma pessoa ou superado (a situação sumiu). Uma falha de leitura não encerra conflito, e uma versão nova do arquivo abre um conflito novo. Nesta fase, a decisão só ficava registrada; "aceitar a nova fonte" veio na Fase 4.
- **Erro:** o conflito da planilha vazia não se encerrava quando ela ia para a lixeira. Com a lista vazia, a consulta virava `NOT IN (NULL)`, que em SQL nunca é verdadeiro.
- **Testes:** 111 automatizados (conflitos sem apagar nada e sem duplicar, conflito superado e reaberto, permissões, fonte removida).

## 04/10/2026 — Fase 4: sugestões das atas e revisão humana

- **Decisões antes de implementar:** três entradas geram sugestões e caem na mesma tela de revisão: ata nova ou editada (IA), planilha importada editada e conflito de troca de fonte. A planilha editada é comparada com a **versão anterior da planilha**, para não "desfazer" edições aprovadas no app. Quando a planilha contradiz uma decisão humana, o assistente recomendou não gerar sugestão; preferi gerá-la **com alerta** ("contraria a decisão de X em DD/MM") e deixar o revisor decidir, o que fica mais perto do R10. As atas da carga inicial também passam pela IA (regra única); a de 01/10, que repete a planilha, deve dar zero sugestões.
- **Construído:**
  - cada versão de ata (arquivo + hash) é analisada uma vez; a resposta segue o contrato da especificação (§6);
  - a resposta é **validada antes de aparecer**: trecho literal no documento, ID existente, prazo escrito no trecho (data relativa → prazo vazio + incerteza), responsável que é membro e está citado, hipótese descartada, campo igual ao oficial removido. Os descartes aparecem com o motivo;
  - tela de revisão com evidência e valor oficial × proposto: aceitar (com ajuste por campo) ou rejeitar com motivo. O aceite grava evento com autor, antes/depois e a ata como fonte;
  - ata editada substitui as sugestões pendentes da versão antiga. Falha da IA vira "falhou", com motivo e nova tentativa; sincronização e edição manual continuam.
- **Verificação com o modelo real** (`gemini-3.8-flash`, dados fictícios): acertou as três atas. Na de 01/10, nada a fazer. Na de 03/10, ACT-101 com prazo 07/10 e próximo passo, sem pôr Bruno como responsável. Na de 04/10, criação para Carla até 10/10, ignorando o "talvez". As respostas ficaram gravadas, e os testes as reutilizam sem rede.
- **Erros e correções:**
  - HTTP 400 nas três atas, porque o código removia a chave `title` do esquema JSON, inclusive a propriedade `title` da atividade.
  - A cota gratuita (20 pedidos por dia) acabou com as repetições; o app deixou de repetir erro de cota diária.
  - A regra de "atividades relacionadas" marcava o ACT-104 só pelo verbo "revisar"; ficou só "mesmo responsável".
- **Saída incorreta do modelo — o plano B:** sem cota no 3.8, rodamos o plano B anotado, `gemini-3.5-flash-lite`. Na ata de 04/10 ele propôs **atualizar o ACT-103**, a leitura que eu já tinha descartado em 29/09 (aceitar mexeria numa tarefa bloqueada sem base); na de 03/10, citou evidência só para o prazo. Abandonei esse modelo e acrescentei uma proteção que vale para qualquer modelo: atualização cujo trecho **não cita o ID** ganha o alerta "a IA concluiu que se trata da mesma atividade; confira".
- **Troca para o `gemini-3.6-flash`:** pedi uma comparação em vez de escolher pelo nome. Rodamos as três atas em cada modelo Flash estável, com a mesma validação do app, e repetimos as duas atas difíceis nos finalistas. O 3.6 e o 3.5-flash acertaram 5 de 5; o 3.7 falhou por sobrecarga (503/504). Fiquei com o 3.6: mesmo preço do 3.8, gabarito completo e nenhuma falha de disponibilidade nos testes; ~US$ 0,01 por ata na camada paga.
- **"Aceitar a nova fonte":** no conflito em que o INDEX aponta outra planilha, o Bruno pode aceitá-la. Nenhuma atividade muda na hora: cada diferença vira sugestão, e a troca nunca apaga valor do app.
- **Testes:** 157 automatizados (gabarito das três atas com as respostas reais e sem IA, idempotência, mesma ata em `.md` e Google Docs, aceite, ajuste e rejeição, permissões, ID inexistente, prazo relativo, instrução dentro do documento, planilha editada, troca de fonte).

## 04/10/2026 — O Drive real achou o que os testes não pegaram

- **Ensaio com uma cópia do banco real:** o 3.6 também respondeu 503 (sobrecarga) antes de responder, e passei para 4 tentativas. O "Sincronizar agora" ficou 43 s parado esperando a IA, o que numa demonstração parece travado; a IA passou a rodar em segundo plano depois da leitura do Drive.
- **Sugestão de ata na lixeira:** subi por engano o `Ata_2026-10-03.md` e o mandei para a lixeira. O app marcou o arquivo como indisponível, mas a sugestão dele **continuava aceitável**, e a proposta do Google Doc da mesma ata seria descartada como repetida. Correção: sugestão com documento indisponível não pode ser aceita, e uma proposta equivalente de outro arquivo a substitui.
- **Revisão real:** como Bruno, aceitei o novo prazo do ACT-101; como Carla, a criação que virou ACT-105, com aviso de auto-revisão. A sugestão da ata de 03/10 aparecia como "documento de 04/10": o Google Doc convertido do `.docx` exporta o cabeçalho de página antes do título, e o leitor perdia a `data_da_reuniao`. Um teste mostrou que a primeira correção (do assistente) aceitava `chave: valor` em qualquer das 12 primeiras linhas, e um "Nota: …" no corpo viraria cabeçalho; restringi a posição.
- **Testes:** 163 automatizados.

## 04/10/2026 — Fase 5: Comece aqui e "o que mudou para mim"

- **Decisões:** o marco do "o que mudou para mim" é um botão "Marcar como visto", mais a escolha de período; descartei marcar a visita ao abrir a página, porque recarregar apagaria o resumo. A lista vem dos registros e atende o R09 sozinha; "Resumir com IA" é opcional e escreve **só a partir dos itens da lista**, com conferência antes de aparecer.
- **Construído:** o "Comece aqui" é montado com **trechos copiados dos documentos de orientação, com link**; o app não escreve propósito nem frentes, e o que o documento marca como parcial aparece como "Provisório: a confirmar". O "o que mudou para mim" separa confirmado, propostas pendentes e dados incertos, e diz "Nada mudou" quando é o caso. "Novidades dos documentos" mostra a linha do tempo de cada arquivo.
- **Saída do modelo corrigida:** no parágrafo da Ana, o `gemini-3.6-flash` escreveu "Fique **atenta**", deduzindo o gênero pelo nome, que o material não informa. Acrescentei linguagem neutra ao pedido e uma conferência automática: o parágrafo é descartado se citar data, `ACT-*` ou pessoa fora dos itens, ou se der como fato um valor que só existe numa proposta pendente.
- **Testes:** 194 automatizados (Ana × Davi, proposta pendente que não aparece como confirmada, lacunas, linha do tempo, parágrafo da IA com dado inventado descartado).

## 04/10/2026 — Fase 6: celular, teclado e estados de tela

- **Como conferi:** capturas com o Firefox sem interface, em 390 px e 1280 px, de todas as telas, com um script que marcava em vermelho o que passasse da largura; com cópia do banco real e com banco vazio; contraste calculado pela fórmula da WCAG.
- **Corrigido:**
  - um selo fazia a página rolar 7 px para o lado no celular;
  - com o banco vazio, o Comece aqui dizia "Nenhuma atividade aberta" antes de qualquer leitura, ou seja, falha parecendo ausência; agora diz que ainda não houve importação;
  - erros mostravam JSON cru; agora há páginas 404/405/500 do app, sem detalhe técnico;
  - um duplo clique em "Criar" podia criar duas atividades; todo formulário que grava trava o reenvio;
  - entrou o aviso "Sem conexão com o app", o foco vai para o resumo de erros do formulário e os selos ganharam borda no modo de alto contraste.
- **Conferido:** contraste de todos os textos ≥ 6,99:1; estado sempre com ícone + texto; link "Pular para o conteúdo"; foco visível em todos os elementos; alvos de toque de 44 px.
- **Não feito:** teste com leitor de tela e auditoria automática (axe); registrado como limitação no README.
- **Testes:** 198 automatizados.

## 04/10/2026 — Quem confirma o propósito

- O Comece aqui dizia "Provisório: a confirmar · Confirmação com Bruno", mas não havia onde confirmar. Decidi não criar botão no app. O propósito pertence ao `ESTADO-ATUAL.md`; o Drive é o repositório dos documentos (especificação §1); e a precedência do INDEX dá peso à decisão aprovada no app "sobre a atividade", não a textos institucionais. Confirmar no app deixaria o banco dizendo "oficial" e o documento dizendo "provisória": duas verdades. A tela passou a dizer que a confirmação é feita pelo Bruno no próprio documento, no Drive.

## 04/10/2026 — Fase 7: documentação, validação e edição no Drive real

- **README** com todos os itens pedidos na entrega, conferido frase a frase contra o texto real das telas (três frases estavam diferentes e foram corrigidas). A restrição da pasta monitorada passou a aparecer também na tela de sincronização, como pede o FAQ.
- **Instalação do zero:** copiei só os arquivos versionados e segui o README, com o `.env` vazio. 198 testes passaram e 1 foi pulado (o do login); o app subiu e listou as variáveis que faltavam.
- **Antes de tornar o repositório público:** busquei em todos os commits os valores do `.env` (sem imprimi-los), meu e-mail e o telefone de contato do processo. Nada encontrado.
- **Edição de ata no Drive real (caso 3):** troquei no Google Doc o prazo `2026-10-07` por `2026-10-08`. A leitura automática das 16:37 ainda recebeu a versão antiga; a das 16:42, cerca de 9 minutos depois da edição, registrou a versão nova da **mesma** fonte. Mudei o README de "até ~5 minutos" para "5 a 10 minutos", ainda dentro dos 15 do enunciado. A análise deu 503 e se recuperou sozinha na tentativa seguinte, com uma sugestão só para o prazo e o alerta de que o prazo atual foi decidido pelo Bruno. O ACT-101 seguiu com 07/10 até a revisão.
- **Por que uma falha da IA não cai nas regras sem IA:** perguntei, e conferimos no código. As regras só entendem o formato do pacote e, numa ata de texto livre, dariam "0 sugestões"; gravar isso como análise concluída transformaria falha em ausência e impediria o Gemini de ler aquela versão depois. Mantive assim e expliquei no README (seção 9).
- **Testes:** 199 automatizados.

## O que ficou de fora, limitações e próximos passos

**Ficou de fora:**
- PDF com texto selecionável: priorizei os fluxos centrais;
- Claude como provedor alternativo no produto: sem chave da API para testar;
- API de mudanças do Drive: a varredura de 5 min cumpre os 15 min do enunciado numa pasta pequena;
- login real e permissões por pessoa: o case aceita troca de usuário; o caminho está no README (seção 11);
- limpeza automática do texto de arquivos que saíram da pasta;
- teste com leitor de tela;
- "aceitar" nos conflitos de planilha parecida ou de fonte ambígua.

As limitações conhecidas estão no README (seção 10).

**Próximos passos, em ordem**
1. Login com a conta Google de cada membro e filtro de todas as telas (e do que vai para a IA) pelas permissões de cada arquivo no Drive. É o que impede usar dados reais hoje.
2. Retenção e limpeza do conteúdo guardado (fontes indisponíveis, acesso revogado).
3. Mais atas de teste com texto livre ("até sexta", pessoa desconhecida, duas decisões no mesmo parágrafo), gravando as respostas do modelo real.
4. PDF com texto selecionável, teste com leitor de tela e auditoria automática (axe), e a API de mudanças do Drive, se o acervo crescer.
5. Modelo reserva quando o Gemini responde 503 (ex.: `gemini-3.5-flash`, que acertou as atas do pacote).

**O que levo do processo**
- Exigir arquivo e trecho para toda afirmação sobre o material pegou erros do assistente várias vezes.
- O Drive real achou falhas que o Drive falso dos testes não pegava: a sugestão de um arquivo na lixeira continuava aceitável, e o Google Doc convertido do `.docx` exporta o cabeçalho de página antes do título.
- O erro do modelo mais barato foi no caso mais sutil (tarefa nova × atualização de uma existente). A validação de trecho, ID e data não pegaria esse erro sozinha; por isso entrou o alerta para atualização sem ID no trecho, e a decisão final continua com uma pessoa.
