"""Caché de respuestas de IA por contenido, modelo y versión del prompt.

Evita pagar dos veces por el mismo análisis. La clave incluye el hash del
contenido de la oferta, el modelo y la versión del prompt: si cambia cualquiera
de los tres, se vuelve a consultar.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from .. import config, db

VERSION_PROMPT = "analisis-oferta-2.0.0"


def clave(contenido_hash: str, modelo: str, version_prompt: str = VERSION_PROMPT) -> str:
    material = f"{contenido_hash}|{modelo}|{version_prompt}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def obtener(conn: sqlite3.Connection, clave_: str) -> dict | None:
    fila = conn.execute(
        "SELECT respuesta_json FROM ai_cache WHERE clave=?", (clave_,)
    ).fetchone()
    if fila is None:
        return None
    with db.transaccion(conn):
        conn.execute(
            "UPDATE ai_cache SET hits = hits + 1, usado_en=? WHERE clave=?",
            (config.ahora_utc(), clave_),
        )
    try:
        return json.loads(fila["respuesta_json"])
    except json.JSONDecodeError:
        return None


def guardar(conn: sqlite3.Connection, clave_: str, proveedor: str, modelo: str,
            respuesta: dict, version_prompt: str = VERSION_PROMPT) -> None:
    with db.transaccion(conn):
        conn.execute(
            """INSERT INTO ai_cache (clave, proveedor, modelo, prompt_version,
                                     respuesta_json, creado_en, usado_en, hits)
               VALUES (?,?,?,?,?,?,?,0)
               ON CONFLICT(clave) DO UPDATE SET
                   respuesta_json=excluded.respuesta_json, usado_en=excluded.usado_en""",
            (clave_, proveedor, modelo, version_prompt,
             json.dumps(respuesta, ensure_ascii=False), config.ahora_utc(), config.ahora_utc()),
        )


def estadisticas(conn: sqlite3.Connection) -> dict:
    fila = conn.execute(
        "SELECT COUNT(*) AS entradas, COALESCE(SUM(hits),0) AS reutilizaciones FROM ai_cache"
    ).fetchone()
    return {"entradas": fila["entradas"], "reutilizaciones": fila["reutilizaciones"]}


def limpiar(conn: sqlite3.Connection) -> int:
    with db.transaccion(conn):
        cur = conn.execute("DELETE FROM ai_cache")
    return cur.rowcount
