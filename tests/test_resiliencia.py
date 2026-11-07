"""Resiliencia: fuente caída, caída entre ingesta y análisis, contenido hostil."""

from __future__ import annotations

from fastapi.testclient import TestClient

from buscador import ingest, queue, worker
from buscador.adapters.base import Observacion, ResultadoFuente
from buscador.web import crear_app


def _obs(titulo: str = "Junior Data Analyst", empresa: str = "Acme", **cambios) -> Observacion:
    base = dict(
        source_id="F01",
        external_id=f"ext-{titulo}",
        url="https://weworkremotely.com/remote-jobs/prueba",
        titulo=titulo,
        empresa=empresa,
        descripcion_html="<p>SQL required. Python desirable.</p>",
        publicado_en="2026-11-01T00:00:00Z",
        region="Anywhere in the World",
        extra={"texto_plano": "SQL required. Python desirable. Excel."},
    )
    base.update(cambios)
    return Observacion(**base)


class _FuenteOk:
    def fetch(self, limite, cursor=None):
        return ResultadoFuente(source_id="F01", estado="success", observaciones=[_obs()])


class _FuenteRota:
    def fetch(self, limite, cursor=None):
        raise RuntimeError("falla simulada de red")


def test_fuente_caida_no_detiene_la_corrida(entorno, perfil_id, monkeypatch):
    monkeypatch.setattr(
        worker.adapters,
        "obtener",
        lambda sid: _FuenteRota() if sid == "F02" else _FuenteOk(),
    )
    resultado = worker.correr(causa="prueba", limite=1, fuentes=["F01", "F02"], usar_mutex=False)

    assert resultado["estado"] == "ok"
    estados = {f["source_id"]: f["estado"] for f in resultado["fuentes"]}
    assert estados["F01"] == "success"
    assert estados["F02"] == "network_error"
    incidentes = entorno.execute(
        "SELECT COUNT(*) FROM source_runs WHERE error_code='network_error'"
    ).fetchone()[0]
    assert incidentes == 1
    # La oferta válida se conserva y se clasifica igual.
    assert entorno.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] >= 1


def test_caida_entre_ingesta_y_analisis_se_recupera(entorno, perfil_id):
    ingest.ingestar(
        entorno,
        ResultadoFuente(source_id="F01", estado="success", observaciones=[_obs()]),
        perfil_id,
    )
    tomadas = queue.reclamar(entorno, "epoch-caida", limite=5)
    assert len(tomadas) == 1
    assert entorno.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 0

    recuperadas = queue.recuperar_huerfanas(entorno, "epoch-nueva")
    assert recuperadas == 1
    procesadas = worker.procesar_tareas(entorno, "epoch-nueva")

    assert procesadas == 1
    assert entorno.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 1
    assert queue.contar(entorno) == {"completed": 1}


def test_contenido_hostil_se_muestra_escapado(entorno, perfil_id):
    hostil = _obs(
        titulo="<script>alert(1)</script> Data Analyst",
        empresa="<img src=x onerror=alert(1)>",
        descripcion_html="<p>SQL required</p><script>alert(2)</script>",
        extra={"texto_plano": "SQL required. <script>alert(3)</script>"},
    )
    ingest.ingestar(
        entorno, ResultadoFuente(source_id="F01", estado="success", observaciones=[hostil]), perfil_id
    )
    worker.procesar_tareas(entorno, "epoch-x")
    job_id = entorno.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]

    cliente = TestClient(crear_app(token="t", csrf="c"), base_url="http://127.0.0.1")
    cliente.get("/entrar?token=t")
    respuesta = cliente.get(f"/oferta/{job_id}")

    assert respuesta.status_code == 200
    assert "<script>alert" not in respuesta.text
    assert "&lt;script&gt;" in respuesta.text


def test_detener_exige_token_de_control(entorno, perfil_id):
    cliente = TestClient(crear_app(token="t", csrf="c", stop_token="control"), base_url="http://127.0.0.1")
    assert cliente.post("/detener").status_code == 403
    assert cliente.post("/detener", headers={"X-Stop-Token": "otro"}).status_code == 403
