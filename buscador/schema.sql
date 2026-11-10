PRAGMA user_version = 11;

CREATE TABLE IF NOT EXISTS sources (
    source_id        TEXT PRIMARY KEY,
    publisher_key    TEXT NOT NULL UNIQUE,
    nombre           TEXT NOT NULL,
    url_base         TEXT NOT NULL,
    endpoint         TEXT NOT NULL,
    metodo           TEXT NOT NULL,
    autorizacion     TEXT NOT NULL,
    atribucion       TEXT,
    cuota            TEXT,
    frecuencia       TEXT,
    parser_version   TEXT NOT NULL,
    activo           INTEGER NOT NULL DEFAULT 1,
    creado_en        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_verifications (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id        TEXT NOT NULL REFERENCES sources(source_id),
    fecha            TEXT NOT NULL,
    metodo           TEXT NOT NULL,
    resultado        TEXT NOT NULL,
    notas            TEXT,
    evidencia_json   TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    causa            TEXT NOT NULL,
    estado           TEXT NOT NULL,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    run_epoch        TEXT NOT NULL UNIQUE,
    heartbeat_at     TEXT,
    notas            TEXT,
    cancelada        INTEGER NOT NULL DEFAULT 0,
    total_fuentes    INTEGER NOT NULL DEFAULT 0,
    resumen_json     TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_estado ON runs(estado, id);

CREATE TABLE IF NOT EXISTS source_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL REFERENCES runs(id),
    source_id        TEXT NOT NULL REFERENCES sources(source_id),
    estado           TEXT NOT NULL,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    http_status      INTEGER,
    observaciones    INTEGER NOT NULL DEFAULT 0,
    nuevas           INTEGER NOT NULL DEFAULT 0,
    actualizadas     INTEGER NOT NULL DEFAULT 0,
    relevantes       INTEGER NOT NULL DEFAULT 0,
    duplicadas       INTEGER NOT NULL DEFAULT 0,
    error_code       TEXT,
    error_msg        TEXT,
    cursor_previo    TEXT,
    cursor_nuevo     TEXT,
    detalle_json     TEXT
);

CREATE TABLE IF NOT EXISTS observations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id        TEXT NOT NULL REFERENCES sources(source_id),
    external_id      TEXT NOT NULL,
    url              TEXT NOT NULL,
    url_final        TEXT,
    titulo           TEXT NOT NULL,
    empresa          TEXT,
    descripcion_texto TEXT,
    publicado_en     TEXT,
    publicado_origen TEXT,
    detectado_en     TEXT NOT NULL,
    content_hash     TEXT NOT NULL,
    parser_version   TEXT NOT NULL,
    field_status_json TEXT NOT NULL,
    evidencia_json   TEXT,
    seniority        TEXT,
    skills           TEXT,
    categoria_fuente TEXT,
    UNIQUE (source_id, external_id)
);

CREATE TABLE IF NOT EXISTS observation_versions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id   INTEGER NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
    content_hash     TEXT NOT NULL,
    capturado_en     TEXT NOT NULL,
    cambios_json     TEXT,
    UNIQUE (observation_id, content_hash)
);

CREATE TABLE IF NOT EXISTS jobs (
    id               TEXT PRIMARY KEY,
    titulo           TEXT NOT NULL,
    empresa          TEXT,
    categoria        TEXT,
    modalidad        TEXT,
    territorio       TEXT,
    salario_json     TEXT,
    estado_vigencia  TEXT NOT NULL DEFAULT 'unknown',
    publicado_en     TEXT,
    primera_deteccion TEXT NOT NULL,
    ultima_deteccion TEXT NOT NULL,
    semantic_hash    TEXT NOT NULL,
    url_atribucion   TEXT,
    fuente_principal TEXT NOT NULL REFERENCES sources(source_id),
    merged_into      TEXT
);

CREATE TABLE IF NOT EXISTS job_observations (
    job_id           TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    observation_id   INTEGER NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
    tipo_match       TEXT NOT NULL,
    motivo           TEXT,
    agrupacion_version TEXT NOT NULL,
    PRIMARY KEY (job_id, observation_id)
);

CREATE TABLE IF NOT EXISTS job_versions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    semantic_hash    TEXT NOT NULL,
    titulo           TEXT NOT NULL,
    empresa          TEXT,
    requisitos_json  TEXT NOT NULL,
    salario_json     TEXT,
    vigencia         TEXT NOT NULL,
    creado_en        TEXT NOT NULL,
    UNIQUE (job_id, semantic_hash)
);

CREATE TABLE IF NOT EXISTS profile_versions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    version          TEXT NOT NULL UNIQUE,
    perfil_json      TEXT NOT NULL,
    origen           TEXT NOT NULL,
    creado_en        TEXT NOT NULL,
    activo           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS analyses (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    job_version_id   INTEGER NOT NULL REFERENCES job_versions(id),
    profile_version_id INTEGER NOT NULL REFERENCES profile_versions(id),
    rules_version    TEXT NOT NULL,
    elegibilidad     TEXT NOT NULL,
    score            REAL,
    componentes_json TEXT NOT NULL,
    razones_json     TEXT NOT NULL,
    incertidumbres_json TEXT NOT NULL,
    creado_en        TEXT NOT NULL,
    obsoleto         INTEGER NOT NULL DEFAULT 0,
    excepcion        INTEGER NOT NULL DEFAULT 0,
    confianza        TEXT,
    motivo_elegibilidad TEXT,
    run_id           INTEGER,
    UNIQUE (job_id, job_version_id, profile_version_id, rules_version)
);

CREATE INDEX IF NOT EXISTS idx_analyses_run ON analyses(run_id);

CREATE TABLE IF NOT EXISTS applications (
    job_id          TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    estado          TEXT NOT NULL DEFAULT 'postulada',
    fecha           TEXT NOT NULL,
    enlace          TEXT,
    notas           TEXT,
    creado_en       TEXT NOT NULL,
    actualizado_en  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_applications_estado ON applications(estado, fecha);

CREATE TABLE IF NOT EXISTS tasks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    kind             TEXT NOT NULL,
    unique_key       TEXT NOT NULL UNIQUE,
    job_id           TEXT,
    job_version_id   INTEGER,
    profile_version_id INTEGER,
    rules_version    TEXT,
    estado           TEXT NOT NULL,
    intentos         INTEGER NOT NULL DEFAULT 0,
    next_due         TEXT NOT NULL,
    locked_by_epoch  TEXT,
    locked_at        TEXT,
    error            TEXT,
    creado_en        TEXT NOT NULL,
    actualizado_en   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id        TEXT NOT NULL UNIQUE,
    job_id           TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    accion           TEXT NOT NULL,
    creado_en        TEXT NOT NULL,
    version_esperada TEXT,
    payload_json     TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    clave            TEXT NOT NULL UNIQUE,
    job_id           TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    canal            TEXT NOT NULL,
    estado           TEXT NOT NULL,
    payload_json     TEXT NOT NULL,
    creado_en        TEXT NOT NULL,
    leido_en         TEXT,
    entregado_en     TEXT
);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    notification_id  INTEGER NOT NULL REFERENCES notifications(id) ON DELETE CASCADE,
    intento          INTEGER NOT NULL,
    estado           TEXT NOT NULL,
    detalle          TEXT,
    creado_en        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo             TEXT NOT NULL,
    detalle_json     TEXT,
    creado_en        TEXT NOT NULL
);

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
    creado_en        TEXT NOT NULL,
    duracion_ms      INTEGER,
    cuota_consumida  INTEGER NOT NULL DEFAULT 1,
    huella_credencial TEXT
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
    creado_en        TEXT NOT NULL,
    huella_credencial TEXT
);

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

CREATE INDEX IF NOT EXISTS idx_observations_source ON observations(source_id);
CREATE INDEX IF NOT EXISTS idx_jobs_vigencia ON jobs(estado_vigencia);
CREATE INDEX IF NOT EXISTS idx_job_versions_job ON job_versions(job_id);
CREATE INDEX IF NOT EXISTS idx_analyses_job ON analyses(job_id, obsoleto);
CREATE INDEX IF NOT EXISTS idx_tasks_cola ON tasks(estado, next_due);
CREATE INDEX IF NOT EXISTS idx_notifications_estado ON notifications(estado);
CREATE INDEX IF NOT EXISTS idx_user_events_job ON user_events(job_id);
CREATE INDEX IF NOT EXISTS idx_incidents_source ON incidents(source_id, resuelto_en);
CREATE INDEX IF NOT EXISTS idx_ai_calls_periodo ON ai_calls(creado_en);
CREATE INDEX IF NOT EXISTS idx_merge_reviews_estado ON merge_reviews(estado);
CREATE INDEX IF NOT EXISTS idx_ai_queue_cola ON ai_queue(estado, next_due, prioridad);
CREATE INDEX IF NOT EXISTS idx_ai_usage_dia ON ai_usage(dia);
CREATE INDEX IF NOT EXISTS idx_ai_calls_huella ON ai_calls(huella_credencial);
CREATE INDEX IF NOT EXISTS idx_ai_checks_huella ON ai_model_checks(huella_credencial);
CREATE INDEX IF NOT EXISTS idx_ai_analyses_job ON ai_analyses(job_id);
