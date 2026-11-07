"""Módulo de IA: catálogo, cascada, cuotas, caché, credenciales y validación.

Ninguna prueba hace llamadas reales: el transporte se inyecta. La única prueba
que toca el sistema operativo es la del Administrador de credenciales, y usa un
objetivo temporal que borra al terminar.
"""

from __future__ import annotations

import json
import sys

import pytest

from buscador import db
from buscador.ai import cache as cache_mod
from buscador.ai import cola, credenciales, cuotas
from buscador.ai.cliente import Cliente, Politica, Rechazo, SinCuota
from buscador.ai.esquema import desde_texto
from buscador.ai.proveedores import (CASCADA_POR_DEFECTO, PROVEEDORES,
                                     PROVEEDORES_ACTIVOS, catalogo, obtener, parsear)

ANALISIS_OK = {
    "categoria": "Data Analyst",
    "seniority": "junior",
    "habilidades_obligatorias": ["SQL", "Excel"],
    "habilidades_deseables": ["Power BI"],
    "anios_experiencia": 1,
    "idiomas": ["español", "inglés B2"],
    "elegibilidad_territorial": "mundial",
    "paises_restringidos": [],
    "modalidad": "remote",
    "salario": {"minimo": None, "maximo": None, "moneda": None, "periodo": "desconocido"},
    "evidencia": [{"campo": "modalidad", "cita": "fully remote"}],
    "incertidumbres": [],
    "explicacion": "Puesto remoto de análisis con SQL y Excel.",
    "confianza": 0.8,
}


def _respuesta_openai(texto: str | None = None, tokens: int = 20) -> dict:
    return {
        "choices": [{"message": {"content": texto or json.dumps(ANALISIS_OK, ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": tokens},
    }


def _respuesta_gemini(texto: str | None = None, tokens: int = 20) -> dict:
    return {
        "candidates": [{"content": {"parts": [
            {"text": texto or json.dumps(ANALISIS_OK, ensure_ascii=False)}]}}],
        "usageMetadata": {"candidatesTokenCount": tokens},
    }


def _transporte(respuesta=None, registro: list | None = None, error: Exception | None = None):
    """Devuelve la forma que corresponde a cada familia, según la URL."""
    def enviar(url, headers, cuerpo, timeout, metodo="POST"):
        if registro is not None:
            registro.append({"url": url, "headers": headers, "cuerpo": cuerpo, "metodo": metodo})
        if error is not None:
            raise error
        if respuesta is not None:
            return respuesta
        return _respuesta_gemini() if "googleapis" in url else _respuesta_openai()
    return enviar


def _politica(**cambios) -> Politica:
    base = dict(habilitada=True, permitir_datos_de_ofertas=True,
                cascada=("gemini:gemini-3.5-flash-lite", "groq:openai/gpt-oss-20b"))
    base.update(cambios)
    return Politica(**base)


# --- catálogo ---------------------------------------------------------------

def test_identificadores_verificados():
    gemini = obtener("gemini")
    assert [m.id for m in gemini.modelos] == [
        "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash"]
    groq = obtener("groq")
    assert [m.id for m in groq.modelos] == ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
    deepseek = obtener("deepseek")
    assert deepseek.modelos[0].id == "deepseek-flash"
    assert deepseek.requiere_pago is True


def test_cascada_por_defecto_es_solo_gemini():
    assert CASCADA_POR_DEFECTO == (
        "gemini:gemini-3.5-flash-lite",
        "gemini:gemini-3.6-flash",
        "gemini:gemini-3.8-flash",
    )
    for referencia in CASCADA_POR_DEFECTO:
        proveedor, modelo = parsear(referencia)
        assert proveedor.clave == "gemini"
        assert modelo.dentro_cuota_gratuita is True
        assert proveedor.requiere_pago is False


def test_otros_proveedores_quedan_desactivados():
    """Groq, Cloudflare y DeepSeek siguen en el catálogo, pero no en la cascada."""
    activos = PROVEEDORES_ACTIVOS
    assert activos == frozenset({"gemini"})
    assert set(PROVEEDORES) == {"gemini", "groq", "cloudflare", "deepseek"}
    assert not any("groq" in r or "cloudflare" in r or "deepseek" in r
                   for r in CASCADA_POR_DEFECTO)


def test_catalogo_plano():
    filas = catalogo()
    assert len(filas) == 8
    assert all("referencia" in f and "gratuito" in f for f in filas)


def test_parsear_rechaza_desconocidos():
    assert parsear("gemini:no-existe") is None
    assert parsear("otro:modelo") is None
    assert parsear("sin-dos-puntos") is None


# --- credenciales -----------------------------------------------------------

def test_enmascarar_no_expone_la_clave():
    assert credenciales.enmascarar("sk-1234567890") == "•" * 9 + "7890"
    assert "123456" not in credenciales.enmascarar("sk-1234567890")


def test_credencial_dpapi_ida_y_vuelta(entorno, monkeypatch):
    """Fuerza el respaldo cifrado para no tocar el almacén del sistema."""
    monkeypatch.setattr(credenciales, "_guardar_credencial", lambda p, s: False)
    monkeypatch.setattr(credenciales, "_leer_credencial", lambda p: None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    resultado = credenciales.guardar("groq", "gsk-prueba-123")
    assert resultado["almacen"] == "dpapi-archivo"
    assert credenciales.leer("groq", "GROQ_API_KEY") == "gsk-prueba-123"
    assert credenciales.origen("groq", "GROQ_API_KEY") == "dpapi-archivo"
    credenciales.borrar("groq")
    assert credenciales.leer("groq", "GROQ_API_KEY") is None


@pytest.mark.skipif(sys.platform != "win32", reason="almacén local de Windows")
def test_credencial_ida_y_vuelta_aislada(entorno):
    objetivo = "prueba-buscador-temporal"
    try:
        deposito = credenciales.guardar(objetivo, "clave-temporal-9876")
        assert deposito["almacen"] in {"credenciales-windows", "dpapi-archivo"}
        assert credenciales.leer(objetivo) == "clave-temporal-9876"
    finally:
        credenciales.borrar(objetivo)
    assert credenciales.leer(objetivo) is None


def test_variable_de_entorno_se_usa_si_no_hay_almacen(entorno, monkeypatch, tmp_path):
    monkeypatch.setattr(credenciales, "_leer_credencial", lambda proveedor: None)
    monkeypatch.setattr(credenciales, "_ruta_dpapi", lambda proveedor: tmp_path / "no.bin")
    monkeypatch.setenv("GROQ_API_KEY", "desde-entorno")
    assert credenciales.leer("groq", "GROQ_API_KEY") == "desde-entorno"
    assert credenciales.origen("groq", "GROQ_API_KEY") == "variable-entorno"


def test_el_almacen_gana_sobre_la_variable_de_entorno(entorno, monkeypatch, tmp_path):
    """Cargar una clave desde la interfaz debe imponerse a una variable vieja."""
    monkeypatch.setattr(credenciales, "_leer_credencial", lambda proveedor: "clave-del-almacen")
    monkeypatch.setattr(credenciales, "_ruta_dpapi", lambda proveedor: tmp_path / "no.bin")
    monkeypatch.setenv("GROQ_API_KEY", "clave-vieja-del-entorno")
    assert credenciales.leer("groq", "GROQ_API_KEY") == "clave-del-almacen"
    assert credenciales.origen("groq", "GROQ_API_KEY") == "credenciales-windows"


def test_la_huella_activa_gana_sobre_todo(entorno, monkeypatch, tmp_path):
    monkeypatch.setattr(credenciales, "_leer_credencial", lambda proveedor: "clave-del-almacen")
    monkeypatch.setattr(credenciales, "_ruta_dpapi", lambda proveedor: tmp_path / "no.bin")
    monkeypatch.setenv("GROQ_API_KEY", "clave-del-entorno")
    huella_entorno = credenciales.candidatas("groq", "GROQ_API_KEY")[1]["huella"]
    resuelta = credenciales.resolver("groq", "GROQ_API_KEY", huella_entorno)
    assert resuelta["valor"] == "clave-del-entorno"
    assert resuelta["origen"] == "variable-entorno"


# --- cuotas -----------------------------------------------------------------

def test_cuota_por_minuto_se_agota(entorno):
    proveedor, modelo = parsear("groq:openai/gpt-oss-20b")
    db.guardar_ajuste(entorno, "ia_limite_groq_rpm", "2")
    for _ in range(2):
        cuotas.registrar(entorno, proveedor.clave, modelo.id, 10, 10)
    ok, motivo = cuotas.verificar(entorno, proveedor, modelo)
    assert ok is False
    assert "minuto" in motivo


def test_cuota_diaria_se_agota(entorno):
    proveedor, modelo = parsear("groq:openai/gpt-oss-120b")
    db.guardar_ajuste(entorno, "ia_limite_groq_rpd", "1")
    cuotas.registrar(entorno, proveedor.clave, modelo.id, 5, 5)
    ok, motivo = cuotas.verificar(entorno, proveedor, modelo)
    assert ok is False
    assert "diario" in motivo


def test_resumen_de_cuotas(entorno):
    proveedor, modelo = parsear("groq:openai/gpt-oss-20b")
    cuotas.registrar(entorno, proveedor.clave, modelo.id, 100, 50)
    datos = cuotas.resumen(entorno)
    assert datos["total_peticiones"] == 1
    assert datos["total_tokens"] == 150


# --- caché ------------------------------------------------------------------

def test_cache_evita_segunda_llamada(entorno, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave-de-prueba")
    registro: list = []
    cliente = Cliente(entorno, _politica(), transporte=_transporte(registro=registro))
    primera = cliente.analizar("contenido", "instrucción", "hash-1", job_id="j1")
    segunda = cliente.analizar("contenido", "instrucción", "hash-1", job_id="j1")
    assert primera["cache"] is False
    assert segunda["cache"] is True
    assert len(registro) == 1
    assert cache_mod.estadisticas(entorno)["reutilizaciones"] == 1


def test_cache_distingue_contenido(entorno, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave-de-prueba")
    registro: list = []
    cliente = Cliente(entorno, _politica(), transporte=_transporte(registro=registro))
    cliente.analizar("a", "i", "hash-a")
    cliente.analizar("a", "i", "hash-b")
    assert len(registro) == 2


# --- cliente ----------------------------------------------------------------

def test_deshabilitada_rechaza(entorno):
    cliente = Cliente(entorno, _politica(habilitada=False))
    with pytest.raises(Rechazo) as excinfo:
        cliente.analizar("x", "y", "h")
    assert excinfo.value.codigo == "no_habilitada"


def test_sin_permiso_de_datos_rechaza(entorno, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave")
    cliente = Cliente(entorno, _politica(permitir_datos_de_ofertas=False))
    with pytest.raises(Rechazo) as excinfo:
        cliente.analizar("x", "y", "h")
    assert excinfo.value.codigo == "datos_no_autorizados"


def test_sin_credencial_no_hay_candidatos(entorno, monkeypatch):
    from pathlib import Path

    for variable in ("GEMINI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(credenciales, "_leer_credencial", lambda p: None)
    monkeypatch.setattr(credenciales, "_ruta_dpapi", lambda p: Path("/no/existe"))
    cliente = Cliente(entorno, _politica())
    with pytest.raises(SinCuota):
        cliente.analizar("x", "y", "h")


def test_429_pasa_al_siguiente_modelo(entorno, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave")
    monkeypatch.setenv("GROQ_API_KEY", "clave")
    llamadas: list = []

    def transporte(url, headers, cuerpo, timeout, metodo="POST"):
        llamadas.append(url)
        if "googleapis" in url:
            error = RuntimeError("HTTP 429")
            error.codigo_http = 429
            error.reintentar_en = 30
            raise error
        return _respuesta_openai()

    # Groq está desactivado por defecto: acá se habilita a propósito para probar el fallback.
    cliente = Cliente(entorno, _politica(proveedores_habilitados=frozenset({"gemini", "groq"})),
                      transporte=transporte)
    resultado = cliente.analizar("x", "y", "h-429")
    assert resultado["proveedor"] == "groq"
    assert len(llamadas) == 2
    assert resultado["fallos_previos"][0]["referencia"].startswith("gemini")


def test_pago_bloqueado_sin_autorizacion(entorno, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "clave")
    politica = _politica(cascada=("deepseek:deepseek-flash",),
                         proveedores_habilitados=frozenset({"deepseek"}))
    cliente = Cliente(entorno, politica)
    assert cliente.candidatos()[0].estado == "pago_no_autorizado"


def test_presupuesto_cero_bloquea_pago(entorno, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "clave")
    politica = _politica(cascada=("deepseek:deepseek-flash",),
                         proveedores_habilitados=frozenset({"deepseek"}),
                         autorizo_pago=True)
    cliente = Cliente(entorno, politica, transporte=_transporte())
    with pytest.raises((Rechazo, SinCuota)) as excinfo:
        cliente.analizar("x", "y", "h-pago")
    assert "presupuesto" in str(excinfo.value) or "cuota" in str(excinfo.value)


def test_llamada_registra_contabilidad(entorno, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave")
    cliente = Cliente(entorno, _politica(), transporte=_transporte())
    resultado = cliente.analizar("texto", "instrucción", "h-ledger", job_id="job-1")
    assert resultado["costo_usd"] == 0.0  # nivel gratuito
    fila = entorno.execute("SELECT * FROM ai_calls ORDER BY id DESC LIMIT 1").fetchone()
    assert fila["proveedor"] == "gemini"
    assert fila["estado"] == "ok"
    assert fila["cuota_consumida"] == 1
    assert fila["duracion_ms"] is not None
    assert entorno.execute("SELECT COUNT(*) FROM ai_usage").fetchone()[0] == 1


def test_respuesta_invalida_no_se_aplica(entorno, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave")
    cliente = Cliente(entorno, _politica(cascada=("gemini:gemini-3.5-flash-lite",)),
                      transporte=_transporte(_respuesta_gemini("no es json")))
    with pytest.raises(SinCuota):
        cliente.analizar("x", "y", "h-malo")
    estados = [f["estado"] for f in entorno.execute("SELECT estado FROM ai_calls").fetchall()]
    assert "invalida" in estados
    assert entorno.execute("SELECT COUNT(*) FROM ai_analyses").fetchone()[0] == 0


def test_cuerpo_gemini_correcto(entorno, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave")
    registro: list = []
    cliente = Cliente(entorno, _politica(cascada=("gemini:gemini-3.6-flash",)),
                      transporte=_transporte(registro=registro))
    cliente.analizar("texto", "instrucción", "h-cuerpo")
    cuerpo = registro[0]["cuerpo"]
    assert cuerpo["systemInstruction"]["parts"][0]["text"] == "instrucción"
    assert cuerpo["generationConfig"]["responseMimeType"] == "application/json"
    # La clave viaja por cabecera, nunca en la URL.
    assert "key=" not in registro[0]["url"]
    assert registro[0]["headers"].get("x-goog-api-key") == "clave"


def test_retry_after_se_interpreta():
    from buscador.ai.cliente import _retry_after

    assert _retry_after({"retry-after": "17"}) == 17
    assert _retry_after({}) is None


# --- esquema ----------------------------------------------------------------

def test_esquema_valida_y_normaliza():
    analisis = desde_texto("```json\n" + json.dumps(ANALISIS_OK) + "\n```")
    assert analisis.categoria == "Data Analyst"
    assert analisis.modalidad == "remote"
    assert analisis.confianza == 0.8


def test_categoria_fuera_de_lista_queda_en_none():
    datos = dict(ANALISIS_OK, categoria="Astronauta")
    assert desde_texto(json.dumps(datos)).categoria is None


def test_evidencia_es_obligatoria():
    datos = {k: v for k, v in ANALISIS_OK.items() if k != "evidencia"}
    with pytest.raises(Exception):
        desde_texto(json.dumps(datos))


def test_confianza_fuera_de_rango_falla():
    with pytest.raises(Exception):
        desde_texto(json.dumps(dict(ANALISIS_OK, confianza=1.7)))


def test_cita_inexistente_se_detecta():
    from buscador.ai.esquema import Evidencia, cita_presente

    texto = "We are hiring a data analyst. Fully remote position."
    assert cita_presente(Evidencia(campo="modalidad", cita="fully remote"), texto) is True
    assert cita_presente(Evidencia(campo="modalidad", cita="presencial en Berlín"), texto) is False


# --- cola -------------------------------------------------------------------

def test_cola_reclama_y_difiere(entorno):
    cola.encolar(entorno, "job-a", None, "pendiente", cola.PRIORIDAD_RAPIDA)
    tareas = cola.reclamar(entorno, limite=5, epoch="e1")
    assert len(tareas) == 1
    assert tareas[0]["estado"] == "running"
    assert cola.fallar(entorno, tareas[0]["id"], "error simulado", 60, 0) == "deferred"
    assert cola.contar(entorno)["deferred"] == 1


def test_cola_se_rinde_tras_varios_intentos(entorno):
    cola.encolar(entorno, "job-b", None, "pendiente")
    tareas = cola.reclamar(entorno, limite=1, epoch="e1")
    assert cola.fallar(entorno, tareas[0]["id"], "error", 1, cola.MAX_INTENTOS) == "failed"


def test_pausar_todo_difiere_la_cola(entorno):
    for indice in range(3):
        cola.encolar(entorno, f"job-{indice}", None, "pendiente")
    assert cola.pausar_todo(entorno, 600, "sin cuota") == 3
    assert cola.contar(entorno)["deferred"] == 3


def test_procesar_cola_sin_cuota_no_pierde_tareas(entorno, monkeypatch):
    """Sin credenciales, la cola se suspende y las tareas siguen ahí."""
    from pathlib import Path

    from buscador.ai import analisis

    for variable in ("GEMINI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(credenciales, "_leer_credencial", lambda p: None)
    monkeypatch.setattr(credenciales, "_ruta_dpapi", lambda p: Path("/no/existe"))
    cliente = Cliente(entorno, _politica())
    resumen = analisis.procesar_cola(entorno, cliente, maximo=3)
    assert resumen["procesadas"] == 0


def test_proveedores_declarados_en_catalogo():
    assert set(PROVEEDORES) == {"gemini", "groq", "cloudflare", "deepseek"}
    for proveedor in PROVEEDORES.values():
        assert proveedor.docs.startswith("https://")


def test_redactar_quita_claves_de_los_mensajes():
    from buscador.ai.cliente import redactar

    ejemplo = "fallo al llamar https://x?key=AIza" + "A" * 35 + "&otro=1"
    limpio = redactar(ejemplo)
    assert "AIza" not in limpio
    assert "[CLAVE-REDACTADA]" in limpio
    assert redactar("sin credenciales") == "sin credenciales"


def test_el_error_guardado_no_contiene_la_clave(entorno, monkeypatch):
    """Aunque el error traiga la clave, ai_calls no la guarda."""
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "B" * 35)

    def transporte(url, headers, cuerpo, timeout, metodo="POST"):
        raise RuntimeError(f"fallo con url {url}?key=AIza{'B' * 35}")

    cliente = Cliente(entorno, _politica(cascada=("gemini:gemini-3.5-flash-lite",)),
                      transporte=transporte)
    with pytest.raises(SinCuota):
        cliente.analizar("x", "y", "h-redaccion")
    errores = [f["error"] or "" for f in entorno.execute("SELECT error FROM ai_calls").fetchall()]
    assert errores
    assert all("AIza" not in e for e in errores)
    assert any("[CLAVE-REDACTADA]" in e for e in errores)


def test_redactar_quita_claves_de_los_mensajes():
    from buscador.ai.cliente import redactar

    ejemplo = "fallo al llamar https://x?key=AIza" + "A" * 35 + "&otro=1"
    limpio = redactar(ejemplo)
    assert "AIza" not in limpio
    assert "[CLAVE-REDACTADA]" in limpio
    assert redactar("sin credenciales") == "sin credenciales"


def test_el_error_guardado_no_contiene_la_clave(entorno, monkeypatch):
    """Aunque el error traiga la clave, ai_calls no la guarda."""
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "B" * 35)

    def transporte(url, headers, cuerpo, timeout, metodo="POST"):
        raise RuntimeError(f"fallo con url {url}?key=AIza{'B' * 35}")

    cliente = Cliente(entorno, _politica(cascada=("gemini:gemini-3.5-flash-lite",)),
                      transporte=transporte)
    with pytest.raises(SinCuota):
        cliente.analizar("x", "y", "h-redaccion")
    errores = [f["error"] or "" for f in entorno.execute("SELECT error FROM ai_calls").fetchall()]
    assert errores
    assert all("AIza" not in e for e in errores)
    assert any("[CLAVE-REDACTADA]" in e for e in errores)


def test_detecta_clave_tapada_por_variable_de_entorno(entorno, monkeypatch):
    """Una variable vieja no debe ocultar la clave recién guardada."""
    monkeypatch.setattr(credenciales, "_guardar_credencial", lambda p, s: True)
    monkeypatch.setattr(credenciales, "_leer_credencial", lambda p: "AIza" + "C" * 35)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "D" * 35)

    lista = credenciales.candidatas("gemini", "GEMINI_API_KEY")
    assert len(lista) == 2
    # El almacén va primero: es la acción explícita del usuario.
    assert lista[0]["origen"] == "credenciales-windows"
    assert lista[1]["origen"] == "variable-entorno"
    aviso = credenciales.hay_sombra("gemini", "GEMINI_API_KEY")
    assert aviso and "tapada" in aviso
    assert "AIza" not in aviso  # nunca el valor


def test_sin_sombra_cuando_es_la_misma_clave(entorno, monkeypatch):
    monkeypatch.setattr(credenciales, "_leer_credencial", lambda p: None)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "E" * 35)
    assert len(credenciales.candidatas("gemini", "GEMINI_API_KEY")) == 1
    assert credenciales.hay_sombra("gemini", "GEMINI_API_KEY") is None


def test_detecta_clave_tapada_por_variable_de_entorno(entorno, monkeypatch):
    """Una variable vieja no debe ocultar la clave recién guardada."""
    monkeypatch.setattr(credenciales, "_guardar_credencial", lambda p, s: True)
    monkeypatch.setattr(credenciales, "_leer_credencial", lambda p: "AIza" + "C" * 35)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "D" * 35)

    lista = credenciales.candidatas("gemini", "GEMINI_API_KEY")
    assert len(lista) == 2
    # El almacén va primero: es la acción explícita del usuario.
    assert lista[0]["origen"] == "credenciales-windows"
    assert lista[1]["origen"] == "variable-entorno"
    aviso = credenciales.hay_sombra("gemini", "GEMINI_API_KEY")
    assert aviso and "tapada" in aviso
    assert "AIza" not in aviso  # nunca el valor


def test_sin_sombra_cuando_es_la_misma_clave(entorno, monkeypatch):
    monkeypatch.setattr(credenciales, "_leer_credencial", lambda p: None)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "E" * 35)
    assert len(credenciales.candidatas("gemini", "GEMINI_API_KEY")) == 1
    assert credenciales.hay_sombra("gemini", "GEMINI_API_KEY") is None


# --- registro de cuota: rechazo no es consumo --------------------------------

def test_prueba_rechazada_no_cuenta_cuota(entorno, monkeypatch):
    """Una petición rechazada no consume cuota ni debe parecer una generación."""
    monkeypatch.setenv("GEMINI_API_KEY", "clave")
    error = RuntimeError("HTTP 400: API key not valid")
    error.codigo_http = 400
    cliente = Cliente(entorno, _politica(), transporte=_transporte(error=error))

    resultado = cliente.probar_conexion("gemini:gemini-3.5-flash-lite")

    assert resultado["ok"] is False
    assert resultado["consumio_cuota"] is False
    fila = entorno.execute("SELECT * FROM ai_calls ORDER BY id DESC LIMIT 1").fetchone()
    assert fila["estado"] == "error"
    assert fila["cuota_consumida"] == 0
    assert fila["tokens_entrada"] == 0 and fila["tokens_salida"] == 0


def test_consumo_distingue_generaciones_de_intentos(entorno, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave")
    error = RuntimeError("HTTP 403: forbidden")
    error.codigo_http = 403
    Cliente(entorno, _politica(), transporte=_transporte(error=error)).probar_conexion(
        "gemini:gemini-3.5-flash-lite")
    Cliente(entorno, _politica(), transporte=_transporte()).analizar(
        "texto", "instrucción", "h-consumo")

    hoy = cliente_consumo(entorno)
    assert hoy["solicitudes_exitosas"] == 1
    assert hoy["intentos_fallidos"] == 1
    assert hoy["cuota_consumida"] == 1
    assert hoy["costo_usd"] == 0.0
    assert hoy["tokens_entrada"] > 0


def cliente_consumo(conn) -> dict:
    from buscador.ai.cliente import consumo as consumo_mod

    return consumo_mod(conn)["hoy"]


def test_verificar_modelos_no_pone_la_clave_en_la_url(entorno, monkeypatch):
    """Una clave en la URL termina en logs de proxy y en los mensajes de error."""
    monkeypatch.setenv("GEMINI_API_KEY", "clave-secreta-de-prueba")
    registro: list = []

    def transporte(url, headers, cuerpo, timeout, metodo="POST"):
        registro.append({"url": url, "headers": headers, "metodo": metodo})
        return {"models": [
            {"name": "models/gemini-3.5-flash-lite",
             "supportedGenerationMethods": ["generateContent"]},
        ]}

    cliente = Cliente(entorno, _politica(), transporte=transporte)
    datos = cliente.verificar_modelos("gemini")

    assert datos["ok"] is True
    assert len(registro) == 1
    assert "clave-secreta-de-prueba" not in registro[0]["url"]
    assert "key=" not in registro[0]["url"]
    assert registro[0]["headers"]["x-goog-api-key"] == "clave-secreta-de-prueba"
