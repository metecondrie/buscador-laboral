"""Postulaciones reales: fecha, enlace y notas. Una por oferta.

«Guardar» y «me interesa» son intenciones; esto registra un hecho. La aplicación
**nunca** envía una postulación: sólo anota que ya se envió por fuera.

Decisiones:

- `job_id` es la clave primaria, así que registrar dos veces la misma oferta
  actualiza la fila en lugar de duplicarla.
- Cada cambio deja un evento en `user_events` (append-only) con un
  `action_id` determinista por oferta y fecha: reintentar el mismo formulario no
  infla el historial.
- Retirar no borra: pasa el estado a `retirada` y conserva fecha, enlace y notas
  por si vuelve a postularse.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date

from . import config, db

ESTADOS = ("postulada", "retirada")


def _hoy() -> str:
    return date.today().isoformat()


def _limpiar(texto: str | None, limite: int = 500) -> str | None:
    if not texto:
        return None
    limpio = " ".join(str(texto).split()).strip()
    return limpio[:limite] or None


def _normalizar_fecha(valor: str | None) -> str:
    if not valor:
        return _hoy()
    try:
        return date.fromisoformat(str(valor)[:10]).isoformat()
    except ValueError:
        return _hoy()


def _evento(conn: sqlite3.Connection, job_id: str, accion: str, accion_id: str) -> None:
    with db.transaccion(conn):
        conn.execute(
            """INSERT OR IGNORE INTO user_events
                   (action_id, job_id, accion, creado_en, version_esperada, payload_json)
               VALUES (?,?,?,?, 'v1', NULL)""",
            (accion_id, job_id, accion, config.ahora_utc()),
        )


def registrar(conn: sqlite3.Connection, job_id: str, fecha: str | None = None,
              enlace: str | None = None, notas: str | None = None) -> dict:
    """Crea o actualiza la postulación de una oferta. Idempotente por oferta."""
    existe = conn.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone()
    if existe is None:
        raise LookupError(f"oferta inexistente: {job_id}")

    dia = _normalizar_fecha(fecha)
    enlace_limpio = _limpiar(enlace, 800)
    notas_limpias = _limpiar(notas, 2000)
    ahora = config.ahora_utc()

    previa = conn.execute(
        "SELECT estado, fecha, enlace, notas FROM applications WHERE job_id=?", (job_id,)
    ).fetchone()
    with db.transaccion(conn):
        conn.execute(
            """INSERT INTO applications (job_id, estado, fecha, enlace, notas,
                                         creado_en, actualizado_en)
               VALUES (?, 'postulada', ?, ?, ?, ?, ?)
               ON CONFLICT(job_id) DO UPDATE SET
                   estado='postulada', fecha=excluded.fecha,
                   enlace=COALESCE(excluded.enlace, applications.enlace),
                   notas=COALESCE(excluded.notas, applications.notas),
                   actualizado_en=excluded.actualizado_en""",
            (job_id, dia, enlace_limpio, notas_limpias, ahora, ahora),
        )

    # Mismo día y misma oferta ⇒ mismo acción: reintentar no duplica historial.
    _evento(conn, job_id, "postular", f"postular:{job_id}:{dia}")
    return {
        "job_id": job_id,
        "estado": "postulada",
        "fecha": dia,
        "enlace": enlace_limpio or (previa["enlace"] if previa else None),
        "notas": notas_limpias or (previa["notas"] if previa else None),
        "nueva": previa is None,
        "reabierta": bool(previa and previa["estado"] == "retirada"),
    }


def retirar(conn: sqlite3.Connection, job_id: str) -> bool:
    """Marca la postulación como retirada. No borra: conserva el registro."""
    with db.transaccion(conn):
        cur = conn.execute(
            "UPDATE applications SET estado='retirada', actualizado_en=? "
            "WHERE job_id=? AND estado<>'retirada'",
            (config.ahora_utc(), job_id),
        )
        retirada = bool(cur.rowcount)
    if retirada:
        _evento(conn, job_id, "retirar", f"retirar:{job_id}:{uuid.uuid4().hex[:8]}")
    return retirada


def obtener(conn: sqlite3.Connection, job_id: str) -> dict | None:
    fila = conn.execute("SELECT * FROM applications WHERE job_id=?", (job_id,)).fetchone()
    return dict(fila) if fila else None


def vigente(conn: sqlite3.Connection, job_id: str) -> dict | None:
    """La postulación sólo si sigue en pie."""
    datos = obtener(conn, job_id)
    return datos if datos and datos["estado"] == "postulada" else None


def listar(conn: sqlite3.Connection, estado: str = "postulada",
           limite: int = 200) -> list[dict]:
    filas = conn.execute(
        """SELECT a.*, j.titulo, j.empresa, j.fuente_principal, j.estado_vigencia
           FROM applications a JOIN jobs j ON j.id=a.job_id
           WHERE a.estado=? ORDER BY a.fecha DESC, a.actualizado_en DESC LIMIT ?""",
        (estado, int(limite)),
    ).fetchall()
    return [dict(f) for f in filas]


def contar(conn: sqlite3.Connection) -> dict:
    filas = conn.execute(
        "SELECT estado, COUNT(*) AS n FROM applications GROUP BY estado").fetchall()
    conteo = {f["estado"]: f["n"] for f in filas}
    conteo.setdefault("postulada", 0)
    conteo.setdefault("retirada", 0)
    return conteo


def historial(conn: sqlite3.Connection, job_id: str, limite: int = 20) -> list[dict]:
    filas = conn.execute(
        """SELECT accion, creado_en FROM user_events
           WHERE job_id=? AND accion IN ('postular','retirar')
           ORDER BY id DESC LIMIT ?""",
        (job_id, int(limite)),
    ).fetchall()
    return [dict(f) for f in filas]
