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
