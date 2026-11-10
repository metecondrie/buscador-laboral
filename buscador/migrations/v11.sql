-- v11: seguimiento de postulaciones reales.
--
-- «Me interesa» es una intención; «me postulé» es un hecho con fecha, enlace y
-- notas. Van separados a propósito: guardar una oferta no significa haber
-- enviado nada, y la aplicación **nunca** envía postulaciones.
--
-- Una fila por oferta (`job_id` es la clave): registrar dos veces la misma
-- postulación actualiza la que existe en lugar de duplicarla. El historial de
-- cambios vive en `user_events`, que ya es append-only.
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

PRAGMA user_version = 11;
