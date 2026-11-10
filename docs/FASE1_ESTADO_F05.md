# Fase 1 — Estado de la fuente F05 (The Muse)

Registro documental únicamente. **En esta fase no se desactiva la fuente, no se
modifican incidentes ni se toca la base SQLite operativa.** La intervención
(circuito abierto / baja controlada / resolución de incidentes) queda reservada
para una fase posterior.

## Estado comprobado al 2026-11-09

| Aspecto | Estado | Evidencia |
|---|---|---|
| Adaptador | Presente y registrado como `F05` | `buscador/adapters/themuse.py`, `buscador/adapters/__init__.py` |
| Endpoint | `https://www.themuse.com/api/public/jobs` (API pública v1 anónima) | `themuse.py:9`, tabla `sources` |
| Particiones | 3: `datos-remoto`, `datos-inicial`, `soporte-remoto` | `themuse.py:28-35` |
| `parser_version` | `themuse-1.0.0` | `themuse.py:24` |
| `sources.activo` | **1** (activa) | copia de sólo lectura de `%LOCALAPPDATA%\BuscadorLaboral\data\buscador.db` |
| Últimas corridas | Dos con `estado=access_restricted`, `http_status=404`; antes una `partial` por `network_error`; más atrás corridas `success` | `source_runs` (copia de sólo lectura) |
| Incidentes abiertos | **2**, sin `resuelto_en`: `id=3` `access_restricted` (run 47, 2026-11-08T19:06:23Z, las 3 particiones) e `id=2` `network_error` (run 45, 2026-11-08T07:06:54Z, `soporte-remoto`) | `incidents` (copia de sólo lectura) |

La auditoría externa (`10_INFORME_ADVERSARIAL.md`, hallazgo H04) sondó el
endpoint una vez y obtuvo HTTP 404 con cuerpo HTML de Next.js/Turbopack, no un
403/429 de WAF ni un 200 con `results: []`. Concluye que la ruta pública dejó de
estar enrutada a la API. En esta fase **no se hizo ninguna petición de red**: el
estado se documenta a partir del código, del informe y de una copia de lectura
de la base, para cumplir la restricción de no usar APIs externas.

## Consecuencia operativa (sin acciones correctivas aún)

- Las corridas programadas siguen intentando las tres particiones y acumulan
  tiempo muerto y falsos incidentes abiertos.
- No se reclasificó la base operativa ni se alteró `sources`, `incidents` ni
  `source_runs`.
- La tarea 1.6 del plan de reparación (`UPDATE sources SET activo=0`, resolver
  incidentes, circuito abierto en el adaptador) **se pospone** expresamente.

## Para la fase posterior

1. Confirmar con una sola sonda controlada si el 404 persiste y si existe una
   ruta alternativa oficial.
2. Decidir entre circuito abierto en `themuse.py` o baja controlada de la fuente.
3. Recién entonces, y con respaldo, actualizar `sources` y resolver los
   incidentes abiertos.
