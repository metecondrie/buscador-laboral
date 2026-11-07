"""Cola persistente de análisis con IA.

Si no hay cuota, la tarea no se pierde: queda `deferred` con `next_due` y se
reintenta cuando la ventana se libere. El rastreador nunca depende de esta cola.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from .. import config, db

PRIORIDAD_RAPIDA = 10      # elegibles: primero lo que sirve
PRIORIDAD_DUDA = 20        # dudosas: resolver incertidumbre
PRIORIDAD_NUEVA = 60
PRIORIDAD_RESTO = 100
MAX_INTENTOS = 6


def encolar(conn: sqlite3.Connection, job_id: str, job_version_id: int | None,
            motivo: str = "nuevo", prioridad: int = PRIORIDAD_NUEVA) -> bool:
    ahora = config.ahora_utc()
    with db.transaccion(conn):
        cur = conn.execute(
            """INSERT OR IGNORE INTO ai_queue
                   (job_id, job_version_id, motivo, prioridad, estado, intentos, next_due,
                    creado_en, actualizado_en)
               VALUES (?,?,?,?, 'queued', 0, ?, ?, ?)""",
            (job_id, job_version_id, motivo, prioridad, ahora, ahora, ahora),
        )
    return bool(cur.rowcount)


def prioridad_para(elegibilidad: str | None, tiene_incertidumbre: bool) -> int:
    if elegibilidad == "eligible":
        return PRIORIDAD_RAPIDA
    if elegibilidad == "doubtful" or tiene_incertidumbre:
        return PRIORIDAD_DUDA
    if elegibilidad == "incompatible":
        return PRIORIDAD_RESTO
    return PRIORIDAD_NUEVA


def encolar_pendientes(conn: sqlite3.Connection, limite: int = 50) -> int:
    """Encola ofertas sin análisis de IA para la versión de reglas vigente."""
    from .. import config as cfg

    filas = conn.execute(
        """SELECT j.id, j.id AS job_id, a.elegibilidad,
                  (SELECT COUNT(*) FROM ai_analyses x WHERE x.job_id=j.id) AS analizados
           FROM jobs j
           LEFT JOIN analyses a ON a.job_id=j.id AND a.obsoleto=0
           WHERE j.merged_into IS NULL
             AND (SELECT COUNT(*) FROM ai_analyses x WHERE x.job_id=j.id) = 0
           ORDER BY CASE a.elegibilidad WHEN 'eligible' THEN 0
                                        WHEN 'doubtful' THEN 1
                                        ELSE 2 END,
                    j.ultima_deteccion DESC
           LIMIT ?""",
        (limite,),
    ).fetchall()
    encoladas = 0
    for fila in filas:
        prioridad = prioridad_para(fila["elegibilidad"], fila["elegibilidad"] == "doubtful")
        if encolar(conn, fila["job_id"], None, "pendiente", prioridad):
            encoladas += 1
    return encoladas


def reclamar(conn: sqlite3.Connection, limite: int = 5, epoch: str = "ia") -> list[dict]:
    ahora = config.ahora_utc()
    with db.transaccion(conn):
        filas = conn.execute(
            """UPDATE ai_queue
               SET estado='running', locked_by=?, intentos=intentos+1, actualizado_en=?
               WHERE id IN (
                   SELECT id FROM ai_queue
                   WHERE estado IN ('queued','deferred') AND next_due<=?
                   ORDER BY prioridad, next_due LIMIT ?
               )
               RETURNING *""",
            (epoch, ahora, ahora, limite),
        ).fetchall()
    return [dict(f) for f in filas]


def completar(conn: sqlite3.Connection, tarea_id: int) -> None:
    with db.transaccion(conn):
        conn.execute(
            "UPDATE ai_queue SET estado='done', locked_by=NULL, ultimo_error=NULL,"
            " actualizado_en=? WHERE id=?",
            (config.ahora_utc(), tarea_id),
        )


def fallar(conn: sqlite3.Connection, tarea_id: int, error: str,
           reintentar_en_segundos: int | None = None, intentos: int = 0) -> str:
    """Devuelve el estado aplicado. Tras varios intentos se rinde."""
    if intentos >= MAX_INTENTOS:
        estado = "failed"
        proximo = config.ahora_utc()
    else:
        estado = "deferred"
        proximo = (datetime.now(timezone.utc) + timedelta(seconds=reintentar_en_segundos or 900))
        proximo = proximo.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with db.transaccion(conn):
        conn.execute(
            "UPDATE ai_queue SET estado=?, ultimo_error=?, next_due=?, locked_by=NULL,"
            " actualizado_en=? WHERE id=?",
            (estado, error[:400], proximo, config.ahora_utc(), tarea_id),
        )
    return estado


def descartar(conn: sqlite3.Connection, tarea_id: int, motivo: str) -> None:
    with db.transaccion(conn):
        conn.execute(
            "UPDATE ai_queue SET estado='skipped', ultimo_error=?, locked_by=NULL,"
            " actualizado_en=? WHERE id=?",
            (motivo[:400], config.ahora_utc(), tarea_id),
        )


def contar(conn: sqlite3.Connection) -> dict[str, int]:
    filas = conn.execute("SELECT estado, COUNT(*) AS n FROM ai_queue GROUP BY estado").fetchall()
    return {f["estado"]: f["n"] for f in filas}


def proxima(conn: sqlite3.Connection) -> str | None:
    fila = conn.execute(
        "SELECT MIN(next_due) AS proxima FROM ai_queue WHERE estado IN ('queued','deferred')"
    ).fetchone()
    return fila["proxima"] if fila else None


def pausar_todo(conn: sqlite3.Connection, segundos: int, motivo: str) -> int:
    """Suspende la cola cuando se agotaron las cuotas gratuitas."""
    proximo = (datetime.now(timezone.utc) + timedelta(seconds=segundos))
    proximo = proximo.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with db.transaccion(conn):
        cur = conn.execute(
            "UPDATE ai_queue SET estado='deferred', next_due=?, ultimo_error=?, actualizado_en=?"
            " WHERE estado IN ('queued','deferred')",
            (proximo, motivo[:300], config.ahora_utc()),
        )
    return cur.rowcount
