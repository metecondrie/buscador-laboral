# Muestra de validación del ranking

25 ofertas reales tomadas de la base, elegidas para que puedas evaluar el criterio.
No están filtradas para que «queden bien»: incluyen los falsos positivos que reportaste
y títulos afines que quedaron descartados, para detectar también falsos negativos.

Cómo usarla: en el CSV, escribí en **veredicto** una de estas opciones y, si querés,
un comentario corto.

| Veredicto | Significado |
|---|---|
| `si` | Vale la pena postularse |
| `no` | No sirve (decime por qué en el comentario) |
| `duda` | Falta información para decidir |

Generada desde `buscador.db` con reglas "rules-2.0.0" y perfil real.

| # | Oferta | Empresa | Fuente | Modalidad | Elegibilidad | Compat. | Confianza | Por qué |
|---|---|---|---|---|---|---|---|---|
| 1 | Remote Data Entry Clerk | NoGigiddy | F01 | remote | eligible | 100 | media | remoto, territorio compatible y seniority acorde |
| 2 | Remote Office Assistant | Coalition Technologies | F11 | remote | eligible | 100 | alta | remoto, territorio compatible y seniority acorde |
| 3 | Clinical Data Manager | Penumbra | F04 | remote | doubtful | 81 | media | indicio en el cuerpo con 'reporting' (sin confirmar en el tí |
| 4 | Sales Operations Analyst | Calabrio | F04 | unknown | doubtful | 77 | media | la fuente no publica el territorio admitido |
| 5 | Consumer Support Specialist (Weekend Shift, Sunday - Thurs | Keeper Security | F01 | remote | doubtful | — | media | formación: bachelor s degree preferred |
| 6 | MSP Mac Help Desk Guru (work from home) | Ignition, Inc. | F01 | remote | doubtful | — | media | pide 5+ años y el perfil cubre sólo 0 % de las habilidades |
| 7 | Scaled Customer Success Manager | Dropbox | F01 | remote | doubtful | — | media | el título implica responsabilidad de gestión: Scaled Custome |
| 8 | Partner Operations Manager | Mecka | F04 | unknown | doubtful | — | baja | indicio en el cuerpo con 'reporting' (sin confirmar en el tí |
| 9 | Customer Success Associate | Voltus | F04 | remote | doubtful | — | media | región declarada no concluyente: Remote |
| 10 | Customer Support Specialist | Ultimate Marketing | F04 | unknown | doubtful | — | media | la fuente no publica el territorio admitido |
| 11 | Technical Customer Support | QuickMail | F04 | unknown | doubtful | — | media | la fuente no publica el territorio admitido |
| 12 | Manager, Scaled Customer Success Strategy & Operations | ramp | F14 | remote | doubtful | — | media | región declarada no concluyente: San Francisco, CA (remote) |
| 13 | Risk&AI Manager | Feedzai | F01 | remote | incompatible | — | baja | el título no es afín a las categorías del perfil |
| 14 | Paid Ads Specialist | Paid Ads Academy | F01 | remote | incompatible | — | baja | el título no es afín a las categorías del perfil |
| 15 | Software Engineer Infrastructure | Sodalis, Inc. | F04 | hybrid | incompatible | — | baja | el título corresponde a un rol fuera de las categorías del p |
| 16 | Agile Program Manager | Toptal | F01 | remote | incompatible | — | baja | el título no es afín a las categorías del perfil |
| 17 | Commercial Data Scientist | Doximity | F03 | onsite | incompatible | — | baja | presencial en USA: el perfil requiere remoto |
| 18 | Customer Support (Season Contractor) | CoinTracker | F03 | onsite | incompatible | — | baja | presencial en USA: el perfil requiere remoto |
| 19 | MEDICAL VIRTUAL ASSISTANT | Vital Virtuals Global HR | F01 | onsite | incompatible | — | baja | presencial en Latin America Only: el perfil requiere remoto |
| 20 | Product Owner | Zanda Health | F01 | remote | incompatible | — | baja | el título no es afín a las categorías del perfil |
| 21 | Contracts Manager Federal | Akicita Federal, LLC | F04 | remote | incompatible | — | baja | el título no es afín a las categorías del perfil |
| 22 | Offshore Virtual Executive Assistant to the CEO | Collective Residential | F01 | onsite | incompatible | — | baja | sin coincidencia con las diez categorías del perfil |
| 23 | Staff Technical Support Engineer (Web App) | Horizon3 | F01 | remote | incompatible | — | baja | el título declara un nivel superior al perfil: Staff Technic |
| 24 | Quality Analyst - Clinical Validation Auditor (CVA), Healt | EXL | F01 | onsite | incompatible | — | baja | sin coincidencia con las diez categorías del perfil |
| 25 | Client Success Manager | Bask Health | F01 | onsite | incompatible | — | baja | la fuente restringe la ubicación a North America Only |

## Qué mirar

1. ¿Las dos elegibles son realmente postulables desde Argentina, en remoto?
2. ¿Alguna dudosa debería ser elegible? (territorio o modalidad mal leídos)
3. ¿Alguna incompatible con título afín debería estar arriba? (falso negativo)
4. ¿La confianza declarada coincide con lo que ves en el aviso?

El CSV completo está en `docs/muestra-validacion.csv`.
