# Proveedores de IA: estado comprobado

Verificado el 2026-11-06 contra la documentación oficial y, cuando hubo
credencial, contra la API real. **Nada de esta tabla es una suposición.**

## Diagnóstico del HTTP 400 de Gemini (06/11/2026, 21:15)

La clave `GEMINI_API_KEY` del entorno existe, pero Google la rechaza. La prueba
se hizo sobre cinco endpoints, sin gastar cuota de generación:

| Prueba | Resultado |
|---|---|
| `GET /v1beta/models?key=…` | 400 · `INVALID_ARGUMENT` · `API_KEY_INVALID` |
| `GET /v1/models?key=…` | 400 · `INVALID_ARGUMENT` · `API_KEY_INVALID` |
| `GET /v1beta/models` con `x-goog-api-key` | 400 · `INVALID_ARGUMENT` · `API_KEY_INVALID` |
| `POST /v1beta/models/gemini-3.5-flash-lite:generateContent` | 400 · `API_KEY_INVALID` |
| `GET youtube/v3` (servicio ajeno) | 400 |
| `GET books/v1` (servicio ajeno) | 400 |

Estructura de la clave: 39 caracteres, prefijo `AIza`, sólo ASCII, sin espacios
ni caracteres invisibles. Huella `d47bcf310e` (no se expone la clave).

**Conclusión:** no es el modelo, ni el endpoint, ni el formato de la solicitud,
ni una restricción de proyecto. La clave **no existe** para Google: fue
revocada, borrada o nunca llegó a generarse. Un servicio ajeno a Gemini también
la rechaza, lo que descarta una restricción por API. **Ningún cambio de código
la arregla**: hay que generar una nueva en <https://aistudio.google.com/apikey>.

Reproducible con:

```bat
.venv\Scripts\python.exe -m buscador ia --diagnosticar
```

Cuando la clave sea válida, ese mismo comando informa los modelos disponibles
para el proyecto y contrasta los tres identificadores configurados.

## Auditoría de credenciales (06/11/2026, 21:35)

Se revisaron **todas** las ubicaciones posibles antes de concluir que hace falta
una clave nueva. Evidencia completa en `docs/evidencia/auditoria-credenciales.txt`.

| Ubicación | Resultado |
|---|---|
| Variable de entorno del **proceso** | presente · 39 car. · huella `d47bcf310e31` |
| Variable de entorno del **usuario** (`HKCU\Environment`) | **la misma** · huella `d47bcf310e31` |
| Variable de entorno del **sistema** (`HKLM\…\Environment`) | ausente |
| Administrador de credenciales (`BuscadorLaboral/*`) | sin entradas del buscador |
| Administrador de credenciales (cualquier entrada con clave `AIza…`) | ninguna |
| Almacén DPAPI (`%LOCALAPPDATA%\BuscadorLaboral\credenciales`) | la carpeta no existe |
| Archivos del proyecto y de datos | ninguna clave |
| Configuraciones de CLI de Google (`~/.gemini`, gcloud) | la misma clave, en registros de sesión del agente |

**Hay una sola clave.** El proceso la hereda de la del usuario: no son dos
claves distintas, es la misma huella. No hay ninguna alternativa guardada, así
que no hay selección de credenciales que corregir.

### De dónde lee la clave la aplicación

Orden exacto en `buscador/ai/credenciales.py`:

1. **Variable de entorno** del proceso (`GEMINI_API_KEY`). Tiene prioridad porque
   permite probar sin tocar el sistema.
2. **Administrador de credenciales de Windows**, objetivo `BuscadorLaboral/gemini`.
   Es donde escribe la interfaz cuando cargás una clave.
3. **Archivo DPAPI** en `%LOCALAPPDATA%\BuscadorLaboral\credenciales\gemini.bin`,
   sólo si el Administrador de credenciales no está disponible.

La interfaz muestra siempre el **origen** junto al estado, para que no haya duda
de cuál se está usando. Antes de esta sesión, una clave cargada desde la interfaz
podía quedar tapada por una variable de entorno vieja; ahora el origen es visible
y el diagnóstico lo informa.

### Verificación de cada huella

Las cinco pruebas se hicieron **por cabecera** (`x-goog-api-key`), no por query
string, y sin consumir cuota de generación:

| Prueba | Resultado |
|---|---|
| `GET /v1beta/models` | 400 · `API_KEY_INVALID` |
| `GET /v1/models` | 400 · `API_KEY_INVALID` |
| `POST generateContent` (`gemini-3.5-flash-lite`) | 400 · `API_KEY_INVALID` |
| `GET youtube/v3` (servicio ajeno) | 400 · `API_KEY_INVALID` · «API Key not found» |
| `GET books/v1` (servicio ajeno) | 400 · `API_KEY_INVALID` · «API Key not found» |

Google dice literalmente **«API Key not found»** en dos servicios que no tienen
relación con Gemini. Eso descarta que sea la API deshabilitada, una restricción
de la clave o del proyecto: **la clave no existe** en los registros de Google.

### Dos correcciones de seguridad que salieron de la auditoría

1. **La clave ya no viaja en la URL.** Gemini acepta `x-goog-api-key`; se cambió
   el cliente y el diagnóstico. Antes, un error de red podía arrastrar
   `?key=…` a un mensaje guardado.
2. **Redacción antes de persistir.** Todo texto que va a `ai_calls.error` pasa por
   `redactar()`, que reemplaza cualquier credencial por `[CLAVE-REDACTADA]`.
   Verificado con prueba: la base y los registros propios tienen **0 claves**.

### Trampa detectada: la variable de entorno tapa la clave guardada

La prioridad actual (entorno primero) tiene un riesgo concreto: si cargás la clave
nueva desde Configuración y la variable `GEMINI_API_KEY` vieja sigue existiendo,
**la aplicación seguiría usando la vieja** y volvería a fallar sin explicación.

Ya está cubierto: `credenciales.candidatas()` y `hay_sombra()` detectan dos claves
distintas y el diagnóstico lo informa con las dos huellas, sin mostrar valores:

> «hay 2 claves distintas: se usa variable-entorno (…abc123) y queda tapada
> credenciales-windows (…def456)»

Antes de cargar la clave nueva, borrá la variable vieja:

```bat
reg delete HKCU\Environment /v GEMINI_API_KEY /f
```

o desde Configuración del sistema → Variables de entorno. Después reiniciá la
consola para que el proceso deje de heredarla.

### Higiene: la clave está en registros de sesión del agente

La misma huella aparece en texto plano en archivos de
`%USERPROFILE%\.gemini\antigravity\brain\…` (registros de la sesión del
asistente, no de esta aplicación). La aplicación no la escribe ahí. Es un motivo
más para revocar esta clave cuando se genere la nueva, y para no pegarla en el
chat: cargala directamente en **Configuración → IA**, que la guarda en el
Administrador de credenciales.

## Modelos y cascada

**Activo ahora: sólo Gemini.** Groq, Cloudflare y DeepSeek siguen en el catálogo
con su código y su configuración, pero desactivados: no se usan ni se piden
credenciales para ellos hasta que Gemini no alcance.

| # | Proveedor | Modelo exacto | Nivel | Cuota gratuita | Estado |
|---|---|---|---|---|---|
| 1 | Google Gemini | `gemini-3.5-flash-lite` | rápido | sí (nivel Free de AI Studio) | **activo** · verificado · generó | 
| 2 | Google Gemini | `gemini-3.6-flash` | equilibrado | sí | **activo** · presente en catálogo | 
| 3 | Google Gemini | `gemini-3.8-flash` | profundo | sí | **activo** · presente en catálogo | 
| — | Groq | `openai/gpt-oss-20b`, `-120b` | rápido/equilibrado | sí: 30 RPM · 1.000 RPD · 8K TPM · 200K TPD | conservado, **desactivado** |
| — | Cloudflare Workers AI | `@cf/openai/gpt-oss-20b` | rápido | sí: 10.000 neuronas/día | conservado, **desactivado** |
| — | DeepSeek | `deepseek-flash` | profundo | **no**: sólo pago | conservado, **desactivado** |

Fuentes:

- Gemini: <https://ai.google.dev/gemini-api/docs/models> y `/rate-limits`.
  `gemini-2.5-flash` y `gemini-2.5-pro` figuran **deprecados**; se retiraron de
  las opciones por defecto. `gemini-3.1-pro-preview` es preview: no se usa.
- Groq: <https://console.groq.com/docs/rate-limits> (tabla «Free Plan Limits»).
- Cloudflare: <https://developers.cloudflare.com/workers-ai/platform/pricing/>.
  Los modelos que exigen tarjeta son otra lista; `@cf/openai/gpt-oss-*` no está
  entre ellos.
- DeepSeek: <https://api-docs.deepseek.com/quick_start/pricing>. Precio de hora
  pico USD 0,30 entrada / 1,20 salida por millón; fuera de pico, la mitad.

### Lo que la documentación no fija

Los topes exactos de Gemini dependen del **proyecto**, no del modelo: el número
sale de AI Studio. En el catálogo quedaron como valores conservadores
configurables (`ia_limite_gemini_rpm` y compañía), no como verdad. Si el
proveedor devuelve 429, la aplicación obedece el `retry-after` y difiere.

## Claves

Ahora sólo hace falta **una**: `GEMINI_API_KEY`, desde
<https://aistudio.google.com/apikey>. Ya hay una cargada y funcionando en el
Administrador de credenciales. La que está en la variable de entorno es una
credencial revocada: queda tapada y conviene quitarla del perfil. Las demás
quedan documentadas para cuando se consideren, pero **no se piden ahora**:

| Proveedor | Variable | Dónde se obtiene | ¿Gratis? | Uso |
|---|---|---|---|---|
| Gemini | `GEMINI_API_KEY` | <https://aistudio.google.com/apikey> | sí, nivel Free | **el único activo** |
| Groq | `GROQ_API_KEY` | <https://console.groq.com/keys> | sí, sin tarjeta | desactivado |
| Cloudflare | `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` | panel de Workers AI | sí, 10.000 neuronas/día | desactivado |
| DeepSeek | `DEEPSEEK_API_KEY` | <https://platform.deepseek.com> | **no**, requiere saldo | desactivado, último recurso |

Cloudflare necesita además el identificador de cuenta (32 caracteres hex), que
se guarda en Configuración, no es secreto pero sí necesario.

## Cómo configurarlas

Por interfaz (recomendado):

1. Abrir la aplicación → **Configuración** → sección *Inteligencia artificial*.
2. En **Credenciales**, escribir la clave en la columna *Registrar* y pulsar
   **Guardar**. Se almacena en el Administrador de credenciales de Windows con el
   objetivo `BuscadorLaboral/<proveedor>`; si no está disponible, se cifra con
   DPAPI en `%LOCALAPPDATA%\BuscadorLaboral\credenciales\`.
3. Pulsar **Verificar**: consulta el catálogo del proveedor y contrasta los
   identificadores. **No consume cuota de generación.**
4. Pulsar **Probar** sólo cuando quieras confirmar una llamada real: **consume
   una petición** de la cuota. El botón lo advierte.
5. Marcar *Permitir enviar el texto de las ofertas* y pulsar **Habilitar IA**.

Por consola, sin interfaz:

```bat
setx GEMINI_API_KEY "tu-clave"        :: queda en el entorno del usuario
.venv\Scripts\python.exe -m buscador ia --verificar gemini
.venv\Scripts\python.exe -m buscador ia --probar gemini:gemini-3.5-flash-lite
```

La prioridad es **almacén → DPAPI → variable de entorno**, y la huella que
funcionó por última vez (`ia_credencial_activa`) manda sobre las tres. Una
variable de entorno vieja ya no puede tapar la clave cargada desde Configuración;
si conviven dos claves distintas, el diagnóstico lo avisa.

## Estado comprobado en esta máquina

| Integración | Estado | Evidencia |
|---|---|---|
| Administrador de credenciales de Windows | **funciona** | guardar/leer/borrar con objetivo temporal; se recuperó el mismo valor y se borró |
| Respaldo DPAPI | **funciona** | ida y vuelta forzando el respaldo (corrige que DPAPI vive en `crypt32.dll`) |
| Catálogo de modelos en código | **verificado contra documentación** | 8 modelos, 4 proveedores |
| Clave guardada (53 car., huella `475ffac78c3a`) | **funciona** | catálogo 200, generación 200, 3 modelos presentes |
| `GEMINI_API_KEY` del entorno (39 car., huella `d47bcf310e31`) | **inválida y tapada** | `API_KEY_INVALID`; queda por debajo de la guardada |
| Cascada Gemini (3 modelos) | **ejecutada** | `gemini-3.5-flash-lite` respondió 200 sobre una oferta real |
| Groq | **sin credencial** | falta `GROQ_API_KEY` |
| Cloudflare | **sin credencial** | faltan token y cuenta |
| DeepSeek | **sin credencial y sin autorización de gasto** | bloqueado por diseño |
| Llamada real de generación | **ejecutada: 1** | ver «Prueba sobre una oferta real» |

La clave del entorno corresponde a una credencial revocada. No se borró: sigue
disponible como último recurso y el diagnóstico informa que está tapada.

### Formato de la clave: dato, no veredicto

La clave que funciona **no** empieza con `AIza` ni mide 39 caracteres. El
diagnóstico informa `formato_conocido: no` y aclara que el formato no determina
la validez: la decide la API. Antes, una comprobación de longitud marcaba como
inválida una clave que respondía 200.

### Prueba sobre una oferta real (07/11/2026)

`tools/prueba_ia_oferta.py` ejecuta el circuito completo sobre **una sola oferta**
y aborta si la corrida puede generar gasto. Salida en
`docs/evidencia/ia-oferta-real.txt`.

| Dato | Valor |
|---|---|
| Oferta | Consumer Support Specialist · Keeper Security · `job_58104e44cfaa6d7e408e` |
| Modelo | `gemini-3.5-flash-lite` (gratuito, USD 0 por 1M tokens) |
| Tokens | 1 969 entrada · 480 salida |
| Costo | **USD 0.00** |
| Duración | 4 926 ms |
| Evidencia citada | 4 válidas · 0 no verificadas |
| Confianza | 0.95 |

Lo que aportó la IA: el motor de reglas había dejado la oferta en *dudosa* por
«bachelor's degree preferred». El análisis encontró una restricción más dura que
la que motivaba la duda —el aviso limita la residencia a husos horarios de
Estados Unidos— y la marcó como territorialmente restringida. Es exactamente el
uso previsto: segunda opinión que **agrega** información, no que anula reglas.

La segunda corrida sobre la misma oferta la resolvió la caché (`cache / cache`,
USD 0, sin petición nueva), así que el total consumido fue **una** generación.

## Controles de costo

- Presupuesto mensual por defecto: **USD 0**. Con los modelos gratuitos el costo
  por llamada es 0, así que el tope no se toca; si se habilita DeepSeek, el tope
  en 0 **bloquea** la llamada.
- Un proveedor de pago requiere dos cosas: estar en la cascada y tener marcada la
  autorización de gasto (`ia_autorizo_pago`). Un saldo disponible no autoriza.
- Cuota por corrida (`ia_llamadas_por_corrida`, por defecto 20).
- Ventanas RPM/RPD/TPM/TPD persistidas en `ai_usage`; al agotarse, la cola se
  suspende y las ofertas quedan pendientes, no perdidas.
- Caché por hash de contenido + modelo + versión del prompt: el mismo aviso no se
  paga dos veces.

## Diagnóstico: qué decide el estado

El diagnóstico hace cinco peticiones, pero **sólo dos deciden**:

| Prueba | Tipo | ¿Decide? |
|---|---|---|
| Catálogo `v1beta/models` | `catalogo` | sí |
| Catálogo `v1/models` | `catalogo_alterno` | sí |
| `generateContent` con 1 token | `generacion` | sí |
| YouTube Data API | `control` | **no** — «no aplica» |
| Books API | `control` | **no** — «no aplica» |

Google ya no acepta claves de API en YouTube ni en Books: esos endpoints
devuelven 401 aunque la clave sea perfecta. Contarlos como fallo hacía que un
diagnóstico correcto pareciera roto. Se muestran igual, con la nota
«no aplica: Google exige OAuth en este servicio».

Reglas de conclusión:

- **Generación 200 ⇒ funciona.** No se sugieren problemas de modelo ni de cuota;
  si el catálogo falló se dice que sólo falló el listado.
- Catálogo 200 + generación 429 ⇒ **cuota**, no clave inválida.
- `API_KEY_INVALID` ⇒ **inválida** (revocada, borrada o nunca emitida).
- El formato y la longitud nunca cambian el estado.

### Último válido vs. errores históricos

`ai_model_checks` guarda el estado y la **huella** de la credencial de cada
corrida. La pantalla separa:

- el **último resultado válido** (estado, fecha, huella);
- los estados agrupados por `(estado, huella)`, marcando cuál es la credencial
  actual;
- un contador de **errores que pertenecen a otra clave**.

Así un 400 de una clave revocada de ayer no se lee como el estado de hoy. La
huella se calcula con SHA-256 y se muestran 12 caracteres; el valor nunca se
guarda ni se imprime.

### Registro de consumo: generación vs. intento

`ai_calls` distingue las dos cosas y `consumo()` las informa por separado:

| Columna | Significado |
|---|---|
| `estado = 'ok'` | generación válida; suma a `solicitudes_exitosas` |
| `estado` en `error`/`invalida` | intento; suma a `intentos_fallidos` |
| `cuota_consumida` | 1 sólo si la API aceptó y generó tokens |
| `huella_credencial` | qué clave produjo la fila |

Corrección de la migración **v8**: `probar_conexion` marcaba `cuota_consumida = 1`
incluso cuando la API respondía 400/401/403. Una petición rechazada no genera
tokens ni consume cuota, y el error quedaba contado como si el modelo hubiera
respondido. Ahora se registra en 0, y la migración reparó las filas viejas sin
tokens en estado de error; una respuesta que sí gastó tokens no se toca.

## Qué NO hace la IA

- No decide elegibilidad. El territorio, la modalidad y el seniority siguen
  mandando por reglas deterministas.
- No puede anular una restricción obligatoria sin una cita textual verificada
  contra el aviso (`evidencia` se contrasta y se cuenta aparte si no aparece).
- No se ejecuta si el rastreador falla: son caminos independientes.
