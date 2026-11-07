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
