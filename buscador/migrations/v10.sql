-- v10: cada análisis recuerda en qué corrida se escribió.
--
-- El delta de una búsqueda («cuántas elegibles aparecieron ahora») se calculaba
-- comparando `creado_en` con `runs.started_at`. Ambas marcas tienen precisión de
-- segundos, así que dos corridas dentro del mismo segundo se atribuían los
-- análisis de la anterior y el resumen informaba candidatas de más.
--
-- Con `run_id` el delta es exacto: es la misma fila de `analyses` la que se
-- reescribe (ON CONFLICT), así que también cuenta bien la reclasificación de una
-- oferta que ya existía.
ALTER TABLE analyses ADD COLUMN run_id INTEGER;

CREATE INDEX IF NOT EXISTS idx_analyses_run ON analyses(run_id);

PRAGMA user_version = 10;
