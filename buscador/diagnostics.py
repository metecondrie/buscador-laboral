"""Diagnóstico del sistema: estado, incidentes y paquete exportable."""

from __future__ import annotations

import json
import platform
import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path

from . import adapters, ai, backups, config, db, incidents, queue, scheduler

SECRETOS = {"key", "token", "password", "secret", "api_key", "authorization"}

# Etiquetas de la cola: `{'queued': 1280}` en pantalla no dice nada.
ETIQUETAS_TAREA = {
    "queued": "en cola", "deferred": "diferidas", "running": "en curso",
    "completed": "completadas", "skipped": "descartadas", "failed": "fallidas",
}


def _miles(numero: int) -> str:
    return f"{numero:,}".replace(",", " ")


def ultima_busqueda(conn: sqlite3.Connection) -> dict:
    """Cifras **de la última corrida**, separadas del acumulado del catálogo.

    Mezclarlas era el problema: «1 299 ofertas» es el catálogo y «825 revisadas»
    es lo que bajó la última búsqueda. No son la misma magnitud y no se suman.
    """
    run = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    if run is None:
        return {"hay": False}

    desde = run["started_at"]
    fuentes = {
        fila["estado"]: fila["n"]
        for fila in conn.execute(
            "SELECT estado, COUNT(*) AS n FROM source_runs WHERE run_id=? GROUP BY estado",
            (run["id"],),
        ).fetchall()
    }
    revisadas = conn.execute(
        "SELECT COALESCE(SUM(observaciones),0) FROM source_runs WHERE run_id=?",
        (run["id"],)).fetchone()[0]
    avisos_nuevos = conn.execute(
        "SELECT COALESCE(SUM(nuevas),0) FROM source_runs WHERE run_id=?",
        (run["id"],)).fetchone()[0]
    duplicadas = conn.execute(
        "SELECT COALESCE(SUM(duplicadas),0) FROM source_runs WHERE run_id=?",
        (run["id"],)).fetchone()[0]
    ofertas_nuevas = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE primera_deteccion>=?", (desde,)).fetchone()[0]
    errores_fuente = conn.execute(
        """SELECT COUNT(*) FROM source_runs WHERE run_id=?
           AND estado NOT IN ('success','empty_valid','partial','pending','running','cancelled')""",
        (run["id"],)).fetchone()[0]
    clasificadas = conn.execute(
        "SELECT COUNT(*) FROM analyses WHERE run_id=?", (run["id"],)).fetchone()[0]

    return {
        "hay": True,
        "run_id": run["id"],
        "causa": run["causa"],
        "estado": run["estado"],
        "iniciada": run["started_at"],
        "finalizada": run["finished_at"],
        "fuentes_ok": sum(fuentes.get(e, 0) for e in ("success", "empty_valid", "partial")),
        "fuentes_error": errores_fuente,
        "fuentes_total": sum(fuentes.values()),
        "revisadas": int(revisadas),
        "avisos_nuevos": int(avisos_nuevos),
        "ofertas_nuevas": int(ofertas_nuevas),
        "duplicadas": int(duplicadas),
        "clasificadas": int(clasificadas),
    }


def errores_clasificacion(conn: sqlite3.Connection) -> dict:
    """Tareas de clasificación que quedaron fallidas, con su último error."""
    total = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE estado='failed'").fetchone()[0]
    ultimo = conn.execute(
        "SELECT error, actualizado_en FROM tasks WHERE estado='failed'"
        " ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "fallidas": total,
        "ultimo_error": (ultimo["error"] if ultimo else None),
        "ultima_vez": (ultimo["actualizado_en"] if ultimo else None),
    }


def clasificacion(conn: sqlite3.Connection) -> dict:
    """Estado del catálogo clasificado, en números que se puedan leer.

    Diagnóstico mostraba `{'queued': 1280}` y `{}` en crudo. Un `{}` en
    elegibilidad es justamente lo que hay que ver como alarma, no como diccionario
    vacío: significa que ningún análisis está vigente.
    """
    ofertas = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE merged_into IS NULL").fetchone()[0]
    analizadas = conn.execute(
        "SELECT COUNT(DISTINCT job_id) FROM analyses WHERE obsoleto=0").fetchone()[0]
    por_elegibilidad = {
        fila["elegibilidad"]: fila["n"]
        for fila in conn.execute(
            "SELECT elegibilidad, COUNT(*) AS n FROM analyses WHERE obsoleto=0"
            " GROUP BY elegibilidad"
        ).fetchall()
    }
    tareas = queue.contar(conn)
    pendientes = (tareas.get("queued", 0) + tareas.get("deferred", 0)
                  + tareas.get("running", 0))
    # Marca de la última corrida: separa «ofertas nuevas» de «históricas».
    fila_corrida = conn.execute("SELECT started_at FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    hoy = fila_corrida["started_at"] if fila_corrida else None
    ultima = conn.execute(
        "SELECT MAX(creado_en) AS marca FROM analyses WHERE obsoleto=0").fetchone()
    perfil = conn.execute(
        "SELECT version, origen, creado_en FROM profile_versions WHERE activo=1"
        " ORDER BY id DESC LIMIT 1").fetchone()

    return {
        "ofertas": ofertas,
        "analizadas": analizadas,
        "sin_analisis": max(ofertas - analizadas, 0),
        "pendientes": pendientes,
        "elegibles": por_elegibilidad.get("eligible", 0),
        "dudosas": por_elegibilidad.get("doubtful", 0),
        "incompatibles": por_elegibilidad.get("incompatible", 0),
        "analisis_historicos": conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0],
        "ofertas_historicas": conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE primera_deteccion < ?",
            (hoy or "",)).fetchone()[0] if hoy else max(ofertas - analizadas, 0),
        "tareas": dict(tareas),
        "errores_clasificacion": errores_clasificacion(conn)["fallidas"],
        "tareas_texto": " · ".join(
            f"{_miles(n)} {ETIQUETAS_TAREA.get(estado, estado)}"
            for estado, n in sorted(tareas.items(), key=lambda par: -par[1])
        ) or "sin tareas",
        "ultima_clasificacion": ultima["marca"] if ultima else None,
        "perfil": dict(perfil) if perfil else None,
        "reglas": config.RULES_VERSION,
        # El catálogo vacío con cola pendiente es un fallo operativo, no un
        # estado normal: la pantalla lo dice y ofrece arreglarlo.
        "alerta": "sin_clasificaciones" if (pendientes and not analizadas) else "",
    }


def resumen(conn: sqlite3.Connection, rutas: config.Rutas | None = None) -> dict:
    rutas = rutas or config.rutas()
    conteos = {}
    for tabla in ("sources", "jobs", "observations", "analyses", "notifications", "tasks",
                  "incidents", "backup_log", "merge_reviews"):
        try:
            conteos[tabla] = conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
        except sqlite3.Error:
            conteos[tabla] = None

    elegibilidad = {
        fila["elegibilidad"]: fila["n"]
        for fila in conn.execute(
            "SELECT elegibilidad, COUNT(*) AS n FROM analyses WHERE obsoleto=0 GROUP BY elegibilidad"
        ).fetchall()
    }
    ultima = db.una(conn, "SELECT * FROM runs ORDER BY id DESC LIMIT 1")
    espacio = shutil.disk_usage(rutas.raiz if rutas.raiz.exists() else Path.cwd())

    return {
        "app": {"version": config.VERSION_APP, "rules": config.RULES_VERSION,
                "esquema": db.pragmas(conn)["user_version"]},
        "entorno": {
            "python": sys.version.split()[0],
            "ejecutable": sys.executable,
            "sqlite": sqlite3.sqlite_version,
            "sistema": f"{platform.system()} {platform.release()}",
        },
        "rutas": {
            "raiz": str(rutas.raiz),
            "base": str(rutas.db),
            "perfil": str(rutas.perfil),
            "respaldos": str(rutas.backups),
            "exportaciones": str(rutas.exports),
        },
        "base": {
            "pragmas": db.pragmas(conn),
            "conteos": conteos,
            "elegibilidad": elegibilidad,
            "ultima_corrida": ultima,
        },
        "clasificacion": clasificacion(conn),
        "ultima_busqueda": ultima_busqueda(conn),
        "errores_clasificacion": errores_clasificacion(conn),
        "disco": {"libre_gb": round(espacio.free / 1024 ** 3, 1),
                  "total_gb": round(espacio.total / 1024 ** 3, 1)},
        "fuentes": incidents.salud_por_fuente(conn),
        "incidentes": {"abiertos": incidents.abiertos(conn), "codigos": incidents.resumen_codigos(conn)},
        "cola": queue.contar(conn),
        "programacion": scheduler.estado(conn),
        "ia": ai.estado(conn),
        "respaldos": backups.listar(rutas)[:5],
    }


def _limpiar(datos):
    if isinstance(datos, dict):
        return {
            k: ("***" if any(s in k.lower() for s in SECRETOS) else _limpiar(v))
            for k, v in datos.items()
        }
    if isinstance(datos, list):
        return [_limpiar(v) for v in datos]
    return datos


def paquete(conn: sqlite3.Connection, rutas: config.Rutas | None = None) -> Path:
    """Genera un ZIP con lo necesario para diagnosticar sin exponer secretos."""
    rutas = rutas or config.rutas()
    rutas.exports.mkdir(parents=True, exist_ok=True)
    destino = rutas.exports / f"diagnostico-{config.ahora_utc().replace(':', '').replace('-', '')}.zip"

    datos = _limpiar(resumen(conn, rutas))
    corridas = [dict(f) for f in conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 20").fetchall()]
    por_fuente = [dict(f) for f in conn.execute(
        "SELECT * FROM source_runs ORDER BY id DESC LIMIT 60").fetchall()]
    historial = incidents.historial(conn, 100)
    fuentes = adapters.metadatos()

    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as paquete:
        paquete.writestr("diagnostico.json", json.dumps(datos, ensure_ascii=False, indent=2))
        paquete.writestr("corridas.json", json.dumps(corridas, ensure_ascii=False, indent=2))
        paquete.writestr("source_runs.json", json.dumps(por_fuente, ensure_ascii=False, indent=2))
        paquete.writestr("incidentes.json", json.dumps(historial, ensure_ascii=False, indent=2))
        paquete.writestr("fuentes.json", json.dumps(fuentes, ensure_ascii=False, indent=2))
        paquete.writestr("LEEME.txt", _leeme(datos))
        log = rutas.log
        if log.exists():
            lineas = log.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
            paquete.writestr("buscador.log", "\n".join(lineas))
    return destino


def _leeme(datos: dict) -> str:
    base = datos["base"]
    return (
        "Paquete de diagnóstico del Buscador Laboral\n"
        f"Generado: {config.ahora_utc()}\n"
        f"Versión: {datos['app']['version']} · reglas {datos['app']['rules']} · esquema {datos['app']['esquema']}\n\n"
        "Contenido:\n"
        "  diagnostico.json  estado general, salud por fuente y programación\n"
        "  corridas.json     últimas 20 corridas\n"
        "  source_runs.json  detalle por fuente de las últimas corridas\n"
        "  incidentes.json   historial de incidentes\n"
        "  fuentes.json      metadatos de los adaptadores\n"
        "  buscador.log      últimas 300 líneas del registro\n\n"
        f"Ofertas: {base['conteos'].get('jobs')} · observaciones: {base['conteos'].get('observations')}\n"
        "No se incluyen claves, tokens ni el contenido completo de las ofertas.\n"
    )
