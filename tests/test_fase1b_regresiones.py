"""Fase 1B: requisitos funcionales de la auditoría adversarial (P0 y P1).

Estas pruebas NO describen cómo está escrito el clasificador: describen qué
 debe pasar con avisos concretos vistos desde Argentina, con remoto obligatorio
 e inglés B1. Se escribieron ANTES de la reparación y fallaban con la Fase 1.

Reglas de esta suite:

- Todo se evalúa con dicts en memoria o la base SQLite temporal (`entorno`).
- No hay red, ni modelos, ni lectura de la base operativa, ni reclasificación.
- El perfil es una COPIA con inglés B1: ni `perfil.json` ni `PERFIL_EJEMPLO` se
  modifican (el usuario no autorizó subir el nivel a B2).
- No se cambia `RULES_VERSION` ni se desactiva la fuente F05.
"""

from __future__ import annotations

import copy

import pytest

from buscador import config, rules
from buscador.adapters import ADAPTADORES
from buscador.perfil import PERFIL_EJEMPLO

PERFIL_B1 = copy.deepcopy(PERFIL_EJEMPLO)
PERFIL_B1["idioma"]["ingles"] = "B1"

BASE = {
    "titulo": "Junior Data Analyst",
    "texto": "SQL required. Excel required. Python required. Remote.",
    "region": "Anywhere in the World",
    "seniority": None,
    "salario": None,
    "publicado_en": "2026-11-01T00:00:00Z",
    "expira_en": None,
}

SQL = "SQL required. Excel required. Python required."


def evaluar(**cambios):
    oferta = dict(BASE)
    oferta.update(cambios)
    return rules.evaluar(oferta, PERFIL_B1)


def idioma(e, nombre="idioma"):
    return next(c for c in e.componentes if c.nombre == nombre)


# ===========================================================================
# P0-A · Territorio ambiguo: «anywhere» no significa mundial si nombra un país
# ===========================================================================

@pytest.mark.parametrize("region,pista", [
    ("Anywhere in Canada", "canada"),
    ("Anywhere in the US", "us"),
    ("Anywhere in the USA", "usa"),
    ("Anywhere in the United States", "united states"),
    ("Anywhere in the UK", "uk"),
    ("Anywhere in Germany", "germany"),
])
def test_anywhere_en_un_pais_concreto_no_es_alcance_mundial(region, pista):
    """«Anywhere in X» admite TODO X, no todo el mundo."""
    e = evaluar(region=region)
    assert e.requisitos["alcance_territorial"] != "mundial"
    assert e.requisitos["alcance_territorial"] == "restringido"
    assert e.elegibilidad == "incompatible"
    assert pista in e.motivo_elegibilidad.lower()


@pytest.mark.parametrize("region,alcance", [
    ("Anywhere in the World", "mundial"),
    ("Anywhere in Argentina", "argentina"),
    ("Worldwide", "mundial"),
    ("Latin America Only", "internacional"),
    ("Argentina", "argentina"),
])
def test_anywhere_sin_pais_restringido_sigue_siendo_compatible(region, alcance):
    e = evaluar(region=region)
    assert e.elegibilidad != "incompatible"
    assert e.requisitos["alcance_territorial"] == alcance


@pytest.mark.parametrize("region", ["Argentina", "Worldwide", "Anywhere in the World", None])
def test_la_region_compatible_no_tapa_una_restriccion_explicita_del_cuerpo(region):
    """Una etiqueta «Argentina»/«Worldwide» no puede ignorar lo que dice el aviso."""
    e = evaluar(region=region, texto=f"US only. {SQL} Remote.")
    assert e.elegibilidad == "incompatible"
    assert e.requisitos["alcance_territorial"] == "restringido"


def test_region_argentina_no_tapa_autorizacion_de_trabajo_extranjera():
    e = evaluar(region="Argentina",
                texto="Must be authorized to work in the United States. "
                      f"{SQL} Remote.")
    assert e.elegibilidad == "incompatible"


def test_declaracion_global_en_el_cuerpo_no_se_convierte_en_restriccion():
    e = evaluar(region="Argentina",
                texto="We welcome qualified applicants from around the world. "
                      f"{SQL} Remote.")
    assert e.elegibilidad != "incompatible"


def test_territorio_contradictorio_prima_la_restriccion_explicita():
    """«Anywhere in Canada» + bienvenida global: el país concreto manda."""
    e = evaluar(region="Anywhere in Canada",
                texto="We welcome qualified applicants from around the world. "
                      f"{SQL} Remote.")
    assert e.elegibilidad == "incompatible"
    assert "canada" in e.motivo_elegibilidad.lower()


def test_mencion_de_un_pais_como_mercado_no_es_restriccion_de_residencia():
    e = evaluar(region="Worldwide",
                texto="We serve customers in the US, Canada and Europe. "
                      f"{SQL} Remote.")
    assert e.elegibilidad != "incompatible"
    assert e.requisitos["alcance_territorial"] != "restringido"


def test_us_como_pronombre_no_se_lee_como_estados_unidos():
    e = evaluar(region="Worldwide",
                texto="Contact us only if you have questions. "
                      f"{SQL} Remote.")
    assert e.elegibilidad != "incompatible"


# ===========================================================================
# P0-B · Residencia y autorización: lo obligatorio excluye, lo preferido no
# ===========================================================================

@pytest.mark.parametrize("frase", [
    "US only.",
    "USA only.",
    "U.S. only.",
    "US-based candidates only.",
    "US residents only.",
    "Must be authorized to work in the United States.",
    "Applicants must be eligible to live and work in the US.",
    "Candidates must be located in the United States.",
    "Only applicants based in Canada are considered.",
    "US work authorization is required.",
    "This role is restricted to candidates in the UK.",
    "North America Only.",
])
def test_restriccion_de_residencia_o_autorizacion_excluye(frase):
    e = evaluar(region="Worldwide", texto=f"{frase} {SQL} Remote.")
    assert e.elegibilidad == "incompatible", frase
    assert e.requisitos["alcance_territorial"] == "restringido", frase


@pytest.mark.parametrize("frase", [
    "US-Remote, EST or CT time zone only.",
    "EST or CT time zone only.",
    "Eastern or Pacific time zone only.",
    "Candidates must be based in the PST time zone.",
    "Central/Mountain/Eastern time zones only.",
    "Candidates in Central, Mountain or Eastern time zones.",
])
def test_huso_horario_obligatorio_es_una_restriccion_geografica(frase):
    e = evaluar(region="Worldwide", texto=f"{frase} {SQL} Remote.")
    assert e.elegibilidad == "incompatible", frase
    assert e.requisitos["alcance_territorial"] == "restringido", frase


@pytest.mark.parametrize("frase", [
    "We prefer candidates in EST time zone.",
    "Availability to work 9:00 a.m. to 6:00 p.m. Pacific Time.",
    "We are looking for someone to work during MST time zone hours.",
    "Medical and dental insurance for eligible US-based team members.",
    "We welcome qualified applicants from around the world.",
])
def test_preferencia_horaria_o_beneficio_no_es_residencia_obligatoria(frase):
    """La preferencia horaria y el beneficio para empleados NO descartan."""
    e = evaluar(region="Worldwide", texto=f"{frase} {SQL} Remote.")
    assert e.elegibilidad != "incompatible", frase
    assert e.requisitos["alcance_territorial"] != "restringido", frase


# ===========================================================================
# P0-C · Idiomas: una cláusula optativa no puede anular otra obligatoria
# ===========================================================================

@pytest.mark.parametrize("texto,obligatorio,opcional", [
    ("French required, German a plus.", "french", "german"),
    ("German desirable. French required.", "french", "german"),
    ("German a plus. French is mandatory.", "french", "german"),
    ("French is a plus. German required.", "german", "french"),
    ("French is a plus, German is essential.", "german", "french"),
])
def test_idioma_obligatorio_excluye_aunque_otro_sea_opcional(texto, obligatorio, opcional):
    e = evaluar(region="Worldwide", texto=f"{texto} {SQL} Remote.")
    assert e.requisitos["estado_idioma"] == "incumplido"
    assert e.elegibilidad == "incompatible"
    motivo = e.motivo_elegibilidad.lower()
    assert obligatorio in motivo
    assert opcional not in motivo


@pytest.mark.parametrize("texto", [
    "Bilingual (English/Spanish or Italian, Dutch, French) is a plus.",
    "French is a plus. German desirable.",
    "French is not required.",
    "No French required.",
    "French not required. German not required.",
    "German is optional; French is nice to have.",
])
def test_idioma_opcional_o_negado_no_excluye(texto):
    e = evaluar(region="Worldwide", texto=f"{texto} {SQL} Remote.")
    assert e.requisitos["estado_idioma"] != "incumplido"
    assert e.elegibilidad != "incompatible"


def test_negacion_explicita_de_un_idioma_no_tapa_otro_obligatorio():
    e = evaluar(region="Worldwide",
                texto=f"French is not required. German required. {SQL} Remote.")
    assert e.elegibilidad == "incompatible"
    assert "german" in e.motivo_elegibilidad.lower()


def test_clausulas_contradictorias_quedan_para_revisar_no_para_descartar():
    """«French required» + «French is not required» es ambiguo, no una exclusión."""
    e = evaluar(region="Worldwide",
                texto=f"French required. French is not required. {SQL} Remote.")
    assert e.elegibilidad != "incompatible"
    assert e.requisitos["estado_idioma"] != "incumplido"


def test_idioma_obligatorio_clasico_sigue_excluyendo():
    e = evaluar(region="Worldwide", texto=f"Turkish required. {SQL} Remote.")
    assert e.elegibilidad == "incompatible"
    assert "turkish" in e.motivo_elegibilidad.lower()


# ===========================================================================
# P1 · Modalidad: título, negaciones y contexto (no es territorio)
# ===========================================================================

@pytest.mark.parametrize("titulo", [
    "On-site Data Analyst",
    "Onsite Data Analyst",
    "Data Analyst - Presencial",
    "In-office Data Analyst",
])
def test_presencialidad_explicita_en_el_titulo_se_detecta(titulo):
    e = evaluar(titulo=titulo, region="Worldwide", texto=SQL)
    assert e.modalidad == "onsite"
    assert e.elegibilidad == "incompatible"


@pytest.mark.parametrize("texto", [
    "No onsite requirement.",
    "There is no onsite requirement for this role.",
    "Onsite interview only for finalists.",
    "Onsite parking available at HQ.",
    "We hold an annual onsite meeting for the whole team.",
])
def test_menciones_onsite_negadas_o_ajenas_al_puesto_no_imponen_presencialidad(texto):
    e = evaluar(region="Worldwide", texto=f"{texto} {SQL}")
    assert e.modalidad != "onsite"
    assert e.elegibilidad != "incompatible"


@pytest.mark.parametrize("texto", [
    "Not a remote position.",
    "This is not a remote role.",
    "No remote work available.",
])
def test_no_remoto_no_se_clasifica_como_remoto(texto):
    e = evaluar(region="Worldwide", texto=f"{texto} {SQL}")
    assert e.modalidad != "remote"
    assert e.elegibilidad == "incompatible"


@pytest.mark.parametrize("texto", ["Fully remote role.", "100% remote position.",
                                   "Work from home.", "Home-based position."])
def test_remoto_afirmativo_sigue_detectandose(texto):
    e = evaluar(region="Worldwide", texto=f"{texto} {SQL}")
    assert e.modalidad == "remote"
    assert e.elegibilidad != "incompatible"


@pytest.mark.parametrize("texto", [
    "No onsite requirement. Fully remote role.",
    "Onsite interview only for finalists. Fully remote position.",
])
def test_negacion_de_presencialidad_con_remoto_explicito_es_remoto(texto):
    e = evaluar(region="Worldwide", texto=f"{texto} {SQL}")
    assert e.modalidad == "remote"
    assert e.elegibilidad != "incompatible"


def test_aviso_contradictorio_no_remoto_y_remoto_no_se_da_por_remoto():
    """Si el aviso se desdice, la negación explícita gana (conservador)."""
    e = evaluar(region="Worldwide",
                texto=f"Fully remote team. Not a remote position. {SQL}")
    assert e.modalidad != "remote"
    assert e.elegibilidad == "incompatible"


@pytest.mark.parametrize("region", ["Fully remote", "100% Remote", "Work from home",
                                    "Home based", "Distributed team"])
def test_terminos_de_modalidad_no_declaran_territorio(region):
    """«Fully remote» dice CÓMO se trabaja, no DESDE DÓNDE se contrata."""
    e = evaluar(region=region, texto=SQL)
    assert e.requisitos["alcance_territorial"] == "desconocido"
    assert e.modalidad == "remote"


def test_territorio_modalidad_y_ubicacion_van_por_carriles_separados():
    presencial = evaluar(region="Latin America Only", texto=f"On-site role. {SQL}")
    assert presencial.requisitos["alcance_territorial"] == "internacional"
    assert presencial.modalidad == "onsite"

    remota = evaluar(region="Berlin, Germany", texto=f"Fully remote. {SQL}")
    assert remota.modalidad == "remote"
    assert remota.requisitos["alcance_territorial"] == "restringido"
    assert remota.elegibilidad == "incompatible"


# ===========================================================================
# P1 · ISO de países y abreviaturas ambiguas
# ===========================================================================

@pytest.mark.parametrize("region", ["UK", "GB", "US", "USA", "Toronto, CA",
                                    "Berlin, DE", "Paris, FR", "Madrid, ES"])
def test_codigos_iso_restringidos_no_quedan_como_duda(region):
    e = evaluar(region=region)
    assert e.elegibilidad == "incompatible", region
    assert e.requisitos["alcance_territorial"] == "restringido", region


@pytest.mark.parametrize("region", ["La Plata, AR", "Buenos Aires, AR",
                                    "Cordoba, AR", "Rosario, AR"])
def test_ar_es_argentina_cuando_el_contexto_lo_confirma(region):
    """AR es el ISO de Argentina; también es Arkansas. El contexto decide."""
    e = evaluar(region=region)
    assert e.elegibilidad != "incompatible", region
    assert e.requisitos["alcance_territorial"] == "argentina", region


def test_ar_suelto_es_ambiguo_y_no_descarta():
    e = evaluar(region="AR")
    assert e.elegibilidad != "incompatible"
    assert e.requisitos["alcance_territorial"] == "desconocido"


# ===========================================================================
# P1 · Inglés CEFR: B1, B2, C1, C2 y negaciones (perfil B1 intacto)
# ===========================================================================

@pytest.mark.parametrize("texto", [
    "English A2 required.", "English B1 required.",
    "English B1 proficiency is required.",
])
def test_nivel_de_ingles_igual_o_menor_al_perfil_se_cumple(texto):
    e = evaluar(region="Worldwide", texto=f"{texto} {SQL} Remote.")
    assert e.requisitos["estado_idioma"] == "cumplido"
    assert idioma(e).obtenido == 8
    assert e.elegibilidad != "incompatible"


@pytest.mark.parametrize("texto,nivel", [
    ("English B2 required.", "B2"),
    ("English C1 required.", "C1"),
    ("English C2 required.", "C2"),
])
def test_nivel_de_ingles_superior_al_perfil_no_se_da_por_cumplido(texto, nivel):
    e = evaluar(region="Worldwide", texto=f"{texto} {SQL} Remote.")
    assert e.requisitos["estado_idioma"] != "cumplido"
    assert "B1" in " ".join(e.razones_texto() + e.incertidumbres)
    assert nivel in " ".join(e.razones_texto() + e.incertidumbres)
    assert e.elegibilidad != "incompatible"  # es duda, no un descarte


def test_ingles_sin_nivel_no_se_inventa_como_cumplido_con_b1():
    e = evaluar(region="Worldwide", texto=f"English required. {SQL} Remote.")
    assert e.requisitos["estado_idioma"] != "cumplido"
    assert "B1" in " ".join(e.razones_texto() + e.incertidumbres)


def test_ingles_no_requerido_no_se_trata_como_requisito():
    e = evaluar(region="Worldwide", texto=f"English is not required. {SQL} Remote.")
    assert e.elegibilidad != "incompatible"
    assert e.requisitos["estado_idioma"] != "incumplido"


def test_espanol_obligatorio_lo_cumple_el_perfil_nativo():
    e = evaluar(region="Worldwide", texto=f"Spanish required. {SQL} Remote.")
    assert e.elegibilidad != "incompatible"
    assert e.requisitos["estado_idioma"] == "cumplido"


def test_negacion_de_espanol_no_tapa_otro_idioma_obligatorio():
    e = evaluar(region="Worldwide",
                texto=f"Spanish not required. French required. {SQL} Remote.")
    assert e.elegibilidad == "incompatible"
    assert "french" in e.motivo_elegibilidad.lower()


# ===========================================================================
# Resguardos de la fase: versión, perfil, F05 y base sin escribir
# ===========================================================================

def test_no_se_cambia_la_version_de_reglas_ni_el_perfil():
    assert config.RULES_VERSION == "rules-3.3.0"
    assert PERFIL_EJEMPLO["idioma"]["ingles"] == "B2"   # constante de demostración, intacta
    assert PERFIL_B1["idioma"]["ingles"] == "B1"      # perfil operativo: se mantiene B1
    assert PERFIL_B1["territorio"]["remoto_obligatorio"] is True


def test_f05_sigue_registrada():
    assert "F05" in ADAPTADORES
    assert ADAPTADORES["F05"].__name__ == "TheMuse"


def test_evaluar_no_escribe_en_la_base(entorno):
    """La reparación es de reglas puras: ninguna corrida toca SQLite."""
    antes = entorno.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
    for _ in range(3):
        evaluar(region="Anywhere in Canada", texto="US only. French required.")
    despues = entorno.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
    assert despues == antes
