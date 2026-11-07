-- Migración 5 -> 6.
-- Validación humana del ranking: la muestra de 25 queda fijada en la base para
-- que las respuestas del usuario sobrevivan a cualquier reclasificación.

CREATE TABLE IF NOT EXISTS validation_samples (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    criterio         TEXT NOT NULL,
    total            INTEGER NOT NULL,
    creada_en        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS validation_items (
    muestra_id       INTEGER NOT NULL REFERENCES validation_samples(id) ON DELETE CASCADE,
    job_id           TEXT NOT NULL,
    orden            INTEGER NOT NULL,
    PRIMARY KEY (muestra_id, job_id)
);

CREATE TABLE IF NOT EXISTS validation_reviews (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    muestra_id       INTEGER NOT NULL REFERENCES validation_samples(id) ON DELETE CASCADE,
    job_id           TEXT NOT NULL,
    veredicto        TEXT NOT NULL,
    comentario       TEXT,
    estado_previo    TEXT,
    score_previo     REAL,
    creado_en        TEXT NOT NULL,
    actualizado_en   TEXT NOT NULL,
    UNIQUE (muestra_id, job_id)
);

CREATE INDEX IF NOT EXISTS idx_validation_reviews_muestra ON validation_reviews(muestra_id);

PRAGMA user_version = 6;
