# Muestra de validación · versión anonimizada

Muestra de **44 ofertas**, sacada del catálogo clasificado con `rules-3.1.0`.

**No contiene datos reales**: sin empresa, sin título del puesto, sin URL y
sin identificador de aviso. La versión con los datos originales no se
publica; queda sólo en el proyecto de trabajo.

Lo que sí está es lo que hace falta para revisar la clasificación:
fuente, modalidad, región declarada, veredicto, compatibilidad, confianza
y el motivo exacto del veredicto.

## Cómo usarla

| Veredicto | Significado |
|---|---|
| `si` | Vale la pena postularse |
| `no` | No sirve (anotá por qué en el comentario) |
| `duda` | Falta información para decidir |

El CSV (`docs/muestra-validacion.csv`) tiene una columna `veredicto` y otra
`comentario`, vacías, para que puedas anotar tu lectura sin tocar nada más.

## Contenido de la muestra

| Bloque | Ofertas | Qué es |
|---|---:|---|
| Elegibles | 2 | las únicas que llegan a decisión sin dudas |
| Dudosas | 22 | la banda accionable: el motor no pudo decidir |
| Incompatibles | 20 | muestra estratificada, 4 por dimensión principal de descarte |

## La muestra

| # | Fuente | Modalidad | Región | Veredicto | Compat. | Conf. | Dimensión | Motivo |
|---|---|---|---|---|---:|---|---|---|
| 1 | F01 | remote | Anywhere in the World | eligible | 35.7 | media | - | remoto, territorio compatible y seniority acorde |
| 2 | F11 | remote | Worldwide | eligible | 62.3 | media | - | remoto, territorio compatible y seniority acorde |
| 3 | F01 | remote | Latin America Only | doubtful | — | baja | - | exige inglés fluido o nativo; el perfil declara un nivel inferior… |
| 4 | F01 | remote | Anywhere in the World | doubtful | 25.7 | media | - | pide 4+ años y el perfil cubre sólo 50 % de las habilidades |
| 5 | F01 | remote | Anywhere in the World | doubtful | — | baja | - | pide 5+ años y el perfil cubre sólo 0 % de las habilidades |
| 6 | F01 | remote | Anywhere in the World | doubtful | — | baja | - | el título implica responsabilidad de gestión: <puesto> |
| 7 | F03 | remote | Argentina,  Hong Kong,  Singapore,  UAE | doubtful | — | baja | - | pide 3+ años y el perfil cubre sólo 0 % de las habilidades |
| 8 | F02 | remote | Guatemala | doubtful | — | baja | - | región declarada no concluyente: Guatemala |
| 9 | F04 | unknown | — | doubtful | — | baja | - | indicio en el cuerpo con 'reporting' (sin confirmar en el título) |
| 10 | F04 | remote | Ohio | doubtful | — | baja | - | indicio en el cuerpo con 'customer support' (sin confirmar en el … |
| 11 | F04 | remote | Remote | doubtful | — | baja | - | región declarada no concluyente: Remote |
| 12 | F04 | remote | — | doubtful | — | baja | - | la fuente no publica el territorio admitido |
| 13 | F04 | remote | — | doubtful | — | baja | - | la fuente no publica el territorio admitido |
| 14 | F10 | unknown | Munich | doubtful | — | baja | - | región declarada no concluyente: Munich |
| 15 | F03 | remote | Canada,  USA | doubtful | — | baja | - | la etiqueta enumera países pero el aviso declara trabajo desde cu… |
| 16 | F03 | remote | LATAM,  Canada,  USA | doubtful | 20.7 | media | - | indicio en el cuerpo con 'reporting' (sin confirmar en el título) |
| 17 | F01 | remote | Anywhere in the World | doubtful | 42.3 | media | - | el aviso menciona zonas horarias sin aclarar si exige residencia … |
| 18 | F02 | remote | Argentina, Colombia | doubtful | 29.0 | media | - | el título implica responsabilidad de gestión: <puesto> |
| 19 | F02 | remote | Bulgaria | doubtful | — | baja | - | región declarada no concluyente: Bulgaria |
| 20 | F10 | remote | Hamburg (remote) | doubtful | 29.0 | media | - | región declarada no concluyente: Hamburg (remote) |
| 21 | F03 | unknown | APAC | doubtful | 29.0 | media | - | región declarada no concluyente: APAC |
| 22 | F10 | unknown | Berlin | doubtful | — | baja | - | región declarada no concluyente: Berlin |
| 23 | F08 | remote | Worldwide | doubtful | — | baja | - | sin habilidades declaradas: información insuficiente |
| 24 | F02 | remote | Argentina | doubtful | — | baja | - | indicio en el cuerpo con 'reporting' (sin confirmar en el título) |
| 25 | F01 | remote | Anywhere in the World | incompatible | — | baja | categoria | sin coincidencia con las diez categorías del perfil |
| 26 | F01 | remote | Latin America Only | incompatible | — | baja | categoria | el título corresponde a un rol fuera de las categorías del perfil |
| 27 | F01 | remote | Latin America Only | incompatible | — | baja | categoria | sin coincidencia con las diez categorías del perfil |
| 28 | F01 | remote | Anywhere in the World | incompatible | — | baja | categoria | el título corresponde a un rol fuera de las categorías del perfil |
| 29 | F01 | unknown | USA Only | incompatible | — | baja | idioma | exige título terminado: título universitario obligatorio |
| 30 | F01 | remote | Anywhere in the World | incompatible | — | baja | idioma | exige turkish, un idioma que el perfil no declara |
| 31 | F01 | remote | Anywhere in the World | incompatible | — | baja | idioma | exige título terminado: título universitario obligatorio |
| 32 | F01 | remote | Anywhere in the World | incompatible | — | baja | idioma | exige czech, un idioma que el perfil no declara |
| 33 | F03 | onsite | EMEA,  LATAM,  Canada,  USA | incompatible | — | baja | modalidad | presencial en EMEA,  LATAM,  Canada,  USA: el perfil requiere remoto |
| 34 | F03 | onsite | Argentina | incompatible | — | baja | modalidad | presencial en Argentina: el perfil requiere remoto |
| 35 | F04 | onsite | Colorado | incompatible | — | baja | modalidad | presencial en Colorado: el perfil requiere remoto |
| 36 | F10 | onsite | Parsdorf, Bavaria | incompatible | — | baja | modalidad | presencial en Parsdorf, Bavaria: el perfil requiere remoto |
| 37 | F01 | remote | Latin America Only | incompatible | — | baja | seniority | el título declara un nivel superior al perfil: <puesto> |
| 38 | F01 | remote | Anywhere in the World | incompatible | — | baja | seniority | el título declara un nivel superior al perfil: <puesto> |
| 39 | F01 | remote | Remote | incompatible | — | baja | seniority | el título declara un nivel superior al perfil: <puesto> |
| 40 | F01 | remote | Harju maakond | incompatible | — | baja | seniority | el título declara un nivel superior al perfil: <puesto> |
| 41 | F01 | remote | North America Only | incompatible | — | baja | territorio | la fuente restringe la ubicación a North America Only |
| 42 | F01 | remote | USA Only | incompatible | — | baja | territorio | la fuente restringe la ubicación a USA Only |
| 43 | F01 | unknown | USA Only | incompatible | — | baja | territorio | la fuente restringe la ubicación a USA Only |
| 44 | F01 | unknown | USA Only | incompatible | — | baja | territorio | la fuente restringe la ubicación a USA Only |

## Qué mirar

1. ¿Las 2 elegibles son realmente postulables en remoto desde Argentina?
2. ¿Alguna dudosa debería ser elegible? (territorio o modalidad mal leídos)
3. ¿Alguna incompatible con título afín debería estar arriba? (falso negativo)
4. ¿La confianza declarada coincide con lo que se ve en el aviso?

El estado completo del catálogo y su desglose están en
`docs/INFORME_CLASIFICACION.md`; los modos de falla, con casos sintéticos,
en `docs/ANEXO_CASOS_ANONIMIZADOS.md`.
