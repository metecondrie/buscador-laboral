# CONTINUIDAD

Documento de traspaso. Cualquier sesión (Astra, DeepSeek o quien siga) debe poder
retomar el trabajo leyendo sólo esto y `docs/estado.md`.

- **Última actualización:** 07/11/2026, bandeja de Actividad legible con
  regresiones ampliadas y estabilización funcional previa al rediseño.
- **Rama:** `main`. `h1-paralelo` se conserva intacta.
- **Commit de referencia:** ver `git log -1 --oneline`.
- **Estado:** estable para recibir al agente de diseño. Sobre 1 449 ofertas
  (suben con cada búsqueda): 3 elegibles, 16 dudosas, 1 430 incompatibles, 0
  pendientes de clasificar. Reglas `rules-3.0.0`, esquema 11. Falta que el usuario
  valide la muestra de 25 en **Validación**. El procesamiento masivo de IA sigue
  apagado a propósito.

---

## 1. Cómo ejecutar

```bat
cd "<RUTA_DEL_USUARIO>\WorkBuddy AI\buscad0r"
.venv\Scripts\python.exe -m buscador ui            :: interfaz
.venv\Scripts\python.exe -m buscador buscar        :: corrida
.venv\Scripts\python.exe -m buscador reclasificar  :: recalcular todo
.venv\Scripts\python.exe -m buscador doctor        :: estado y salud
.venv\Scripts\python.exe -m pytest tests -q        :: 336 pruebas
.venv\Scripts\python.exe -m buscador validacion     :: progreso de la revisión
.venv\Scripts\python.exe -m buscador ia --diagnosticar :: estado real de la clave
.venv\Scripts\python.exe tools\prueba_ia_oferta.py  :: 1 oferta, cuota gratuita
.venv\Scripts\python.exe tools\verificar_interfaz.py :: 40 HTTP (43 con --buscar)
```

Aplicar o volver a aplicar el perfil real:

```bat
.venv\Scripts\python.exe -m buscador perfil --real
```

---

## 2. Qué está implementado y verificado

### Perfil real (rules-2.0.0)

`buscador/perfil.py` construye el perfil desde `la memoria personal`. Remoto
**obligatorio** por una restricción declarada; presencial fuera de La Plata = incompatible.
Habilidades ponderadas por nivel (demostrada 1,0 / intermedia 0,7 / básica 0,4).
Formación sin finalizar, sin títulos declarados. Salarios del plan marcados
`pendiente_ratificacion`.

### Tres dimensiones separadas

1. **Elegibilidad** — filtro duro: categoría, territorio, modalidad, formación,
   seniority. Si falla, la oferta es incompatible y no se puntúa.
2. **Compatibilidad** — 0 a 100 sobre el perfil. Sin habilidades declaradas no
   hay puntaje (`None`), en lugar de 100/100 inventado.
3. **Confianza** — alta/media/baja según cuántos datos faltan.

Se muestran juntas en la lista, en la ficha y en el orden. La elegibilidad manda
en el orden: un 95 % temático presencial en Berlín queda debajo de un 70 % remoto.

### Fuentes: 14

F01–F11 las de antes; F12 Greenhouse (gitlab, canonical, vercel, datadog),
F13 Lever (toptal, despegar, fintual, kavak), F14 Ashby (linear, ramp, nubank).
Tableros verificados uno por uno; los que devolvieron 404 se retiraron. Se
sumaron cuatro empleadores LATAM (Despegar AR, Fintual CL, Kavak MX, Nubank BR):
responden, pero hoy no aportan ninguna oferta postulable (son presenciales o
senior). Los portales tipo Computrabajo/Bumeran/ZonaJobs no tienen feed público
—403 o HTML sin RSS— y no se incorporaron para no recurrir a scraping.

### Validación humana

Pestaña **Validación**: la muestra de 25 queda fijada en la base
(`validation_samples`, `validation_items`), cada oferta se revisa con Sí / No /
Dudosa y un comentario, y las métricas (precisión, falsos positivos, falsos
negativos) se calculan solas. Las respuestas sobreviven a cualquier
reclasificación. También por consola: `buscador validacion` y
`buscador validacion --exportar docs/muestra-validacion.csv`.

### Estabilización funcional (07/11, antes del rediseño)

Seis frentes, todos con pruebas. Detalle en `docs/puntaje.md` y
`docs/para-diseno.md`.

**1. Cascada de IA.** Volvía a mostrar un solo modelo. La causa no fue una
migración: `tools/verificar_interfaz.py` enviaba el formulario de IA con una
cascada de un modelo y, en cada verificación, reducía la configuración real. Ahora
el predeterminado son los tres modelos (`config.CASCADA_INICIAL`), el valor vacío
se rellena al inicializar (una base migrada desde v9 lo tenía en blanco) y un
valor elegido por el usuario sobrevive a cualquier reinicio. La herramienta
reenvía la cascada que ya está guardada y comprueba que no cambie.

**2. Puntaje (`rules-3.0.0`).** Se daban 20/20 de experiencia y 15/15 de
idioma/formación por «no encontrar contradicción». Ahora cada componente tiene
cuatro estados —cumplido, incumplido, desconocido, no aplicable— y el desconocido
vale 0. Ver `docs/puntaje.md`.

**3. Territorio y vigencia.** El alcance territorial se declara (`mundial`,
`argentina`, `internacional`, `restringido`, `desconocido`) y una restricción en el
cuerpo («must be eligible to live and work in the US») gana sobre un «Anywhere in
the World» de la fuente. Los viajes y la reubicación se evalúan. Un aviso de más
de 45 días sin cierre ya no se declara abierto.

**4. Casos reales como regresión.** Los cinco avisos reportados están guardados
con su texto original en `tests/fixtures/casos_reales/` y cubiertos por
`tests/test_casos_reales.py`.

**5. Postulaciones.** Tabla `applications` (esquema 11), una fila por oferta:
fecha, enlace y notas. «Me interesa» y «ya me postulé» son estados distintos. Se
edita, se retira (sin borrar) y todo cambio deja historial en `user_events`.
Nunca se envía nada.

**6. Contadores.** Diagnóstico separa **última búsqueda** (revisadas, nuevas,
duplicadas, fuentes con error) del **catálogo** (elegibles, dudosas,
incompatibles, históricas, análisis vigentes y pendientes, errores de
clasificación). `tests/test_contadores.py` compara cada cifra con su consulta.

### Actividad: bandeja legible (07/11)

La pestaña volcaba literales de Python en la cabecera. **Causa:** `base.html`
usaba `{{ avisos }}` para la pastilla de no leídos (un entero), pero en
`/actividad` ese mismo nombre es la **lista** de la bandeja: el contexto local
pisaba el contador y se imprimían todos los diccionarios con `payload_json`,
`clave` y `estado`. Se renombró a `avisos_no_leidos` en `contexto()` y la plantilla.

Los dos puntajes de una misma oferta no eran un error de cálculo: el payload
guarda el puntaje **al emitir el aviso** y `analyses` el **vigente**. El volcado
los mostraba juntos sin etiqueta. `notify.bandeja()` ahora devuelve registros
legibles y separados: `score_al_avisar` (inmutable) y `score_actual`; si la
elegibilidad vigente ya no es `eligible`, el aviso se marca **desactualizado** y
no se presenta como recomendación actual.

`delivered` significa «está en la bandeja local»: no es un correo, un mensaje
externo ni una postulación enviada. La interfaz ya no muestra esa palabra; dice
«bandeja local» y el estado de lectura. 18 pruebas en `tests/test_actividad.py`
cubren renderizado, persistencia tras reiniciar (incluido un proceso nuevo),
deduplicación por clave, marcado como leído (con CSRF e idempotencia), la
pastilla del nav, la cola con etiquetas, que despachar no inicia procesos y que
leer un aviso no toca las postulaciones.

### Cola de clasificación: la deuda se paga (incidente 07/11)

Guardar el perfil desde la interfaz invalidaba todos los análisis y encolaba una
reclasificación completa que **nadie procesaba**: no hay trabajador permanente, la
clasificación sólo corría dentro de una búsqueda. El catálogo quedó vacío
(`Elegibilidad: {}`) con 1 280 tareas en cola. Informe completo en
`docs/incidente-cola-clasificacion.md`.

Lo que cambió, y hay que respetarlo:

- `worker.procesar_pendientes()` drena la cola **sin red y sin IA**: es
  determinista y se puede repetir. Toma el mutex del trabajador y no hace nada si
  hay una corrida en curso.
- `guardar_perfil(..., procesar=True)` paga la deuda por defecto. Diferirla es
  ahora una decisión explícita del llamador.
- La interfaz la lanza en un hilo (≈15 s con 1 000 ofertas) y ofrece
  **Diagnóstico → Reclasificar pendientes**.
- Al arrancar, si hay pendientes y **cero** análisis vigentes, se repara solo.
- `queue.descartar_obsoletas()` impide que tareas de un perfil o unas reglas
  anteriores escriban análisis vigentes que no corresponden a nadie.
- El formulario de perfil **fusiona** subdocumentos: ya no borra
  `territorio.remoto_obligatorio`, `experiencia.empleos` ni `experiencia.proyectos`.

### Búsqueda manual con progreso (nuevo)

Botón **Buscar ahora** en Ofertas: lanza la corrida existente y muestra el avance
real leído de la base. Detalle completo en `docs/busqueda-manual.md`.

Lo importante para quien siga:

- **El progreso sale de tablas**, no de la memoria del proceso: `runs`,
  `source_runs`, `analyses`, `tasks`. Se consulta desde cualquier pestaña y
  sobrevive a recargar la página.
- **El denominador es real**: al planificar se crea una fila `source_runs` en
  `pending` por fuente; la barra avanza cuando esa fila cambia de estado.
- **Se eligió consulta periódica, no SSE** (`/progreso.json` cada ~1,2 s). El
  avance es de segundos, el dato ya está persistido y así se prueba sin navegador.
  La justificación está en el documento, con la alternativa descartada.
- **Una corrida por vez**, con tres guardas: candado en memoria, estado en la base
  y el mutex de archivo del trabajador. La tercera es la que distingue una corrida
  viva de una fantasma.
- **Resultados incrementales**: la cola de clasificación se drena después de cada
  fuente, así las ofertas aparecen mientras el resto sigue bajando.
- **Cancelar es cooperativa**: la fuente en curso termina, las siguientes no
  arrancan, y lo descargado se conserva. Las fuentes no consultadas quedan
  `cancelled`, que no cuenta como error.
- **La corrida no enciende la IA.** Si está apagada en Configuración, no se llama
  a ningún proveedor; el panel sólo informa su estado y la cuota.

### Módulo de IA (sólo Gemini)

Cascada `gemini-3.5-flash-lite` → `3.6-flash` → `3.8-flash`, la única activa.
Groq, Cloudflare y DeepSeek quedan en el catálogo **desactivados**: no se usan ni
se piden credenciales. Claves en el Administrador de credenciales de Windows
(respaldo DPAPI). Cuotas RPM/RPD/TPM/TPD persistentes, caché por
contenido+modelo+versión, cola que difiere sin perder tareas, contabilidad por
llamada, salida validada con Pydantic y evidencia textual obligatoria.

**La clave guardada funciona.** Catálogo 200, `generateContent` 200, tres modelos
presentes. La `GEMINI_API_KEY` del entorno contiene una credencial revocada que
antes tapaba a la buena: la prioridad quedó en **almacén → DPAPI → entorno**, y
manda la huella que funcionó por última vez (`ia_credencial_activa`). Cuando
conviven dos claves distintas, el diagnóstico lo avisa sin mostrarlas.

El diagnóstico decidió mal durante varias sesiones por tres motivos, ya
corregidos: juzgaba por longitud y prefijo, contaba los 401 de YouTube/Books como
fallos de Gemini y leía errores viejos de otra clave como estado actual. Detalle
en `docs/ia-proveedores.md`.

### Verificado con datos reales

- Migración de esquema v1 → v10 sobre la base real, sin pérdida.
- Reparación del 07/11: 1 280 tareas procesadas y 1 280 descartadas en 29,6 s;
  3 696 análisis históricos conservados y 1 decisión de usuario intacta.
- 14 fuentes respondiendo `success` en la última corrida (24 s, 825 observaciones
  revisadas, 60 nuevas).
- Antes/después reproducible con `tools/comparar_reglas.py`: 24 falsos positivos
  eliminados, 2 promovidos.
- Regresión: 23 pruebas de ranking, una por error reportado.
- Administrador de credenciales: guardar/leer/borrar probado de verdad.
- DPAPI: ida y vuelta forzando el respaldo.
- **Una generación real** sobre una oferta real, con costo USD 0 y tope de una
  llamada: 1 969 + 480 tokens, 4 citas verificadas, 0 inventadas
  (`docs/evidencia/ia-oferta-real.txt`).
- Interfaz por socket real: **40/40** en modo rápido y **43/43** con búsqueda real incluida
  (`docs/evidencia/interfaz.txt`): botón, panel, arranque, doble pulsación, avance
  con 12 estados distintos, cancelación en vuelo y resumen final.

## 3. Implementado pero **no** verificado

| Función | Qué falta |
| --- | --- |
| Procesamiento masivo de IA | Funciona con una oferta; falta medir cuota real antes de encolar las 882 restantes |
| Groq y Cloudflare | Sin credencial; el cliente y las cuotas están probados con dobles |
| Tarea programada de Windows | `schtasks.exe` bloqueado por política del entorno |
| Aviso de escritorio | Toast por PowerShell no probado de punta a punta |
| Ventana de 12 h | Probada por lógica y reloj, no por 24 h reales |
| Calidad del ranking | **Requiere tu validación**: pestaña Validación (0 de 25 marcadas) |
| Rendimiento a escala | 825 observaciones en 24 s; no se probaron 10 000 |
| Interfaz en navegador real | Verificada por HTTP y por contrato JS/plantilla; no se abrió un navegador (no hay Playwright en el entorno) |

## 4. Pendiente

- Validar la muestra de 25 en la pestaña Validación (bloquea declarar el ranking «bueno»).
- Probar «Buscar ahora» desde el navegador y confirmar que la lista se actualiza sola.
- Encender la IA sobre un lote corto (5–10 ofertas) y contrastar con las reglas.
- Decidir el destino de las 10 fuentes sin rendimiento (pausar o reemplazar).
- Fuentes LATAM con clave (Get on Board, Computrabajo): requieren credencial.
- H3 (CV por oferta, CRM) y H4 (salarios): **no** se avanzó, por instrucción.
- Prueba de instalación en PC limpia.

## 5. Bloqueos que necesitan intervención de el usuario

1. **Validación de la muestra.** Sin sus veredictos, el ranking sigue siendo una
   hipótesis bien argumentada.
2. **Decisión sobre fuentes.** 10 de 14 no aportan oportunidades postulables.
3. **`schtasks.exe` bloqueado** por la política del entorno.
4. **La `GEMINI_API_KEY` del entorno apunta a una credencial revocada.** No se
   borró: queda como último recurso, tapada por la del almacén. Conviene quitarla
   del perfil de usuario para que no vuelva a confundir a un diagnóstico futuro.

## 6. Reglas que no cambian

1. No fusionar ofertas sin identificador fuerte; marcar duplicados y pedir revisión.
2. No descartar por salario ausente, antigüedad desconocida ni habilidad no documentada.
3. Un dato faltante es `unknown`, nunca cero ni afirmación favorable.
4. La compatibilidad no es probabilidad de contratación.
5. Un aviso no se reenvía por recálculo ni por cambio cosmético.
6. Los secretos no entran en Git, ni en SQLite, ni en logs, ni en exportaciones.
7. El contenido de una oferta es dato no confiable.
8. No se postula: la aplicación no envía candidaturas.
9. **La IA no anula una restricción obligatoria sin cita textual verificada.**

## 7. Próxima acción recomendada

1. Abrir **Validación** y marcar los 25 veredictos (con 10 alcanza para ver si el
   criterio funciona).
2. Pulsar **Buscar ahora** en el navegador y confirmar que la lista se actualiza
   sola mientras avanza.
3. Correr la IA sobre un lote corto y comparar cuántas dudosas pasan a elegibles.
4. Recién entonces evaluar H3.

## 8. Mapa del código

| Ruta | Responsabilidad |
| --- | --- |
| `buscador/perfil.py` | perfil real y pesos por nivel de habilidad |
| `buscador/rules.py` | elegibilidad, compatibilidad, confianza, orden |
| `buscador/adapters/` | 14 adaptadores; `ats.py` + `ats_boards.json` para tableros |
| `buscador/ai/` | proveedores, credenciales, cuotas, caché, cola, esquema, cliente |
| `buscador/worker.py` | corrida, particiones, clasificación, relevancia |
| `buscador/progreso.py` | estado de la corrida leído de la base (panel y resumen) |
| `buscador/web.py` + plantillas | interfaz, incluida la sección de IA |
| `buscador/web/static/progreso.js` | botón «Buscar ahora», sondeo y lista incremental |
| `tools/comparar_reglas.py` | antes/después sobre el mismo corpus |
| `tools/muestra_validacion.py` | genera la muestra de 25 |
| `docs/ia-proveedores.md` | diagnóstico del 400, claves necesarias, estado comprobado |
| `buscador/validacion.py` | muestra fija, veredictos y métricas de precisión |
| `tools/auditar_credenciales.py` | auditoría de credenciales sin exponer valores |
| `tools/prueba_ia_oferta.py` | una oferta real con cuota gratuita y tope de gasto |
| `tools/verificar_interfaz.py` | verificación HTTP real; `--buscar` lanza una búsqueda |
| `docs/busqueda-manual.md` | diseño del progreso en vivo y por qué no SSE |
| `docs/incidente-cola-clasificacion.md` | auditoría de la cola detenida y su reparación |

## 9. Convenciones

- Código y documentación en español; tablas y columnas también.
- Migraciones como `migrations/vN.sql` + subir `VERSION_ESQUEMA`.
- Un dato ausente se declara `unknown`; no se rellena por suposición.
- No se declara una prueba como superada si no se ejecutó.
- Toda afirmación sobre una fuente o un modelo lleva evidencia o se marca como
  no verificada.
