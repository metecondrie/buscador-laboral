# 2. Análisis de falsos negativos — 07/11/2026

> Repo `buscad0r @ a97b9b3` · esquema 11 · `rules-3.0.0` · base SHA-256 `3bfc2319…`.
> Universo: 1 430 ofertas `incompatible`. Solo lectura; sin cambios al clasificador.

## Diseño de la muestra

Muestra **estratificada y determinista** de 99 ofertas (6,9 % del universo), guardada en
`datos/muestra-incompatibles.csv`. En vez de un muestreo aleatorio ciego, se tomaron todos los
casos de los estratos sospechosos y cupos ordenados por `id` en el resto:

| Estrato | Cupo | Filas | Motivo del estrato |
|---|---:|---:|---|
| `modalidad_presencial_con_territorio_remoto` | 25 | 25 | Descartes que dicen "presencial en Worldwide/LATAM/Home based" |
| `argentina_en_territorio` | 15 | 15 | Argentina declarada y aun así descartada |
| `titulo_afin_descartado_por_categoria` | 12 | 12 | Títulos con *analyst/data/support/assistant/operations* descartados por categoría |
| `remote_solo_despues_de_4000` | 12 | 7 | "remote" aparece en el texto pero fuera de los primeros 4 000 caracteres |
| `categoria` | 10 | 10 | Control del motivo de descarte más frecuente no geográfico |
| `geografia` | 10 | 8 | Control de restricciones territoriales |
| `exige_titulo_universitario` | 8 | 8 | Control de exclusiones por título universitario |
| `exige_idioma` | 8 | 8 | Control de exclusiones por idioma |
| `uno_por_fuente` | 14 | 6 | Al menos una oferta por fuente, para cubrir adaptadores |

La superposición entre estratos explica que 99 filas < suma de cupos. Para cada fila se registró
`senial_remote_total` y `senial_remote_primeros_4000` contando `\bremote\b` en el texto completo
y en su prefijo: 62 de 99 contienen la palabra "remote"; en **22 de la muestra** esa señal está
**sólo después** de los 4 000 caracteres.

## Distribución de los 1 430 descartes

| Familia | Cantidad | Ejemplo de motivo |
|---|---:|---|
| Geografía / modalidad | ≈ 900 | "la fuente restringe la ubicación a United States" (239), "USA" (97), "USA Only" (28), ciudades de EE. UU. (27), Canada (26) |
| Presencialidad / híbrido | 202 | "presencial en Hamburg…", "híbrido fuera de tu zona" (23) |
| Categoría | 162 | "el título no es afín…" (82), "rol fuera de las categorías…" (65), "sin coincidencia…" (15) |
| Idioma no declarado | 51 | alemán (24), francés (9), mandarín (3), ruso (2), portugués (2) |
| Título universitario | 44 | "degree is required" (28), "bachelor s degree required" (14) |

**Dato estructural:** las 1 430 descartadas tienen `score = NULL` y `confianza = baja`
(100 %). El clasificador sale antes de puntuar cuando hay exclusión dura. Consecuencia: no existe
ninguna forma de ordenar los descartes para revisarlos; un falso negativo con 90 % de afinidad
es indistinguible de un aviso de ingeniería senior en Alemania.

## Errores sistemáticos encontrados

### E1 · Modalidad mal inferida por truncar el texto a 4 000 caracteres

`rules._modalidad` busca "remote" en `texto[:4000]`; si no lo encuentra y hay región, asume
`onsite`. **33** descartes por "presencial en …" tienen la palabra "remote" en el aviso pero
después de ese corte. De ellos, **25** tienen además un territorio claramente remoto
(`Worldwide` 6, `Home based - Worldwide` 6, `Europe, LATAM, APAC…` 5, `Latin America Only` 2,
`EMEA/LATAM/…` 2, `LATAM` 3, `Berlin | Global Team` 1).
Ejemplo verificable: `job_00fb5037fd1c930c360d` (Drop Zero Digital) dice "Based in Argentina" y
"2100 USD per month" recién en la segunda mitad del texto; el campo `territorio = Latin America
Only` no está en la lista de indicios remotos, así que se descartó como presencial.

Casos recuperados por este error: **Drop Zero Digital** (apta), **Elavate UGC Coordinator**
(remota LATAM, pero 2+ años, inglés fluido y categoría ajena), **ElevenLabs Deployment
Strategist – Argentina** ("remote-first … anywhere in Argentina", pero 3+ años y viajes regulares).
Los otros 22 son en su mayoría ingenierías senior (6+ años, DevOps, Swift, Magento) que seguirían
descartadas por experiencia aunque se corrigiera la modalidad.

### E2 · El campo `seniority` de la fuente se interpreta como "gestión"

`_SENIORITY_DUDA` incluye `mid level`; `_experiencia` lo aplica a `título + seniority` y emite
**"el título implica responsabilidad de gestión: …"**. Con `seniority = Mid-level`
(Himalayas, RemoteOK) el mensaje culpa al título. Afecta al menos a MarketFully y Go Lean Health:
"Customer Support Specialist" y "Bilingual Back-Office…" no son cargos de gestión. La regex no
contiene "specialist"; el problema es el mensaje y la equiparación *mid-level ≈ manager*.

### E3 · Restricciones por zona horaria no detectadas

El detector de restricciones en el cuerpo busca frases como "must be eligible to work in…".
No reconoce **"Must be in EST or CT time zone only"** (Calabrio, dudosa 66,1),
**"Eastern or Pacific time zones"** (Ignition), **"work during MST time zone hours"** (Alloy) ni la
ventana "8am–8pm US". Calabrio e Ignition son, en la práctica, puestos restringidos a EE. UU. y
deberían estar entre los incompatibles, no entre las dudosas. Es un error en **ambas direcciones**:
infla las dudosas y deja pasar candidaturas inviables.

### E4 · Viajes y presencialidad periódica detectados a medias

Alloy sí fue marcada por "once a quarter"/"quarterly onsite" (correcto). Canonical
(**"Ability to travel twice a year, for company events up to two weeks long"**) y ElevenLabs
(**"Expect regular travel for customer onsite"**) no lo fueron. La lista de patrones no cubre
"travel twice a year" ni "regular travel".

### E5 · "Título universitario" sin considerar equivalencia

44 descartes por `degree is required` / `bachelor s degree required`. En 2 de los 6 revisados el
aviso dice **"degree required; MBA or equivalent"** y **"or equivalent"**. Extrapolado: ~15 de los
44 podrían ser elegibles por experiencia equivalente. Son puestos senior (Director, Head of
Planning), por lo que el impacto práctico es bajo, pero el filtro es demasiado tajante.

### E6 · Categoría: pocos falsos negativos reales

Sólo **4** títulos con palabras afines fueron descartados por categoría: SOC Analyst,
"Analyst I, Falcon Complete" (CrowdStrike), "Administrative Assistenz" (alemán) y "Brand
Protection & Marketplace Compliance Analyst". Los cuatro son efectivamente otros dominios
(ciberseguridad, alemán, compliance). El filtro de categoría **no parece** una fuente importante
de falsos negativos.

### E7 · Territorio "compatible" mal rotulado

291 descartadas tienen en `territorio` cadenas como `Worldwide`, `Anywhere`, `LATAM`,
`Latin America`, `Global`. 15 mencionan **Argentina** explícitamente. Varias aparecen como
"presencial en …" (E1) o "región declarada no concluyente: Remote / Guatemala / Berlin Office".
El caso "Voltus – Customer Success Associate" tiene `territorio = Remote` y se marca
"no concluyente": la etiqueta dice modalidad, no geografía. Falta separar ambos conceptos.

### E8 · Calidad de datos

- **Salario:** 354 ofertas con `salario_json`; 7 con período ausente o rango > 5×. El caso más
  grave es Coalition Technologies: guardado `52000–353000 USD` sin período, mientras el aviso
  publica **USD 15–25/hora** para cuatro estados. El dato estructurado no viene del texto.
- **Frescura:** `estado_vigencia = open` en 18 de 19 elegibles/dudosas; NoGigiddy es `unknown`
  y tiene fecha de publicación de hace 12 meses. La última detección es mejor señal que el estado.
- **Tokens anti-spam:** al menos 3 avisos de RemoteOK (Voltus, Destination Careers, QuickMail)
  incluyen instrucciones del tipo "mencioná la palabra X y etiquetá Y" dentro del texto. Son
  artefactos de la plataforma; conviene marcarlos y no tratarlos como requisitos del puesto
  (mucho menos enviarlos a un modelo de IA).

## Veredicto

**Falsos negativos reales (oportunidades perdidas): 3**, de los cuales sólo **1** es una
oportunidad de primer nivel: **Drop Zero Digital**. Los otros dos (Elavate, ElevenLabs) quedan
excluidos por experiencia, idioma, categoría o viajes una vez leídos completos.

**Falsos positivos de tolerancia (deberían estar descartadas y figuran como dudosas): 2**
(Calabrio, Ignition) y 2 con motivos incompletos (Canonical, VXI).

**Zona gris cuantificada:** 25–33 descartes por modalidad mal inferida y ~15 por equivalencia de
título universitario. No todos son oportunidades, pero hoy son invisibles para cualquier revisión
humana porque no tienen puntaje.

Ver `03-recomendaciones.md` para las propuestas de ajuste, sin tocar el clasificador.
