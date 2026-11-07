"""Revisión de posibles duplicados entre fuentes (fusión suave y reversible).

La regla del proyecto es explícita: no se fusiona sin identificador fuerte. Lo
que hace este módulo es **sugerir** y dejar la decisión en manos del usuario.
Aceptar no borra nada: la oferta absorbida apunta a la que la reemplaza con
`merged_into` y deja de listarse. Revertir la devuelve a la vista.
"""

from __future__ import annotations

import json
import sqlite3

from . import config, db


def sugerencias(conn: sqlite3.Connection, limite: int = 100) -> list[dict]:
    return [
        dict(f)
        for f in conn.execute(
            """SELECT m.id, m.job_origen, m.job_destino, m.similitud, m.motivo, m.estado, m.creado_en,
                      o.titulo AS titulo_origen, o.empresa AS empresa_origen, o.fuente_principal AS fuente_origen,
                      d.titulo AS titulo_destino, d.empresa AS empresa_destino, d.fuente_principal AS fuente_destino
               FROM merge_reviews m
               JOIN jobs o ON o.id = m.job_origen
               JOIN jobs d ON d.id = m.job_destino
               ORDER BY CASE m.estado WHEN 'sugerida' THEN 0 ELSE 1 END, m.similitud DESC
               LIMIT ?""",
            (limite,),
        ).fetchall()
    ]


def contar_pendientes(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute("SELECT COUNT(*) FROM merge_reviews WHERE estado='sugerida'").fetchone()[0]
    )


def depurar(conn: sqlite3.Connection) -> int:
    """Retira sugerencias pendientes que dejaron de cumplir el criterio.

    Ocurre cuando cambia el umbral o cuando dos avisos del mismo editor quedaron
    marcados como duplicados: son vacantes distintas, no un cruce entre fuentes.
    """
    from .ingest import UMBRAL_SUGERENCIA

    filas = conn.execute(
        """SELECT m.id, m.similitud, o.fuente_principal AS origen, d.fuente_principal AS destino,
                  o.merged_into AS origen_merged, d.merged_into AS destino_merged
           FROM merge_reviews m
           JOIN jobs o ON o.id = m.job_origen
           JOIN jobs d ON d.id = m.job_destino
           WHERE m.estado='sugerida'"""
    ).fetchall()
    obsoletas = [
        f["id"] for f in filas
        if f["origen"] == f["destino"]
        or f["similitud"] < UMBRAL_SUGERENCIA
        or f["origen_merged"] or f["destino_merged"]
    ]
    if not obsoletas:
        return 0
    with db.transaccion(conn):
        conn.executemany("DELETE FROM merge_reviews WHERE id=?", [(i,) for i in obsoletas])
    return len(obsoletas)


def _auditar(conn: sqlite3.Connection, tipo: str, detalle: dict) -> None:
    conn.execute(
        "INSERT INTO audit_events (tipo, detalle_json, creado_en) VALUES (?,?,?)",
        (tipo, json.dumps(detalle, ensure_ascii=False), config.ahora_utc()),
    )


def aceptar(conn: sqlite3.Connection, review_id: int) -> dict:
    fila = conn.execute("SELECT * FROM merge_reviews WHERE id=?", (review_id,)).fetchone()
    if fila is None:
        raise ValueError("sugerencia inexistente")
    if fila["estado"] != "sugerida":
        return {"cambiado": False, "motivo": f"estado actual: {fila['estado']}"}
    destino = conn.execute("SELECT merged_into FROM jobs WHERE id=?", (fila["job_destino"],)).fetchone()
    if destino is None or destino["merged_into"]:
        raise ValueError("la oferta destino ya no está disponible")

    with db.transaccion(conn):
        conn.execute(
            "UPDATE jobs SET merged_into=? WHERE id=?", (fila["job_destino"], fila["job_origen"])
        )
        conn.execute("UPDATE analyses SET obsoleto=1 WHERE job_id=?", (fila["job_origen"],))
        conn.execute(
            "UPDATE merge_reviews SET estado='aceptada', resuelto_en=? WHERE id=?",
            (config.ahora_utc(), review_id),
        )
        _auditar(conn, "fusion_aceptada", {
            "review": review_id, "origen": fila["job_origen"], "destino": fila["job_destino"],
            "similitud": fila["similitud"],
        })
    return {"cambiado": True, "origen": fila["job_origen"], "destino": fila["job_destino"]}


def rechazar(conn: sqlite3.Connection, review_id: int) -> dict:
    with db.transaccion(conn):
        cur = conn.execute(
            "UPDATE merge_reviews SET estado='rechazada', resuelto_en=? WHERE id=? AND estado='sugerida'",
            (config.ahora_utc(), review_id),
        )
        if cur.rowcount:
            _auditar(conn, "fusion_rechazada", {"review": review_id})
    return {"cambiado": bool(cur.rowcount)}


def revertir(conn: sqlite3.Connection, review_id: int) -> dict:
    fila = conn.execute("SELECT * FROM merge_reviews WHERE id=?", (review_id,)).fetchone()
    if fila is None or fila["estado"] != "aceptada":
        return {"cambiado": False, "motivo": "sólo se revierte una fusión aceptada"}
    with db.transaccion(conn):
        conn.execute("UPDATE jobs SET merged_into=NULL WHERE id=?", (fila["job_origen"],))
        conn.execute(
            "UPDATE merge_reviews SET estado='revertida', resuelto_en=? WHERE id=?",
            (config.ahora_utc(), review_id),
        )
        _auditar(conn, "fusion_revertida", {
            "review": review_id, "origen": fila["job_origen"], "destino": fila["job_destino"],
        })
    return {"cambiado": True}
