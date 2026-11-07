"""Incidentes por fuente: registro, agrupación y cierre (diagnóstico de fallos)."""

from __future__ import annotations

import sqlite3
from collections import Counter

from . import config, db

CODIGOS = {
    "rate_limited": "La fuente pidió frenar (HTTP 429). Se reintenta en la próxima corrida.",
    "auth_required": "La fuente exige credenciales o una clave de API.",
    "access_restricted": "La fuente bloqueó el acceso o redirigió fuera del dominio aprobado.",
    "network_error": "Fallo de red, DNS o tiempo de espera agotado.",
    "schema_changed": "La respuesta ya no tiene la forma esperada: hay que revisar el parser.",
    "partial": "Se obtuvo una parte del lote y se descartó el resto.",
    "empty_valid": "La fuente respondió sin avisos: no es un fallo, es un listado vacío.",
    "clasificacion_fallida": "Una oferta no se pudo clasificar con las reglas actuales.",
}


def registrar(conn: sqlite3.Connection, source_id: str | None, codigo: str,
              mensaje: str | None = None, run_id: int | None = None) -> int:
    """Registra un incidente. Evita duplicar el mismo código abierto para la fuente."""
    with db.transaccion(conn):
        existente = conn.execute(
            "SELECT id FROM incidents WHERE source_id IS ? AND codigo=? AND resuelto_en IS NULL",
            (source_id, codigo),
        ).fetchone()
        if existente is not None:
            conn.execute(
                "UPDATE incidents SET mensaje=?, run_id=? WHERE id=?",
                ((mensaje or "")[:500], run_id, existente["id"]),
            )
            return int(existente["id"])
        cur = conn.execute(
            "INSERT INTO incidents (source_id, codigo, mensaje, run_id, creado_en) VALUES (?,?,?,?,?)",
            (source_id, codigo, (mensaje or "")[:500], run_id, config.ahora_utc()),
        )
    return int(cur.lastrowid)


def resolver(conn: sqlite3.Connection, source_id: str | None = None, codigo: str | None = None) -> int:
    sql = "UPDATE incidents SET resuelto_en=? WHERE resuelto_en IS NULL"
    params: list = [config.ahora_utc()]
    if source_id is not None:
        sql += " AND source_id=?"
        params.append(source_id)
    if codigo is not None:
        sql += " AND codigo=?"
        params.append(codigo)
    with db.transaccion(conn):
        cur = conn.execute(sql, tuple(params))
    return cur.rowcount


def resolver_por_exito(conn: sqlite3.Connection, source_id: str) -> int:
    """Cierra los incidentes de red y cuota de una fuente que volvió a responder."""
    with db.transaccion(conn):
        cur = conn.execute(
            """UPDATE incidents SET resuelto_en=?
               WHERE source_id=? AND resuelto_en IS NULL
                 AND codigo IN ('network_error','rate_limited','partial')""",
            (config.ahora_utc(), source_id),
        )
    return cur.rowcount


def abiertos(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(f)
        for f in conn.execute(
            """SELECT i.*, s.nombre AS fuente
               FROM incidents i LEFT JOIN sources s ON s.source_id=i.source_id
               WHERE i.resuelto_en IS NULL ORDER BY i.id DESC LIMIT 100"""
        ).fetchall()
    ]


def historial(conn: sqlite3.Connection, limite: int = 50) -> list[dict]:
    return [
        dict(f)
        for f in conn.execute(
            """SELECT i.*, s.nombre AS fuente
               FROM incidents i LEFT JOIN sources s ON s.source_id=i.source_id
               ORDER BY i.id DESC LIMIT ?""",
            (limite,),
        ).fetchall()
    ]


def salud_por_fuente(conn: sqlite3.Connection, corridas: int = 5) -> dict[str, dict]:
    """Estado reciente por fuente: últimos resultados, tasa de éxito e incidente abierto."""
    resultado: dict[str, dict] = {}
    for fila in conn.execute("SELECT source_id FROM sources ORDER BY source_id").fetchall():
        sid = fila["source_id"]
        ultimas = [
            dict(r)
            for r in conn.execute(
                """SELECT estado, started_at, observaciones, relevantes, error_code, error_msg
                   FROM source_runs WHERE source_id=? ORDER BY id DESC LIMIT ?""",
                (sid, corridas),
            ).fetchall()
        ]
        exitos = sum(1 for r in ultimas if r["estado"] in {"success", "empty_valid", "partial"})
        abierto = conn.execute(
            "SELECT codigo, mensaje, creado_en FROM incidents WHERE source_id=? AND resuelto_en IS NULL ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
        resultado[sid] = {
            "corridas": len(ultimas),
            "tasa_exito": round(exitos / len(ultimas), 2) if ultimas else None,
            "ultimo_estado": ultimas[0]["estado"] if ultimas else None,
            "ultima_corrida": ultimas[0]["started_at"] if ultimas else None,
            "observaciones_ultima": ultimas[0]["observaciones"] if ultimas else 0,
            "relevantes_ultima": ultimas[0]["relevantes"] if ultimas else 0,
            "incidente": dict(abierto) if abierto else None,
        }
    return resultado


def resumen_codigos(conn: sqlite3.Connection) -> list[dict]:
    filas = conn.execute(
        """SELECT codigo, COUNT(*) AS total,
                  SUM(CASE WHEN resuelto_en IS NULL THEN 1 ELSE 0 END) AS abiertos
           FROM incidents GROUP BY codigo ORDER BY total DESC"""
    ).fetchall()
    return [{**dict(f), "descripcion": CODIGOS.get(f["codigo"], "")} for f in filas]


def conteo(conn: sqlite3.Connection) -> Counter:
    return Counter(
        dict(f)["codigo"]
        for f in conn.execute("SELECT codigo FROM incidents WHERE resuelto_en IS NULL").fetchall()
    )
