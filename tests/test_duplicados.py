"""Duplicados entre fuentes: sugerencia, fusión suave y reversión."""

from __future__ import annotations

from buscador import ingest, merge, worker
from buscador.adapters.base import Observacion, ResultadoFuente


def _obs(source_id: str, ext: str, titulo: str, empresa: str = "Acme") -> Observacion:
    return Observacion(
        source_id=source_id, external_id=ext, url=f"https://ejemplo.test/{ext}",
        titulo=titulo, empresa=empresa, descripcion_html="<p>SQL required.</p>",
        publicado_en="2026-11-01T00:00:00Z", region="Anywhere in the World",
        extra={"texto_plano": "SQL required. Python desirable."},
    )


def _ingerir(conn, perfil_id):
    ingest.ingestar(conn, ResultadoFuente("F01", "success", [_obs("F01", "a", "Data Analyst")]), perfil_id)
    ingest.ingestar(conn,
                    ResultadoFuente("F02", "success", [_obs("F02", "b", "Data Analyst (Remote)")]),
                    perfil_id)
    worker.procesar_tareas(conn, "epoch-dup")


def test_similitud_ignora_forma_pero_no_nivel():
    assert ingest.similitud_titulo("Data Analyst", "Data Analyst (Remote)") == 1.0
    assert ingest.similitud_titulo("Data Analyst", "Data Analyst (Full Time)") == 1.0
    # El nivel distingue puestos: junior y senior no son el mismo aviso.
    assert ingest.similitud_titulo("Junior Data Analyst", "Senior Data Analyst") < 0.82
    assert ingest.similitud_titulo("Data Analyst", "Warehouse Operator") < 0.3


def test_sugerencia_no_fusiona_sola(entorno, perfil_id):
    _ingerir(entorno, perfil_id)
    assert entorno.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
    assert entorno.execute("SELECT COUNT(*) FROM jobs WHERE merged_into IS NOT NULL").fetchone()[0] == 0
    sugerencias = merge.sugerencias(entorno)
    assert len(sugerencias) == 1
    assert sugerencias[0]["estado"] == "sugerida"
    assert sugerencias[0]["similitud"] >= 0.82


def test_aceptar_y_revertir_es_reversible(entorno, perfil_id):
    _ingerir(entorno, perfil_id)
    review = merge.sugerencias(entorno)[0]

    assert merge.aceptar(entorno, review["id"])["cambiado"] is True
    assert entorno.execute("SELECT COUNT(*) FROM jobs WHERE merged_into IS NOT NULL").fetchone()[0] == 1
    # La oferta absorbida sigue existiendo: no se borra nada.
    assert entorno.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
    assert entorno.execute(
        "SELECT COUNT(*) FROM audit_events WHERE tipo='fusion_aceptada'"
    ).fetchone()[0] == 1

    assert merge.revertir(entorno, review["id"])["cambiado"] is True
    assert entorno.execute("SELECT COUNT(*) FROM jobs WHERE merged_into IS NOT NULL").fetchone()[0] == 0
    assert entorno.execute(
        "SELECT estado FROM merge_reviews WHERE id=?", (review["id"],)
    ).fetchone()[0] == "revertida"


def test_rechazar_deja_constancia(entorno, perfil_id):
    _ingerir(entorno, perfil_id)
    review = merge.sugerencias(entorno)[0]
    assert merge.rechazar(entorno, review["id"])["cambiado"] is True
    assert merge.contar_pendientes(entorno) == 0
    assert entorno.execute(
        "SELECT COUNT(*) FROM audit_events WHERE tipo='fusion_rechazada'"
    ).fetchone()[0] == 1


def test_empresas_distintas_no_generan_sugerencia(entorno, perfil_id):
    ingest.ingestar(entorno, ResultadoFuente("F01", "success", [_obs("F01", "a", "Data Analyst", "Acme")]), perfil_id)
    ingest.ingestar(entorno, ResultadoFuente("F02", "success", [_obs("F02", "b", "Data Analyst", "Globex")]), perfil_id)
    assert merge.contar_pendientes(entorno) == 0


def test_misma_fuente_no_genera_sugerencia(entorno, perfil_id):
    """Dos vacantes del mismo editor con título parecido son puestos distintos."""
    ingest.ingestar(entorno, ResultadoFuente("F01", "success", [
        _obs("F01", "a", "Data Analyst", "Acme"),
        _obs("F01", "b", "Data Analyst (Remote)", "Acme"),
    ]), perfil_id)
    assert merge.contar_pendientes(entorno) == 0


def test_nivel_distinto_no_se_sugiere(entorno, perfil_id):
    ingest.ingestar(entorno, ResultadoFuente("F01", "success", [_obs("F01", "a", "Data Analyst", "Acme")]), perfil_id)
    ingest.ingestar(entorno, ResultadoFuente("F02", "success", [_obs("F02", "b", "Senior Data Analyst", "Acme")]), perfil_id)
    assert merge.contar_pendientes(entorno) == 0


def test_misma_fuente_no_genera_sugerencia(entorno, perfil_id):
    """Dos vacantes del mismo editor con título parecido son puestos distintos."""
    ingest.ingestar(entorno, ResultadoFuente("F01", "success", [
        _obs("F01", "a", "Data Analyst", "Acme"),
        _obs("F01", "b", "Data Analyst (Remote)", "Acme"),
    ]), perfil_id)
    assert merge.contar_pendientes(entorno) == 0


def test_nivel_distinto_no_se_sugiere(entorno, perfil_id):
    ingest.ingestar(entorno, ResultadoFuente("F01", "success", [_obs("F01", "a", "Data Analyst", "Acme")]), perfil_id)
    ingest.ingestar(entorno, ResultadoFuente("F02", "success", [_obs("F02", "b", "Senior Data Analyst", "Acme")]), perfil_id)
    assert merge.contar_pendientes(entorno) == 0
