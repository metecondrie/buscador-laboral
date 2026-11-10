"""Fase 1E — D1 (regiones multipaís), D2 (precedencia) y D3 (categoría).

Estas pruebas se escribieron ANTES de tocar `rules.py` y fallan con la Fase 1D.
Describen QUÉ debe pasar con avisos vistos desde Argentina, con remoto
obligatorio e inglés B1; no describen cómo está implementado el clasificador.

Reglas de esta suite:

- Sólo dicts en memoria; ninguna prueba abre la base operativa ni la red.
- El perfil es una COPIA con inglés B1: ni `perfil.json` ni `PERFIL_EJEMPLO` cambian.
- No se modifica `RULES_VERSION`, no hay modelos ni reclasificación.
- Cada corrección lleva pares de control: se comprueba también el caso que
  SÍ debe seguir excluyendo, para que la reparación no sea un parche permisivo.
"""
from __future__ import annotations

import copy

import pytest

from buscador import config, rules
from buscador.perfil import PERFIL_EJEMPLO

PERFIL_B1 = copy.deepcopy(PERFIL_EJEMPLO)
PERFIL_B1["idioma"]["ingles"] = "B1"

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


def evaluar(**cambios):
    oferta = dict(BASE)
    oferta.update(cambios)
    return rules.evaluar(oferta, PERFIL_B1)


def con(frase: str, **cambios):
    return evaluar(texto=f"{frase} {SQL} {REMOTE}".strip(), **cambios)


# ===========================================================================
# D1 · Una lista multipaís que incluye Argentina/LATAM no se descarta
# ===========================================================================

LISTAS_CON_ALCANCE_COMPATIBLE = [
    ("Argentina, Colombia",
     "Where: Argentina or Colombia - 100% Remote."),
    ("Argentina,  Hong Kong,  Singapore,  UAE",
     "We hire in Argentina, Hong Kong, Singapore or the UAE."),
    ("LATAM,  Canada,  USA",
     "Open to candidates in LATAM, Canada and the USA."),
]


@pytest.mark.parametrize("region,frase", LISTAS_CON_ALCANCE_COMPATIBLE)
def test_d1_lista_multipais_con_argentina_o_latam_no_descarta(region, frase):
    e = con(frase, region=region)
    assert e.elegibilidad != "incompatible", (region, e.motivo_elegibilidad)
    assert e.requisitos["alcance_territorial"] != "restringido", region


def test_d1_lista_larga_de_paises_que_incluye_argentina_no_descarta():
    region = ("Argentina, Australia, Austria, Belgium, Brazil, Bulgaria, Canada, "
              "China, Colombia, Germany, Ireland, Japan, Mexico, Netherlands, "
              "Poland, Singapore, Spain, Sweden, UK, USA, Vietnam")
    e = evaluar(region=region)
    assert e.elegibilidad != "incompatible"
    assert e.requisitos["alcance_territorial"] == "internacional"


def test_d1_americas_frente_a_lista_canada_usa_queda_dudosa():
    """Contradicción real: etiqueta Canada/USA vs «anywhere in the Americas»."""
    e = con("Fully remote. Work from anywhere in the Americas.",
            region="Canada,  USA")
    assert e.elegibilidad == "doubtful"
    assert e.requisitos["alcance_territorial"] != "restringido"


def test_d1_lista_compatible_no_marca_elegible_si_otro_requisito_lo_impide():
    e = con("Where: Argentina or Colombia. Degree required.",
            region="Argentina, Colombia")
    assert e.elegibilidad == "incompatible"


# Controles negativos: restricciones EXPLÍCITAS a US, Canadá y Europa.
@pytest.mark.parametrize("region", [
    "US Only", "USA Only", "Canada Only", "Europe Only", "EU Only",
    "United States", "Canada", "North America Only",
])
def test_d1_control_negativo_restriccion_explicita_en_etiqueta(region):
    e = evaluar(region=region)
    assert e.elegibilidad == "incompatible", region
    assert e.requisitos["alcance_territorial"] == "restringido", region


@pytest.mark.parametrize("frase", [
    "US only.",
    "Only open to candidates in Canada.",
    "Must be based in Europe.",
    "Candidates must reside in the United States.",
])
def test_d1_control_negativo_restriccion_explicita_en_descripcion(frase):
    e = con(frase, region="Argentina, Colombia")
    assert e.elegibilidad == "incompatible", frase


def test_d1_control_negativo_restriccion_explicita_en_titulo():
    e = con("Where: Argentina or Colombia.",
            region="Argentina, Colombia", titulo="Data Analyst (US Only)")
    assert e.elegibilidad == "incompatible"


# Distinción entre lista de admitidos, residencia obligatoria, sede y menciones.
def test_d1_sede_de_la_empresa_no_es_restriccion_de_residencia():
    e = con("Headquarters: Chicago, Illinois, United States.", region="Worldwide")
    assert e.elegibilidad != "incompatible"


def test_d1_paises_mencionados_incidentalmente_no_restringen():
    e = con("Our platform serves customers in 100+ countries, including Canada and the USA.",
            region="Worldwide")
    assert e.elegibilidad != "incompatible"


def test_d1_residencia_obligatoria_en_el_cuerpo_sigue_excluyendo():
    e = con("Must reside in Canada.", region="Argentina, Colombia")
    assert e.elegibilidad == "incompatible"


# ===========================================================================
# D2 · Las restricciones obligatorias se evalúan ANTES que las preferencias
# ===========================================================================

@pytest.mark.parametrize("frase,region", [
    ("A US work permit is preferred.", "United States"),
    ("Candidates residing ideally in the Eastern or Central Time Zone.",
     "North America Only"),
])
def test_d2_preferencia_no_tapa_restriccion_territorial_explicita(frase, region):
    e = con(frase, region=region)
    assert e.elegibilidad == "incompatible", (frase, region, e.motivo_elegibilidad)
    assert e.requisitos["alcance_territorial"] == "restringido"


def test_d2_preferencia_legal_no_tapa_pais_explicito_del_titulo():
    e = con("In possession of a work permit from Canada, Finland, Spain, or the UK. "
            "Your application will not be considered if you do not meet this requirement.",
            region="Anywhere in the World",
            titulo="Customer Happiness Advocate (Remote - Canada)")
    assert e.elegibilidad == "incompatible", e.motivo_elegibilidad


def test_d2_obligatoriedad_horaria_gana_a_preferencia_legal():
    e = con("A US work permit is preferred. Candidates in EST time zones only.",
            region="Worldwide")
    assert e.elegibilidad == "incompatible"


@pytest.mark.parametrize("frase", [
    "A US work permit is preferred.",
    "Candidates residing ideally in the Eastern or Central Time Zone.",
])
def test_d2_preferencia_sin_restriccion_no_excluye(frase):
    e = con(frase, region="Worldwide")
    assert e.elegibilidad == "doubtful", frase
    assert e.requisitos["alcance_territorial"] != "restringido"


# Requisito legal: obligatorio ≠ preferido.
def test_d2_permiso_legal_obligatorio_excluye():
    e = con("Must have a US work permit.", region="Worldwide")
    assert e.elegibilidad == "incompatible"


def test_d2_permiso_legal_opcional_no_excluye():
    e = con("US work permit is a plus.", region="Worldwide")
    assert e.elegibilidad != "incompatible"


# Residencia ≠ disponibilidad horaria ≠ mención incidental.
def test_d2_disponibilidad_horaria_no_es_residencia():
    e = con("Availability during EST business hours is required.", region="Worldwide")
    assert e.elegibilidad != "incompatible"


def test_d2_residencia_en_huso_extranjero_excluye():
    e = con("Candidates in EST time zones only.", region="Worldwide")
    assert e.elegibilidad == "incompatible"


def test_d2_mencion_incidental_de_permiso_no_inventa_obligatoriedad():
    e = con("Our headquarters is in the United States and we support 100+ countries.",
            region="Worldwide")
    assert e.elegibilidad != "incompatible"


# ===========================================================================
# D3 · «operations analyst» no basta para un puesto de ingeniería
# ===========================================================================

INGENIERIA_OPS = (
    "This is an engineering role, not a ticket queue. You will own the lifecycle "
    "of our corporate technology: Google Workspace, Okta, MDM, Cloudflare Zero "
    "Trust, endpoint compliance, Terraform and automation. Security is embedded, "
    "not a separate function."
)
SOPORTE_OPS = (
    "You will handle tickets, help desk requests and live chat for end users. "
    "Customer support and customer inquiries are the core of the role."
)
DATOS_OPS = (
    "Own data quality, data governance and dashboards for security data. "
    "Build SQL reports and maintain data pipelines."
)


def test_d3_upguard_no_queda_eligible_por_coincidencia_superficial():
    e = evaluar(titulo="IT Operations Analyst", region="LATAM",
                texto=f"{INGENIERIA_OPS} {SQL} {REMOTE}")
    assert e.elegibilidad != "eligible", e.motivo_elegibilidad
    categoria, _, _ = rules.categoria_de("IT Operations Analyst", INGENIERIA_OPS)
    assert categoria is None


def test_d3_it_operations_con_tareas_de_soporte_no_se_prohibe():
    categoria, _, origen = rules.categoria_de("IT Operations Analyst", SOPORTE_OPS)
    assert categoria == "Customer Support"
    assert origen == "texto"
    e = evaluar(titulo="IT Operations Analyst", region="LATAM",
                texto=f"{SOPORTE_OPS} {SQL} {REMOTE}")
    assert e.elegibilidad != "incompatible"


def test_d3_security_operations_con_tareas_de_datos_no_se_prohibe():
    categoria, _, origen = rules.categoria_de("Security Operations Analyst", DATOS_OPS)
    assert categoria == "Data Operations"
    assert origen == "texto"
    e = evaluar(titulo="Security Operations Analyst", region="LATAM",
                texto=f"{DATOS_OPS} {SQL} {REMOTE}")
    assert e.elegibilidad != "incompatible"


def test_d3_operations_analyst_generico_sigue_siendo_business_analyst():
    categoria, _, origen = rules.categoria_de(
        "Operations Analyst", "Requirements gathering with stakeholders and process mapping.")
    assert categoria == "Business Analyst"
    assert origen == "titulo"


def test_d3_it_operations_sin_tareas_del_perfil_no_es_elegible():
    e = evaluar(titulo="IT Operations Analyst", region="LATAM",
                texto=f"{SQL} {REMOTE}")
    assert e.elegibilidad != "eligible"


# ===========================================================================
# Resguardo de la fase
# ===========================================================================

def test_fase1e_no_cambia_la_version_ni_el_perfil_de_demostracion():
    assert config.RULES_VERSION == "rules-3.4.0"
    assert PERFIL_B1["idioma"]["ingles"] == "B1"
    assert PERFIL_EJEMPLO["idioma"]["ingles"] == "B2"
