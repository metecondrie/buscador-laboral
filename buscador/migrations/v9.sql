-- v9: estado de corrida consultable desde cualquier pestaña.
--
-- La búsqueda manual necesita que el progreso salga de la base y no de la
-- memoria del proceso: así se recupera tras recargar la página, se consulta
-- desde cualquier pestaña y sobrevive a un reinicio del servidor.
--
-- - `cancelada`: bandera que el trabajador consulta entre fuentes. Cancelar no
--   interrumpe una descarga en curso ni borra lo ya ingerido.
-- - `total_fuentes`: denominador real de la barra de progreso, fijado al
--   planificar la corrida.
-- - `resumen_json`: resumen final (duración, fuentes, errores, nuevas,
--   candidatas) para poder mostrarlo después de cerrar la página.
ALTER TABLE runs ADD COLUMN cancelada INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN total_fuentes INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN resumen_json TEXT;

CREATE INDEX IF NOT EXISTS idx_runs_estado ON runs(estado, id);

PRAGMA user_version = 9;
