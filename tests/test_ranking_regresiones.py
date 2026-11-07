"""Regresiones del ranking (rules-2.0.0).

Cada prueba reproduce un error concreto que el usuario reportó sobre datos reales y
fija el comportamiento corregido. Si alguna vuelve a fallar, es que el error
volvió.
"""

from __future__ import annotations

from buscador import rules
from buscador.perfil import PERFIL_EJEMPLO

BASE = {
    "titulo": "Data Analyst",
    "empresa": "Acme",
    "texto": "We need SQL and Excel. Fully remote.",
    "region": "Anywhere in the World",
    "seniority": None,
    "salario": None,
    "publicado_en": "2026-11-01T00:00:00Z",
    "expira_en": None,
}


def evaluar(**cambios):
    oferta = dict(BASE)
    oferta.update(cambios)
    return rules.evaluar(oferta, PERFIL_EJEMPLO)


# 1. «Risk&AI Manager» aparecía como Customer Support elegible por el cuerpo.
def test_manager_con_mencion_de_soporte_no_es_elegible():
    """Era «Customer Support elegible». Ahora ni siquiera entra a las categorías."""
    e = evaluar(
        titulo="Risk & AI Manager",
        texto="You will coordinate our customer support team and report risks. Remote.",
    )
    assert e.categoria is None
    assert e.elegibilidad == "incompatible"
    assert e.compatibilidad is None


def test_manager_de_soporte_con_titulo_afin_queda_dudoso():
    e = evaluar(
        titulo="Support Operations Manager",
        texto="Lead our customer support team. Remote.",
    )
    assert e.categoria == "Customer Support"
    assert e.elegibilidad == "doubtful"
    assert any("gestión" in r["texto"] for r in e.razones)


# 2. Dudosas con 100/100 aunque hubiera 0 % de habilidades.
def test_sin_habilidades_no_hay_puntaje():
    e = evaluar(texto="Join our growing team. 4+ years of experience. Remote.")
    assert e.compatibilidad is None
    assert e.elegibilidad == "doubtful"
    assert any("información insuficiente" in i for i in e.decisivas)
    habilidades = next(c for c in e.componentes if c.nombre == "habilidades")
    assert habilidades.estado == "sin_datos"


# 3. Presencial en Seattle, Berlín o Múnich con puntaje alto.
def test_presencial_fuera_de_zona_es_incompatible():
    for region in ("Seattle, WA", "Berlin, Germany", "Munich, Germany"):
        e = evaluar(region=region, texto="We need SQL and Excel. On-site role.")
        assert e.elegibilidad == "incompatible", region
        assert e.compatibilidad is None, region
        motivo = e.motivo_elegibilidad.lower()
        assert any(p in motivo for p in ("presencial", "restringe", "ubicación",
                                         "estado de", "ciudad de", "estados unidos")), region


def test_presencial_en_la_plata_queda_dudoso():
    e = evaluar(region="La Plata, Buenos Aires", texto="We need SQL and Excel.")
    assert e.elegibilidad == "doubtful"
    assert e.modalidad == "onsite"
    assert e.motivo_elegibilidad


# 4. «Software Engineer Infrastructure» caía en VA/Data Entry por «data entry».
def test_ingenieria_no_cae_en_va_por_mencion_suelta():
    e = evaluar(
        titulo="Software Engineer Infrastructure",
        texto="You will also support data entry workflows and internal tools. Remote.",
    )
    assert e.categoria is None
    assert e.origen_categoria == "ninguno"
    assert e.elegibilidad == "incompatible"
    assert "fuera de las categorías" in e.motivo_elegibilidad


# 5. Avisos de 2025 abiertos sin comprobación reciente.
def test_aviso_viejo_no_se_declara_abierto():
    e = evaluar(publicado_en="2025-06-01T00:00:00Z", expira_en=None)
    assert e.vigencia == "unknown"
    assert e.confianza != "alta"


def test_aviso_reciente_si_es_abierto():
    e = evaluar(publicado_en="2026-11-01T00:00:00Z")
    assert e.vigencia == "open"


# 6. País específico en el título con región «Anywhere in the World».
def test_pais_en_el_titulo_anula_el_anywhere():
    e = evaluar(titulo="Data Analyst (Remote - Canada)", region="Anywhere in the World")
    assert e.elegibilidad == "incompatible"
    assert "canada" in e.motivo_elegibilidad.lower()


def test_pais_en_el_titulo_con_region_vacia():
    e = evaluar(titulo="Data Analyst - US only", region=None)
    assert e.elegibilidad == "incompatible"


# 7. Salario sin moneda ni período mostrado como comparable.
def test_salario_sin_moneda_no_es_comparable():
    e = evaluar(salario={"min": 1000, "max": 2000, "moneda": None, "periodo": None})
    assert e.requisitos["salario_comparable"] is False


def test_salario_completo_es_comparable():
    e = evaluar(salario={"min": 1000, "max": 2000, "moneda": "USD", "periodo": "month"})
    assert e.requisitos["salario_comparable"] is True


# El orden no puede poner arriba un puesto no elegible con mejor tema.
def test_orden_no_prioriza_tematico_sobre_elegible():
    remoto = {"id": "R", "publicado_en": "2026-11-01T00:00:00Z", "salario": None,
              "fuente_principal": "F01", "modalidad": "remote"}
    presencial = {"id": "P", "publicado_en": "2026-11-01T00:00:00Z", "salario": None,
                  "fuente_principal": "F01", "modalidad": "onsite"}
    orden = sorted(
        [
            (presencial, {"elegibilidad": "incompatible", "score": 95, "modalidad": "onsite"}),
            (remoto, {"elegibilidad": "eligible", "score": 70, "modalidad": "remote"}),
        ],
        key=lambda par: rules.clave_orden(par[1], par[0]),
    )
    assert orden[0][0]["id"] == "R"


# Las tres dimensiones son independientes y siempre están presentes.
def test_tres_dimensiones_presentes():
    e = evaluar()
    assert e.elegibilidad in {"eligible", "doubtful", "incompatible"}
    assert e.confianza in {"alta", "media", "baja"}
    assert e.compatibilidad is None or 0 <= e.compatibilidad <= 100
    assert e.motivo_elegibilidad


def test_seniority_en_titulo_no_es_junior():
    assert evaluar(titulo="Senior Data Analyst").elegibilidad == "incompatible"
    # Con categoría clara y cargo de gestión: no es junior, pero tampoco se descarta solo.
    assert evaluar(titulo="Data Analyst Manager").elegibilidad == "doubtful"
    assert evaluar(titulo="Customer Support Manager").elegibilidad == "doubtful"
    assert evaluar(titulo="Junior Data Analyst").elegibilidad == "eligible"


def test_perfil_de_ejemplo_no_declara_titulos_obtenidos():
    for estudio in PERFIL_EJEMPLO["formacion"]:
        if not estudio["acreditado"]:
            assert "no finalizada" in estudio["estado"] or "pendientes" in estudio["estado"]


def test_perfil_de_ejemplo_marca_remoto_obligatorio():
    assert PERFIL_EJEMPLO["territorio"]["remoto_obligatorio"] is True
    assert PERFIL_EJEMPLO["salario"]["estado"] == "pendiente_ratificacion"


# 8. «Paid Ads Specialist» caía en Reporting Analyst por mencionar «reporting».
def test_titulo_no_afin_no_hereda_categoria_del_cuerpo():
    e = evaluar(
        titulo="Paid Ads Specialist",
        texto="You will own reporting dashboards and campaign analysis. Remote.",
    )
    assert e.categoria is None
    assert e.elegibilidad == "incompatible"


def test_titulo_afin_si_puede_heredar_indicio():
    e = evaluar(titulo="Operations", texto="Buscamos un data analyst para el equipo. Remoto.")
    assert e.categoria == "Data Analyst"
    assert e.origen_categoria == "texto"
    assert e.elegibilidad == "doubtful"


# 9. «Your Remote US Home Office» se leía como región no concluyente.
def test_region_con_us_suelto_es_restriccion():
    for region in ("Your Remote US Home Office", "US-Remote", "U.S. only", "Remote (US)"):
        e = evaluar(region=region)
        assert e.elegibilidad == "incompatible", region


def test_region_sin_us_sigue_siendo_dudosa():
    e = evaluar(region="Remote")
    assert e.elegibilidad == "doubtful"


# 10. «San Francisco, CA» o «Austin, TX» sin decir el país.
def test_ciudad_o_estado_de_eeuu_excluye():
    for region in ("San Francisco, CA", "Austin, TX", "Seattle, WA", "New York, NY",
                   "San Francisco, CA (remote)"):
        e = evaluar(region=region)
        assert e.elegibilidad == "incompatible", region


def test_la_plata_no_se_confunde_con_luisiana():
    e = evaluar(region="La Plata, Buenos Aires")
    assert e.elegibilidad != "incompatible"
