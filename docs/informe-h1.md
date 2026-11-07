# Informe H1 · Buscador laboral

Fecha: 06/11/2026. Autor de la implementación: agente de IA en WorkBuddy. Aceptación: pendiente del usuario.

## 1. Qué se construyó

Un prototipo local modular con dos modos de proceso y una base SQLite:

- **Interfaz** (`python -m buscador ui`): servidor FastAPI en `127.0.0.1`, sesión por token de un solo uso, cookie HttpOnly, CSRF en cada cambio y verificación de Host.
- **Trabajador** (`python -m buscador buscar`): captura, normaliza, agrupa, clasifica y genera avisos. Puede ejecutarse con la interfaz cerrada y usa un mutex de archivo para impedir corridas simultáneas.

No hay agentes autónomos, ni llamadas de IA, ni servicios pagos.

## 2. Recorrido implementado

1. **Captura** de tres fuentes públicas: We Work Remotely (RSS), Himalayas (API con cursor) y Jobicy (API con cursor).
2. **Normalización** a un sobre común: título, empresa, texto plano, región, salario, seniority, hashes y estado de cada campo (`known`/`unknown`).
3. **Identidad**: identificador fuerte por fuente; vínculo débil por empresa y título dentro de 30 días. La agrupación guarda motivo y versión.
4. **Clasificación** por reglas: categoría, territorio, formación, seniority, idioma, habilidades y cobertura.
5. **Aviso** en bandeja local solo si la oferta es elegible, vigente, con compatibilidad ≥ 75 y cobertura ≥ 70 %.
6. **Decisión humana**: guardar, interesar, descartar y deshacer, con historial y acción idempotente.

## 3. Resultados medidos

| Métrica | Valor |
| --- | --- |
| Observaciones capturadas | 265 |
| Ofertas canónicas | 264 |
| Análisis vigentes | 263 |
| Elegibles con aviso | 1 |
| Dudosas | 4 |
| Incompatibles | 258 |
| Vínculos débiles entre fuentes | 1 |
| Duración de corrida completa (260 obs.) | 8,2 s |
| Repetición inmediata | 0 nuevas, 0 tareas, 0 avisos duplicados |

La distribución de categorías detectadas: 18 Customer Support, 4 VA/Data Entry, 2 Research Analyst, 2 Data Operations, 1 Reporting Analyst, 1 Data Scientist, 1 Data Analyst.

## 4. Lectura crítica del resultado

El sistema funciona de punta a punta, pero **la cosecha útil es pobre**: 5 ofertas no incompatibles sobre 264. Las causas son verificables:

- Los feeds generales priorizan puestos senior y ventas, no roles junior de datos.
- Muchas ofertas son explícitamente `US only` o `North America Only`.
- El filtro de seniority descarta títulos con `Senior`, `Lead` o `Manager`.
- El perfil es de demostración, así que la comparación de habilidades es aproximada.

No corresponde maquillar esto. Sirve como línea de base: cualquier mejora de H2 debe medirse contra estos números.

## 5. Decisiones de diseño y su reversión

| Decisión | Motivo | Cómo se revierte |
| --- | --- | --- |
| Reglas en lugar de IA | USD 0, resultados explicables, sin envío de datos | Agregar proveedor en T07 detrás de la puerta de permisos |
| Aviso solo en bandeja | Canal durable sin dependencias externas | Adelantar canal en H2 si la bandeja no alcanza |
| Tres páginas por fuente | Acotar P05 sin perder cursor | Subir el techo en `worker._fetch_con_paginas` |
| Perfil sintético marcado | No inventar el CV | Reemplazar `perfil.json` y subir `version` |
| Un proceso, fuentes secuenciales | Simplicidad y medición limpia | Paralelizar con el límite de tres fuentes |

## 6. Riesgos abiertos

1. **Puntajes no personalizados** mientras el perfil sea de demostración.
2. **Cobertura baja** de roles junior: el MVP de H2 exige diez fuentes y hoy hay tres.
3. **Sin respaldo**: una corrupción de la base perdería el historial.
4. **Sin programación**: la captura automática cada 12 h no existe aún.
5. **Repetición no espaciada**: falta confirmar estabilidad en 12 h.
6. **Contenido no confiable**: se muestra como texto plano y el enlace advierte el dominio, pero no hay análisis de seguridad más profundo.

## 7. Qué revisar antes de aprobar H1

1. Abrir la aplicación y recorrer las seis pestañas.
2. Marcar una oferta como interesada y comprobar que persiste tras cerrar y reabrir.
3. Revisar si el criterio de dudas y exclusiones coincide con tu forma de filtrar.
4. Decidir si el perfil de demostración se reemplaza ahora o en H2.
5. Leer `docs/pruebas.md` y `docs/estado.md`.

## 8. Siguiente etapa sugerida (no ejecutada)

H2 debería empezar por ampliar fuentes con criterio de aporte útil, no por la interfaz: T05 antes que T06. Con diez fuentes verificadas, programación real cada 12 h, respaldo y las 25 revisiones humanas, recién ahí tiene sentido hablar de MVP.
