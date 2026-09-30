# Registro de validação

Casos testados com entrada, resultado esperado, resultado observado e correções. O enunciado exige no mínimo 5, incluindo **conflito**, **dado ausente** e **arquivo adicionado ao Drive**. A base são os critérios de aceite da especificação técnica (§9).

> Estado: **a preencher** conforme cada fase for concluída.

| # | Caso | Entrada / preparação | Resultado esperado | Resultado observado | Correções |
|---|---|---|---|---|---|
| 1 | Visão pessoal | Entrar como Ana e como Davi após a carga inicial | Ana: ACT-101 e ACT-104. Davi: ACT-102 e ACT-104. ACT-104 conta como uma atividade só. Prazos e bloqueios visíveis | | |
| 2 | Arquivo adicionado ao Drive | Colocar `Ata_2026-10-03` (Google Docs nativo) na pasta, sem usar a aplicação | Aparece como fonte processada em até 15 min; uma sugestão fica pendente | | |
| 3 | Edição de arquivo conhecido | Alterar o texto de uma ata já processada | Nova versão detectada na mesma fonte, sem documento duplicado; sugestão antiga marcada como substituída | | |
| 4 | Atualização de prazo | Ata de 03/10 muda o prazo do ACT-101 | Sugestão de **atualização** (não de criação), com evidência; o prazo oficial só muda depois da aprovação | | |
| 5 | Conflito: arquivo homônimo | Colocar `Ata - copia vazia.xlsx` na pasta | Atividades existentes permanecem; o arquivo aparece como sem autoridade ou descartado, com aviso visível | | |
| 6 | Atividade manual | Criar uma tarefa pela interface e reiniciar o app | A tarefa persiste, com autor e histórico | | |
| 7 | Ideia vaga | Ata de 04/10 ("Talvez… série diária de notícias") | Não vira atividade nem sugestão | | |
| 8 | Erro de fonte | Retirar o acesso a um arquivo ou simular erro de leitura | Aviso visível; o estado confirmado continua, marcado como possivelmente desatualizado | | |
| 9 | Resumo pessoal | Mudança aprovada que afeta Ana e não Davi | Resumos diferentes, com fontes e estado de aprovação | | |
| 10 | Primeiro acesso | Membro novo, sem orientação oral | Encontra propósito (provisório), frentes, fonte das tarefas e primeira ação; lacunas identificadas | | |
| 11 | Dado ausente | Ata com "até sexta" ou sem responsável | Prazo ou responsável ficam vazios, com incerteza marcada; nada é inventado | | |
