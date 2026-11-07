"""Interfaz local: sesión, CSRF, acciones idempotentes y cierre (P01, P09)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from buscador import ingest, worker
from buscador.adapters.base import Observacion, ResultadoFuente
from buscador.web import crear_app

TOKEN = "token-de-prueba"
CSRF = "csrf-de-prueba"


def _sembrar_oferta(conn, perfil_id: int) -> str:
    obs = Observacion(
        source_id="F01",
        external_id="ext-ui-1",
        url="https://weworkremotely.com/remote-jobs/acme-junior-data-analyst",
        titulo="Junior Data Analyst",
        empresa="Acme",
        descripcion_html="<p>SQL required. Python desirable.</p>",
        publicado_en="2026-11-01T00:00:00Z",
        region="Anywhere in the World",
        extra={"texto_plano": "SQL required. Python desirable. Excel."},
    )
    ingest.ingestar(
        conn, ResultadoFuente(source_id="F01", estado="success", observaciones=[obs]), perfil_id
    )
    worker.procesar_tareas(conn, "epoch-ui")
    return conn.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]


@pytest.fixture
def cliente(entorno, perfil_id):
    _sembrar_oferta(entorno, perfil_id)
    app = crear_app(token=TOKEN, csrf=CSRF)
    return TestClient(app, base_url="http://127.0.0.1")


def test_sin_sesion_redirige(cliente):
    respuesta = cliente.get("/ofertas", follow_redirects=False)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/entrar"


def test_token_invalido_rechazado(cliente):
    assert cliente.get("/entrar?token=otro").status_code == 403


def test_token_de_un_solo_uso(cliente):
    assert cliente.get("/entrar?token=" + TOKEN, follow_redirects=False).status_code == 303
    assert cliente.get("/entrar?token=" + TOKEN).status_code == 403


def test_host_ajeno_rechazado(entorno, perfil_id):
    app = crear_app(token=TOKEN, csrf=CSRF)
    otro = TestClient(app, base_url="http://evil.example")
    assert otro.get("/salud").status_code == 400


def test_csrf_invalido_rechazado(cliente, entorno):
    cliente.get("/entrar?token=" + TOKEN)
    job_id = entorno.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]
    respuesta = cliente.post(
        f"/oferta/{job_id}/accion",
        data={"csrf": "malo", "accion": "guardar", "action_id": "a1"},
        follow_redirects=False,
    )
    assert respuesta.status_code == 400


def test_accion_idempotente(cliente, entorno):
    cliente.get("/entrar?token=" + TOKEN)
    job_id = entorno.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]
    datos = {"csrf": CSRF, "accion": "guardar", "action_id": "accion-1"}

    assert cliente.post(f"/oferta/{job_id}/accion", data=datos, follow_redirects=False).status_code == 303
    cliente.post(f"/oferta/{job_id}/accion", data={**datos, "accion": "descartar"}, follow_redirects=False)

    eventos = entorno.execute("SELECT accion FROM user_events WHERE action_id='accion-1'").fetchall()
    assert len(eventos) == 1
    assert eventos[0]["accion"] == "guardar"


def test_guardadas_refleja_la_accion(cliente, entorno):
    cliente.get("/entrar?token=" + TOKEN)
    job_id = entorno.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]
    cliente.post(
        f"/oferta/{job_id}/accion",
        data={"csrf": CSRF, "accion": "interesar", "action_id": "accion-2"},
        follow_redirects=False,
    )
    guardadas = cliente.get("/guardadas")
    assert guardadas.status_code == 200
    assert "Junior Data Analyst" in guardadas.text


def test_aviso_local_se_crea_una_sola_vez(cliente, entorno, perfil_id):
    job_id = entorno.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]
    fila = entorno.execute(
        """SELECT a.elegibilidad, a.score FROM analyses a WHERE a.job_id=? AND a.obsoleto=0""", (job_id,)
    ).fetchone()
    if fila["elegibilidad"] != "eligible" or (fila["score"] or 0) < 75:
        pytest.skip("la oferta de prueba no alcanza el umbral de aviso")

    worker.procesar_tareas(entorno, "epoch-ui-2")
    total = entorno.execute("SELECT COUNT(*) FROM notifications WHERE job_id=?", (job_id,)).fetchone()[0]
    assert total == 1


def test_salir_responde(cliente):
    cliente.get("/entrar?token=" + TOKEN)
    respuesta = cliente.post("/salir", data={"csrf": CSRF})
    assert respuesta.status_code == 200
    assert "Servidor detenido" in respuesta.text
