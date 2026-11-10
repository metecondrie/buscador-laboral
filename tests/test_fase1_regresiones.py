"""Regresiones independientes de la Fase 1 (BUSCAD0R).

Casos que motivaron la reparación: una región declarada se interpretaba como
presencialidad; faltaban locuciones remotas inequívocas; un idioma opcional
excluía igual que uno obligatorio; y los motivos de idioma declaraban B2 aunque
el perfil efectivo dice B1.

Todo se evalúa contra dicts en memoria o una base SQLite temporal (`entorno`).
No hay red, ni modelos, ni lectura de la base operativa, ni reclasificación.
"""

from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient

from buscador import config, db, notify, rules
from buscador.perfil import PERFIL_EJEMPLO
from buscador.web import crear_app

TOKEN = "token-fase1"
CSRF = "csrf-fase1"

# El usuario declaró inglés general B1. Se usa una COPIA: ni se cambia el
# perfil operativo (`perfil.json`) ni la constante de demostración del módulo.
PERFIL_B1 = copy.deepcopy(PERFIL_EJEMPLO)
PERFIL_B1["idioma"]["ingles"] = "B1"

BASE = {
    "titulo": "Junior Data Analyst",
    "texto": "SQL required. Excel required. Python required.",
    "region": None,
    "seniority": None,
    "salario": None,
    "publicado_en": "2026-11-01T00:00:00Z",
    "expira_en": None,
}


def evaluar(**cambios):
    return rules.evaluar(dict(BASE, **cambios), PERFIL_B1)


# --- A. Modalidad, territorio y elegibilidad son tres cosas distintas --------

@pytest.mark.parametrize("region,alcance", [
    ("Latin America Only", "internacional"),
    ("Worldwide", "mundial"),
])
def test_region_sin_modalidad_no_se_asume_presencial(region, alcance):
    e = evaluar(
        region=region,
        texto=("We are looking for an analyst to work with SQL and Python dashboards. "
               "Must have good communication skills."),
    )
    assert e.modalidad == "unknown"                       # ni onsite ni remote
    assert e.requisitos["alcance_territorial"] == alcance  # territorio separado
    assert e.elegibilidad != "incompatible"               # no se descarta
    assert e.compatibilidad is not None                    # conserva su puntaje
    assert not any("presencial" in r["texto"] for r in e.razones)


def test_virtual_aislado_no_garantiza_modalidad_remota():
    assert "virtual" not in rules._REMOTO
    e = evaluar(region="Latin America",
                texto="Virtual meetings with the team. SQL required. Excel required.")
    assert e.modalidad == "unknown"


# --- B. Vocabulario remoto inequívoco ---------------------------------------

@pytest.mark.parametrize("locucion", [
    "home based", "home-based", "fully remote", "work from home",
    "work from anywhere",
])
def test_locuciones_remotas_inequivocas_se_reconocen(locucion):
    e = evaluar(region="Worldwide",
                texto=f"{locucion.capitalize()} position. SQL required. "
                      "Excel required. Python required.")
    assert e.modalidad == "remote"
    assert e.requisitos["alcance_territorial"] == "mundial"
    assert e.elegibilidad == "eligible"


def test_home_based_worldwide_en_la_cabecera_tambien_es_remoto():
    e = evaluar(region="Home based - Worldwide",
                texto="Canonical is hiring. SQL and Python automation. Global team.")
    assert e.modalidad == "remote"


# --- Presencial e híbrida siguen detectándose con evidencia explícita -------

@pytest.mark.parametrize("texto", [
    "On-site role. SQL required. Excel required.",
    "This is an in office position. SQL required. Excel required.",
])
def test_presencial_con_region_geografica_sigue_siendo_onsite(texto):
    e = evaluar(region="Berlin, Germany", texto=texto)
    assert e.modalidad == "onsite"
    assert e.elegibilidad == "incompatible"


def test_hibrida_no_se_confunde_con_remota():
    e = evaluar(region="Buenos Aires (hybrid)",
                texto="Hybrid work, two days in the office. SQL required. Excel required.")
    assert e.modalidad == "hybrid"
    assert e.elegibilidad == "incompatible"


# --- C. Idioma: obligatorio != opcional -------------------------------------

@pytest.mark.parametrize("texto", [
    "French required. SQL required. Excel required. Remote.",
    "Turkish speaker required. SQL required. Excel required. Remote.",
    "Fluent in German is essential. SQL required. Excel required. Remote.",
])
def test_idioma_extranjero_obligatorio_excluye(texto):
    e = evaluar(region="Worldwide", texto=texto)
    assert e.requisitos["estado_idioma"] == "incumplido"
    assert e.elegibilidad == "incompatible"


@pytest.mark.parametrize("texto", [
    "French is a plus. SQL required. Excel required. Remote.",
    "SQL required. French is a plus. Excel required. Remote.",
    "German desirable. SQL required. Excel required. Remote.",
])
def test_idioma_extranjero_opcional_no_excluye(texto):
    e = evaluar(region="Worldwide", texto=texto)
    assert e.requisitos["estado_idioma"] != "incumplido"
    assert e.elegibilidad != "incompatible"
    assert "un idioma que el perfil no declara" not in e.motivo_elegibilidad


def test_mensajes_de_idioma_usan_el_nivel_efectivo_del_perfil():
    textos = (
        "Native English speaker required. SQL required. Remote.",
        "English C1 required. SQL required. Remote.",
        "English proficiency required. SQL required. Remote.",
    )
    for texto in textos:
        e = evaluar(region="Worldwide", texto=texto)
        mensajes = " ".join(e.razones_texto() + e.incertidumbres + e.decisivas
                            + [e.motivo_elegibilidad])
        assert "B2" not in mensajes
        assert "B1" in mensajes

    _, motivo_b1, _ = rules._idioma("Data Analyst", textos[0], "B1")
    assert "B1" in motivo_b1 and "B2" not in motivo_b1
    _, motivo_b2, _ = rules._idioma("Data Analyst", textos[0], "B2")
    assert "B2" in motivo_b2 and "B1" not in motivo_b2
    assert PERFIL_B1["idioma"]["ingles"] == "B1"


# --- D. Notificaciones marcadas como leídas (base temporal) -----------------

@pytest.fixture
def bandeja(entorno):
    """Dos avisos sin leer y uno leído, en la base temporal de `entorno`."""
    ahora = config.ahora_utc()
    with db.transaccion(entorno):
        entorno.execute(
            """INSERT INTO jobs (id, titulo, empresa, estado_vigencia, publicado_en,
                   primera_deteccion, ultima_deteccion, semantic_hash,
                   url_atribucion, fuente_principal)
               VALUES ('job_fase1', 'Data Analyst', 'Acme', 'unknown', ?, ?, ?, ?,
                       'https://ejemplo.test/fase1', 'F01')""",
            (ahora, ahora, ahora, "hash-fase1"),
        )
        for numero, leido in enumerate((False, True, False), start=1):
            entorno.execute(
                """INSERT INTO notifications
                       (clave, job_id, canal, estado, payload_json, creado_en, leido_en)
                   VALUES (?, 'job_fase1', 'inbox', 'delivered', ?, ?, ?)""",
                (f"fase1|inbox|{numero}",
                 json.dumps({"job_id": "job_fase1", "titulo": "Data Analyst",
                             "empresa": "Acme", "score": 80.0}),
                 ahora, ahora if leido else None),
            )
    return entorno


def test_notificaciones_marcadas_como_leidas(bandeja):
    assert notify.no_leidos(bandeja) == 2
    cliente = TestClient(crear_app(token=TOKEN, csrf=CSRF),
                         base_url="http://127.0.0.1")
    cliente.get(f"/entrar?token={TOKEN}")

    respuesta = cliente.post("/avisos/leidos", data={"csrf": CSRF},
                             follow_redirects=False)
    assert respuesta.status_code == 303
    assert notify.no_leidos(bandeja) == 0
    assert notify.marcar_leidos(bandeja) == 0  # idempotente

    # Se verifica el componente de lectura, no la frase fija de los textos de
    # ayuda (resumen de la bandeja y tooltip del enlace de Actividad).
    html = cliente.get("/actividad").text
    tabla = (html.split("<h2>Bandeja de avisos</h2>", 1)[1]
             .split("<table", 1)[1].split("</table>", 1)[0])
    assert "<b>sin leer</b>" not in tabla
    assert tabla.count("leído") == 3
    enlace = html.split('<a href="/actividad"', 1)[1].split("</a>", 1)[0]
    assert '<span class="pill"' not in enlace
