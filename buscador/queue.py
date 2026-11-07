"""Cola durable de tareas con reclamo atómico (T02)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from . import config, db


def encolar(conn: sqlite3.Connection, kind: str, unique_key: str,
            reencolar_si_completada: bool = False, **campos) -> bool:
    """Encola una tarea.

    Con `reencolar_si_completada` la tarea vuelve a la cola aunque ya exista como
    `completed`. Hace falta cuando el resultado anterior se invalidó: sin eso, la
    clave ya existe, el `INSERT` se ignora y el trabajo no se rehace nunca.
    """
    ahora = config.ahora_utc()
    with db.transaccion(conn):
        cur = conn.execute(
            """INSERT INTO tasks (kind, unique_key, job_id, job_version_id, profile_version_id,
                   rules_version, estado, intentos, next_due, creado_en, actualizado_en)
               VALUES (?,?,?,?,?,?, 'queued', 0, ?, ?, ?)
               ON CONFLICT(unique_key) DO UPDATE SET
                   estado='queued', intentos=0, next_due=excluded.next_due,
                   locked_by_epoch=NULL, locked_at=NULL, error=NULL,
                   actualizado_en=excluded.actualizado_en
               WHERE tasks.estado='completed'""",
            (
                kind, unique_key, campos.get("job_id"), campos.get("job_version_id"),
                campos.get("profile_version_id"), campos.get("rules_version", config.RULES_VERSION),
                campos.get("next_due", ahora), ahora, ahora,
            ),
        ) if reencolar_si_completada else conn.execute(
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


def descartar_obsoletas(conn: sqlite3.Connection, profile_version_id: int,
                       rules_version: str | None = None) -> int:
    """Descarta tareas planeadas para un perfil o unas reglas que ya no rigen.

    Sin esto, la cola de una versión anterior se procesa igual y escribe análisis
    con un perfil inactivo: quedan como vigentes (`obsoleto=0`) aunque no
    correspondan a nadie, y el catálogo muestra puntajes de un perfil que ya se
    cambió. Las `running` no se tocan: las tiene otro trabajador.
    """
    from . import config as cfg

    reglas = rules_version or cfg.RULES_VERSION
    with db.transaccion(conn):
        cur = conn.execute(
            """UPDATE tasks SET estado='skipped', locked_by_epoch=NULL, locked_at=NULL,
                   error=?, actualizado_en=?
               WHERE estado IN ('queued','deferred')
                 AND ((profile_version_id IS NOT NULL AND profile_version_id<>?)
                      OR rules_version<>?)""",
            ("planeada para un perfil o reglas anteriores", cfg.ahora_utc(),
             profile_version_id, reglas),
        )
        descartadas = cur.rowcount
    return descartadas


def recuperar_tareas(conn: sqlite3.Connection, epoch_actual: str) -> int:
    """Devuelve a la cola las tareas que quedaron `running` sin dueño.

    Pasa cuando el proceso muere a mitad de una clasificación. Sin esto la tarea
    queda `running` para siempre: nadie la reclama y la oferta nunca se clasifica,
    aunque la cola parezca vacía.
    """
    with db.transaccion(conn):
        cur = conn.execute(
            """UPDATE tasks SET estado='queued', locked_by_epoch=NULL, locked_at=NULL, actualizado_en=?
               WHERE estado='running' AND (locked_by_epoch IS NULL OR locked_by_epoch<>?)""",
            (config.ahora_utc(), epoch_actual),
        )
        recuperadas = cur.rowcount
    return recuperadas


def recuperar_huerfanas(conn: sqlite3.Connection, epoch_actual: str) -> int:
    """Devuelve a la cola las tareas de corridas abandonadas por caída."""
    recuperadas = recuperar_tareas(conn, epoch_actual)
    with db.transaccion(conn):
        conn.execute(
            "UPDATE runs SET estado='abandoned', finished_at=COALESCE(finished_at, ?) WHERE estado='running' AND run_epoch<>?",
            (config.ahora_utc(), epoch_actual),
        )
    return recuperadas


def contar(conn: sqlite3.Connection) -> dict[str, int]:
    filas = conn.execute("SELECT estado, COUNT(*) AS n FROM tasks GROUP BY estado").fetchall()
    return {f["estado"]: f["n"] for f in filas}
