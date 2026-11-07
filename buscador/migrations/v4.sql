-- Migración 3 -> 4.
-- Módulo de IA: cola persistente, caché, cuotas por ventana, análisis
-- estructurados y comprobaciones de modelo. Aditivo: no toca datos existentes.

ALTER TABLE ai_calls ADD COLUMN duracion_ms INTEGER;
ALTER TABLE ai_calls ADD COLUMN cuota_consumida INTEGER NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS ai_queue (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           TEXT NOT NULL,
    job_version_id   INTEGER,
    motivo           TEXT NOT NULL,
    prioridad        INTEGER NOT NULL DEFAULT 100,
    estado           TEXT NOT NULL,
    intentos         INTEGER NOT NULL DEFAULT 0,
    next_due         TEXT NOT NULL,
    locked_by        TEXT,
    ultimo_error     TEXT,
    creado_en        TEXT NOT NULL,
    actualizado_en   TEXT NOT NULL,
    UNIQUE (job_id, job_version_id, motivo)
);

CREATE TABLE IF NOT EXISTS ai_cache (
    clave            TEXT PRIMARY KEY,
    proveedor        TEXT NOT NULL,
    modelo           TEXT NOT NULL,
    prompt_version   TEXT NOT NULL,
    respuesta_json   TEXT NOT NULL,
    creado_en        TEXT NOT NULL,
    usado_en         TEXT,
    hits             INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ai_usage (
    proveedor        TEXT NOT NULL,
    modelo           TEXT NOT NULL,
    minuto           TEXT NOT NULL,
    dia              TEXT NOT NULL,
    peticiones       INTEGER NOT NULL DEFAULT 0,
    tokens_entrada   INTEGER NOT NULL DEFAULT 0,
    tokens_salida    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (proveedor, modelo, minuto)
);

CREATE TABLE IF NOT EXISTS ai_analyses (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id                 TEXT NOT NULL,
    job_version_id         INTEGER,
    proveedor              TEXT NOT NULL,
    modelo                 TEXT NOT NULL,
    categoria              TEXT,
    seniority              TEXT,
    modalidad              TEXT,
    elegibilidad_territorial TEXT,
    habilidades_obligatorias_json TEXT NOT NULL DEFAULT '[]',
    habilidades_deseables_json    TEXT NOT NULL DEFAULT '[]',
    anios_experiencia      INTEGER,
    idiomas_json           TEXT NOT NULL DEFAULT '[]',
    salario_json           TEXT,
    evidencia_json         TEXT NOT NULL DEFAULT '[]',
    incertidumbres_json    TEXT NOT NULL DEFAULT '[]',
    explicacion            TEXT,
    confianza              REAL,
    evidencia_invalida     INTEGER NOT NULL DEFAULT 0,
    aplicado               INTEGER NOT NULL DEFAULT 0,
    creado_en              TEXT NOT NULL,
    UNIQUE (job_id, job_version_id, modelo)
);

CREATE TABLE IF NOT EXISTS ai_model_checks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    proveedor        TEXT NOT NULL,
    modelo           TEXT,
    estado           TEXT NOT NULL,
    detalle          TEXT,
    consumio_cuota   INTEGER NOT NULL DEFAULT 0,
    creado_en        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_queue_cola ON ai_queue(estado, next_due, prioridad);
CREATE INDEX IF NOT EXISTS idx_ai_usage_dia ON ai_usage(dia);
CREATE INDEX IF NOT EXISTS idx_ai_analyses_job ON ai_analyses(job_id);

PRAGMA user_version = 4;
