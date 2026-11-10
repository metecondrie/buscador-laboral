"""Modelo de puntaje de rules-3.0.0: sólo se puntúa lo que se puede comprobar.

La regla que ordena todo el archivo: **no se otorgan puntos por ausencia de
información**. Cada componente declara uno de cuatro estados y la nota se calcula
con los que tienen datos.
"""

from __future__ import annotations

import pytest

from buscador import rules
from buscador.perfil import PERFIL_EJEMPLO

BASE = {
    "titulo": "Data Analyst",
    "texto": "SQL required. Excel required. Python required. Remote.",
    "region": "Anywhere in the World",
    "seniority": None,
    "salario": None,
    "publicado_en": "2026-11-05T00:00:00Z",
    "expira_en": None,
}


def evaluar(**cambios):
    return rules.evaluar(dict(BASE, **cambios), PERFIL_EJEMPLO)


def comp(e, nombre):
    return next(c for c in e.componentes if c.nombre == nombre)


# --- los cuatro estados -----------------------------------------------------

def test_requisito_cumplido_suma():
    e = evaluar(texto="SQL required. Excel required. Python required. "
                      "2 years of experience. Remote.")
    experiencia = comp(e, "experiencia")
    assert experiencia.estado in {"cumplido", "parcial"}
    assert experiencia.obtenido > 0


def test_requisito_incumplido_no_suma_y_excluye():
    e = evaluar(texto="Bachelor degree required. SQL required. Remote.")
    assert e.elegibilidad == "incompatible"
    assert e.compatibilidad is None
    assert e.requisitos["estado_formacion"] == "excluye"


def test_requisito_desconocido_no_otorga_puntos():
    """Sin fecha ni experiencia declaradas, esos componentes valen 0."""
    e = evaluar(texto="SQL required. Excel required. Python required. Remote.")
    for nombre in ("experiencia", "formacion"):
        c = comp(e, nombre)
        assert c.estado == "sin_datos", nombre
        assert c.obtenido == 0, nombre


def test_requisito_no_aplicable_sale_del_denominador():
    """Un aviso en español no exige inglés: el componente no cuenta."""
    e = evaluar(
        titulo="Analista de Datos",
        texto=("Buscamos analista de datos. Se requiere SQL y Excel. "
               "Tareas: reportes semanales, dashboards y métricas. Modalidad remota. "
               "Es un puesto de nivel inicial, sin experiencia previa."),
        region="Argentina",
    )
    idioma = comp(e, "idioma")
    assert idioma.estado == "no_aplicable"
    assert not idioma.aplicable
    assert e.requisitos["idioma_aviso"] == "es"
    # El denominador baja a 92: la nota no se castiga por un requisito inexistente.
    assert e.compatibilidad is not None


def test_los_cuatro_estados_son_distintos():
    """El bug original: «no contradice» se contaba como «cumple»."""
    sin_datos = evaluar(texto="SQL required. Excel required. Python required. Remote.")
    assert comp(sin_datos, "experiencia").estado == "sin_datos"
    assert comp(sin_datos, "experiencia").obtenido == 0

    con_datos = evaluar(texto="SQL required. Excel required. Python required. "
                              "1 year of experience. Remote.")
    assert comp(con_datos, "experiencia").estado == "cumplido"
    assert comp(con_datos, "experiencia").obtenido == 20
    assert con_datos.compatibilidad > sin_datos.compatibilidad


# --- categoría y tareas -----------------------------------------------------

def test_titulo_solo_no_da_los_veinticinco():
    solo_titulo = evaluar(titulo="Data Analyst", texto="SQL required. Remote.")
    assert comp(solo_titulo, "categoria_tareas").obtenido == 15
    assert comp(solo_titulo, "categoria_tareas").estado == "parcial"
    assert any("no describe tareas" in i for i in solo_titulo.incertidumbres)

    con_tareas = evaluar(
        titulo="Data Analyst",
        texto="SQL required. Construir dashboards, reportes semanales y métricas para el equipo.",
    )
    assert comp(con_tareas, "categoria_tareas").obtenido == 25
    assert comp(con_tareas, "categoria_tareas").estado == "cumplido"


def test_categoria_solo_por_cuerpo_no_da_puntaje_pleno():
    e = evaluar(titulo="Operations", texto="Buscamos un data analyst. Dashboards y reportes.")
    assert e.origen_categoria == "texto"
    assert comp(e, "categoria_tareas").obtenido == 10


# --- habilidades ------------------------------------------------------------

def test_una_sola_habilidad_no_llena_el_componente():
    una = evaluar(texto="Excel required. Remote.")
    tres = evaluar(texto="SQL required. Excel required. Python required. Remote.")
    assert comp(una, "habilidades").obtenido <= 40 / 3 + 0.1
    assert comp(tres, "habilidades").obtenido == 40
    assert any("poco representativa" in i for i in una.incertidumbres)


def test_sin_habilidades_no_hay_puntaje():
    e = evaluar(texto="Join our growing team. Remote.")
    assert e.compatibilidad is None
    assert comp(e, "habilidades").estado == "sin_datos"


# --- idioma -----------------------------------------------------------------

def test_idioma_que_el_perfil_no_habla_excluye():
    e = evaluar(titulo="Data Analyst (German required)", texto="SQL. Remote.")
    assert e.elegibilidad == "incompatible"
    assert "german" in e.motivo_elegibilidad.lower()
    assert e.requisitos["estado_idioma"] == "incumplido"


def test_ingles_exigido_y_cumplido_suma():
    e = evaluar(texto="SQL required. Excel required. Python required. "
                      "English B2 required. Remote.")
    assert comp(e, "idioma").estado == "cumplido"
    assert comp(e, "idioma").obtenido == 8


def test_ingles_fluido_deja_dudosa():
    e = evaluar(texto="SQL required. Excel required. Fluent English required. Remote.")
    assert e.elegibilidad == "doubtful"
    assert comp(e, "idioma").obtenido == 0


def test_aviso_en_ingles_sin_nivel_da_credito_parcial():
    e = evaluar(texto="We are looking for a data analyst to join our team. "
                      "You will build dashboards and reports. SQL and Excel required. "
                      "This is a fully remote position.")
    assert comp(e, "idioma").estado == "parcial"
    assert 0 < comp(e, "idioma").obtenido < 8


# --- fórmula ----------------------------------------------------------------

def test_la_formula_es_suma_sobre_base_sin_no_aplicables():
    e = evaluar(texto="SQL required. Excel required. Python required. "
                      "English B2 required. 1 year of experience. Remote. "
                      "Construir dashboards y reportes.")
    base = 100 - sum(c.maximo for c in e.componentes if not c.aplicable)
    obtenido = sum(c.obtenido for c in e.componentes if c.aplicable)
    assert e.compatibilidad == round(100 * obtenido / base, 1)


def test_cobertura_refleja_la_parte_con_datos():
    denso = evaluar(texto="SQL required. Excel required. Python required. "
                          "1 year of experience. English B2 required. Remote. "
                          "Dashboards y reportes.")
    vacio = evaluar(texto="Join us. Remote.")
    assert denso.cobertura > vacio.cobertura
    assert 0 <= vacio.cobertura <= 1


def test_la_ausencia_de_datos_baja_la_confianza():
    e = evaluar(texto="SQL required. Excel required. Python required. Remote.")
    assert e.confianza in {"media", "baja"}


# --- territorio y vigencia --------------------------------------------------

@pytest.mark.parametrize("region,alcance,esperado", [
    ("Worldwide", "mundial", "eligible"),
    ("Anywhere in the World", "mundial", "eligible"),
    ("Argentina", "argentina", "eligible"),
    ("Remote", "desconocido", "doubtful"),
])
def test_alcance_territorial_se_declara(region, alcance, esperado):
    e = evaluar(region=region)
    assert e.requisitos["alcance_territorial"] == alcance
    assert e.elegibilidad == esperado


def test_restriccion_explicita_en_el_cuerpo_gana_a_la_region_permisiva():
    e = evaluar(region="Anywhere in the World",
                texto="Applicants must be eligible to live and work in the US. SQL.")
    assert e.elegibilidad == "incompatible"
    assert e.requisitos["alcance_territorial"] == "restringido"


def test_hibrido_fuera_de_zona_excluye():
    e = evaluar(region="Berlin, Germany", texto="Hybrid role, 3 days onsite. SQL.")
    assert e.elegibilidad == "incompatible"
    motivo = e.motivo_elegibilidad.lower()
    # Fuera de su zona, el motivo puede ser territorial o de modalidad.
    assert any(p in motivo for p in ("presencial", "híbrido", "restringe", "ubicación"))


def test_viajes_dejan_dudosa_no_incompatible():
    e = evaluar(texto="SQL required. Excel required. Python required. "
                      "This role may require travel to our offices. Remote.")
    assert e.elegibilidad == "doubtful"
    assert e.requisitos["estado_laboral"] == "duda"


def test_reubicacion_excluye():
    e = evaluar(texto="SQL. Candidates must relocate to Austin. ")
    assert e.elegibilidad == "incompatible"


def test_vigencia_separa_publicacion_de_disponibilidad():
    reciente = evaluar(publicado_en="2026-11-05T00:00:00Z")
    viejo = evaluar(publicado_en="2025-06-01T00:00:00Z")
    assert reciente.vigencia == "open"
    # V01: `stale` es un estado propio: ni abierto sin evidencia ni cerrado por
    # antigüedad. La fuente lo conserva y la oferta va a revisión.
    assert viejo.vigencia == "stale"
    assert viejo.requisitos["publicado_en"] == "2025-06-01T00:00:00Z"


def test_vencimiento_explicito_manda():
    e = evaluar(expira_en="2026-01-01T00:00:00Z")
    assert e.vigencia == "closed"
