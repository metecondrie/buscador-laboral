-- Migración 6 -> 7.
-- Cada intento de IA queda asociado a la huella de la credencial usada, para
-- separar el último resultado válido de los errores históricos de otra clave.

ALTER TABLE ai_calls ADD COLUMN huella_credencial TEXT;
ALTER TABLE ai_model_checks ADD COLUMN huella_credencial TEXT;

CREATE INDEX IF NOT EXISTS idx_ai_calls_huella ON ai_calls(huella_credencial);
CREATE INDEX IF NOT EXISTS idx_ai_checks_huella ON ai_model_checks(huella_credencial);

PRAGMA user_version = 7;
