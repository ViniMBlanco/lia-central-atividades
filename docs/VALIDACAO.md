# Registro de validação

Casos testados com entrada, resultado esperado, resultado observado e correções. O enunciado exige no mínimo 5, incluindo **conflito**, **dado ausente** e **arquivo adicionado ao Drive**. A base são os critérios de aceite da especificação técnica (§9).

> Estado: **a preencher** conforme cada fase for concluída.
>
> Testes automatizados: `python -m pytest` (88 testes ao fim da Fase 2, com um Drive falso em memória e os arquivos do pacote de teste em `tests/fixtures/`). Cobrem leitores, varredura, renomeação, edição, remoção, lixeira, falha de leitura, falha de listagem, autoridade das fontes, importação única, filtros, criação, edição e histórico.

| # | Caso | Entrada / preparação | Resultado esperado | Resultado observado | Correções |
|---|---|---|---|---|---|
| 0 | Carga inicial (Fase 1) | Pasta `LIA case teste` com os 6 arquivos de `01_CARGA_INICIAL`; conectar a conta e sincronizar | 6 fontes processadas, cada uma com link para o Drive; `.xlsx` continua `.xlsx` (não convertido); cabeçalhos lidos (plano antigo = `deprecated`) | 03/10: 6 processadas, 0 falhas, 0 ignoradas; link de cada arquivo abre no Drive; `Ata_registro.xlsx` com mimeType de `.xlsx`; `status: deprecated` lido no plano antigo; a sincronização automática seguinte (5 min) não baixou nada de novo nem duplicou versões | Primeira tentativa de login: `403 access_denied` (conta fora de *Test users*); corrigido no console |
| 1 | Visão pessoal | Entrar como Ana e como Davi após a carga inicial | Ana: ACT-101 e ACT-104. Davi: ACT-102 e ACT-104. ACT-104 conta como uma atividade só. Prazos e bloqueios visíveis | 03/10, Drive real: Ana vê ACT-101 (05/10, "vence em 2 dias", em andamento) e ACT-104; Davi vê ACT-102 e ACT-104; Carla vê ACT-103 (bloqueada); Bruno não tem atividades. ACT-104 aparece uma vez, com "Ana, Davi". Trocar de usuário não altera nenhum dado | — |
| 2 | Arquivo adicionado ao Drive | Colocar `Ata_2026-10-03` (Google Docs nativo) na pasta, sem usar a aplicação | Aparece como fonte processada em até 15 min; uma sugestão fica pendente | | |
| 3 | Edição de arquivo conhecido | Alterar o texto de uma ata já processada | Nova versão detectada na mesma fonte, sem documento duplicado; sugestão antiga marcada como substituída | | |
| 4 | Atualização de prazo | Ata de 03/10 muda o prazo do ACT-101 | Sugestão de **atualização** (não de criação), com evidência; o prazo oficial só muda depois da aprovação | | |
| 5 | Conflito: arquivo homônimo | Colocar `Ata - copia vazia.xlsx` na pasta | Atividades existentes permanecem; o arquivo aparece como sem autoridade ou descartado, com aviso visível | | |
| 6 | Atividade manual | Criar uma tarefa pela interface e reiniciar o app | A tarefa persiste, com autor e histórico | 03/10, navegador: sem usuário escolhido, a criação é recusada com aviso. Como Davi, criada `ACT-105`; editados prazo e estado com motivo. Depois de parar e subir o servidor, a atividade continua, com "Criada manualmente por Davi" e o evento de edição (antes → depois, autor, motivo) | Texto do histórico ajustado: "alteração manual" aparecia também na criação |
| 7 | Ideia vaga | Ata de 04/10 ("Talvez… série diária de notícias") | Não vira atividade nem sugestão | | |
| 8 | Erro de fonte | Retirar o acesso a um arquivo ou simular erro de leitura | Aviso visível; o estado confirmado continua, marcado como possivelmente desatualizado | | |
| 9 | Resumo pessoal | Mudança aprovada que afeta Ana e não Davi | Resumos diferentes, com fontes e estado de aprovação | | |
| 10 | Primeiro acesso | Membro novo, sem orientação oral | Encontra propósito (provisório), frentes, fonte das tarefas e primeira ação; lacunas identificadas | | |
| 11 | Dado ausente | Ata com "até sexta" ou sem responsável | Prazo ou responsável ficam vazios, com incerteza marcada; nada é inventado | | |
