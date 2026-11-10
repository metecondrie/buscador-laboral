# Implementación · revisión del 2026-11-10

Registro único de la ejecución del plan integrado (auditorías de Gemini y Qwen
sobre `rules-3.1.0`). Rama: `fix/auditoria-2026-11-10`. Versión resultante:
app `0.2.1`, reglas `rules-3.2.0`.

Estados: `corregido` · `no reproducido` · `bloqueado` · `pendiente` (fuera de
alcance de esta revisión).

## Lote A — clasificador determinista

| ID | Estado | Commit | Prueba | Nota |
| --- | --- | --- | --- | --- |
| C01 | corregido | `lote A/B` | `test_fase1f_auditoria.py::test_c01_*` | Títulos de soporte y back office por patrón con guardas. `Operations Associate` de depósito queda fuera; `Paid Ads`, `Senior Software Engineer`, enfermería y marketing siguen fuera |
| C02 | corregido | `lote A/B` | `test_c02_*` | Una pista de herramienta (`power bi`) sólo otorga categoría si el título es afín a datos |
| C03 | corregido | `lote A/B` | `test_c03_*` | El cuerpo aporta indicios administrativos; se aplican como `origen=texto`, nunca como categoría plena |
| C04 | corregido | `lote A/B` | `test_c04_*` | `worker.py` y `verify.py` dejan de enviar `categoria_fuente` como `tipo_contrato`. La etiqueta de la fuente corrobora (`categoria_corroborada`), no decide |
| C05 | corregido | `lote A/B` | `test_c05_*` | `categoria_de()` recibe las categorías del perfil; sin dato usa todas (compatibilidad retroactiva) y reporta las no reconocidas |
| C06 | corregido | `lote A/B` | `test_c06_*` | Se separan requeridas, declaradas e informativas. El vocabulario de soporte se detecta pero no resta ni suma si el perfil no lo declara |
| E01 | corregido | `lote A/B` | `test_e01_*` | «or equivalent experience» → duda; «strictly required» sigue excluyendo |
| E02 | corregido | `lote A/B` | `test_e02_*` | «manager» de cuentas no marca gestión sin evidencia de equipo en el cuerpo |
| L01 | corregido | `lote A/B` | `test_aviso_corto_deja_trazabilidad_de_idioma_no_evaluado` | El idioma no evaluado se declara; no bloquea |
| L02 | corregido | `lote A/B` | `test_l02_*` | B1 y B2 no se promueven a «fluido»; B1 no aprueba B2 explícito |
| T01 | corregido | `lote A/B` | `test_cuerpo_mundial_contradice_a_la_fuente_y_va_a_revision` | Conflicto campo/cuerpo → `doubtful` con el motivo a la vista |
| T03 | corregido | `lote A/B` | `test_fase1f_auditoria.py` (territorio) | Ciudades, estados y países completos dejan de quedar en duda |
| V01 | corregido | `lote A/B` | `test_vigencia_separa_publicacion_de_disponibilidad` | Estado `stale` propio; no expulsa y no alerta |
| V03 | corregido | `lote A/B` | `test_clasificacion_casos_sinteticos.py` | `demotrada` → `demostrada`; expectativas recalculadas |

## Lote B — puntaje, alertas y evidencia

| ID | Estado | Commit | Prueba | Nota |
| --- | --- | --- | --- | --- |
| S01 | corregido | `lote A/B` | `test_s01_*` | Umbral en `config.UMBRAL_AVISO` (65) y en la tabla `settings` (`umbral_aviso`). Techo real medido: 69 sin nivel de inglés declarado, 73 con él |
| S02 | corregido | `lote A/B` | `test_s02_*` | El puntaje sigue calculándose sobre todo el peso aplicable. Se probó normalizar sobre lo observado y se descartó: inflaba coincidencias parciales (42 → 54) y premiaba la ausencia. Se expone `escala_puntaje` y `cobertura` |

## Lote C — fuentes y calidad de adquisición

| ID | Estado | Commit | Prueba | Nota |
| --- | --- | --- | --- | --- |
| F02 | corregido | `lote C` | `test_fase1f_fuentes.py::test_los_tableros_*` | 8 tableros nuevos verificados el 2026-11-10 con sonda HTTP + conteo de vacantes |
| F03 | corregido | `lote C` | idem | GoFasti, Precision Medicine Group, Aghanim, Maple, Whippy, Atlas Assistants, Wing Assistant, BlueLight Consulting |
| F04 | corregido | `lote C` | `test_jobicy_particiona_por_region_latam` | Jobicy: `geo=latam` verificado. Remotive: el filtro por categoría se ignora (verificado), no se particiona |
| F05 | corregido | `lote C` | `test_el_circuito_se_abre_tras_dos_fallos_terminales` | Sonda única: 404 confirmado. Circuito abierto tras dos fallos terminales; el histórico se conserva |
| C6 (métricas) | corregido | `lote C` | `test_las_metricas_por_fuente_*` | `verificar-fuentes` informa elegibles, revisables, incompatibles, vigentes, vigencia sin confirmar y HTTP |
| F01 | pendiente | — | — | Curar consultas por fuente y medir relevancia marginal: requiere datos y decisiones de producto, no un cambio de código |
| Q01 | pendiente | — | — | La muestra de validación quedó saneada y reproducible; la calibración empírica con etiquetas humanas no se ejecutó |

## Lote D — documentación, instalación y entrega

| ID | Estado | Commit | Prueba | Nota |
| --- | --- | --- | --- | --- |
| T02 | corregido | `lote D` | `test_una_ciudad_con_remote_no_cuenta_como_alcance_global` | El agrupador territorial ya no toma «remote» como alcance global; el orden pone la geografía primero |
| V02 | corregido | `lote D` | `test_la_muestra_no_publica_titulo_ni_empresa`, `test_el_csv_publicado_no_tiene_bom` | La herramienta escribía título y empresa (datos identificables) y declaraba `rules-2.0.0` fijo. Ahora es saneada, escribe `dimension_principal` y deja procedencia en `.meta.json` |
| V04 | corregido | `lote D` | `docs/ANEXO_CASOS_ANONIMIZADOS.md` | Definiciones de FP/FN corregidas (estaban invertidas) y casos A/C/I/M reclasificados sin borrar el diagnóstico original |
| Q02 | corregido | `lote D` | — | README con versión, cambios, pendientes, instalación desde GitHub y modo demo |
| Demo sin red | corregido | `lote D` | `test_la_demo_prepara_ofertas_sinteticas_sin_red` | `buscador demo` crea base aparte, clasifica 8 ofertas sintéticas y abre la interfaz |
| Compatibilidad | corregido | `fix(instalacion)` | suite completa en Python 3.12 | `Path.read_text(newline=)` requería 3.13; el README promete 3.10+ |

## Bloqueos y límites

- **Cifras del catálogo**: no se recalcularon. No hay base en el repositorio y no
  se tocó la instalación operativa. Las 2.543 / 2 / 22 / 2.519 son el corte
  histórico del 2026-11-09 con `rules-3.1.0`.
- **Get on Board**: la API de vacantes responde 401 (requiere clave). No se
  integra: la condición del plan era acceso sin clave.
- **Impactos anunciados** (5×–10×, «22 dudosas destrabadas», «>10 nuevas
  elegibles»): no se verificaron. Requieren backtest sobre datos autorizados.
- **Privacidad**: el repositorio es público y hubo material de auditoría con
  datos reales en commits históricos, retirado después de `main`. La eliminación
  no borra el historial de Git. No se reescribió historia (no se autorizó) ni se
  recopiló ese material. Si apareciera una credencial activa, hay que rotarla y
  evaluar la reescritura como tarea aparte.
