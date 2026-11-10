"""Fase 1C — corpus adversarial, contraejemplos y propiedades.

Estas pruebas se escribieron ANTES de la reparación y fallaban con la Fase 1B:
29 de los 47 casos del corpus daban un veredicto erróneo. Describen QUÉ debe
pasar, no cómo está implementado el clasificador.

Reglas de esta suite:

- Sólo dicts en memoria y (cuando hace falta) la base SQLite temporal `entorno`.
- Sin red, sin APIs, sin modelos, sin base operativa, sin reclasificación.
- El perfil es una COPIA con inglés B1: ni `perfil.json` ni `PERFIL_EJEMPLO` cambian.
- No se modifica `RULES_VERSION`, `schema.sql`, `worker.py` ni la versión activa.
"""
from __future__ import annotations

import copy

import pytest

from buscador import config, perfil as perfil_mod, rules
from buscador.perfil import PERFIL_EJEMPLO
from corpus_fase1c import BASE, CASOS, SQL, REMOTE, fallos

PERFIL_B1 = copy.deepcopy(PERFIL_EJEMPLO)
PERFIL_B1["idioma"]["ingles"] = "B1"


def evaluar(**cambios):
    oferta = dict(BASE)
    oferta.update(cambios)
    return rules.evaluar(oferta, PERFIL_B1)


# ===========================================================================
# 1. Corpus adversarial: los 22 defectos y sus controles positivos/negativos
# ===========================================================================

@pytest.mark.parametrize("cid,grupo,cambios,checks", CASOS, ids=[c[0] for c in CASOS])
def test_caso_adversarial(cid, grupo, cambios, checks):
    e = evaluar(**cambios)
    problemas = fallos(e, checks)
    assert not problemas, f"{cid} [{grupo}]: " + " | ".join(problemas)


# ===========================================================================
# 2. Regla fundamental: una incompatibilidad explícita NO se vuelve elegible
#    por otro campo aparentemente favorable
# ===========================================================================

FAVORABLE = ("Great team and health insurance. English B1 required. Spanish required. "
             "We welcome qualified applicants from around the world. Fully remote.")

CASOS_INCOMPATIBLES = [(cid, cambios) for cid, _, cambios, checks in CASOS
                       if checks.get("elegibilidad") == "incompatible"]


@pytest.mark.parametrize("cid,cambios", CASOS_INCOMPATIBLES,
                         ids=[c[0] for c in CASOS_INCOMPATIBLES])
def test_evidencia_favorable_no_revierte_una_incompatibilidad_explicita(cid, cambios):
    oferta = dict(BASE)
    oferta.update(cambios)
    oferta["texto"] = f"{oferta['texto']} {FAVORABLE}"
    e = rules.evaluar(oferta, PERFIL_B1)
    assert e.elegibilidad == "incompatible", f"{cid}: {e.motivo_elegibilidad!r}"


# ===========================================================================
# 3. Pruebas metamórficas: ruido irrelevante no crea ni borra requisitos
# ===========================================================================

RUIDO = [
    "We offer medical and dental insurance.",
    "Our company was founded in 2009 and has 15 years of history.",
    "Onsite gym available at the headquarters.",
    "We welcome qualified applicants from around the world.",
    "We hold an annual onsite meeting for the whole team.",
    "Coffee, snacks and a friendly distributed team.",
    "Please mention your favourite colour in the application.",
]

BASES_INCOMPATIBLES = [
    ({"region": "Anywhere in Canada"}, "alcance_territorial"),
    ({"texto": f"US only. {SQL} {REMOTE}"}, "alcance_territorial"),
    ({"texto": f"French required. {SQL} {REMOTE}"}, "estado_idioma"),
    ({"texto": f"Onsite role. {SQL}"}, "modalidad"),
    ({"texto": f"10+ years required. {SQL} {REMOTE}"}, "estado_experiencia"),
    ({"texto": f"Bachelor's degree in Statistics required. {SQL} {REMOTE}"},
     "estado_formacion"),
    ({"texto": f"Relocation to Berlin is required. {SQL} {REMOTE}"}, "estado_laboral"),
]


@pytest.mark.parametrize("cambios,campo", BASES_INCOMPATIBLES)
@pytest.mark.parametrize("ruido", RUIDO)
def test_ruido_no_convierte_incompatibles_en_elegibles(cambios, campo, ruido):
    base = evaluar(**cambios)
    assert base.elegibilidad == "incompatible"
    con_ruido = evaluar(**{**cambios, "texto": f"{ruido} {cambios.get('texto', '')}"})
    assert con_ruido.elegibilidad == "incompatible", ruido
    assert con_ruido.requisitos[campo] == base.requisitos[campo], ruido


@pytest.mark.parametrize("ruido", RUIDO)
def test_ruido_no_inventa_requisitos_obligatorios(ruido):
    limpio = evaluar()
    with_ruido = evaluar(texto=f"{ruido} {BASE['texto']}")
    # Campos que representan requisitos OBLIGATORIOS: el ruido no los crea,
    # no los borra ni cambia el veredicto. (`estado_idioma` queda aparte: el
    # crédito parcial por «aviso en inglés» no es un requisito obligatorio.)
    for campo in ("estado_formacion", "estado_laboral", "estado_experiencia",
                  "alcance_territorial", "modalidad"):
        assert with_ruido.requisitos[campo] == limpio.requisitos[campo], (ruido, campo)
    assert with_ruido.anios_requeridos == limpio.anios_requeridos, ruido
    assert with_ruido.requisitos["estado_idioma"] not in {"incumplido"}, ruido
    assert with_ruido.elegibilidad == limpio.elegibilidad, ruido


# ===========================================================================
# 4. Contradicciones entre título, región y descripción
# ===========================================================================

@pytest.mark.parametrize("cambios", [
    {"region": "Worldwide", "titulo": "US Only Data Analyst"},
    {"region": "Argentina", "texto": f"US only. {SQL} {REMOTE}"},
    {"region": "Anywhere in Canada",
     "texto": f"We welcome qualified applicants from around the world. {SQL} {REMOTE}"},
    {"region": "Berlin, Germany", "titulo": "Remote Data Analyst",
     "texto": f"Fully remote. {SQL}"},
    {"region": "La Plata, Maryland, USA", "titulo": "Data Analyst Argentina"},
])
def test_contradiccion_territorial_manda_la_restriccion_explicita(cambios):
    e = evaluar(**cambios)
    assert e.elegibilidad == "incompatible"
    assert e.requisitos["alcance_territorial"] == "restringido"


def test_contradiccion_de_modalidad_no_se_resuelve_como_remota():
    e = evaluar(region="Worldwide", titulo="Onsite Data Analyst",
                texto=f"Fully remote role. {SQL}")
    assert e.modalidad != "remote"
    assert e.elegibilidad != "eligible"


def test_territorio_compatible_no_tapa_restricciones_multiples():
    e = evaluar(region="Argentina",
                texto=f"Must be a US citizen. French required. {SQL} {REMOTE}")
    assert e.elegibilidad == "incompatible"


# ===========================================================================
# 5. Propiedades: country explícito, idiomas, experiencia y niveles CEFR
# ===========================================================================

@pytest.mark.parametrize("region", [
    "Cordoba, Spain", "La Plata, Maryland, USA", "Rosario, Philippines",
    "Ambato, Ecuador", "Mendoza, Chile", "Quilmes, Peru", "Mar del Plata, Mexico",
])
def test_pais_explicito_gana_a_toponimos_argentinos(region):
    e = evaluar(region=region)
    assert e.elegibilidad == "incompatible", region


@pytest.mark.parametrize("region", [
    "Cordoba, AR", "La Plata, AR", "Rosario, Argentina", "Buenos Aires, Argentina",
])
def test_toponimo_argentino_con_pais_argentino_sigue_compatible(region):
    e = evaluar(region=region)
    assert e.elegibilidad != "incompatible", region
    assert e.requisitos["alcance_territorial"] == "argentina"


@pytest.mark.parametrize("frase", [
    "French required.", "Se requiere frances.", "Francophone required.",
    "French-speaking candidates required.", "El frances es obligatorio.",
])
def test_idioma_obligatorio_no_hablado_excluye_en_ambos_idiomas(frase):
    e = evaluar(texto=f"{frase} {SQL} {REMOTE}")
    assert e.elegibilidad == "incompatible", frase
    assert e.requisitos["estado_idioma"] == "incumplido", frase


@pytest.mark.parametrize("frase", [
    "English C1 required.", "English C2 required.", "English B2 required.",
    "Native English speaker required.", "Fluent English required.",
])
def test_nivel_de_ingles_superior_a_b1_nunca_es_elegible(frase):
    e = evaluar(texto=f"{frase} {SQL} {REMOTE}")
    assert e.elegibilidad != "eligible", frase
    mensajes = " ".join(e.razones_texto() + e.incertidumbres + e.decisivas
                        + [e.motivo_elegibilidad])
    assert "B1" in mensajes, frase
    # B2 puede aparecer como NIVEL PEDIDO; lo que no puede es atribuírselo
    # al perfil operativo, que es estrictamente B1.
    assert "perfil declara B2" not in mensajes, frase


@pytest.mark.parametrize("frase", [
    "10+ years required. 1 year of Python.",
    "Minimum 8 years of experience. 1 year of SQL.",
    "At least 10 years experience required. 2 years with Tableau.",
])
def test_experiencia_laboral_no_se_pierde_por_otra_mencion_numerica(frase):
    e = evaluar(texto=f"{frase} {SQL} {REMOTE}")
    assert e.elegibilidad == "incompatible", frase
    assert e.anios_requeridos is not None and e.anios_requeridos >= 8, frase


@pytest.mark.parametrize("frase", [
    "Must be 18 years or older.",
    "Our company has 15 years of history.",
    "The product has been on the market for 20 years.",
    "Founded 12 years ago.",
])
def test_edad_antiguedad_y_edad_de_producto_no_son_experiencia_laboral(frase):
    e = evaluar(texto=f"{frase} {SQL} {REMOTE}")
    assert e.elegibilidad != "incompatible", frase
    assert e.anios_requeridos is None, frase


@pytest.mark.parametrize("frase", [
    "Senior level required.", "Se requiere nivel senior.",
    "Minimum 5 years as a lead is mandatory.",
])
def test_seniority_obligatorio_en_el_cuerpo_se_detecta(frase):
    e = evaluar(texto=f"{frase} {SQL} {REMOTE}")
    assert e.elegibilidad != "eligible", frase


@pytest.mark.parametrize("frase", [
    "Bachelor's degree in Statistics required.",
    "Titulo en Estadistica excluyente.",
    "Se requiere titulo universitario.",
    "University degree is mandatory.",
])
def test_formacion_obligatoria_en_ingles_y_espanol(frase):
    e = evaluar(texto=f"{frase} {SQL} {REMOTE}")
    assert e.elegibilidad == "incompatible", frase
    assert e.requisitos["estado_formacion"] == "excluye", frase


@pytest.mark.parametrize("frase", [
    "Relocation to Berlin is required.",
    "Se requiere reubicacion en Madrid.",
    "Must be willing to relocate to Toronto.",
])
def test_reubicacion_obligatoria_excluye(frase):
    e = evaluar(texto=f"{frase} {SQL} {REMOTE}")
    assert e.elegibilidad == "incompatible", frase
    assert e.requisitos["estado_laboral"] == "excluye", frase


# ===========================================================================
# 5b. Contraejemplos independientes (no tomados de la auditoría)
# ===========================================================================

@pytest.mark.parametrize("frase,idioma_obligatorio", [
    ("French and German required.", "french"),          # coordinación con propagación
    ("French is a plus and German required.", "german"),
    ("German is a plus and French required.", "french"),
    ("Se requiere frances y aleman.", "french"),
])
def test_coordinacion_de_idiomas_no_oculta_un_requisito(frase, idioma_obligatorio):
    e = evaluar(texto=f"{frase} {SQL} {REMOTE}")
    assert e.elegibilidad == "incompatible", frase
    assert idioma_obligatorio in e.motivo_elegibilidad.lower(), frase


def test_edad_no_tapa_un_requisito_de_experiencia_laboral():
    e = evaluar(texto=f"Must be 18 years or older. 10+ years required. {SQL} {REMOTE}")
    assert e.elegibilidad == "incompatible"
    assert e.anios_requeridos == 10


@pytest.mark.parametrize("frase,debe_excluir", [
    # Fase 1D: ART es una ALTERNATIVA compatible. Que además aparezca EST no
    # autoriza el descarte; la expectativa anterior (True) estaba equivocada.
    ("EST or ART time zone only.", False),
    ("ART or EST time zone only.", False),
    ("ART time zone only.", False),            # huso argentino: compatible
    ("GMT time zone only.", False),            # referencia neutra
    ("Candidates in EST or PST time zones.", True),
])
def test_husos_mezclados_y_neutros(frase, debe_excluir):
    e = evaluar(texto=f"{frase} {SQL} {REMOTE}")
    if debe_excluir:
        assert e.elegibilidad == "incompatible", frase
        assert e.requisitos["alcance_territorial"] == "restringido", frase
    else:
        assert e.elegibilidad != "incompatible", frase


def test_restriccion_afirmativa_y_negacion_en_otra_oracion_no_se_compensan():
    e = evaluar(texto=f"US only. Not a US-only position. {SQL} {REMOTE}")
    assert e.elegibilidad == "incompatible"
    assert e.requisitos["alcance_territorial"] == "restringido"


def test_negacion_de_una_restriccion_no_cancela_otra_distinta():
    e = evaluar(texto=f"Not a US-only position. US citizens only. {SQL} {REMOTE}")
    assert e.elegibilidad == "incompatible"
    assert "estados unidos" in e.motivo_elegibilidad.lower()


def test_contradiccion_de_un_mismo_idioma_queda_para_revisar():
    e = evaluar(texto=f"French required. French is not required. {SQL} {REMOTE}")
    assert e.elegibilidad != "incompatible"
    assert e.requisitos["estado_idioma"] != "incumplido"


# ===========================================================================
# 6. Resguardos de la fase: B1, versión, perfil de demostración y base
# ===========================================================================

def test_perfil_operativo_b1_y_constante_de_demostracion_b2_intactas(tmp_path):
    assert PERFIL_EJEMPLO["idioma"]["ingles"] == "B2"
    assert PERFIL_B1["idioma"]["ingles"] == "B1"
    # RIESGO DOCUMENTADO: `perfil --real` aplica perfil_mod.perfil(rutas) (B2) y
    # guarda el perfil en disco + fuerza reclasificación total. No se ejecuta
    # contra la instalación operativa: la comprobación usa una raíz temporal.
    rutas = config.crear_estructura(tmp_path / "perfil-temporal")
    assert perfil_mod.perfil(rutas)["idioma"]["ingles"] == "B2"
    assert config.RULES_VERSION == "rules-3.1.0"


def test_evaluar_no_toca_la_base_temporal(entorno):
    antes = entorno.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
    for cid, _, cambios, _ in CASOS:
        rules.evaluar(dict(BASE, **cambios), PERFIL_B1)
    despues = entorno.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
    assert despues == antes
