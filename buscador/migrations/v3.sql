-- Migración 2 -> 3.
-- Fusiones suaves y reversibles: una oferta absorbida apunta a la que la
-- reemplaza y deja de listarse, pero sus observaciones y su historial siguen
-- intactos. `merged_into = NULL` la devuelve a la vista.

ALTER TABLE jobs ADD COLUMN merged_into TEXT;

CREATE INDEX IF NOT EXISTS idx_jobs_merged ON jobs(merged_into);

PRAGMA user_version = 3;
