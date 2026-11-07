"""La interfaz de IA no debe devolver HTTP 500 en ninguna acción.

Se ejercitan las rutas reales con dobles de credenciales y de red: no se lee,
escribe ni borra ninguna credencial del sistema.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from buscador import db
from buscador.ai import credenciales, diagnostico
from buscador.ai.cliente import Cliente
from buscador.web import crear_app

TOKEN = "token-ia"
CSRF = "csrf-ia"

OK = {"http": 200, "ok": True, "razones": [], "mensaje": ""}
INVALIDA = {"http": 400, "ok": False, "razones": ["API_KEY_INVALID"],
            "mensaje": "API key not found."}


@pytest.fixture
def cliente_http(entorno, monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(credenciales, "_guardar_credencial", lambda proveedor, clave: True)
    monkeypatch.setattr(credenciales, "_leer_credencial", lambda proveedor: None)
    monkeypatch.setattr(credenciales, "_borrar_credencial", lambda proveedor: True)
    monkeypatch.setattr(credenciales, "_ruta_dpapi", lambda proveedor: tmp_path / "no.bin")
    # Mensajes largos a propósito: con respuestas cortas el JSON entraba en el
    # límite y el truncado pasaba desapercibido.
    detallada = dict(INVALIDA)
    detallada["mensaje"] = ("API key not valid. Please pass a valid API key. " * 6).strip()
    monkeypatch.setattr(diagnostico, "_consultar",
                        lambda url, clave, cabecera=True, cuerpo=None: dict(detallada))

    app = crear_app(token=TOKEN, csrf=CSRF)
    cliente = TestClient(app, base_url="http://127.0.0.1")
    cliente.get("/entrar?token=" + TOKEN)
    return cliente


def test_configuracion_renderiza(cliente_http):
    respuesta = cliente_http.get("/config")
    assert respuesta.status_code == 200
    assert "Internal Server Error" not in respuesta.text
    assert "Inteligencia artificial" in respuesta.text


def test_get_ia_no_es_500(cliente_http):
    """`/ia` sólo acepta POST: GET debe ser 405, nunca 500."""
    respuesta = cliente_http.get("/ia")
    assert respuesta.status_code in (200, 405)
    assert respuesta.status_code != 500


def test_accion_diagnosticar(cliente_http, entorno):
    respuesta = cliente_http.post("/ia", data={"csrf": CSRF, "accion": "diagnosticar",
                                               "proveedor": "gemini"},
                                  follow_redirects=False)
    assert respuesta.status_code == 303
    guardado = entorno.execute(
        "SELECT valor FROM settings WHERE clave='ia_ultimo_diagnostico'"
    ).fetchone()
    assert guardado is not None and "conclusion" in guardado["valor"]


def test_pagina_muestra_el_diagnostico(cliente_http):
    cliente_http.post("/ia", data={"csrf": CSRF, "accion": "diagnosticar",
                                   "proveedor": "gemini"}, follow_redirects=False)
    respuesta = cliente_http.get("/config")
    assert respuesta.status_code == 200
    assert "Diagnóstico de la credencial" in respuesta.text


def test_accion_verificar(cliente_http, entorno, monkeypatch):
    monkeypatch.setattr(Cliente, "verificar_modelos", lambda self, proveedor: {
        "ok": True, "estado": "verificada", "presentes": ["gemini-3.5-flash-lite"],
        "ausentes": [], "total_proveedor": 40,
    })
    respuesta = cliente_http.post("/ia", data={"csrf": CSRF, "accion": "verificar",
                                               "proveedor": "gemini"},
                                  follow_redirects=False)
    assert respuesta.status_code == 303
    guardado = entorno.execute(
        "SELECT valor FROM settings WHERE clave='ia_ultima_verificacion'"
    ).fetchone()
    assert guardado is not None


def test_accion_guardar_configuracion(cliente_http, entorno):
    respuesta = cliente_http.post("/ia", data={
        "csrf": CSRF, "accion": "guardar",
        "cascada": "gemini:gemini-3.5-flash-lite\ngemini:gemini-3.6-flash\ngemini:no-existe",
        "presupuesto": "0", "limite_llamadas": "10",
        "datos": "1", "cache": "1", "cuenta_cloudflare": "",
        "proveedores": ["gemini"],
    }, follow_redirects=False)
    assert respuesta.status_code == 303
    cascada = db.ajuste(entorno, "ia_cascada")
    assert "no-existe" not in cascada
    assert "gemini-3.6-flash" in cascada
    assert db.ajuste(entorno, "ia_proveedores_habilitados") == "gemini"


def test_accion_guardar_clave(cliente_http, entorno):
    respuesta = cliente_http.post("/ia", data={
        "csrf": CSRF, "accion": "clave", "proveedor": "gemini",
        "clave": "AIza" + "Z" * 35,
    }, follow_redirects=False)
    assert respuesta.status_code == 303
    estado = entorno.execute(
        "SELECT valor FROM settings WHERE clave='ia_estado_gemini'"
    ).fetchone()
    assert estado is not None and estado["valor"] == "presente"
    # La clave nunca queda en la base.
    fila = entorno.execute(
        "SELECT COUNT(*) FROM settings WHERE valor LIKE '%AIza%'"
    ).fetchone()[0]
    assert fila == 0


def test_accion_borrar_clave(cliente_http, entorno):
    respuesta = cliente_http.post("/ia", data={
        "csrf": CSRF, "accion": "borrar-clave", "proveedor": "gemini",
    }, follow_redirects=False)
    assert respuesta.status_code == 303
    estado = entorno.execute(
        "SELECT valor FROM settings WHERE clave='ia_estado_gemini'"
    ).fetchone()
    assert estado is not None and estado["valor"] == "ausente"


@pytest.mark.parametrize("accion", ["habilitar", "deshabilitar"])
def test_habilitar_y_deshabilitar(cliente_http, entorno, accion):
    respuesta = cliente_http.post("/ia", data={"csrf": CSRF, "accion": accion},
                                  follow_redirects=False)
    assert respuesta.status_code == 303
    esperado = "1" if accion == "habilitar" else "0"
    assert db.ajuste(entorno, "ia_habilitada") == esperado


def test_accion_sin_csrf_es_400_no_500(cliente_http):
    respuesta = cliente_http.post("/ia", data={"csrf": "malo", "accion": "diagnosticar"})
    assert respuesta.status_code == 400


def test_accion_desconocida_no_rompe(cliente_http):
    respuesta = cliente_http.post("/ia", data={"csrf": CSRF, "accion": "inventada"},
                                  follow_redirects=False)
    assert respuesta.status_code == 303
