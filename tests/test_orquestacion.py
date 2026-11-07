"""Orquestación de fuentes: particiones, aislamiento de errores y relevancia."""

from __future__ import annotations

from buscador import ingest, worker
from buscador.adapters.base import Observacion, Particion, ResultadoFuente


def _obs(source_id: str, ext: str, titulo: str, empresa: str = "Acme") -> Observacion:
    return Observacion(
        source_id=source_id,
        external_id=ext,
        url=f"https://ejemplo.test/{ext}",
        titulo=titulo,
        empresa=empresa,
        descripcion_html="<p>SQL required. Python desirable.</p>",
        publicado_en="2026-11-01T00:00:00Z",
        region="Anywhere in the World",
        extra={"texto_plano": "SQL required. Python desirable. Excel."},
    )


class _ConParticiones:
    source_id = "F99"
    particiones = (
        Particion("uno", "una", {"x": "1"}),
        Particion("dos", "dos", {"x": "2"}),
        Particion("rota", "rota", {"x": "3"}),
    )

    def fetch(self, limite, cursor=None, particion=None):
        if particion and particion.clave == "rota":
            raise RuntimeError("falla simulada")
        return ResultadoFuente(
            source_id="F99", estado="success",
            observaciones=[_obs("F99", f"{particion.clave}-a", "Data Analyst")],
        )


class _ConDuplicadosEntreParticiones:
    source_id = "F98"
    particiones = (
        Particion("uno", "una", {}),
        Particion("dos", "dos", {}),
    )

    def fetch(self, limite, cursor=None, particion=None):
        return ResultadoFuente(
            source_id="F98", estado="success",
            observaciones=[_obs("F98", "mismo-id", "Data Analyst")],
        )


def test_particion_rota_no_anula_el_resto():
    resultado = worker.recolectar(_ConParticiones(), limite=10)
    assert resultado.estado == "partial"
    assert len(resultado.observaciones) == 2
    assert [p["clave"] for p in resultado.detalle["particiones"]] == ["uno", "dos", "rota"]
    assert resultado.error_msg and "rota" in resultado.error_msg


def test_particiones_no_duplican_observaciones():
    resultado = worker.recolectar(_ConDuplicadosEntreParticiones(), limite=10)
    assert len(resultado.observaciones) == 1


def test_todas_las_particiones_fallan_reportan_error():
    class _TodoRoto(_ConParticiones):
        particiones = (Particion("rota", "rota", {}),)

    resultado = worker.recolectar(_TodoRoto(), limite=5)
    assert resultado.estado == "network_error"
    assert resultado.observaciones == []


def test_relevancia_se_mide_por_fuente_no_por_volumen(entorno, perfil_id):
    """Una fuente con muchos avisos irrelevantes no debe parecer productiva."""
    from buscador import config

    conn = entorno
    corrida = ingest.abrir_corrida(conn, "prueba", "epoch-relevancia")
    for sid in ("F01", "F02"):
        ingest.abrir_source_run(conn, corrida, sid, None)

    utiles = [_obs("F01", f"util-{i}", "Data Analyst", empresa=f"Acme {i}") for i in range(3)]
    ruido = [_obs("F02", f"ruido-{i}", "Warehouse Operator", empresa=f"Otra {i}") for i in range(20)]
    ingest.ingestar(conn, ResultadoFuente("F01", "success", utiles), perfil_id)
    ingest.ingestar(conn, ResultadoFuente("F02", "success", ruido), perfil_id)
    worker.procesar_tareas(conn, "epoch-relevancia")

    relevancia = worker.medir_relevancia(conn, corrida)
    assert relevancia["F01"]["relevantes"] == 3
    assert relevancia["F02"]["relevantes"] == 0
    filas = {
        f["source_id"]: f["relevantes"]
        for f in conn.execute("SELECT source_id, relevantes FROM source_runs WHERE run_id=?", (corrida,))
    }
    assert filas == {"F01": 3, "F02": 0}
    assert config.RULES_VERSION == "rules-2.0.0"


def test_limite_se_respeta_entre_particiones():
    resultado = worker.recolectar(_ConDuplicadosEntreParticiones(), limite=1)
    assert len(resultado.observaciones) == 1
