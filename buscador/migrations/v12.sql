-- v12: conserva vencimiento, modalidad estructurada y corrida de captura.
ALTER TABLE observations ADD COLUMN expira_en TEXT;
ALTER TABLE observations ADD COLUMN modalidad_json TEXT;
ALTER TABLE observations ADD COLUMN corrida_id INTEGER REFERENCES runs(id);

CREATE INDEX IF NOT EXISTS idx_observations_corrida ON observations(corrida_id);

PRAGMA user_version = 12;
