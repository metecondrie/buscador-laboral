# CONTINUIDAD

Documento de traspaso. Cualquier sesión (Astra, DeepSeek o quien siga) debe poder
retomar el trabajo leyendo sólo esto y `docs/estado.md`.

- **Última actualización:** 07/11/2026, sesión de búsqueda manual con progreso en
  vivo.
- **Rama:** `main`. `h1-paralelo` se conserva intacta.
- **Commit de referencia:** ver `git log -1 --oneline`.
- **Estado:** el buscador funciona y **ya no sobrevalora** ofertas. Sobre 1 280
  ofertas quedan 3 elegibles y 8 dudosas. Se puede lanzar la búsqueda desde
  **Ofertas → Buscar ahora** y ver el avance real. Falta que el usuario valide la muestra
  de 25 en la pestaña **Validación**. La IA **funciona** con la clave guardada: una
  generación real sobre una oferta costó USD 0. El procesamiento masivo sigue
  apagado a propósito.

---

## 1. Cómo ejecutar

```bat
cd "C:\ruta\donde\clonaste\buscador-laboral"
.venv\Scripts\python.exe -m buscador ui            :: interfaz
.venv\Scripts\python.exe -m buscador buscar        :: corrida
.venv\Scripts\python.exe -m buscador reclasificar  :: recalcular todo
.venv\Scripts\python.exe -m buscador doctor        :: estado y salud
.venv\Scripts\python.exe -m pytest tests -q        :: 208 pruebas
.venv\Scripts\python.exe -m buscador validacion     :: progreso de la revisión
.venv\Scripts\python.exe -m buscador ia --diagnosticar :: estado real de la clave
.venv\Scripts\python.exe tools\prueba_ia_oferta.py  :: 1 oferta, cuota gratuita
.venv\Scripts\python.exe tools\verificar_interfaz.py :: 17 comprobaciones HTTP
```

Aplicar o volver a aplicar el perfil real:

```bat
.venv\Scripts\python.exe -m buscador perfil --real
```

---

## 2. Qué está implementado y verificado

### Perfil (rules-2.0.0)

`buscador/perfil.py` publica sólo la **estructura** y un perfil de ejemplo sin
datos personales. El perfil real se carga desde `data/perfil.local.json` o desde
`Configuración`, siempre fuera del repositorio.

Reglas que el perfil expresa como configuración, no como datos: remoto
**obligatorio** (`territorio.remoto_obligatorio`), zona presencial admitida
(`territorio.presencial`), y salarios marcados `pendiente_ratificacion`.

Habilidades ponderadas por nivel (demostrada 1,0 / intermedia 0,7 / básica 0,4).

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
- Interfaz por socket real: **30/30** con búsqueda real incluida
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

## 5. Bloqueos que necesitan intervención del usuario

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

## 9. Convenciones

- Código y documentación en español; tablas y columnas también.
- Migraciones como `migrations/vN.sql` + subir `VERSION_ESQUEMA`.
- Un dato ausente se declara `unknown`; no se rellena por suposición.
- No se declara una prueba como superada si no se ejecutó.
- Toda afirmación sobre una fuente o un modelo lleva evidencia o se marca como
  no verificada.
