"""Reglas 1.1.0: la experiencia declarada no excluye por sí sola (excepción por competencias)."""

from __future__ import annotations

from buscador import rules
from buscador.perfil import PERFIL_EJEMPLO as PERFIL_DEMO

BASE = {
    "titulo": "Data Analyst",
    "texto": "SQL required. Python desirable. Excel.",
    "region": "Anywhere in the World",
    "seniority": None,
    "salario": None,
    "publicado_en": "2026-11-01T00:00:00Z",
    "expira_en": None,
}


def evaluar(**cambios):
    oferta = dict(BASE)
    oferta.update(cambios)
    return rules.evaluar(oferta, PERFIL_DEMO)


def test_tres_anios_con_competencias_no_excluye():
    """Pedir 3 años no descarta la oferta si el perfil cubre las habilidades."""
    e = evaluar(texto="SQL required. Python required. Excel required. 3+ years of experience.")
    assert e.elegibilidad == "eligible"
    assert e.excepcion is True
    assert e.anios_requeridos == 3
    assert any("excepción por competencias" in r["texto"] for r in e.razones)
    experiencia = next(c for c in e.componentes if c.nombre == "experiencia")
    assert experiencia.obtenido == 12


def test_tres_anios_sin_competencias_va_a_dudosas():
    e = evaluar(texto="SAP required. Oracle required. 3+ years of experience.")
    assert e.elegibilidad == "doubtful"
    assert e.excepcion is False
    assert any("años" in i for i in e.decisivas)


def test_ocho_anios_excluye():
    e = evaluar(texto="SQL required. 8+ years of experience.")
    assert e.elegibilidad == "incompatible"


def test_un_anio_no_es_obstaculo():
    e = evaluar(texto="SQL required. 1 year of experience.")
    assert e.elegibilidad == "eligible"
    assert e.excepcion is False


def test_titulo_senior_sigue_excluyendo():
    assert evaluar(titulo="Senior Data Analyst").elegibilidad == "incompatible"
    assert evaluar(titulo="Data Analyst Lead").elegibilidad == "incompatible"


def test_seniority_intermedio_declarado_va_a_dudosas():
    e = evaluar(seniority="Mid Level")
    assert e.elegibilidad == "doubtful"


def test_modalidad_remota_se_detecta():
    assert evaluar(region="Remote worldwide").modalidad == "remote"
    assert evaluar(region=None, texto="This is a fully remote role. SQL required.").modalidad == "remote"
    assert evaluar(region="La Plata, Argentina").modalidad == "onsite"
    assert evaluar(region=None, texto="SQL required.").modalidad == "unknown"


def test_modalidad_hibrida_no_se_confunde_con_remota():
    assert evaluar(region="Buenos Aires (hybrid)").modalidad == "hybrid"


def test_anios_requeridos_toma_el_minimo():
    assert rules.anios_requeridos("2+ years of experience, ideally 5 years") == 2
    assert rules.anios_requeridos("sin requisitos de experiencia") is None


def test_orden_prioriza_remoto_ante_igual_puntaje():
    remota = {"id": "A", "publicado_en": "2026-11-01T00:00:00Z", "salario": None, "fuente_principal": "F01"}
    presencial = {"id": "B", "publicado_en": "2026-11-01T00:00:00Z", "salario": None, "fuente_principal": "F01"}
    orden = sorted(
        [(remota, {"score": 80, "vigencia": "open", "modalidad": "remote"}),
         (presencial, {"score": 80, "vigencia": "open", "modalidad": "onsite"})],
        key=lambda par: rules.clave_orden(par[1], par[0]),
    )
    assert orden[0][0]["id"] == "A"


def test_categoria_reconoce_analytics_engineer():
    categoria, _, _ = rules.categoria_de("Analytics Engineer", "")
    assert categoria == "Data Scientist"


def test_cobertura_baja_sigue_impidiendo_alerta():
    e = evaluar(texto="Join our growing team.")
    assert e.elegibilidad == "doubtful"
    assert e.cobertura < 0.7
