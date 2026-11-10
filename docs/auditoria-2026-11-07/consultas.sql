-- Auditoría de oportunidades · 07/11/2026
-- Repo buscad0r @ a97b9b3 · esquema 11 · rules-3.0.0
-- Solo lectura. Ejecutar con: sqlite3 "%LOCALAPPDATA%\BuscadorLaboral\data\buscador.db" < consultas.sql

-- 1. Estado del catálogo ----------------------------------------------------
SELECT 'analisis_vigentes_por_elegibilidad', elegibilidad, COUNT(*)
FROM analyses WHERE obsoleto=0 GROUP BY elegibilidad;

SELECT 'ofertas_canonicas', COUNT(*) FROM jobs WHERE merged_into IS NULL;
SELECT 'analisis_historicos', COUNT(*) FROM analyses;
SELECT 'ultima_corrida', id, causa, estado, started_at, finished_at
FROM runs ORDER BY id DESC LIMIT 1;

-- 2. Las 19 ofertas elegibles y dudosas ------------------------------------
SELECT j.id, j.titulo, j.empresa, j.url_atribucion, j.fuente_principal,
       j.territorio, j.modalidad, j.categoria, j.salario_json,
       j.estado_vigencia, j.publicado_en, j.ultima_deteccion,
       a.elegibilidad, a.score, a.confianza, a.motivo_elegibilidad
FROM jobs j JOIN analyses a ON a.job_id=j.id AND a.obsoleto=0
WHERE j.merged_into IS NULL AND a.elegibilidad IN ('eligible','doubtful')
ORDER BY CASE a.elegibilidad WHEN 'eligible' THEN 0 ELSE 1 END, a.score DESC;

-- 3. Motivos de descarte ----------------------------------------------------
SELECT motivo_elegibilidad, COUNT(*) n
FROM analyses a JOIN jobs j ON j.id=a.job_id AND a.obsoleto=0 AND j.merged_into IS NULL
WHERE a.elegibilidad='incompatible'
GROUP BY motivo_elegibilidad ORDER BY n DESC;

-- 4. Todas las descartadas carecen de puntaje y confianza -------------------
SELECT a.score IS NULL AS sin_score, a.confianza, COUNT(*) n
FROM analyses a JOIN jobs j ON j.id=a.job_id AND a.obsoleto=0 AND j.merged_into IS NULL
WHERE a.elegibilidad='incompatible' GROUP BY sin_score, a.confianza;

-- 5. Descartadas por "presencial" pese a territorio remoto -----------------
SELECT j.id, j.titulo, j.territorio, a.motivo_elegibilidad
FROM analyses a JOIN jobs j ON j.id=a.job_id AND a.obsoleto=0 AND j.merged_into IS NULL
WHERE a.elegibilidad='incompatible'
  AND a.motivo_elegibilidad LIKE 'presencial en %'
  AND (lower(j.territorio) LIKE '%worldwide%'
       OR lower(j.territorio) LIKE '%anywhere%'
       OR lower(j.territorio) LIKE '%latam%'
       OR lower(j.territorio) LIKE '%latin america%'
       OR lower(j.territorio) LIKE '%home based%'
       OR lower(a.motivo_elegibilidad) LIKE '%latam%');

-- 6. Texto de una observación (para verificar "remote" más allá de 4000) ---
SELECT j.titulo, length(o.descripcion_texto) AS caracteres,
       substr(o.descripcion_texto, 1, 4000) AS primeros_4000
FROM observations o
JOIN job_observations jo ON jo.observation_id=o.id
JOIN jobs j ON j.id=jo.job_id
WHERE j.id = 'job_00fb5037fd1c930c360d'
ORDER BY o.id DESC LIMIT 1;

-- 7. Ofertas con Argentina declarada que fueron descartadas ----------------
SELECT j.id, j.titulo, j.territorio, a.motivo_elegibilidad
FROM analyses a JOIN jobs j ON j.id=a.job_id AND a.obsoleto=0 AND j.merged_into IS NULL
WHERE a.elegibilidad='incompatible' AND lower(j.territorio) LIKE '%argentina%';

-- 8. Frescura: vistas en la última corrida ---------------------------------
SELECT j.ultima_deteccion >= (SELECT started_at FROM runs ORDER BY id DESC LIMIT 1) AS vista,
       COUNT(*) n
FROM jobs j JOIN analyses a ON a.job_id=j.id AND a.obsoleto=0 AND j.merged_into IS NULL
WHERE a.elegibilidad IN ('eligible','doubtful') GROUP BY vista;

-- 9. Calidad del salario publicado -----------------------------------------
SELECT j.titulo, j.salario_json FROM jobs j
WHERE j.merged_into IS NULL AND j.salario_json IS NOT NULL;
