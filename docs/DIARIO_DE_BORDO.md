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
