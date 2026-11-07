"""Validación humana: muestra fija, veredictos y métricas.

Nada acá inventa respuestas: se comprueba que la muestra quedे fija, que un
veredicto se guarde y se pueda corregir, y que las métricas salgan de datos
reales (incluidos falsos positivos y negativos).
"""

from __future__ import annotations

import pytest

from buscador import ingest, validacion, worker
from buscador.adapters.base import Observacion, ResultadoFuente


def _obs(ext: str, titulo: str, region: str = "Anywhere in the World",
         empresa: str | None = None) -> Observacion:
    return Observacion(
        source_id="F01", external_id=ext, url=f"https://ejemplo.test/{ext}",
        titulo=titulo, empresa=empresa or f"Empresa {ext}",
        descripcion_html="<p>SQL and Excel required. Fully remote.</p>",
        publicado_en="2026-11-01T00:00:00Z", region=region,
        extra={"texto_plano": "SQL and Excel required. Fully remote."},
    )


def _sembrar(conn, perfil_id):
    ingest.ingestar(conn, ResultadoFuente("F01", "success", [
        _obs("a", "Data Analyst"),
        _obs("b", "Data Entry Clerk"),
        _obs("c", "Warehouse Operator"),
        _obs("d", "Senior Data Analyst"),
        _obs("e", "Customer Support Specialist"),
    ]), perfil_id)
    worker.procesar_tareas(conn, "epoch-val")


def test_muestra_se_crea_una_vez_y_no_cambia(entorno, perfil_id):
    _sembrar(entorno, perfil_id)
    primera = validacion.crear_muestra(entorno)
    antes = [i["job_id"] for i in validacion.items(entorno, primera)]
    segunda = validacion.crear_muestra(entorno)
    despues = [i["job_id"] for i in validacion.items(entorno, segunda)]
    assert primera == segunda
    assert antes == despues


def test_items_traen_lo_necesario_para_decidir(entorno, perfil_id):
    _sembrar(entorno, perfil_id)
    muestra = validacion.crear_muestra(entorno)
    filas = validacion.items(entorno, muestra)
    assert filas
    primera = filas[0]
    for campo in ("titulo", "empresa", "url_atribucion", "descripcion", "modalidad",
                  "territorio", "elegibilidad", "score", "motivo_elegibilidad"):
        assert campo in primera
    assert primera["descripcion"]
    assert primera["orden"] == 1


def test_veredicto_se_guarda_y_se_corrige(entorno, perfil_id):
    _sembrar(entorno, perfil_id)
    muestra = validacion.crear_muestra(entorno)
    job_id = validacion.items(entorno, muestra)[0]["job_id"]

    validacion.registrar(entorno, muestra, job_id, "no", "pide presencialidad")
    fila = entorno.execute(
        "SELECT veredicto, comentario, estado_previo FROM validation_reviews WHERE job_id=?",
        (job_id,),
    ).fetchone()
    assert fila["veredicto"] == "no"
    assert fila["comentario"] == "pide presencialidad"
    assert fila["estado_previo"] in {"eligible", "doubtful", "incompatible"}

    validacion.registrar(entorno, muestra, job_id, "si", "me sirve")
    assert entorno.execute(
        "SELECT COUNT(*) FROM validation_reviews WHERE job_id=?", (job_id,)
    ).fetchone()[0] == 1
    assert entorno.execute(
        "SELECT veredicto FROM validation_reviews WHERE job_id=?", (job_id,)
    ).fetchone()[0] == "si"


def test_veredicto_invalido_se_rechaza(entorno, perfil_id):
    _sembrar(entorno, perfil_id)
    muestra = validacion.crear_muestra(entorno)
    job_id = validacion.items(entorno, muestra)[0]["job_id"]
    with pytest.raises(ValueError):
        validacion.registrar(entorno, muestra, job_id, "quizas")


def test_metricas_sin_datos_no_inventan_precision(entorno, perfil_id):
    _sembrar(entorno, perfil_id)
    muestra = validacion.crear_muestra(entorno)
    datos = validacion.metricas(entorno, muestra)
    assert datos["revisadas"] == 0
    assert datos["precision_pct"] is None
    assert "sin datos" in datos["conclusion"]


def test_metricas_cuentan_falsos_positivos_y_negativos(entorno, perfil_id):
    _sembrar(entorno, perfil_id)
    muestra = validacion.crear_muestra(entorno)
    filas = validacion.items(entorno, muestra)

    relevantes = [f["job_id"] for f in filas if f["elegibilidad"] in {"eligible", "doubtful"}]
    descartadas = [f["job_id"] for f in filas if f["elegibilidad"] == "incompatible"]
    assert relevantes, "la muestra debe incluir al menos una oferta relevante"
    assert descartadas, "la muestra debe incluir al menos una descartada"

    # Un acierto y un falso positivo, sobre ofertas distintas.
    validacion.registrar(entorno, muestra, relevantes[0], "si", "aplica")
    if len(relevantes) > 1:
        validacion.registrar(entorno, muestra, relevantes[1], "no", "es presencial")

    # Un falso negativo: el sistema lo descartó y sí serviría.
    validacion.registrar(entorno, muestra, descartadas[0], "si", "es remoto de verdad")

    datos = validacion.metricas(entorno, muestra)
    assert datos["revisadas"] >= 2
    assert datos["falsos_negativos"] == 1
    if len(relevantes) > 1:
        assert datos["falsos_positivos"] == 1
    assert datos["precision_pct"] is not None
    assert datos["por_regla"]


def test_metricas_sobreviven_a_una_reclasificacion(entorno, perfil_id):
    """El veredicto es del usuario: no se pierde si cambian las reglas."""
    _sembrar(entorno, perfil_id)
    muestra = validacion.crear_muestra(entorno)
    job_id = validacion.items(entorno, muestra)[0]["job_id"]
    validacion.registrar(entorno, muestra, job_id, "si", "vale")

    worker.reclasificar_todo(entorno, perfil_id)
    worker.procesar_tareas(entorno, "epoch-nueva")

    fila = entorno.execute(
        "SELECT veredicto, comentario FROM validation_reviews WHERE job_id=?", (job_id,)
    ).fetchone()
    assert fila["veredicto"] == "si"
    assert fila["comentario"] == "vale"
    assert validacion.metricas(entorno, muestra)["revisadas"] == 1
