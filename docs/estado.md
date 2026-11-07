# Estado del proyecto

Fecha: 07/11/2026. Actualizado tras la sesión de búsqueda manual con progreso en
vivo.
Commit de referencia: `git log -1 --oneline`.

**No declaro el MVP terminado**: el ranking ya no miente, pero la calidad real de
las recomendaciones todavía no está validada por vos. La muestra de
`docs/muestra-validacion.md` es el paso que falta.

## 1. Perfil activo

El perfil activo lo administra la aplicación y vive fuera del repositorio:
`%LOCALAPPDATA%\BuscadorLaboral\data\perfil.json`, con semilla opcional en
`perfil.local.json`. El repositorio sólo publica un perfil de ejemplo.

Reglas que el perfil activo expresa como configuración:

- **Remoto obligatorio** (`territorio.remoto_obligatorio`): presencial fuera de
  la zona declarada es incompatible. El motivo de la restricción no se versiona.
- Habilidades ponderadas por nivel: **demostrada** (1,0), **intermedia** (0,7),
  **básica** (0,4).
- Salarios marcados `pendiente_ratificacion`.

El perfil anterior sigue guardado como versión y se puede reactivar.

## 2. Cifras

| Métrica | Antes (rules-1.1 + perfil demo) | Ahora (rules-2.0 + perfil real) |
| --- | --- | --- |
| Ofertas evaluadas | 882 | 1 229 |
| Elegibles | 3 | 3 |
| Dudosas | 31 | 8 |
| Incompatibles | 848 | 1 218 |
| Dejaron de ser relevantes | — | 24 |
| Pasaron a relevantes | — | 2 |

Las 24 que se cayeron son, una por una, los falsos positivos que reportaste:
`MEDICAL VIRTUAL ASSISTANT` (86,7), `Commercial Data Scientist` (78,7),
`Customer Support (Season Contractor)` (60), `IT Consultant - Solutions
Architect`, `Sales Representative`, `Risk&AI Manager`, entre otras. Evidencia
reproducible: `tools/comparar_reglas.py`.

Relevantes por fuente: F04 Remote OK 5 · F01 We Work Remotely 4 · F11 Remotive 1.
Las otras once fuentes no aportan ninguna oportunidad postulable hoy: responden
bien, pero su inventario es presencial, senior o restringido a EE. UU.

Confianza de la información: 1 alta, 10 media, 893 baja. Es el retrato honesto
del corpus: la mayoría de los avisos no declara habilidades, modalidad ni fecha
verificable.

## 3. Fuentes: 14

Las 11 anteriores más tres familias de tableros de empresa:

| ID | Fuente | Tableros verificados |
| --- | --- | --- |
| F12 | Greenhouse | gitlab, canonical, vercel, datadog |
| F13 | Lever | toptal, despegar (AR), fintual (CL), kavak (MX) |
| F14 | Ashby | linear, ramp, nubank (BR) |

Los tableros que devolvieron 404 (deel, automattic, supabase, remote) se
retiraron en lugar de dejarlos fallando. Cada tablero es una partición: su
rendimiento se mide por separado.

## 4. Módulo de IA

Cascada gratuita verificada contra documentación: `gemini-3.5-flash-lite` →
`3.6-flash` → `3.8-flash` → Groq `gpt-oss-20b`/`120b` → Cloudflare
`@cf/openai/gpt-oss-20b` → DeepSeek `deepseek-flash` (pago, bloqueado por
defecto). Credenciales en el Administrador de credenciales de Windows con
respaldo DPAPI. Detalle y estado comprobado en `docs/ia-proveedores.md`.

**Estado real:** la clave guardada en el Administrador de credenciales de Windows
funciona. Catálogo HTTP 200, `generateContent` HTTP 200 y los tres modelos
presentes. Hay una `GEMINI_API_KEY` en el entorno con una clave **revocada** que
quedaba por encima de la buena: la prioridad se invirtió (almacén → DPAPI →
entorno, y manda la huella que funcionó) y el diagnóstico avisa cuando conviven
dos claves distintas.

Una generación real sobre una oferta real se ejecutó con costo **USD 0**:
1 969 + 480 tokens, 4 citas verificadas, 0 inventadas. Ver
`docs/evidencia/ia-oferta-real.txt`.

## 5. Pruebas

228 superadas. `docs/evidencia/pytest.txt`. 30 comprobaciones de interfaz sobre
socket real, con una búsqueda real completa
(`tools/verificar_interfaz.py --buscar`): `docs/evidencia/interfaz.txt`.

## 4 bis. Búsqueda manual con progreso

**Ofertas → Buscar ahora** lanza la corrida existente y muestra el avance leído de
la base: fuentes pendientes/ejecutando/completadas/fallidas, nombre de la fuente en
curso, barra sobre fuentes planificadas, contadores, estado de la IA y resumen
final. Una sola corrida a la vez; cancelación cooperativa que conserva el trabajo.
Diseño y justificación de la consulta periódica (en lugar de SSE) en
`docs/busqueda-manual.md`.

## 6. Fallos corregidos en esta sesión

| Fallo | Corrección |
| --- | --- |
| Una clave válida marcada como inválida por longitud/prefijo | El formato se informa como dato; la validez la decide la API |
| «Problema de modelo o cuota» después de un `generateContent` 200 | La conclusión sólo mira catálogo y generación; 200 ⇒ funciona |
| Errores de ayer leídos como estado de hoy | `ai_model_checks` con huella; último válido separado del historial |
| YouTube/Books 401 contados como fallo de Gemini | Pruebas tipadas; los controles se muestran «no aplica» |
| Diagnóstico con `UnboundLocalError: sombra` (HTTP 500) | Resolución de candidatas antes de la conclusión, con `try/except` |
| El diagnóstico no se mostraba en la página | Se truncaban campos, no el JSON completo |
| Petición rechazada contada como cuota consumida | `probar_conexion` registra 0; migración v8 repara las filas viejas |
| Clave de Gemini en la URL de `verificar_modelos` | Cabecera `x-goog-api-key`, también en el catálogo |
| Corrida muerta bloqueaba «Buscar ahora» para siempre | Latido + candado del trabajador: se marca abandonada y se puede buscar |
| Cancelar contaba como fuente «con error» | Bucket propio `canceladas`; no es un fallo |
| El resumen decía «1 candidata» habiendo 10 | `candidatas` es el catálogo; el delta es `candidatas_nuevas` |
| Dos corridas en el mismo segundo se robaban análisis | `analyses.run_id` (v10) en lugar de comparar marcas de tiempo |
| Se veía `completed` con el resumen sin escribir | El resumen se guarda antes de cerrar la corrida |
| La variable de entorno tapaba la clave buena | Prioridad almacén primero + huella activa |
| DPAPI buscaba `CryptProtectData` en `advapi32` | Se movió a `crypt32.dll` |
| La caché de IA serializaba un objeto Pydantic | Se guarda `model_dump()` y se revalida al leer |
| Una prueba imprimió una clave real | Fixture `autouse` que aísla todo almacén de credenciales |

## 7. Límites conocidos

- Con el perfil real y reglas estrictas quedan **2 elegibles y 8 dudosas**. Es
  poco, pero es lo que hay en el corpus actual; el problema ya no es el filtro.
- 10 de las 14 fuentes no aportan nada postulable: son tableros senior o
  restringidos a EE. UU. La opción es pausarlas o buscar fuentes LATAM, que
  requieren clave (Get on Board) y quedaron fuera por falta de credencial.
- La IA funcionó sobre una oferta, pero el procesamiento masivo sigue apagado a
  propósito: falta medir cuota real antes de encolar las 882 restantes.
- No se visitó ninguna página de detalle: se analiza el texto del feed o API.

## 8. Próxima acción

1. Abrir la pestaña **Validación** y marcar los 25 veredictos. Eso convierte el
   ranking en algo medible en lugar de opinable.
2. Encender la IA sobre un lote corto (5–10 ofertas) y comparar con las reglas:
   ya hay cuota gratuita confirmada y costo 0 verificado.
3. Pulsar **Buscar ahora** desde el navegador y confirmar que la lista se actualiza
   sola mientras avanza.
4. Decidir si se pausan las fuentes de rendimiento cero.
