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
4. **Editar a planilha no Drive não sobrescreve nada.** O app detecta a nova versão e avisa que ela diverge; as diferenças são tratadas como sugestão para revisão humana. Linha apagada na planilha não apaga atividade.
5. **Planilha que o `INDEX` não aponta nunca importa nem apaga.** É o caso de `Ata - copia vazia.xlsx`: aparece como "sem autoridade" na tela de sincronização, e as atividades continuam intactas. Se ela puder ser confundida com a fonte — **nome parecido** (palavra em comum com a planilha apontada, como "Ata - copia vazia" × "Ata_registro") **ou** cabeçalho de registro de atividades (colunas ID e Atividade) —, vazia ou não, vira um **conflito de fonte** visível (ver seção 5). Uma planilha sem nenhuma das duas coisas fica só como "sem autoridade". A data do arquivo não importa: "mais recente" não significa "mais confiável".
6. **Ambiguidade não é resolvida por palpite.** Dois `INDEX`, duas planilhas com o nome apontado, `INDEX` citando duas planilhas ou passando a apontar outra depois da importação: nada é importado nem trocado; vira conflito de fonte, com o motivo em "Todas as atividades" e em "Estado da sincronização", até uma pessoa registrar a decisão.
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

**Conflitos de fonte.** Quando os arquivos não deixam claro qual é a verdade — planilha não apontada pelo `INDEX` com nome parecido ou com cabeçalho de registro de atividades (como `Ata - copia vazia.xlsx`), dois `INDEX`, duas planilhas com o nome apontado, ou o `INDEX` passando a apontar outra planilha —, o app registra um conflito. O conflito **nunca altera atividades**: fica visível em "Estado da sincronização" (e com aviso em "Todas as atividades") até uma pessoa que revisa todas as frentes (Bruno, nos dados de teste) registrar a decisão por escrito. Se a situação desaparece sozinha (o arquivo sai da pasta), o conflito fica como "superado". Uma versão nova do mesmo arquivo abre um conflito novo, porque a decisão anterior valia para outro conteúdo.

**Por que ler a pasta inteira, e não a API de mudanças do Drive.** A pasta é pequena, a leitura completa é barata (arquivos sem mudança não são baixados de novo) e deixa óbvio o que saiu da pasta: é o que não apareceu na leitura. A `changes.list` seria uma otimização para acervos grandes.

## 6. Formatos suportados

*A preencher.*

## 7. IA no produto e custo estimado por uso

*A preencher.*

## 8. Limitações conhecidas

*Em construção.*

- A sincronização só roda com o app aberto; não há notificação do Drive (webhook).
- A decisão de um conflito de fonte é registrada, mas o app não troca a fonte das atividades: trocar de planilha depois da importação exigiria uma nova regra de migração.

## 9. Antes de usar dados reais

*A preencher.*

## 10. Ferramentas de IA usadas no desenvolvimento

Claude Code (plano Claude Pro), para análise do material, planejamento e programação em par. Detalhes em [`docs/DIARIO_DE_BORDO.md`](docs/DIARIO_DE_BORDO.md).

## 11. Documentação complementar

- [`docs/DIARIO_DE_BORDO.md`](docs/DIARIO_DE_BORDO.md): decisões, dificuldades e verificações.
- [`docs/VALIDACAO.md`](docs/VALIDACAO.md): casos testados.
