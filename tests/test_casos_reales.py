"""Casos reales reportados por el usuario, con el texto original del aviso.

Los cinco avisos están guardados en `tests/fixtures/casos_reales/` tal como los
devolvió la fuente (título, empresa, territorio, fecha y cuerpo completo). Son la
evidencia: si el clasificador cambia, estos archivos no se tocan.

Antes / después con rules-3.0.0:

| Aviso | Antes (rules-2.0.0) | Ahora |
|---|---|---|
| Remote Office Assistant · Coalition | eligible · 100,0 · confianza alta | eligible · 75,7 · media |
| Remote Data Entry Clerk · NoGigiddy | eligible · 100,0 · media | eligible · 42,3 · media |
| Technical Support Engineer · Alloy | eligible · 86,0 · alta | **doubtful** · 63,7 · media |
| Clinical Data Manager · Penumbra | incompatible (EE. UU.) | incompatible (EE. UU.) |
| Client Service Analyst · Bybit | incompatible **por categoría** | incompatible **por idioma (turco)** |
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from buscador import rules
from buscador.perfil import PERFIL_EJEMPLO

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "casos_reales"


def cargar(nombre: str) -> dict:
    return json.loads((FIXTURES / f"{nombre}.json").read_text(encoding="utf-8"))


def evaluar(nombre: str):
    datos = cargar(nombre)
    return rules.evaluar(
        {
            "titulo": datos["titulo"],
            "empresa": datos["empresa"],
            "texto": datos["texto"],
            "region": datos["region"],
            "seniority": None,
            "salario": None,
            "publicado_en": datos["publicado_en"],
            "expira_en": None,
        },
        PERFIL_EJEMPLO,
    )


def componente(evaluacion, nombre: str):
    return next(c for c in evaluacion.componentes if c.nombre == nombre)


# --- 1. Remote Office Assistant (Coalition Technologies) --------------------

def test_office_assistant_no_saca_cien_por_no_contradecir():
    """Antes: 25/25 + 40/40 + 20/20 + 15/15 = 100 con confianza alta.

    El aviso no declara formación, no declara nivel de inglés y menciona sólo dos
    habilidades reconocibles. Ahora eso se paga: no se otorgan puntos por lo que
    no se sabe.
    """
    e = evaluar("office_assistant")

    assert e.elegibilidad == "eligible"
    assert e.compatibilidad is not None
    assert e.compatibilidad < 90
    assert e.confianza != "alta"

    # La categoría sí está bien: el título y las tareas coinciden.
    assert e.categoria == "VA/Data Entry"
    assert componente(e, "categoria_tareas").estado == "cumplido"

    # Habilidades: dos menciones no llenan 40 puntos.
    habilidades = componente(e, "habilidades")
    assert habilidades.estado == "parcial"
    assert habilidades.obtenido < 40

    # Formación: no se declara, así que no suma.
    formacion = componente(e, "formacion")
    assert formacion.estado == "sin_datos"
    assert formacion.obtenido == 0

    # Idioma: aviso en inglés sin nivel exigido → crédito parcial, no 8/8.
    idioma = componente(e, "idioma")
    assert idioma.estado == "parcial"
    assert 0 < idioma.obtenido < 8


# --- 2. Remote Data Entry Clerk (NoGigiddy) ---------------------------------

def test_data_entry_clerk_queda_con_puntaje_bajo_y_honesto():
    """Antes: 100,0 y elegible. Hoy: puntaje bajo y vigencia sin confirmar.

    V01: el aviso se publicó el 2025-11-11 y no declara cierre. La antigüedad no
    prueba que esté cerrado, pero tampoco hay evidencia de que siga abierto: va a
    revisión con el motivo a la vista, nunca a `eligible` por inercia.
    """
    e = evaluar("data_entry_clerk")

    assert e.categoria == "VA/Data Entry"
    assert e.vigencia == "stale"
    assert e.elegibilidad == "doubtful"
    assert any("vigencia sin confirmar" in i for i in e.incertidumbres)
    assert e.compatibilidad is not None
    assert e.compatibilidad <= 50
    assert componente(e, "experiencia").estado == "sin_datos"
    assert componente(e, "habilidades").obtenido <= 40 * (1 / 3) + 0.1
    assert any("no declara experiencia" in i for i in e.incertidumbres)


# --- 3. Technical Support Engineer, Triage & Discovery (Alloy) --------------

def test_support_engineer_con_viajes_no_es_elegible_sin_revisar():
    """Antes: eligible 86,0 con confianza alta.

    El aviso real dice que los remotos van a la oficina una vez por trimestre y
    que el puesto «may require travel». Eso no es incompatible, pero tampoco
    elegible sin que el usuario lo revise.
    """
    e = evaluar("support_engineer_alloy")

    assert e.elegibilidad == "doubtful"
    assert any("viajes" in i or "visitas presenciales" in i for i in e.decisivas)
    assert e.requisitos["estado_laboral"] == "duda"
    # Sigue puntuado: la información es buena, la restricción es la duda.
    assert e.compatibilidad is not None


def test_support_engineer_reconoce_la_exigencia_de_experiencia():
    """Pide 3 años: excepción por competencias, no 20/20 por «sin contradicción»."""
    e = evaluar("support_engineer_alloy")
    experiencia = componente(e, "experiencia")
    assert e.anios_requeridos == 3
    assert e.excepcion is True
    assert experiencia.obtenido == 12
    assert experiencia.estado == "parcial"


# --- 4. Clinical Data Manager (Penumbra) ------------------------------------

def test_clinical_data_manager_excluye_por_territorio_estadounidense():
    e = evaluar("clinical_data_manager")

    assert e.elegibilidad == "incompatible"
    assert e.compatibilidad is None
    assert "estados unidos" in e.motivo_elegibilidad.lower()
    assert e.requisitos["alcance_territorial"] == "restringido"


def test_el_cuerpo_manda_sobre_un_territorio_permisivo():
    """Aunque la fuente diga «Anywhere», el aviso puede exigir permiso de trabajo."""
    datos = cargar("clinical_data_manager")
    e = rules.evaluar(
        {**datos, "region": "Anywhere in the World", "seniority": None,
         "salario": None, "expira_en": None},
        PERFIL_EJEMPLO,
    )
    assert e.elegibilidad == "incompatible"
    assert e.requisitos["alcance_territorial"] == "restringido"


# --- 5. Client Service Analyst (Bybit, turco) -------------------------------

def test_client_service_excluye_por_idioma_no_por_categoria():
    """Antes el motivo era «sin coincidencia con las categorías»: no era el motivo.

    El puesto es atención al cliente y el requisito real es hablar turco, idioma
    que el perfil no declara.
    """
    e = evaluar("client_service_turkish")

    assert e.elegibilidad == "incompatible"
    assert e.categoria == "Customer Support"
    assert "turkish" in e.motivo_elegibilidad.lower()
    assert e.requisitos["estado_idioma"] == "incumplido"


# --- coherencia entre los cinco ---------------------------------------------

@pytest.mark.parametrize("nombre", [
    "office_assistant", "data_entry_clerk", "support_engineer_alloy",
    "clinical_data_manager", "client_service_turkish",
])
def test_ningun_caso_queda_sin_motivo_ni_con_puntaje_incoherente(nombre):
    e = evaluar(nombre)
    assert e.motivo_elegibilidad
    assert e.confianza in {"alta", "media", "baja"}
    if e.elegibilidad == "incompatible":
        assert e.compatibilidad is None
    else:
        assert e.compatibilidad is not None
        assert 0 <= e.compatibilidad <= 100
    # La suma de componentes nunca supera el máximo disponible.
    assert sum(c.obtenido for c in e.componentes if c.aplicable) <= 100
