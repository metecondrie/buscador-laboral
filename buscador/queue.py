"""Cola durable de tareas con reclamo atómico (T02)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from . import config, db


def encolar(conn: sqlite3.Connection, kind: str, unique_key: str, **campos) -> bool:
    ahora = config.ahora_utc()
    with db.transaccion(conn):
        cur = conn.execute(
        """INSERT OR IGNORE INTO tasks (kind, unique_key, job_id, job_version_id, profile_version_id,
               rules_version, estado, intentos, next_due, creado_en, actualizado_en)
           VALUES (?,?,?,?,?,?, 'queued', 0, ?, ?, ?)""",
        (
            kind, unique_key, campos.get("job_id"), campos.get("job_version_id"),
            campos.get("profile_version_id"), campos.get("rules_version", config.RULES_VERSION),
            campos.get("next_due", ahora), ahora, ahora,
        ),
    )
    return bool(cur.rowcount)


def reclamar(conn: sqlite3.Connection, epoch: str, limite: int = 10) -> list[dict]:
    """Reclama tareas vencidas y registra el intento en una transacción breve."""
    ahora = config.ahora_utc()
    with db.transaccion(conn):
        filas = conn.execute(
            """UPDATE tasks
               SET estado='running', locked_by_epoch=?, locked_at=?, intentos=intentos+1, actualizado_en=?
               WHERE id IN (
                   SELECT id FROM tasks
                   WHERE estado IN ('queued','deferred') AND next_due<=?
                   ORDER BY next_due LIMIT ?
               )
               RETURNING *""",
            (epoch, ahora, ahora, ahora, limite),
        ).fetchall()
    return [dict(f) for f in filas]


def completar(conn: sqlite3.Connection, task_id: int) -> None:
    with db.transaccion(conn):
        conn.execute(
            "UPDATE tasks SET estado='completed', locked_by_epoch=NULL, locked_at=NULL, error=NULL, actualizado_en=? WHERE id=?",
            (config.ahora_utc(), task_id),
        )


def fallar(conn: sqlite3.Connection, task_id: int, error: str, reintentar_en_segundos: int | None = None) -> None:
    estado = "failed"
    proximo = config.ahora_utc()
    if reintentar_en_segundos is not None:
        estado = "deferred"
        proximo = (
            datetime.now(timezone.utc) + timedelta(seconds=reintentar_en_segundos)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with db.transaccion(conn):
        conn.execute(
            """UPDATE tasks SET estado=?, error=?, next_due=?, locked_by_epoch=NULL, locked_at=NULL,
                   actualizado_en=? WHERE id=?""",
            (estado, error[:500], proximo, config.ahora_utc(), task_id),
        )


def recuperar_huerfanas(conn: sqlite3.Connection, epoch_actual: str) -> int:
    """Devuelve a la cola las tareas de corridas abandonadas por caída."""
    with db.transaccion(conn):
        cur = conn.execute(
            """UPDATE tasks SET estado='queued', locked_by_epoch=NULL, locked_at=NULL, actualizado_en=?
               WHERE estado='running' AND (locked_by_epoch IS NULL OR locked_by_epoch<>?)""",
            (config.ahora_utc(), epoch_actual),
        )
        recuperadas = cur.rowcount
    with db.transaccion(conn):
        conn.execute(
            "UPDATE runs SET estado='abandoned', finished_at=COALESCE(finished_at, ?) WHERE estado='running' AND run_epoch<>?",
            (config.ahora_utc(), epoch_actual),
        )
    return recuperadas


def contar(conn: sqlite3.Connection) -> dict[str, int]:
    filas = conn.execute("SELECT estado, COUNT(*) AS n FROM tasks GROUP BY estado").fetchall()
    return {f["estado"]: f["n"] for f in filas}
