# Incidente: cola de clasificación detenida (07/11/2026)

Síntoma reportado: Diagnóstico mostraba **1 280 ofertas**, **1 280 tareas `queued`**
y **`Elegibilidad: {}`**. La pestaña Ofertas quedó sin resultados.

Reglas `rules-2.0.0`, esquema 10. Nada se borró ni se reinició.

## Qué pasó, en orden

| Hora (UTC) | Hecho |
|---|---|
| 03:33:06–03:33:30 | Corrida 26 (`manual-ui`) termina bien: 14/14 fuentes, 60 nuevas |
| 03:33:54 | Se guarda el **perfil v3** desde la interfaz (`perfil-20261107T033354Z`, origen `manual`) |
| 03:33:54 | `UPDATE analyses SET obsoleto=1` → **2 416 análisis invalidados de golpe** |
| 03:33:54–03:33:56 | `reclasificar_todo` encola **1 280 tareas** para el perfil v3 |
| … | Nadie procesa la cola. La aplicación queda con 0 análisis vigentes y 1 280 pendientes |
| 03:47:59 | Reparación (esta sesión) |

## Causa 1 — la deuda quedaba impaga

`worker.guardar_perfil()` hace lo correcto al invalidar: los puntajes dependen del
perfil. El problema es que **encolaba y se iba**. La cola de clasificación sólo se
drenaba dentro de `worker.correr()`, es decir, al lanzar una búsqueda.

No existe un trabajador en segundo plano: la clasificación es una etapa de la
corrida. Si se cambiaba el perfil y no se buscaba, el catálogo quedaba vacío para
siempre. Eso responde la pregunta «¿el trabajador está detenido?»: **no hay
trabajador**, y por eso nada tomaba la cola.

`POST /perfil` llamaba `guardar_perfil(...)` sin procesar nada. El comando de
consola `buscador reclasificar` sí drenaba; la interfaz no.

## Causa 2 — guardar el perfil lo degradaba

El formulario de Configuración sólo expone unos campos, pero
`_perfil_desde_formulario` **reemplazaba subdocumentos enteros**:

| Campo | Antes (v2) | Después (v3) |
|---|---|---|
| `territorio` | `remoto_obligatorio: true`, `motivo`, `acepta_hibrido_en_zona`, `fuente` | sólo `residencia`, `remoto`, `presencial` |
| `experiencia` | `detalle`, `empleos` (3), `proyectos` (3) | sólo `anios`, `nivel` |
| `idioma` | `fuente` | sin `fuente` |
| `disponibilidad` | `estado` | sin `estado` |
| `categorias` | 9 curadas | 10 (se agregó «Data Scientist») |

Perder `remoto_obligatorio` no es cosmético: es la restricción dura por una restricción declarada.
Con el perfil degradado la reclasificación daba **2 elegibles / 21 dudosas /
1 257 incompatibles**, en lugar de 3 / 8 / 1 218.

Nadie se enteró porque el guardado no avisa qué cambió.

## Causa 3 (latente) — la cola vieja escribía con el perfil viejo

Si se encolaba para el perfil A y luego se cambiaba a B sin drenar, procesar la
cola escribía análisis con `profile_version_id = A` y `obsoleto = 0`. Es decir:
**análisis vigentes de un perfil que ya no es el activo**, indistinguibles en
pantalla de los correctos.

## Causa 4 — ofertas que se quedaban sin análisis (hallada al verificar)

Al comprobar el resultado aparecieron **7 ofertas sin análisis vigente y sin
tarea pendiente**: lo peor de los dos mundos, invisibles en todas las vistas.

Secuencia: una captura invalidaba el análisis de la oferta
(`UPDATE analyses SET obsoleto=1`) y encolaba la reclasificación con
`INSERT OR IGNORE` sobre una clave que **ya existía como `completed`**. El
`INSERT` se ignoraba, así que no quedaba nada pendiente y el análisis no se
rehacía nunca. Con 1 280 ofertas capturadas en cada corrida, el hueco se abre
solo.

Corrección doble:

- `ingest._encolar_clasificacion` reencola la tarea completada **sólo si la
  oferta perdió su análisis vigente**, así una captura sin cambios no dispara
  trabajo de más.
- `worker.reclasificar_faltantes()` encola y clasifica las ofertas que estén sin
  análisis vigente. Es lo que ejecutan el botón de Diagnóstico y la
  autoreparación, así que el hueco se cierra sin depender de la próxima corrida.

## Causa 5 — dos análisis vigentes para la misma oferta

La clave única de `analyses` es
`(job_id, job_version_id, profile_version_id, rules_version)`, así que dos
versiones del mismo aviso convivían con `obsoleto = 0`. Resultado: **1 331 filas
vigentes para 1 299 ofertas**; 23 ofertas aparecían duplicadas en las listas y los
contadores sumaban de más.

`clasificar()` ahora marca obsoletos los demás análisis vigentes de la misma
oferta dentro de la misma transacción: **una oferta, un análisis vigente**. Los 32
duplicados existentes se movieron a histórico conservando el de la versión actual
del aviso (nada borrado).

## Reparación aplicada

1. **Respaldo verificado** antes de tocar nada:
   `buscador-20261107T034754Z-pre-reparacion-cola.db` (14 MB, `integrity ok`,
   SHA-256 `fd24634c…`).
2. **Perfil restaurado** desde v2 (`memoria-verificada`, con
   `remoto_obligatorio: true`) como **versión nueva (v4)**. v3 queda en el
   historial como versión inactiva: no se borró nada.
3. **Cola procesada** de forma determinista, sin red y sin IA:
   1 280 procesadas, 1 280 descartadas (eran del perfil v3, ya superado),
   29,6 s.

Resultado, con el perfil correcto:

| Métrica | Antes | Después |
|---|---|---|
| Ofertas | 1 280 | 1 280 |
| Análisis vigentes | **0** | **1 280** |
| Tareas pendientes | **1 280** | **0** |
| Elegibles / dudosas / incompatibles | — | **3 / 8 / 1 288** |
| Análisis históricos | 2 416 | **3 771** (nada borrado) |
| Decisiones del usuario | 1 | 1 |

Después de cerrar el hueco de las 7 ofertas y de normalizar las 23 ofertas que
tenían dos análisis vigentes, la invariante se cumple:
**1 299 ofertas, 1 299 analizadas, 0 pendientes, 0 sin análisis**, y
**3 + 8 + 1 288 = 1 299**.

## Correcciones de código

- **`worker.procesar_pendientes()`**: drena la cola sin consultar fuentes ni
  proveedores. Si hay una corrida en curso no hace nada (esa corrida drena al
  terminar). Toma el mutex del trabajador, recupera tareas `running` huérfanas y
  descarta las planeadas para un perfil o reglas anteriores.
- **`guardar_perfil(..., procesar=True)`**: por defecto paga la deuda en el acto.
  Un llamador sólo puede diferirla de forma explícita.
- **`POST /perfil`** usa `procesar=False` y lanza el drenaje en un hilo: con
  1 000 ofertas son ~15 s y bloquear el request congelaría la interfaz.
- **`POST /diagnostico/reclasificar`**: botón para procesar la cola a mano.
- **Autoreparación al arrancar**: si hay pendientes y **cero** análisis vigentes,
  la aplicación drena sola al abrirse. Es el estado exacto de este incidente.
- **`queue.descartar_obsoletas()`**: la cola de un perfil o unas reglas
  anteriores se marca `skipped`, no se procesa.
- **`queue.recuperar_tareas()`**: devuelve a la cola las tareas `running` de un
  proceso muerto, sin tocar las corridas.
- **`_perfil_desde_formulario()`**: fusiona subdocumentos; sólo cambia lo que el
  formulario muestra. `remoto_obligatorio`, `empleos`, `proyectos`, `fuente` y
  `estado` sobreviven a un guardado.
- **`queue.encolar(..., reencolar_si_completada=True)`** y
  **`worker.reclasificar_faltantes()`**: cierran el hueco de ofertas invalidadas
  sin trabajo pendiente.
- **Diagnóstico**: bloque de clasificación con ofertas, analizadas, pendientes,
  elegibles/dudosas/incompatibles, históricos, perfil y reglas. Se fueron los
  diccionarios en crudo (`{'queued': 1280}` y `{}`), que eran el síntoma visible.

## Por qué no fue un cambio de reglas

`sincronizar_reglas` sólo actúa si hay análisis vigentes con `rules_version`
distinta de la actual. Al momento del incidente todos los análisis eran
`rules-2.0.0` y el código también: no había nada que resincronizar. El disparador
fue la **versión de perfil**, no la de reglas. El efecto es el mismo (todo
obsoleto + reclasificación completa) y por eso se confunden.

## Pruebas de regresión

`tests/test_reclasificacion.py`, 20 pruebas:

- el formulario no borra `remoto_obligatorio`, `empleos`, `proyectos`, `fuente`,
  `estado`, ni `presencial` cuando el campo no viene;
- guardar el perfil procesa la cola y no deja pendientes;
- diferirla deja la alerta `sin_clasificaciones` y `procesar_pendientes` la cobra;
- un cambio de reglas reclasifica, deja todo en la versión nueva y **conserva** el
  historial;
- las tareas de reglas o de perfil anteriores se descartan;
- una tarea `running` de un proceso muerto se recupera;
- con una corrida en curso no se roban tareas;
- una búsqueda manual no deja tareas `queued`/`deferred`/`running`;
- el arranque repara el catálogo vacío y no toca nada si está sano;
- Diagnóstico muestra números y no diccionarios en crudo;
- una oferta invalidada se reencola aunque su tarea ya estuviera completada;
- `reclasificar_faltantes` cierra el hueco sin tareas pendientes;
- abrir la aplicación no reencola nada si no hay faltantes;
- una oferta nunca queda con dos análisis vigentes.

## Verificación

- `pytest`: **248 superadas** (228 + 20).
- Socket real: **34/34**, incluidas las comprobaciones nuevas de Diagnóstico, la
  invariante «todas las ofertas clasificadas» y que reclasificar sin pendientes
  no altera el catálogo.
- Catálogo tras la reparación: 1 299 ofertas, 1 299 analizadas, 3 elegibles ·
  8 dudosas · 1 288 incompatibles, 0 pendientes.

## Lección

Invalidar análisis es una operación con deuda. Quien invalida tiene que pagarla o
dejar constancia de que la difiere, y tiene que existir un camino que la cobre sin
depender de que el usuario lance una búsqueda. Y un guardado de perfil no puede
destruir en silencio datos que el formulario ni siquiera muestra.
