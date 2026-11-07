"""Búsqueda manual con progreso real: concurrencia, recuperación y parciales.

Las pruebas no usan red: las fuentes son adaptadores falsos inyectados y la
corrida es la de verdad (`worker.correr`), así que lo que se verifica es el
circuito real de ingesta, clasificación y persistencia del progreso.

El progreso se lee siempre desde una conexión distinta de la que escribe, que es
la situación real: el trabajador corre en un hilo y la interfaz consulta desde
otro.
"""

from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from buscador import config, db, ingest, progreso, worker
from buscador.adapters.base import Observacion, ResultadoFuente
from buscador.web import crear_app


def _obs(sid: str, ext: str, titulo: str, empresa: str) -> Observacion:
    return Observacion(
        source_id=sid,
        external_id=ext,
        url=f"https://ejemplo.test/{ext}",
        titulo=titulo,
        empresa=empresa,
        descripcion_html="<p>SQL required. Python desirable.</p>",
        publicado_en="2026-11-02T00:00:00Z",
        region="Anywhere in the World",
        extra={"texto_plano": "SQL required. Python desirable. Excel. Power BI."},
    )


class Fuente:
    """Adaptador falso que registra cuándo se lo consultó."""

    def __init__(self, sid: str, ofertas: int = 1, revienta: bool = False,
                 al_consultar=None, titulo: str = "Data Analyst"):
        self.source_id = sid
        self.ofertas = ofertas
        self.revienta = revienta
        self.al_consultar = al_consultar
        self.titulo = titulo
        self.veces = 0

    def fetch(self, limite, cursor=None):
        self.veces += 1
        if self.al_consultar is not None:
            self.al_consultar(self)
        if self.revienta:
            raise RuntimeError("falla simulada de red")
        return ResultadoFuente(
            source_id=self.source_id,
            estado="success",
            observaciones=[
                _obs(self.source_id, f"{self.source_id}-{i}",
                     f"{self.titulo} {i}", f"Empresa {self.source_id} {i}")
                for i in range(self.ofertas)
            ],
        )


@pytest.fixture
def fuentes(monkeypatch):
    """Instala fuentes falsas y devuelve el diccionario para inspeccionarlas."""
    registro: dict[str, Fuente] = {}

    def instalar(**kwargs):
        for sid, opciones in kwargs.items():
            registro[sid] = Fuente(sid, **opciones)
        monkeypatch.setattr(worker.adapters, "obtener",
                            lambda sid: registro.get(sid) or Fuente(sid, ofertas=0))
        return registro

    return instalar


def _snapshot(run_id: int | None = None) -> dict:
    """Lectura desde otra conexión, como haría una pestaña cualquiera."""
    conn = db.conectar(config.rutas().db)
    try:
        return progreso.snapshot(conn, run_id)
    finally:
        conn.close()


# --- progreso real -----------------------------------------------------------

def test_progreso_sale_de_la_base_y_cuenta_fuentes_reales(entorno, perfil_id, fuentes):
    fuentes(F01={"ofertas": 2}, F02={"ofertas": 1}, F03={"revienta": True})

    resultado = worker.correr(causa="manual-ui", limite=5,
                              fuentes=["F01", "F02", "F03"], usar_mutex=False)

    assert resultado["estado"] == "ok"
    datos = _snapshot()
    assert datos["activo"] is False
    assert datos["estado"] == "completed"
    assert datos["fuentes"]["total"] == 3
    assert datos["fuentes"]["completadas"] == 2
    assert datos["fuentes"]["fallidas"] == 1
    assert datos["fuentes"]["pendientes"] == 0
    assert datos["fuentes"]["procesadas"] == 3
    assert datos["fuentes"]["fraccion"] == 1.0
    # El denominador no se estima: son las filas planificadas antes de consultar.
    assert entorno.execute("SELECT COUNT(*) FROM source_runs").fetchone()[0] == 3


def test_el_progreso_avanza_y_clasifica_antes_de_terminar(entorno, perfil_id, fuentes):
    """Cuando corre la segunda fuente, la primera ya dejó ofertas clasificadas."""
    visto: dict = {}

    def mirar(fuente):
        if fuente.source_id != "F02":
            return
        conn = db.conectar(config.rutas().db)
        try:
            visto["filas"] = [dict(f) for f in conn.execute(
                "SELECT source_id, estado FROM source_runs ORDER BY id").fetchall()]
            visto["corrida"] = dict(conn.execute(
                "SELECT estado, total_fuentes, heartbeat_at FROM runs ORDER BY id DESC LIMIT 1"
            ).fetchone())
            visto["analisis"] = conn.execute(
                "SELECT COUNT(*) FROM analyses WHERE obsoleto=0").fetchone()[0]
            visto["foto"] = progreso.snapshot(conn)
        finally:
            conn.close()

    fuentes(F01={"ofertas": 2}, F02={"ofertas": 1,
                                     "al_consultar": mirar})

    worker.correr(causa="manual-ui", limite=5, fuentes=["F01", "F02"], usar_mutex=False)

    # En plena corrida: F01 cerrada, F02 ejecutándose, F03 no existe.
    estados = {f["source_id"]: f["estado"] for f in visto["filas"]}
    assert estados == {"F01": "success", "F02": "running"}
    assert visto["corrida"]["estado"] == "running"
    assert visto["corrida"]["total_fuentes"] == 2
    assert visto["corrida"]["heartbeat_at"]
    # Resultados incrementales: lo de F01 ya está clasificado.
    assert visto["analisis"] >= 2
    foto = visto["foto"]
    assert foto["activo"] is True
    assert foto["fuentes"]["completadas"] == 1
    assert foto["fuentes"]["ejecutando"] == 1
    assert foto["fuentes"]["actual"] == "F02"
    assert foto["fuentes"]["fraccion"] == 0.5
    assert foto["ofertas"]["nuevas"] >= 2


def test_resumen_final_con_duracion_errores_y_candidatas(entorno, perfil_id, fuentes):
    fuentes(F01={"ofertas": 2, "titulo": "Junior Data Analyst"},
            F02={"revienta": True})

    worker.correr(causa="manual-ui", limite=5, fuentes=["F01", "F02"], usar_mutex=False)

    resumen = _snapshot()["resumen"]
    assert resumen["fuentes_total"] == 2
    assert resumen["fuentes_procesadas"] == 2
    assert resumen["fuentes_fallidas"] == 1
    assert resumen["duracion_ms"] is not None and resumen["duracion_ms"] >= 0
    assert [e["source_id"] for e in resumen["errores"]] == ["F02"]
    assert resumen["nuevas"] >= 2
    assert "candidatas" in resumen and "elegibles" in resumen and "dudosas" in resumen
    # El resumen queda guardado: se puede leer después de cerrar la página.
    guardado = json.loads(entorno.execute(
        "SELECT resumen_json FROM runs ORDER BY id DESC LIMIT 1").fetchone()[0])
    assert guardado["candidatas"] == resumen["candidatas"]


def test_fallo_parcial_conserva_lo_ingestado(entorno, perfil_id, fuentes):
    fuentes(F01={"ofertas": 3}, F02={"revienta": True}, F03={"ofertas": 1})

    resultado = worker.correr(causa="manual-ui", limite=5,
                              fuentes=["F01", "F02", "F03"], usar_mutex=False)

    assert resultado["estado"] == "ok"
    estados = {f["source_id"]: f["estado"] for f in resultado["fuentes"]}
    assert estados["F02"] == "network_error"
    assert estados["F01"] == "success" and estados["F03"] == "success"
    assert entorno.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] >= 4
    assert _snapshot()["ofertas"]["nuevas"] >= 4


# --- cancelación -------------------------------------------------------------

def test_cancelar_detiene_entre_fuentes_y_conserva_el_trabajo(entorno, perfil_id, fuentes):
    """La cancelación es cooperativa: no corta una descarga ni borra lo hecho."""
    def pedir_cancelar(fuente):
        if fuente.source_id != "F02":
            return
        conn = db.conectar(config.rutas().db)
        try:
            run_id = conn.execute("SELECT id FROM runs WHERE estado='running'").fetchone()["id"]
            progreso.marcar_cancelada(conn, run_id)
        finally:
            conn.close()

    registro = fuentes(F01={"ofertas": 2}, F02={"ofertas": 1, "al_consultar": pedir_cancelar},
                       F03={"ofertas": 1})

    resultado = worker.correr(causa="manual-ui", limite=5,
                              fuentes=["F01", "F02", "F03"], usar_mutex=False)

    assert resultado["cancelada"] is True
    assert resultado["estado"] == "cancelled"
    assert registro["F03"].veces == 0, "la fuente siguiente no debe consultarse"

    filas = {f["source_id"]: f["estado"] for f in entorno.execute(
        "SELECT source_id, estado FROM source_runs").fetchall()}
    assert filas == {"F01": "success", "F02": "success", "F03": "cancelled"}
    # Lo cancelado no es un error: se informa aparte.
    assert datos_cancelados(entorno) == {"completadas": 2, "fallidas": 0, "canceladas": 1}
    # Lo cancelado no es un error: se informa aparte.
    assert datos_cancelados(entorno) == {"completadas": 2, "fallidas": 0, "canceladas": 1}

    datos = _snapshot()
    assert datos["activo"] is False
    assert datos["estado"] == "cancelled"
    assert datos["cancelada"] is True
    # Lo descargado y clasificado sobrevive a la cancelación.
    assert datos["ofertas"]["nuevas"] >= 3
    assert entorno.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] >= 3


# --- HTTP: botón, JSON y concurrencia ---------------------------------------

def _cliente() -> TestClient:
    cliente = TestClient(crear_app(token="t", csrf="c"), base_url="http://127.0.0.1")
    cliente.get("/entrar?token=t")
    return cliente


def test_la_pestana_de_ofertas_ofrece_el_boton_y_la_lista(entorno, perfil_id):
    respuesta = _cliente().get("/ofertas")
    assert respuesta.status_code == 200
    assert 'id="btn-buscar"' in respuesta.text
    assert "Buscar ahora" in respuesta.text
    assert 'id="lista-ofertas"' in respuesta.text
    assert 'id="panel-busqueda"' in respuesta.text


def test_progreso_json_exige_sesion(entorno, perfil_id):
    sin_sesion = TestClient(crear_app(token="t", csrf="c"), base_url="http://127.0.0.1")
    respuesta = sin_sesion.get("/progreso.json", follow_redirects=False)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/entrar"


def test_progreso_json_se_recupera_tras_recargar(entorno, perfil_id, fuentes):
    fuentes(F01={"ofertas": 1})
    worker.correr(causa="manual-ui", limite=5, fuentes=["F01"], usar_mutex=False)

    # Otra instancia de la aplicación: simula recargar o abrir otra pestaña.
    primer = _cliente().get("/progreso.json").json()
    segundo = _cliente().get("/progreso.json").json()

    assert primer["run_id"] == segundo["run_id"]
    assert primer["estado"] == "completed"
    assert primer["resumen"]["fuentes_total"] == 1
    assert primer["ofertas"]["nuevas"] >= 1
    assert primer["version"] == segundo["version"]


def test_buscar_ahora_lanza_una_corrida_y_devuelve_json(entorno, perfil_id, fuentes):
    fuentes(F01={"ofertas": 2})
    cliente = _cliente()
    app = cliente.app

    respuesta = cliente.post("/buscar/ahora", data={"csrf": "c"})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["iniciada"] is True

    hilo = app.state.hilo_corrida
    if hilo is not None:
        hilo.join(timeout=20)
    assert not hilo.is_alive(), "la corrida no terminó a tiempo"

    datos = cliente.get("/progreso.json").json()
    assert datos["estado"] == "completed"
    assert datos["ofertas"]["nuevas"] >= 2


def test_una_sola_corrida_aunque_se_pulse_dos_veces(entorno, perfil_id, monkeypatch):
    """El segundo clic no inicia otra: muestra la que ya está en curso."""
    import buscador.web as web_mod

    empezado = threading.Event()
    soltar = threading.Event()

    def correr_lento(causa="manual", **kwargs):
        empezado.set()
        soltar.wait(timeout=15)
        return {"estado": "ok", "run_id": 999, "observaciones": 0, "tareas_procesadas": 0}

    monkeypatch.setattr(web_mod.worker, "correr", correr_lento)
    cliente = _cliente()

    primera = cliente.post("/buscar/ahora", data={"csrf": "c"}).json()
    assert primera["iniciada"] is True
    assert empezado.wait(timeout=10)

    segunda = cliente.post("/buscar/ahora", data={"csrf": "c"}).json()
    assert segunda["iniciada"] is False
    assert "en curso" in segunda["motivo"]

    # El formulario sin JavaScript tampoco duplica: vuelve con `busqueda=ocupado`.
    formulario = cliente.post("/buscar", data={"csrf": "c", "volver": "/ofertas"},
                              follow_redirects=False)
    assert formulario.status_code == 303
    assert "busqueda=ocupado" in formulario.headers["location"]
    assert formulario.headers["location"].startswith("/ofertas")

    soltar.set()
    cliente.app.state.hilo_corrida.join(timeout=10)


def test_corrida_activa_en_la_base_bloquea_un_segundo_intento(entorno, perfil_id):
    """Aunque la memoria del proceso se haya perdido, la base manda."""
    with entorno:
        run_id = ingest.abrir_corrida(entorno, "manual-ui", "epoch-externa")
        progreso.latido(entorno, run_id)

    # Un trabajador vivo tiene el candado tomado: así lo distingue el servidor
    # de una corrida que quedó colgada.
    mutex = worker.Mutex(config.rutas().lock)
    assert mutex.adquirir()
    try:
        respuesta = _cliente().post("/buscar/ahora", data={"csrf": "c"}).json()
    finally:
        mutex.liberar()

    assert respuesta["iniciada"] is False
    assert respuesta["run_id"] == run_id
    assert "en curso" in respuesta["motivo"]


def test_corrida_colgada_no_bloquea_la_siguiente(entorno, perfil_id, monkeypatch):
    """Latido fresco pero sin candado: el proceso murió, hay que poder buscar."""
    import buscador.web as web_mod

    monkeypatch.setattr(web_mod.worker, "correr",
                        lambda causa="manual", **kw: {"estado": "ok", "run_id": 4242})
    with entorno:
        run_id = ingest.abrir_corrida(entorno, "manual-ui", "epoch-muerta")
        progreso.latido(entorno, run_id)
        ingest.planificar_source_runs(entorno, run_id, ["F01", "F02"])

    assert _snapshot()["activo"] is True  # el latido todavía es reciente

    cliente = _cliente()
    respuesta = cliente.post("/buscar/ahora", data={"csrf": "c"}).json()

    assert respuesta["iniciada"] is True
    cliente.app.state.hilo_corrida.join(timeout=10)
    anterior = _snapshot(run_id=run_id)
    assert anterior["estado"] == "abandoned"
    assert anterior["fuentes"]["pendientes"] == 0   # no quedan colgadas
    assert anterior["fuentes"]["canceladas"] == 2   # sin consultar, no "con error"
    assert anterior["fuentes"]["fallidas"] == 0


def test_corrida_sin_latido_se_informa_abandonada(entorno, perfil_id):
    with entorno:
        run_id = ingest.abrir_corrida(entorno, "manual-ui", "epoch-vieja")
        entorno.execute(
            "UPDATE runs SET heartbeat_at='2020-01-01T00:00:00Z' WHERE id=?", (run_id,))
        run_id_fila = entorno.execute(
            "SELECT id FROM runs WHERE estado='running'").fetchone()["id"]

    datos = _snapshot()
    assert datos["run_id"] == run_id_fila
    assert datos["activo"] is False
    assert datos["estado"] == "abandoned"
    # Y no impide lanzar una búsqueda nueva.
    assert _cliente().post("/buscar/ahora", data={"csrf": "c"}).json()["iniciada"] is True


def test_cancelar_por_http_avisa_que_no_hay_corrida(entorno, perfil_id):
    respuesta = _cliente().post("/buscar/cancelar", data={"csrf": "c"}).json()
    assert respuesta["cancelada"] is False
    assert "no hay una búsqueda en curso" in respuesta["motivo"]


def test_ambas_acciones_exigen_csrf(entorno, perfil_id):
    cliente = _cliente()
    assert cliente.post("/buscar/ahora", data={"csrf": "malo"}).status_code == 400
    assert cliente.post("/buscar/cancelar", data={"csrf": "malo"}).status_code == 400
    assert cliente.post("/buscar", data={"csrf": "malo"}).status_code == 400


def test_volver_no_permite_redireccion_abierta(entorno, perfil_id, monkeypatch):
    import buscador.web as web_mod

    monkeypatch.setattr(web_mod.worker, "correr",
                        lambda causa="manual", **kw: {"estado": "ok", "run_id": 1})
    cliente = _cliente()
    respuesta = cliente.post("/buscar", data={"csrf": "c", "volver": "//malicioso.test/x"},
                             follow_redirects=False)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"].startswith("/actividad")
    cliente.app.state.hilo_corrida.join(timeout=10)


def test_la_ia_se_informa_sin_tocar_credenciales(entorno, perfil_id):
    datos = _snapshot()
    assert datos["ia"]["habilitada"] is False
    assert "IA desactivada" in datos["ia"]["cuota"]["motivo"]
    assert datos["ia"]["pendientes"] == 0


def test_el_panel_no_expone_datos_de_credenciales(entorno, perfil_id):
    texto = _cliente().get("/ofertas").text
    assert "AIza" not in texto
    assert "/progreso.json" not in texto  # el sondeo vive en el JS, no en el HTML


def datos_cancelados(conn) -> dict:
    """Conteo de fuentes por familia, para distinguir error de no consultada."""
    fuentes = progreso.snapshot(conn)["fuentes"]
    return {clave: fuentes[clave] for clave in ("completadas", "fallidas", "canceladas")}


def datos_cancelados(conn) -> dict:
    """Conteo de fuentes por familia, para distinguir error de no consultada."""
    fuentes = progreso.snapshot(conn)["fuentes"]
    return {clave: fuentes[clave] for clave in ("completadas", "fallidas", "canceladas")}


def test_candidatas_es_el_catalogo_y_candidatas_nuevas_el_delta(entorno, perfil_id, fuentes):
    """El resumen no debe confundir «lo que hay» con «lo que sumó esta corrida».

    Antes decía «1 candidata» cuando en el catálogo había 10: sólo una se había
    recalculado en esa búsqueda.
    """
    fuentes(F01={"ofertas": 2, "titulo": "Junior Data Analyst"})
    worker.correr(causa="manual-ui", limite=5, fuentes=["F01"], usar_mutex=False)

    primera = _snapshot()
    total = primera["ofertas"]["elegibles"] + primera["ofertas"]["dudosas"]
    assert primera["resumen"]["candidatas"] == total
    assert primera["resumen"]["candidatas_nuevas"] == 2

    # Segunda corrida sin ofertas nuevas: el catálogo sigue igual, el delta es 0.
    fuentes(F02={"ofertas": 0})
    worker.correr(causa="manual-ui", limite=5, fuentes=["F02"], usar_mutex=False)

    segunda = _snapshot()
    assert segunda["resumen"]["candidatas"] == total
    assert segunda["resumen"]["candidatas_nuevas"] == 0
    assert segunda["resumen"]["nuevas"] == 0


def test_candidatas_es_el_catalogo_y_candidatas_nuevas_el_delta(entorno, perfil_id, fuentes):
    """El resumen no debe confundir «lo que hay» con «lo que sumó esta corrida».

    Antes decía «1 candidata» cuando en el catálogo había 10: sólo una se había
    recalculado en esa búsqueda.
    """
    fuentes(F01={"ofertas": 2, "titulo": "Junior Data Analyst"})
    worker.correr(causa="manual-ui", limite=5, fuentes=["F01"], usar_mutex=False)

    primera = _snapshot()
    total = primera["ofertas"]["elegibles"] + primera["ofertas"]["dudosas"]
    assert primera["resumen"]["candidatas"] == total
    assert primera["resumen"]["candidatas_nuevas"] == 2

    # Segunda corrida sin ofertas nuevas: el catálogo sigue igual, el delta es 0.
    fuentes(F02={"ofertas": 0})
    worker.correr(causa="manual-ui", limite=5, fuentes=["F02"], usar_mutex=False)

    segunda = _snapshot()
    assert segunda["resumen"]["candidatas"] == total
    assert segunda["resumen"]["candidatas_nuevas"] == 0
    assert segunda["resumen"]["nuevas"] == 0


def test_el_js_y_la_plantilla_comparten_los_mismos_identificadores(entorno, perfil_id):
    """Si el JS busca un `id` que la plantilla no tiene, el panel queda mudo.

    No hay navegador en este entorno: esta prueba cubre el contrato entre los
    dos archivos, que es donde se rompen estas cosas.
    """
    import re
    from pathlib import Path

    fuente = (Path(__file__).resolve().parents[1]
              / "buscador" / "web" / "static" / "progreso.js").read_text(encoding="utf-8")
    usados = set(re.findall(r'\$\("#([a-z0-9\-]+)"\)', fuente))
    assert usados, "el JS no declara ningún selector: revisá el archivo"

    html = _cliente().get("/ofertas").text
    faltan = sorted(i for i in usados if f'id="{i}"' not in html)
    assert not faltan, f"la plantilla no tiene estos ids que el JS usa: {faltan}"


def test_el_js_y_la_plantilla_comparten_los_mismos_identificadores(entorno, perfil_id):
    """Si el JS busca un `id` que la plantilla no tiene, el panel queda mudo.

    No hay navegador en este entorno: esta prueba cubre el contrato entre los
    dos archivos, que es donde se rompen estas cosas.
    """
    import re
    from pathlib import Path

    fuente = (Path(__file__).resolve().parents[1]
              / "buscador" / "web" / "static" / "progreso.js").read_text(encoding="utf-8")
    usados = set(re.findall(r'\$\("#([a-z0-9\-]+)"\)', fuente))
    assert usados, "el JS no declara ningún selector: revisá el archivo"

    html = _cliente().get("/ofertas").text
    faltan = sorted(i for i in usados if f'id="{i}"' not in html)
    assert not faltan, f"la plantilla no tiene estos ids que el JS usa: {faltan}"
