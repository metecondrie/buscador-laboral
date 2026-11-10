"""Interfaz del MVP: rutas nuevas, filtros, perfil, respaldos y duplicados."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from buscador import ingest, merge, worker
from buscador.adapters.base import Observacion, ResultadoFuente
from buscador.web import crear_app

TOKEN = "token-mvp"
CSRF = "csrf-mvp"
RUTAS = ["/ofertas", "/dudosas", "/todas", "/guardadas", "/duplicados", "/historial",
         "/fuentes", "/actividad", "/config", "/diagnostico"]


def _obs(source_id: str, ext: str, titulo: str, empresa: str, region: str,
         texto: str = "SQL required. Python desirable. Excel.") -> Observacion:
    return Observacion(
        source_id=source_id, external_id=ext, url=f"https://ejemplo.test/{ext}",
        titulo=titulo, empresa=empresa, descripcion_html=f"<p>{texto}</p>",
        publicado_en="2026-11-01T00:00:00Z", region=region,
        extra={"texto_plano": texto},
    )


@pytest.fixture
def cliente(entorno, perfil_id):
    ingest.ingestar(entorno, ResultadoFuente("F01", "success", [
        _obs("F01", "a", "Data Analyst", "Acme", "Anywhere in the World"),
    ]), perfil_id)
    ingest.ingestar(entorno, ResultadoFuente("F02", "success", [
        # Presencialidad declarada en el aviso: la región por sí sola ya no
        # alcanza para clasificar una oferta como «onsite».
        _obs("F02", "b", "Data Analyst", "Globex", "Berlin, Germany",
             "SQL required. Python desirable. On-site role at the Berlin office."),
    ]), perfil_id)
    worker.procesar_tareas(entorno, "epoch-mvp")
    app = crear_app(token=TOKEN, csrf=CSRF)
    cliente = TestClient(app, base_url="http://127.0.0.1")
    cliente.get("/entrar?token=" + TOKEN)
    return cliente


def test_todas_las_paginas_renderizan(cliente):
    for ruta in RUTAS:
        respuesta = cliente.get(ruta)
        assert respuesta.status_code == 200, ruta
        assert "Internal Server Error" not in respuesta.text, ruta


def test_filtro_por_modalidad(cliente):
    remotas = cliente.get("/todas?modalidad=remote")
    assert "Data Analyst" in remotas.text
    solo_presenciales = cliente.get("/todas?modalidad=onsite")
    assert "Berlin, Germany" in solo_presenciales.text
    assert "Anywhere in the World" not in solo_presenciales.text


def test_filtro_por_fuente(cliente):
    respuesta = cliente.get("/todas?fuente=F02")
    assert "Globex" in respuesta.text
    assert "Acme" not in respuesta.text


def test_detalle_muestra_historial_y_componentes(cliente, entorno):
    job_id = entorno.execute(
        """SELECT jo.job_id FROM job_observations jo
           JOIN observations o ON o.id = jo.observation_id
           WHERE o.external_id = 'a'"""
    ).fetchone()["job_id"]
    respuesta = cliente.get(f"/oferta/{job_id}")
    assert respuesta.status_code == 200
    assert "Componentes del puntaje" in respuesta.text
    assert "Historial de la oferta" in respuesta.text


def test_guardar_perfil_reclasifica(cliente, entorno):
    antes = entorno.execute("SELECT COUNT(*) FROM profile_versions").fetchone()[0]
    respuesta = cliente.post("/perfil", data={
        "csrf": CSRF, "habilidades": "SQL\nPython\nPower BI", "ingles": "B2",
        "anios": "1", "nivel": "junior", "residencia": "Argentina", "remoto": "1",
        "presencial": "La Plata", "ars_referencia": "100000", "ars_objetivo": "200000",
        "usd_hora": "5", "desde": "inmediata", "horas": "40",
        "categorias": ["Data Analyst", "Business Analyst"],
    }, follow_redirects=False)
    assert respuesta.status_code == 303
    despues = entorno.execute("SELECT COUNT(*) FROM profile_versions").fetchone()[0]
    assert despues == antes + 1
    assert entorno.execute("SELECT COUNT(*) FROM tasks WHERE estado='queued'").fetchone()[0] >= 1
    activo = entorno.execute(
        "SELECT perfil_json FROM profile_versions WHERE activo=1 ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    assert "Power BI" in activo
    assert "Data Analyst" in activo


def test_perfil_sin_csrf_rechazado(cliente):
    assert cliente.post("/perfil", data={"csrf": "malo"}).status_code == 400


def test_respaldo_desde_la_interfaz(cliente, entorno):
    respuesta = cliente.post("/respaldo", data={"csrf": CSRF}, follow_redirects=False)
    assert respuesta.status_code == 303
    assert entorno.execute("SELECT COUNT(*) FROM backup_log").fetchone()[0] == 1


def test_exportacion_desde_la_interfaz(cliente, entorno):
    respuesta = cliente.post("/exportar", data={"csrf": CSRF, "guardadas": "0"},
                             follow_redirects=False)
    assert respuesta.status_code == 303


def test_duplicados_aceptar_y_revertir_desde_la_interfaz(entorno, perfil_id):
    ingest.ingestar(entorno, ResultadoFuente("F01", "success", [
        _obs("F01", "a", "Data Analyst", "Acme", "Anywhere in the World"),
    ]), perfil_id)
    ingest.ingestar(entorno, ResultadoFuente("F02", "success", [
        _obs("F02", "b", "Data Analyst (Remote)", "Acme", "Anywhere in the World"),
    ]), perfil_id)
    worker.procesar_tareas(entorno, "epoch-dup-ui")
    review = merge.sugerencias(entorno)[0]

    app = crear_app(token=TOKEN, csrf=CSRF)
    cliente = TestClient(app, base_url="http://127.0.0.1")
    cliente.get("/entrar?token=" + TOKEN)

    lista = cliente.get("/duplicados")
    assert "equivalencia" in lista.text

    assert cliente.post(f"/duplicados/{review['id']}/aceptar", data={"csrf": CSRF},
                        follow_redirects=False).status_code == 303
    assert entorno.execute("SELECT merged_into FROM jobs WHERE id=?",
                           (review["job_origen"],)).fetchone()[0] == review["job_destino"]

    assert cliente.post(f"/duplicados/{review['id']}/revertir", data={"csrf": CSRF},
                        follow_redirects=False).status_code == 303
    assert entorno.execute("SELECT merged_into FROM jobs WHERE id=?",
                           (review["job_origen"],)).fetchone()[0] is None


def test_accion_de_duplicado_invalida(cliente):
    respuesta = cliente.post("/duplicados/1/borrar-todo", data={"csrf": CSRF})
    assert respuesta.status_code == 400


def test_pagina_de_fuentes_muestra_once(cliente):
    respuesta = cliente.get("/fuentes")
    for source_id in ("F01", "F04", "F07", "F11"):
        assert source_id in respuesta.text
    assert "relevantes" in respuesta.text.lower()
