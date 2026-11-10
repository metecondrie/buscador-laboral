# 4. Evidencias verificables — 07/11/2026

> Repo `buscad0r @ a97b9b3` (main) · esquema 11 · `rules-3.0.0` · app 0.2.0.
> Instantánea: `2026-11-07T09:38:02+00:00`. Solo lectura de la base operativa.

## Identificación de los datos

| Campo | Valor |
|---|---|
| Base SQLite | `%LOCALAPPDATA%\BuscadorLaboral\data\buscador.db` |
| Tamaño | 19,824,640 bytes |
| SHA-256 de la base | `3bfc231920e0124a98e947f7f4de509f81c50942269fff20fd46f3b4cf9df3ce` |
| Perfil activo | `id=4`, `perfil-20261107T034759Z`, origen `memoria-verificada` |
| Última corrida | `id=43`, `manual-ui`, 2026-11-07T08:29:33Z → 08:30:04Z |
| Catálogo | 1 449 ofertas canónicas · 3 elegibles · 16 dudosas · 1 430 incompatibles · 5 268 análisis históricos |

**Criterios del perfil usados** (sin datos personales): nivel junior / 1 año, inglés B2,
español nativo, residencia Argentina, **remoto obligatorio**, categorías
Data/Business/BI/Reporting/SQL Analyst, Data Operations, Research, VA/Data Entry y Customer
Support; referencia salarial ARS 750 000 netos, objetivo ARS 900 000, USD 10/hora freelance.

## Método

1. Consultas SQL de solo lectura (`consultas.sql`) sobre la base indicada. No se ejecutó
   `INSERT`, `UPDATE` ni `DELETE`; no se crearon respaldos ni se modificó el esquema.
2. Extracción de las 19 ofertas elegibles/dudosas y del texto completo de su observación más
   reciente para leer requisitos, remuneración, ubicación, modalidad e idioma.
3. Muestra estratificada de **99** ofertas descartadas (9 estratos), con señales de
   texto computadas sobre el aviso completo y sobre sus primeros 4 000 caracteres.
4. Verificación de vigencia: **22 peticiones HTTP `GET`** a fichas públicas, sin credenciales,
   `User-Agent` neutro, 12 s de timeout, lectura máxima de 120 kB por respuesta. Se buscaron
   marcadores de cierre, señales de postulación y el campo `validThrough` de JSON-LD.
   No se ejecutaron búsquedas masivas ni se consultaron APIs de pago.
5. No se usó IA, no se enviaron mensajes ni postulaciones, no se modificó código.

## Resultado de las 22 comprobaciones HTTP

| Oferta | Empresa | HTTP | Cerrado | `validThrough` | Vista última corrida | Nota |
|---|---|---:|---|---|---|---|
| Remote Office Assistant | Coalition Technologi | 200 | no | 2026-11-11T20:17:27+00:00 | True | — |
| Remote Data Entry Clerk | NoGigiddy | 200 | no | 2026-12-06 00:58:24 UTC | False | — |
| Client Service Analyst - P2P | Bybit | 200 | no | 2026-11-30 07:31:02 UTC | False | — |
| Sales Operations Analyst | Calabrio | 200 | no | 2027-02-01T16:00:05+00:00 | True | — |
| Technical Support Engineer, Triage | Alloy | 200 | no | 2026-11-30 07:31:02 UTC | True | — |
| Strategy & Operations Analyst - Ge | Pennylane De | 200 | no | 2026-12-18T19:40:13+01:00 | False | — |
| Customer Support Specialist | MarketFully | 403 | no | — | True | bloqueado por el sitio; sin  |
| Financial Analyst | Canonical | 200 | no | — | True | — |
| MEDICAL VIRTUAL ASSISTANT | Vital Virtuals Globa | 200 | no | 2026-12-06 04:12:16 UTC | True | — |
| MSP Mac Help Desk Guru (work from  | Ignition, Inc. | 200 | no | 2026-11-26 03:42:29 UTC | False | — |
| Scaled Customer Success Manager | Dropbox | 200 | no | 2026-12-05 22:42:07 UTC | False | — |
| Sanctions Operations Analyst (1 ye | Binance | 200 | no | — | True | — |
| US Remote Patient Care Advocate (C | VXI Global Solutions | 200 | no | 2026-12-04 18:30:56 UTC | True | — |
| Bilingual Back-Office Insurance &  | Go Lean Health | 403 | no | — | False | bloqueado por el sitio; sin  |
| Partner Operations Manager | Mecka | 200 | no | 2027-01-30T00:00:08+00:00 | True | — |
| Client Support & Travel Booking On | Destination Careers | 200 | no | 2027-01-28T00:00:03+00:00 | True | — |
| Customer Success Associate | Voltus | 200 | no | 2027-01-14T00:00:43+00:00 | True | — |
| Customer Support Specialist | Ultimate Marketing | 200 | no | 2027-01-12T01:31:49+00:00 | True | — |
| Technical Customer Support | QuickMail | 200 | no | 2027-01-10T16:20:10+00:00 | True | — |
| Operations Associate (Hiring or Cl | Drop Zero Digital | 200 | no | 2026-12-06 04:12:16 UTC | n/d | consulta adicional |
| UGC Coordinator | Elavate | 200 | no | 2026-12-06 17:00:25 UTC | n/d | consulta adicional |
| Deployment Strategist - Argentina | Elevenlabs | 200 | no | — | n/d | consulta adicional |

Resumen: 19 fichas de elegibles/dudosas → **17 HTTP 200, 2 HTTP 403, 0 marcadores de cierre**.
Las 3 consultas adicionales sobre falsos negativos devolvieron 200.
Dos dominios (Himalayas) bloquean agentes automatizados: **sin veredicto** para MarketFully y
Go Lean Health. Los `validThrough` publicados son generados por la plataforma
(Remotive ≈ `datePosted + 31 días`, RemoteOK ≈ `+ 90 días`) y **no constituyen confirmación del
empleador**. Contradicción detectada: NoGigiddy declara `datePosted = 2025-11-11` en JSON-LD
mientras la página muestra "Posted 1 day ago".

## Evidencias generadas

| Archivo | SHA-256 |
|---|---|
| `datos/ofertas-elegibles-dudosas.csv` | `7ced92e9e00a63393386962a83de92d42a769e3913c3fb9bf9b4b1f8ad34e87c` |
| `datos/muestra-incompatibles.csv` | `67bba9644942b561cd73564cec2eb256f6806de7d789e5f75eb07e4b3984e96f` |
| `datos/verificacion-http.json` | `3fc1d6648d59c18d65e91b0a60aaed200436c8617dbc6f6021ca6daea996f64d` |

- `ofertas-elegibles-dudosas.csv`: 19 filas, 21 columnas (id, título, empresa, URL,
  fuente, territorio, modalidad, categoría, elegibilidad, puntaje, confianza, motivo, salario
  publicado, fechas, última detección, vigencia y resultado HTTP).
- `muestra-incompatibles.csv`: 99 filas, 15 columnas; incluye el estrato y las señales
  `senial_remote_total` / `senial_remote_primeros_4000`.
- `verificacion-http.json`: 22 resultados con estado, URL final, marcador de cierre, señal de
  postulación y `validThrough`.
- `consultas.sql`: las 9 consultas usadas, ejecutables con `sqlite3` sobre la misma base.
- `hashes.json`: metadatos y hashes.

## Cómo reproducir

```bat
cd "%RAIZ_DEL_PROYECTO%"
.venv\Scripts\python.exe -m buscador doctor
sqlite3 "%LOCALAPPDATA%\BuscadorLaboral\data\buscador.db" < docs\auditoria-2026-11-07\consultas.sql
```

Para repetir la comprobación HTTP, reutilizar las URL de
`datos/ofertas-elegibles-dudosas.csv` (columna `url`). La huella de la base cambiará con cada
corrida nueva; por eso se registra el instante de la instantánea.

## Límites y advertencias

- **Vigencia:** HTTP 200 y `validThrough` futuro prueban que la página existe, no que el puesto
  siga abierto. La señal más confiable disponible es `ultima_deteccion` frente a la última corrida.
- **Bloqueos:** 2 fichas devolvieron 403; no se intentó evadir el bloqueo ni usar proxies.
- **Texto:** se usó la observación más reciente de cada oferta; si una fuente actualizó el aviso
  después de la instantánea, el texto puede diferir.
- **Salario:** no se normalizaron monedas ni períodos; se citan las cifras publicadas. El dato
  estructurado `salario_json` no siempre proviene del texto del aviso (caso Coalition).
- **Perfil:** no se exponen datos personales ni la restricción de salud en este informe; se usa
  "remoto obligatorio" y "sin traslados" de forma genérica.
- **Alcance:** la auditoría no corrige ni reclasifica ninguna oferta. Las propuestas de
  `03-recomendaciones.md` quedan para una decisión posterior.
