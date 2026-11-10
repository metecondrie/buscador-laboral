"""Elegibilidad, compatibilidad y confianza por reglas (rules-3.0.0).

Tres dimensiones **separadas**, porque mezclarlas es lo que producía los errores
que el usuario reportó:

1. **Elegibilidad** (`eligible` / `doubtful` / `incompatible`): ¿puede postularse
   desde Argentina, en su modalidad, con su seniority? Es un filtro duro.
2. **Compatibilidad** (`compatibilidad`, 0–100): qué tan cerca está el puesto de
   su perfil profesional. Puede ser alta en un puesto no elegible; nunca se
   muestra sin la elegibilidad al lado.
3. **Confianza** (`alta` / `media` / `baja`): cuánta información real hay.

## Fórmula (rules-3.0.0)

Cada componente se puntúa **sólo con evidencia**, en uno de cuatro estados:

| Estado | Qué significa | Puntos |
|---|---|---|
| `cumplido` | el aviso declara el requisito y el perfil lo satisface | proporcionales |
| `incumplido` | lo declara y el perfil no lo satisface | 0 (suele excluir) |
| `desconocido` | el aviso no lo declara | **0** y queda como incertidumbre |
| `no_aplicable` | el requisito no existe para esta oferta | sale del denominador |

```
compatibilidad = 100 · Σ obtenido / (100 − Σ máximos no aplicables)
cobertura      = Σ máximos con datos / (100 − Σ máximos no aplicables)
```

Componentes y máximos: `categoria_tareas` 25 · `habilidades` 40 · `experiencia`
20 · `idioma` 8 · `formacion` 7.

`cobertura` es la parte de la nota que se apoya en datos; `compatibilidad` es el
grado de coincidencia **verificado**. Un aviso que no dice nada de experiencia ni
de formación no puede sacar 100: saca lo que se pudo comprobar y queda con
cobertura baja y confianza baja.

### Qué cambió respecto de rules-2.0.0

- **No se dan puntos por ausencia de información.** Antes, «no se declara
  seniority» daba 20/20 y «no se exige formación» daba 7/7: 27 puntos por no
  saber nada. Ahora esos componentes valen 0 y quedan como incertidumbre.
- **Categoría y tareas se separan.** El título por sí solo ya no da 25/25: da 15
  y avisa que el cuerpo no describe tareas de la categoría. Los 25 exigen
  coincidencia en el título **y** evidencia de tareas en el texto.
- **Habilidades se pondera por amplitud.** Un aviso que menciona una sola
  habilidad no puede llenar los 40 puntos: la cobertura se multiplica por
  `min(1, distintas/3)`, porque una sola mención es un dato, no una medición.
- **Idioma deja de ser un supuesto.** Un aviso en inglés sin nivel declarado da
  crédito parcial (no 8/8), y un requisito explícito de un idioma que el perfil
  no habla (turco, checo, alemán…) excluye en lugar de ignorarse.
- **Formación explícita o nada.** «Degree required» excluye (el perfil no tiene
  título terminado); «preferred» deja dudosa; el silencio vale 0, no 7.

Correcciones que se conservan de rules-2.0.0: la modalidad remota es requisito;
una categoría detectada sólo en el cuerpo nunca da puntaje pleno; títulos de
ingeniería o diseño no caen en «VA/Data Entry» por una mención suelta; «manager»
o «senior» en el título impiden tratarlo como junior; sin habilidades detectadas
no hay puntaje; un aviso de más de 45 días sin cierre no se declara abierto.

### Fase 1B (corrección de regresiones, sin cambio de RULES_VERSION)

Se separan tres lecturas que antes se contaminaban entre sí:

- **Territorio**: «Anywhere in X» se resuelve por X, no por la palabra
  «Anywhere»; una restricción explícita del cuerpo siempre manda sobre la
  etiqueta de la fuente, incluso cuando dice «Argentina». Se reconocen «US
  only», «US-based candidates only», autorización de trabajo y husos horarios
  obligatorios. Las preferencias horarias no excluyen. Los códigos ISO se
  interpretan con contexto (AR = Argentina, no Arkansas).
- **Modalidad**: presencialidad explícita en el título; negaciones («Not a
  remote position», «No onsite requirement») y menciones ajenas al puesto
  (entrevistas, estacionamiento) dejan de inferir presencialidad. Los términos
  de modalidad se sacaron de las reglas de territorio.
- **Idioma**: cada cláusula se evalúa por separado; la optatividad de un idioma
  ya no anula la obligatoriedad de otro y las negaciones cancelan obligaciones
  del mismo idioma. Los niveles CEFR se comparan con el nivel real del perfil.

`RULES_VERSION` queda en `rules-3.0.0` a propósito: el cambio de versión (y la
consiguiente invalidación/reclasificación controlada de `analyses`) se reserva
para la activación posterior. Hasta entonces el código nuevo sólo afecta a
clasificaciones que se calculen de cero.

### Fase 1C (reparación estructural, sin cambio de RULES_VERSION)

La auditoría adversarial mostró que seguir sumando regex no alcanzaba: los
defectos venían de **mezclar dimensiones** y de tomar decisiones con la primera
coincidencia. La reparación separa extracción y decisión:

1. **Extracción tipada.** Funciones pequeñas devuelven hechos (`Requisito`,
   `Clausula`, `AnalisisIdiomas`), no veredictos. Normalización controlada,
   segmentación por cláusula y detección explícita de negación, optatividad y
   contradicción.
2. **Decisión por precedencia.** Territorio → modalidad → residencia/legal →
   idiomas → experiencia/seniority → formación → elegibilidad. Cada capa
   produce un estado (`ok` / `duda` / `excluye`) y la elegibilidad final toma el
   peor: una evidencia explícita de incompatibilidad nunca se compensa con otro
   campo favorable.
3. **Reglas de alcance.** Un país explícito gana a un topónimo argentino; la
   negación se aplica sólo a la restricción que niega; un huso argentino (ART)
   no es una residencia extranjera; beneficios, entrevistas y contexto
   tecnológico no son modalidad laboral; cada idioma se evalúa por separado y el
   estado global es el peor de todos; edad, antigüedad de empresa y años con una
   herramienta no son años de experiencia laboral.

Ante falta de información se devuelve `doubtful`, no se inventan requisitos.

### Fase 1D (corrección focalizada, sin cambio de RULES_VERSION)

La auditoría adversarial posterior encontró que la precedencia era correcta pero
la EXTRACCIÓN seguía perdiendo matices del lenguaje. Se corrigen las causas:

- **Alcance del modificador.** La negación y la preferencia se aplican a la
  cláusula que modifican; «no agencies please, US only» no niega el territorio.
  «us» pronombre se distingue de «US» país por el contexto, no por una lista de
  excepciones.
- **Disyunción.** `or` / `o` / lista con «or» final declara ALTERNATIVAS, tanto
  de idiomas como de modalidad; `and` declara requisitos acumulativos. Una
  alternativa satisface el requisito si algún miembro lo satisface. Ante
  alternativas de modalidad sin evidencia de que el remoto sea completo, se
  devuelve `doubtful` en lugar de imponer presencialidad.
- **Contradicción.** Un mismo idioma exigido y negado, o una formación exigida y
  eximida, no se resuelve ni como cumplimiento ni como descarte: queda marcado
  para revisión humana.
- **Requisito legal y husos.** Permiso de trabajo (obligatorio vs. preferido) y
  zona horaria (residencia vs. disponibilidad) se extraen como hechos separados.
- **Límites de extracción.** Años de experiencia de dos dígitos altos, techo de
  puntuación alcanzable y rama inalcanzable de `_experiencia`.

### Fase 1E (corrección focalizada, sin cambio de RULES_VERSION)

Tres defectos reproducidos sobre 2.399 ofertas reales:

- **D1 · Regiones multipaís.** Una etiqueta que enumera países ADMITIDOS y
  contiene Argentina/LATAM/Américas no se descarta por nombrar también otros
  países. Sólo un marcador explícito («only», «must be based») convierte la
  lista en residencia obligatoria. Una contradicción sin resolver entre la
  etiqueta y el cuerpo se aparta como `doubtful`.
- **D2 · Precedencia.** Las restricciones obligatorias (cuerpo, título,
  etiqueta) se deciden ANTES que los permisos preferidos y las preferencias de
  huso. Las preferencias no anulan exclusiones; sin exclusión siguen generando
  duda. Residencia, disponibilidad horaria y menciones incidentales se separan.
- **D3 · Alcance de categoría.** «operations analyst» no convierte un puesto de
  ingeniería de operaciones técnicas en Business Analyst: se resuelve por título
  y responsabilidades reales. Los roles de IT/Security Operations con tareas de
  soporte o de datos siguen considerándose; no hay prohibición global.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import RULES_VERSION
from .perfil import peso_habilidad
from .textutil import normalizar

CATEGORIAS = [
    "Data Analyst",
    "Data Scientist",
    "Business Analyst",
    "BI Analyst",
    "Reporting Analyst",
    "Data Operations",
    "SQL Analyst",
    "Research Analyst",
    "VA/Data Entry",
    "Customer Support",
]

ANIOS_EXCEPCION_DESDE = 2
ANIOS_EXCEPCION_HASTA = 7
ANIOS_EXCLUYEN = 8
COBERTURA_EXCEPCION = 0.6
# Debajo de esto no hay con qué decidir: la oferta va a dudosas. El umbral es
# bajo a propósito porque los avisos reales casi nunca declaran experiencia,
# formación e idioma a la vez; exigir 0,7 mandaba todo a dudosas. Para *avisar*
# se sigue exigiendo 0,7 (ver `worker._corresponde_aviso`).
COBERTURA_MINIMA_DUDA = 0.45
DIAS_VIGENCIA_RAZONABLE = 45

# (categoría, pistas de título, pistas de cuerpo). Sólo las de título otorgan
# categoría plena; las de cuerpo son indicio para revisar.
_PISTAS: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("SQL Analyst", ("sql analyst", "analista sql"), ("sql analyst",)),
    ("BI Analyst", ("bi analyst", "business intelligence", "power bi", "tableau developer",
                    "bi developer", "analista bi", "power bi developer"),
     ("business intelligence", "power bi")),
    ("Reporting Analyst", ("reporting analyst", "reporting specialist", "analista de reportes",
                           "mis analyst"),
     ("reporting", "reportes")),
    ("Research Analyst", ("research analyst", "market research", "analista de investigacion"),
     ("market research", "investigacion de mercado")),
    ("Data Scientist", ("data scientist", "cientista de datos", "machine learning scientist",
                        "analytics engineer", "ingeniero de datos"),
     ("data scientist", "machine learning")),
    ("Data Analyst", ("data analyst", "analista de datos", "analytics analyst",
                      "product analyst", "data analytics", "insights analyst",
                      "analytics consultant"),
     ("data analyst", "analisis de datos")),
    ("Business Analyst", ("business analyst", "analista de negocio", "analista funcional",
                          "functional analyst", "process analyst", "operations analyst",
                          "analista de operaciones"),
     ("business analyst", "analisis funcional")),
    ("Data Operations", ("data operations", "data ops", "data quality", "data stewardship",
                         "data entry specialist", "data management analyst",
                         "data quality analyst"),
     ("data quality", "data stewardship")),
    ("VA/Data Entry", ("virtual assistant", "data entry", "asistente virtual",
                      "administrative assistant", "asistente administrativo",
                      "office assistant", "back office"),
     # Fase 1F · C03: el cuerpo sí aporta indicios administrativos, pero sólo se
     # evalúan si el TÍTULO es afín (`_TITULO_AFIN` o contextual). «data entry»
     # suelto en un aviso comercial sigue sin alcanzar.
     ("data entry", "ingreso de datos", "administrative", "administrativ",
      "back office", "scheduling", "calendar management", "inbox management",
      "bookkeeping", "invoicing", "records management", "filing")),
    ("Customer Support", ("customer support", "customer success", "client success",
                          "client service", "customer service", "technical support",
                          "support specialist", "help desk", "livechat", "live chat",
                          "atencion al cliente", "soporte tecnico", "customer happiness",
                          # «Customer Care Specialist - Spend - FinTech or Accounting
                          # Platforms» es soporte: sin esta pista, la palabra
                          # «Accounting» del título lo mandaba a fuera de perfil.
                          "customer care"),
     ("customer support", "customer service", "atencion al cliente")),
]

#: Pistas de cuerpo DÉBILES: herramientas y palabras genéricas que aparecen en
#: cualquier aviso corporativo. «Power BI» en un puesto de soporte es un tablero
#: que se consulta (Fase 1F · C02); «reporting» en un aviso de RR. HH. son los
#: reportes de otra persona (reproducido el 2026-11-10: HR Assistant y
#: Accounting Assistant clasificados como Reporting Analyst). Sólo otorgan
#: categoría si el TÍTULO ya es afín a datos.
_PISTAS_CUERPO_DEBILES = {"power bi", "business intelligence", "reporting", "reportes"}

_TITULO_FUERA_DE_PERFIL = re.compile(
    r"\b(engineer|engineering|developer|programmer|architect|designer|scientist|"
    r"accountant|bookkeeper|nurse|physician|lawyer|paralegal|driver|warehouse|"
    r"electrician|plumber|mechanic|teacher|professor|cook|chef|waiter|cleaner|"
    r"recruiter|talent acquisition|seo|copywriter|graphic|"
    # Fase 1G: RR. HH. y finanzas no son ninguna de las diez categorías. Antes
    # entraban por una palabra suelta del cuerpo («reporting») y quedaban como
    # Reporting Analyst. Se evalúan después de las pistas de título, así que
    # «HR Data Analyst» o «Financial Data Analyst» siguen siendo Data Analyst.
    r"hr|human resources|people operations|recruiting|recruitment|"
    r"finance|financial|accounting|payroll|tax|audit|treasury|controller)\b"
)

# Para aceptar una categoría detectada sólo en el cuerpo, el título tiene que
# ser al menos afín. Sin esto, «Paid Ads Specialist» caía en Reporting Analyst
# porque la descripción mencionaba «reporting».
_TITULO_AFIN = re.compile(
    r"\b(analyst|analista|data|datos|support|soporte|assistant|asistente|"
    r"operations|operaciones|reporting|business intelligence|bi|insights|research|"
    r"entry|back office)\b"
)

_SENIORITY_EXCLUYE = re.compile(
    r"\b(senior|sr|principal|staff|head of|head|director|vp|vice president|"
    r"chief|cto|ceo)\b"
    # «Lead Generation» es un dominio comercial, NO seniority. «Data Analyst
    # Lead» (lead al final) sí lo es y sigue excluyendo.
    r"|\blead\b(?!\s+(?:generation|gen\b|list|scoring|nurturing|qualification|"
    r"magnet|pipeline|prospect|ads|capture|data))"
)
# Seniority obligatorio declarado en el CUERPO (no sólo en el título).
_SENIORITY_CUERPO = re.compile(
    r"\b(?:senior|sr|principal|staff|director|vp|chief|head of|jefe|jefa|"
    r"as a lead|level senior|nivel senior)\b")
_REQ_SENIORITY = re.compile(
    r"\b(?:required|mandatory|must|minimum|minimo|excluyente|obligatorio|"
    r"se requiere|requiere|is a must|at least|or above)\b")
#: Gestión de personas: un «manager» o un «coordinador» manda gente.
_SENIORITY_DUDA = re.compile(
    r"\b(manager|supervisor|jefe|jefa|coordinador|coordinadora)\b")
#: Banda intermedia declarada por la fuente o el título. NO es gestión: un
#: «Mid-level» en el campo `seniority` de Himalayas convertía a un Operations
#: Assistant en «responsabilidad de gestión» (reproducido el 2026-11-10).
_SENIORITY_INTERMEDIA = re.compile(
    r"\b(mid level|midlevel|intermediate|semi senior|ssr|senior level)\b")
#: E02: «manager» en estos títulos describe la relación con clientes o una
#: cuenta, no la gestión de personas. Sólo se apartan si el aviso lo confirma.
_GESTION_DE_CUENTA = re.compile(
    r"\b(?:account|customer success|client success|community|social media|partner|"
    r"relationship|customer|client)\s+manager\b")
#: Evidencia de gestionar PERSONAS. «Mentor» o «coaching» no alcanzan: son
#: tareas habituales de un puesto individual que acompaña a compañeros.
_EVIDENCIA_GESTION = re.compile(
    r"\b(?:direct reports?|reports? to you|manage (?:a |the )?team|team of \d+|"
    r"people management|performance reviews?|hiring|headcount|supervis\w*)\b")

_SKILLS = [
    "sql", "python", "excel", "power bi", "tableau", "looker", "postgresql",
    "mysql", "sql server", "bigquery", "snowflake", "airflow", "dbt", "etl",
    "pandas", "numpy", "r", "statistics", "estadistica", "google sheets",
    "apps script", "git", "docker", "api", "jira", "salesforce", "hubspot",
    "data visualization", "visualizacion de datos", "power query", "vba",
    "looker studio", "metabase", "qlik", "spss", "stata", "nosql", "mongodb",
]

#: Fase 1F · C06: vocabulario de soporte y back office. `_SKILLS` sólo cubría
#: datos y tecnología, así que un aviso de VA o de atención al cliente no tenía
#: NINGUNA habilidad reconocible y quedaba sin puntaje (`sin_datos`). Estas
#: pistas se detectan siempre, pero **sólo puntúan si el perfil las declara**:
#: el resto se informa como brecha informativa y no resta ni suma. Ampliar la
#: lista a secas bajaba el score de todos los demás puestos.
_SKILLS_SOPORTE = [
    "customer service", "atencion al cliente", "customer support", "soporte al cliente",
    "data entry", "ingreso de datos", "zendesk", "freshdesk", "intercom", "help desk",
    "crm", "google workspace", "microsoft office", "office 365", "outlook",
    "scheduling", "bookkeeping", "invoicing", "transcription", "typing",
    "shopify", "slack", "notion", "asana", "trello", "airtable",
]


# Tareas típicas por categoría: es la evidencia de que el cuerpo del aviso
# describe el trabajo, no sólo que el título tiene la palabra clave.
_TAREAS: dict[str, tuple[str, ...]] = {
    "Data Analyst": ("dashboards", "dashboards de", "reportes", "reports", "kpis",
                     "analisis de datos", "insights", "metricas", "queries"),
    "Data Scientist": ("machine learning", "modelos", "modeling", "feature engineering",
                       "experimentos", "predictivo"),
    "Business Analyst": ("requirements", "stakeholders", "procesos", "process mapping",
                         "user stories", "relevamiento"),
    "BI Analyst": ("power bi", "tableau", "dashboards", "modelo de datos", "etl"),
    "Reporting Analyst": ("reportes", "reports", "weekly", "monthly reporting",
                          "metricas", "dashboards"),
    "Data Operations": ("data quality", "calidad de datos", "stewardship", "catalogo",
                        "governance", "limpieza de datos"),
    "SQL Analyst": ("queries", "consultas", "sql", "stored procedures"),
    "Research Analyst": ("research", "investigacion", "encuestas", "surveys",
                         "benchmark", "mercado"),
    "VA/Data Entry": ("data entry", "ingreso de datos", "administrative", "administrativ",
                      "bookkeeping", "filing", "archivo", "scheduling", "agenda",
                      "inbox", "correspondence", "documentos", "records", "typing"),
    "Customer Support": ("tickets", "live chat", "zendesk", "intercom", "clientes",
                         "customer inquiries", "soporte", "atencion al cliente",
                         "resolucion", "cases"),
}

# --- Fase 1F · C01: títulos afines que la taxonomía no reconocía -------------
# `Helpdesk Agent`, `CX Associate`, `Executive Assistant`, `Office
# Administrator`, `CRM Specialist`, `Operations Associate` y `Billing
# Specialist` describen puestos reales de soporte y de back office, pero no
# contenían ninguna de las cadenas de `_PISTAS`. Se reconocen por PATRÓN y con
# guardas: la categoría se otorga por el título, nunca por una mención suelta
# del cuerpo (Fase 1F · C02).
_TITULO_ADMINISTRATIVO = re.compile(
    r"\b(?:executive|personal|administrative|admin)\s+(?:assistant|coordinator|"
    r"specialist|officer|support)\b"
    r"|\boffice\s+(?:administrator|coordinator|clerk|assistant)\b"
    r"|\boperations\s+(?:associate|assistant|coordinator)\b"
    r"|\bback\s?office(?:\s+(?:assistant|specialist|associate|clerk))?\b"
    r"|\bbilling\s+(?:specialist|clerk|associate|coordinator)\b"
    r"|\bdata\s+entry(?:\s+(?:clerk|specialist|associate|operator|assistant))?\b"
    r"|\brecords?\s+(?:clerk|specialist|assistant)\b"
    r"|\bdocument\s+(?:specialist|controller|processor)\b"
    r"|\border\s+processing\b"
    r"|\bvirtual\s+assistant\b"
)
#: Guardas: un «operations associate» de depósito no es back office.
_ADMIN_GUARDA = re.compile(
    r"\b(?:warehouse|forklift|inventory|stock|shipping|receiving|driver|delivery|"
    r"logistics|pick(?:ing)?|packing|fulfilment|fulfillment|store|retail floor)\b")
_TITULO_SOPORTE_CONTEXTO = re.compile(
    r"\bhelp\s?desk(?:\s+(?:agent|specialist|analyst|technician|tier\s*\d))?\b"
    r"|\bservice\s+desk(?:\s+(?:agent|analyst|specialist))?\b"
    r"|\bdesktop\s+support\b"
    r"|\bcx\s+(?:associate|specialist|agent|representative|rep|advisor)\b"
    r"|\bcustomer\s+experience\s+(?:associate|specialist|agent|representative|advisor)\b"
    r"|\bcustomer\s+(?:care|success)\s+(?:associate|specialist|agent|representative|"
    r"advisor|manager|producer)\b"
    r"|\bclient\s+(?:support|service|success)(?:\s+(?:associate|specialist|agent|"
    r"representative|advisor|manager))?\b"
    r"|\bsupport\s+(?:associate|agent|specialist|representative)\b"
    r"|\btechnical\s+support(?:\s+(?:agent|specialist|associate))?\b"
    r"|\bcall\s+cent(?:er|re)\s+(?:agent|representative)\b"
    r"|\bbilling\s+support\b"
)
_TITULO_CRM = re.compile(
    r"\bcrm\s+(?:specialist|administrator|admin|analyst|coordinator|associate)\b"
    r"|\b(?:salesforce|hubspot)\s+(?:specialist|administrator|admin)\b"
)
#: Título afín a datos: sólo con esto una herramienta del cuerpo puede dar
#: categoría (si no, «Power BI» en un aviso de soporte lo volvía BI Analyst).
_TITULO_AFIN_DATOS = re.compile(
    r"\b(?:analyst|analista|data|datos|bi|business intelligence|reporting|insights|"
    r"research|sql|analytics|estadistic|statistic)\b")

# --- Idiomas: una tabla de superficies -> idioma canónico ------------------
# «French-speaking», «Francophone» y «francés» son el MISMO requisito. Tener
# una tabla (y no regex sueltas) evita contar dos veces el mismo idioma y
# permite evaluar cada requisuto por separado, en inglés o en español.
_IDIOMAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("french", ("french speaking", "frances hablante", "francophone", "francofono",
                "french", "frances")),
    ("german", ("german speaking", "german", "aleman")),
    ("turkish", ("turkish", "turkce", "turco")),
    ("czech", ("czech", "checo")),
    ("italian", ("italian", "italiano")),
    ("portuguese", ("portuguese", "portugues")),
    ("polish", ("polish", "polaco")),
    ("russian", ("russian", "ruso")),
    ("arabic", ("arabic", "arabe")),
    ("mandarin", ("mandarin", "mandarin")),
    ("chinese", ("chinese", "chino")),
    ("japanese", ("japanese", "japones")),
    ("korean", ("korean", "coreano")),
    ("hindi", ("hindi",)),
    ("dutch", ("dutch", "holandes")),
    ("romanian", ("romanian", "rumano")),
    ("ukrainian", ("ukrainian", "ucraniano")),
    ("hebrew", ("hebrew", "hebreo")),
    ("thai", ("thai", "tailandes")),
    ("vietnamese", ("vietnamese", "vietnamita")),
    ("indonesian", ("indonesian", "indonesio")),
    ("greek", ("greek", "griego")),
    ("swedish", ("swedish", "sueco")),
    ("norwegian", ("norwegian", "noruego")),
    ("danish", ("danish", "danes")),
    ("finnish", ("finnish", "finlandes")),
    ("hungarian", ("hungarian", "hungaro")),
    ("bulgarian", ("bulgarian", "bulgaro")),
    ("croatian", ("croatian", "croata")),
    ("serbian", ("serbian", "serbio")),
    ("slovak", ("slovak", "eslovaco")),
    ("estonian", ("estonian", "estonio")),
    ("latvian", ("latvian", "leton")),
    ("lithuanian", ("lithuanian", "lituano")),
    ("catalan", ("catalan",)),
    ("english", ("english speaking", "english", "ingles")),
    ("spanish", ("spanish", "espanol", "castellano")),
)
_SUPERFICIE_IDIOMA = {superficie: canonico
                      for canonico, superficies in _IDIOMAS
                      for superficie in superficies}
_IDIOMA_RE = re.compile(r"\b(?:" + "|".join(
    re.escape(s) for s in sorted(_SUPERFICIE_IDIOMA, key=len, reverse=True)) + r")\b")
# El perfil operativo declara inglés B1 y español nativo; nada más.
_IDIOMAS_PERFIL = {"english", "spanish"}

# La unidad de análisis es la CLÁUSULA, no una ventana de ±N caracteres:
# «French required, German a plus» son dos cláusulas con sentidos opuestos.
_CONJUNCIONES = re.compile(
    r"\b(?:but|while|whereas|although|however|pero|mientras|aunque)\b", re.I
)


def _unidades_crudas(texto: str, comas: bool = False) -> list[str]:
    """Segmentación SIN normalizar: conserva paréntesis y puntuación original.

    Es la capa previa a `normalizar`. Los paréntesis se respetan: una coma
    dentro de «(English/Spanish o Italian, Dutch, French)» no separa la lista.
    """
    if not texto:
        return []
    # «U.S.», «U.S.A.» y «a.m.»: ni el punto entre letras ni el punto final de
    # la abreviatura son fin de oración. «U.S. only» se convierte en «U S only»
    # para que la segmentación por cláusulas NO separe el país de su «only»;
    # antes había que evaluar el texto completo para no perder esa restricción,
    # y eso hacía que una negación de otra cláusula la cancelara.
    texto = re.sub(r"\bU\.S\.A\.?", "U S A", texto, flags=re.I)
    texto = re.sub(r"\bU\.S\.?", "U S", texto, flags=re.I)
    texto = re.sub(r"\b([A-Za-z])\.(?=[A-Za-z]\.)", r"\1 ", texto)
    fragmentos: list[str] = []
    actual: list[str] = []
    profundidad = 0
    for caracter in texto:
        if caracter in "([{":
            profundidad += 1
            actual.append(caracter)
        elif caracter in ")]}":
            profundidad = max(0, profundidad - 1)
            actual.append(caracter)
        elif profundidad == 0 and (caracter in ".;!?\n\r|" or (comas and caracter == ",")):
            fragmentos.append("".join(actual))
            actual = []
        else:
            actual.append(caracter)
    fragmentos.append("".join(actual))
    salida: list[str] = []
    for fragmento in fragmentos:
        for parte in _CONJUNCIONES.split(fragmento):
            if parte.strip():
                salida.append(parte)
    return salida


def _segmentos(texto: str, comas: bool = False) -> list[str]:
    """Divide texto en unidades independientes y las normaliza.

    `comas=True` separa también listas y enumeraciones (para idiomas); en
    cambio las oraciones completas (territorio, husos horarios) conservan las
    comas internas, porque «EST or CT time zone only» es una sola declaración.
    """
    salida = [normalizar(u) for u in _unidades_crudas(texto, comas)]
    return [u for u in salida if u]


# --- Modificadores de una cláusula de idioma --------------------------------
# Un modificador se aplica SÓLO a los idiomas de su propia cláusula. Así
# «French required and no degree needed» no niega el francés: la negación está
# en otra cláusula y no nombra ningún idioma.
_IDIOMA_OPCIONAL = re.compile(
    r"\b(?:is a plus|a plus|plus|preferred|preferible|nice to have|desirable|"
    r"deseable|se valora|se valorara|bonus|asset|advantageous|advantage|"
    r"an advantage|strong advantage|beneficial|helpful|welcome|valued|"
    r"optional|optativo|opcional|ventaja|no excluyente|not required|"
    r"not mandatory|not needed|not necessary|no requerido|not essential|"
    r"no es necesario)\b"
)
# Disyunción entre idiomas: «Italian, Spanish, French, or German», «Italian or
# Spanish», «English/Spanish or Italian». Es una ALTERNATIVA, no una suma de
# requisitos: basta con que el perfil satisfaga uno de los miembros.
_DISYUNCION_IDIOMA = re.compile(r"\b(?:or|o|either|alternatively)\b")
_DISYUNCION_BARRA = re.compile(
    r"(?:english|spanish|french|german|italian|portuguese|dutch|chinese|"
    r"japanese|frances|aleman|italiano|espanol)\s*/", re.I)
_IDIOMA_NEGADO = re.compile(
    r"\b(?:no|not|never|without|sin|isn t|isnt|aren t|arent|ningun|ninguno)\b"
)
_REQUISITO_IDIOMA = re.compile(
    r"\b(?:required|requerido|requiere|se requiere|requisito|obligatorio|"
    r"obligatoria|mandatory|must|essential|excluyente|indispensable|"
    r"imprescindible|fluent|native|bilingual|proficiency|proficient|speaker|"
    r"necesario|needed|exige|is a must|a must|dominio)\b"
)
_COORDINACION = re.compile(r"\b(?:and|y)\b")
_SIN_PARENTESIS = re.compile(r"\([^)]*\)")


def _modificador_idioma(clausula: str) -> str:
    """`cancelado` (optativo/negado), `requerido` o `ninguno`."""
    if _IDIOMA_OPCIONAL.search(clausula) or _IDIOMA_NEGADO.search(clausula):
        return "cancelado"
    return "requerido" if _REQUISITO_IDIOMA.search(clausula) else "ninguno"


def _idiomas_en(clausula: str) -> list[str]:
    vistos: list[str] = []
    for m in _IDIOMA_RE.finditer(clausula):
        canonico = _SUPERFICIE_IDIOMA[m.group(0)]
        if canonico not in vistos:
            vistos.append(canonico)
    return vistos


def _clausulas_idioma(
        titulo: str, texto: str) -> list[tuple[str, list[str], str, bool]]:
    """(cláusula, idiomas, modificador, es_alternativa) por separado.

    La unidad de extracción es la ORACIÓN completa: partir primero por comas
    destruye la disyunción («Italian, Spanish, French, or German» quedaría como
    cuatro requisitos independientes y el orden decidiría cuál manda). Recién
    después, si NO hay disyunción, se baja a la enumeración/coordinación:

    - «or» / «o» / lista con «or» final / barra → un grupo de ALTERNATIVAS.
    - «and» / «y» → requisitos independientes, con propagación del modificador
      final («French and German required» obliga a los dos).
    - Paréntesis sin idiomas se descartan; paréntesis CON idiomas se conservan
      para que el «is a plus» exterior siga aplicándose a toda la lista.

    El contenido entre paréntesis que NO nombra idiomas no modifica la cláusula:
    «French required (no exceptions)» sigue siendo obligatorio.
    """
    salida: list[tuple[str, list[str], str, bool]] = []
    for oracion in (_unidades_crudas(titulo, comas=False)
                    + _unidades_crudas(texto[:8000], comas=False)):
        for pieza in _CONJUNCIONES.split(oracion):
            dentro = " ".join(_SIN_PARENTESIS.findall(pieza))
            if not _idiomas_en(normalizar(dentro)):
                pieza = _SIN_PARENTESIS.sub(" ", pieza)
            unidad = normalizar(pieza)
            lenguajes = _idiomas_en(unidad)
            if not lenguajes:
                continue

            if len(lenguajes) >= 2 and (_DISYUNCION_IDIOMA.search(unidad)
                                        or _DISYUNCION_BARRA.search(pieza)):
                salida.append((unidad, lenguajes,
                               _modificador_idioma(unidad), True))
                continue

            for cruda in _unidades_crudas(pieza, comas=True):
                dentro_sub = " ".join(_SIN_PARENTESIS.findall(cruda))
                if not _idiomas_en(normalizar(dentro_sub)):
                    cruda = _SIN_PARENTESIS.sub(" ", cruda)
                sub = normalizar(cruda)
                partes = _COORDINACION.split(sub)
                lengs = [_idiomas_en(p) for p in partes]
                mods = [_modificador_idioma(p) for p in partes]
                for i, parte in enumerate(partes):
                    if not lengs[i]:
                        continue
                    mod = mods[i]
                    if mod == "ninguno":
                        # Propagación explícita: «French and German required».
                        for j in range(i + 1, len(partes)):
                            if lengs[j] and mods[j] != "ninguno":
                                mod = mods[j]
                                break
                    salida.append((parte.strip(), lengs[i], mod, False))
    return salida

# CEFR: el nivel pedido se compara con el nivel REAL del perfil (B1).
_NIVELES_CEFR = {"a1": 1, "a2": 2, "b1": 3, "b2": 4, "c1": 5, "c2": 6}
_RANGO_PERFIL = {
    "a1": 1, "a2": 2, "b1": 3, "intermedio": 3, "intermediate": 3,
    "b2": 4, "c1": 5, "c2": 6, "avanzado": 5, "advanced": 5,
    "nativo": 7, "native": 7,
}

_ESTOPWORDS = {"de", "la", "que", "el", "en", "y", "los", "se", "del", "las", "un",
               "por", "con", "una", "para", "es", "al", "lo", "como", "más", "mas",
               "sus", "le", "ya", "o", "este", "sí", "porque", "esta", "entre"}
_ENSTOPWORDS = {"the", "and", "of", "to", "in", "a", "is", "for", "with", "on",
                "that", "as", "are", "be", "this", "or", "from", "at", "by", "will",
                "you", "we", "our", "your", "an", "it", "have", "has", "not"}

_REQUISITO_FUERTE = re.compile(
    r"\b(required|requirement|must have|must be|minimum|obligatorio|excluyente|indispensable)\b"
)
_ANIOS = re.compile(r"(\d{1,3})\s*\+?\s*(?:year|years|yr|yrs|años|anos|año|ano)\b")

_PAISES_NO_AR = [
    "united states", "usa only", "us only", "u.s. only", "canada", "united kingdom",
    "uk only", "emea", "europe", "eu only", "germany", "france", "spain", "india",
    "philippines", "australia", "new zealand", "singapore", "japan", "brazil",
    "mexico", "colombia", "chile", "peru", "uruguay", "paraguay", "bolivia",
    "venezuela", "ecuador", "south africa", "nigeria", "kenya", "pakistan",
    "bangladesh", "indonesia", "malaysia", "vietnam", "thailand", "poland",
    "romania", "portugal", "netherlands", "ireland", "sweden", "norway",
    "denmark", "finland", "switzerland", "italy", "turkey", "israel", "egypt",
    "morocco", "ukraine", "czech", "hungary", "greece", "china", "korea",
    "taiwan", "hong kong", "saudi", "emirates", "qatar", "north america",
    # Fase 1F · T03: países y regiones que quedaban en «dudosa» sin motivo.
    "bulgaria", "croatia", "serbia", "slovenia", "slovakia", "lithuania",
    "latvia", "estonia", "luxembourg", "malta", "iceland", "cyprus", "moldova",
    "albania", "asia pacific", "asia-pacific", "apac", "middle east",
    "gulf region", "central america", "caribbean",
]
# Indicadores de EE. UU. que no aparecen como frase completa en las regiones:
# «Your Remote US Home Office», «US-Remote», «U.S. only». Se buscan como palabra.
_EEUU = re.compile(r"\b(u s|us|usa|united states|estados unidos)\b")
_ESTADOS_EEUU = ("al", "ak", "az", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
                 "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
                 "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
                 "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
                 "wi", "wy")
_CIUDADES_EEUU = ("san francisco", "new york", "seattle", "austin", "boston", "chicago",
                  "denver", "atlanta", "los angeles", "san diego", "miami", "dallas",
                  "houston", "philadelphia", "phoenix", "portland", "minneapolis",
                  "washington dc", "silicon valley", "bay area", "new jersey")

#: T03: nombres completos de estados de EE. UU. (`_ESTADOS_EEUU` sólo tiene el
#: código de dos letras, así que «Ohio» o «Texas» quedaban en «dudosa»).
_ESTADOS_EEUU_NOMBRES = (
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york state", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington state", "west virginia", "wisconsin", "wyoming",
)
#: Ciudades extranjeras inequívocas. No se incluye ningún topónimo argentino ni
#: nombres ambiguos («Santiago» puede ser Chile o España): esos se resuelven por
#: el país que acompaña a la región.
_CIUDADES_NO_AR = (
    "berlin", "munich", "munchen", "hamburg", "frankfurt", "cologne", "koln",
    "stuttgart", "dusseldorf", "dortmund", "leipzig", "dresden", "nuremberg",
    "london", "manchester", "edinburgh", "dublin", "paris", "lyon", "madrid",
    "barcelona", "valencia", "lisbon", "porto", "rome", "milan", "naples",
    "amsterdam", "rotterdam", "brussels", "antwerp", "warsaw", "krakow",
    "prague", "brno", "vienna", "zurich", "geneva", "basel", "stockholm",
    "oslo", "copenhagen", "helsinki", "tallinn", "riga", "vilnius", "sofia",
    "bucharest", "budapest", "athens", "belgrade", "zagreb", "istanbul",
    "ankara", "tel aviv", "dubai", "abu dhabi", "cairo", "lagos", "nairobi",
    "johannesburg", "cape town", "toronto", "vancouver", "montreal", "ottawa",
    "sydney", "melbourne", "brisbane", "auckland", "wellington", "tokyo",
    "osaka", "seoul", "singapore", "hong kong", "shanghai", "beijing",
    "shenzhen", "bangalore", "bengaluru", "mumbai", "new delhi", "hyderabad",
    "pune", "chennai", "manila", "cebu", "jakarta", "bangkok", "hanoi",
    "ho chi minh", "kuala lumpur", "karachi", "lahore", "dhaka",
    "mexico city", "ciudad de mexico", "guadalajara", "monterrey", "bogota",
    "medellin", "lima", "quito", "caracas", "sao paulo", "rio de janeiro",
)

# Un PAÍS declarado explícitamente en la región manda sobre cualquier parecido
# con un topónimo argentino. «Cordoba, Spain» no es Córdoba (AR); «La Plata,
# Maryland, USA» no es La Plata (AR). Se buscan con límites de palabra: nunca
# como subcadena dentro de otro nombre propio.
_PAISES_EXPLICITOS = (
    "united states", "estados unidos", "usa", "canada",
    "united kingdom", "great britain", "uk", "u k", "england", "scotland",
    "ireland", "europe", "european union", "european", "emea", "eu", "north america",
    "spain", "france", "germany", "italy", "portugal", "netherlands", "sweden",
    "norway", "denmark", "finland", "switzerland", "austria", "belgium",
    "poland", "romania", "czech", "hungary", "greece", "turkey", "ukraine",
    "israel", "egypt", "morocco", "saudi", "emirates", "qatar", "india",
    "philippines", "singapore", "japan", "china", "korea", "taiwan",
    "hong kong", "australia", "new zealand", "south africa", "nigeria",
    "kenya", "pakistan", "bangladesh", "indonesia", "malaysia", "vietnam",
    "thailand", "brazil", "mexico", "colombia", "chile", "peru", "uruguay",
    "paraguay", "bolivia", "venezuela", "ecuador",
)

# «us» / «u s» son ambiguos: país o pronombre. En una ETIQUETA de región es un
# país («US», «U.S.»); dentro de una frase exige contexto territorial y que no
# venga después de un verbo que lo use como objeto («Join Us», «Contact us»).
_US_TERRITORIO = re.compile(
    r"^\s*(?:us|u\s+s)\b\s+(?:only|based|residents?|citizens?|nationals?|"
    r"candidates?|applicants?|employees?|workers?|locations?|offices?|"
    r"remote|time\s+zones?|work\s+(?:authorization|permit)|passport|"
    r"citizenship|permits?)\b"
    r"|^\s*(?:us|u\s+s)[- ](?:only|based|remote|residents?|citizens?)\b"
)
_US_EN_FRASE = re.compile(r"\b(?:in|within|from|of|for|to)\s+the\s+(?:us|u\s+s)\b")
_US_PRONOMBRE = re.compile(
    r"\b(?:join|with|contact|help|tell|send|among|amongst|ask|email|"
    r"write|meet|support|serve|reach|let|invite)\s+$", re.I)


def _us_es_territorio(campo: str, *, etiqueta: bool) -> bool:
    if etiqueta:
        return bool(re.search(r"\b(?:us|u\s+s)\b", campo))
    if _US_EN_FRASE.search(campo):
        return True
    for m in re.finditer(r"\b(?:us|u\s+s)\b", campo):
        prefijo = campo[max(0, m.start() - 30):m.start()]
        if _US_PRONOMBRE.search(prefijo):
            continue
        if _US_TERRITORIO.search(campo[m.start():m.start() + 45]):
            return True
    return False


def _pais_explicito(campo: str, *, etiqueta: bool = False) -> str | None:
    """País extranjero nombrado como tal; `etiqueta` = campo de ubicación."""
    for p in _PAISES_EXPLICITOS:
        if re.search(rf"\b{re.escape(p)}\b", campo):
            return p
    return "us" if _us_es_territorio(campo, etiqueta=etiqueta) else None


def _contexto_argentino(campo: str) -> bool:
    """Topónimo argentino con límites de palabra (no subcadena)."""
    return "argentina" in campo or any(
        re.search(rf"\b{re.escape(c)}\b", campo) for c in _CONTEXTO_ARGENTINO)

# TERRITORIO: sólo locuciones que declaran DESDE DÓNDE se contrata. Los términos
# de MODALIDAD («fully remote», «100% remote», «remote worldwide») se sacaron:
# decir cómo se trabaja no dice dónde se puede estar.
_PERMITIDOS = [
    "anywhere", "worldwide", "world wide", "global", "latam", "latin america",
    "south america", "americas", "argentina", "any location", "international",
]
_CONTEXTO_ARGENTINO = ("argentina", "la plata", "buenos aires", "cordoba", "rosario",
                       "mendoza", "quilmes", "mar del plata", "amba", "avellaneda")
# Códigos ISO de dos letras, sólo como ÚLTIMO componente de la región. «AR» es
# ambiguo (Argentina / Arkansas) y se resuelve por contexto, nunca a ciegas.
_ISO_NO_AR = {
    "us": "Estados Unidos", "usa": "Estados Unidos", "uk": "Reino Unido",
    "gb": "Reino Unido", "ca": "Canadá", "de": "Alemania", "fr": "Francia",
    "es": "España", "it": "Italia", "jp": "Japón", "cn": "China", "kr": "Corea",
    "in": "India", "ph": "Filipinas", "br": "Brasil", "mx": "México",
    "au": "Australia", "nz": "Nueva Zelanda", "za": "Sudáfrica", "ng": "Nigeria",
    "ke": "Kenia", "pk": "Pakistán", "bd": "Bangladesh", "id": "Indonesia",
    "my": "Malasia", "vn": "Vietnam", "th": "Tailandia", "pl": "Polonia",
    "ro": "Rumania", "pt": "Portugal", "nl": "Países Bajos", "ie": "Irlanda",
    "se": "Suecia", "no": "Noruega", "dk": "Dinamarca", "fi": "Finlandia",
    "ch": "Suiza", "il": "Israel", "eg": "Egipto", "ma": "Marruecos",
    "ua": "Ucrania", "cz": "Chequia", "hu": "Hungría", "gr": "Grecia",
    "tr": "Turquía", "ae": "Emiratos", "sa": "Arabia Saudí", "qa": "Catar",
    "hk": "Hong Kong", "tw": "Taiwán", "eu": "Unión Europea",
}

# --- Restricciones geográficas declaradas en el CUERPO ----------------------
# Patrones de alta precisión: exigen una declaración de residencia o de
# autorización, no la mención suelta de un país (que puede ser la sede, un
# beneficio o el mercado que atiende la empresa).
_LUGAR_RE = (
    r"(?:the\s+)?(?:united\s+states(?:\s+of\s+america)?|estados\s+unidos|"
    r"u\s+s\s+a|usa|u\s+s|us|canada|united\s+kingdom|great\s+britain|"
    r"u\s+k|uk|england|scotland|ireland|european\s+union|european|europe|eu|emea|"
    r"north\s+america|australia|new\s+zealand|india|philippines|singapore|"
    r"japan|china|korea|brazil|mexico|colombia|chile|peru|uruguay|paraguay|"
    r"bolivia|venezuela|ecuador|south\s+africa|nigeria|kenya|pakistan|"
    r"bangladesh|indonesia|malaysia|vietnam|thailand|poland|romania|"
    r"portugal|netherlands|sweden|norway|denmark|finland|switzerland|"
    r"italy|turkey|israel|egypt|morocco|ukraine|czech|hungary|greece|"
    r"taiwan|hong\s+kong|saudi|emirates|qatar|spain|france|germany|"
    r"austria|belgium)"
)
_PATRONES_LUGAR = tuple(
    re.compile(patron) for patron in (
        rf"\b(?P<lugar>{_LUGAR_RE})\s+only\b",
        rf"\b(?P<lugar>{_LUGAR_RE})\s+(?:residents|candidates|applicants|citizens)\s+only\b",
        rf"\b(?:only|exclusively)\s+(?:open\s+to\s+|hiring\s+in\s+|for\s+)?"
        rf"(?:candidates|applicants|residents|people|workers)?\s*"
        rf"(?:located\s+|based\s+|residing\s+|living\s+)?"
        rf"(?:in|from|within)\s+(?P<lugar>{_LUGAR_RE})\b",
        rf"\b(?:restricted|limited)\s+to\s+(?:candidates\s+)?"
        rf"(?:in\s+|from\s+|within\s+)?(?P<lugar>{_LUGAR_RE})\b",
        rf"\b(?:must|should|need\s+to|are\s+required\s+to)\s+be\s+"
        rf"(?:legally\s+)?(?:eligible|authorized|able)\s+to\s+"
        rf"(?:live\s+and\s+)?work\s+in\s+(?P<lugar>{_LUGAR_RE})\b",
        rf"\bauthorized\s+to\s+work\s+in\s+(?P<lugar>{_LUGAR_RE})\b",
        rf"\b(?:must|should|need\s+to)\s+be\s+(?:located|based|residing|living)\s+in\s+"
        rf"(?P<lugar>{_LUGAR_RE})\b",
        rf"\b(?P<lugar>{_LUGAR_RE})\s+work\s+authorization\b",
        rf"\bwork\s+authorization\s+(?:in|for)\s+(?P<lugar>{_LUGAR_RE})\b",
        rf"\b(?P<lugar>{_LUGAR_RE})[- ]based\s+(?:candidates|applicants|residents|"
        rf"employees|team\s+members|workers)\s+only\b",
        rf"\b(?:candidates|applicants|residents)\s+(?:must|should|need\s+to)\s+be\s+"
        rf"(?P<lugar>{_LUGAR_RE})[- ]based\b",
        rf"\banywhere\s+in\s+(?P<lugar>{_LUGAR_RE})\b",
        rf"\b(?P<lugar>us|u\s+s|usa|united\s+states)[- ]remote\b",
        # Residencia / ciudadanía declarada con otro verbo. «Must live in the
        # US» y «Must currently reside in Canada» no son horarios de trabajo.
        rf"\b(?:must|should|need\s+to|are\s+required\s+to)\s+(?:currently\s+)?"
        rf"(?:live|reside|be\s+located|be\s+based|work)\s+in\s+(?:the\s+)?"
        rf"(?P<lugar>{_LUGAR_RE})\b",
        rf"\b(?:must|should|need\s+to)\s+be\s+(?:a|an)?\s*"
        rf"(?P<lugar>{_LUGAR_RE})\s+"
        rf"(?:citizen|citizens|national|resident|permanent\s+resident)\b",
        rf"\b(?P<lugar>{_LUGAR_RE})\s+citizenship\s+"
        rf"(?:is\s+)?(?:required|mandatory|needed)\b",
        rf"\b(?:must|should)\s+have\s+(?:a\s+)?(?P<lugar>{_LUGAR_RE})\s+"
        rf"(?:citizenship|passport|work\s+permit)\b",
    )
)
_PRONOMBRE_US = re.compile(r"\b(?:join|with|for|to|contact|help|tell|send|among)\s+$")
# Una negación inmediatamente ANTES de la restricción la cancela: «not a
# US-only position», «we are not restricted to candidates in the US».
_NEGACION_LUGAR = re.compile(
    r"\b(?:not|no|never|without|sin|isn t|isnt|non|nor)\b")
# No alcanza con que haya un «no» en algún lugar de la ventana: tiene que estar
# ENLAZADO con la restricción que niega. «No agencies please» / «No visa
# sponsorship» niegan OTRA cláusula y no cancelan el «US only» que les sigue.
_NEGACION_ENLACE = re.compile(
    r"\b(?:not|never|no|sin|without|isn t|isnt|non|nor)\b"
    r"(?:\s+(?:a|an|the|only|restricted|limited|exclusive|exclusively|hiring|"
    r"open|available|required|necessary|needed|based|located|residing|living|"
    r"in|from|within|to|for|of|applicants?|candidates?|residents?|citizens?|"
    r"work|we|are|is|be|position|role|this|that|it|us|u s)){0,8}\s*$", re.I)


def _canonico_lugar(token: str) -> str:
    # `_LUGAR_RE` admite el artículo («in the US»): se quita antes de nombrar.
    t = re.sub(r"^the\s+", "", (token or "").strip())
    if re.search(r"united\s+states|estados\s+unidos|u\s+s\s+a|usa|u\s+s|^us$", t):
        return "Estados Unidos"
    if "canada" in t:
        return "Canadá"
    if re.search(r"united\s+kingdom|great\s+britain|u\s+k|^uk$|england|scotland", t):
        return "Reino Unido"
    if re.search(r"^eu$|europe|european", t):
        return "Europa"
    return t or "otro país"


def _lugar_restringido(oraciones: list[str]) -> str | None:
    """¿El aviso declara que sólo contrata en un territorio incompatible?

    Se revisan TODAS las coincidencias de la oración: si la primera está
    negada, otra puede seguir siendo válida. La negación sólo cancela la
    coincidencia a la que precede, nunca una restricción distinta.
    """
    for oracion in oraciones:
        for patron in _PATRONES_LUGAR:
            for m in patron.finditer(oracion):
                prefijo = oracion[:m.start()]
                if (_NEGACION_LUGAR.search(prefijo)
                        and _NEGACION_ENLACE.search(prefijo)):
                    continue
                token = (m.groupdict().get("lugar") or "").strip()
                # «us» también es pronombre: «... join us only if» no es territorio.
                if token in {"us", "u s"} and _PRONOMBRE_US.search(
                        oracion[max(0, m.start() - 25):m.start()]):
                    continue
                return _canonico_lugar(token)
    return None


# --- Requisito LEGAL: permiso de trabajo / ciudadanía -----------------------
# «Must have an EU work permit» y «A European work permit is required» son la
# misma condición; «... preferred» es una preferencia y NO excluye. Se extraen
# como un hecho separado del territorio para poder distinguir obligatoriedad.
_PATRONES_LEGAL = tuple(re.compile(p, re.I) for p in (
    rf"\b(?:must|should|need\s+to|are\s+required\s+to)\s+(?:have|hold|possess)\s+"
    rf"(?:a|an|the)?\s*(?P<lugar>{_LUGAR_RE})\s+"
    rf"(?:work\s+permit|work\s+authorization|citizenship|passport)\b",
    rf"\b(?P<lugar>{_LUGAR_RE})\s+"
    rf"(?:work\s+permit|work\s+authorization|citizenship)\b",
    rf"\b(?:work\s+permit|work\s+authorization|citizenship)\s+"
    rf"(?:in|for|from)\s+(?P<lugar>{_LUGAR_RE})\b",
))
_LEGAL_OBLIGATORIO = re.compile(
    r"\b(?:must|required|mandatory|obligatorio|excluyente|need\s+to|have\s+to|"
    r"is\s+a\s+must|necessary)\b", re.I)
_LEGAL_PREFERIDO = re.compile(
    r"\b(?:preferred|preferible|desirable|deseable|a plus|nice to have|bonus|"
    r"optional|opcional|ideally|advantage|advantageous)\b", re.I)


def _requisito_legal(oraciones: list[str]) -> tuple[str, str]:
    """(`obligatorio` | `preferido` | ``, territorio) para permisos legales."""
    for oracion in oraciones:
        for patron in _PATRONES_LEGAL:
            for m in patron.finditer(oracion):
                prefijo = oracion[:m.start()]
                if (_NEGACION_LUGAR.search(prefijo)
                        and _NEGACION_ENLACE.search(prefijo)):
                    continue
                lugar = _canonico_lugar((m.groupdict().get("lugar") or "").strip())
                if _LEGAL_OBLIGATORIO.search(oracion):
                    return "obligatorio", lugar
                if _LEGAL_PREFERIDO.search(oracion):
                    return "preferido", lugar
                # Mera mención sin marcador: no se inventa obligatoriedad.
                # Queda como duda, no como descarte.
                return "preferido", lugar
    return "", ""


# Husos horarios: obligación de residir en una zona ≠ preferencia de horario.
_HUSO = (r"(?:pacific|eastern|central|mountain|est|cst|pst|mst|edt|pdt|cdt|mdt|"
         r"ct|et|pt|mt|gmt|utc|cet|bst|ist|aest|art)")
_HUSO_TOKEN = re.compile(r"\b(?:pacific|eastern|central|mountain|est|cst|pst|mst|"
                         r"edt|pdt|cdt|mdt|ct|et|pt|mt|gmt|utc|cet|bst|ist|aest|art)\b")
# ART es la zona de Argentina: exigirla es COMPATIBLE, no una residencia
# extranjera. GMT/UTC son referencias neutras, no territorio.
_HUSOS_ARGENTINOS = {"art"}
_HUSOS_NEUTROS = {"gmt", "utc"}
_ZONA_HORARIA = re.compile(rf"\b{_HUSO}(?:[\s/or,&-]+{_HUSO})*\s+time\s+zones?\b")
_ZONA_DURA = re.compile(
    r"\b(?:only|exclusively|must|required|restricted|limited|mandatory)\b"
    r"|\b(?:must|should|need\s+to)\s+be\s+(?:located|based|residing|working)\s+in\b"
    r"|\bus[- ]remote\b"
)
_ZONA_SUAVE = re.compile(
    r"\b(?:prefer|preferred|ideally|a plus|nice to have|bonus|flexible|"
    r"preferible|deseable)\b"
)
# «Candidates in Central, Mountain or Eastern time zones» es una declaración de
# a quién se contrata, aunque no diga «only». No es un horario de trabajo.
_ZONA_DECLARACION = re.compile(
    r"\b(?:candidates|applicants|residents|hiring|open\s+to)\s+"
    r"(?:in|within|from|located\s+in|based\s+in)\b"
)
# «US time zones only» nombra un PAÍS, no un huso: puede estar pidiendo
# residencia o simplemente disponibilidad para cumplir un horario. Desde
# Argentina se puede trabajar en horario EST, así que no autoriza un descarte.
_ZONA_PAIS = re.compile(
    r"\b(?:us|u\s+s|usa|united\s+states|canada|uk|u\s+k|europe|eu|emea)\s+"
    r"time\s+zones?\b")
_ZONA_DISPONIBILIDAD = re.compile(
    r"\b(?:availability|available|schedule|scheduled|hours|shift|overlap|"
    r"cover|coverage|a m|p m)\b")
_ZONA_RESIDENCIA = re.compile(
    r"\b(?:must|should|need\s+to)\s+(?:be\s+)?"
    r"(?:located|based|residing|living)\s+in\b"
    r"|\b(?:residents?|citizens?)\s+(?:in|only)\b")


def _zona_horaria(oraciones: list[str]) -> str:
    """`obligatoria`, `compatible` (ART), `dudosa`, `preferida`, `` (neutro).

    Un huso horario no es automáticamente una residencia extranjera: primero se
    identifica DE QUÉ zona se habla, y después si el aviso pide RESIDIR en ella
    o sólo DISPONIBILIDAD para ese horario. Con alternativas compatibles (ART)
    o sin esa distinción se devuelve `dudosa`, no un descarte.
    """
    disponibilidad = any(_ZONA_DISPONIBILIDAD.search(o) for o in oraciones)
    residencia = any(_ZONA_RESIDENCIA.search(o) for o in oraciones)
    declaracion = any(_ZONA_DECLARACION.search(o) for o in oraciones)
    for oracion in oraciones:
        if _ZONA_PAIS.search(oracion):
            return "obligatoria" if declaracion or residencia else "dudosa"
        m = _ZONA_HORARIA.search(oracion)
        if not m:
            continue
        zonas = _HUSO_TOKEN.findall(m.group(0))
        if zonas and all(z in _HUSOS_ARGENTINOS for z in zonas):
            return "compatible"
        if zonas and all(z in _HUSOS_NEUTROS for z in zonas):
            return ""
        # «EST or ART time zone only»: ART es una alternativa compatible; la
        # presencia adicional de EST no alcanza para descartar la oferta.
        if any(z in _HUSOS_ARGENTINOS for z in zonas):
            return "dudosa"
        duro = bool(_ZONA_DURA.search(oracion))
        if _ZONA_SUAVE.search(oracion) and not duro:
            return "preferida"
        if duro or _ZONA_DECLARACION.search(oracion):
            if disponibilidad and not (residencia or _ZONA_DECLARACION.search(oracion)):
                return "dudosa"
            return "obligatoria"
    return ""


def _restringido_en(plano: str) -> bool:
    """¿Una región «anywhere in X» nombra un país que no admite Argentina?"""
    if any(re.search(rf"\b{re.escape(p)}\b", plano) for p in _PAISES_NO_AR):
        return True
    if _EEUU.search(plano):
        return True
    return bool(re.search(
        r"\b(?:uk|u k|gb|eu|emea|ca|de|fr|es|it|jp|cn|kr|in|ph|br|mx|au|nz|"
        r"za|ng|ke|pk|bd|id|my|vn|th|pl|ro|pt|nl|ie|se|no|dk|fi|ch|il|eg|ma|"
        r"ua|cz|hu|gr|tr|ae|sa|qa|hk|tw)\b", plano))


def _iso_region(region: str | None) -> str:
    """Interpreta el código ISO final de una región; «» = no es ISO.

    Se parte el ORIGINAL por comas: `normalizar` borra los signos y convertía
    «Berlin, DE» en «berlin de», donde el código ya no era el último token.
    """
    campo = normalizar(region)
    crudo = region or ""
    ultimo_crudo = re.sub(r"\([^)]*\)", " ", crudo.rsplit(",", 1)[-1]).strip(" ,")
    ultimo = normalizar(ultimo_crudo)
    if ultimo == "ar":
        if any(c in campo for c in _CONTEXTO_ARGENTINO) or "argentina" in campo:
            return "argentina"
        return "ambiguo"
    if ultimo == "ca" and any(c in campo for c in _CIUDADES_EEUU):
        return "California (EE. UU.)"
    return _ISO_NO_AR.get(ultimo, "")


def _alcance_de_campo(campo: str) -> str:
    if "argentina" in campo:
        return "argentina"
    if any(p in campo for p in ("anywhere", "worldwide", "world wide", "global", "any location")):
        return "mundial"
    if any(p in campo for p in _PERMITIDOS):
        return "internacional"
    return "desconocido"


# --- Fase 1E · D1: listas multipaís / D2: precedencia ----------------------
# Una etiqueta de fuente puede enumerar los países DONDE SE ACEPTAN
# POSTULANTES («Argentina, Colombia», «LATAM, Canada, USA») en lugar de imponer
# un país de residencia. Nombrar otros países NO excluye si la lista contiene
# Argentina/LATAM/Américas. Sólo un marcador explícito («only», «must be
# based», «restricted to») convierte la lista en una restricción.
_ALCANCES_COMPATIBLES_EN_LISTA = re.compile(
    r"\b(?:argentina|latam|latin\s+america|south\s+america|americas|"
    r"anywhere|worldwide|world|global|international|any\s+location)\b")
_MARCADOR_RESTRICCION_REGION = re.compile(
    r"\b(?:only|exclusively|restricted|limited|must|required|mandatory|"
    r"obligatorio|excluyente|residents?\s+only|candidates?\s+only)\b")
_DECLARACION_AMERICAS = re.compile(
    r"\b(?:work\s+from\s+anywhere\s+in\s+the\s+(?:world|americas|latin\s+america)|"
    r"anywhere\s+in\s+the\s+(?:world|americas|latin\s+america|south\s+america)|"
    r"remote\s+worldwide|open\s+to\s+candidates?\s+in\s+(?:the\s+)?americas)\b")
# Países/regiones reconocibles para contar CUÁNTOS lugares enumera la etiqueta.
# «Berlin, Germany» tiene uno: es una ubicación, no una lista de admitidos.
_LUGARES_EN_LISTA = re.compile(
    r"\b(?:argentina|latam|latin\s+america|south\s+america|americas|"
    r"north\s+america|anywhere|worldwide|world|global|international|emea|apac|"
    r"united\s+states|estados\s+unidos|usa|u\s+s|canada|united\s+kingdom|"
    r"great\s+britain|uk|u\s+k|england|scotland|ireland|europe|"
    r"european\s+union|european|eu|germany|france|spain|italy|portugal|"
    r"netherlands|sweden|norway|denmark|finland|switzerland|austria|belgium|"
    r"poland|romania|czech|hungary|greece|turkey|ukraine|israel|egypt|morocco|"
    r"saudi|emirates|qatar|uae|india|philippines|singapore|japan|china|korea|"
    r"taiwan|hong\s+kong|australia|new\s+zealand|south\s+africa|nigeria|kenya|"
    r"pakistan|bangladesh|indonesia|malaysia|vietnam|thailand|brazil|mexico|"
    r"colombia|chile|peru|uruguay|paraguay|bolivia|venezuela|ecuador)\b")


def _lugares_en_lista(region: str | None) -> int:
    """Cantidad de países/regiones DISTINTOS que enumera una etiqueta."""
    if not region:
        return 0
    partes = [normalizar(u) for u in _unidades_crudas(region, comas=True)]
    if len([p for p in partes if p]) < 2:
        return 0
    vistos: set[str] = set()
    for parte in partes:
        vistos.update(m.group(0) for m in _LUGARES_EN_LISTA.finditer(parte))
    return len(vistos)


def _territorio_lista_multipais(region: str | None, cuerpo: str):
    """Resuelve una lista de países admitidos; `None` = no es ese caso.

    `ok`   -> la lista contiene un alcance compatible (Argentina/LATAM/...).
    `duda` -> la etiqueta y una declaración permisiva del cuerpo se contradicen
              y no se puede resolver sin revisión humana.
    """
    campo = normalizar(region)
    if not campo or _lugares_en_lista(region) < 2:
        return None
    if _MARCADOR_RESTRICCION_REGION.search(campo):
        return None  # «US only», «must be based in Canada» -> flujo normal
    if _ALCANCES_COMPATIBLES_EN_LISTA.search(campo):
        mundial = bool(re.search(r"\b(?:anywhere|worldwide|world|global)\b", campo))
        return ("ok",
                f"la fuente enumera países admitidos e incluye un alcance compatible: {region}",
                region or "", "mundial" if mundial else "internacional")
    if _DECLARACION_AMERICAS.search(cuerpo):
        return ("duda",
                "la etiqueta enumera países pero el aviso declara trabajo desde "
                "cualquier punto de las Américas: contradicción sin resolver",
                "", "desconocido")
    return None


def _exclusion_explicita_de_fuente(campo: str, en_titulo: str, lista, region) -> bool:
    """¿Hay una exclusión territorial DURA que deba ganar a una preferencia?"""
    if _pais_explicito(en_titulo):
        return True
    if any(re.search(rf"\b{re.escape(p)}\b", en_titulo) for p in _PAISES_NO_AR):
        return True
    if not campo or lista is not None:
        return False
    if _pais_explicito(campo, etiqueta=True):
        return True
    if any(re.search(rf"\b{re.escape(p)}\b", campo) for p in _PAISES_NO_AR):
        return True
    if _EEUU.search(campo):
        return True
    return bool(_iso_region(region))


# --- MODALIDAD: cómo se trabaja ---------------------------------------------
_REMOTO = ("remote", "remoto", "remota", "teletrabajo", "work from home", "home office",
           "home based", "fully remote", "work from anywhere", "anywhere",
           "distributed", "remote-first")
_REMOTO_CUERPO = re.compile(
    r"\b(remote|remot[ao]s?|teletrabajo|home office|work from home|home based|"
    r"fully remote|work from anywhere)\b")
_PRESENCIAL = re.compile(
    r"\b(on ?site|onsite|presencial|in office|in the office|office based)\b")
_PRESENCIAL_NEGADO = re.compile(
    r"\b(?:no|not|never|without|sin|isn t|isnt)\b[^.;]{0,30}\b(?:on ?site|onsite|presencial)\b"
    r"|\b(?:on ?site|onsite|presencial)\b[^.;]{0,25}\b(?:is\s+)?not\s+"
    r"(?:required|needed|necessary|mandatory)\b")
# Beneficios, entrevistas, estacionamiento, visitas y eventos NO describen el
# puesto. «Onsite gym available» no vuelve presencial una oferta remota.
_PRESENCIAL_NO_MODALIDAD = re.compile(
    r"\b(?:interview|interviews|meeting|meetings|parking|estacionamiento|visit|"
    r"visits|once|quarterly|annual|event|events|training|conference|trip|travel|"
    r"finalist|finalists|week|gym|gimnasio|cafeteria|cafe|lunch|snacks|amenities|"
    r"facilities|perks|benefits|headquarters|hq)\b")
# «This role is onsite 3 days a week» SÍ es modalidad (parcial), aunque la
# oración contenga «week». Exige que el sujeto sea el puesto.
_PRESENCIAL_PARCIAL = re.compile(
    r"\b(?:this|the)\s+(?:role|position|job|puesto)\s+is\s+"
    r"(?:on ?site|onsite|presencial)\b[^.;]{0,20}\bdays?\s+(?:a|per|por)\s+week\b"
    r"|\byou\s+(?:will|must|are\s+expected\s+to)\s+be\s+(?:on ?site|onsite)\b"
    r"[^.;]{0,20}\bdays?\s+(?:a|per)\s+week\b")
_REMOTO_NEGADO = re.compile(
    r"\b(?:not|never|isn t|isnt|aren t|arent|no)\b"
    r"(?!\s+(?:only|just|merely|simply))\s+(?:\w+\s+){0,3}?\bremote\b"
    r"|\bno\s+remote\b"
    r"|\bremote\b[^.;]{0,35}\b(?:is|are)\s+not\b[^.;]{0,25}"
    r"\b(?:permitted|allowed|available|possible|offered|supported)\b")
# «Hybrid Cloud Data Analyst» es contexto tecnológico, no modalidad laboral.
_HIBRIDO_TECNOLOGICO = re.compile(
    r"\bhybrid\b\s+(?:cloud|infrastructure|architecture|systems?|environment|"
    r"deployment|database|storage|network|technology|stack|app|application|"
    r"engine|platform)\b")
_MODALIDAD_EN_REGION = re.compile(
    r"\b(?:remote|remoto|remota|fully|100|distributed|home\s+based|home\s+office|"
    r"work\s+from\s+home|teletrabajo|virtual)\b"
)

# Restricciones laborales que el perfil no puede sostener (restricción declarada que
# impide traslados regulares). Los viajes ocasionales no descartan: dejan la
# oferta en dudosas para revisarla.
_VIAJES = re.compile(
    r"\b(may require travel|travel (is )?required|must be willing to travel|"
    r"travel up to \d+ ?%|willingness to travel|onsite once|onsite \w+ times|"
    r"visit (one of )?our offices?|quarterly onsite|occasional travel)\b")
_REUBICACION = re.compile(
    r"\b(must relocate|relocation (is )?required|required to relocate|"
    r"must be willing to relocate|"
    r"relocation\s+(?:to\s+\w+\s+)?is\s+required|"
    r"relocation\s+(?:to\s+\w+\s+)?es\s+obligatoria|"
    r"se requiere reubicacion|reubicacion obligatoria|"
    r"relocate\s+to\s+\w+\s+is\s+required|"
    r"willingness\s+to\s+relocate\s+is\s+required)\b")
# «No relocation required» y «Relocation is not required» EXIMEN de reubicarse.
# La exigencia y su negación se evalúan por cláusula: antes el regex afirmativo
# veía «relocation required» dentro de «no relocation required» y excluía.
_REUBICACION_NEGADA = re.compile(
    r"\b(?:no|not|never|without|sin)\b[^.;]{0,30}\b(?:relocation|reubicacion)\b"
    r"|\b(?:relocation|reubicacion)\b[^.;]{0,40}\b(?:is\s+)?not\s+"
    r"(?:required|needed|necessary|mandatory|obligatoria)\b")
_HIBRIDO = ("hybrid", "hibrido", "híbrido", "partially remote", "parcialmente remoto")

# Alternativas de MODALIDAD. «or» OFRECE opciones; «and» ACUMULA requisitos.
# «not only remote» no niega el remoto: dice que hay algo más, y por eso mismo
# no confirma que el remoto sea una opción completa. En todos estos casos falta
# información y la elegibilidad debe quedar en `doubtful`, no en `incompatible`.
_MODALIDAD_TOKEN = re.compile(
    r"\b(?:remote|remot[ao]s?|teletrabajo|home office|home based|"
    r"work from home|work from anywhere|fully remote|on ?site|onsite|"
    r"presencial|in office|in the office|office based|hybrid|hibrido)\b")
_DISYUNCION_MODALIDAD = re.compile(r"\b(?:or|o|either|alternatively)\b")
_MODALIDAD_INCOMPLETA = re.compile(
    r"\bnot\s+(?:only|just|merely)\s+remote\b"
    r"|\bremote\s+(?:is\s+)?not\s+(?:only|just)\b")
_MODALIDAD_BARRA = re.compile(
    r"(?:remote|remot[ao])\s*/\s*(?:on\s*site|onsite|presencial|hybrid|hibrido)"
    r"|(?:on\s*site|onsite|presencial|hybrid|hibrido)\s*/\s*(?:remote|remot[ao])",
    re.I)


def _categoria_modalidad(token: str) -> str:
    if re.search(r"remote|remot|teletrabajo|home|anywhere|distributed", token):
        return "remote"
    if re.search(r"onsite|on site|presencial|office", token):
        return "onsite"
    return "hybrid"


def _alternativas_de_modalidad(texto: str, cabecera: str = "") -> bool:
    """¿El aviso ofrece DOS modalidades distintas como opción (o las matiza)?"""
    unidades = _segmentos(texto[:6000], comas=False) + [normalizar(cabecera)]
    for unidad in unidades:
        if _MODALIDAD_INCOMPLETA.search(unidad):
            return True
        tokens = list(_MODALIDAD_TOKEN.finditer(unidad))
        if len(tokens) < 2:
            continue
        if len({_categoria_modalidad(t.group(0)) for t in tokens}) < 2:
            continue
        entre = unidad[tokens[0].end():tokens[-1].start()]
        if _DISYUNCION_MODALIDAD.search(entre):
            return True
    return bool(_MODALIDAD_BARRA.search(texto))


@dataclass
class Componente:
    nombre: str
    maximo: int
    obtenido: float
    aplicable: bool
    estado: str = "calculado"
    detalle: str = ""


@dataclass
class Evaluacion:
    # Dimensión 1: ¿puede postularse?
    elegibilidad: str = "doubtful"
    motivo_elegibilidad: str = ""
    # Dimensión 2: ¿qué tan cerca está del perfil?
    compatibilidad: float | None = None
    # Dimensión 3: ¿cuánto se sabe de verdad?
    confianza: str = "baja"
    razones: list[dict[str, Any]] = field(default_factory=list)
    incertidumbres: list[str] = field(default_factory=list)
    decisivas: list[str] = field(default_factory=list)
    componentes: list[Componente] = field(default_factory=list)
    cobertura: float = 0.0
    #: `observada` = puntaje sobre lo que el aviso declara; `conservadora` = sobre
    #: todo el peso aplicable; `sin_datos` = no hay con qué puntuar.
    escala: str = "conservadora"
    provisional: bool = False
    categoria: str | None = None
    origen_categoria: str = "ninguno"
    vigencia: str = "unknown"
    modalidad: str = "unknown"
    excepcion: bool = False
    anios_requeridos: int | None = None
    requisitos: dict[str, Any] = field(default_factory=dict)
    rules_version: str = RULES_VERSION

    @property
    def score(self) -> float | None:
        """Alias de compatibilidad, por compatibilidad con la base y la interfaz."""
        return self.compatibilidad

    def razones_texto(self) -> list[str]:
        return [r["texto"] for r in self.razones]


# --- Fase 1E · D3: alcance real de «operations analyst» --------------------
# «IT Operations Analyst» (UpGuard) coincide con la pista genérica, pero el
# puesto es ingeniería de plataforma/identidad. Se decide con TÍTULO +
# RESPONSABILIDADES REALES: no hay prohibición global de IT/Security
# Operations; los que efectivamente hacen soporte o Data Operations se apartan
# para revisión humana (origen `texto`), nunca se declaran `eligible` solos.
_TITULO_OPS_TECNICO = re.compile(
    r"\b(?:it|information technology|security|cyber|infosec|infrastructure|"
    r"systems?|network|cloud|devops|platform|technical)\s+"
    r"(?:operations?|ops)\s+analyst\b")
_TAREAS_INGENIERIA_OPS = re.compile(
    r"\b(?:engineering role|infrastructure|zero trust|okta|identity provider|"
    r"idp|mdm|jamf|kandji|endpoint|terraform|kubernetes|devops|cloudflare|"
    r"saas administration|service catalogue|zero touch provisioning|"
    r"attack surface|threat intel|siem|soc|network trust|sso|saml|scim)\b")
_TAREAS_SOPORTE_OPS = re.compile(
    r"\b(?:tickets?|help desk|service desk|zendesk|customer inquiries|"
    r"customer support|live chat|intercom|atencion al cliente|end users?)\b")
_TAREAS_DATOS_OPS = re.compile(
    r"\b(?:data quality|calidad de datos|data governance|data pipelines?|"
    r"dashboards?|sql queries|stored procedures|etl)\b")


def _categoria_ops_tecnica(titulo: str, texto: str):
    """`None` = el título no es de operaciones técnicas especializadas.

    Si lo es: (categoría o None, motivo). Una categoría confirmada por TAREAS
    se devuelve con origen `texto`, para revisión humana.
    """
    if not _TITULO_OPS_TECNICO.search(normalizar(titulo)):
        return None
    cuerpo = normalizar(texto[:6000])
    if _TAREAS_INGENIERIA_OPS.search(cuerpo):
        return (None, "el título y las responsabilidades describen ingeniería de "
                      "operaciones técnicas, fuera de las categorías del perfil")
    if _TAREAS_SOPORTE_OPS.search(cuerpo):
        return ("Customer Support",
                "operaciones técnicas con tareas reales de soporte a usuarios")
    if _TAREAS_DATOS_OPS.search(cuerpo):
        return ("Data Operations",
                "operaciones técnicas con tareas reales de calidad y gestión de datos")
    return (None, "operaciones técnicas sin tareas del perfil confirmadas en el aviso")


def categorias_efectivas(categorias: list[str] | None = None) -> list[str]:
    """Categorías habilitadas por el perfil activo, en el orden de `CATEGORIAS`.

    Si el perfil no declara categorías (dato faltante, perfiles anteriores a
    `perfil-ejemplo-1`) se usan todas: compatibilidad retroactiva explícita, no
    silenciosa. Una categoría del perfil que el código no conoce se ignora y se
    informa por `categorias_no_reconocidas`.
    """
    if not categorias:
        return list(CATEGORIAS)
    pedidas = {c.strip() for c in categorias if isinstance(c, str) and c.strip()}
    efectivas = [c for c in CATEGORIAS if c in pedidas]
    return efectivas or list(CATEGORIAS)


def categorias_no_reconocidas(categorias: list[str] | None = None) -> list[str]:
    """Categorías pedidas por el perfil que la taxonomía no implementa."""
    if not categorias:
        return []
    conocidas = set(CATEGORIAS)
    return sorted({c.strip() for c in categorias
                   if isinstance(c, str) and c.strip() and c.strip() not in conocidas})


def _categoria_por_titulo_contextual(en_titulo: str, cuerpo: str,
                                     permitidas: set[str]) -> tuple[str, str] | None:
    """C01: títulos de soporte/back office reconocidos por patrón y contexto.

    Devuelve (categoría, motivo) o `None`. Nunca devuelve una categoría que el
    perfil no habilite: en ese caso el título queda sin categoría y el motivo lo
    dice, en vez de clasificarlo en una categoría que el perfil no acepta.
    """
    if "VA/Data Entry" in permitidas and _TITULO_ADMINISTRATIVO.search(en_titulo):
        if _ADMIN_GUARDA.search(cuerpo):
            return None
        return ("VA/Data Entry",
                "el título describe tareas administrativas de back office")
    if "Customer Support" in permitidas and _TITULO_SOPORTE_CONTEXTO.search(en_titulo):
        return ("Customer Support",
                "el título describe atención a clientes o mesa de ayuda")
    if "Data Operations" in permitidas and _TITULO_CRM.search(en_titulo):
        return ("Data Operations",
                "el título describe administración y calidad de datos de CRM")
    return None


def _categoria_por_cuerpo(en_titulo: str, en_texto: str,
                          permitidas: set[str]) -> tuple[str, str, str] | None:
    """C02/C03: indicios del cuerpo, con precedencia por responsabilidad.

    Reglas:
    - Una pista de HERRAMIENTA (`power bi`, `business intelligence`) sólo cuenta
      si el título ya es afín a datos. Un tablero que se consulta no convierte un
      puesto de soporte en BI Analyst.
    - Entre las categorías con indicio gana la que además tiene TAREAS descritas
      en el texto; si ninguna las tiene, gana la más específica según `_PISTAS`.
    """
    afin_datos = bool(_TITULO_AFIN_DATOS.search(en_titulo))
    candidatas: list[tuple[str, str]] = []
    for categoria, _, pistas_cuerpo in _PISTAS:
        if categoria not in permitidas:
            continue
        for pista in pistas_cuerpo:
            if not re.search(rf"\b{re.escape(pista)}\b", en_texto):
                continue
            if pista in _PISTAS_CUERPO_DEBILES and not afin_datos:
                continue
            candidatas.append((categoria, pista))
            break
    if not candidatas:
        return None
    con_tareas = [c for c in candidatas if hay_tareas_de(c[0], en_texto)]
    categoria, pista = (con_tareas or candidatas)[0]
    return (categoria,
            f"indicio en el cuerpo con '{pista}' (sin confirmar en el título)",
            "texto")


def categoria_de(titulo: str, texto: str,
                 categorias: list[str] | None = None) -> tuple[str | None, str, str]:
    """Devuelve (categoría, motivo, origen).

    Origen `titulo` es la única vía para una categoría plena. `texto` es indicio:
    sirve para revisar a mano, no para puntuar alto.

    `categorias` son las que habilita el perfil activo (C05). Si se omite, se
    usan todas las de `CATEGORIAS`: mismo comportamiento que `rules-3.1.0`.
    """
    en_titulo = normalizar(titulo)
    cuerpo = normalizar(texto[:6000])
    permitidas = set(categorias_efectivas(categorias))

    # Fase 1E · D3: «IT Operations Analyst» no es Business Analyst por la pista
    # suelta «operations analyst». Se resuelve por título + responsabilidades.
    override = _categoria_ops_tecnica(titulo, texto)
    if override is not None:
        categoria, motivo = override
        if categoria is not None and categoria not in permitidas:
            return (None,
                    f"la categoría detectada ({categoria}) no está habilitada en el perfil",
                    "ninguno")
        return categoria, motivo, ("texto" if categoria else "ninguno")

    for categoria, pistas_titulo, _ in _PISTAS:
        if categoria not in permitidas:
            # C05: la categoría existe en el código pero el perfil no la habilita.
            # Se nombra el hecho en vez de disfrazarlo de «rol fuera de perfil».
            for pista in pistas_titulo:
                if re.search(rf"\b{re.escape(pista)}\b", en_titulo):
                    return (None,
                            f"el título coincide con '{categoria}', que el perfil "
                            f"activo no habilita", "ninguno")
            continue
        for pista in pistas_titulo:
            if re.search(rf"\b{re.escape(pista)}\b", en_titulo):
                return categoria, f"coincidencia en el título con '{pista}'", "titulo"

    if _TITULO_FUERA_DE_PERFIL.search(en_titulo):
        return None, "el título corresponde a un rol fuera de las categorías del perfil", "ninguno"

    # C01: títulos afines por patrón (soporte, back office, CRM), con guardas.
    contextual = _categoria_por_titulo_contextual(en_titulo, cuerpo, permitidas)
    if contextual is not None:
        return contextual[0], contextual[1], "titulo"

    if not _TITULO_AFIN.search(en_titulo):
        return None, "el título no es afín a las categorías del perfil", "ninguno"

    indicio = _categoria_por_cuerpo(en_titulo, normalizar(texto[:1500]), permitidas)
    if indicio is not None:
        return indicio
    return None, "sin coincidencia con las diez categorías del perfil", "ninguno"



_ALCANCE_EN_CUERPO = re.compile(
    r"\b(?:worldwide|world\s?wide|work\s+from\s+anywhere|anywhere\s+in\s+the\s+world|"
    r"open\s+to\s+(?:applicants|candidates)\s+(?:from\s+)?(?:all|any)\s+countries|"
    r"all\s+countries|globally\s+remote|remote\s+globally|"
    r"latin\s+america|latam|south\s+america|the\s+americas|"
    r"international\s+applicants|anywhere\s+in\s+argentina|"
    r"candidates?\s+from\s+any\s+country)\b")


def _alcance_declarado_en_cuerpo(cuerpo: str) -> str | None:
    """T01: alcance compatible declarado EN EL TEXTO del aviso.

    Se usa sólo para detectar CONTRADICCIÓN con la etiqueta de la fuente. No
    otorga elegibilidad por sí solo: si la fuente restringe y el cuerpo amplía,
    el resultado es `duda` con el conflicto registrado, nunca `eligible`.
    """
    m = _ALCANCE_EN_CUERPO.search(cuerpo)
    return m.group(0) if m else None


def _restriccion_en_cuerpo(cuerpo: str) -> bool:
    """Compatibilidad: ¿el cuerpo declara una restricción geográfica explícita?"""
    return _lugar_restringido(_segmentos(cuerpo, comas=False)) is not None


def _territorio(region: str | None, titulo: str, texto: str) -> tuple[str, str, str, str]:
    """Devuelve (estado, motivo, restricción, alcance).

    `alcance` es lo que la interfaz muestra como «a quién contrata»:

    - `mundial`, `argentina`, `internacional`: alcances compatibles.
    - `restringido`: limita a un país o región incompatibles.
    - `desconocido`: no hay dato.

    Orden de autoridad: **cuerpo > título > etiqueta de la fuente**. Una región
    «Argentina» o «Anywhere in the World» no puede tapar un «US only» escrito
    en el aviso. Remoto sigue sin implicar territorio: son dimensiones distintas.
    """
    campo = normalizar(region)
    en_titulo = normalizar(titulo)
    oraciones = _segmentos(texto[:8000], comas=False)
    clausulas = _segmentos(texto[:8000], comas=True)
    cuerpo = normalizar(texto[:8000])

    # Fase 1E: se tipa la declaración territorial ANTES de decidir. Una lista
    # multipaís admitida no es una exclusión; una restricción explícita sí lo es
    # y debe poder evaluarse incluso si el aviso menciona una preferencia.
    alcance_cuerpo = _alcance_declarado_en_cuerpo(cuerpo)
    lista_previa = _territorio_lista_multipais(region, cuerpo) if campo else None
    exclusion_explicita = _exclusion_explicita_de_fuente(
        campo, en_titulo, lista_previa, region)

    def _campo_excluye(motivo: str, restriccion: str):
        """Exclusión por etiqueta de fuente, salvo contradicción con el cuerpo."""
        if alcance_cuerpo:
            return ("duda",
                    f"{motivo}; el cuerpo declara «{alcance_cuerpo}»: metadatos "
                    f"contradictorios, confirmar el alcance antes de postular",
                    restriccion, "desconocido")
        return ("excluye", motivo, restriccion, "restringido")

    # 1) El cuerpo manda. Se revisan también las cláusulas y el texto completo:
    #    la negación se evalúa DENTRO de cada cláusula, no sobre una ventana ciega
    #    de caracteres que podía cruzar de «No agencies please» a «US only».
    lugar = _lugar_restringido([cuerpo] + clausulas + oraciones)
    if lugar:
        return ("excluye",
                f"el aviso restringe la contratación a {lugar}: no admite Argentina",
                lugar, "restringido")
    estado_legal, lugar_legal = _requisito_legal(clausulas + oraciones)
    zona = _zona_horaria(oraciones)

    # 1a) Restricciones OBLIGATORIAS: se deciden antes que cualquier preferencia.
    #     Antes «US work permit preferred» podía tapar un huso obligatorio.
    if estado_legal == "obligatorio":
        return ("excluye",
                f"el aviso exige permiso de trabajo o ciudadanía de {lugar_legal}: "
                f"no admite Argentina",
                lugar_legal, "restringido")
    if zona == "obligatoria":
        return ("excluye",
                "el aviso exige residir en una zona horaria restringida: no admite Argentina",
                "", "restringido")

    # 1b) Preferencias (Fase 1E · D2): sólo producen duda cuando NO hay una
    #     exclusión explícita pendiente en el título o en la etiqueta. Si la hay,
    #     se sigue evaluando y la exclusión gana. Una preferencia nunca anula
    #     una exclusión ni inventa una residencia obligatoria.
    if estado_legal == "preferido" and not exclusion_explicita:
        return ("duda",
                f"el aviso menciona permiso de trabajo de {lugar_legal} sin "
                f"declararlo obligatorio: confirmar si admite Argentina",
                "", _alcance_de_campo(campo))
    if zona == "preferida" and not exclusion_explicita:
        return ("duda",
                "el aviso expresa una preferencia de zona horaria: confirmar si restringe la residencia",
                "", _alcance_de_campo(campo))
    if zona == "dudosa" and not exclusion_explicita:
        return ("duda",
                "el aviso menciona zonas horarias sin aclarar si exige residencia "
                "o sólo disponibilidad: confirmar si admite Argentina",
                "", _alcance_de_campo(campo))
    # «compatible» (ART) y «» (GMT/UTC, dato neutro) siguen a las demás capas:
    # no declaran residencia extranjera ni inventan una restricción.

    # 2) Un país explícito en el título gana a una región permisiva.
    detectado_titulo = (_pais_explicito(en_titulo)
                        or next((p for p in _PAISES_NO_AR
                                 if re.search(rf"\b{re.escape(p)}\b", en_titulo)), None))
    if detectado_titulo:
        return ("excluye", f"el título restringe el puesto a {detectado_titulo}",
                detectado_titulo, "restringido")

    # 3) Etiqueta de la fuente.
    if campo:
        # 3a') Fase 1E · D1: lista de países DONDE SE ACEPTAN POSTULANTES.
        #      Argentina/LATAM/Américas en la lista no se descarta porque la
        #      lista nombre además otros países. La contradicción sin resolver
        #      (etiqueta Canada/USA + «anywhere in the Americas») va a dudosas.
        if lista_previa is not None:
            return lista_previa
        # 3a) «Anywhere in X»: decide X, no la palabra «Anywhere».
        m = re.search(r"\banywhere\s+(?:in|within)\s+(?:the\s+)?(.+)$", campo)
        if m:
            destino = _MODALIDAD_EN_REGION.sub(" ", m.group(1)).strip()
            # Un país nombrado explícitamente gana al parecido con un topónimo
            # argentino: «Anywhere in Cordoba, Spain» no es Córdoba (AR).
            if _pais_explicito(destino, etiqueta=True):
                return _campo_excluye(f"la fuente restringe la ubicación a {region}",
                                      region or "")
            if "argentina" in destino or _contexto_argentino(destino):
                return ("ok", f"la fuente declara alcance compatible: {region}",
                        region or "", "argentina" if "argentina" in destino else "internacional")
            if re.search(r"\b(?:latam|latin\s+america|south\s+america|americas)\b", destino):
                return ("ok", f"la fuente declara alcance compatible: {region}",
                        region or "", "internacional")
            if _restringido_en(destino):
                return _campo_excluye(f"la fuente restringe la ubicación a {region}",
                                      region or "")
            if re.search(r"\b(?:world|globe|planet|worldwide|international)\b", destino):
                return ("ok", f"la fuente declara alcance compatible: {region}",
                        region or "", "mundial")
            return ("duda", f"región declarada no concluyente: {region}",
                    region or "", "desconocido")

        # 3b) País extranjero explícito: prioridad absoluta sobre el contexto
        #     argentino. «Cordoba, Spain» y «La Plata, Maryland, USA» no son AR.
        if _pais_explicito(campo, etiqueta=True):
            return _campo_excluye(f"la fuente restringe la ubicación a {region}",
                                  region or "")

        # 3c) Contexto argentino confirmado: «La Plata, AR» NO es Arkansas.
        if _contexto_argentino(campo):
            return ("ok", f"la fuente declara Argentina: {region}", "argentina", "argentina")

        # 3d) Alcance declarado. Ya no contiene términos de modalidad.
        if any(p in campo for p in _PERMITIDOS):
            return ("ok", f"la fuente declara alcance compatible: {region}",
                    region or "", _alcance_de_campo(campo))

        # 3d') T03: estado o ciudad extranjera nombrada completa. Antes
        #      «Ohio», «Berlin (remote)» o «Bulgaria» quedaban en «dudosa»
        #      porque sólo se reconocían el código de dos letras y el país.
        estado_largo = next((e for e in _ESTADOS_EEUU_NOMBRES
                             if re.search(rf"\b{re.escape(e)}\b", campo)), None)
        if estado_largo:
            return _campo_excluye(
                f"la región es un estado de EE. UU.: {region}", region or "")
        ciudad = next((c for c in _CIUDADES_NO_AR
                       if re.search(rf"\b{re.escape(c)}\b", campo)), None)
        if ciudad:
            return _campo_excluye(
                f"la región es una ciudad extranjera: {region}", region or "")

        # 3d) País, código ISO o estado de EE. UU. declarado.
        detectado = next((p for p in _PAISES_NO_AR
                          if re.search(rf"\b{re.escape(p)}\b", campo)), None)
        if detectado:
            return _campo_excluye(f"la fuente restringe la ubicación a {region}",
                                  region or "")
        if _EEUU.search(campo):
            return _campo_excluye(
                f"la región declarada apunta a Estados Unidos: {region}", region or "")

        iso = _iso_region(region)
        if iso == "argentina":
            return ("ok", f"la fuente declara Argentina: {region}", "argentina", "argentina")
        if iso == "ambiguo":
            return ("duda", f"código de país ambiguo en la región: {region}",
                    region or "", "desconocido")
        if iso:
            return _campo_excluye(
                f"la fuente restringe la ubicación a {region} ({iso})", region or "")

        ultimo = normalizar(re.sub(r"\([^)]*\)", " ",
                                   (region or "").rsplit(",", 1)[-1]).strip(" ,"))
        if ultimo in _ESTADOS_EEUU:
            return _campo_excluye(
                f"la región es un estado de EE. UU.: {region}", region or "")
        if any(ciudad in campo for ciudad in _CIUDADES_EEUU):
            return _campo_excluye(
                f"la región es una ciudad de EE. UU.: {region}", region or "")
        return ("duda", f"región declarada no concluyente: {region}",
                region or "", "desconocido")

    # 4) Sin etiqueta: sólo queda el cuerpo.
    if re.search(r"\b(no visa sponsorship|cannot sponsor|without sponsorship)\b", cuerpo):
        return ("duda", "el aviso no patrocina visa: hay que confirmar si admite Argentina",
                "", "desconocido")
    if any(p in cuerpo for p in ("remote worldwide", "work from anywhere",
                                 "anywhere in the world")):
        return ("ok", "el texto declara alcance mundial", "worldwide", "mundial")
    return ("duda", "la fuente no publica el territorio admitido", "", "desconocido")


def _hibrido_de_trabajo(unidad: str) -> bool:
    """«Hybrid» como modalidad, descartando el contexto tecnológico."""
    return (any(p in unidad for p in _HIBRIDO)
            and not _HIBRIDO_TECNOLOGICO.search(unidad))


def _presencial_de_rol(unidad: str) -> bool:
    """¿La oración declara presencialidad DEL PUESTO y no de otra cosa?"""
    if not _PRESENCIAL.search(unidad):
        return False
    if _PRESENCIAL_NEGADO.search(unidad):
        return False
    # Una declaración explícita del puesto gana a los marcadores incidentales.
    if _PRESENCIAL_PARCIAL.search(unidad):
        return True
    return not _PRESENCIAL_NO_MODALIDAD.search(unidad)


def _modalidad(region: str | None, titulo: str, texto: str, contrato: str | None = None) -> str:
    """Modalidad **declarada**: cómo se trabaja, nunca dónde se contrata.

    Precedencia explícita (Fase 1C/1D): negación del remoto > ALTERNATIVAS de
    modalidad (duda) > presencialidad del puesto > híbrido > remoto >
    desconocido. Ante evidencia contradictoria NUNCA se elige automáticamente
    `remote`: la presencialidad declarada gana, porque es la restricción que el
    perfil no puede sostener. Una disyunción `or` no es presencialidad.
    """
    cabecera = normalizar(f"{region or ''} {titulo or ''} {contrato or ''}")
    titulo_plano = normalizar(titulo)
    oraciones = _segmentos(texto[:6000], comas=False)

    # 1) «Not a remote position» / «Remote work is not permitted».
    if any(_REMOTO_NEGADO.search(u) for u in [cabecera] + oraciones):
        return "onsite"

    # 1b) «Remote or onsite» / «Hybrid or remote» / «not only remote» son
    #     ALTERNATIVAS o matices, no una declaración de presencialidad. No hay
    #     evidencia de que el remoto sea una opción completa: queda `unknown` y
    #     la elegibilidad se resuelve como duda, no como descarte.
    if _alternativas_de_modalidad(texto, cabecera):
        return "unknown"

    # 2) Presencialidad declarada en el título, aunque la región sea permisiva.
    if _presencial_de_rol(titulo_plano):
        return "hybrid" if _PRESENCIAL_PARCIAL.search(titulo_plano) else "onsite"

    # 3) Cabecera (región, título, contrato). «Hybrid Cloud» no cuenta.
    if _hibrido_de_trabajo(cabecera):
        return "hybrid"
    if any(p in cabecera for p in _REMOTO):
        return "remote"

    # 4) Cuerpo: se recoge TODA la evidencia antes de decidir. Así «Remote
    #    team. Onsite role.» no se resuelve por la primera coincidencia.
    presencial = [u for u in oraciones if _presencial_de_rol(u)]
    hibrido = any(_hibrido_de_trabajo(u) for u in oraciones)
    remoto = any(_REMOTO_CUERPO.search(u) or any(p in u for p in _REMOTO)
                 for u in oraciones)
    if hibrido:
        return "hybrid"
    if presencial:
        return ("hybrid" if any(_PRESENCIAL_PARCIAL.search(u) for u in presencial)
                else "onsite")
    if remoto:
        return "remote"
    return "unknown"


def _en_zona_local(region: str | None, perfil: dict) -> bool:
    if not region:
        return False
    base = normalizar(region)
    zonas = perfil.get("territorio", {}).get("presencial") or ["la plata"]
    return any(normalizar(z) in base for z in zonas)


def _modalidad_viable(modalidad: str, region: str | None, perfil: dict) -> tuple[str, str]:
    """Traduce modalidad + territorio en un veredicto de elegibilidad."""
    territorio = perfil.get("territorio", {})
    obligatorio = bool(territorio.get("remoto_obligatorio"))
    if modalidad == "remote":
        return "ok", "el aviso es remoto"
    if modalidad == "unknown":
        return "duda", "no se declara la modalidad; hay que confirmarla antes de postular"
    if modalidad == "hybrid":
        if _en_zona_local(region, perfil) and territorio.get("acepta_hibrido_en_zona", True):
            return "duda", f"híbrido en {region}: exige presencialidad parcial en tu zona"
        return "excluye", "híbrido fuera de tu zona: exige presencialidad que no podés sostener"
    if _en_zona_local(region, perfil):
        return "duda", f"presencial en {region}: está en tu zona, pero no es remoto"
    if obligatorio:
        return ("excluye",
                f"presencial en {region or 'una ubicación no declarada'}: "
                f"el perfil requiere remoto")
    return "duda", "presencial fuera de tu zona"


def _idioma_del_aviso(texto: str) -> str:
    """Idioma dominante del aviso: `es`, `en` o `desconocido`.

    Se usa para no dar por cumplido un requisito que el aviso ni menciona, y para
    no inventar un requisito de idioma en un aviso escrito en español.
    """
    muestra = normalizar(texto[:1500])
    if len(muestra) < 80:
        return "desconocido"
    palabras = re.findall(r"[a-záéíóúñü]+", muestra)
    if not palabras:
        return "desconocido"
    es = sum(1 for p in palabras if p in _ESTOPWORDS)
    en = sum(1 for p in palabras if p in _ENSTOPWORDS)
    if es > en * 1.2:
        return "es"
    if en > es * 1.2:
        return "en"
    return "desconocido"


def _ingles_en_clausula(clausula: str, nivel: str,
                        nivel_mostrado: str) -> tuple[str, str, int]:
    """Compara el nivel CEFR pedido contra el nivel REAL del perfil (B1)."""
    cefr = re.search(r"\b(a1|a2|b1|b2|c1|c2)\b", clausula)
    if cefr:
        pedido = cefr.group(1)
        if _NIVELES_CEFR[pedido] <= _RANGO_PERFIL.get(nivel, 0):
            return ("cumplido",
                    f"exige inglés {pedido.upper()} y el perfil declara {nivel_mostrado}", 8)
        return ("parcial",
                f"exige inglés {pedido.upper()}; el perfil declara {nivel_mostrado}", 0)
    if re.search(r"\b(native|fluent|bilingual)\b", clausula):
        return ("parcial",
                f"exige inglés fluido o nativo; el perfil declara {nivel_mostrado}", 0)
    if _RANGO_PERFIL.get(nivel, 0) >= 4:
        return ("cumplido", f"exige inglés y el perfil declara {nivel_mostrado}", 8)
    return ("parcial",
            f"exige inglés con nivel no comparable al perfil ({nivel_mostrado})", 4)


@dataclass
class AnalisisIdiomas:
    """Resultado de evaluar TODOS los requisitos de idioma por separado."""
    estado: str
    motivo: str
    puntos: int
    bloquea: bool = False          # requisito explícito incumplido → dudosa
    requisitos: list[dict[str, str]] = field(default_factory=list)


_PEOR_IDIOMA = {"cumplido": 0, "parcial": 1, "incumplido": 2}


def _hecho_idioma(idioma: str, clausula: str, nivel: str,
                  nivel_mostrado: str) -> tuple[str, str, int, bool]:
    """Estado de UN idioma exigido: (estado, motivo, puntos, bloquea)."""
    if idioma == "english":
        estado, motivo, puntos = _ingles_en_clausula(
            clausula, nivel, nivel_mostrado)
        return estado, motivo, puntos, estado != "cumplido"
    if idioma == "spanish":
        return ("cumplido", "exige español y el perfil declara español nativo",
                8, False)
    return ("incumplido", f"exige {idioma}, un idioma que el perfil no declara",
            0, True)


def _analisis_idiomas(titulo: str, texto: str, perfil_nivel: str) -> AnalisisIdiomas:
    """Evalúa cada cláusula por separado; gana el PEOR estado PENDIENTE.

    - Un idioma satisfecho (español) no puede ocultar otro incumplido.
    - En un grupo de ALTERNATIVAS gana el MEJOR estado de sus miembros: basta
      con que uno satisfaga el requisito. El resultado no depende del orden.
    - Una contradicción (`required` + `not required` del mismo idioma) se aparta
      para revisión humana: ni cumplimiento confirmado ni descarte. Un requisito
      incumplido EN OTRA cláusula sigue excluyendo.
    """
    nivel = (perfil_nivel or "").lower()
    nivel_mostrado = (nivel or "desconocido").upper()
    requeridos: dict[str, tuple[str, str, int, bool]] = {}
    alternativas: list[list[tuple[tuple[str, str, int, bool], str]]] = []
    cancelados: set[str] = set()

    for clausula, lenguajes, modificador, es_alternativa in _clausulas_idioma(titulo, texto):
        if modificador == "cancelado":
            cancelados.update(lenguajes)
            continue
        if modificador != "requerido":
            continue
        hechos = [(_hecho_idioma(i, clausula, nivel, nivel_mostrado), i)
                  for i in lenguajes]
        if es_alternativa and len(lenguajes) >= 2:
            alternativas.append(hechos)
            continue
        for hecho, idioma in hechos:
            anterior = requeridos.get(idioma)
            if anterior is None or _PEOR_IDIOMA[hecho[0]] > _PEOR_IDIOMA[anterior[0]]:
                requeridos[idioma] = hecho

    exigidos = set(requeridos) | {i for grupo in alternativas for _, i in grupo}
    contradictorios = exigidos & cancelados
    pendientes_individuales = {i: r for i, r in requeridos.items()
                               if i not in cancelados}
    pendientes_grupos = [[par for par in g if par[1] not in cancelados]
                         for g in alternativas]
    pendientes_grupos = [g for g in pendientes_grupos if g]

    lista = [{"idioma": i, "estado": r[0], "motivo": r[1]}
             for i, r in sorted(requeridos.items())]
    for grupo in alternativas:
        mejor = min((h for h, _ in grupo), key=lambda h: _PEOR_IDIOMA[h[0]])
        nombres = " / ".join(sorted(i for _, i in grupo))
        lista.append({"idioma": nombres, "estado": mejor[0],
                      "motivo": "alternativa: " + mejor[1]})

    estados = (list(pendientes_individuales.values())
               + [min((h for h, _ in g), key=lambda h: _PEOR_IDIOMA[h[0]])
                  for g in pendientes_grupos])
    peor = max(estados, key=lambda r: _PEOR_IDIOMA[r[0]]) if estados else None

    # Un incumplido explícito en otra cláusula no se compensa con una duda.
    if peor and peor[0] == "incumplido":
        return AnalisisIdiomas("incumplido", peor[1], peor[2],
                               bloquea=True, requisitos=lista)
    if contradictorios:
        nombres = ", ".join(sorted(contradictorios))
        return AnalisisIdiomas(
            "contradictorio",
            f"contradicción lingüística sobre {nombres}: el aviso exige y niega "
            f"el mismo idioma; requiere revisión",
            0, bloquea=True, requisitos=lista)
    if peor:
        return AnalisisIdiomas(peor[0], peor[1], peor[2],
                               bloquea=bool(peor[3] or peor[0] != "cumplido"),
                               requisitos=lista)

    idioma_aviso = _idioma_del_aviso(texto)
    if idioma_aviso == "en":
        return AnalisisIdiomas("parcial",
                               "el aviso está en inglés pero no declara el nivel exigido",
                               4, requisitos=lista)
    if idioma_aviso == "es":
        return AnalisisIdiomas("no_aplicable",
                               "el aviso está en español: no declara requisito de idioma",
                               8, requisitos=lista)
    return AnalisisIdiomas(
        "desconocido",
        "no se declara requisito de idioma y el texto es demasiado corto para "
        "reconocer el idioma del aviso" if len(normalizar(texto[:1500])) < 80
        else "no se declara requisito de idioma",
        0, requisitos=lista)


def _idioma(titulo: str, texto: str, perfil_nivel: str) -> tuple[str, str, int]:
    """API histórica de 3 valores; delega en el análisis estructurado."""
    a = _analisis_idiomas(titulo, texto, perfil_nivel)
    return a.estado, a.motivo, a.puntos


def _restricciones_laborales(texto: str) -> tuple[str, str | None]:
    """Viajes, presencialidad ocasional o reubicación declarados en el aviso."""
    base = normalizar(texto[:8000])
    for unidad in _segmentos(texto[:8000], comas=False):
        if _REUBICACION_NEGADA.search(unidad):
            continue
        if _REUBICACION.search(unidad):
            return "excluye", "exige reubicación: el perfil no puede trasladarse"
    if _VIAJES.search(base):
        return ("duda",
                "el aviso menciona viajes o visitas presenciales: confirmá la frecuencia")
    return "ok", None


# --- Formación: título académico + marcador de obligatoriedad --------------
_GRADO = re.compile(
    r"\b(?:bachelor|bachelors|master|masters|msc|phd|doctorate|licenciatura|"
    r"titulo|university degree|college degree|degree|grado universitario|"
    r"carrera universitaria)\b")
_GRADO_FALSO_AMIGO = re.compile(
    r"\b(?:high|greater|some|low|certain|reasonable)\s+degree\s+of\b")
_REQ_GRADO = re.compile(
    r"\b(?:required|requerido|requiere|se requiere|obligatorio|excluyente|"
    r"mandatory|must|indispensable|is a must|minimum|exige|needed)\b")
_GRADO_NEGADO = re.compile(
    r"\b(?:no|not|sin|never|isn t)\b[^.;]{0,25}"
    r"\b(?:degree|titulo|licenciatura|bachelor)\b"
    r"|\b(?:degree|titulo|bachelor)\b[^.;]{0,25}"
    r"\b(?:not|no)\s+(?:required|needed|necessary)\b")
_GRADO_PREFERIDO = re.compile(
    r"\b(?:preferred|preferible|deseable|a plus|nice to have|bonus|optional|opcional)\b")
#: E01: alternativas explícitas al título. «Bachelor's degree or equivalent
#: experience» NO es lo mismo que «Bachelor's degree required»: la primera admite
#: trayectoria y la segunda no. No se infiere ninguna equivalencia que el aviso
#: no escriba.
_GRADO_EQUIVALENTE = re.compile(
    r"\b(?:or|o)\s+(?:an?\s+)?(?:equivalent|comparable|similar|related)\s+"
    r"(?:work\s+|professional\s+|practical\s+|relevant\s+|hands.?on\s+)?"
    r"(?:experience|experiencia|trayectoria)\b"
    r"|\b(?:or|o)\s+(?:equivalent|comparable)\b"
    r"|\bexperience\s+(?:may|can)\s+(?:be\s+)?(?:substitute|replace|count)\b"
    r"|\bin\s+lieu\s+of\s+(?:a\s+)?degree\b"
    r"|\bor\s+demonstrable\s+experience\b"
    r"|\bdegree\s+or\s+(?:equivalent\s+)?experience\b"
)



def _formacion(texto: str) -> tuple[str, str | None]:
    """`excluye`, `duda`, `ok`, `desconocido`: título + obligatoriedad.

    «Bachelor's degree in Statistics required» y «Título en Estadística
    excluyente» se detectan por sus dos piezas, no por una frase exacta.
    «No degree needed» EXIME el requisito: el perfil (sin título terminado) lo
    satisface, y por eso `ok` es alcanzable y el puntaje puede llegar a 100.
    Antes `ok` era una rama muerta y el techo real era 93/100.
    """
    estados: list[tuple[str, str]] = []
    for unidad in _segmentos(texto, comas=True):
        if not _GRADO.search(unidad) or _GRADO_FALSO_AMIGO.search(unidad):
            continue
        if _GRADO_NEGADO.search(unidad):
            estados.append(("ok", "el aviso declara que no exige título"))
            continue
        if _REQ_GRADO.search(unidad):
            # E01: si la misma cláusula ofrece una alternativa explícita, el
            # título no es un corte duro: va a revisión, no a descarte.
            if _GRADO_EQUIVALENTE.search(unidad):
                estados.append(("duda",
                                "título universitario o experiencia equivalente"))
            else:
                estados.append(("excluye", "título universitario obligatorio"))
        elif _GRADO_PREFERIDO.search(unidad):
            estados.append(("duda", "título universitario preferido"))
        elif _GRADO_EQUIVALENTE.search(unidad):
            # «Bachelor's degree or equivalent experience», sin «required»:
            # sigue siendo una exigencia, pero con alternativa explícita.
            estados.append(("duda", "título universitario o experiencia equivalente"))
        elif _GRADO_EQUIVALENTE.search(unidad):
            # «Bachelor's degree or equivalent experience», sin «required»:
            # sigue siendo una exigencia, pero con alternativa explícita.
            estados.append(("duda", "título universitario o experiencia equivalente"))
    conjunto = {e for e, _ in estados}
    if {"excluye", "ok"} <= conjunto:
        return "duda", "formación contradictoria: el aviso exige y exime el título"
    if "excluye" in conjunto:
        return "excluye", "título universitario obligatorio"
    if "ok" in conjunto:
        return "ok", "el aviso declara que no exige título"
    if estados:
        return "duda", estados[0][1]
    return "desconocido", None



# --- Experiencia: años LABORALES, no edad ni antigüedad de empresa ----------
_NO_EXPERIENCIA_LABORAL = re.compile(
    r"\b(?:or older|old|of age|de edad)\b"
    r"|\b(?:must be|minimum age|age of)\b"
    r"|\b(?:company|firm|business|organisation|organization|product|empresa|"
    r"antiguedad|founded|established|on the market|years of history|years ago|"
    r"in business)\b")
_PREFERENCIA_ANIOS = re.compile(
    r"\b(?:ideally|preferably|preferred|preferible|preferiblemente|deseable|"
    r"a plus|nice to have|optional)\b")
_ANIOS_HERRAMIENTA = re.compile(
    r"^\s*(?:of|with|using|con|en|in)\s+(?:" +
    "|".join(re.escape(s) for s in _SKILLS) + r")\b")


def anios_requeridos(texto: str) -> int | None:
    """Mayor exigencia LABORAL declarada; `None` si no hay ninguna.

    Se descartan explícitamente la edad, la antigüedad de la empresa o del
    producto, las preferencias («ideally 5 years») y los años con una
    HERRAMIENTA («1 year of Python»). Ya no se toma el menor número a ciegas.
    """
    validos: list[int] = []
    for unidad in _segmentos(texto[:6000], comas=True):
        if _NO_EXPERIENCIA_LABORAL.search(unidad) or _PREFERENCIA_ANIOS.search(unidad):
            continue
        for m in _ANIOS.finditer(unidad):
            numero = int(m.group(1))
            # Tope de cordura (el esquema de IA admite hasta 40). Un «25+ years»
            # es una exigencia laboral real y debe detectarse; antes el techo de
            # 20 lo descartaba y la oferta quedaba como elegible.
            if not 0 < numero <= 40:
                continue
            if _ANIOS_HERRAMIENTA.search(unidad[m.end():m.end() + 60]):
                continue
            validos.append(numero)
    return max(validos) if validos else None


def _experiencia(titulo: str, texto: str, declarado: str | None,
                 cobertura_competencias: float) -> tuple[str, str, int | None]:
    """`excluye` / `duda` / `excepcion` / `cumplido` / `desconocido`.

    `desconocido` no es `cumplido`: si el aviso no dice cuántos años pide ni qué
    seniority tiene, no hay evidencia para dar los 20 puntos.
    """
    base = normalizar(f"{titulo} {declarado or ''}")
    if _SENIORITY_EXCLUYE.search(base):
        return "excluye", f"el título declara un nivel superior al perfil: {titulo}", None
    if _SENIORITY_DUDA.search(base):
        # E02: un «Customer Success Manager» o un «Account Manager» administra
        # cuentas, no necesariamente personas. Se aparta sólo si el aviso lo
        # confirma; si no, se sigue evaluando por años y seniority declarados.
        if (_GESTION_DE_CUENTA.search(base)
                and not _EVIDENCIA_GESTION.search(normalizar(texto[:6000]))):
            pass
        else:
            return "duda", f"el título implica responsabilidad de gestión: {titulo}", None

    intermedia = _SENIORITY_INTERMEDIA.search(base)
    if intermedia:
        # Un nivel intermedio no es gestión: es una banda por encima de junior.
        # Se informa de dónde viene para no atribuirlo al título cuando lo
        # declaró la fuente en su campo `seniority`.
        en_titulo = _SENIORITY_INTERMEDIA.search(normalizar(titulo))
        origen = "el título" if en_titulo else "la fuente"
        return ("duda",
                f"{origen} declara un nivel {intermedia.group(0)}: revisar si "
                f"encaja con un perfil junior", None)

    # Seniority obligatorio también puede estar en el cuerpo, no sólo en el
    # título. Exige un marcador de obligatoriedad: «senior stakeholders» NO.
    for unidad in _segmentos(texto[:6000], comas=True):
        if _SENIORITY_CUERPO.search(unidad) and _REQ_SENIORITY.search(unidad):
            return ("excluye",
                    "el cuerpo exige un nivel de seniority superior al perfil", None)

    anios = anios_requeridos(texto)
    if anios is None:
        # Seniority declarado y compatible (junior, entry level, trainee).
        if re.search(r"\b(junior|jr|entry level|trainee|practicante|sin experiencia)\b",
                     normalizar(f"{titulo} {declarado or ''} {texto[:600]}")):
            return "cumplido", "el aviso declara nivel junior o inicial", None
        return "desconocido", "", None
    if anios >= ANIOS_EXCLUYEN:
        return "excluye", f"pide {anios}+ años de experiencia", anios
    if anios >= ANIOS_EXCEPCION_DESDE:
        if cobertura_competencias >= COBERTURA_EXCEPCION:
            return ("excepcion",
                    f"pide {anios}+ años, pero el perfil cubre "
                    f"{int(cobertura_competencias * 100)} % de las habilidades requeridas", anios)
        return ("duda",
                f"pide {anios}+ años y el perfil cubre sólo "
                f"{int(cobertura_competencias * 100)} % de las habilidades", anios)
    # Sólo se llega aquí con anios == 1 (2..7 se resolvieron arriba como
    # excepción/duda y >= 8 excluye). La segunda rama era inalcanzable y además
    # atribuía al perfil «1» año que nunca se declaró así.
    return ("cumplido",
            f"pide {anios} año(s) de experiencia, dentro de lo declarado por el perfil",
            anios)


def hay_tareas_de(categoria: str | None, texto: str) -> bool:
    """¿El cuerpo describe tareas propias de la categoría?

    Es la evidencia que separa «el título tiene la palabra» de «el puesto es de
    eso». Sin esto, un aviso que sólo dice «Office Assistant» se llevaba los 25
    puntos de categoría y tareas sin que el texto nombrara una sola tarea.
    """
    if not categoria:
        return False
    plano = normalizar(texto[:6000])
    return any(re.search(rf"\b{re.escape(t)}\b", plano) for t in _TAREAS.get(categoria, ()))


_SINONIMOS_CATEGORIA: dict[str, tuple[str, ...]] = {
    "Data Analyst": ("data analyst", "data analysis", "analytics", "data analytics"),
    "Data Scientist": ("data scientist", "data science", "machine learning"),
    "Business Analyst": ("business analyst", "business analysis", "functional analyst"),
    "BI Analyst": ("bi", "business intelligence", "power bi", "bi analyst"),
    "Reporting Analyst": ("reporting", "reports", "reporting analyst"),
    "Data Operations": ("data operations", "data ops", "data quality", "data entry",
                        "data management"),
    "SQL Analyst": ("sql", "sql analyst"),
    "Research Analyst": ("research", "market research", "research analyst"),
    "VA/Data Entry": ("virtual assistant", "va", "administrative", "back office",
                      "data entry", "admin"),
    "Customer Support": ("customer support", "customer service", "support", "helpdesk",
                         "help desk", "customer success", "client service"),
}


def _categoria_corroborada(categoria: str | None, categoria_fuente: str | None) -> bool | None:
    """¿La etiqueta de la fuente coincide con la categoría del texto?

    `None` = la fuente no publicó categoría. Nunca decide: sólo corrobora o deja
    constancia de la discrepancia. Una etiqueta externa no puede convertir un
    aviso en elegible ni descartarlo por sí sola (C04).
    """
    if not categoria or not categoria_fuente:
        return None
    base = normalizar(categoria_fuente)
    sinonimos = _SINONIMOS_CATEGORIA.get(categoria, ())
    return any(re.search(rf"\b{re.escape(s)}\b", base) for s in sinonimos)


def _skills_requeridas(texto: str, habilidades: dict[str, float],

                       extra: str | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """Cruza las habilidades pedidas con el perfil, ponderadas por nivel.

    Devuelve `(aplicables, faltantes, informativas)`:

    - `aplicables`: pedidas y declaradas por el perfil → puntúan por nivel.
    - `faltantes`: pedidas, del vocabulario técnico y NO declaradas → restan.
    - `informativas`: pedidas del vocabulario de soporte/back office y no
      declaradas → se muestran al revisor, no restan ni suman. Son herramientas
      de un puesto que el perfil no cubre: descontarlas castigaría dos veces.

    `extra` es la evidencia estructurada de la fuente (`observations.skills`).
    Se usa como texto adicional porque es un dato de origen, no una inferencia.
    """
    plano = normalizar(f"{texto}\n{extra or ''}")
    aplicables: list[dict] = []
    faltantes: list[dict] = []
    informativas: list[dict] = []

    for skill in _SKILLS + [s for s in _SKILLS_SOPORTE if s not in _SKILLS]:
        if not re.search(rf"\b{re.escape(skill)}\b", plano):
            continue
        posicion = plano.find(skill)
        ventana = plano[max(0, posicion - 120): posicion + 120]
        obligatorio = bool(_REQUISITO_FUERTE.search(ventana))
        peso = 2 if obligatorio else 1
        item = {"skill": skill, "peso": peso, "obligatorio": obligatorio}
        if skill in habilidades:
            item["nivel"] = habilidades[skill]
            item["peso_cumplido"] = peso * habilidades[skill]
            aplicables.append(item)
        elif skill in _SKILLS_SOPORTE and skill not in _SKILLS:
            item["peso_cumplido"] = 0.0
            informativas.append(item)
        else:
            item["peso_cumplido"] = 0.0
            faltantes.append(item)
    return aplicables, faltantes, informativas



def _vigencia(expira_en: str | None, publicado_en: str | None,
              ahora: datetime | None = None) -> str:
    """`closed`, `open`, `stale` o `unknown`.

    `stale` (V01) es un estado propio: el aviso se publicó hace más de
    `DIAS_VIGENCIA_RAZONABLE` días y nadie confirmó que siga abierto. No es
    `closed` —la antigüedad no prueba el cierre— ni `open` —no hay evidencia de
    disponibilidad—. Va a revisión, nunca a alerta.
    """
    ahora = ahora or datetime.now(timezone.utc)
    if expira_en:
        try:
            return "open" if datetime.fromisoformat(expira_en.replace("Z", "+00:00")) > ahora else "closed"
        except ValueError:
            pass
    if not publicado_en:
        return "unknown"
    try:
        publicado = datetime.fromisoformat(publicado_en.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    if (ahora - publicado).days <= DIAS_VIGENCIA_RAZONABLE:
        return "open"
    return "stale"


def _salario_comparable(salario: dict | None) -> bool:
    if not salario:
        return False
    periodo = (salario.get("periodo") or "").lower()
    return bool(salario.get("moneda")) and bool(periodo) and periodo != "desconocido"


def _confianza(componentes: list[Componente], vigencia: str, origen_categoria: str,
               modalidad: str, publicado_en: str | None, cobertura: float) -> str:
    """Cuánta información real hay. Un componente sin datos siempre resta."""
    faltantes = 0
    if not any(c.nombre == "habilidades" and c.estado != "sin_datos" for c in componentes):
        faltantes += 1
    if modalidad == "unknown":
        faltantes += 1
    if not publicado_en:
        faltantes += 1
    if vigencia in {"unknown", "stale"}:
        faltantes += 1
    if origen_categoria == "texto":
        faltantes += 1
    if any(c.estado == "sin_datos" for c in componentes):
        faltantes += 1
    if cobertura < 0.5:
        faltantes += 1
    if faltantes == 0:
        return "alta"
    if faltantes <= 2:
        return "media"
    return "baja"


def evaluar(oferta: dict, perfil: dict) -> Evaluacion:
    """oferta: titulo, empresa, region, texto, salario, seniority, expira_en."""
    titulo = oferta.get("titulo") or ""
    texto = oferta.get("texto") or ""
    region = oferta.get("region")

    habilidades: dict[str, float] = {}
    for habilidad in perfil.get("habilidades", []):
        nombre = normalizar(habilidad.get("nombre", ""))
        if nombre:
            habilidades[nombre] = max(habilidades.get(nombre, 0.0),
                                      peso_habilidad(habilidad.get("nivel")))

    categoria, motivo_categoria, origen_categoria = categoria_de(
        titulo, texto, perfil.get("categorias"))
    territorio, motivo_territorio, restriccion, alcance = _territorio(region, titulo, texto)
    formacion, motivo_formacion = _formacion(texto)
    laboral, motivo_laboral = _restricciones_laborales(texto)
    modalidad = _modalidad(region, titulo, texto, oferta.get("tipo_contrato"))
    vigencia = _vigencia(oferta.get("expira_en"), oferta.get("publicado_en"))

    # C04: la etiqueta de la fuente es EVIDENCIA, no veredicto. `categoria_fuente`
    # (columna de `observations`) y `tipo_contrato` (tipo de empleo del aviso) son
    # campos distintos: mezclarlos hacía que «Customer Service» se leyera como
    # modalidad de trabajo.
    corroborada = _categoria_corroborada(categoria, oferta.get("categoria_fuente"))
    aplicables, faltantes, informativas = _skills_requeridas(
        texto, habilidades, oferta.get("skills"))
    peso_total = sum(i["peso"] for i in aplicables + faltantes)
    peso_cumplido = sum(i["peso_cumplido"] for i in aplicables)
    cobertura_competencias = (peso_cumplido / peso_total) if peso_total else 0.0


    experiencia, motivo_experiencia, anios = _experiencia(
        titulo, texto, oferta.get("seniority"), cobertura_competencias)
    analisis_idiomas = _analisis_idiomas(
        titulo, texto, perfil.get("idioma", {}).get("ingles", "desconocido"))
    idioma = analisis_idiomas.estado
    motivo_idioma = analisis_idiomas.motivo
    puntos_idioma = analisis_idiomas.puntos

    razones: list[dict[str, Any]] = []
    incertidumbres: list[str] = []
    decisivas: list[str] = []
    if _alternativas_de_modalidad(
            texto, f"{region or ''} {titulo or ''} {oferta.get('tipo_contrato') or ''}"):
        mensaje = ("el aviso declara modalidades alternativas: confirmar si el "
                   "trabajo remoto es una opción completa")
        incertidumbres.append(mensaje)
        razones.append({"tipo": "modalidad", "texto": mensaje, "efecto": "duda"})
    excluye = False
    # (prioridad, motivo). Más chico = más específico y accionable. «Exige turco»
    # le sirve a el usuario; «no coincide la categoría» es una consecuencia.
    motivos_duros: list[tuple[int, str]] = []

    # --- filtro duro 1: categoría --------------------------------------
    if categoria is None:
        excluye = True
        motivos_duros.append((6, motivo_categoria))
        razones.append({"tipo": "categoria", "texto": motivo_categoria, "efecto": "excluye"})
    elif origen_categoria == "texto":
        decisivas.append(motivo_categoria)
        incertidumbres.append(motivo_categoria)
        razones.append({"tipo": "categoria", "texto": motivo_categoria, "efecto": "duda"})
    else:
        razones.append({"tipo": "categoria", "texto": f"{categoria}: {motivo_categoria}",
                        "efecto": "suma"})

    # --- filtro duro 2: territorio -------------------------------------
    if territorio == "excluye":
        excluye = True
        motivos_duros.append((3, motivo_territorio))
        razones.append({"tipo": "territorio", "texto": motivo_territorio, "efecto": "excluye"})
    elif territorio == "duda":
        incertidumbres.append(motivo_territorio)
        decisivas.append(motivo_territorio)
        razones.append({"tipo": "territorio", "texto": motivo_territorio, "efecto": "duda"})
    else:
        razones.append({"tipo": "territorio", "texto": motivo_territorio, "efecto": "suma"})

    # --- filtro duro 3: modalidad --------------------------------------
    veredicto_modalidad, motivo_modalidad = _modalidad_viable(modalidad, region, perfil)
    if veredicto_modalidad == "excluye":
        excluye = True
        motivos_duros.append((4, motivo_modalidad))
        razones.append({"tipo": "modalidad", "texto": motivo_modalidad, "efecto": "excluye"})
    elif veredicto_modalidad == "duda":
        incertidumbres.append(motivo_modalidad)
        decisivas.append(motivo_modalidad)
        razones.append({"tipo": "modalidad", "texto": motivo_modalidad, "efecto": "duda"})
    else:
        razones.append({"tipo": "modalidad", "texto": motivo_modalidad, "efecto": "suma"})

    # --- filtro duro 4: formación, seniority e idioma --------------------
    if formacion == "excluye":
        excluye = True
        motivos_duros.append((2, f"exige título terminado: {motivo_formacion}"))
        razones.append({"tipo": "formacion", "efecto": "excluye",
                        "texto": f"exige título terminado: {motivo_formacion}"})
    elif formacion == "duda":
        incertidumbres.append(f"formación: {motivo_formacion}")
        decisivas.append(f"formación: {motivo_formacion}")
        razones.append({"tipo": "formacion", "efecto": "duda",
                        "texto": f"formación preferida: {motivo_formacion}"})

    if experiencia == "excluye":
        excluye = True
        motivos_duros.append((5, motivo_experiencia))
        razones.append({"tipo": "seniority", "texto": motivo_experiencia, "efecto": "excluye"})
    elif experiencia == "duda":
        incertidumbres.append(motivo_experiencia)
        decisivas.append(motivo_experiencia)
        razones.append({"tipo": "seniority", "texto": motivo_experiencia, "efecto": "duda"})
    elif experiencia == "excepcion":
        razones.append({"tipo": "experiencia", "efecto": "salvedad",
                        "texto": f"excepción por competencias: {motivo_experiencia}"})
    elif experiencia == "desconocido":
        # No excluye: se puede postular igual. Pero no suma y queda a la vista.
        incertidumbres.append("el aviso no declara experiencia ni seniority")
        razones.append({"tipo": "seniority", "efecto": "duda",
                        "texto": "no se declara experiencia exigida: no se otorgan puntos"})

    if laboral == "excluye":
        excluye = True
        motivos_duros.append((2, motivo_laboral or "exige reubicación"))
        razones.append({"tipo": "viajes", "texto": motivo_laboral or "", "efecto": "excluye"})
    elif laboral == "duda":
        incertidumbres.append(motivo_laboral or "viajes sin precisar")
        decisivas.append(motivo_laboral or "viajes sin precisar")
        razones.append({"tipo": "viajes", "texto": motivo_laboral or "", "efecto": "duda"})

    if vigencia == "stale":
        mensaje = ("vigencia sin confirmar: el aviso se publicó hace más de "
                   f"{DIAS_VIGENCIA_RAZONABLE} días y no declara fecha de cierre")
        incertidumbres.append(mensaje)
        decisivas.append(mensaje)
        razones.append({"tipo": "vigencia", "texto": mensaje, "efecto": "duda"})

    if idioma == "incumplido":
        excluye = True
        motivos_duros.append((1, motivo_idioma))
        razones.append({"tipo": "idioma", "texto": motivo_idioma, "efecto": "excluye"})
    elif idioma == "parcial":
        incertidumbres.append(motivo_idioma)
        # Un requisito EXPLÍCITO de idioma incumplido nunca deja la oferta en
        # `eligible`: va a dudosas para revisión. El «aviso está en inglés»
        # genérico (bloquea=False) sigue siendo sólo incertidumbre.
        if analisis_idiomas.bloquea and motivo_idioma not in decisivas:
            decisivas.append(motivo_idioma)
        razones.append({"tipo": "idioma", "texto": motivo_idioma, "efecto": "duda"})
    elif idioma == "cumplido":
        razones.append({"tipo": "idioma", "texto": motivo_idioma, "efecto": "suma"})
    elif idioma == "contradictorio":
        # Ni cumplimiento confirmado ni descarte: se aparta para revisión humana.
        incertidumbres.append(motivo_idioma)
        decisivas.append(motivo_idioma)
        razones.append({"tipo": "idioma", "texto": motivo_idioma, "efecto": "duda"})
    elif idioma == "desconocido":
        # L01: un aviso corto o sin nivel declarado no se evalúa. Antes no
        # dejaba NINGÚN rastro y parecía que el idioma había dado por bueno el
        # aviso. No bloquea: se declara que no se evaluó.
        mensaje = ("idioma no evaluado: el aviso no declara nivel exigido y su "
                   "texto no alcanza para inferir el idioma")
        incertidumbres.append(mensaje)
        razones.append({"tipo": "idioma", "texto": mensaje, "efecto": "duda"})

    evaluacion = Evaluacion(
        razones=razones,
        incertidumbres=incertidumbres,
        decisivas=decisivas,
        categoria=categoria,
        origen_categoria=origen_categoria,
        vigencia=vigencia,
        modalidad=modalidad,
        excepcion=experiencia == "excepcion",
        anios_requeridos=anios,
        requisitos={
            "restriccion_territorial": restriccion,
            "alcance_territorial": alcance,
            "categoria_motivo": motivo_categoria,
            "origen_categoria": origen_categoria,
            "modalidad": modalidad,
            "vigencia": vigencia,
            "salario_comparable": _salario_comparable(oferta.get("salario")),
            "estado_experiencia": experiencia,
            "estado_formacion": formacion,
            "estado_idioma": idioma,
            "requisitos_idioma": analisis_idiomas.requisitos,
            "estado_laboral": laboral,
            "idioma_aviso": _idioma_del_aviso(texto),
            "tareas_en_el_texto": hay_tareas_de(categoria, texto),
            "categoria_fuente": oferta.get("categoria_fuente"),
            "categoria_corroborada": corroborada,
            "tipo_contrato": oferta.get("tipo_contrato"),
            "categorias_efectivas": categorias_efectivas(perfil.get("categorias")),
            "categorias_no_reconocidas": categorias_no_reconocidas(perfil.get("categorias")),
            "publicado_en": oferta.get("publicado_en"),
            "ultima_deteccion": oferta.get("ultima_deteccion"),
            "expira_en": oferta.get("expira_en"),
        },
    )

    if excluye:
        evaluacion.elegibilidad = "incompatible"
        evaluacion.motivo_elegibilidad = (min(motivos_duros)[1] if motivos_duros
                                          else "no elegible")
        evaluacion.compatibilidad = None
        evaluacion.confianza = "baja"
        return evaluacion

    # --- compatibilidad (sólo si no está descartada) --------------------
    componentes: list[Componente] = []

    # 1. Categoría y tareas (25). El título por sí solo no alcanza para el total.
    if origen_categoria == "titulo" and hay_tareas_de(categoria, texto):
        componentes.append(Componente("categoria_tareas", 25, 25, True, estado="cumplido",
                                      detalle=f"{categoria}: título y tareas coinciden"))
    elif origen_categoria == "titulo":
        componentes.append(Componente(
            "categoria_tareas", 25, 15, True, estado="parcial",
            detalle=f"{categoria}: el título coincide, el aviso no describe tareas"))
        incertidumbres.append("el aviso no describe tareas de la categoría")
    else:
        componentes.append(Componente(
            "categoria_tareas", 25, 10, True, estado="parcial",
            detalle=f"{categoria}: indicio en el cuerpo, sin confirmar en el título"))

    # 2. Habilidades (40), ponderadas por nivel y por amplitud de la evidencia.
    if not aplicables and not faltantes:
        if informativas:
            # C06: el aviso pide habilidades de un puesto que el perfil no cubre.
            # No es «no hay datos»: hay datos y dicen que falta. Se puntúa 0 y se
            # deja constancia, sin descontar dos veces lo mismo.
            nombres = ", ".join(sorted({i["skill"] for i in informativas}))
            componentes.append(Componente(
                "habilidades", 40, 0, True, estado="parcial",
                detalle=f"el aviso pide habilidades que el perfil no declara: {nombres}"))
            incertidumbres.append(
                "el aviso pide habilidades que el perfil no declara: " + nombres)
            decisivas.append(
                "el perfil no declara ninguna de las habilidades que pide el aviso")
        else:
            componentes.append(Componente("habilidades", 40, 0, aplicable=True,
                                          estado="sin_datos",
                                          detalle="el aviso no enumera habilidades reconocibles"))
            incertidumbres.append("el aviso no enumera habilidades: no se puede puntuar")
            decisivas.append("sin habilidades declaradas: información insuficiente")
    else:
        distintas = len({i["skill"] for i in aplicables + faltantes})
        # Una sola habilidad mencionada es un dato suelto, no una medición.
        amplitud = min(1.0, distintas / 3)
        obtenido = 40 * cobertura_competencias * amplitud
        detalle = (f"{peso_cumplido:.1f}/{peso_total:.0f} de peso cumplido "
                   f"({distintas} habilidad(es) distinta(s))")
        if faltantes:
            detalle += "; faltan: " + ", ".join(sorted({i["skill"] for i in faltantes}))
        estado_skills = "cumplido" if obtenido >= 39.5 else "parcial"
        componentes.append(Componente("habilidades", 40, obtenido, True,
                                      estado=estado_skills, detalle=detalle))
        if distintas < 3:
            incertidumbres.append(
                f"el aviso menciona {distintas} habilidad(es): cobertura poco representativa")


    # 3. Experiencia (20).
    if experiencia == "excepcion":
        componentes.append(Componente("experiencia", 20, 12, True, estado="parcial",
                                      detalle=f"excepción por competencias ({anios} años pedidos)"))
    elif experiencia == "cumplido":
        componentes.append(Componente("experiencia", 20, 20, True, estado="cumplido",
                                      detalle=motivo_experiencia or "nivel declarado y acorde"))
    else:
        componentes.append(Componente("experiencia", 20, 0, True, estado="sin_datos",
                                      detalle="no se declara experiencia ni seniority"))

    # 4. Idioma (8).
    maximo_idioma = 8
    if idioma == "no_aplicable":
        componentes.append(Componente("idioma", maximo_idioma, 0, False,
                                      estado="no_aplicable", detalle=motivo_idioma))
    elif idioma == "cumplido":
        componentes.append(Componente("idioma", maximo_idioma, 8, True,
                                      estado="cumplido", detalle=motivo_idioma))
    elif idioma == "parcial":
        componentes.append(Componente("idioma", maximo_idioma, puntos_idioma, True,
                                      estado="parcial", detalle=motivo_idioma))
    elif idioma == "contradictorio":
        componentes.append(Componente("idioma", maximo_idioma, 0, True,
                                      estado="sin_datos", detalle=motivo_idioma))
    else:
        componentes.append(Componente("idioma", maximo_idioma, 0, True,
                                      estado="sin_datos", detalle=motivo_idioma))

    # 5. Formación (7).
    if formacion == "ok":
        componentes.append(Componente("formacion", 7, 7, True, estado="cumplido",
                                      detalle="formación exigida y cumplida"))
    elif formacion == "duda":
        componentes.append(Componente("formacion", 7, 0, True, estado="parcial",
                                      detalle=f"formación preferida: {motivo_formacion}"))
    else:
        componentes.append(Componente("formacion", 7, 0, True, estado="sin_datos",
                                      detalle="el aviso no declara formación exigida"))

    no_aplicable = sum(c.maximo for c in componentes if not c.aplicable)
    base = 100 - no_aplicable
    obtenido_total = sum(c.obtenido for c in componentes if c.aplicable)
    con_datos = sum(c.maximo for c in componentes
                    if c.aplicable and c.estado not in {"sin_datos"})
    observados = sum(1 for c in componentes
                     if c.aplicable and c.estado not in {"sin_datos"})
    hay_habilidades = any(c.nombre == "habilidades" and c.estado != "sin_datos"
                          for c in componentes)

    evaluacion.componentes = componentes
    evaluacion.cobertura = round(con_datos / base, 2) if base else 0.0
    # S01/S02: el puntaje se mantiene sobre TODO el peso aplicable. Normalizar
    # sobre lo observado fue la tentación obvia para destrabar el techo de 73,
    # pero infla cualquier coincidencia parcial (un aviso que cubre 13/40 de
    # habilidades pasaba de 42 a 54) y vuelve a premiar la ausencia de datos.
    # El desajuste de escala se corrige en el UMBRAL de alerta, que es donde
    # estaba el error, y no en la fórmula.
    if not base or not hay_habilidades:
        evaluacion.compatibilidad = None
        evaluacion.escala = "sin_datos"
    else:
        evaluacion.compatibilidad = round(100 * obtenido_total / base, 1)
        evaluacion.escala = "aplicable"
    evaluacion.provisional = any(c.estado in {"provisional", "sin_datos"} or not c.aplicable
                                 for c in componentes)
    evaluacion.requisitos.update({
        "skills_aplicables": aplicables,
        "skills_faltantes": faltantes,
        "skills_informativas": informativas,
        "excepcion_experiencia": experiencia == "excepcion",
        "anios_requeridos": anios,
        "cobertura_competencias": round(cobertura_competencias, 2),
        "escala_puntaje": evaluacion.escala,
        "componentes_observados": observados,
    })

    if evaluacion.cobertura < COBERTURA_MINIMA_DUDA:
        mensaje = (f"cobertura de requisitos baja "
                   f"({int(evaluacion.cobertura * 100)}% de los pesos aplicables)")
        if mensaje not in evaluacion.incertidumbres:
            evaluacion.incertidumbres.append(mensaje)
            evaluacion.decisivas.append(mensaje)
            evaluacion.razones.append({"tipo": "cobertura", "texto": mensaje, "efecto": "duda"})

    evaluacion.confianza = _confianza(componentes, vigencia, origen_categoria, modalidad,
                                      oferta.get("publicado_en"), evaluacion.cobertura)

    if evaluacion.decisivas:
        evaluacion.elegibilidad = "doubtful"
        evaluacion.motivo_elegibilidad = evaluacion.decisivas[0]
    else:
        evaluacion.elegibilidad = "eligible"
        evaluacion.motivo_elegibilidad = "remoto, territorio compatible y seniority acorde"
    return evaluacion


def clave_orden(analisis: dict, oferta: dict) -> tuple:
    """Orden: elegibilidad, compatibilidad, confianza, vigencia, modalidad, frescura.

    La elegibilidad va primero a propósito: un 95 % temático en un puesto
    presencial en Berlín no puede quedar arriba de un 70 % remoto y postulable.
    """
    from .textutil import dias_desde

    elegibilidad = analisis.get("elegibilidad") or "doubtful"
    tramo_elegibilidad = {"eligible": 0, "doubtful": 1, "incompatible": 2}.get(elegibilidad, 1)
    confianza = analisis.get("confianza") or "baja"
    tramo_confianza = {"alta": 0, "media": 1, "baja": 2}.get(confianza, 2)
    compatibilidad = analisis.get("compatibilidad")
    if compatibilidad is None:
        compatibilidad = analisis.get("score")
    vigencia = analisis.get("vigencia") or oferta.get("estado_vigencia") or "unknown"
    tramo_vigencia = {"open": 0, "stale": 1, "unknown": 2, "closed": 3}.get(vigencia, 2)
    dias = dias_desde(oferta.get("publicado_en"))
    tramo_dias = 0 if dias is None else (0 if dias <= 7 else 1 if dias <= 14 else 2 if dias <= 30 else 3)
    modalidad = analisis.get("modalidad") or oferta.get("modalidad") or "unknown"
    tramo_modalidad = {"remote": 0, "hybrid": 1, "onsite": 2}.get(modalidad, 1)
    salario = oferta.get("salario") or {}
    comparable = 0 if (salario.get("moneda") and salario.get("periodo")
                       and salario.get("periodo") != "desconocido") else 1
    excepcion = 0 if analisis.get("excepcion") else 1
    return (
        tramo_elegibilidad,
        -(compatibilidad if compatibilidad is not None else -1),
        tramo_confianza,
        tramo_vigencia,
        tramo_modalidad,
        tramo_dias,
        comparable,
        excepcion,
        oferta.get("id") or "",
    )
