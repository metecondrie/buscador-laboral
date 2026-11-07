-- Migración 4 -> 5.
-- Separa las tres dimensiones del análisis: a la compatibilidad y la
-- elegibilidad ya existentes se les agrega la confianza de la información y el
-- motivo legible de la decisión.

ALTER TABLE analyses ADD COLUMN confianza TEXT;
ALTER TABLE analyses ADD COLUMN motivo_elegibilidad TEXT;

CREATE INDEX IF NOT EXISTS idx_analyses_confianza ON analyses(confianza);

PRAGMA user_version = 5;
