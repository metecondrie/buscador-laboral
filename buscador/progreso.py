"""Progreso de una corrida leído de la base, no de la memoria del proceso.

Todo lo que la interfaz muestra sale de acá, y todo lo que hay acá sale de
tablas: `runs`, `source_runs`, `analyses`, `tasks`, `ai_queue` y `ai_analyses`.
La consecuencia práctica es que el panel funciona igual desde cualquier pestaña,
sobrevive a recargar la página y no miente si el proceso que lanzó la búsqueda
ya no existe.

Dos decisiones que conviene conocer:

- **El denominador es real.** Al planificar la corrida se crea una fila
  `source_runs` por fuente con estado `pending`. La barra avanza cuando esas
  filas cambian de estado, así que el porcentaje nunca es una estimación.
- **Una corrida sin latido se declara abandonada.** `heartbeat_at` se actualiza
  entre fuentes. Si el servidor muere a mitad de camino, la corrida queda
  `running` en la base para siempre y bloquearía «Buscar ahora»; pasado el
  umbral se informa como abandonada en lugar de fingir que sigue viva.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from . import config, db

# Una fuente puede tardar: conexión 10 s + lectura 30 s y hasta tres páginas. El
# latido se escribe entre fuentes, así que el umbral tiene que cubrir la más
# lenta sin dejar bloqueada una corrida muerta.
SIN_LATIDO_S = 180

ESTADOS_OK = {"success", "empty_valid", "partial"}
ESTADOS_FINALES = ESTADOS_OK | {"network_error", "rate_limited", "auth_required",
                                "access_restricted", "schema_changed", "blocked",
                                "cancelled", "failed", "error"}


def _segundos_desde(marca: str | None) -> float | None:
    if not marca:
        return None
    try:
        cuando = datetime.fromisoformat(marca.replace("Z", "+00:00"))
    except ValueError:
        return None
    if cuando.tzinfo is None:
        cuando = cuando.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - cuando).total_seconds()


def _json(valor) -> dict:
    if not valor:
        return {}
    try:
        datos = json.loads(valor)
        return datos if isinstance(datos, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _delta_ms(desde: str | None, hasta: str | None) -> int | None:
    """Milisegundos entre dos marcas ISO. `None` si falta alguna o es inválida."""
    if not desde or not hasta:
        return None
    try:
        a = datetime.fromisoformat(desde.replace("Z", "+00:00"))
        b = datetime.fromisoformat(hasta.replace("Z", "+00:00"))
    except ValueError:
        return None
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return int((b - a).total_seconds() * 1000)


def corrida(conn: sqlite3.Connection) -> dict | None:
    """La corrida más reciente, esté viva o no."""
    fila = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(fila) if fila else None


def activa(conn: sqlite3.Connection) -> dict | None:
    """Corrida viva según la base: `running` y con latido reciente."""
    fila = conn.execute(
        "SELECT * FROM runs WHERE estado='running' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if fila is None:
        return None
    datos = dict(fila)
    edad = _segundos_desde(datos.get("heartbeat_at") or datos.get("started_at"))
    datos["viva"] = edad is not None and edad <= SIN_LATIDO_S
    datos["sin_latido_s"] = round(edad, 1) if edad is not None else None
    return datos


def _fuentes(conn: sqlite3.Connection, run: dict) -> dict:
    filas = conn.execute(
        """SELECT r.id, r.source_id, r.estado, r.started_at, r.finished_at, r.observaciones,
                  r.nuevas, r.actualizadas, r.error_code, r.error_msg,
                  COALESCE(s.nombre, r.source_id) AS nombre
           FROM source_runs r LEFT JOIN sources s ON s.source_id = r.source_id
           WHERE r.run_id=? ORDER BY r.id""",
        (run["id"],),
    ).fetchall()
    detalle = [dict(f) for f in filas]

    pendientes = [f for f in detalle if f["estado"] == "pending"]
    ejecutando = [f for f in detalle if f["estado"] == "running"]
    completadas = [f for f in detalle if f["estado"] in ESTADOS_OK]
    # `cancelled` no es un error: es una fuente que no llegó a consultarse.
    # Mezclarlas haría que cancelar pareciera una corrida llena de fallos.
    canceladas = [f for f in detalle if f["estado"] == "cancelled"]
    fallidas = [f for f in detalle if f["estado"] not in ESTADOS_OK
                and f["estado"] not in ("pending", "running", "cancelled")]

    total = run.get("total_fuentes") or len(detalle)
    hechas = len(completadas) + len(fallidas) + len(canceladas)
    return {
        "total": total,
        "pendientes": len(pendientes),
        "ejecutando": len(ejecutando),
        "completadas": len(completadas),
        "fallidas": len(fallidas),
        "canceladas": len(canceladas),
        "procesadas": hechas,
        # Sólo fuentes con estado final: la barra no avanza por tiempo.
        "fraccion": round(hechas / total, 4) if total else 0.0,
        "actual": (ejecutando[0]["source_id"] if ejecutando else None),
        "actual_nombre": (ejecutando[0]["nombre"] if ejecutando else None),
        "detalle": detalle,
    }


def _ofertas(conn: sqlite3.Connection, run: dict) -> dict:
    """Cifras de la búsqueda y del catálogo.

    Se distinguen dos familias a propósito:

    - **de esta corrida** (`revisadas`, `nuevas`, `duplicadas`, `clasificadas_new`):
      lo que el aviso descargó y clasificó ahora;
    - **del catálogo** (`elegibles`, `dudosas`, `incompatibles`): el total vigente,
      que es lo que el usuario puede postular.

    Mezclarlas hace que un resumen diga «1 candidata» cuando en realidad hay 10:
    sólo una se recalculó en esa corrida.
    """
    base = conn.execute(
        """SELECT COALESCE(SUM(observaciones),0) AS revisadas,
                  COALESCE(SUM(nuevas),0) AS nuevas,
                  COALESCE(SUM(duplicadas),0) AS duplicadas
           FROM source_runs WHERE run_id=?""",
        (run["id"],),
    ).fetchone()

    totales = {
        fila["elegibilidad"]: fila["n"]
        for fila in conn.execute(
            "SELECT elegibilidad, COUNT(*) AS n FROM analyses WHERE obsoleto=0"
            " GROUP BY elegibilidad"
        ).fetchall()
    }

    # El delta se atribuye por `run_id`, no por reloj: dos corridas en el mismo
    # segundo comparten marca de tiempo y se robaban los análisis entre sí.
    nuevas = {
        fila["elegibilidad"]: fila["n"]
        for fila in conn.execute(
            """SELECT elegibilidad, COUNT(*) AS n FROM analyses
               WHERE obsoleto=0 AND run_id=? GROUP BY elegibilidad""",
            (run["id"],),
        ).fetchall()
    }
    ultima = conn.execute(
        "SELECT MAX(creado_en) AS marca FROM analyses WHERE obsoleto=0 AND run_id=?",
        (run["id"],),
    ).fetchone()

    return {
        "revisadas": int(base["revisadas"] or 0),
        "nuevas": int(base["nuevas"] or 0),
        "duplicadas": int(base["duplicadas"] or 0),
        "elegibles": int(totales.get("eligible", 0)),
        "dudosas": int(totales.get("doubtful", 0)),
        "incompatibles": int(totales.get("incompatible", 0)),
        "elegibles_nuevas": int(nuevas.get("eligible", 0)),
        "dudosas_nuevas": int(nuevas.get("doubtful", 0)),
        "clasificadas": sum(int(v) for v in nuevas.values()),
        "ultima_clasificacion": ultima["marca"] if ultima else None,
    }


def _ia(conn: sqlite3.Connection, run: dict | None = None) -> dict:
    """Estado real de la IA. No toca el almacén de credenciales ni la red."""
    habilitada = db.ajuste(conn, "ia_habilitada", "0") == "1"
    conteo = {
        fila["estado"]: fila["n"]
        for fila in conn.execute("SELECT estado, COUNT(*) AS n FROM ai_queue GROUP BY estado").fetchall()
    }
    pendientes = int(conteo.get("queued", 0)) + int(conteo.get("deferred", 0))
    analizando = int(conteo.get("running", 0))

    desde = (run or {}).get("started_at")
    en_corrida = (
        conn.execute("SELECT COUNT(*) FROM ai_analyses WHERE creado_en>=?", (desde,)).fetchone()[0]
        if desde else 0
    )

    cuota = {"disponible": False, "motivo": "", "modelo": None}
    if not habilitada:
        cuota["motivo"] = "IA desactivada en Configuración"
    else:
        referencia = (db.ajuste(conn, "ia_cascada", "") or "").split(",")[0].strip()
        from .ai import cuotas as cuotas_mod
        from .ai.proveedores import parsear

        par = parsear(referencia) if referencia else None
        if par is None:
            cuota["motivo"] = "sin modelo en la cascada"
        else:
            proveedor, modelo = par
            cuota["modelo"] = f"{proveedor.clave}:{modelo.id}"
            libre, motivo = cuotas_mod.verificar(conn, proveedor, modelo)
            estado_prov = db.ajuste(conn, f"ia_estado_{proveedor.clave}", "")
            if estado_prov == "invalida":
                cuota["motivo"] = "la credencial figura como inválida"
            elif not modelo.dentro_cuota_gratuita:
                cuota["motivo"] = "el modelo no es gratuito"
            else:
                cuota["disponible"] = bool(libre)
                cuota["motivo"] = motivo

    return {
        "habilitada": habilitada,
        "pendientes": pendientes,
        "analizando": analizando,
        "en_corrida": int(en_corrida),
        "consumidas": int(conteo.get("done", 0)),
        "cuota": cuota,
    }


def _resumen(conn: sqlite3.Connection, run: dict, fuentes: dict, ofertas: dict) -> dict:
    guardado = _json(run.get("resumen_json"))
    if guardado:
        return guardado
    # Corrida en curso o interrumpida: se arma con lo que hay, sin inventar.
    errores = [
        {"source_id": f["source_id"], "nombre": f["nombre"],
         "motivo": f.get("error_code") or f["estado"]}
        for f in fuentes["detalle"]
        if f["estado"] not in ESTADOS_OK
        and f["estado"] not in ("pending", "running", "cancelled")
    ]
    return {
        # Una corrida interrumpida igual informa cuánto duró.
        "duracion_ms": _delta_ms(run.get("started_at"), run.get("finished_at")),
        "fuentes_procesadas": fuentes["procesadas"],
        "fuentes_total": fuentes["total"],
        "errores": errores,
        "nuevas": ofertas["nuevas"],
        "candidatas": ofertas["elegibles"] + ofertas["dudosas"],
        "candidatas_nuevas": ofertas["elegibles_nuevas"] + ofertas["dudosas_nuevas"],
        "incompletas": True,
    }


def snapshot(conn: sqlite3.Connection, run_id: int | None = None) -> dict:
    """Estado observable de una corrida (la indicada, la activa o la última)."""
    if run_id is not None:
        fila = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        run = dict(fila) if fila else None
        viva = bool(run and run["estado"] == "running")
        if viva:
            edad = _segundos_desde(run.get("heartbeat_at") or run.get("started_at"))
            viva = edad is not None and edad <= SIN_LATIDO_S
    else:
        run = activa(conn)
        viva = bool(run and run["viva"])
        if run is None:
            run = corrida(conn)
            viva = False

    if run is None:
        return {
            "version": 0,
            "activo": False,
            "estado": "sin_corridas",
            "run_id": None,
            "iniciada": None,
            "duracion_ms": None,
            "fuentes": {"total": 0, "pendientes": 0, "ejecutando": 0, "completadas": 0,
                        "fallidas": 0, "canceladas": 0, "procesadas": 0, "fraccion": 0.0,
                        "actual": None, "actual_nombre": None, "detalle": []},
            "ofertas": {"revisadas": 0, "nuevas": 0, "duplicadas": 0, "elegibles": 0,
                        "dudosas": 0, "incompatibles": 0, "elegibles_nuevas": 0,
                        "dudosas_nuevas": 0, "clasificadas": 0,
                        "ultima_clasificacion": None},
            "ia": _ia(conn),
            "resumen": {},
            "cola": {
                fila["estado"]: fila["n"]
                for fila in conn.execute(
                    "SELECT estado, COUNT(*) AS n FROM tasks GROUP BY estado").fetchall()
            },
        }

    fuentes = _fuentes(conn, run)
    ofertas = _ofertas(conn, run)
    duracion = _delta_ms(run.get("started_at"), run.get("finished_at"))

    estado = run["estado"]
    if estado == "running" and not viva:
        # Mismo vocabulario que la base: la interfaz sólo compara una vez.
        estado = "abandoned"

    return {
        # `version` cambia cuando cambia algo observable: la interfaz sólo
        # redibuja si el número se movió.
        "version": int(run["id"]) * 10_000 + fuentes["procesadas"] * 100
                   + min(ofertas["clasificadas"], 99),
        "activo": viva,
        "estado": estado,
        "cancelada": bool(run.get("cancelada")),
        "run_id": run["id"],
        "causa": run.get("causa"),
        "iniciada": run.get("started_at"),
        "finalizada": run.get("finished_at"),
        "duracion_ms": duracion,
        "fuentes": fuentes,
        "ofertas": ofertas,
        "ia": _ia(conn, run),
        "resumen": _resumen(conn, run, fuentes, ofertas),
        "cola": {
            fila["estado"]: fila["n"]
            for fila in conn.execute("SELECT estado, COUNT(*) AS n FROM tasks GROUP BY estado").fetchall()
        },
    }


def marcar_abandonada(conn: sqlite3.Connection, run_id: int) -> bool:
    """Cierra una corrida que nadie está ejecutando.

    Pasa cuando el proceso muere a mitad de camino: la fila queda `running` y,
    si no se corrige, la interfaz muestra una búsqueda fantasma y el botón no
    responde. Las fuentes que no llegaron a correr quedan `cancelled`, no
    `success`: el progreso no debe contar como procesado lo que no se procesó.
    """
    with db.transaccion(conn):
        cur = conn.execute(
            "UPDATE runs SET estado='abandoned', finished_at=COALESCE(finished_at, ?)"
            " WHERE id=? AND estado='running'",
            (config.ahora_utc(), run_id),
        )
        conn.execute(
            "UPDATE source_runs SET estado='cancelled', finished_at=?"
            " WHERE run_id=? AND estado IN ('pending','running')",
            (config.ahora_utc(), run_id),
        )
    return bool(cur.rowcount)


def cancelada(conn: sqlite3.Connection, run_id: int) -> bool:
    """¿Se pidió cancelar? El trabajador lo consulta entre fuentes."""
    fila = conn.execute("SELECT cancelada FROM runs WHERE id=?", (run_id,)).fetchone()
    return bool(fila and fila["cancelada"])


def marcar_cancelada(conn: sqlite3.Connection, run_id: int) -> bool:
    """Pide cancelar. El trabajador la atiende entre fuentes, no a la fuerza."""
    with db.transaccion(conn):
        cur = conn.execute(
            "UPDATE runs SET cancelada=1 WHERE id=? AND estado='running'", (run_id,)
        )
    return bool(cur.rowcount)


def guardar_resumen(conn: sqlite3.Connection, run_id: int, resumen: dict) -> None:
    with db.transaccion(conn):
        conn.execute(
            "UPDATE runs SET resumen_json=? WHERE id=?",
            (json.dumps(resumen, ensure_ascii=False), run_id),
        )


def latido(conn: sqlite3.Connection, run_id: int) -> None:
    with db.transaccion(conn):
        conn.execute("UPDATE runs SET heartbeat_at=? WHERE id=?", (config.ahora_utc(), run_id))
