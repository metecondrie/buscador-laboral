"""Lote C: fuentes, tableros y circuito abierto.

Nada de esto sale a internet: los tableros y las particiones se validan sobre el
archivo de configuración, y el circuito se prueba con corridas sintéticas en una
base temporal.
"""

from __future__ import annotations

import json
import uuid
import uuid
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from buscador import adapters, config, db, ingest, verify, worker  # noqa: E402
from buscador.adapters import ats  # noqa: E402
from buscador.adapters.base import Observacion, ResultadoFuente  # noqa: E402


# --- Tableros ATS ----------------------------------------------------------

def test_los_tableros_declaran_solo_familias_soportadas():
    datos = json.loads(ats.TABLEROS.read_text(encoding="utf-8"))
    familias = {t["ats"] for t in datos["tableros"]}
    assert familias <= {"greenhouse", "lever", "ashby"}
    assert datos["verificado_en"], "los tableros deben declarar cuándo se verificaron"


def test_no_hay_tableros_repetidos_ni_sin_organizacion():
    datos = json.loads(ats.TABLEROS.read_text(encoding="utf-8"))
    claves = [(t["ats"], t["org"]) for t in datos["tableros"]]
    assert len(claves) == len(set(claves))
    for tablero in datos["tableros"]:
        assert tablero["org"].strip()
        assert tablero.get("activo", True) is True


def test_cada_familia_tiene_al_menos_un_tablero_cargable():
    for familia in ("greenhouse", "lever", "ashby"):
        assert ats.cargar_tableros(familia), familia


# --- Particiones de fuentes ------------------------------------------------

def test_jobicy_particiona_por_region_latam():
    jobicy = adapters.obtener("F03")
    claves = {p.clave: p.params for p in jobicy.particiones}
    assert claves.get("latam") == {"geo": "latam"}


def test_remotive_no_particiona_por_categoria_porque_la_api_lo_ignora():
    remotive = adapters.obtener("F11")
    assert not getattr(remotive, "particiones", ())


# --- Circuito abierto (F05) ------------------------------------------------

def _corrida(conn, source_id: str, estado: str, error_code: str | None) -> None:
    epoch = "epoch-" + uuid.uuid4().hex
    with db.transaccion(conn):
        run = ingest.abrir_corrida(conn, "prueba", epoch)
        sr = ingest.planificar_source_runs(conn, run, [source_id])[source_id]
        ingest.cerrar_source_run(
            conn, sr,
            ResultadoFuente(source_id=source_id, estado=estado, error_code=error_code),
            0, 0, None)


def test_el_circuito_se_abre_tras_dos_fallos_terminales(entorno):
    sid = "F05"
    assert not worker._circuito_abierto(entorno, sid)
    _corrida(entorno, sid, "access_restricted", "access_restricted")
    assert not worker._circuito_abierto(entorno, sid), "un solo fallo no abre el circuito"
    _corrida(entorno, sid, "access_restricted", "access_restricted")
    assert worker._circuito_abierto(entorno, sid)


def test_un_timeout_no_abre_el_circuito(entorno):
    sid = "F05"
    for _ in range(3):
        _corrida(entorno, sid, "network_error", "network_error")
    assert not worker._circuito_abierto(entorno, sid)


def test_un_exito_reciente_cierra_el_circuito(entorno):
    sid = "F05"
    _corrida(entorno, sid, "access_restricted", "access_restricted")
    _corrida(entorno, sid, "success", None)
    assert not worker._circuito_abierto(entorno, sid)


# --- Métricas por fuente ---------------------------------------------------

def test_las_metricas_por_fuente_distinguen_revisables_y_vigentes(monkeypatch):
    observacion = Observacion(
        source_id="F05", external_id="x1", url="https://ejemplo.test/aviso",
        titulo="Data Analyst", empresa="Sintetica", descripcion_html="",
        publicado_en=config.ahora_utc(), region="Argentina",
        extra={"texto_plano": "SQL required. Excel required. Remote. Dashboards."},
    )

    monkeypatch.setattr(worker, "recolectar",
                        lambda adaptador, limite: ResultadoFuente(
                            source_id="F05", estado="success", observaciones=[observacion]))
    fila = verify.verificar_adaptador("F05", 5, {"categorias": ["Data Analyst"],
                                                 "habilidades": [], "idioma": {},
                                                 "territorio": {}})
    for clave in ("elegibles", "revisables", "incompatibles", "vigentes",
                  "vigencia_sin_confirmar", "http_status"):
        assert clave in fila
    assert fila["revisables"] + fila["elegibles"] + fila["incompatibles"] == fila["observaciones"]
