"""Reglas de elegibilidad y orden (P07)."""

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


def test_territorio_excluyente_es_incompatible():
    e = evaluar(region="USA Only")
    assert e.elegibilidad == "incompatible"
    assert e.score is None
    assert any("restringe la ubicación" in r["texto"] for r in e.razones)


def test_territorio_desconocido_va_a_dudosas():
    e = evaluar(region=None, texto="SQL required. Remote.")
    assert e.elegibilidad == "doubtful"
    assert any("territorio" in i for i in e.decisivas)


def test_titulo_terminado_obligatorio_excluye():
    e = evaluar(texto="Bachelor degree required. SQL required.")
    assert e.elegibilidad == "incompatible"


def test_seniority_superior_excluye():
    assert evaluar(titulo="Senior Data Analyst").elegibilidad == "incompatible"
    assert evaluar(titulo="Data Analyst Lead").elegibilidad == "incompatible"


def test_salario_ausente_no_excluye():
    e = evaluar(salario=None)
    assert e.elegibilidad == "eligible"
    assert e.score is not None


def test_cobertura_baja_impide_alerta():
    e = evaluar(texto="Join our growing team.")
    assert e.elegibilidad == "doubtful"
    assert e.cobertura < 0.7
    assert any("cobertura" in i for i in e.decisivas)


def test_componentes_no_aplicables_se_excluyen_del_denominador():
    e = evaluar(texto="SQL required. Python desirable. Excel.")
    habilidades = next(c for c in e.componentes if c.nombre == "habilidades")
    assert habilidades.aplicable
    assert round(habilidades.obtenido, 1) == 40.0


def test_orden_prioriza_compatibilidad_sobre_salario():
    """Contraejemplo P07: mejor compatibilidad y peor salario va primero."""
    mejor = {"id": "A", "publicado_en": "2026-11-01T00:00:00Z", "salario": {"min": 500}, "fuente_principal": "F01"}
    peor = {"id": "B", "publicado_en": "2026-11-01T00:00:00Z", "salario": {"min": 5000}, "fuente_principal": "F01"}
    orden = sorted(
        [(mejor, {"score": 90, "vigencia": "open"}), (peor, {"score": 70, "vigencia": "open"})],
        key=lambda par: rules.clave_orden(par[1], par[0]),
    )
    assert orden[0][0]["id"] == "A"


def test_vigencia_cerrada_no_alerta():
    e = evaluar(expira_en="2026-01-01T00:00:00Z")
    assert e.vigencia == "closed"


def test_categoria_prioriza_titulo_sobre_cuerpo():
    """El título manda; un rol de otro rubro no se reclasifica por el cuerpo."""
    categoria, _, origen = rules.categoria_de(
        "Warehouse Operator", "We also have a data analyst in the team."
    )
    assert categoria is None
    assert origen == "ninguno"

    categoria2, _, origen2 = rules.categoria_de("Junior Data Analyst", "")
    assert categoria2 == "Data Analyst"
    assert origen2 == "titulo"

    categoria3, _, origen3 = rules.categoria_de("Operations", "buscamos un data analyst")
    assert categoria3 == "Data Analyst"
    assert origen3 == "texto"
