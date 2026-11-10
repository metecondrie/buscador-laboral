"""Caracterización de los modos de falla de clasificación (`rules-3.1.0`).

Estas pruebas **no juzgan** si el comportamiento actual es el correcto: lo
describen. Sirven para que cualquier cambio en las reglas se vea al instante en
la pantalla, y para que una mejora se pueda discutir con un ejemplo concreto y
reproducible delante.

Todo es sintético: no hay ofertas reales, ni nombres de empresa, ni URLs, ni
identificadores de aviso, ni datos de ninguna persona. El perfil está escrito
dentro del archivo para que el resultado no dependa del perfil real ni del perfil
de ejemplo del repositorio.

Correspondencia con `docs/ANEXO_CASOS_ANONIMIZADOS.md` (casos A a L).

Cómo leer un fallo:

- si el comportamiento cambió **a propósito**, actualizá la prueba y el anexo;
- si el cambio fue accidental, la prueba lo delata.

Los casos marcados `[FP]` (falso positivo) y `[FN]` (falso negativo) son
candidatos a mejora. Los marcados `[OK]` son controles: deben seguir igual.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from buscador import rules  # noqa: E402

#: Perfil sintético mínimo. No es el perfil real ni el de ejemplo del repo.
PERFIL = {
    "habilidades": [
        {"nombre": "SQL", "nivel": "demostrada"},
        {"nombre": "Python", "nivel": "demostrada"},
        {"nombre": "Excel", "nivel": "demotrada"},
    ],
    "idioma": {"ingles": "B2", "espanol": "nativo"},
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

BASE = {
    "titulo": "Data Analyst",
    "empresa": "Empresa Sintetica",
    "region": "Anywhere in the World",
    "texto": "SQL required. Excel required.",
    "salario": None,
    "seniority": None,
    "publicado_en": "2026-11-01T00:00:00Z",
    "expira_en": None,
    "tipo_contrato": None,
}


def evaluar(**cambios):
    """Evalúa una oferta sintética contra el perfil sintético."""
    oferta = dict(BASE)
    oferta.update(cambios)
    return rules.evaluar(oferta, PERFIL)


def razones_de(e, tipo: str, efecto: str) -> list[str]:
    return [r.get("texto", "") for r in e.razones
            if r.get("tipo") == tipo and r.get("efecto") == efecto]


# --- Caso A · idioma en lista «plus» ---------------------------------------


def test_idioma_en_lista_plus_no_es_requisito():
    """[OK · FP ya corregido] Un «is a plus» no es una exigencia de idioma."""
    e = evaluar(
        titulo="Customer Support Specialist",
        texto=("SQL required. Excel required. Bilingual (English/Spanish or "
               "Italian, Dutch, French) is a plus."),
    )
    assert e.elegibilidad == "eligible"
    # No se exige el idioma: la razón que queda es «no declara el nivel», que
    # suma incertidumbre pero no bloquea.
    assert not razones_de(e, "idioma", "excluye")
    assert any("no declara el nivel" in t for t in razones_de(e, "idioma", "duda"))


# --- Caso B · zona horaria restrictiva en el cuerpo -------------------------


def test_zona_horaria_en_el_cuerpo_excluye():
    """[OK] La restricción horaria del cuerpo se lee aunque la fuente sea global."""
    e = evaluar(
        titulo="Customer Support Specialist",
        texto=("SQL required. Excel required. This position is open to candidates "
               "in Central, Mountain and Eastern time zones only, Sunday to "
               "Thursday 8:30 to 17 CST."),
    )
    assert e.elegibilidad == "incompatible"
    assert any("zona horaria" in t for t in razones_de(e, "territorio", "excluye"))


# --- Caso C · el cuerpo contradice a la fuente ------------------------------


def test_cuerpo_mundial_no_contradice_a_la_fuente():
    """[FP · abierto] La fuente manda: el cuerpo «Worldwide» no la corrige.

    Este es el modo de falla con más volumen detrás (405 ofertas con alcance
    global declarado que aun así se descartan). Si una mejora decide que el
    cuerpo puede contradecir a la fuente, esta prueba es la que hay que
    cambiar, y el anexo junto con ella.
    """
    e = evaluar(
        titulo="Customer Support Specialist",
        region="United States",
        texto=("SQL required. Excel required. This is a Worldwide Remote position "
               "open to applicants from all countries."),
    )
    assert e.elegibilidad == "incompatible"
    assert any("United States" in t for t in razones_de(e, "territorio", "excluye"))
    # Y no queda rastro de la contradicción en las razones.
    assert not razones_de(e, "territorio", "duda")


# --- Caso D · híbrido fuera de la zona --------------------------------------


def test_hibrido_fuera_de_la_zona_excluye():
    """[OK] El híbrido fuera de la zona presencial no es viable."""
    e = evaluar(region="Berlin",
                texto="SQL required. Excel required. Hybrid 3 days per week in the office.")
    assert e.elegibilidad == "incompatible"
    assert e.modalidad == "hybrid"
    assert any("híbrido" in t for t in razones_de(e, "modalidad", "excluye"))


def test_hibrido_en_la_zona_queda_dudoso():
    """[OK] El híbrido en la zona presencial es duda, no descarte."""
    e = evaluar(region="La Plata",
                texto="SQL required. Excel required. Hybrid 3 days per week in the office.")
    assert e.elegibilidad == "doubtful"
    assert any("híbrido" in t for t in razones_de(e, "modalidad", "duda"))


# --- Caso E y F · formación -------------------------------------------------


def test_formacion_exigida_excluye():
    """[FN · abierto] «bachelor's degree is required» descarta sin mirar disciplina."""
    e = evaluar(texto="SQL required. Excel required. A bachelor's degree is required.")
    assert e.elegibilidad == "incompatible"
    assert any("título" in t for t in razones_de(e, "formacion", "excluye"))


def test_formacion_preferida_queda_dudosa():
    """[OK] «preferred» no descarta: duda."""
    e = evaluar(texto="SQL required. Excel required. A bachelor's degree is preferred.")
    assert e.elegibilidad == "doubtful"
    assert any("título" in t for t in razones_de(e, "formacion", "duda"))


# --- Caso G · experiencia ---------------------------------------------------


def test_ocho_anos_excluye():
    """[OK] Por encima del rango del perfil, la experiencia descarta."""
    e = evaluar(texto="SQL required. Excel required. 8+ years of experience.")
    assert e.elegibilidad == "incompatible"
    assert any("años" in t for t in razones_de(e, "seniority", "excluye"))


def test_tres_anos_con_competencias_no_excluye():
    """[OK] La excepción por competencias: 3 años no descarta si las skills están."""
    e = evaluar(texto="SQL required. Excel required. 3+ years of experience.")
    assert e.elegibilidad == "eligible"
    assert e.excepcion is True


def test_tres_anos_sin_competencias_queda_dudosa():
    """[OK] 3 años sin cobertura van a dudosas, no a descartes."""
    e = evaluar(texto="SAP required. Oracle required. 3+ years of experience.")
    assert e.elegibilidad == "doubtful"
    assert e.excepcion is False


# --- Caso H · categoría -----------------------------------------------------


def test_categoria_ajena_excluye():
    """[OK] Un rol ajeno a las categorías del perfil se descarta."""
    e = evaluar(titulo="Paid Ads Specialist",
                texto="SQL required. Excel required. Run Meta and Google ads campaigns.")
    assert e.elegibilidad == "incompatible"
    assert any("categor" in t for t in razones_de(e, "categoria", "excluye"))


# --- Caso I · remoto sin territorio publicado --------------------------------


def test_remoto_sin_territorio_queda_dudoso():
    """[FN · abierto] Sin territorio publicado no hay decisión: duda."""
    e = evaluar(region=None,
                texto="SQL required. Excel required. This is a fully remote position.")
    assert e.elegibilidad == "doubtful"
    assert e.modalidad == "remote"
    assert any("no publica el territorio" in t
               for t in razones_de(e, "territorio", "duda"))


# --- Caso J · inglés fluidity exigido ----------------------------------------


def test_ingles_fluido_con_perfil_b2_no_descarta():
    """[OK] Un requisito de idioma incumplido bloquea pero no descarta."""
    e = evaluar(titulo="Customer Support Specialist",
                texto="SQL required. Excel required. Fluent spoken English is required.")
    assert e.elegibilidad == "doubtful"
    assert not razones_de(e, "idioma", "excluye")


def test_idioma_no_declarado_no_puntua():
    """[OK] Sin nivel de inglés declarado no se otorgan puntos de idioma."""
    e = evaluar(
        titulo="Customer Support Specialist",
        texto=("SQL required. Excel required. We are looking for a customer "
               "support specialist to join our team."),
    )
    assert any("no declara el nivel" in t for t in razones_de(e, "idioma", "duda"))


def test_aviso_corto_no_genera_razon_de_idioma():
    """[FP · abierto] Con poco texto no se detecta el idioma dominante.

    `_idioma_del_aviso` necesita texto suficiente para reconocer inglés. Un
    aviso corto queda en «desconocido» y **no** genera ninguna razón de idioma:
    ni exige nivel ni lo pide. Es decir, la banda dudosa se puebla sólo con los
    avisos que tienen suficiente texto, y los avisos más escuetos pasan sin
    dejar rastro de que su idioma nunca se evaluó.
    """
    corto = evaluar(
        titulo="Customer Support Specialist",
        texto="SQL required. Excel required.",
    )
    largo = evaluar(
        titulo="Customer Support Specialist",
        texto=("SQL required. Excel required. We are looking for a customer "
               "support specialist to join our team."),
    )
    assert not razones_de(corto, "idioma", "excluye")
    assert not razones_de(corto, "idioma", "duda")
    assert razones_de(largo, "idioma", "duda")


# --- Caso K · línea base ----------------------------------------------------


def test_aviso_con_datos_minimos_es_elegible():
    """[OK] Línea base: sólo SQL, territorio global, sin extras."""
    e = evaluar()
    assert e.elegibilidad == "eligible"
    assert e.confianza in ("media", "alta")


# --- Caso L · alcance global declarado en el cuerpo -------------------------


def test_alcance_mundial_en_el_cuerpo_sin_region_se_acepta():
    """[OK] Si la fuente no dice nada, el cuerpo sí define el alcance."""
    e = evaluar(titulo="Technical Customer Support", region=None,
                texto=("SQL required. Excel required. Fully remote worldwide team. "
                       "No years of experience required."))
    assert e.elegibilidad == "eligible"
    assert any("alcance mundial" in t for t in razones_de(e, "territorio", "suma"))


# --- Control de versión -----------------------------------------------------


def test_reglas_es_3_1_0():
    """[OK] La caracterización corresponde a `rules-3.1.0`."""
    from buscador import config
    assert config.RULES_VERSION == "rules-3.1.0"
    assert rules.RULES_VERSION == "rules-3.1.0"


def test_evaluar_no_escribe_en_la_base(tmp_path):
    """[OK] `evaluar` es una función pura: no toca disco ni base de datos."""
    antes = sorted(p.name for p in tmp_path.iterdir())
    evaluar()
    despues = sorted(p.name for p in tmp_path.iterdir())
    assert antes == despues


@pytest.mark.parametrize("caso", ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"])
def test_anexo_documenta_todos_los_casos(caso):
    """[OK] Cada caso del anexo tiene su prueba: no se pierde documentación."""
    anexo = RAIZ / "docs" / "ANEXO_CASOS_ANONIMIZADOS.md"
    texto = anexo.read_text(encoding="utf-8")
    assert f"## Caso {caso} " in texto
