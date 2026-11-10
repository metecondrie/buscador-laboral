"""Lote D: modo demostración, reportes saneados y agrupación territorial.

La demostración se ejecuta de verdad, sobre una base temporal y con la red
bloqueada por `conftest`: si el modo demo necesitara internet, esta prueba falla.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tools"))

import informe_clasificacion  # noqa: E402
import muestra_validacion  # noqa: E402
from buscador import demo  # noqa: E402


# --- Modo demostración -----------------------------------------------------

def test_la_demo_prepara_ofertas_sinteticas_sin_red(tmp_path):
    resultado = demo.preparar(tmp_path / "demo")
    assert resultado["ofertas"] == len(demo.OFERTAS_DEMO)
    assert resultado["clasificadas"] == resultado["ofertas"]
    assert set(resultado["por_elegibilidad"]) <= {"eligible", "doubtful", "incompatible"}
    assert resultado["por_elegibilidad"], "la demo tiene que producir veredictos"
    assert Path(resultado["db"]).is_file()


def test_la_demo_escribe_fuera_de_la_instalacion_operativa(tmp_path):
    destino = tmp_path / "demo"
    resultado = demo.preparar(destino)
    assert Path(resultado["base"]).resolve().is_relative_to(destino.resolve())


def test_la_demo_se_puede_reiniciar(tmp_path):
    destino = tmp_path / "demo"
    primera = demo.preparar(destino)
    segunda = demo.preparar(destino, reiniciar=True)
    assert primera["ofertas"] == segunda["ofertas"]
    assert segunda["por_elegibilidad"]


def test_las_ofertas_de_la_demo_no_son_reales():
    """Ninguna empresa ni URL de la demo puede parecer un aviso verdadero."""
    for oferta in demo.OFERTAS_DEMO:
        assert "ejemplo" in oferta["empresa"].lower()
        assert oferta["id"].startswith("demo-")


# --- Reporte saneado (V02) -------------------------------------------------

def test_la_muestra_no_publica_titulo_ni_empresa():
    columnas = {c.lower() for c in muestra_validacion.COLUMNAS}
    assert "titulo" not in columnas
    assert "empresa" not in columnas
    assert "url" not in columnas
    assert "dimension_principal" in columnas


def test_la_dimension_principal_sale_de_las_razones():
    razones = json.dumps([
        {"tipo": "categoria", "texto": "ok", "efecto": "suma"},
        {"tipo": "territorio", "texto": "US only", "efecto": "excluye"},
    ])
    assert muestra_validacion.dimension_principal(razones) == "territorio"
    assert muestra_validacion.dimension_principal(None) == "-"
    assert muestra_validacion.dimension_principal("no es json") == "-"


def test_el_csv_publicado_no_tiene_bom():
    crudo = (RAIZ / "docs" / "muestra-validacion.csv").read_bytes()
    assert not crudo.startswith(b"\xef\xbb\xbf")
    cabecera = crudo.split(b"\n", 1)[0].decode("utf-8").strip()
    assert cabecera.split(";")[:2] == ["n", "fuente"]


# --- Agrupación territorial del informe (T02) ------------------------------

def test_una_ciudad_con_remote_no_cuenta_como_alcance_global():
    for valor in ("Berlin (remote)", "Hamburg (remote)", "Munich (remote)"):
        assert informe_clasificacion.familia_territorio(valor) == "Europa (sin Reino Unido)"


def test_el_alcance_global_sigue_reconociendose():
    for valor in ("Anywhere in the World", "Worldwide", "Remote worldwide"):
        assert informe_clasificacion.familia_territorio(valor) == "remoto global declarado"


def test_remote_a_secas_no_inventa_geografia():
    assert informe_clasificacion.familia_territorio("Remote") == "otra region no clasificada"
    assert informe_clasificacion.familia_territorio(None) == "sin territorio declarado"
