# 3. Recomendaciones de ajuste — 07/11/2026

> Repo `buscad0r @ a97b9b3` · esquema 11 · `rules-3.0.0`.
> **Propuestas solamente.** No se modificó el clasificador ni ningún archivo de código.
> Cada ítem indica el problema, el cambio propuesto, dónde aplicaría y cómo medirlo.

## Prioridad 1 — corrigen pérdidas de oportunidades

**R1 · No truncar la evidencia de modalidad a 4 000 caracteres**
*Problema:* 33 descartes por "presencial …" dicen "remote" más adelante en el aviso; el caso más
valioso (Drop Zero Digital, USD 2 100/mes, "Based in Argentina") se pierde por eso.
*Propuesta:* buscar indicios de modalidad en el texto completo (o al menos 12 000 caracteres) y
dar prioridad a frases explícitas (`remote-first`, `100% remote`, `fully remote`, `work from home`,
`home based`) sobre la ausencia de la palabra en el encabezado. Si la única señal es un `territorio`,
clasificar como **dudosa / revisar**, nunca como `presencial` firme.
*Dónde:* heurística de modalidad del motor de reglas (futuro cambio, fuera de esta auditoría).
*Métrica:* los 25 casos de `modalidad_presencial_con_territorio_remoto` dejan de figurar como
`presencial`; Drop Zero Digital aparece en elegibles o dudosas.

**R2 · Tratar `Worldwide`, `LATAM`, `Latin America Only`, `Home based`, `Global` como indicios remotos**
*Problema:* la lista de indicios remotos contiene `anywhere` pero no `worldwide` ni `latam`; por eso
"presencial en Worldwide" y "presencial en Latin America Only".
*Propuesta:* ampliar el vocabulario y, cuando la región sea un alcance y no una ciudad, no inferir
`onsite` por defecto.
*Dónde:* vocabulario de modalidad/territorio.
*Métrica:* 0 descartes con motivo que empiece por "presencial en Worldwide/LATAM…".

**R3 · Separar territorio de modalidad en el modelo de datos**
*Problema:* `territorio = "Remote"` (Voltus) se interpreta como "región no concluyente"; el campo
de la fuente mezcla dónde se contrata y cómo se trabaja.
*Propuesta:* dos campos independientes — `alcance_geografico` (argentina / internacional /
mundial / restringido / desconocido) y `modalidad` (remote / hybrid / onsite / unknown) — y que la
interfaz los muestre por separado. El clasificador ya calcula un `alcance`; hoy no llega a la vista.
*Dónde:* ingesta + plantilla de ficha.
*Métrica:* ninguna oferta con `territorio = "Remote"` figura como "región no concluyente".

**R4 · Detectar restricciones por zona horaria**
*Problema:* "Must be in EST or CT time zone only" (Calabrio), "Eastern or Pacific time zones"
(Ignition), "work during MST time zone hours" (Alloy) pasan como compatibles o dudosas benignas.
*Propuesta:* patrones para `EST/CT/MST/PST/Eastern/Pacific/CET/UK overlap/US business hours` con
`only`/`must`/`required`; clasificar como **territorio restringido** (o duda fuerte si el texto dice
"solo se requiere solape horario"). Distinguir "solape de horario" (compatible desde Argentina) de
"residencia obligatoria en esa zona" (incompatible).
*Dónde:* detector de restricciones en el cuerpo.
*Métrica:* Calabrio e Ignition pasan a `incompatible` con motivo explícito; MarketFully y QuickMail
siguen siendo compatibles porque sólo piden solape.

**R5 · Detectar viajes y presencialidad periódica**
*Problema:* "Ability to travel twice a year… up to two weeks" (Canonical) y "Expect regular travel
for customer onsite" (ElevenLabs) no se detectan; Alloy sí. La restricción declarada del perfil
excluye traslados.
*Propuesta:* ampliar patrones (`travel twice a year`, `regular travel`, `travel up to N%`,
`onsite once a quarter`, `X days a week in office`, `company events`). Escalar a exclusión dura
cuando la frecuencia esté declarada; a duda cuando diga "occasional".
*Dónde:* detector de restricciones laborales.
*Métrica:* Canonical, ElevenLabs y Pennylane quedan excluidas por presencialidad/viajes.

## Prioridad 2 — reducen ruido y falsas dudas

**R6 · No equiparar `Mid-level` con "gestión"**
*Problema:* el campo `seniority = Mid-level` dispara "el título implica responsabilidad de gestión"
en títulos como "Customer Support Specialist".
*Propuesta:* reservar el marcador de gestión para `manager/director/head/lead/principal/staff` en el
**título**, y tratar el `seniority` de la fuente como dato separado (`mid-level` → duda de
experiencia, no de jerarquía). Corregir el texto del motivo para que cite la evidencia real.
*Dónde:* evaluación de experiencia.
*Métrica:* desaparece el motivo "el título implica responsabilidad de gestión: … Specialist".

**R7 · "Título universitario" con equivalencia**
*Problema:* 44 exclusiones; 2 de 6 revisadas dicen "or equivalent".
*Propuesta:* si el aviso admite `equivalent experience`, pasar a **dudosa** en vez de excluir; si
dice `or equivalent degree`, mantener exclusión pero con motivo matizado.
*Dónde:* evaluación de formación.
*Métrica:* ~15 ofertas cambian de `incompatible` a `doubtful` con motivo de equivalencia.

**R8 · Puntaje de auditoría para los descartes**
*Problema:* las 1 430 incompatibles tienen `score = NULL` y `confianza = baja`; es imposible
priorizar una revisión humana.
*Propuesta:* calcular un **puntaje de afinidad independiente de la elegibilidad** (categoría,
habilidades, experiencia) y guardarlo aunque la oferta esté excluida. La elegibilidad sigue siendo
un filtro duro; el puntaje sólo ordena la cola de revisión.
*Dónde:* persistencia de análisis + columna en Diagnóstico.
*Métrica:* se puede listar "top 20 descartadas por afinidad" y Drop Zero Digital aparece arriba.

**R9 · Estado "por revisar" en lugar de forzar tres categorías**
*Problema:* "sin habilidades declaradas", "territorio desconocido" y "modalidad no declarada"
terminan como dudosas con confianza baja y puntaje nulo, mezcladas con casos realmente probables.
*Propuesta:* cuarta etiqueta `uncertain / por revisar` para información insuficiente, con su propia
cola. No se declara ni compatible ni incompatible sin evidencia.
*Dónde:* modelo de elegibilidad y pestañas.
*Métrica:* las 6 dudosas con `score = NULL` pasan a "por revisar" y las dudosas restantes tienen
puntaje.

## Prioridad 3 — frescura, salario y calidad de datos

**R10 · Frescura explícita y conservadora**
*Problema:* NoGigiddy (`publicado_en` de hace 12 meses, `estado_vigencia = unknown`, ausente de las
últimas corridas) figura como **elegible**; 18 de 19 dicen `open` sin verificación del empleador.
*Propuesta:* mostrar siempre cuatro fechas distintas — publicación, primera detección, última
detección y vencimiento declarado — y degradar a "vigencia no confirmada" (no elegible para avisos)
a toda oferta ausente en 2 corridas consecutivas o con `estado_vigencia = unknown`. No usar
`validThrough` de la plataforma como fecha de cierre real sin marcar su origen.
*Dónde:* ingesta, diagnóstico y emisión de avisos.
*Métrica:* ninguna oferta ausente en 2 corridas aparece en elegibles ni genera notificación.

**R11 · Normalización del salario publicado**
*Problema:* 7 de 354 salarios tienen período ausente o rango > 5×; Coalition guarda
`52000–353000 USD` cuando el aviso dice USD 15–25/h.
*Propuesta:* exigir moneda **y** período para considerar el dato comparable; descartar rangos con
`max/min > 5`; guardar junto al valor el fragmento de texto del que se extrajo; mostrar "no
comparable" cuando falte algo. Nunca mezclar salario de la API de la fuente con el del texto sin
indicar origen.
*Dónde:* parser de salario y ficha de oferta.
*Métrica:* 0 salarios comparables sin período; el valor de Coalition coincide con el aviso.

**R12 · Marcar tokens anti-spam del texto**
*Problema:* 3 avisos de RemoteOK contienen instrucciones ("mencioná la palabra X", "etiquetá Y")
dentro de la descripción.
*Propuesta:* detector que marque ese fragmento como artefacto de plataforma, lo excluya de
requisitos y **nunca lo envíe a un modelo de IA** si se habilitara el análisis con IA.
*Dónde:* ingesta / limpieza de texto.
*Métrica:* esas cadenas no aparecen como requisitos ni en el payload de notificaciones.

**R13 · Avisos: sólo recomendaciones vigentes**
*Problema:* la bandeja conserva avisos emitidos con `rules-2.0.0` cuyo puntaje vigente es otro
(Alloy 86 → 63,7). Ya está resuelto en la interfaz; falta que la emisión no se repita.
*Propuesta:* no emitir un aviso si la oferta no fue vista en la última corrida, si
`estado_vigencia != open` o si la elegibilidad vigente no es `eligible`. Conservar el histórico.
*Dónde:* condición de emisión de avisos.
*Métrica:* 0 avisos nuevos sobre ofertas ausentes del último feed.

**R14 · Preferencias explícitas del perfil para turnos y guardias**
*Problema:* MarketFully (guardias nocturnas y fines de semana) y Bybit (turnos rotativos con
franja 12am–9am) se evalúan igual que un puesto de lunes a viernes.
*Propuesta:* agregar al perfil, como datos declarados, `acepta_guardias`, `acepta_turnos_rotativos`
y `franja_horaria_preferida`, y usarlos como filtro blando (duda) en vez de descubrirlos a mano.
*Dónde:* perfil y capa de presentación de requisitos. No requiere cambiar la fórmula de puntaje.
*Métrica:* esas dos ofertas muestran el conflicto de disponibilidad antes de recomendarlas.

## Orden sugerido y criterio de aceptación

1. R1 + R2 + R3 (modalidad y territorio) → recuperan la oportunidad perdida.
2. R4 + R5 + R6 (restricciones y seniority) → limpian las dudosas inviables.
3. R8 + R9 (puntaje de auditoría y cola "por revisar") → hacen auditables los 1 430 descartes.
4. R10 + R11 + R12 + R13 + R14 (datos y frescura).

Tras aplicar 1–3, la auditoría debería poder repetirse con estos resultados: **Drop Zero Digital**
en elegibles/dudosas, **Calabrio e Ignition** en incompatibles, **Canonical y Pennylane** excluidas
por presencialidad, y una cola de descartes ordenable por afinidad. Ninguna de estas propuestas se
implementó en esta tarea.
