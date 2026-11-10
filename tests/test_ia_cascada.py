"""Cascada de modelos: valores por defecto, persistencia y reinicios.

El incidente: la cascada aparecía con un solo modelo (`gemini-3.5-flash-lite`)
aunque estaba configurada con tres. La causa no fue una migración ni un reinicio:
`tools/verificar_interfaz.py` enviaba el formulario de IA con una cascada de un
modelo y, en cada verificación, reducía la configuración real.

Estas pruebas fijan tres cosas:

1. Una instalación nueva arranca con los tres modelos soportados.
2. Un valor vacío no es una elección: se rellena (bases migradas desde v9).
3. Lo que el usuario guarda se respeta y **no se reduce** al reiniciar.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from buscador import config, db
from buscador.ai import CASCADA_POR_DEFECTO, Politica, parsear
from buscador.web import crear_app

CSRF = "c"
TRES = ("gemini:gemini-3.5-flash-lite", "gemini:gemini-3.6-flash", "gemini:gemini-3.8-flash")


@pytest.fixture
def cliente(entorno):
    cliente = TestClient(crear_app(token="t", csrf=CSRF), base_url="http://127.0.0.1")
    cliente.get("/entrar?token=t")
    return cliente


def _cascada(conn) -> tuple[str, ...]:
    return Politica.desde_ajustes(conn).cascada


# --- valores por defecto ----------------------------------------------------

def test_el_predeterminado_son_los_tres_modelos_soportados():
    assert CASCADA_POR_DEFECTO == TRES
    assert tuple(config.AJUSTES_POR_DEFECTO["ia_cascada"].split(",")) == TRES
    for referencia in TRES:
        assert parsear(referencia) is not None, f"referencia inválida: {referencia}"


def test_una_base_nueva_arranca_con_tres_modelos(entorno):
    assert _cascada(entorno) == TRES
    assert db.ajuste(entorno, "ia_cascada") == ",".join(TRES)


# --- migración y reinicio ---------------------------------------------------

def test_una_cascada_vacia_se_rellena_al_inicializar(entorno, monkeypatch, tmp_path):
    """Base migrada desde v9: `ia_cascada=''` mostraba el campo en blanco."""
    db.guardar_ajuste(entorno, "ia_cascada", "")
    assert db.ajuste(entorno, "ia_cascada") == ""

    db.inicializar(config.rutas().db)   # lo que hace cada arranque

    assert _cascada(entorno) == TRES


def test_un_valor_elegido_por_el_usuario_sobrevive_al_reinicio(entorno):
    elegida = "gemini:gemini-3.6-flash,gemini:gemini-3.8-flash"
    db.guardar_ajuste(entorno, "ia_cascada", elegida)

    for _ in range(3):                  # tres reinicios seguidos
        db.inicializar(config.rutas().db)

    assert db.ajuste(entorno, "ia_cascada") == elegida
    assert _cascada(entorno) == tuple(elegida.split(","))


def test_abrir_la_aplicacion_no_toca_la_cascada(entorno):
    antes = db.ajuste(entorno, "ia_cascada")
    crear_app(token="t", csrf=CSRF)
    crear_app(token="t", csrf=CSRF)
    assert db.ajuste(entorno, "ia_cascada") == antes


# --- formulario -------------------------------------------------------------

def test_guardar_los_tres_modelos_los_persiste(cliente, entorno):
    respuesta = cliente.post("/ia", data={
        "csrf": CSRF, "accion": "guardar", "cascada": "\n".join(TRES),
        "presupuesto": "0", "limite_llamadas": "20",
        "datos": "0", "cache": "1", "proveedores": ["gemini"],
    }, follow_redirects=False)

    assert respuesta.status_code == 303
    assert _cascada(entorno) == TRES


def test_la_pantalla_muestra_la_cascada_completa(cliente, entorno):
    html = cliente.get("/config").text
    for referencia in TRES:
        assert referencia.split(":", 1)[1] in html


def test_guardar_conserva_el_orden_y_descarta_lo_desconocido(cliente, entorno):
    cliente.post("/ia", data={
        "csrf": CSRF, "accion": "guardar",
        "cascada": "gemini:gemini-3.8-flash\ngemini:no-existe\ngemini:gemini-3.5-flash-lite",
        "presupuesto": "0", "limite_llamadas": "20", "datos": "0", "cache": "1",
        "proveedores": ["gemini"],
    }, follow_redirects=False)

    assert _cascada(entorno) == ("gemini:gemini-3.8-flash", "gemini:gemini-3.5-flash-lite")


def test_una_cascada_de_un_modelo_no_se_rellena_sola(entorno):
    """Reducirla a mano es una decisión válida: no se revierte por sistema."""
    db.guardar_ajuste(entorno, "ia_cascada", "gemini:gemini-3.5-flash-lite")
    db.inicializar(config.rutas().db)
    assert _cascada(entorno) == ("gemini:gemini-3.5-flash-lite",)


def test_los_otros_proveedores_siguen_deshabilitados(entorno):
    politica = Politica.desde_ajustes(entorno)
    assert politica.proveedores_habilitados == frozenset({"gemini"})
    assert politica.presupuesto_mensual_usd == 0.0
    assert politica.autorizo_pago is False
