"""Elegibilidad, compatibilidad y confianza por reglas (rules-2.0.0).

Tres dimensiones **separadas**, porque mezclarlas es lo que producía los errores
que reportó el usuario:

1. **Elegibilidad** (`eligible` / `doubtful` / `incompatible`): ¿puede postularse
   desde Argentina, en su modalidad, con su seniority? Es un filtro duro.
2. **Compatibilidad** (`compatibilidad`, 0–100): qué tan cerca está el puesto de
   su perfil profesional. Puede ser alta en un puesto no elegible; nunca se
   muestra sin la elegibilidad al lado.
3. **Confianza** (`alta` / `media` / `baja`): cuánta información real hay. Un
   aviso sin habilidades, sin fecha o con modalidad desconocida no puede
   sentirse seguro aunque el título encaje.

Correcciones respecto de rules-1.1.0:

- La modalidad remota es requisito, no preferencia: presencial fuera de La Plata
  es incompatible aunque el título sea perfecto.
- Una categoría detectada sólo en el cuerpo no alcanza para ser elegible y nunca
  habilita un puntaje alto; el título manda.
- Títulos de ingeniería, desarrollo o diseño no caen en «VA/Data Entry» por una
  mención suelta de «data entry» en el texto.
- «Manager», «supervisor» y «jefe» en el título impiden tratarlo como junior.
- Sin habilidades detectadas no hay puntaje: se informa «información
  insuficiente» en lugar de 100/100.
- Un aviso de hace más de 45 días sin fecha de cierre no se declara «abierto».
- La restricción territorial se busca también en el título, no sólo en la región.
- Un salario sin moneda o sin período se marca como no comparable.
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
     ()),  # sin pistas de cuerpo: «data entry» suelto no alcanza
    ("Customer Support", ("customer support", "customer success", "client success",
                          "technical support", "support specialist", "help desk",
                          "atencion al cliente", "soporte tecnico", "customer happiness"),
     ("customer support", "atencion al cliente")),
]

_TITULO_FUERA_DE_PERFIL = re.compile(
    r"\b(engineer|engineering|developer|programmer|architect|designer|scientist|"
    r"accountant|bookkeeper|nurse|physician|lawyer|paralegal|driver|warehouse|"
    r"electrician|plumber|mechanic|teacher|professor|cook|chef|waiter|cleaner|"
    r"recruiter|talent acquisition|seo|copywriter|graphic)\b"
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
    r"\b(senior|sr|lead|principal|staff|head of|head|director|vp|vice president|chief|cto|ceo)\b"
)
_SENIORITY_DUDA = re.compile(r"\b(manager|supervisor|jefe|jefa|coordinador|coordinadora|"
                             r"mid level|midlevel|intermediate|semi senior|ssr)\b")

_SKILLS = [
    "sql", "python", "excel", "power bi", "tableau", "looker", "postgresql",
    "mysql", "sql server", "bigquery", "snowflake", "airflow", "dbt", "etl",
    "pandas", "numpy", "r", "statistics", "estadistica", "google sheets",
    "apps script", "git", "docker", "api", "jira", "salesforce", "hubspot",
    "data visualization", "visualizacion de datos", "power query", "vba",
    "looker studio", "metabase", "qlik", "spss", "stata", "nosql", "mongodb",
]

_REQUISITO_FUERTE = re.compile(
    r"\b(required|requirement|must have|must be|minimum|obligatorio|excluyente|indispensable)\b"
)
_ANIOS = re.compile(r"(\d{1,2})\s*\+?\s*(?:years|yrs|años|anos)")

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
]
# Indicadores de EE. UU. que no aparecen como frase completa en las regiones:
# «Your Remote US Home Office», «US-Remote», «U.S. only». Se buscan como palabra.
# `normalizar` borra los puntos, así que «U.S.» llega como «u s».
_EEUU = re.compile(r"\b(u s|us|usa|united states|estados unidos)\b")
# Ciudades y estados de EE. UU. que aparecen sin el nombre del país.
_ESTADOS_EEUU = ("al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
                 "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
                 "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
                 "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
                 "wi", "wy")
_CIUDADES_EEUU = ("san francisco", "new york", "seattle", "austin", "boston", "chicago",
                  "denver", "atlanta", "los angeles", "san diego", "miami", "dallas",
                  "houston", "philadelphia", "phoenix", "portland", "minneapolis",
                  "washington dc", "silicon valley", "bay area", "new jersey")
_PERMITIDOS = [
    "anywhere", "worldwide", "world wide", "global", "latam", "latin america",
    "south america", "americas", "argentina", "remote worldwide", "any location",
    "international", "fully remote", "100% remote",
]
_REMOTO = ("remote", "remoto", "teletrabajo", "work from home", "home office",
           "anywhere", "distributed", "remote-first")
_HIBRIDO = ("hybrid", "hibrido", "híbrido", "partially remote", "parcialmente remoto")


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


def categoria_de(titulo: str, texto: str) -> tuple[str | None, str, str]:
    """Devuelve (categoría, motivo, origen).

    Origen `titulo` es la única vía para una categoría plena. `texto` es indicio:
    sirve para revisar a mano, no para puntuar alto.
    """
    en_titulo = normalizar(titulo)
    for categoria, pistas_titulo, _ in _PISTAS:
        for pista in pistas_titulo:
            if re.search(rf"\b{re.escape(pista)}\b", en_titulo):
                return categoria, f"coincidencia en el título con '{pista}'", "titulo"

    if _TITULO_FUERA_DE_PERFIL.search(en_titulo):
        return None, "el título corresponde a un rol fuera de las categorías del perfil", "ninguno"

    if not _TITULO_AFIN.search(en_titulo):
        return None, "el título no es afín a las categorías del perfil", "ninguno"

    en_texto = normalizar(texto[:1500])
    for categoria, _, pistas_cuerpo in _PISTAS:
        for pista in pistas_cuerpo:
            if re.search(rf"\b{re.escape(pista)}\b", en_texto):
                return (categoria,
                        f"indicio en el cuerpo con '{pista}' (sin confirmar en el título)",
                        "texto")
    return None, "sin coincidencia con las diez categorías del perfil", "ninguno"


def _territorio(region: str | None, titulo: str, texto: str) -> tuple[str, str, str]:
    """Devuelve (estado, motivo, restricción). Mira región, título y cuerpo."""
    campo = normalizar(region)
    en_titulo = normalizar(titulo)

    if campo:
        if any(p in campo for p in _PERMITIDOS):
            # «Anywhere» en el campo no borra un país escrito en el título:
            # "(Remote - Canada)" es más específico que "Anywhere in the World".
            en_conflicto = next((p for p in _PAISES_NO_AR if p in en_titulo), None)
            if en_conflicto:
                return ("excluye",
                        f"el título restringe el puesto a {en_conflicto} aunque la fuente "
                        f"declare «{region}»", en_conflicto)
            return "ok", f"la fuente declara alcance compatible: {region}", region or ""
        detectado = next((p for p in _PAISES_NO_AR if p in campo), None)
        if detectado:
            return "excluye", f"la fuente restringe la ubicación a {region}", region or ""
        if _EEUU.search(campo):
            return "excluye", f"la región declarada apunta a Estados Unidos: {region}", region or ""
        # «San Francisco, CA» o «Austin, TX» sin decir «United States».
        sin_parentesis = re.sub(r"\([^)]*\)", " ", campo).strip(" ,")
        ultimo = sin_parentesis.rsplit(",", 1)[-1].strip()
        if ultimo in _ESTADOS_EEUU:
            return "excluye", f"la región es un estado de EE. UU.: {region}", region or ""
        if any(ciudad in campo for ciudad in _CIUDADES_EEUU):
            return "excluye", f"la región es una ciudad de EE. UU.: {region}", region or ""
        return "duda", f"región declarada no concluyente: {region}", region or ""

    detectado_titulo = next((p for p in _PAISES_NO_AR if p in en_titulo), None)
    if detectado_titulo:
        return "excluye", f"el título restringe el puesto a {detectado_titulo}", detectado_titulo

    cuerpo = normalizar(texto[:6000])
    for patron in (
        r"must be (located|based) in the (united states|us|usa|uk|canada|europe)",
        r"only (candidates|applicants) (located|based) in",
        r"us residents only",
        r"authorized to work in the (united states|us)",
        r"no visa sponsorship",
    ):
        if re.search(patron, cuerpo):
            return "duda", "el texto menciona una restricción territorial sin campo estructurado", ""

    if any(p in cuerpo for p in ("remote worldwide", "work from anywhere", "anywhere in the world")):
        return "ok", "el texto declara alcance mundial", "worldwide"

    return "duda", "la fuente no publica el territorio admitido", ""


def _modalidad(region: str | None, titulo: str, texto: str, contrato: str | None = None) -> str:
    base = normalizar(f"{region or ''} {titulo or ''} {contrato or ''}")
    if any(p in base for p in _REMOTO):
        return "remote"
    if any(p in base for p in _HIBRIDO):
        return "hybrid"
    cuerpo = normalizar(texto[:4000])
    if "fully remote" in cuerpo or "100% remote" in cuerpo or "remote position" in cuerpo:
        return "remote"
    if any(p in cuerpo for p in _HIBRIDO):
        return "hybrid"
    if region:
        return "onsite"
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


def _formacion(texto: str) -> tuple[str, str | None]:
    base = normalizar(texto)
    fuerte = [
        "bachelor s degree required", "bachelors degree required", "degree is required",
        "degree required", "must have a bachelor", "titulo universitario excluyente",
        "titulo de grado obligatorio", "university degree required",
    ]
    debil = ["bachelor s degree preferred", "degree preferred", "titulo deseable"]
    for patron in fuerte:
        if patron in base:
            return "excluye", patron
    for patron in debil:
        if patron in base:
            return "duda", patron
    return "ok", None


def anios_requeridos(texto: str) -> int | None:
    encontrados = [int(a) for a in _ANIOS.findall(normalizar(texto)[:6000])]
    validos = [a for a in encontrados if 0 < a <= 20]
    return min(validos) if validos else None


def _experiencia(titulo: str, texto: str, declarado: str | None,
                 cobertura_competencias: float) -> tuple[str, str, int | None]:
    base = normalizar(f"{titulo} {declarado or ''}")
    if _SENIORITY_EXCLUYE.search(base):
        return "excluye", f"el título declara un nivel superior al perfil: {titulo}", None
    if _SENIORITY_DUDA.search(base):
        return "duda", f"el título implica responsabilidad de gestión: {titulo}", None

    anios = anios_requeridos(texto)
    if anios is None:
        return "ok", "", None
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
    return "ok", "", anios


def _idioma(texto: str, perfil_nivel: str) -> tuple[str, str | None]:
    base = normalizar(texto)
    if re.search(r"\b(native|fluent|bilingual)\s+(in\s+)?english\b", base):
        return "duda", "exige inglés fluido o nativo"
    if re.search(r"\b(c1|c2)\b.{0,20}\benglish\b|\benglish\b.{0,20}\b(c1|c2)\b", base):
        return "duda", "exige inglés C1/C2"
    return "ok", None


def _skills_requeridas(texto: str, habilidades: dict[str, float]) -> tuple[list[dict], list[dict]]:
    """Cruza las habilidades pedidas con el perfil, ponderadas por nivel."""
    plano = normalizar(texto)
    aplicables: list[dict] = []
    faltantes: list[dict] = []
    for skill in _SKILLS:
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
        else:
            item["peso_cumplido"] = 0.0
            faltantes.append(item)
    return aplicables, faltantes


def _vigencia(expira_en: str | None, publicado_en: str | None,
              ahora: datetime | None = None) -> str:
    """`closed`, `open` o `unknown`. Un aviso viejo sin cierre NO es `open`."""
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
    return "open" if (ahora - publicado).days <= DIAS_VIGENCIA_RAZONABLE else "unknown"


def _salario_comparable(salario: dict | None) -> bool:
    if not salario:
        return False
    periodo = (salario.get("periodo") or "").lower()
    return bool(salario.get("moneda")) and bool(periodo) and periodo != "desconocido"


def _confianza(componentes: list[Componente], vigencia: str, origen_categoria: str,
               modalidad: str, publicado_en: str | None) -> str:
    faltantes = 0
    if not any(c.nombre == "habilidades" and c.aplicable for c in componentes):
        faltantes += 1
    if modalidad == "unknown":
        faltantes += 1
    if not publicado_en:
        faltantes += 1
    if vigencia == "unknown":
        faltantes += 1
    if origen_categoria == "texto":
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

    categoria, motivo_categoria, origen_categoria = categoria_de(titulo, texto)
    territorio, motivo_territorio, restriccion = _territorio(region, titulo, texto)
    formacion, motivo_formacion = _formacion(texto)
    modalidad = _modalidad(region, titulo, texto, oferta.get("tipo_contrato"))
    vigencia = _vigencia(oferta.get("expira_en"), oferta.get("publicado_en"))

    aplicables, faltantes = _skills_requeridas(texto, habilidades)
    peso_total = sum(i["peso"] for i in aplicables + faltantes)
    peso_cumplido = sum(i["peso_cumplido"] for i in aplicables)
    cobertura_competencias = (peso_cumplido / peso_total) if peso_total else 0.0

    experiencia, motivo_experiencia, anios = _experiencia(
        titulo, texto, oferta.get("seniority"), cobertura_competencias)
    idioma, motivo_idioma = _idioma(texto, perfil.get("idioma", {}).get("ingles", "desconocido"))

    razones: list[dict[str, Any]] = []
    incertidumbres: list[str] = []
    decisivas: list[str] = []
    excluye = False
    motivos_duros: list[str] = []

    # --- filtro duro 1: categoría --------------------------------------
    if categoria is None:
        excluye = True
        motivos_duros.append(motivo_categoria)
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
        motivos_duros.append(motivo_territorio)
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
        motivos_duros.append(motivo_modalidad)
        razones.append({"tipo": "modalidad", "texto": motivo_modalidad, "efecto": "excluye"})
    elif veredicto_modalidad == "duda":
        incertidumbres.append(motivo_modalidad)
        decisivas.append(motivo_modalidad)
        razones.append({"tipo": "modalidad", "texto": motivo_modalidad, "efecto": "duda"})
    else:
        razones.append({"tipo": "modalidad", "texto": motivo_modalidad, "efecto": "suma"})

    # --- filtro duro 4: formación y seniority ---------------------------
    if formacion == "excluye":
        excluye = True
        motivos_duros.append(f"exige título terminado: {motivo_formacion}")
        razones.append({"tipo": "formacion", "efecto": "excluye",
                        "texto": f"exige título terminado: {motivo_formacion}"})
    elif formacion == "duda":
        incertidumbres.append(f"formación: {motivo_formacion}")
        decisivas.append(f"formación: {motivo_formacion}")
        razones.append({"tipo": "formacion", "efecto": "duda",
                        "texto": f"formación preferida: {motivo_formacion}"})

    if experiencia == "excluye":
        excluye = True
        motivos_duros.append(motivo_experiencia)
        razones.append({"tipo": "seniority", "texto": motivo_experiencia, "efecto": "excluye"})
    elif experiencia == "duda":
        incertidumbres.append(motivo_experiencia)
        decisivas.append(motivo_experiencia)
        razones.append({"tipo": "seniority", "texto": motivo_experiencia, "efecto": "duda"})
    elif experiencia == "excepcion":
        razones.append({"tipo": "experiencia", "efecto": "salvedad",
                        "texto": f"excepción por competencias: {motivo_experiencia}"})

    if idioma == "duda":
        incertidumbres.append(motivo_idioma or "exigencia de idioma ambigua")
        decisivas.append(motivo_idioma or "exigencia de idioma ambigua")
        razones.append({"tipo": "idioma", "texto": motivo_idioma or "", "efecto": "duda"})

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
            "categoria_motivo": motivo_categoria,
            "origen_categoria": origen_categoria,
            "modalidad": modalidad,
            "vigencia": vigencia,
            "salario_comparable": _salario_comparable(oferta.get("salario")),
        },
    )

    if excluye:
        evaluacion.elegibilidad = "incompatible"
        evaluacion.motivo_elegibilidad = motivos_duros[0] if motivos_duros else "no elegible"
        evaluacion.compatibilidad = None
        evaluacion.confianza = "baja"
        return evaluacion

    # --- compatibilidad (sólo si no está descartada) --------------------
    componentes: list[Componente] = []

    puntos_categoria = 25 if origen_categoria == "titulo" else 10
    componentes.append(Componente("categoria_tareas", 25, puntos_categoria, True,
                                  detalle=motivo_categoria))

    if not aplicables and not faltantes:
        # Sin habilidades declaradas no hay puntaje: inventarlo era el 100/100.
        componentes.append(Componente("habilidades", 40, 0, aplicable=False, estado="sin_datos",
                                      detalle="el aviso no enumera habilidades reconocibles"))
        incertidumbres.append("el aviso no enumera habilidades: no se puede puntuar")
        decisivas.append("sin habilidades declaradas: información insuficiente")
    else:
        obtenido = 40 * cobertura_competencias
        detalle = f"{peso_cumplido:.1f}/{peso_total:.0f} de peso cumplido (ponderado por nivel)"
        if faltantes:
            detalle += "; faltan: " + ", ".join(sorted({i["skill"] for i in faltantes}))
        componentes.append(Componente("habilidades", 40, obtenido, True, detalle=detalle))

    if experiencia == "excepcion":
        componentes.append(Componente("experiencia", 20, 12, True,
                                      detalle=f"excepción por competencias ({anios} años pedidos)"))
    elif oferta.get("seniority") or experiencia == "ok":
        componentes.append(Componente("experiencia", 20, 20, True,
                                      detalle="sin contradicción con el perfil"))
    else:
        componentes.append(Componente("experiencia", 20, 0, False, estado="provisional",
                                      detalle="no se declara seniority"))
        incertidumbres.append("seniority no declarado")

    puntos = (8 if idioma == "ok" else 0) + (7 if formacion == "ok" else 0)
    componentes.append(Componente("idioma_formacion", 15, puntos, True,
                                  detalle="inglés y formación sin exigencia incompatible"))

    aplicables_max = sum(c.maximo for c in componentes if c.aplicable)
    obtenido_total = sum(c.obtenido for c in componentes if c.aplicable)
    hay_habilidades = any(c.nombre == "habilidades" and c.aplicable for c in componentes)

    evaluacion.componentes = componentes
    evaluacion.compatibilidad = (round(100 * obtenido_total / aplicables_max, 1)
                                 if aplicables_max and hay_habilidades else None)
    evaluacion.cobertura = round(aplicables_max / 100, 2)
    evaluacion.provisional = any(c.estado in {"provisional", "sin_datos"} or not c.aplicable
                                 for c in componentes)
    evaluacion.requisitos.update({
        "skills_aplicables": aplicables,
        "skills_faltantes": faltantes,
        "excepcion_experiencia": experiencia == "excepcion",
        "anios_requeridos": anios,
        "cobertura_competencias": round(cobertura_competencias, 2),
    })

    if evaluacion.cobertura < 0.7:
        mensaje = (f"cobertura de requisitos baja "
                   f"({int(evaluacion.cobertura * 100)}% de los pesos aplicables)")
        if mensaje not in evaluacion.incertidumbres:
            evaluacion.incertidumbres.append(mensaje)
            evaluacion.decisivas.append(mensaje)
            evaluacion.razones.append({"tipo": "cobertura", "texto": mensaje, "efecto": "duda"})

    evaluacion.confianza = _confianza(componentes, vigencia, origen_categoria, modalidad,
                                      oferta.get("publicado_en"))

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
    tramo_vigencia = {"open": 0, "unknown": 1, "closed": 2}.get(vigencia, 1)
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
