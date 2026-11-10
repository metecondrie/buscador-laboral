"""Vista de candidatas: orden, filtros y separación confirmado/desconocido."""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from buscador import candidatas, db, ingest  # noqa: E402


def _sembrar(conn, filas: list[dict], perfil_id: int) -> None:
    """Crea ofertas y análisis con los campos que la vista consume."""
    import json

    for fila in filas:
        conn.execute(
            """INSERT INTO jobs (id, titulo, empresa, categoria, modalidad, territorio,
                   estado_vigencia, publicado_en, primera_deteccion, ultima_deteccion,
                   semantic_hash, url_atribucion, fuente_principal)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fila["id"], fila["titulo"], fila.get("empresa"), fila.get("categoria"),
             fila.get("modalidad", "remote"), fila.get("territorio"),
             fila.get("vigencia", "open"), "2026-11-01T00:00:00Z",
             "2026-11-01T00:00:00Z", "2026-11-01T00:00:00Z", fila["id"],
             fila.get("url"), "F01"),
        )
        conn.execute(
            """INSERT INTO analyses (job_id, job_version_id, profile_version_id, rules_version,
                   elegibilidad, score, componentes_json, razones_json, incertidumbres_json,
                   creado_en, obsoleto, excepcion, confianza, motivo_elegibilidad, run_id)
               VALUES (?,?,?,'rules-3.4.0',?,?,?,?,?,?,0,0,?,?,NULL)""",
            (fila["id"], ingest._asegurar_version(conn, fila["id"]), perfil_id,
             fila["elegibilidad"], fila.get("score"),
             json.dumps(fila.get("componentes", [])),
             json.dumps(fila.get("razones", [])),
             json.dumps(fila.get("incertidumbres", [])),
             "2026-11-10T00:00:00Z", fila.get("confianza", "media"),
             fila.get("motivo", "")),
        )
    conn.commit()


def _fila(id_: str, **cambios) -> dict:
    base = {"id": id_, "titulo": id_, "elegibilidad": "doubtful", "score": 20.0,
            "territorio": "Anywhere in the World", "categoria": "Customer Support",
            "razones": [{"tipo": "territorio", "texto": "ok", "efecto": "suma"}],
            "componentes": [{"nombre": "habilidades", "estado": "cumplido",
                             "detalle": "2/2"}], "incertidumbres": []}
    base.update(cambios)
    return base


def test_ordena_por_puntaje_y_pone_vigentes_primero(entorno, perfil_id):
    _sembrar(entorno, [
        _fila("baja", score=10.0),
        _fila("alta", score=60.0),
        _fila("cerrada", score=90.0, vigencia="stale"),
    ], perfil_id)
    lista = candidatas.listar(entorno)
    assert [c.job_id for c in lista] == ["alta", "baja", "cerrada"]


def test_deja_fuera_el_conflicto_de_territorio(entorno, perfil_id):
    _sembrar(entorno, [
        _fila("ok"),
        _fila("conflicto", razones=[
            {"tipo": "territorio", "texto": "la fuente restringe a United States",
             "efecto": "duda"}]),
    ], perfil_id)
    lista = candidatas.listar(entorno)
    assert [c.job_id for c in lista] == ["ok"]
    todas = candidatas.listar(entorno, solo_territorio_confirmado=False)
    assert {c.job_id for c in todas} == {"ok", "conflicto"}


def test_separa_confirmado_de_desconocido(entorno, perfil_id):
    _sembrar(entorno, [
        _fila("mixta", componentes=[
            {"nombre": "categoria_tareas", "estado": "cumplido", "detalle": "título y tareas"},
            {"nombre": "experiencia", "estado": "sin_datos", "detalle": "no declara"},
        ]),
    ], perfil_id)
    candidata = candidatas.listar(entorno)[0]
    assert any("categoria_tareas" in c for c in candidata.confirmados)
    assert any("experiencia" in c for c in candidata.desconocidos)


def test_no_lista_incompatibles_ni_elegibles_por_error(entorno, perfil_id):
    _sembrar(entorno, [
        _fila("descartada", elegibilidad="incompatible"),
        _fila("elegible", elegibilidad="eligible", score=70.0),
    ], perfil_id)
    lista = candidatas.listar(entorno)
    assert [c.job_id for c in lista] == ["elegible"]


def test_el_resumen_cuenta_categorias_reconocidas(entorno, perfil_id):
    _sembrar(entorno, [
        _fila("con", categoria="Customer Support"),
        _fila("sin", categoria=None),
    ], perfil_id)
    resumen = candidatas.resumen(candidatas.listar(entorno))
    assert resumen["total"] == 2
    assert resumen["con_categoria"] == 1
    assert resumen["sin_categoria"] == 1
