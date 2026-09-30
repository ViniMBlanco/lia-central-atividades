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
