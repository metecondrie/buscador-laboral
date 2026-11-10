"""Corpus adversarial de la Fase 1C (independiente de la implementación).

Sólo datos: cada caso describe QUÉ debe pasar, no cómo se programa. Lo consumen
la sonda aislada (`sonda.py`) y la suite de regresión del repositorio.
Sin red, sin SQLite, sin perfil operativo.
"""
from __future__ import annotations

BASE = {
    "titulo": "Junior Data Analyst",
    "texto": "SQL required. Excel required. Python required. Remote.",
    "region": "Worldwide",
    "seniority": None,
    "salario": None,
    "publicado_en": "2026-11-01T00:00:00Z",
    "expira_en": None,
}

SQL = "SQL required. Excel required. Python required."
REMOTE = "Remote."


def t(frase: str, *, titulo: str = "Junior Data Analyst", region: str = "Worldwide",
      texto_extra: str = "") -> dict:
    """Aviso completo y REALISTA: siempre con evidencia remota y de habilidades."""
    return {"titulo": titulo, "region": region,
            "texto": f"{frase} {SQL} {REMOTE} {texto_extra}".strip()}


# (id, grupo, cambios sobre BASE, comprobaciones)
# Operadores: valor exacto, "!valor" (distinto), ">n", "<n", None.
CASOS: list[tuple[str, str, dict, dict]] = [
    # --- TERRITORIO --------------------------------------------------------
    ("T01", "territorio", {"region": "Cordoba, Spain"},
     {"elegibilidad": "incompatible", "alcance": "restringido"}),
    ("T02", "territorio", {"region": "La Plata, Maryland, USA"},
     {"elegibilidad": "incompatible", "alcance": "restringido"}),
    ("T03", "territorio", {"region": "Rosario, Philippines"},
     {"elegibilidad": "incompatible", "alcance": "restringido"}),
    ("T04", "territorio", {"region": "Ambato, Ecuador"},
     {"elegibilidad": "incompatible", "alcance": "restringido"}),
    ("T05", "territorio", t("Must be a US citizen.", region="Argentina"),
     {"elegibilidad": "incompatible", "alcance": "restringido"}),
    ("T06", "territorio", t("Must live in the US."),
     {"elegibilidad": "incompatible", "alcance": "restringido"}),
    ("T07", "territorio", t("Must currently reside in Canada."),
     {"elegibilidad": "incompatible", "alcance": "restringido"}),
    ("T08", "territorio", t("", titulo="US Only Data Analyst"),
     {"elegibilidad": "incompatible", "alcance": "restringido"}),
    ("T09", "territorio", t("", region="Anywhere in Canada"),
     {"elegibilidad": "incompatible", "alcance": "restringido"}),
    ("T10", "territorio", t("US only."),
     {"elegibilidad": "incompatible", "alcance": "restringido"}),
    ("T11", "territorio", t("This is not a US-only position."),
     {"elegibilidad": "!incompatible", "alcance": "!restringido"}),
    ("T12", "territorio", t("ART time zone only."),
     {"elegibilidad": "!incompatible", "alcance": "!restringido"}),
    ("T13", "territorio", t("Availability to work 9:00 a.m. to 6:00 p.m. ART time zone."),
     {"elegibilidad": "!incompatible", "alcance": "!restringido"}),
    ("T14", "territorio", t("We prefer candidates in EST time zone."),
     {"elegibilidad": "!incompatible", "alcance": "!restringido"}),
    ("T15", "territorio", t("We serve customers in the US, Canada and Europe."),
     {"elegibilidad": "!incompatible", "alcance": "!restringido"}),
    ("T16", "territorio", t("This is a US-only position."),
     {"elegibilidad": "incompatible", "alcance": "restringido"}),
    ("T17", "territorio", t("Not a US-only position."),
     {"elegibilidad": "!incompatible", "alcance": "!restringido"}),

    # --- MODALIDAD ---------------------------------------------------------
    ("M01", "modalidad", {"texto": "Remote team. Onsite role. " + SQL},
     {"elegibilidad": "!eligible", "modalidad": ["!remote", "!unknown"]}),
    ("M02", "modalidad", {"texto": "Remote work is not permitted. " + SQL},
     {"elegibilidad": "!eligible", "modalidad": "!remote"}),
    ("M03", "modalidad", {"texto": "This role is onsite 3 days a week. " + SQL},
     {"elegibilidad": "!eligible", "modalidad": ["!unknown", "!remote"]}),
    ("M04", "modalidad", {"texto": "Onsite gym available. " + SQL + " " + REMOTE},
     {"modalidad": "!onsite", "elegibilidad": "!incompatible"}),
    ("M05", "modalidad", {"texto": "No onsite requirement. " + SQL + " " + REMOTE},
     {"modalidad": "!onsite", "elegibilidad": "!incompatible"}),
    ("M06", "modalidad", {"texto": "On-site interview required. " + SQL + " " + REMOTE},
     {"modalidad": "!onsite", "elegibilidad": "!incompatible"}),
    ("M07", "modalidad", {"titulo": "Hybrid Cloud Data Analyst",
                          "texto": SQL + " " + REMOTE},
     {"modalidad": "!hybrid", "elegibilidad": "!incompatible"}),
    ("M08", "modalidad", {"texto": "Remote team. Fully remote position. " + SQL},
     {"modalidad": "remote", "elegibilidad": "!incompatible"}),

    # --- IDIOMAS -----------------------------------------------------------
    ("L01", "idiomas", t("French required and no degree needed."),
     {"elegibilidad": "incompatible", "motivo_incluye": "french"}),
    ("L02", "idiomas", t("French required and being organized is a plus."),
     {"elegibilidad": "incompatible", "motivo_incluye": "french"}),
    ("L03", "idiomas", t("French required (no exceptions)."),
     {"elegibilidad": "incompatible", "motivo_incluye": "french"}),
    ("L04", "idiomas", t("Spanish required. English C1 required."),
     {"elegibilidad": "!eligible", "estado_idioma": "!cumplido"}),
    ("L05", "idiomas", t("English C2 required."),
     {"elegibilidad": "!eligible", "estado_idioma": "!cumplido", "texto_incluye": "b1"}),
    ("L06", "idiomas", t("French required and German is a plus."),
     {"elegibilidad": "incompatible", "motivo_incluye": "french"}),
    ("L07", "idiomas", t("Spanish not required. French required."),
     {"elegibilidad": "incompatible", "motivo_incluye": "french"}),
    ("L08", "idiomas", t("Se requiere frances."),
     {"elegibilidad": "incompatible", "motivo_incluye": "french"}),
    ("L09", "idiomas", t("Francophone required."),
     {"elegibilidad": "incompatible", "motivo_incluye": "french"}),
    ("L10", "idiomas", t("French-speaking candidates required."),
     {"elegibilidad": "incompatible", "motivo_incluye": "french"}),
    ("L11", "idiomas", t("French is optional. German mandatory."),
     {"elegibilidad": "incompatible", "motivo_incluye": "german"}),
    ("L12", "idiomas", t("No degree needed. French required."),
     {"elegibilidad": "incompatible", "motivo_incluye": "french"}),
    ("L13", "idiomas", t("French is a plus. German desirable."),
     {"elegibilidad": "!incompatible", "estado_idioma": "!incumplido"}),
    ("L14", "idiomas", t("English B1 required. Spanish required."),
     {"elegibilidad": "!incompatible", "estado_idioma": "cumplido"}),

    # --- EXPERIENCIA / FORMACIÓN / REUBICACIÓN -----------------------------
    ("E01", "experiencia", t("10+ years required. 1 year of Python."),
     {"elegibilidad": "incompatible", "anios_requeridos": 10}),
    ("E02", "experiencia", t("Must be 18 years or older."),
     {"elegibilidad": "!incompatible", "anios_requeridos": None}),
    ("E03", "experiencia", {"titulo": "Data Analyst - Lead Generation",
                            "texto": SQL + " " + REMOTE},
     {"elegibilidad": "!incompatible", "motivo_no_incluye": "nivel superior"}),
    ("E04", "experiencia", t("Senior level required."),
     {"elegibilidad": "!eligible"}),
    ("E05", "formacion", t("Bachelor's degree in Statistics required."),
     {"elegibilidad": "incompatible", "estado_formacion": "excluye"}),
    ("E06", "formacion", t("Titulo en Estadistica excluyente."),
     {"elegibilidad": "incompatible", "estado_formacion": "excluye"}),
    ("E07", "reubicacion", t("Relocation to Berlin is required."),
     {"elegibilidad": "incompatible", "estado_laboral": "excluye"}),
    ("E08", "experiencia", t("Our company has 15 years of history. 1 year of experience required."),
     {"elegibilidad": "!incompatible", "anios_requeridos": 1}),
]


def fallos(e, checks: dict) -> list[str]:
    """Devuelve las comprobaciones no cumplidas por una evaluación."""
    problemas: list[str] = []
    for clave, crudo in checks.items():
        for esperado in (crudo if isinstance(crudo, list) else [crudo]):
            problemas.extend(_un_fallo(e, clave, esperado))
    return problemas


def _un_fallo(e, clave: str, esperado) -> list[str]:
    problemas: list[str] = []
    if clave == "alcance":
        real = e.requisitos.get("alcance_territorial")
    elif clave in {"estado_idioma", "estado_formacion", "estado_laboral"}:
        real = e.requisitos.get(clave)
    elif clave == "motivo_incluye":
        real = e.motivo_elegibilidad.lower() + " " + " ".join(e.razones_texto()).lower()
        if esperado not in real:
            problemas.append(f"motivo no incluye {esperado!r}: {e.motivo_elegibilidad!r}")
        return problemas
    elif clave == "motivo_no_incluye":
        real = e.motivo_elegibilidad.lower()
        if esperado in real:
            problemas.append(f"motivo incluye {esperado!r}: {e.motivo_elegibilidad!r}")
        return problemas
    elif clave == "texto_incluye":
        real = " ".join(e.razones_texto() + e.incertidumbres + e.decisivas).lower()
        if esperado not in real:
            problemas.append(f"texto no incluye {esperado!r}")
        return problemas
    elif clave == "anios_requeridos":
        real = e.anios_requeridos
        if real != esperado:
            problemas.append(f"anios: {real!r} != {esperado!r}")
        return problemas
    else:
        real = getattr(e, clave, None)

    if isinstance(esperado, str) and esperado.startswith("!"):
        if real == esperado[1:]:
            problemas.append(f"{clave}: {real!r} no debía ser {esperado[1:]!r}")
    elif real != esperado:
        problemas.append(f"{clave}: {real!r} != {esperado!r}")
    return problemas
