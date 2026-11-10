# Buscador laboral · motor de clasificación

Aplicación local para Windows que captura ofertas de **catorce fuentes públicas**,
las clasifica con reglas explicables y deja registrado por qué cada oferta quedó
elegible, dudosa o descartada.

Este repositorio está preparado para **una revisión independiente de los
resultados de la clasificación**, no como distribución de datos personales: no trae la base de datos,
ni el perfil operativo, ni credenciales. Todo lo que hace falta para entender y discutir el
comportamiento del motor está aquí.

- No usa IA por defecto, no envía CV ni postulaciones, y tiene presupuesto de IA USD 0. Las búsquedas sí realizan peticiones HTTP a las fuentes públicas.
- El servidor sólo escucha en `127.0.0.1`.
- La base, el perfil, los registros y los respaldos viven **fuera** del
  repositorio, en `%LOCALAPPDATA%\BuscadorLaboral\`.

---

## 1. Qué se busca en esta revisión

El catálogo clasificado con `rules-3.1.0` deja **2 elegibles, 22 dudosas y
2.519 incompatibles** sobre 2.543 ofertas. Es decir, el 99 % figura como incompatible en este corte; **eso no demuestra** que el 99 % sean descartes erróneos.

El objetivo de la revisión es identificar **las tres mejoras concretas que más
aumentarían la cantidad de oportunidades laborales realmente adecuadas, sin
admitir falsos positivos**.

La lectura mínima para poder opinar con fundamento:

| Documento | Para qué |
| --- | --- |
| `docs/INFORME_CLASIFICACION.md` | El estado del catálogo y su desglose, reproducible |
| `docs/ANEXO_CASOS_ANONIMIZADOS.md` | Los modos de falla, con casos sintéticos |
| `tests/test_clasificacion_casos_sinteticos.py` | El comportamiento actual, Caracterizado en código |
| `buscador/rules.py` | La implementación del filtro duro |

La sección 7 resume los principales focos de investigación. Las secciones 10–12 distinguen **defectos observados**, **hipótesis por validar** y **mejoras futuras**. No hay cambios de reglas aprobados: ése es el trabajo de la revisión externa.

## 2. Estado funcional

| Aspecto | Estado |
| --- | --- |
| Versión de reglas | `rules-3.1.0` (`buscador/config.py`) |
| Versión de la app | `0.2.0` |
| Pruebas | Última ejecución informada para el árbol de trabajo: **834 aprobadas**; la copia publicada debe probarse independientemente (el conjunto puede diferir) |
| Clasificación | operativa: 2.543 ofertas, 2 elegibles, 22 dudosas, 2.519 incompatibles |
| Captura | operativa: 14 fuentes, corridas cada 12 h |
| IA | apagada por defecto (presupuesto USD 0) |
| Respaldo de base | verificado con SHA-256 |
| Postulación | la app **no** postula; deja el registro del enlace y la fecha |

Lo que **no** está resuelto y no se toca en esta revisión:

- la fuente F05 (The Muse) devolvió 404 / `access_restricted` en las últimas corridas documentadas y acumula
  incidentes: está documentado en `docs/FASE1_ESTADO_F05.md`, y su baja queda
  para una fase posterior;
- la base de datos **no** está en el repositorio: quien revise necesita su
  propia copia o los números del informe.

## 3. Arquitectura

### 3.1 El recorrido de una oferta

```
fuente pública ──► adapter ──► ingest ──► observations ──► merge ──► jobs
                                                                    │
perfil ──────────────────────────────► rules.evaluar ◄─────────────┤
                                            │                      │
                                            ▼                      ▼
                                        analyses              job_versions
```

1. **`buscador/adapters/`** — un módulo por familia de fuente (RSS, API
   pública, tableros de empresa). Devuelven `observations` crudas con su
   `field_status_json`: qué campo vino y qué campo no vino. No deciden nada.
2. **`buscador/ingest.py`** — normaliza, calcula `content_hash` y deduplica.
3. **`buscador/merge.py`** — agrupa la misma oferta publicada en varias
   fuentes. `jobs` es la oferta única; `job_observations` guarda de dónde vino.
4. **`buscador/rules.py`** — el filtro. `evaluar(oferta, perfil)` devuelve una
   `Evaluacion` con elegibilidad, motivo, razones, incertidumbres y
   componentes de compatibilidad. **Es el archivo central de esta revisión.**
5. **`buscador/worker.py`** — la cola: clasifica, invalida análisis viejos y
   avisa. Escribe en `analyses`.
6. **`buscador/web.py`** — la interfaz local (FastAPI) y las plantillas de
   `buscador/web/templates/`.
7. **`buscador/ai/`** — la capa opcional de IA (proveedores, cuotas, caché,
   cola). Apagada; el motor funciona sin ella.

### 3.2 El modelo de decisión

Tres dimensiones que nunca se mezclan:

1. **Elegibilidad** (filtro duro): categoría, territorio, modalidad, formación,
   seniority, idioma y restricciones laborales. Si algo falla acá, la oferta
   queda `incompatible` con un motivo textual.
2. **Compatibilidad** (0–100): cercanía profesional, ponderada por el nivel de
   cada habilidad del perfil. Sin habilidades declaradas no hay puntaje.
3. **Confianza** (alta / media / baja): cuánta información real trae el aviso.

Una oferta que no se puede decidir va a `doubtful`: el motor no inventa datos
para resolver una ambigüedad, la deja explícita.

La **excepción por competencias** evita que la experiencia sea un filtro
absoluto: entre 2 y 7 años, con ≥ 60 % de las habilidades cubiertas, la oferta
no se descarta.

### 3.3 La base

SQLite, en `%LOCALAPPDATA%\BuscadorLaboral\data\buscador.db`. Tablas que
importan para esta revisión:

| Tabla | Qué guarda |
| --- | --- |
| `jobs` | la oferta única: categoría, territorio, modalidad, vigencia, fuente |
| `observations` | cada aparición, con su `seniority`, `skills` y `field_status_json` |
| `analyses` | el veredicto: `elegibilidad`, `razones_json`, `motivo_elegibilidad`, `score` |
| `sources` | las catorce fuentes y su estado |
| `runs` / `source_runs` | las corridas y el resultado por fuente |
| `profile_versions` | el perfil con el que se clasificó |

`analyses` es histórico: cada reclasificación deja la fila anterior con
`obsoleto=1`. El estado vigente es `obsoleto=0`, y hay exactamente una fila
vigente por oferta.

## 4. Instalación

Requiere **Python 3.10 o superior** (desarrollado sobre 3.14.10, Windows). Sin
servicios externos: no hay base de datos que levantar ni cuentas que crear.

```bat
git clone <url-del-repositorio>
cd buscador-laboral

py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Para las pruebas, además:

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## 5. Ejecutar las pruebas

```bat
.venv\Scripts\python.exe -m pytest tests -q
```

La última ejecución de la suite informada antes del push registró **834 pruebas aprobadas** en el árbol de trabajo. **No se afirma que ese resultado valide el HEAD actual**: hay pruebas adicionales de la maquinaria de publicación y de rollback que deben ejecutarse en un entorno aislado. Las pruebas ordinarias no deben acceder a la DB operativa ni a servicios de red; verificar `BUSCADOR_DATA_DIR` antes de ejecutarlas.

Qué cubren:

| Archivo | Qué mira |
| --- | --- |
| `tests/test_clasificacion_casos_sinteticos.py` | el comportamiento de la clasificación, caso por caso |
| `tests/test_reglas_experiencia.py` | la excepción por competencias |
| `tests/test_ranking_regresiones.py` | que el puntaje no se rompa |
| `tests/test_web_mvp.py` | la interfaz y la API local |
| `tests/test_actividad.py`, `tests/test_orquestacion.py` | la cola y la actividad |
| `tests/test_fase1*.py`, `tests/test_fase2b_perfil_guard.py` | regresiones de las fases anteriores |
| `tests/test_publicacion.py` | la mecánica de publicación y el saneado |

Si una mejora cambia el comportamiento de un caso, **el test correspondiente
falla**: eso es intencional, es la señal de que el cambio es deliberado.

## 6. Comandos

```bat
.venv\Scripts\python.exe -m buscador ui                  :: interfaz en 127.0.0.1:8765
.venv\Scripts\python.exe -m buscador buscar              :: corrida manual
.venv\Scripts\python.exe -m buscador doctor              :: estado y salud
.venv\Scripts\python.exe -m buscador verificar-fuentes   :: mide cada fuente
.venv\Scripts\python.exe -m buscador respaldar           :: respaldo verificado
.venv\Scripts\python.exe -m buscador exportar --guardadas :: CSV
.venv\Scripts\python.exe -m buscador programar --estado  :: cada 12 h
.venv\Scripts\python.exe -m buscador diagnosticar        :: paquete ZIP de soporte
.venv\Scripts\python.exe tools\informe_clasificacion.py  :: informe reproducible (sólo lectura)
```

## 7. Dónde está el rendimiento, en números

Del catálogo vigente (`docs/INFORME_CLASIFICACION.md` tiene el detalle completo):

| Observación | Dato |
| --- | --- |
| El descarte dominante es el **territorio** | 1.503 de 2.519 incompatibles (59,7 %) |
| La **categoría** no se reconoce en casi todo el catálogo | 2.330 ofertas sin categoría (91,6 %) |
| La banda accionable son las 22 dudosas | frenadas por datos ausentes, no por conflicto |
| Tres fuentes aportan el 69 % del catálogo y **ninguna** elegible | F02, F10, F03; comprobar utilidad marginal, no asumir que toda su oferta es mala |
| Hay **405 descartadas en la familia «remoto global declarado»** | requiere muestreo: puede haber restricciones de idioma, categoría, seniority u otras; **no equivale a 405 falsos descartes** |
| 9 de 10 categorías del perfil nunca producen una elegible | sólo `VA/Data Entry` llega |

## 8. Qué NO está en este repositorio, y por qué

| No se publica | Por qué |
| --- | --- |
| La base SQLite operativa | es el dato, no el programa; vive en `%LOCALAPPDATA%` |
| El perfil real | se publica un perfil de ejemplo (`buscador/perfil.py`) |
| Credenciales, API keys, tokens | se leen del entorno; nunca están en el código |
| CV y datos de formación del titular | no existen en el repositorio |
| Registros y respaldos de la base | viven en `%LOCALAPPDATA%\...\logs` y `...\backups` |
| Auditorías con ofertas reales (empresa, título, URL) | reemplazadas por `docs/ANEXO_CASOS_ANONIMIZADOS.md` |
| La muestra de validación con empresas reales | reemplazada por una versión anonimizada (`docs/muestra-validacion.csv`) |

La publicación pasa por una puerta de control: `tools/publicacion/saneado.py`
reemplaza rutas, correo, nombre y datos de salud, y **bloquea la publicación**
si detecta una clave de Google, un token de GitHub, una clave privada, un
`.env`, una base SQLite o un volcado de logs.

## 9. Estructura

| Ruta | Contenido |
| --- | --- |
| `buscador/` | la aplicación: configuración, base, adaptadores, reglas, trabajador, interfaz |
| `buscador/adapters/` | los adaptadores de fuente y sus utilidades |
| `buscador/ai/` | la capa opcional de IA (apagada por defecto) |
| `buscador/web/templates/` | las plantillas de la interfaz |
| `tests/` | pruebas automatizadas; el total depende del commit y del entorno |
| `tools/` | utilidades: informe de clasificación, auditoría de credenciales, publicación |
| `tools/publicacion/` | el saneado y la puerta de datos sensibles |
| `docs/` | informe, anexo, instalación, pruebas, trazabilidad |

## 10. Límites conocidos

- Presupuesto USD 0: sin llamadas de IA ni servicios pagos.
- La aplicación no postula ni investiga salarios.
- El catálogo está en inglés en su gran mayoría y es mayoritariamente de
  EE. UU. y Europa: buena parte del descarte territorial es ruido de origen, no
  ruido de clasificación.
- La confianza declarada es `baja` en el 99,7 % del catálogo.


## 11. Hoja de ruta y deuda técnica (no implementada)

**Convención:** «Confirmado» significa observado en datos, código o interfaz;
«Hipótesis» exige etiquetado humano o reproducción; «Mejora» es una propuesta,
no un fallo probado. **Este README no autoriza cambios al motor ni al perfil.**

| Prioridad | Estado | Trabajo pendiente | Evidencia / criterio de cierre |
| --- | --- | --- | --- |
| P0 | Confirmado | **Medir rendimiento útil por fuente** y ampliar fuentes realmente compatibles con trabajo remoto desde Argentina, nivel inicial y requisitos lingüísticos viables. | F02/F10/F03 aportan ~69 % del catálogo y 0 elegibles en el corte; medir ofertas pertinentes y vigentes por fuente, no sólo volumen bruto. |
| P0 | Hipótesis | **Auditar la detección de categorías** en una muestra humana de puestos potencialmente afines descartados. | 2.330 incompatibles sin categoría reconocida; determinar cuántos son ajenos y cuántos son falsos negativos antes de modificar patrones. |
| P0 | Hipótesis | **Revisar precedencia entre territorio del campo fuente y texto del aviso.** | Casos contradictorios del anexo C; no interpretar las 405 descartadas de alcance global como errores confirmados. |
| P0 | Confirmado | **Separar «dudosa» de «postulable» y documentar criterios de revisión humana** (territorio, inglés oral, experiencia, horarios y guardias). | Sólo hay 4 revisiones humanas previas; sin conjunto etiquetado suficiente no corresponde estimar precisión ni recall. |
| P1 | Confirmado | **Tratar seniority de forma contextual**: `Mid-level` o `Specialist` no implica automáticamente gestión. | En la ficha de soporte aparece «el título implica responsabilidad de gestión» pese a que el título es Specialist; crear casos positivos y negativos. |
| P1 | Confirmado | **Resolver geografía extranjera no reconocida y modalidad incompleta** (APAC, ciudades y países como Berlin, Munich, Bulgaria, Guatemala, Ohio). | Parte de las dudosas son ruido geográfico; evitar descartar anuncios abiertos mundialmente por una mención incidental. |
| P1 | Confirmado | **Decidir el destino de F05 The Muse**: confirmar el endpoint, aplicar circuito abierto o desactivar controladamente. | Últimas corridas con 404 / `access_restricted`; ver `docs/FASE1_ESTADO_F05.md`. |
| P1 | Mejora | **Revisar la política de alertas y su umbral (75) sin abrir falsos positivos**; distinguir oferta «eligible», oferta de revisión y alerta. | Ninguna de las dos elegibles del corte inicial alcanzaba 75; medir alertas útiles y fatiga de notificaciones antes de cambiarlo. |
| P1 | Hipótesis | **Inspeccionar formación y alternativas a título terminado** (`required`, `preferred`, experiencia equivalente, disciplina). | La dimensión `formacion` produjo 103 exclusiones principales; que un título sea exigido no constituye por sí solo un error. |
| P1 | Mejora | **Considerar disponibilidad horaria, guardias y requisitos de inglés oral**, además del nivel de inglés indicado. | El motor no determina de forma completa la compatibilidad real de turnos, on-call y comunicación telefónica. |
| P2 | Mejora | **Catálogo ampliable de fuentes**, con alta/baja supervisada, verificaciones y métricas por fuente. | Las fuentes nuevas se deben validar por cobertura, legalidad de acceso, duplicación y utilidad; no incorporar indiscriminadamente. |
| P2 | Mejora | **Mejorar etiquetas y explicaciones de UI** para incertidumbres y puntuación; mantener seguimiento manual de postulaciones. | El buscador registra decisiones, pero **no adjunta ni envía CV**, y no debe enviar candidaturas sin una decisión de producto y autorización específica. |
| P2 | Opcional | **IA gratuita sólo como apoyo excepcional** para extracción/revisión, con límites de privacidad y costo. | La clasificación principal continúa determinista y operativa sin IA; no activar pagos ni enviar el perfil a proveedores por defecto. |

### Condición para dar por útil una mejora

1. Basar la propuesta en **ejemplos verificables**, distinguiendo dato real, hipótesis y prueba sintética.
2. Medir **ofertas adicionales potencialmente postulables**, tasa de descarte erróneo en una muestra etiquetada y costo operativo, no sólo número de pruebas.
3. Evitar degradar exclusiones claras (residencia obligatoria fuera de Argentina, presencial fuera de zona, idiomas realmente imprescindibles).
4. Implementar como un ticket acotado con pruebas de regresión, una revisión independiente y cierre; no abrir sucesivas auditorías generales.

## 12. Protocolo de revisión independiente y precauciones

- **Sólo lectura** en esta ronda: no modificar reglas, CSV, perfil, fuentes, scheduler ni ejecutar búsquedas o reclasificaciones. Se espera un diagnóstico, no un PR.
- Leer `docs/INFORME_CLASIFICACION.md`, `docs/ANEXO_CASOS_ANONIMIZADOS.md`, `tests/test_clasificacion_casos_sinteticos.py`, `buscador/rules.py` y adaptadores relevantes.
- Los datos son una **instantánea del 2026-11-09**: los conteos cambian con cada búsqueda. El repositorio **no incluye la DB operativa**.
- **Terminología estándar de clasificación:** falso positivo (FP) = se acepta una oferta que realmente no sirve; falso negativo (FN) = se descarta una oferta que sí serviría. En el anexo actual algunas marcas FP/FN están invertidas y algunas hipótesis se describen como hechos: **no usar esas etiquetas sin verificarlas**. Las pruebas sintéticas caracterizan el comportamiento, no demuestran la aptitud real de postulaciones.
- Un resultado `doubtful` **no es automáticamente un falso negativo**. Y una región global declarada no implica compatibilidad si el cuerpo exige un país, idioma, experiencia o presencialidad incompatibles.
- El repositorio es **privado**. Algunas auditorías con ofertas reales fueron retiradas de `main` pero permanecen en el **historial Git**. Antes de otorgar acceso a colaboradores externos, evaluar purgar ese historial o compartir únicamente un ZIP saneado, sin objetos históricos.
- No solicitar, exportar ni subir credenciales, CV, perfil operativo, bases SQLite, documentos personales ni logs. No ejecutar pruebas contra la DB real.
- Entrega solicitada: **exactamente tres mejoras priorizadas**, cada una con evidencia, mecanismo causal, estimación de impacto con incertidumbre, costo/tiempo aproximado, riesgo de falsos positivos y prueba que validaría el cambio. Las demás ideas van a «pendientes».
