# Pruebas ejecutadas

Última ejecución: 07/11/2026. Entorno: Windows 10 Pro 22H2, Python 3.14.10 en
`.venv`, SQLite 3.50.4.

Estados: **superada**, **parcial**, **simulada**, **no ejecutada**.

## Automáticas

Comando: `.venv\Scripts\python.exe -m pytest tests -q`
Resultado: **336 superadas**, 1 advertencia de Starlette sobre `httpx` (no afecta).
Evidencia: `docs/evidencia/pytest.txt`.

| Archivo | Qué cubre | Pruebas |
| --- | --- | --- |
| `test_rules.py` | territorio, formación, seniority, salario ausente, cobertura, orden | 10 |
| `test_ranking_regresiones.py` | una prueba por cada error reportado: manager, 100/100, presencial, ingeniería, vigencia, país en título, salario, región US, ciudad/estado de EE. UU. | 23 |
| `test_reglas_experiencia.py` | excepción por competencias, 8+ años, modalidad, orden por remoto | 12 |
| `test_validacion.py` | muestra fija, veredictos, corrección, métricas, falsos positivos y negativos, persistencia tras reclasificar | 7 |
| `test_diagnostico.py` | formato no determina validez, generación 200 sin sugerir cuota, último válido vs. errores de otra clave, controles YouTube/Books «no aplica», cuota agotada, sin permiso, sin clave, fallo del almacén, huella registrada, la clave nunca aparece en el resultado | 16 |
| `test_web_ia.py` | GET /config, GET /ia (405), y acciones diagnosticar, verificar, guardar, guardar y borrar clave, habilitar y deshabilitar | 12 |
| `test_adapters.py` | fixtures F01–F03, errores tipados, dominio no aprobado, destino privado | 10 |
| `test_adapters_nuevos.py` | fixtures F04–F11, salario en texto, entidades HTML, metadatos | 13 |
| `test_esquema.py` | versión, migraciones idempotentes, ajustes, rechazo de base futura, PRAGMAs, PRAGMA de cada migración, reparación de cuota de la v8 | 7 |
| `test_actividad.py` | bandeja legible sin volcado de dicts, puntaje histórico vs vigente, recomendación desactualizada, `delivered` como bandeja local, persistencia tras reiniciar y en un proceso nuevo, deduplicación por clave, marcado como leído idempotente con CSRF, pastilla del nav, cola con etiquetas, despachar sin procesos externos y lectura que no toca postulaciones | 18 |
| `test_puntaje_evidencia.py` | los cuatro estados del componente, fórmula, amplitud de habilidades, idioma por aviso, territorio (5 alcances), viajes y vigencia | 26 |
| `test_casos_reales.py` | los cinco avisos reportados con su texto original: puntajes antes/después y motivos correctos | 12 |
| `test_postulaciones.py` | registrar, editar, retirar, reabrir, historial sin duplicados, insignia en la lista, página de postuladas, persistencia tras reinicio, CSRF y «no envía nada» | 17 |
| `test_contadores.py` | cada cifra de Diagnóstico contra su consulta; separación corrida/catálogo; errores de fuente vs de clasificación | 5 |
| `test_ia_cascada.py` | tres modelos por defecto, relleno del valor vacío, valor del usuario intacto tras reiniciar, formulario sin efectos colaterales | 10 |
| `test_reclasificacion.py` | el formulario no degrada el perfil, guardar procesa la cola, deuda diferida y su reparación, cambio de reglas con historial conservado, descarte de tareas de perfil/reglas anteriores, recuperación de tareas colgadas, la cola no se toca con una corrida en curso, búsqueda sin tareas abandonadas, Diagnóstico con números, botón de reclasificar y autoreparación al arrancar | 16 |
| `test_busqueda_manual.py` | progreso por fuente desde la base, avance y clasificación incremental antes del final, resumen final, fallo parcial, cancelación que conserva el trabajo, botón y panel en Ofertas, `/progreso.json` con y sin sesión, recuperación tras recargar, una sola corrida por doble pulsación y por base, corrida colgada, CSRF, redirección abierta, IA informada sin tocar credenciales, contrato JS/plantilla | 20 |
| `test_identidad.py` | deduplicación, cambio material, vínculo entre fuentes, reclamo atómico, entidades | 9 |
| `test_duplicados.py` | similitud, sugerencia, fusión aceptada y revertida, rechazo, misma fuente | 7 |
| `test_orquestacion.py` | particiones, aislamiento de errores, relevancia por fuente, tope | 5 |
| `test_operacion.py` | respaldo, verificación, restauración, retención, CSV, programación, incidentes, paquete | 10 |
| `test_ia.py` | catálogo verificado, cascada sólo Gemini, proveedores desactivados, credenciales (Windows y DPAPI), prioridad almacén > entorno, cuotas, caché, 429, presupuesto, esquema, cola, rechazo que no consume cuota, consumo que separa generaciones de intentos, clave fuera de la URL | 43 |
| `test_web.py` | sesión, token de un solo uso, Host ajeno, CSRF, idempotencia, cierre | 9 |
| `test_web_mvp.py` | 10 páginas, filtros, perfil, respaldos, duplicados desde la interfaz | 11 |
| `test_resiliencia.py` | fuente caída, caída entre ingesta y análisis, HTML hostil, token de control | 4 |

Ninguna prueba usa la red ni gasta dinero. Las que necesitan una fuente usan
fixtures versionados o dobles de prueba explícitos. Un fixture `autouse` bloquea
los almacenes de credenciales reales: ninguna prueba puede leer ni imprimir la
clave del sistema.

## Manuales con datos reales

| Comprobación | Resultado |
| --- | --- |
| Catorce fuentes contra su respuesta real | 976 ofertas, 14 fuentes, 4 aportan relevantes |
| Corrida completa | 416 observaciones en 12,5 s, 11 fuentes (antes de sumar F12–F14) |
| Migración v1 → v8 sobre la base real | Sin pérdida: conteos preservados, `user_version` 8 |
| Respaldo y restauración sobre la base real | Respaldo verificado, `integrity_check` ok |
| Paquete de diagnóstico | ZIP con 6 archivos, sin claves |
| Interfaz | 10 páginas renderizadas en proceso (ASGI) y todas las acciones POST verificadas |
| Servidor real por socket | **ejecutada** con `tools/verificar_interfaz.py`: uvicorn real y HTTP real en el mismo proceso (el entorno bloquea loopback entre procesos). 40/40 en modo rápido (cancela la corrida) y **43/43 con `--buscar`**, que lanza una búsqueda real completa: botón, panel, JS servido, `/progreso.json`, arranque, doble pulsación sin duplicar, 12 estados de progreso distintos, cancelación en vuelo, resumen final y progreso recuperado tras recargar. Evidencia en `docs/evidencia/interfaz.txt` |
| Búsqueda manual real | **ejecutada**: 14/14 fuentes, 24–28 s, 825 observaciones revisadas, 60 nuevas, 0 duplicadas nuevas, 11 candidatas en el catálogo |
| Reclasificación con rules-3.0.0 | **ejecutada sobre la base real**: 1 299 ofertas reencoladas y clasificadas en 27,8 s; historial de 3 772 → 5 073 análisis, 0 pendientes |
| Postulación tras reiniciar | **ejecutada**: un proceso registra, otro proceso relee la misma fila (`docs/evidencia/postulacion-reinicio.txt`) |
| Bandeja de Actividad | **superada**: 18 pruebas y 5 comprobaciones HTTP reales sobre la base real; sin `payload_json` ni `delivered`, ofertas con título, empresa, fecha, elegibilidad, lectura y enlace, puntaje «al avisar» separado del vigente, y persistencia en un proceso nuevo |
| Reparación de la cola (07/11) | **ejecutada sobre la base real**: 1 280 procesadas, 1 280 descartadas por ser de un perfil superado, 29,6 s; 3 696 análisis históricos conservados. Informe en `docs/incidente-cola-clasificacion.md` |
| **Generación real sobre una oferta** | **superada**: `gemini-3.5-flash-lite`, 1 969 + 480 tokens, 4 citas verificadas, 0 inventadas, **USD 0**. Evidencia en `docs/evidencia/ia-oferta-real.txt` |
| **Segunda corrida sobre la misma oferta** | **superada**: la caché respondió sin petición nueva (`cache / cache`, USD 0) |

## Del plan

| ID | Estado | Evidencia y límite |
| --- | --- | --- |
| P01 Instalación | **parcial** | Arranque, cierre por botón y persistencia probados. Falta tarea programada verificada y prueba en PC limpia. |
| P02 Fuentes | **superada con salvedad** | Once fuentes verificadas contra su respuesta real; 7 aportan relevantes. La ventana de 12 h no se observó durante 24 h. |
| P03 Programa | **parcial** | Mecanismo implementado y probado. `schtasks.exe` bloqueado por política: no se pudo verificar el disparo real. |
| P04 Parcial | **superada con simulación** | Fuente que lanza excepción y partición que falla: el resto termina, el incidente queda tipado. No se inyectó un 429 real. |
| P05 Rendimiento | **parcial** | 416 observaciones en 12,5 s. No mide 10.000 ofertas. |
| P06 Duplicados | **superada** | Identificador fuerte, URL canónica, vínculo débil, sugerencias con reversión. |
| P07 Elegibilidad | **parcial** | Casos US-only/LATAM, título obligatorio, seniority, salario ausente y excepción por competencias. Falta etiquetado humano de 25. |
| P08 Ranking | **no ejecutada** | Requiere las 25 revisiones humanas. |
| P19 Estabilización | **superada** | Cascada persistente, puntaje con evidencia, territorio/vigencia, casos reales, postulaciones y contadores, con pruebas de reinicio. |
| P18 Reclasificación | **superada** | Drenaje determinista sin red, deuda diferida reparable, descarte de cola obsoleta, autoreparación al arrancar y 16 pruebas de regresión. |
| P17 Búsqueda manual | **superada** | Botón, progreso persistido, incremental, cancelación, concurrencia y recuperación probados; verificada por socket real con búsqueda de verdad. |
| P09 Interés | **superada** | Guardar, interesar, descartar y deshacer; repetición idempotente; persiste tras reinicio. |
| P10 Avisos | **parcial** | Un aviso por oferta, sin duplicados. Escritorio opcional no verificado de punta a punta. |
| P11 Gasto | **superada** | Presupuesto y cuota probados con transporte inyectado, más **una** generación real a USD 0 con tope verificado antes de la llamada. |
| P12 Datos | **superada** | Sin envío externo por defecto; el permiso de datos es explícito y se prueba. |
| P13 Hostilidad | **parcial** | Host, CSRF, SSRF, redirecciones, HTML hostil y fórmulas CSV. Sin XML con entidades externas. |
| P14 Caídas | **parcial** | Corte entre ingesta y análisis recuperado. Sin corte físico del proceso. |
| P15 Respaldo | **superada** | Respaldo, verificación, retención, restauración y exportación probadas. |
| P16 Candidaturas | **no aplica** | Fuera de alcance por decisión del proyecto. |

## Cómo repetir la evidencia

```bat
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe -m buscador verificar-fuentes --limite 20 --salida docs\evidencia\fuentes-verificacion.json
.venv\Scripts\python.exe -m buscador buscar --limite 60 --json
.venv\Scripts\python.exe -m buscador doctor
.venv\Scripts\python.exe tools\verificar_interfaz.py
.venv\Scripts\python.exe tools\prueba_ia_oferta.py --listar
.venv\Scripts\python.exe tools\verificar_interfaz.py --buscar
```

`--buscar` lanza una corrida real completa; sin el flag la verificación arranca la
búsqueda y la cancela, para no dejar una corrida colgada ni tardar de más.

La prueba de IA sobre una oferta concreta aborta sola si la corrida puede generar
gasto (proveedor de pago, modelo con precio, presupuesto distinto de 0 o pago
autorizado). Para verla sin ejecutar: `--listar`.

Una prueba no ejecutada no cuenta como aprobada. Las pruebas con dobles se
distinguen de las que usaron red real.
