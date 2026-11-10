"""Los contadores de Diagnóstico tienen que coincidir con la base.

Regla del proyecto: ninguna cifra inventada. Cada número de la pantalla se
compara acá contra la consulta que lo produce, y se verifica que no se mezclen
las cifras de la última corrida con las del catálogo.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from buscador import config, db, diagnostics, ingest, worker
from buscador.adapters.base import Observacion, ResultadoFuente
from buscador.web import crear_app


def _obs(ext: str, titulo: str = "Junior Data Analyst") -> Observacion:
    return Observacion(
        source_id="F01", external_id=ext, url=f"https://ejemplo.test/{ext}",
        titulo=titulo, empresa=f"Acme {ext}",
        descripcion_html="<p>SQL required.</p>", publicado_en="2026-11-05T00:00:00Z",
        region="Anywhere in the World",
        extra={"texto_plano": "SQL required. Excel. Dashboards. Reportes."},
    )


@pytest.fixture
def con_datos(entorno, perfil_id, monkeypatch):
    class Fuente:
        source_id = "F01"

        def fetch(self, limite, cursor=None):
            return ResultadoFuente("F01", "success", [_obs(f"ext-{i}") for i in range(3)])

    monkeypatch.setattr(worker.adapters, "obtener", lambda sid: Fuente())
    worker.correr(causa="prueba", limite=10, fuentes=["F01"], usar_mutex=False)
    return entorno


def test_las_cifras_del_catalogo_salen_de_la_base(con_datos):
    conn = con_datos
    datos = diagnostics.clasificacion(conn)

    assert datos["ofertas"] == conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE merged_into IS NULL").fetchone()[0]
    assert datos["analizadas"] == conn.execute(
        "SELECT COUNT(DISTINCT job_id) FROM analyses WHERE obsoleto=0").fetchone()[0]
    assert datos["elegibles"] == conn.execute(
        "SELECT COUNT(*) FROM analyses WHERE obsoleto=0 AND elegibilidad='eligible'").fetchone()[0]
    assert datos["sin_analisis"] == datos["ofertas"] - datos["analizadas"]
    assert datos["pendientes"] == 0
    assert (datos["elegibles"] + datos["dudosas"] + datos["incompatibles"]
            == datos["analizadas"])


def test_no_se_mezcla_la_corrida_con_el_catalogo(con_datos):
    conn = con_datos
    busqueda = diagnostics.ultima_busqueda(conn)
    catalogo = diagnostics.clasificacion(conn)

    assert busqueda["hay"] is True
    assert busqueda["run_id"] == conn.execute(
        "SELECT MAX(id) FROM runs").fetchone()[0]
    assert busqueda["revisadas"] == conn.execute(
        "SELECT COALESCE(SUM(observaciones),0) FROM source_runs WHERE run_id=?",
        (busqueda["run_id"],)).fetchone()[0]
    # «Nuevas» es de la corrida; «ofertas» es el catálogo. No son lo mismo.
    assert busqueda["ofertas_nuevas"] <= catalogo["ofertas"]
    assert busqueda["ofertas_nuevas"] == 3
    assert catalogo["ofertas"] == 3
    assert catalogo["ofertas_historicas"] == catalogo["ofertas"] - busqueda["ofertas_nuevas"]


def test_los_errores_de_fuente_y_de_clasificacion_se_cuentan_aparte(con_datos):
    conn = con_datos
    errores = diagnostics.errores_clasificacion(conn)
    busqueda = diagnostics.ultima_busqueda(conn)

    assert errores["fallidas"] == conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE estado='failed'").fetchone()[0]
    assert busqueda["fuentes_error"] == conn.execute(
        "SELECT COUNT(*) FROM source_runs WHERE run_id=?"
        " AND estado NOT IN ('success','empty_valid','partial','pending','running','cancelled')",
        (busqueda["run_id"],)).fetchone()[0]


def test_una_fuente_caida_aparece_como_error_y_no_como_vacia(con_datos, monkeypatch):
    class Rota:
        source_id = "F02"

        def fetch(self, limite, cursor=None):
            raise RuntimeError("falla simulada")

    monkeypatch.setattr(worker.adapters, "obtener", lambda sid: Rota())
    worker.correr(causa="prueba", limite=10, fuentes=["F02"], usar_mutex=False)

    busqueda = diagnostics.ultima_busqueda(con_datos)
    assert busqueda["fuentes_error"] == 1
    assert busqueda["fuentes_ok"] == 0


def test_diagnostico_muestra_los_dos_bloques(con_datos):
    cliente = TestClient(crear_app(token="t", csrf="c", autoreparar=False),
                         base_url="http://127.0.0.1")
    cliente.get("/entrar?token=t")
    html = cliente.get("/diagnostico").text

    assert "Última búsqueda" in html
    assert "Revisadas en esa corrida" in html
    assert "Clasificación" in html
    assert "Errores de clasificación" in html
    assert "Estas cifras son de esa corrida" in html
