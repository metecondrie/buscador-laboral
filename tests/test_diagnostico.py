"""Regresión del diagnóstico de credenciales.

Cubre los cinco puntos que pidió el usuario:

1. una clave válida no se marca como incorrecta por su longitud o prefijo;
2. si la generación respondió 200 no se sugieren problemas de modelo ni de cuota;
3. el último resultado válido se distingue de los errores históricos, con fecha y
   huella de la credencial;
4. las respuestas de YouTube y Books no se interpretan como fallos de Gemini;
5. el registro separa generaciones exitosas de intentos fallidos.

Ninguna prueba toca la red ni credenciales reales: `_consultar` se reemplaza por
un doble y el aislamiento de conftest bloquea el almacén del sistema.
"""

from __future__ import annotations

import pytest

from buscador.ai import credenciales, diagnostico
from buscador.ai.proveedores import obtener

OK = {"http": 200, "ok": True, "estado": "OK", "razones": [], "mensaje": "", "cuerpo": {}}
INVALIDA = {"http": 400, "ok": False, "estado": "INVALID_ARGUMENT",
            "razones": ["API_KEY_INVALID"], "mensaje": "API key not valid.", "cuerpo": {}}
CUOTA = {"http": 429, "ok": False, "estado": "RESOURCE_EXHAUSTED",
         "razones": ["RESOURCE_EXHAUSTED"], "mensaje": "quota exceeded", "cuerpo": {}}
SIN_PERMISO = {"http": 403, "ok": False, "estado": "PERMISSION_DENIED",
               "razones": ["PERMISSION_DENIED"], "mensaje": "API not enabled", "cuerpo": {}}
CONTROL_401 = {"http": 401, "ok": False, "estado": "UNAUTHENTICATED",
               "razones": ["CREDENTIALS_MISSING"],
               "mensaje": "API keys are not supported by this API. Expected OAuth2 access token.",
               "cuerpo": {}}
CONTROL_500 = {"http": 500, "ok": False, "estado": "INTERNAL",
               "razones": [], "mensaje": "backend error", "cuerpo": {}}

CATALOGO_OK = {**OK, "cuerpo": {"models": [
    {"name": f"models/{m.id}", "supportedGenerationMethods": ["generateContent"]}
    for m in obtener("gemini").modelos
]}}

# Clave de mentira con formato no estándar: 53 caracteres y sin prefijo AIza.
CLAVE_RARA = "AQ.Ab8RN6" + "x" * 45
CLAVE_ENV = "clave-de-entorno-para-pruebas"


def simular(catalogo=OK, generacion=OK, youtube=CONTROL_401, books=CONTROL_401):
    """Doble de `_consultar` que responde según el endpoint."""
    def consultar(url, clave, cuerpo=None):
        if "generateContent" in url:
            return dict(generacion)
        if "v1beta/models" in url:
            return dict(catalogo)
        if "/v1/models" in url:
            return dict(catalogo)
        if "youtube" in url:
            return dict(youtube)
        if "books" in url:
            return dict(books)
        return dict(INVALIDA)
    return consultar


@pytest.fixture
def con_clave_rara(monkeypatch):
    monkeypatch.setattr(credenciales, "_leer_credencial", lambda proveedor: CLAVE_RARA)


# --- 1. formato no determina validez ---------------------------------------

def test_clave_valida_con_formato_no_estandar_no_se_marca_invalida(entorno, con_clave_rara, monkeypatch):
    monkeypatch.setattr(diagnostico, "_consultar", simular(catalogo=CATALOGO_OK))

    datos = diagnostico.diagnosticar(entorno, "gemini")

    assert datos["estado"] == "funciona"
    assert datos["ok"] is True
    assert datos["clave"]["formato_conocido"] is False
    assert datos["clave"]["longitud"] == len(CLAVE_RARA)
    assert "no determina la validez" in datos["clave"]["nota_formato"]
    assert "invalid" not in datos["conclusion"].lower()


def test_clave_valida_con_formato_estandar(entorno, monkeypatch):
    monkeypatch.setattr(credenciales, "_leer_credencial", lambda p: "AIza" + "A" * 35)
    monkeypatch.setattr(diagnostico, "_consultar", simular(catalogo=CATALOGO_OK))
    datos = diagnostico.diagnosticar(entorno, "gemini")
    assert datos["estado"] == "funciona"
    assert datos["clave"]["formato_conocido"] is True


# --- 2. generación 200 no sugiere modelo ni cuota --------------------------

def test_generacion_200_no_sugiere_problemas_de_modelo_ni_cuota(entorno, con_clave_rara, monkeypatch):
    monkeypatch.setattr(diagnostico, "_consultar", simular(catalogo=CATALOGO_OK))

    datos = diagnostico.diagnosticar(entorno, "gemini")
    texto = datos["conclusion"].lower()

    assert "funciona" in texto
    assert "cuota" not in texto
    assert "agotada" not in texto
    assert "no está disponible" not in texto
    assert datos["modelos"]["presentes"] == [
        "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash"]


def test_generacion_ok_con_catalogo_caido_sigue_siendo_valida(entorno, con_clave_rara, monkeypatch):
    monkeypatch.setattr(diagnostico, "_consultar", simular(catalogo=INVALIDA))
    datos = diagnostico.diagnosticar(entorno, "gemini")
    assert datos["estado"] == "funciona"
    assert "sólo falló el listado" in datos["conclusion"]


# --- 3. último válido vs errores históricos --------------------------------

def test_historial_separa_ultimo_valido_de_errores_de_otra_clave(entorno):
    with entorno:
        for estado, huella in (("invalida", "vieja1111111"), ("invalida", "vieja1111111"),
                               ("funciona", "nueva2222222")):
            entorno.execute(
                "INSERT INTO ai_model_checks (proveedor, estado, detalle, consumio_cuota,"
                " creado_en, huella_credencial) VALUES ('gemini',?,?,0,?,?)",
                (estado, "prueba", "2026-11-07T01:00:00Z", huella),
            )

    datos = diagnostico._historial(entorno, "nueva2222222")

    assert datos["ultimo_valido"]["huella_credencial"] == "nueva2222222"
    assert datos["errores_de_otra_clave"] == 2
    actual = next(c for c in datos["por_estado"] if c["huella"] == "nueva2222222")
    assert actual["es_actual"] is True


def test_diagnostico_incluye_historial_con_huella(entorno, con_clave_rara, monkeypatch):
    monkeypatch.setattr(diagnostico, "_consultar", simular(catalogo=CATALOGO_OK))
    datos = diagnostico.diagnosticar(entorno, "gemini")

    assert datos["historial"]["ultimo_valido"]["huella_credencial"] == datos["clave"]["huella"]
    assert datos["historial"]["por_estado"][0]["es_actual"] is True


# --- 4. YouTube y Books no son Gemini --------------------------------------

def test_controles_401_no_aplican_y_no_afectan_la_conclusion(entorno, con_clave_rara, monkeypatch):
    monkeypatch.setattr(diagnostico, "_consultar", simular(catalogo=CATALOGO_OK))

    datos = diagnostico.diagnosticar(entorno, "gemini")
    controles = [e for e in datos["endpoints"] if e["tipo"] == "control"]

    assert datos["estado"] == "funciona"
    assert controles and all(c["aplicable"] is False for c in controles)
    assert all("no aplica" in c["nota"] for c in controles)
    assert "error" not in datos["conclusion"].lower()


def test_control_caido_tampoco_afecta(entorno, con_clave_rara, monkeypatch):
    monkeypatch.setattr(diagnostico, "_consultar",
                        simular(catalogo=CATALOGO_OK, youtube=CONTROL_500, books=CONTROL_500))
    datos = diagnostico.diagnosticar(entorno, "gemini")
    assert datos["estado"] == "funciona"
    assert "control informativo" in controls_nota(datos)


def controls_nota(datos: dict) -> str:
    return " ".join(e.get("nota") or "" for e in datos["endpoints"] if e["tipo"] == "control")


def test_solo_gemini_decide_la_conclusion(entorno, con_clave_rara, monkeypatch):
    """Controles OK y Gemini caído: la conclusión debe ser negativa igual."""
    monkeypatch.setattr(diagnostico, "_consultar",
                        simular(catalogo=INVALIDA, generacion=INVALIDA, youtube=OK, books=OK))
    datos = diagnostico.diagnosticar(entorno, "gemini")
    assert datos["estado"] == "invalida"
    assert "no reconoce esta clave" in datos["conclusion"]


# --- estados específicos ----------------------------------------------------

def test_cuota_agotada_no_es_clave_invalida(entorno, con_clave_rara, monkeypatch):
    monkeypatch.setattr(diagnostico, "_consultar",
                        simular(catalogo=CATALOGO_OK, generacion=CUOTA))
    datos = diagnostico.diagnosticar(entorno, "gemini")
    assert datos["estado"] == "cuota"
    assert "válida" in datos["conclusion"]
    assert "invalida" != datos["estado"]


def test_sin_permiso_se_distingue(entorno, con_clave_rara, monkeypatch):
    monkeypatch.setattr(diagnostico, "_consultar", simular(generacion=SIN_PERMISO))
    datos = diagnostico.diagnosticar(entorno, "gemini")
    assert datos["estado"] == "sin_permiso"


def test_sin_clave(entorno):
    datos = diagnostico.diagnosticar(entorno, "gemini")
    assert datos["estado"] == "sin_clave"
    assert datos["clave"]["presente"] is False
    assert datos["candidatas"] == []


def test_proveedor_desconocido(entorno):
    assert diagnostico.diagnosticar(entorno, "inexistente")["ok"] is False


def test_error_al_enumerar_candidatas_no_rompe(entorno, con_clave_rara, monkeypatch):
    monkeypatch.setattr(diagnostico, "_consultar", simular(catalogo=CATALOGO_OK))

    def romper(proveedor, variable=None):
        raise OSError("almacén no disponible")

    monkeypatch.setattr(credenciales, "candidatas", romper)
    datos = diagnostico.diagnosticar(entorno, "gemini")

    assert datos["ok"] is True
    assert "no se pudieron enumerar" in datos["aviso"]


def test_queda_registrado_con_huella(entorno, con_clave_rara, monkeypatch):
    monkeypatch.setattr(diagnostico, "_consultar", simular(catalogo=CATALOGO_OK))
    datos = diagnostico.diagnosticar(entorno, "gemini")

    fila = entorno.execute(
        "SELECT estado, huella_credencial, consumio_cuota FROM ai_model_checks"
        " ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert fila["estado"] == "funciona"
    assert fila["huella_credencial"] == datos["clave"]["huella"]
    assert fila["consumio_cuota"] == 1
    assert "AIza" not in (fila["huella_credencial"] or "")


def test_clave_no_aparece_en_el_resultado(entorno, con_clave_rara, monkeypatch):
    monkeypatch.setattr(diagnostico, "_consultar", simular(catalogo=CATALOGO_OK))
    datos = diagnostico.diagnosticar(entorno, "gemini")
    assert CLAVE_RARA not in str(datos)
