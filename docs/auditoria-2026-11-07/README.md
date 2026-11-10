# Auditoría de oportunidades laborales — 07/11/2026

**Repositorio:** `buscad0r`, rama `main`, HEAD `a97b9b3` (sin cambios posteriores al inicio de la auditoría).
**Versión del motor:** app `0.2.0` · esquema SQLite `11` · reglas `rules-3.0.0` · perfil activo `id=4` (`perfil-20261107T034759Z`).
**Datos utilizados:** `%LOCALAPPDATA%\BuscadorLaboral\data\buscador.db`, 19 824 640 bytes, SHA-256
`3bfc231920e0124a98e947f7f4de509f81c50942269fff20fd46f3b4cf9df3ce`.
Instantánea tomada el `2026-11-07T09:38:02Z`. Última corrida registrada: `id=43`, `manual-ui`,
`2026-11-07T08:29:33Z` → `08:30:04Z`, 14 fuentes.

**Catálogo analizado:** 1 449 ofertas canónicas = 1 449 análisis vigentes;
3 elegibles, 16 dudosas, 1 430 incompatibles; 5 268 análisis históricos conservados.

**Alcance:** auditoría de solo lectura. No se modificó código, no se tocó la base operativa,
no se hicieron postulaciones ni envíos, no se consumieron APIs pagas ni se usó IA.
La única actividad de red fueron 22 solicitudes HTTP `GET` a fichas públicas de ofertas
(19 elegibles/dudosas + 3 falsos negativos), sin credenciales y con 12 s de timeout.

## Entregables

| Archivo | Contenido |
|---|---|
| `01-informe-oportunidades.md` | Las 19 ofertas analizadas, vigencia verificada y **lista priorizada** con enlaces y justificaciones |
| `02-falsos-negativos.md` | Muestra estratificada de 99 descartadas, errores sistemáticos y casos recuperados |
| `03-recomendaciones.md` | Mejoras concretas de filtros y datos (**sin modificar el clasificador**) |
| `04-evidencia.md` | Método, consultas, resultados HTTP, hashes y límites de la verificación |
| `consultas.sql` | Consultas SQL reproducibles sobre la base |
| `datos/ofertas-elegibles-dudosas.csv` | Las 19 ofertas con todos sus campos y resultado HTTP |
| `datos/muestra-incompatibles.csv` | Muestra de 99 descartadas, con estrato y señales de texto |
| `datos/verificacion-http.json` | 22 comprobaciones HTTP con estado, cierre y `validThrough` |
| `datos/hashes.json` | Hashes de la base y de cada evidencia |

## Conclusiones en una línea

De las 3 ofertas marcadas como elegibles, **solo 1 resiste el análisis** (Coalition);
otra tiene un año de antigüedad y no vuelve a aparecer en el feed (NoGigiddy) y la tercera
exige 2–4 años y turnos rotativos (Bybit). La mejor oportunidad real, **Drop Zero Digital**,
estaba entre las descartadas por un error de modalidad. Ver `01` y `02`.

## Límites honestos

- La vigencia se infiere de HTTP 200, de `validThrough` publicado por la plataforma y de la
  última vez que la fuente emitió el aviso. **Ningún empleador confirmó que el puesto siga abierto.**
- Los `validThrough` de Remotive/RemoteOK/We Work Remotely parecen generados automáticamente
  (`datePosted` + 30 o 90 días), no fijados por quien contrata.
- Dos fichas (Himalayas) devolvieron HTTP 403: sin veredicto de vigencia para esas dos.
- No se convirtieron monedas ni se inventaron equivalentes salariales: se comparan cifras
  publicadas contra la referencia del perfil (USD 10/hora, ARS 750 000 netos de referencia).
- Los informes no contienen datos personales del usuario; las restricciones se mencionan de
  forma genérica.
