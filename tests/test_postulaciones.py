"""Postulaciones: registrar, editar, retirar, historial y persistencia.

«Me interesa» es una intención; «postulada» es un hecho con fecha. La aplicación
nunca envía nada: sólo anota lo que el usuario ya hizo por fuera.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from buscador import config, db, ingest, postulaciones
from buscador.adapters.base import Observacion, ResultadoFuente
from buscador.web import crear_app

CSRF = "c"


def _obs(ext: str = "ext-1") -> Observacion:
    return Observacion(
        source_id="F01", external_id=ext, url=f"https://ejemplo.test/{ext}",
        titulo="Junior Data Analyst", empresa="Acme",
        descripcion_html="<p>SQL required.</p>", publicado_en="2026-11-05T00:00:00Z",
        region="Anywhere in the World",
        extra={"texto_plano": "SQL required. Excel. Dashboards."},
    )


@pytest.fixture
def oferta(entorno, perfil_id):
    """Una oferta guardada y clasificada, lista para postular."""
    ingest.ingestar(entorno, ResultadoFuente("F01", "success", [_obs()]), perfil_id)
    from buscador import worker

    worker.procesar_tareas(entorno, "epoch-postulaciones",
                           perfil=worker.asegurar_perfil(entorno, config.rutas()))
    job_id = entorno.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]
    return job_id


@pytest.fixture
def cliente(entorno):
    cliente = TestClient(crear_app(token="t", csrf=CSRF), base_url="http://127.0.0.1")
    cliente.get("/entrar?token=t")
    return cliente


# --- modelo ---------------------------------------------------------------

def test_registrar_guarda_fecha_enlace_y_notas(entorno, oferta):
    datos = postulaciones.registrar(
        entorno, oferta, fecha="2026-11-06",
        enlace="https://empleo.test/postular", notas="Enviado por el portal")

    assert datos["estado"] == "postulada"
    assert datos["fecha"] == "2026-11-06"
    guardada = postulaciones.obtener(entorno, oferta)
    assert guardada["enlace"] == "https://empleo.test/postular"
    assert guardada["notas"] == "Enviado por el portal"


def test_no_se_duplica_la_postulacion(entorno, oferta):
    postulaciones.registrar(entorno, oferta, fecha="2026-11-06")
    postulaciones.registrar(entorno, oferta, fecha="2026-11-07")

    filas = entorno.execute(
        "SELECT COUNT(*) FROM applications WHERE job_id=?", (oferta,)).fetchone()[0]
    assert filas == 1
    assert postulaciones.obtener(entorno, oferta)["fecha"] == "2026-11-07"


def test_editar_conserva_lo_que_no_se_envia(entorno, oferta):
    postulaciones.registrar(entorno, oferta, fecha="2026-11-06", notas="primera nota")
    postulaciones.registrar(entorno, oferta, fecha="2026-11-08")

    actual = postulaciones.obtener(entorno, oferta)
    assert actual["fecha"] == "2026-11-08"
    assert actual["notas"] == "primera nota"      # no se borra por no reenviarla


def test_retirar_conserva_el_registro(entorno, oferta):
    postulaciones.registrar(entorno, oferta, fecha="2026-11-06", notas="nota")
    assert postulaciones.retirar(entorno, oferta) is True

    actual = postulaciones.obtener(entorno, oferta)
    assert actual["estado"] == "retirada"
    assert actual["notas"] == "nota"              # el registro sigue ahí
    assert postulaciones.vigente(entorno, oferta) is None


def test_reabrir_una_postulacion_retirada(entorno, oferta):
    postulaciones.registrar(entorno, oferta, fecha="2026-11-06")
    postulaciones.retirar(entorno, oferta)
    datos = postulaciones.registrar(entorno, oferta, fecha="2026-11-09")

    assert datos["estado"] == "postulada"
    assert datos["reabierta"] is True
    assert postulaciones.vigente(entorno, oferta) is not None


def test_historial_sin_duplicados_por_reintento(entorno, oferta):
    for _ in range(3):
        postulaciones.registrar(entorno, oferta, fecha="2026-11-06")

    eventos = entorno.execute(
        "SELECT COUNT(*) FROM user_events WHERE job_id=? AND accion='postular'",
        (oferta,)).fetchone()[0]
    assert eventos == 1      # mismo día y misma oferta → mismo evento


def test_historial_registra_cambios_de_fecha(entorno, oferta):
    postulaciones.registrar(entorno, oferta, fecha="2026-11-06")
    postulaciones.registrar(entorno, oferta, fecha="2026-11-07")
    postulaciones.retirar(entorno, oferta)

    historial = postulaciones.historial(entorno, oferta)
    assert [h["accion"] for h in historial].count("postular") == 2
    assert "retirar" in [h["accion"] for h in historial]


def test_me_interesa_no_es_postulada(entorno, oferta):
    """Distinción explícita: guardar o interesar no crea una postulación."""
    with db.transaccion(entorno):
        entorno.execute(
            "INSERT INTO user_events (action_id, job_id, accion, creado_en, version_esperada)"
            " VALUES ('x1', ?, 'interesar', ?, 'v1')",
            (oferta, config.ahora_utc()))
    assert postulaciones.obtener(entorno, oferta) is None
    assert postulaciones.contar(entorno)["postulada"] == 0


def test_oferta_inexistente_no_rompe(entorno):
    with pytest.raises(LookupError):
        postulaciones.registrar(entorno, "job_no_existe", "2026-11-06")


def test_fecha_invalida_cae_en_hoy(entorno, oferta):
    from datetime import date

    datos = postulaciones.registrar(entorno, oferta, fecha="no-es-fecha")
    assert datos["fecha"] == date.today().isoformat()


# --- interfaz y persistencia ---------------------------------------------

def test_registrar_por_http_y_verlo_en_la_ficha(cliente, entorno, oferta):
    respuesta = cliente.post(
        f"/oferta/{oferta}/postulacion",
        data={"csrf": CSRF, "fecha": "2026-11-06", "enlace": "https://x.test/1",
              "notas": "por el portal"},
        follow_redirects=False)

    assert respuesta.status_code == 303
    ficha = cliente.get(f"/oferta/{oferta}").text
    assert "Postulada el" in ficha
    assert "2026-11-06" in ficha
    assert "por el portal" in ficha


def test_la_lista_muestra_la_insignia(cliente, entorno, oferta):
    cliente.post(f"/oferta/{oferta}/postulacion",
                 data={"csrf": CSRF, "fecha": "2026-11-06"}, follow_redirects=False)

    html = cliente.get("/todas").text
    assert "postulada 2026-11-06" in html


def test_pagina_postuladas_lista_la_oferta(cliente, entorno, oferta):
    cliente.post(f"/oferta/{oferta}/postulacion",
                 data={"csrf": CSRF, "fecha": "2026-11-06"}, follow_redirects=False)

    html = cliente.get("/postuladas").text
    assert "Junior Data Analyst" in html
    assert "2026-11-06" in html


def test_retirar_por_http(cliente, entorno, oferta):
    cliente.post(f"/oferta/{oferta}/postulacion",
                 data={"csrf": CSRF, "fecha": "2026-11-06"}, follow_redirects=False)
    respuesta = cliente.post(f"/oferta/{oferta}/postulacion/retirar",
                             data={"csrf": CSRF}, follow_redirects=False)

    assert respuesta.status_code == 303
    assert postulaciones.obtener(entorno, oferta)["estado"] == "retirada"
    assert "retirada" in cliente.get("/postuladas").text


def test_la_postulacion_sobrevive_al_reinicio(entorno, oferta):
    """Criterio de aceptación: registrar, cerrar y volver a leer."""
    postulaciones.registrar(entorno, oferta, fecha="2026-11-06",
                            enlace="https://x.test/1", notas="nota persistente")

    db.inicializar(config.rutas().db)          # simula reiniciar la aplicación
    otra = db.conectar(config.rutas().db)
    try:
        guardada = postulaciones.obtener(otra, oferta)
        assert guardada["estado"] == "postulada"
        assert guardada["fecha"] == "2026-11-06"
        assert guardada["enlace"] == "https://x.test/1"
        assert guardada["notas"] == "nota persistente"
        assert postulaciones.contar(otra)["postulada"] == 1
    finally:
        otra.close()


def test_csrf_obligatorio(cliente, entorno, oferta):
    assert cliente.post(f"/oferta/{oferta}/postulacion",
                        data={"csrf": "malo"}).status_code == 400
    assert cliente.post(f"/oferta/{oferta}/postulacion/retirar",
                        data={"csrf": "malo"}).status_code == 400


def test_no_envia_nada_solo_anota(cliente, entorno, oferta):
    """La aplicación no postula: no hay ninguna llamada de red en el camino."""
    from buscador import fetch

    def prohibido(*a, **k):
        raise AssertionError("no debe salir a la red")

    original = fetch.descargar
    fetch.descargar = prohibido
    try:
        cliente.post(f"/oferta/{oferta}/postulacion",
                     data={"csrf": CSRF, "fecha": "2026-11-06"}, follow_redirects=False)
    finally:
        fetch.descargar = original
    assert postulaciones.obtener(entorno, oferta) is not None
