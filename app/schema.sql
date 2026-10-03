-- Esquema do banco local (SQLite). Datas sempre em ISO 8601 com fuso (UTC).
-- Exibição em America/Sao_Paulo é feita na camada de apresentação.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Fontes: um registro por arquivo do Drive visto na pasta monitorada.
-- O file_id do Drive é a identidade: renomear não cria outra fonte.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sources (
    file_id           TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    mime_type         TEXT NOT NULL,
    ext               TEXT,                 -- extensão em minúsculas, sem ponto ('' se não houver)
    kind              TEXT,                 -- markdown | xlsx | gdoc | gsheet | text | folder | (vazio = não suportado)
    web_url           TEXT,
    path              TEXT,                 -- caminho legível a partir da pasta raiz
    parent_id         TEXT,
    size_bytes        INTEGER,
    md5_checksum      TEXT,                 -- só arquivos binários têm
    modified_at       TEXT,                 -- modifiedTime do Drive
    drive_version     TEXT,                 -- campo version do Drive (muda até em renomeação)
    content_hash      TEXT,                 -- sha256 do conteúdo extraído na última versão processada
    sync_status       TEXT NOT NULL DEFAULT 'pending'
                      CHECK (sync_status IN ('pending', 'processed', 'failed', 'ignored', 'unavailable')),
    status_reason     TEXT,                 -- motivo legível de falha, de ser ignorado ou de estar indisponível
    authority         TEXT NOT NULL DEFAULT 'none'
                      CHECK (authority IN ('activity_register', 'direction', 'minutes', 'deprecated', 'none')),
    authority_reason  TEXT,                 -- por que o arquivo tem essa autoridade (recalculado a cada sync)
    doc_title        TEXT,                 -- título (H1 ou primeira linha)
    doc_meta          TEXT,                 -- JSON com o cabeçalho "chave: valor" (status, atualizado_em...)
    first_seen_at     TEXT NOT NULL,
    last_seen_at      TEXT NOT NULL,        -- última vez que apareceu numa varredura completa
    last_processed_at TEXT,                 -- última extração de conteúdo bem-sucedida
    last_error_at     TEXT
);

-- Cada versão de conteúdo processada fica guardada: é a "referência à versão processada"
-- usada por evidências, sugestões e histórico. Idempotência: (file_id, content_hash).
CREATE TABLE IF NOT EXISTS source_versions (
    version_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         TEXT NOT NULL REFERENCES sources(file_id),
    content_hash    TEXT NOT NULL,
    drive_version   TEXT,
    modified_at     TEXT,
    name_at_version TEXT NOT NULL,
    extracted_text  TEXT NOT NULL,
    structured_json TEXT,                   -- planilhas: abas e células; documentos: cabeçalho
    processed_at    TEXT NOT NULL,
    UNIQUE (file_id, content_hash)
);

-- ---------------------------------------------------------------------------
-- Membros de demonstração (troca explícita de usuário; não há login de membro).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS members (
    member_id    TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    front        TEXT NOT NULL,
    role         TEXT NOT NULL,
    review_scope TEXT NOT NULL DEFAULT 'none' CHECK (review_scope IN ('all', 'front', 'none'))
);

-- Pessoas de demonstração (LEIA_ME_PRIMEIRO.md do pacote de teste).
-- Revisão: Bruno em qualquer frente; Carla só na Formação ("revisa propostas de atividades
-- da sua frente", GUIA_INICIAL.md); Ana e Davi não revisam.
INSERT OR IGNORE INTO members (member_id, display_name, front, role, review_scope) VALUES
    ('U-A', 'Ana',   'Growth',    'Membro, responsável por tarefas',            'none'),
    ('U-B', 'Bruno', 'Growth',    'Líder de Growth, pode revisar sugestões',    'all'),
    ('U-C', 'Carla', 'Formação',  'Membro e revisora de sugestões da Formação', 'front'),
    ('U-D', 'Davi',  'Operações', 'Membro, responsável por tarefas',            'none');

-- ---------------------------------------------------------------------------
-- Atividades: depois da importação, o banco é a fonte oficial.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS activities (
    activity_id TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT,
    next_step   TEXT,
    front       TEXT,
    status      TEXT NOT NULL CHECK (status IN ('a_fazer', 'em_andamento', 'bloqueada', 'concluida')),
    due_date    TEXT,                       -- AAAA-MM-DD ou NULL ("a definir")
    priority    TEXT,
    notes       TEXT,
    origin      TEXT NOT NULL CHECK (origin IN ('import', 'manual', 'suggestion')),
    created_by  TEXT NOT NULL,              -- member_id ou 'sistema:importacao'
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Importação única da planilha apontada pelo INDEX. Depois dela, o banco é a fonte oficial;
-- edições posteriores da planilha não sobrescrevem nada (viram sugestões para revisão).
CREATE TABLE IF NOT EXISTS register_import (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    file_id      TEXT NOT NULL REFERENCES sources(file_id),
    file_name    TEXT NOT NULL,
    sheet_name   TEXT NOT NULL,
    content_hash TEXT NOT NULL,             -- versão da planilha que foi importada
    imported_at  TEXT NOT NULL,
    n_imported   INTEGER NOT NULL,
    warnings     TEXT NOT NULL DEFAULT '[]' -- JSON: linhas não importadas e outros avisos
);

-- Situação da fonte das atividades, recalculada a cada sincronização concluída.
CREATE TABLE IF NOT EXISTS register_status (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    state      TEXT NOT NULL CHECK (state IN ('importada', 'aguardando', 'alterada', 'atencao')),
    message    TEXT NOT NULL,
    checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_owners (
    activity_id TEXT NOT NULL REFERENCES activities(activity_id),
    member_id   TEXT NOT NULL REFERENCES members(member_id),
    PRIMARY KEY (activity_id, member_id)
);

CREATE TABLE IF NOT EXISTS activity_refs (
    ref_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id     TEXT NOT NULL REFERENCES activities(activity_id),
    file_id         TEXT NOT NULL REFERENCES sources(file_id),
    version_or_hash TEXT NOT NULL,
    locator         TEXT,                   -- aba/linha/célula ou seção
    quote           TEXT,
    relation_type   TEXT NOT NULL,          -- imported_from | mentioned_in | changed_by
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suggestions (
    suggestion_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file_id       TEXT NOT NULL REFERENCES sources(file_id),
    source_version       TEXT NOT NULL,
    kind                 TEXT NOT NULL CHECK (kind IN ('create', 'update')),
    target_activity_id   TEXT REFERENCES activities(activity_id),
    front                TEXT,
    front_inferred       INTEGER NOT NULL DEFAULT 0,
    proposed_fields      TEXT NOT NULL,     -- JSON
    evidence             TEXT NOT NULL,
    uncertainties        TEXT NOT NULL DEFAULT '[]',
    related_activity_ids TEXT NOT NULL DEFAULT '[]',
    generated_by         TEXT NOT NULL,     -- deterministico | gemini:<modelo> | anthropic:<modelo>
    review_status        TEXT NOT NULL DEFAULT 'pendente'
                         CHECK (review_status IN ('pendente', 'aceita', 'ajustada', 'rejeitada', 'substituida')),
    reviewer_id          TEXT REFERENCES members(member_id),
    reviewed_at          TEXT,
    review_reason        TEXT,
    self_review          INTEGER NOT NULL DEFAULT 0,
    dedupe_key           TEXT NOT NULL UNIQUE,
    created_at           TEXT NOT NULL
);

-- Histórico auditável: toda mudança em atividade oficial gera um evento com autor.
CREATE TABLE IF NOT EXISTS activity_events (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id    TEXT NOT NULL REFERENCES activities(activity_id),
    actor_id       TEXT NOT NULL,
    ts             TEXT NOT NULL,
    action         TEXT NOT NULL,           -- import | create | update | suggestion_accepted ...
    before         TEXT,                    -- JSON
    after          TEXT,                    -- JSON
    reason         TEXT,
    source_file_id TEXT,
    source_version TEXT,
    suggestion_id  INTEGER REFERENCES suggestions(suggestion_id)
);

CREATE TABLE IF NOT EXISTS conflicts (
    conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    file_id     TEXT REFERENCES sources(file_id),
    description TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'aberto' CHECK (status IN ('aberto', 'resolvido')),
    resolved_by TEXT,
    resolved_at TEXT,
    resolution  TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE (kind, file_id)
);

-- ---------------------------------------------------------------------------
-- Sincronização
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sync_runs (
    run_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger      TEXT NOT NULL CHECK (trigger IN ('auto', 'manual', 'startup')),
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    ok           INTEGER,                   -- NULL = em andamento
    error        TEXT,
    n_seen       INTEGER NOT NULL DEFAULT 0,
    n_new        INTEGER NOT NULL DEFAULT 0,
    n_changed    INTEGER NOT NULL DEFAULT 0,
    n_processed  INTEGER NOT NULL DEFAULT 0,
    n_failed     INTEGER NOT NULL DEFAULT 0,
    n_ignored    INTEGER NOT NULL DEFAULT 0,
    n_unavailable INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sync_state (
    folder_id       TEXT PRIMARY KEY,
    folder_name     TEXT,
    folder_url      TEXT,
    account_name    TEXT,
    last_success_at TEXT,
    last_attempt_at TEXT,
    last_error      TEXT
);

-- Marco do "o que mudou para mim".
CREATE TABLE IF NOT EXISTS visits (
    member_id    TEXT PRIMARY KEY REFERENCES members(member_id),
    last_seen_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(sync_status);
CREATE INDEX IF NOT EXISTS idx_events_activity ON activity_events(activity_id, ts);
CREATE INDEX IF NOT EXISTS idx_suggestions_status ON suggestions(review_status);
