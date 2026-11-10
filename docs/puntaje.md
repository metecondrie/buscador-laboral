# Puntaje: sólo se cuenta lo que se puede comprobar (rules-3.0.0)

## El problema

En la ficha de *Remote Office Assistant* (Coalition) el desglose era:

| Componente | Puntos | Justificación que daba el sistema |
|---|---|---|
| Categoría / tareas | **25 / 25** | coincidencia en el título |
| Habilidades | **40 / 40** | dos habilidades mencionadas |
| Experiencia | **20 / 20** | «sin contradicción con el perfil» |
| Idioma / formación | **15 / 15** | «sin exigencia incompatible» |
| **Total** | **100 / 100** | confianza **alta** |

Tres de los cuatro bloques daban el máximo **por no encontrar información**. Es
decir: el sistema premiaba los avisos peor documentados. Un aviso que no dice
cuántos años pide ni qué formación exige sacaba más nota que uno que lo dice y
coincide.

## La regla nueva

Cada componente se puntúa en uno de **cuatro estados**:

| Estado | Significado | Puntos |
|---|---|---|
| `cumplido` | el aviso lo declara y el perfil lo satisface | proporcionales |
| `incumplido` | lo declara y el perfil no | 0 (suele excluir) |
| `desconocido` | el aviso no lo declara | **0** + incertidumbre |
| `no_aplicable` | el requisito no existe para esa oferta | fuera del denominador |

```
compatibilidad = 100 · Σ obtenido / (100 − Σ máximos no aplicables)
cobertura      = Σ máximos con datos / (100 − Σ máximos no aplicables)
```

| Componente | Máximo | Cómo se gana |
|---|---|---|
| `categoria_tareas` | 25 | título **y** tareas descritas en el cuerpo (15 si sólo título, 10 si sólo cuerpo) |
| `habilidades` | 40 | cobertura ponderada por nivel × amplitud (`min(1, distintas/3)`) |
| `experiencia` | 20 | años o seniority declarados y compatibles (12 si es excepción por competencias) |
| `idioma` | 8 | exigencia declarada y cumplida; 4 si el aviso está en inglés sin nivel |
| `formacion` | 7 | sólo si el aviso declara formación y se cumple |

«Cobertura» es la parte de la nota que se apoya en datos. Se muestra al lado del
puntaje y es lo que impide que un 40/100 parezca mejor que un 70/100 con más
evidencia.

## Antes y después, sobre los avisos reales

Evidencia completa en `tests/fixtures/casos_reales/` (texto original de cada aviso).

| Aviso | Antes | Después | Qué cambió |
|---|---|---|---|
| Remote Office Assistant · Coalition | eligible · **100,0** · alta | eligible · **75,7** · media | experiencia y formación sin datos y sólo 2 habilidades |
| Remote Data Entry Clerk · NoGigiddy | eligible · **100,0** · media | eligible · **42,3** · media | una sola habilidad, sin experiencia declarada |
| Technical Support Engineer · Alloy | eligible · **86,0** · alta | **doubtful** · 63,7 · media | el aviso exige visitas trimestrales y «may require travel» |
| Clinical Data Manager · Penumbra | incompatible (EE. UU.) | incompatible (EE. UU.) | sin cambios: ya estaba bien |
| Client Service Analyst · Bybit (turco) | incompatible **por categoría** | incompatible **por idioma** | el motivo real era el turco, no la categoría |

Sobre el catálogo completo (1 299 ofertas), con el mismo perfil:

| | rules-2.0.0 | rules-3.0.0 |
|---|---|---|
| Elegibles | 3 | 3 |
| Dudosas | 8 | **15** |
| Incompatibles | 1 288 | **1 281** |

Las 7 ofertas que pasaron de incompatibles a dudosas son avisos de atención al
cliente que antes se descartaban por categoría y ahora se reconocen («client
service», «livechat»). Las dudosas suben porque los viajes y la presencialidad
ocasional ahora se declaran en lugar de ignorarse.

## Efectos deliberados

- **Ya casi no hay avisos automáticos.** `worker._corresponde_aviso` exige
  compatibilidad ≥ 75, confianza distinta de baja y cobertura ≥ 0,7. Con el modelo
  nuevo, eso significa «aviso bien documentado y bien alineado». Es el
  comportamiento buscado: antes se avisaba de ofertas con 100/100 sustentado en
  ausencia de datos.
- **El orden cambia poco entre ofertas comparables**, porque todas pierden puntos
  por los mismos motivos. El orden fino lo siguen decidiendo las habilidades y la
  categoría.
- **`sin_datos` se muestra.** Si el diseño lo pinta igual que `cumplido`, la
  corrección se pierde en pantalla.

## Otros arreglos de la misma sesión

- **«1 year of experience» no se detectaba**: la expresión pedía «years» en plural.
  Ahora reconoce `1 year`, `2 yrs`, `3 años`.
- **Modalidad**: un aviso con región «Worldwide» y el texto «Remote.» se clasificaba
  como presencial en Worldwide y se descartaba. Ahora la cabecera manda y después
  el cuerpo.
- **Territorio**: el cuerpo puede imponer una restricción que la fuente no declara
  («must be eligible to live and work in the US»). Ahora esa restricción gana
  sobre un «Anywhere in the World».
- **Viajes y reubicación**: «may require travel», «onsite once a quarter» o
  «must relocate» dejan la oferta en dudosas (o incompatible si exige mudarse).
- **Vigencia**: un aviso de más de 45 días sin fecha de cierre ya no se declara
  `open`. La fuente puede conservarlo; el sistema no afirma que siga abierto.

## Cómo se prueba

```bat
.venv\Scripts\python.exe -m pytest tests\test_puntaje_evidencia.py -q   :: el modelo
.venv\Scripts\python.exe -m pytest tests\test_casos_reales.py -q        :: los 5 avisos
.venv\Scripts\python.exe -m pytest tests\test_rules.py tests\test_ranking_regresiones.py -q
```
