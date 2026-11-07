-- Migración 1 -> 2.
-- Sólo agrega: métricas de relevancia por fuente, ajustes, revisión de fusiones,
-- contabilidad de IA, bitácora de respaldos e incidentes. No reescribe datos.

ALTER TABLE source_runs ADD COLUMN relevantes INTEGER NOT NULL DEFAULT 0;
ALTER TABLE source_runs ADD COLUMN duplicadas INTEGER NOT NULL DEFAULT 0;
ALTER TABLE analyses ADD COLUMN excepcion INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS settings (
    clave            TEXT PRIMARY KEY,
    valor            TEXT NOT NULL,
    actualizado_en   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS merge_reviews (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_origen       TEXT NOT NULL,
    job_destino      TEXT NOT NULL,
    similitud        REAL NOT NULL,
    motivo           TEXT,
    estado           TEXT NOT NULL DEFAULT 'sugerida',
    creado_en        TEXT NOT NULL,
    resuelto_en      TEXT,
    UNIQUE (job_origen, job_destino)
);

CREATE TABLE IF NOT EXISTS ai_calls (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    proveedor        TEXT NOT NULL,
    modelo           TEXT NOT NULL,
    proposito        TEXT NOT NULL,
    job_id           TEXT,
    tokens_entrada   INTEGER,
    tokens_salida    INTEGER,
    costo_usd        REAL NOT NULL DEFAULT 0,
    estado           TEXT NOT NULL,
    error            TEXT,
    creado_en        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_budget (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    periodo          TEXT NOT NULL UNIQUE,
    limite_usd       REAL NOT NULL,
    gastado_usd      REAL NOT NULL DEFAULT 0,
    llamadas         INTEGER NOT NULL DEFAULT 0,
    actualizado_en   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backup_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    archivo          TEXT NOT NULL,
    bytes            INTEGER,
    sha256           TEXT,
    verificado       INTEGER NOT NULL DEFAULT 0,
    creado_en        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id        TEXT,
    codigo           TEXT NOT NULL,
    mensaje          TEXT,
    run_id           INTEGER,
    creado_en        TEXT NOT NULL,
    resuelto_en      TEXT
);

CREATE INDEX IF NOT EXISTS idx_incidents_source ON incidents(source_id, resuelto_en);
CREATE INDEX IF NOT EXISTS idx_ai_calls_periodo ON ai_calls(creado_en);
CREATE INDEX IF NOT EXISTS idx_merge_reviews_estado ON merge_reviews(estado);

PRAGMA user_version = 2;
