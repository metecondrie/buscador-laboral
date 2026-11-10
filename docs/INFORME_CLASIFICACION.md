# Informe reproducible · por qué el catálogo deja 2 ofertas elegibles

Fecha del corte: 2026-11-09 · Reglas: `rules-3.1.0` · Base: `%LOCALAPPDATA%\BuscadorLaboral\data\buscador.db`

Alcance: **sólo lectura**. No se reclasificó nada, no se modificaron reglas, fuentes,
umbrales, perfil ni scheduler, y no se interrumpió ninguna búsqueda programada.

## 1. El problema, en una línea

De **2.543** ofertas capturadas, **2** quedaron elegibles, **22** dudosas y **2.519**
incompatibles. El catálogo no está vacío, pero la banda que llega a decisión humana
es del **0,94 %** (24 de 2.543). La pregunta de esta revisión es si ese filtro
está descartando oportunidades que sí eran postulables, y si está dejando pasar
algunas que no lo eran.

## 2. Cómo reproducirlo

```bat
py -3 tools\informe_clasificacion.py            :: informe en markdown
py -3 tools\informe_clasificacion.py --json     :: lo mismo, en json
py -3 tools\informe_clasificacion.py --db RUTA  :: contra otra base
```

Garantías del script:

- abre la base con `file:...?mode=ro`: el proceso **no puede escribir** y no toma
  bloqueos de escritura, de modo que la búsqueda programada sigue corriendo;
- no llama a la aplicación, no lee el perfil activo y no escribe en ningún lado;
- si la base no existe, sale con código 2 sin tocar nada.

Las cifras de este documento salen de ese script sobre la base del 2026-11-09.
Si el catálogo cambia, los números cambian; el método no.

## 3. Distribución

| Clase | Ofertas | % del catálogo |
| --- | ---: | ---: |
| `eligible` | 2 | 0,08 % |
| `doubtful` | 22 | 0,87 % |
| `incompatible` | 2.519 | 99,05 % |
| **total** | **2.543** | 100 % |

Contexto: 2.543 ofertas con análisis vigente de `rules-3.1.0`, sobre 10.740
análisis históricos (el resto son versiones anteriores, `obsoleto=1`).
La confianza declarada es `baja` en 2.535 casos y `media` en 8: **ninguna oferta
tiene confianza `alta`**.

Las 2 elegibles son de la categoría `VA/Data Entry`, una de Remotive (F11) y una
de We Work Remotely (F01).

## 4. Por qué se descartó: la dimensión principal

Una sola por oferta, recuperada cruzando el motivo elegido por el motor
(`motivo_elegibilidad`) con las razones de tipo `excluye` del propio análisis. No
es una estimación por palabras clave: para las 2.519 ofertas se recuperó la
dimensión (0 sin recuperar).

| Dimensión principal del descarte | Ofertas | % de las incompatibles |
| --- | ---: | ---: |
| `territorio` | 1.503 | 59,7 % |
| `categoria` | 399 | 15,8 % |
| `seniority` | 265 | 10,5 % |
| `idioma` | 137 | 5,4 % |
| `modalidad` | 112 | 4,4 % |
| `formacion` | 103 | 4,1 % |

**El territorio es el filtro dominante.** Casi seis de cada diez ofertas
incompatibles se descartaron por no admitir al perfil, no por el puesto en sí.

Una oferta puede fallar en varias dimensiones a la vez; por eso el desglose
siguiente, que cuenta cada dimensión por separado, suma más que 2.519.

### 4.1 Dimensiones que contribuyen al descarte (solapables)

| Dimensión | Ofertas con al menos un descarte por esta dimensión |
| --- | ---: |
| `categoria` | 2.330 |
| `territorio` | 1.679 |
| `seniority` | 1.204 |
| `modalidad` | 325 |
| `idioma` | 137 |
| `formacion` | 107 |

## 5. Desglose por fuente

| Fuente | Incompatibles | Elegibles | Dudosas |
| --- | ---: | ---: | ---: |
| F02 · Himalayas | 741 | 0 | 4 |
| F10 · Arbeitnow | 562 | 0 | 3 |
| F03 · Jobicy | 453 | 0 | 4 |
| F01 · We Work Remotely | 205 | 1 | 5 |
| F08 · Jobspresso | 98 | 0 | 1 |
| F04 · Remote OK | 96 | 0 | 5 |
| F14 · Ashby | 93 | 0 | 0 |
| F12 · Greenhouse | 91 | 0 | 0 |
| F13 · Lever | 67 | 0 | 0 |
| F06 · Working Nomads | 41 | 0 | 0 |
| F05 · The Muse | 33 | 0 | 0 |
| F09 · Python.org Jobs | 20 | 0 | 0 |
| F11 · Remotive | 10 | 1 | 0 |
| F07 · NoDesk | 9 | 0 | 0 |

Lectura: **las tres fuentes que más inventario aportan (F02, F10, F03 = 1.756
ofertas, el 69 % del catálogo) no aportan ni una sola elegible**. Sus inventarios
responden bien pero son mayoritariamente EE. UU./Europa y roles senior. F14, F12,
F13 y F09 no aportan ninguna oferta elegible ni dudosa. El valor marginal del
catálogo está concentrado en un puñado de fuentes pequeñas.

## 6. Desglose por categoría

| Categoría | Incompatibles | Elegibles | Dudosas |
| --- | ---: | ---: | ---: |
| (sin categoría asignada) | 2.330 | 0 | 8 |
| Customer Support | 88 | 0 | 15 |
| Reporting Analyst | 30 | 0 | 3 |
| Data Scientist | 28 | 0 | 1 |
| Data Analyst | 16 | 0 | 0 |
| Business Analyst | 11 | 0 | 2 |
| Data Operations | 5 | 0 | 1 |
| BI Analyst | 5 | 0 | 0 |
| Research Analyst | 4 | 0 | 0 |
| VA/Data Entry | 2 | 2 | 2 |

**9 de las 10 categorías del perfil nunca producen una oferta elegible.** Sólo
`VA/Data Entry` llega a 2, y `Customer Support` se queda en 15 dudosas de 103.

De 2.543 ofertas, **2.330 (91,6 %) ni siquiera tienen categoría asignada**: el
motor no las clasificó dentro de ninguna categoría del perfil y las descartó por
eso. Es el mayor bloque individual de descarta y merece una lectura aparte: ¿son
roles genuinamente ajenos al perfil, o el detector de categoría no reconoce
títulos legítimos?

## 7. Desglose por territorio

### 7.1 Por familia

| Familia | Incompatibles |
| --- | ---: |
| Estados Unidos / Canadá / América del Norte | 910 |
| Europa (sin Reino Unido) | 613 |
| Remoto global declarado | 405 |
| Asia-Pacífico | 156 |
| Reino Unido e Irlanda | 132 |
| Latinoamérica | 114 |
| Otra región no clasificada | 103 |
| Sin territorio declarado | 73 |
| África y Oriente Medio | 13 |

### 7.2 Valores más frecuentes

| Territorio declarado | Incompatibles |
| --- | ---: |
| United States | 445 |
| USA | 167 |
| Anywhere in the World | 96 |
| USA Only | 76 |
| Berlin | 73 |
| (sin territorio) | 73 |
| Canada | 69 |
| Remote | 59 |
| Munich | 52 |
| Germany | 48 |
| United Kingdom | 47 |

El bloque **405 ofertas con alcance global declarado** que aun así se descartaron
es el candidato más obvio a falsos positivos: la fuente dice «Anywhere in the
World» / «Worldwide» / «Remote» y el resultado sigue siendo incompatible.

## 8. Desglose por experiencia

| Seniority declarado | Ofertas |
| --- | ---: |
| (sin seniority declarado) | 1.297 |
| Senior | 470 |
| Mid-level | 328 |
| Director | 197 |
| Any | 89 |
| Entry-level | 56 |
| Entry Level, Junior | 14 |
| Senior Level | 14 |
| Entry-level, Mid-level | 10 |
| Entry Level | 10 |
| Mid Level | 9 |
| Manager | 8 |
| Resto (niveles compuestos) | 21 |

La columna no es completa: `observations.seniority` viene vacío en 1.297 ofertas
(la fuente no lo publica), y 1.204 ofertas reciben algún descarte por
`seniority`. Cuando el aviso no declara seniority, el motor no lo inventa:
deja la experiencia como «desconocida», no la da por cumplida y no excluye.

## 9. Desglose por idioma

| Motivo de descarte | Ofertas |
| --- | ---: |
| exige german | 75 |
| exige french | 10 |
| exige swedish | 8 |
| exige czech / chinese / portuguese | 4 c/u |
| exige mandarin / arabic / polish / norwegian / japanese | 3 c/u |
| exige russian / danish / vietnamese / korean / dutch / italian | 2 c/u |
| exige turkish / estonian / indonesian / hindi / ukrainian | 1 c/u |
| **total por idioma** | **137** |

El patrón es nítido: **el idioma nunca es un falso positivo de «exigencia»**, sino
una restricción real (alemán, francés y otros idiomas no declarados por el perfil).
La banda dudosa, en cambio,
está dominada por el idioma: las 22 dudosas tienen, todas, una razón de idioma
(«el aviso está en inglés pero no declara el nivel exigido») y todas, también,
una razón de seniority.

## 10. Las 22 dudosas: la banda accionable

Estas 22 son las ofertas que el motor **no** descartó y que quedaron esperando
decisión. Merecen atención porque son el punto donde una regla mal calibrada
cuesta oportunidades reales.

| Dimensión | Ofertas dudosas con esa razón |
| --- | ---: |
| `seniority` | 22 |
| `idioma` | 22 |
| `cobertura` | 16 |
| `territorio` | 13 |
| `categoria` | 4 |
| `modalidad` | 4 |
| `viajes` | 1 |

Por fuente: F04 Remote OK (5), F01 We Work Remotely (5), F03 Jobicy (4),
F02 Himalayas (4), F10 Arbeitnow (3), F08 Jobspresso (1).
Por categoría: Customer Support (15), Reporting Analyst (3), VA/Data Entry (2),
Business Analyst (2).

Las razones se superponen (una duda puede tener varias dimensiones). El patrón
común: **al motor le falta información, no le sobra**. Casi siempre es «el aviso
no declara el nivel de inglés», «el aviso no declara experiencia» y «la fuente no
publica el territorio admitido». Son huecos de datos en el aviso, no contradicciones
del perfil.

## 11. Límites de estos datos

Conviene tenerlos presentes antes de interpretar:

1. **La base no está en el repositorio.** Quien revise necesita su propia copia o
   los números de este informe; el script sólo corre contra una base local.
2. **El corpus es mayoritariamente de habla inglesa y de nivel EE. UU./Europa.**
   1.523 ofertas incompatibles son de América del Norte o Europa. Si el objetivo
   del perfil es remoto desde Argentina, buena parte del catálogo es ruido de
   origen, no ruido de clasificación.
3. **2.330 ofertas sin categoría** limitan cualquier lectura sobre el detector de
   categorías: puede estar fallando en recognising títulos válidos.
4. **La confianza es `baja` en el 99,7 %** del catálogo. La banda elegible no
   tiene respaldo de confianza alta.
5. **Este informe describe el estado actual, no el correctivo.** No se modificó
   ninguna regla.

## 12. Materia prima para la revisión

Para proponer las tres mejoras concretas que más aumenten la cantidad de
oportunidades realmente adecuadas sin admitir falsos positivos, el material
deliberadamente preparado es:

- este informe, con el desglose completo y reproducible;
- `docs/ANEXO_CASOS_ANONIMIZADOS.md`: los modos de falla, con ofertas sintéticas
  y sin nombres de empresa;
- `tests/test_clasificacion_casos_sinteticos.py`: el comportamiento actual
  Caracterizado en código, para que cualquier cambio se pueda contrastar;
- `buscador/rules.py`: la implementación del filtro duro.

Los casos que el anexo y las pruebas dejan sobre la mesa, y que son los puntos
de mayor rendimiento para una revisión:

| # | Modo de falla | Dónde se ve |
| --- | --- | --- |
| 1 | La fuente y el cuerpo se contradicen en territorio, y gana la fuente | caso `C` del anexo |
| 2 | El cuerpo declara alcance global pero el campo de la fuente no lo dice | caso `L` del anexo |
| 3 | La categoría no se reconoce en 2.330 ofertas (91,6 %) | §6 de este informe |
| 4 | La banda dudosa (22) se decide por datos ausentes, no por conflicto | §10 de este informe |
| 5 | «Formación» excluye por exigir título, sin mirar ni la disciplina ni el «preferred» | casos `E` y `F` del anexo |

## 13. Trazabilidad

- Todos los números: `tools/informe_clasificacion.py` contra
  `%LOCALAPPDATA%\BuscadorLaboral\data\buscador.db`, en `mode=ro`.
- Reglas del corte: `rules-3.1.0` (`buscador/config.py`, `RULES_VERSION`).
- Consultas y agregaciones: sólo `analyses` con `obsoleto=0`, `jobs`, `sources`,
  `observations` y `job_observations`.
- No se escribió en la base, ni en el código, ni en el scheduler. La búsqueda
  programada siguió su curso normal durante toda la lectura.
