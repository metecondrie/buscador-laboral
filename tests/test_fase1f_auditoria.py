"""Aceptación de la revisión 2026-11-10 (Gemini + Qwen): casos C, E, L, S, T.

Todo es sintético. El perfil se declara acá adentro para que el resultado no
dependa del perfil real ni del de ejemplo. Cada prueba nombra el hallazgo que
protege, de modo que un cambio futuro se vea en la pantalla y no en producción.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from buscador import config, rules  # noqa: E402

PERFIL = {
    "habilidades": [
        {"nombre": "SQL", "nivel": "demostrada"},
        {"nombre": "Python", "nivel": "demostrada"},
        {"nombre": "Excel", "nivel": "demostrada"},
        {"nombre": "Power BI", "nivel": "demostrada"},
        {"nombre": "PostgreSQL", "nivel": "demostrada"},
        {"nombre": "Google Sheets", "nivel": "demostrada"},
        {"nombre": "ETL", "nivel": "demostrada"},
    ],
    "idioma": {"ingles": "B1", "espanol": "nativo"},
    "experiencia": {"anios": 1, "nivel": "junior"},
    "territorio": {
        "residencia": "Argentina",
        "remoto": True,
        "remoto_obligatorio": True,
        "presencial": ["La Plata"],
        "acepta_hibrido_en_zona": True,
    },
    "categorias": [
        "Data Analyst", "Business Analyst", "BI Analyst", "Reporting Analyst",
        "SQL Analyst", "Data Operations", "Research Analyst", "VA/Data Entry",
        "Customer Support",
    ],
    "formacion": [],
    "salario": {},
}

#: Cuerpo de un puesto de soporte/back office con señales profesionales claras.
CUERPO_SOPORTE = (
    "You will answer customer tickets in Zendesk, update the CRM, handle the "
    "inbox and schedule meetings for the team. We use Power BI dashboards to "
    "follow volume. Excel is required for the weekly report."
)

BASE = {
    "titulo": "Data Analyst",
    "empresa": "Empresa Sintetica",
    "region": "Anywhere in the World",
    "texto": "SQL required. Excel required. Python required. Remote.",
    "salario": None,
    "seniority": None,
    "publicado_en": "2026-11-05T00:00:00Z",
    "expira_en": None,
    "tipo_contrato": None,
}


def evaluar(perfil=None, **cambios):
    return rules.evaluar(dict(BASE, **cambios), perfil or PERFIL)


def razones(e, tipo, efecto):
    return [r.get("texto", "") for r in e.razones
            if r.get("tipo") == tipo and r.get("efecto") == efecto]


# --- C01 · títulos afines que la taxonomía no reconocía --------------------

@pytest.mark.parametrize("titulo,esperada", [
    ("Helpdesk Agent", "Customer Support"),
    ("CX Associate", "Customer Support"),
    ("Executive Assistant", "VA/Data Entry"),
    ("Office Administrator", "VA/Data Entry"),
    ("CRM Specialist", "Data Operations"),
    ("Operations Associate", "VA/Data Entry"),
    ("Billing Specialist", "VA/Data Entry"),
    ("Data Entry Clerk", "VA/Data Entry"),
])
def test_c01_titulos_afines_se_reconocen(titulo, esperada):
    categoria, _, origen = rules.categoria_de(titulo, CUERPO_SOPORTE, PERFIL["categorias"])
    assert categoria == esperada
    assert origen == "titulo"


@pytest.mark.parametrize("titulo", [
    "Paid Ads Specialist", "Senior Software Engineer", "Registered Nurse",
    "Marketing Coordinator", "Account Executive", "Sales Development Representative",
])
def test_c01_controles_negativos_siguen_fuera(titulo):
    categoria, motivo, origen = rules.categoria_de(titulo, CUERPO_SOPORTE,
                                                  PERFIL["categorias"])
    assert categoria is None
    assert origen == "ninguno"


def test_c01_un_operations_associate_de_deposito_no_es_back_office():
    categoria, _, _ = rules.categoria_de(
        "Operations Associate",
        "Manage warehouse inventory, forklift operation and shipping schedules.",
        PERFIL["categorias"])
    assert categoria is None


# --- C02 · «power bi» en el cuerpo no secuestra la categoría --------------

def test_c02_power_bi_no_convierte_soporte_en_bi_analyst():
    e = evaluar(titulo="Helpdesk Agent", texto=CUERPO_SOPORTE)
    assert e.categoria == "Customer Support"
    assert e.categoria != "BI Analyst"


def test_c02_power_bi_sigue_valiendo_para_un_titulo_de_datos():
    e = evaluar(titulo="Reporting", texto="We build Power BI dashboards and reports.")
    assert e.categoria == "BI Analyst"
    assert e.origen_categoria == "texto"


# --- C03 · indicios de cuerpo para VA, sin promoción automática -----------

def test_c03_el_cuerpo_administrativo_reconoce_va_pero_no_la_promueve():
    e = evaluar(titulo="Assistant", texto=(
        "Administrative support: manage the inbox, scheduling and bookkeeping. "
        "Data entry in Excel."))
    assert e.categoria == "VA/Data Entry"
    assert e.origen_categoria == "texto"
    # Indicio ≠ categoría plena: queda en revisión, nunca elegible sola.
    assert e.elegibilidad == "doubtful"


def test_c03_data_entry_suelto_en_un_aviso_comercial_no_alcanza():
    categoria, _, _ = rules.categoria_de(
        "Paid Ads Specialist", "Data entry of campaign results in Meta.", ["VA/Data Entry"])
    assert categoria is None


# --- C04 · categoria_fuente y tipo_contrato no se confunden ---------------

def test_c04_la_categoria_de_la_fuente_no_es_una_modalidad():
    """«Customer Service» como etiqueta de fuente no puede volverse modalidad."""
    sin_etiqueta = evaluar(titulo="Data Analyst", region="Argentina")
    con_etiqueta = evaluar(titulo="Data Analyst", region="Argentina",
                           categoria_fuente="Customer Service")
    assert con_etiqueta.modalidad == sin_etiqueta.modalidad
    assert con_etiqueta.requisitos["categoria_fuente"] == "Customer Service"
    assert con_etiqueta.requisitos["categoria_corroborada"] is False


def test_c04_la_etiqueta_corrobora_cuando_coincide():
    e = evaluar(titulo="Data Analyst", region="Argentina", categoria_fuente="Data Analysis")
    assert e.requisitos["categoria_corroborada"] is True


def test_c04_la_etiqueta_de_la_fuente_no_decide_la_categoria():
    """Un aviso de ventas con etiqueta «Data Analyst» sigue sin categoría."""
    e = evaluar(titulo="Paid Ads Specialist", texto="Run Meta ads. Excel required.",
                categoria_fuente="Data Analyst")
    assert e.categoria is None
    assert e.elegibilidad == "incompatible"


# --- C05 · el perfil manda sobre las categorías del código ----------------

def test_c05_una_categoria_fuera_del_perfil_no_se_asigna():
    sin_datos = dict(PERFIL)
    sin_datos["categorias"] = [c for c in PERFIL["categorias"] if c != "Customer Support"]
    e = evaluar(perfil=sin_datos, titulo="Customer Support Specialist")
    assert e.categoria is None
    assert "no habilita" in e.motivo_elegibilidad


def test_c05_sin_categorias_declaradas_se_usan_todas():
    sin_categorias = {k: v for k, v in PERFIL.items() if k != "categorias"}
    e = evaluar(perfil=sin_categorias, titulo="Customer Support Specialist")
    assert e.categoria == "Customer Support"


def test_c05_categoria_desconocida_se_informa_sin_romper():
    raro = dict(PERFIL)
    raro["categorias"] = PERFIL["categorias"] + ["Astronauta de datos"]
    e = evaluar(perfil=raro, titulo="Data Analyst")
    assert e.categoria == "Data Analyst"
    assert e.requisitos["categorias_no_reconocidas"] == ["Astronauta de datos"]


# --- C06 · habilidades: requeridas, declaradas y evidencia ----------------

def test_c06_habilidades_no_declaradas_no_regalan_puntos():
    e = evaluar(titulo="Data Entry Clerk", texto=(
        "Data entry in Zendesk and CRM. Typing and scheduling."))
    habilidades = next(c for c in e.componentes if c.nombre == "habilidades")
    assert habilidades.obtenido == 0
    assert habilidades.estado == "parcial"
    assert e.requisitos["skills_informativas"]
    assert not e.requisitos["skills_faltantes"]


def test_c06_una_brecha_real_sigue_restando():
    e = evaluar(texto="SQL required. Tableau required. Remote.")
    faltantes = {i["skill"] for i in e.requisitos["skills_faltantes"]}
    assert "tableau" in faltantes


# --- E01 · título con alternativa explícita -------------------------------

def test_e01_titulo_o_experiencia_equivalente_no_descarta():
    e = evaluar(texto="SQL required. Excel required. Bachelor's degree or equivalent "
                      "experience. Remote.")
    assert e.requisitos["estado_formacion"] == "duda"
    assert e.elegibilidad != "incompatible"
    assert any("equivalente" in t for t in razones(e, "formacion", "duda"))


def test_e01_titulo_estrictamente_obligatorio_sigue_excluyendo():
    e = evaluar(texto="SQL required. Excel required. Bachelor's degree strictly required.")
    assert e.requisitos["estado_formacion"] == "excluye"
    assert e.elegibilidad == "incompatible"


# --- E02 · gestión de cuentas no es gestión de personas -------------------

def test_e02_customer_success_manager_sin_equipo_no_marca_gestion():
    e = evaluar(titulo="Customer Success Manager", texto=CUERPO_SOPORTE)
    assert e.requisitos["estado_experiencia"] != "duda"


def test_e02_manager_con_equipo_a_cargo_si_marca_gestion():
    e = evaluar(titulo="Customer Success Manager", texto=(
        CUERPO_SOPORTE + " You will have 5 direct reports and run performance reviews."))
    assert e.requisitos["estado_experiencia"] == "duda"
    assert e.elegibilidad == "doubtful"


# --- L02 · inglés fluido no se asume ------------------------------

@pytest.mark.parametrize("nivel", ["B1", "B2"])
def test_l02_ingles_fluido_no_se_promueve(nivel):
    perfil = dict(PERFIL)
    perfil["idioma"] = {"ingles": nivel, "espanol": "nativo"}
    e = evaluar(perfil=perfil, titulo="Customer Support Specialist",
                texto="SQL required. Excel required. Fluent English is required.")
    assert e.requisitos["estado_idioma"] == "parcial"
    assert e.elegibilidad == "doubtful"


def test_l02_b1_no_aprueba_b2_explicito():
    e = evaluar(texto="SQL required. Excel required. English B2 required. Remote.")
    assert e.requisitos["estado_idioma"] == "parcial"


def test_l02_b1_aprueba_b1_explicito():
    e = evaluar(texto="SQL required. Excel required. English B1 required. Remote.")
    assert e.requisitos["estado_idioma"] == "cumplido"


# --- S01 · la alerta legítima es alcanzable -------------------------------

def test_s01_una_oferta_completa_puede_superar_el_umbral():
    """Techos reales sin experiencia ni formación declaradas: 69 y 73 sobre 100.

    Con el umbral anterior (75) ninguna oferta de este tipo podía alertar nunca:
    el máximo alcanzable era 73 y, si el aviso está en inglés sin declarar nivel,
    69. El umbral se calibró; el puntaje no se toca.
    """
    sin_nivel = evaluar(texto=("SQL required. Excel required. Python required. "
                               "Remote. Build dashboards, reports and KPIs."))
    assert sin_nivel.elegibilidad == "eligible"
    assert sin_nivel.compatibilidad == 69.0
    assert sin_nivel.compatibilidad > config.UMBRAL_AVISO

    con_nivel = evaluar(texto=("SQL required. Excel required. Python required. "
                               "English B1 required. Remote. Build dashboards, "
                               "reports and KPIs."))
    assert con_nivel.compatibilidad == 73.0
    assert con_nivel.compatibilidad > config.UMBRAL_AVISO


def test_s01_el_umbral_es_configurable():
    from buscador import worker
    assert worker._corresponde_aviso(
        rules.Evaluacion(elegibilidad="eligible", compatibilidad=71.0,
                         confianza="alta", vigencia="open", cobertura=0.8), 70.0)
    assert not worker._corresponde_aviso(
        rules.Evaluacion(elegibilidad="eligible", compatibilidad=71.0,
                         confianza="alta", vigencia="open", cobertura=0.8), 75.0)


# --- S02 · la ausencia no puntúa ni alerta --------------------------------

def test_s02_un_aviso_vacio_no_llega_al_maximo():
    e = evaluar(titulo="Data Analyst", texto="Remote.")
    assert e.compatibilidad is None or e.compatibilidad < 40
    assert e.compatibilidad != 100
    assert not rules.evaluar(dict(BASE, titulo="Data Analyst", texto="Remote."),
                             PERFIL).elegibilidad == "eligible"


def test_s02_la_cobertura_se_informa():
    e = evaluar(texto="SQL required. Excel required. Remote.")
    assert 0 < e.cobertura < 1
    assert e.requisitos["escala_puntaje"] == "aplicable"


def test_s02_sin_habilidades_no_hay_puntaje():
    e = evaluar(titulo="Data Analyst", texto="Remote. Join our team.")
    assert e.compatibilidad is None
    assert e.requisitos["escala_puntaje"] == "sin_datos"


# --- Fase 1G · defectos reproducidos el 2026-11-10 -------------------------

@pytest.mark.parametrize("titulo", [
    "HR Assistant (Argentina)",
    "Accounting Assistant",
    "Financial Analyst",
    "Payroll Specialist",
])
def test_g1_rr_hh_y_finanzas_no_son_reporting_analyst(titulo):
    """«reporting» en el cuerpo de un aviso de RR. HH. no da categoría.

    Antes: HR Assistant y Accounting Assistant quedaban como Reporting Analyst
    porque el aviso decía «reporting». RR. HH. y finanzas no son ninguna de las
    diez categorías del perfil.
    """
    categoria, motivo, _ = rules.categoria_de(
        titulo, "Support the team with payroll, HR systems and monthly reporting.",
        PERFIL["categorias"])
    assert categoria is None
    assert "fuera de las categorías" in motivo


def test_g1_un_titulo_de_datos_con_area_sigue_siendo_data_analyst():
    """Las pistas de título ganan: «HR Data Analyst» es Data Analyst."""
    categoria, _, origen = rules.categoria_de(
        "HR Data Analyst", "Reporting and dashboards. SQL required.",
        PERFIL["categorias"])
    assert categoria == "Data Analyst"
    assert origen == "titulo"


def test_g1_reporting_analyst_de_titulo_sigue_funcionando():
    categoria, _, origen = rules.categoria_de(
        "Reporting Analyst", "Weekly reporting and dashboards.",
        PERFIL["categorias"])
    assert categoria == "Reporting Analyst"
    assert origen == "titulo"


def test_g1_reporting_generico_no_da_categoria_sin_titulo_afin():
    categoria, _, _ = rules.categoria_de(
        "Partner Operations Manager", "Own reporting and monthly packs.",
        PERFIL["categorias"])
    assert categoria is None


def test_g2_mid_level_declarado_no_es_responsabilidad_de_gestion():
    """Un «Mid-level» de la fuente es una banda, no gestión de personas.

    Antes el campo `seniority` de Himalayas («Mid-level») se normalizaba a
    «mid level» y el motor informaba «el título implica responsabilidad de
    gestión» sobre un Operations Assistant.
    """
    e = evaluar(titulo="Operations Assistant (Construction Support)",
                texto="Administrative support. C1 English required.",
                seniority="Mid-level")
    assert e.requisitos["estado_experiencia"] == "duda"
    assert any("nivel mid level" in i for i in e.incertidumbres)
    assert not any("gestión" in i for i in e.incertidumbres)


def test_g2_la_gestion_real_sigue_marcandose():
    e = evaluar(titulo="Customer Success Manager", texto=(
        CUERPO_SOPORTE + " You will have 5 direct reports and run performance reviews."),
        seniority="Mid-level")
    assert e.requisitos["estado_experiencia"] == "duda"
    assert any("gestión" in i for i in e.incertidumbres)


def test_g2_mentor_y_coaching_no_son_gestion_de_personas():
    e = evaluar(titulo="Customer Success Manager", texto=(
        CUERPO_SOPORTE + " Mentor junior teammates and coach the team on best practices."),
        seniority=None)
    assert not any("gestión" in i for i in e.incertidumbres)

