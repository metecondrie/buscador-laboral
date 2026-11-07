"""Caso de uso: analizar ofertas con IA y guardar el resultado estructurado.

La IA **no reemplaza** al motor de reglas. Su salida queda en `ai_analyses` como
segunda opinión con evidencia citada. Sólo puede *agregar* información; nunca
anular una restricción obligatoria (territorio, modalidad, seniority) sin una
cita textual verificada dentro del aviso.
"""

from __future__ import annotations

import json
import sqlite3

from .. import config, db, logs
from ..textutil import hash_texto, html_a_texto
from . import cache as cache_mod
from . import cola
from .cliente import Cliente, Rechazo, SinCuota
from .esquema import (AnalisisIA, contenido_oferta, evidencias_verificadas,
                      instruccion)

COMPLEJIDAD_DUDA = "equilibrado"
COMPLEJIDAD_BASE = "rapido"


def contenido_de(conn: sqlite3.Connection, job_id: str) -> dict | None:
    fila = conn.execute(
        """SELECT j.id, j.titulo, j.empresa, j.territorio, j.fuente_principal, j.semantic_hash,
                  (SELECT o.descripcion_texto FROM observations o
                     JOIN job_observations jo ON jo.observation_id = o.id
                    WHERE jo.job_id = j.id ORDER BY o.detectado_en DESC LIMIT 1) AS texto
           FROM jobs j WHERE j.id=?""",
        (job_id,),
    ).fetchone()
    if fila is None:
        return None
    return {
        "job_id": fila["id"],
        "titulo": fila["titulo"],
        "empresa": fila["empresa"],
        "region": fila["territorio"],
        "texto": fila["texto"] or "",
        "hash": fila["semantic_hash"],
    }


def _complejidad(conn: sqlite3.Connection, job_id: str) -> str:
    fila = conn.execute(
        "SELECT elegibilidad, incertidumbres_json FROM analyses"
        " WHERE job_id=? AND obsoleto=0 ORDER BY id DESC LIMIT 1",
        (job_id,),
    ).fetchone()
    if fila is None:
        return COMPLEJIDAD_BASE
    incertidumbres = json.loads(fila["incertidumbres_json"] or "[]")
    return COMPLEJIDAD_DUDA if (fila["elegibilidad"] != "eligible" or incertidumbres) else COMPLEJIDAD_BASE


def analizar_uno(cliente: Cliente, conn: sqlite3.Connection, job_id: str,
                 proposito: str = "analisis") -> dict:
    datos = contenido_de(conn, job_id)
    if datos is None:
        raise ValueError(f"oferta inexistente: {job_id}")
    texto_plano = datos["texto"] or ""
    if len(texto_plano.strip()) < 40:
        raise ValueError("la oferta no tiene texto suficiente para analizar")

    contenido = contenido_oferta(datos["titulo"], datos["empresa"], datos["region"], texto_plano)
    complejidad = _complejidad(conn, job_id)
    resultado = cliente.analizar(
        contenido=contenido,
        instruccion=instruccion(),
        contenido_hash=datos["hash"],
        proposito=proposito,
        complejidad=complejidad,
        job_id=job_id,
    )
    analisis: AnalisisIA = resultado["analisis"]
    validas, invalidas = evidencias_verificadas(analisis, texto_plano)
    _guardar(conn, job_id, datos["hash"], resultado, analisis, len(invalidas))
    return {
        "job_id": job_id,
        "proveedor": resultado["proveedor"],
        "modelo": resultado["modelo"],
        "complejidad": complejidad,
        "cache": resultado.get("cache", False),
        "confianza": analisis.confianza,
        "evidencias_validas": len(validas),
        "evidencias_invalidas": len(invalidas),
        "costo_usd": resultado.get("costo_usd", 0.0),
    }


def _guardar(conn: sqlite3.Connection, job_id: str, contenido_hash: str,
             resultado: dict, analisis: AnalisisIA, invalidas: int) -> None:
    with db.transaccion(conn):
        conn.execute(
            """INSERT INTO ai_analyses
                   (job_id, job_version_id, proveedor, modelo, categoria, seniority, modalidad,
                    elegibilidad_territorial, habilidades_obligatorias_json,
                    habilidades_deseables_json, anios_experiencia, idiomas_json, salario_json,
                    evidencia_json, incertidumbres_json, explicacion, confianza,
                    evidencia_invalida, aplicado, creado_en)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)
               ON CONFLICT(job_id, job_version_id, modelo) DO UPDATE SET
                   categoria=excluded.categoria, seniority=excluded.seniority,
                   modalidad=excluded.modalidad,
                   elegibilidad_territorial=excluded.elegibilidad_territorial,
                   habilidades_obligatorias_json=excluded.habilidades_obligatorias_json,
                   habilidades_deseables_json=excluded.habilidades_deseables_json,
                   anios_experiencia=excluded.anios_experiencia,
                   idiomas_json=excluded.idiomas_json, salario_json=excluded.salario_json,
                   evidencia_json=excluded.evidencia_json,
                   incertidumbres_json=excluded.incertidumbres_json,
                   explicacion=excluded.explicacion, confianza=excluded.confianza,
                   evidencia_invalida=excluded.evidencia_invalida,
                   creado_en=excluded.creado_en""",
            (
                job_id, None, resultado["proveedor"], resultado["modelo"],
                analisis.categoria, analisis.seniority, analisis.modalidad,
                analisis.elegibilidad_territorial,
                json.dumps(analisis.habilidades_obligatorias, ensure_ascii=False),
                json.dumps(analisis.habilidades_deseables, ensure_ascii=False),
                analisis.anios_experiencia,
                json.dumps(analisis.idiomas, ensure_ascii=False),
                json.dumps(analisis.salario.model_dump(), ensure_ascii=False) if analisis.salario else None,
                json.dumps([e.model_dump() for e in analisis.evidencia], ensure_ascii=False),
                json.dumps(analisis.incertidumbres, ensure_ascii=False),
                analisis.explicacion, analisis.confianza, invalidas,
                config.ahora_utc(),
            ),
        )
    _ = contenido_hash


def procesar_cola(conn: sqlite3.Connection, cliente: Cliente, maximo: int = 20,
                  epoch: str = "ia") -> dict:
    """Procesa la cola respetando cuota. Si se agota, suspende sin perder nada."""
    resumen = {"procesadas": 0, "descartadas": 0, "diferidas": 0, "suspendida": False,
               "motivo": "", "costo_usd": 0.0}
    procesadas = 0
    while procesadas < maximo:
        lote = cola.reclamar(conn, limite=min(5, maximo - procesadas), epoch=epoch)
        if not lote:
            break
        for tarea in lote:
            procesadas += 1
            try:
                resultado = analizar_uno(cliente, conn, tarea["job_id"])
            except ValueError as exc:
                cola.descartar(conn, tarea["id"], str(exc))
                resumen["descartadas"] += 1
                continue
            except Rechazo as exc:
                cola.descartar(conn, tarea["id"], f"rechazada: {exc.motivo}")
                resumen["descartadas"] += 1
                logs.registrar("ia_rechazo", motivo=exc.motivo, codigo=exc.codigo)
                continue
            except SinCuota as exc:
                cola.pausar_todo(conn, exc.reintentar_en_segundos,
                                 f"sin cuota: {exc.detalle[:2]}")
                resumen["suspendida"] = True
                resumen["motivo"] = "sin cuota gratuita; se reintenta más tarde"
                logs.registrar("ia_sin_cuota", detalle=exc.detalle[:3])
                return resumen
            except Exception as exc:  # noqa: BLE001 - un fallo no rompe la cola
                estado = cola.fallar(conn, tarea["id"], repr(exc), 600, tarea["intentos"])
                resumen["diferidas"] += 1
                logs.registrar("ia_error", tarea=tarea["id"], estado=estado, error=repr(exc)[:200])
                continue
            cola.completar(conn, tarea["id"])
            resumen["procesadas"] += 1
            resumen["costo_usd"] += resultado.get("costo_usd", 0.0)
    return resumen


def resumen(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM ai_analyses").fetchone()[0]
    con_evidencia = conn.execute(
        "SELECT COUNT(*) FROM ai_analyses WHERE evidencia_invalida=0"
    ).fetchone()[0]
    por_modelo = [
        dict(f) for f in conn.execute(
            "SELECT modelo, COUNT(*) AS n, AVG(confianza) AS confianza FROM ai_analyses"
            " GROUP BY modelo ORDER BY n DESC"
        ).fetchall()
    ]
    return {
        "analisis": total,
        "con_evidencia_valida": con_evidencia,
        "por_modelo": por_modelo,
        "cola": cola.contar(conn),
        "cache": cache_mod.estadisticas(conn),
    }


def ultimo(conn: sqlite3.Connection, job_id: str) -> dict | None:
    fila = conn.execute(
        "SELECT * FROM ai_analyses WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,)
    ).fetchone()
    if fila is None:
        return None
    datos = dict(fila)
    for campo in ("habilidades_obligatorias", "habilidades_deseables", "idiomas",
                  "evidencia", "incertidumbres"):
        crudo = datos.pop(f"{campo}_json", None)
        try:
            datos[campo] = json.loads(crudo) if crudo else []
        except json.JSONDecodeError:
            datos[campo] = []
    return datos


def hash_para(oferta: dict) -> str:
    """Hash estable para la caché: contenido decisivo, sin fechas de captura."""
    material = f"{oferta.get('titulo')}|{oferta.get('empresa')}|{oferta.get('texto', '')[:4000]}"
    return hash_texto(material)


def texto_plano(valor: str | None) -> str:
    return html_a_texto(valor or "")
