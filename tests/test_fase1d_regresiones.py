"""Fase 1D — pares mínimos, correcciones focalizadas y contraejemplos nuevos.

Estas pruebas se escribieron ANTES de tocar `rules.py` y fallaban con la Fase 1C.
Describen QUÉ debe pasar con avisos concretos vistos desde Argentina, con remoto
obligatorio e inglés B1; no describen cómo está implementado el clasificador.

Reglas de esta suite:

- Sólo dicts en memoria; ninguna prueba abre la base operativa.
- El perfil es una COPIA con inglés B1: ni `perfil.json` ni `PERFIL_EJEMPLO` cambian.
- No se modifica `RULES_VERSION`, no hay red, no hay modelos, no hay reclasificación.
- Cada defecto lleva su par de control para que la corrección no sea un parche
  artificial: se comprueba también el caso que SÍ debe seguir excluyendo.
"""
from __future__ import annotations

import copy
import inspect

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


def con(frase: str, *, remoto: bool = True, **cambios):
    return evaluar(texto=f"{frase} {SQL} {REMOTE if remoto else ''}".strip(), **cambios)


# ===========================================================================
# E1 · «us» pronombre ≠ «US» territorio
# ===========================================================================

@pytest.mark.parametrize("titulo", [
    "Data Analyst - Join Us",
    "Data Analyst - Join us",
    "Data Analyst - Work with us",
    "Data Analyst - Come help us",
])
def test_titulo_con_pronombre_us_no_es_restriccion_territorial(titulo):
    e = evaluar(titulo=titulo)
    assert e.requisitos["alcance_territorial"] != "restringido", titulo
    assert e.elegibilidad != "incompatible", titulo


@pytest.mark.parametrize("titulo", ["US Only Data Analyst", "USA Only Data Analyst"])
def test_par_control_us_territorial_en_titulo_sigue_excluyendo(titulo):
    e = evaluar(titulo=titulo)
    assert e.elegibilidad == "incompatible", titulo
    assert e.requisitos["alcance_territorial"] == "restringido", titulo


def test_par_control_region_us_sigue_excluyendo():
    assert evaluar(region="US").elegibilidad == "incompatible"
    assert evaluar(region="USA").elegibilidad == "incompatible"


# ===========================================================================
# E2 · La negación de OTRA cláusula no cancela la restricción territorial
# ===========================================================================

@pytest.mark.parametrize("frase", [
    "No agencies please, US only.",
    "No visa sponsorship, US only.",
    "No agencies please. US only.",
    "No visa sponsorship. US only.",
])
def test_negacion_ajena_no_cancela_restriccion_territorial(frase):
    e = con(frase)
    assert e.elegibilidad == "incompatible", frase
    assert e.requisitos["alcance_territorial"] == "restringido", frase


@pytest.mark.parametrize("frase", [
    "This is not a US-only position.",
    "Not a US-only position.",
    "We are not restricted to candidates in the US.",
])
def test_par_control_negacion_de_la_misma_restriccion_si_cancela(frase):
    e = con(frase)
    assert e.elegibilidad != "incompatible", frase
    assert e.requisitos["alcance_territorial"] != "restringido", frase


# ===========================================================================
# E3 · Alternativas entre idiomas (disyunción, independientes del orden)
# ===========================================================================

LISTAS_CON_ESPANOL = [
    "Fluent in a second language: Italian, Spanish, French, or German.",
    "Fluent in a second language: German, French, Spanish, or Italian.",
    "Fluent in a second language: Spanish, Italian, German or French.",
    "Fluent in a second language: Italian or Spanish.",
    "Fluency in Spanish, Italian or German is required.",
]


@pytest.mark.parametrize("frase", LISTAS_CON_ESPANOL)
def test_alternativa_de_idiomas_se_satisface_con_espanol(frase):
    e = con(frase)
    assert e.elegibilidad != "incompatible", frase
    assert e.requisitos["estado_idioma"] == "cumplido", frase


@pytest.mark.parametrize("frase", [
    "Fluent in a second language: Italian, French, or German.",
    "Fluent in a second language: German or Italian.",
])
def test_par_control_alternativa_sin_idioma_del_perfil_excluye(frase):
    e = con(frase)
    assert e.elegibilidad == "incompatible", frase
    assert e.requisitos["estado_idioma"] == "incumplido", frase


def test_par_control_conjuncion_and_no_es_alternativa():
    e = con("Italian and Spanish required.")
    assert e.elegibilidad == "incompatible"
    assert e.requisitos["estado_idioma"] == "incumplido"


def test_independencia_del_orden_de_las_alternativas():
    resultados = [con(f) for f in LISTAS_CON_ESPANOL[:3]]
    estados = {(r.elegibilidad, r.requisitos["estado_idioma"], r.compatibilidad)
               for r in resultados}
    assert len(estados) == 1, estados


# ===========================================================================
# E4 · Requisito preferido, no obligatorio
# ===========================================================================

@pytest.mark.parametrize("frase", [
    "German language proficiency is a strong advantage.",
    "German language proficiency is advantageous.",
    "German language proficiency is preferred.",
    "German language proficiency is desirable.",
    "German is a strong advantage. French is desirable.",
])
def test_idioma_preferido_no_es_obligatorio(frase):
    e = con(frase)
    assert e.elegibilidad != "incompatible", frase
    assert e.requisitos["estado_idioma"] != "incumplido", frase


@pytest.mark.parametrize("frase", [
    "Spanish required. German language proficiency is a strong advantage.",
    "German is preferred. Spanish required.",
])
def test_preferido_no_contamina_un_idioma_obligatorio_satisfecho(frase):
    e = con(frase)
    assert e.requisitos["estado_idioma"] == "cumplido", frase
    assert e.elegibilidad != "incompatible", frase


@pytest.mark.parametrize("frase", [
    "German is preferred. French required.",
    "French required. German is a strong advantage.",
    "German is desirable but French is mandatory.",
])
def test_par_control_preferido_no_tapa_idioma_obligatorio_incumplido(frase):
    e = con(frase)
    assert e.elegibilidad == "incompatible", frase
    assert "french" in e.motivo_elegibilidad.lower(), frase


# ===========================================================================
# E5 · Reubicación negada
# ===========================================================================

@pytest.mark.parametrize("frase", [
    "No relocation required.",
    "Relocation is not required.",
    "No relocation is required.",
    "Relocation not required.",
])
def test_reubicacion_negada_no_exige_reubicarse(frase):
    e = con(frase)
    assert e.requisitos["estado_laboral"] != "excluye", frase
    assert e.elegibilidad != "incompatible", frase


@pytest.mark.parametrize("frase", [
    "Relocation is required.",
    "Relocation to Berlin is required.",
    "Must be willing to relocate.",
    "Se requiere reubicacion en Madrid.",
])
def test_par_control_reubicacion_afirmativa_sigue_excluyendo(frase):
    e = con(frase)
    assert e.requisitos["estado_laboral"] == "excluye", frase
    assert e.elegibilidad == "incompatible", frase


# ===========================================================================
# E6 · Alternativas de modalidad: «or» ≠ «and», «not only» ≠ «not»
# ===========================================================================

@pytest.mark.parametrize("frase", [
    "Remote or onsite.",
    "Hybrid or remote.",
    "Onsite or remote.",
    "Remote or hybrid.",
])
def test_modalidades_alternativas_no_imponen_presencialidad(frase):
    e = con(frase, remoto=False)
    assert e.modalidad != "onsite", frase
    assert e.elegibilidad == "doubtful", frase


def test_par_control_and_no_es_alternativa():
    e = con("Remote and onsite.", remoto=False)
    assert e.modalidad != "remote"
    assert e.elegibilidad != "eligible"


@pytest.mark.parametrize("frase", ["Not only remote.", "Not just remote."])
def test_not_only_remote_no_es_negacion_del_remoto(frase):
    e = con(frase, remoto=False)
    assert e.modalidad != "onsite", frase
    assert e.elegibilidad != "incompatible", frase


def test_par_control_not_a_remote_position_sigue_excluyendo():
    e = con("Not a remote position.", remoto=False)
    assert e.modalidad != "remote"
    assert e.elegibilidad == "incompatible"


def test_par_control_presencialidad_declarada_sigue_excluyendo():
    e = con("Onsite role.", remoto=False)
    assert e.modalidad == "onsite"
    assert e.elegibilidad == "incompatible"


# ===========================================================================
# E7 · Permiso de trabajo: obligatorio ≠ preferido
# ===========================================================================

@pytest.mark.parametrize("frase", [
    "Must have an EU work permit.",
    "Must have a European work permit.",
    "A European work permit is required.",
    "EU work permit required.",
])
def test_permiso_de_trabajo_obligatorio_se_detecta(frase):
    e = con(frase)
    assert e.elegibilidad == "incompatible", frase
    assert e.requisitos["alcance_territorial"] == "restringido", frase


@pytest.mark.parametrize("frase", [
    "EU work permit preferred.",
    "A European work permit is desirable.",
])
def test_permiso_de_trabajo_preferido_no_excluye_pero_queda_en_duda(frase):
    e = con(frase)
    assert e.elegibilidad == "doubtful", frase
    assert e.requisitos["alcance_territorial"] != "restringido", frase


def test_par_control_obligatorio_gana_a_preferido():
    e = con("EU work permit preferred. US only.")
    assert e.elegibilidad == "incompatible"


# ===========================================================================
# E8 · Husos: residencia ≠ disponibilidad horaria; alternativas compatibles
# ===========================================================================

@pytest.mark.parametrize("frase", [
    "US time zones only.",
    "EST time zone only. Availability to work 9 a.m. to 6 p.m.",
])
def test_huso_ambiguo_no_clasifica_como_incompatible(frase):
    e = con(frase)
    assert e.elegibilidad == "doubtful", frase
    assert e.requisitos["alcance_territorial"] != "restringido", frase


@pytest.mark.parametrize("frase", [
    "EST or ART time zone only.",
    "ART or EST time zone only.",
    "ART time zone only.",
])
def test_alternativa_argentina_en_husos_no_excluye(frase):
    e = con(frase)
    assert e.elegibilidad != "incompatible", frase


@pytest.mark.parametrize("frase", [
    "Candidates must be based in the PST time zone.",
    "EST or CT time zone only.",
    "Candidates in EST or PST time zones.",
])
def test_par_control_residencia_en_huso_extranjero_sigue_excluyendo(frase):
    e = con(frase)
    assert e.elegibilidad == "incompatible", frase
    assert e.requisitos["alcance_territorial"] == "restringido", frase


# ===========================================================================
# Defectos adicionales
# ===========================================================================

FULL = ("SQL required. Excel required. Python required. Dashboards. "
        "1 year of experience. Spanish required. Remote.")


def test_formacion_eximida_hace_alcanzable_el_100_y_el_estado_ok():
    base = evaluar(texto=FULL)
    assert base.compatibilidad == 93.0                 # techo real de la Fase 1C
    assert base.requisitos["estado_formacion"] == "desconocido"

    con_exencion = evaluar(texto=f"No degree required. {FULL}")
    assert con_exencion.requisitos["estado_formacion"] == "ok"
    formacion = next(c for c in con_exencion.componentes if c.nombre == "formacion")
    assert formacion.estado == "cumplido"
    assert formacion.obtenido == 7
    assert con_exencion.compatibilidad == 100.0


def test_formacion_contradictoria_no_se_resuelve_como_cumplimiento():
    e = con("Bachelor degree required. No degree required.")
    assert e.requisitos["estado_formacion"] == "duda"


@pytest.mark.parametrize("frase", [
    "25+ years of experience required.",
    "30 years of experience required.",
])
def test_requisitos_de_mas_de_20_anios_no_se_descartan(frase):
    assert rules.anios_requeridos(frase) is not None
    e = con(frase)
    assert e.anios_requeridos is not None and e.anios_requeridos > 20
    assert e.elegibilidad == "incompatible", frase


@pytest.mark.parametrize("frase", [
    "Our company has 25 years of history.",
    "Must be 25 years or older.",
])
def test_par_control_edad_y_antiguedad_siguen_siendo_25_anios_no_laborales(frase):
    assert rules.anios_requeridos(frase) is None
    assert con(frase).anios_requeridos is None


def test_no_queda_codigo_muerto_en_experiencia():
    fuente = inspect.getsource(rules._experiencia)
    assert "pide {anios} años y el perfil declara 1" not in fuente
    estado, motivo, anios = rules._experiencia(
        "Junior Data Analyst", "1 year of experience.", None, 0.0)
    assert estado == "cumplido" and anios == 1
    assert "1 años" not in motivo


@pytest.mark.parametrize("frase", [
    "French required. French is not required.",
    "Spanish required. Spanish is not required.",
    "French required. No French required.",
])
def test_contradiccion_de_idioma_no_es_cumplimiento_confirmado(frase):
    e = con(frase)
    assert e.elegibilidad == "doubtful", frase
    assert e.requisitos["estado_idioma"] == "contradictorio", frase
    assert e.requisitos["estado_idioma"] != "cumplido"
    assert any("contradic" in texto for texto in e.incertidumbres + e.decisivas), frase


def test_par_control_idioma_no_contradictorio_sigue_siendo_incumplido():
    e = con("French required.")
    assert e.requisitos["estado_idioma"] == "incumplido"
    assert e.elegibilidad == "incompatible"


# ===========================================================================
# Contraejemplos nuevos (revisión adversarial propia)
# ===========================================================================

@pytest.mark.parametrize("frase", [
    "No agencies please, US only. Fully remote.",
    "No visa sponsorship, US only. Spanish required.",
])
def test_evidencia_favorable_no_revierte_restriccion_territorial(frase):
    e = con(frase)
    assert e.elegibilidad == "incompatible", frase


def test_alternativa_satisfecha_no_cancela_otro_requisito_separado():
    e = con("Fluent in a second language: Italian or Spanish. French required.")
    assert e.elegibilidad == "incompatible"
    assert "french" in e.motivo_elegibilidad.lower()


def test_contradiccion_no_tapa_otro_idioma_obligatorio():
    e = con("French required. French is not required. German required.")
    assert e.elegibilidad == "incompatible"


def test_alternativas_de_modalidad_no_tapan_una_restriccion_territorial():
    e = con("US only. Remote or onsite.", remoto=False)
    assert e.elegibilidad == "incompatible"


# --- Propiedades metamórficas ----------------------------------------------

RUIDO = [
    "We offer medical and dental insurance.",
    "Our company was founded in 2009 and has 15 years of history.",
    "Onsite gym available at the headquarters.",
    "Coffee, snacks and a friendly distributed team.",
    "Please mention your favourite colour in the application.",
]

CAMPOS_ESTABLES = ("alcance_territorial", "modalidad", "estado_idioma",
                   "estado_formacion", "estado_laboral", "estado_experiencia")


@pytest.mark.parametrize("ruido", RUIDO)
def test_texto_irrelevante_no_altera_requisitos(ruido):
    limpio = con("No agencies please, US only. Spanish required. No relocation required.")
    con_ruido = con(f"{ruido} No agencies please, US only. Spanish required. "
                    "No relocation required.")
    for campo in CAMPOS_ESTABLES:
        assert limpio.requisitos[campo] == con_ruido.requisitos[campo], (ruido, campo)
    assert limpio.elegibilidad == con_ruido.elegibilidad, ruido


@pytest.mark.parametrize("ruido", RUIDO)
def test_texto_irrelevante_no_convierte_alternativas_en_obligaciones(ruido):
    limpio = con("Fluent in a second language: Italian, Spanish, French, or German.")
    con_ruido = con(f"{ruido} Fluent in a second language: Italian, Spanish, French, or German.")
    assert limpio.requisitos["estado_idioma"] == con_ruido.requisitos["estado_idioma"]
    assert limpio.elegibilidad == con_ruido.elegibilidad


def test_orden_de_alternativas_de_modalidad_no_cambia_el_veredicto():
    pares = ["Remote or onsite.", "Onsite or remote.", "Hybrid or remote.", "Remote or hybrid."]
    resultados = {(con(f, remoto=False).elegibilidad,
                   con(f, remoto=False).modalidad) for f in pares}
    assert resultados == {("doubtful", "unknown")}, resultados


def test_mencion_de_permiso_sin_obligatoriedad_no_inventa_un_descarte():
    e = con("We provide EU work permit guidance for successful candidates.")
    assert e.elegibilidad != "incompatible"


def test_huso_con_residencia_explicita_si_excluye():
    e = con("Candidates must be based in US time zones only.")
    assert e.elegibilidad == "incompatible"


def test_alternativa_con_ingles_b1_tambien_satisface():
    e = con("Fluent in English B1 or German is required.")
    assert e.requisitos["estado_idioma"] == "cumplido"
    assert e.elegibilidad != "incompatible"


def test_negacion_de_reubicacion_no_tapa_otra_clausula_que_si_exige():
    e = con("No relocation required. Must be willing to relocate.")
    assert e.requisitos["estado_laboral"] == "excluye"
    assert e.elegibilidad == "incompatible"


# --- Resguardos de la fase --------------------------------------------------

def test_resguardos_de_la_fase():
    assert config.RULES_VERSION == "rules-3.2.0"
    assert PERFIL_EJEMPLO["idioma"]["ingles"] == "B2"
    assert PERFIL_B1["idioma"]["ingles"] == "B1"
    assert PERFIL_B1["territorio"]["remoto_obligatorio"] is True
