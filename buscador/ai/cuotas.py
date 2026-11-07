"""Cuotas por proveedor: RPM, RPD, TPM y TPD con ventanas persistentes.

Los topes se leen del catálogo y pueden ajustarse desde Configuración. Las
ventanas viven en SQLite, así que sobreviven a reinicios y a varias ejecuciones
simultáneas. Si un tope no se conoce (0 o ausente), no se inventa: se aplica sólo
lo que la fuente declara.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .. import config, db
from .proveedores import Modelo, Proveedor


def _minuto(ahora: datetime | None = None) -> str:
    return (ahora or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M")


def _dia(ahora: datetime | None = None) -> str:
    return (ahora or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def consumido(conn: sqlite3.Connection, proveedor: str, modelo: str,
              ahora: datetime | None = None) -> dict:
    minuto, dia = _minuto(ahora), _dia(ahora)
    fila = conn.execute(
        """SELECT COALESCE(SUM(peticiones),0) AS peticiones,
                  COALESCE(SUM(tokens_entrada),0) AS entrada,
                  COALESCE(SUM(tokens_salida),0) AS salida
           FROM ai_usage WHERE proveedor=? AND modelo=? AND minuto=?""",
        (proveedor, modelo, minuto),
    ).fetchone()
    delDia = conn.execute(
        """SELECT COALESCE(SUM(peticiones),0) AS peticiones,
                  COALESCE(SUM(tokens_entrada),0) AS entrada,
                  COALESCE(SUM(tokens_salida),0) AS salida
           FROM ai_usage WHERE proveedor=? AND modelo=? AND dia=?""",
        (proveedor, modelo, dia),
    ).fetchone()
    return {
        "rpm": int(fila["peticiones"]),
        "tpm": int(fila["entrada"]) + int(fila["salida"]),
        "rpd": int(delDia["peticiones"]),
        "tpd": int(delDia["entrada"]) + int(delDia["salida"]),
    }


def registrar(conn: sqlite3.Connection, proveedor: str, modelo: str,
              tokens_entrada: int, tokens_salida: int,
              ahora: datetime | None = None) -> None:
    minuto, dia = _minuto(ahora), _dia(ahora)
    with db.transaccion(conn):
        conn.execute(
            """INSERT INTO ai_usage (proveedor, modelo, minuto, dia, peticiones,
                                     tokens_entrada, tokens_salida)
               VALUES (?,?,?,?,1,?,?)
               ON CONFLICT(proveedor, modelo, minuto) DO UPDATE SET
                   peticiones = peticiones + 1,
                   tokens_entrada = tokens_entrada + excluded.tokens_entrada,
                   tokens_salida = tokens_salida + excluded.tokens_salida""",
            (proveedor, modelo, minuto, dia, tokens_entrada, tokens_salida),
        )


def verificar(conn: sqlite3.Connection, proveedor: Proveedor, modelo: Modelo,
              tokens_estimados: int = 0, ahora: datetime | None = None) -> tuple[bool, str]:
    """Devuelve (hay_cuota, motivo). No consume: sólo consulta."""
    limites = _limites(conn, proveedor)
    uso = consumido(conn, proveedor.clave, modelo.id, ahora)
    if limites.get("rpm") and uso["rpm"] >= limites["rpm"]:
        return False, f"tope por minuto alcanzado ({uso['rpm']}/{limites['rpm']} RPM)"
    if limites.get("rpd") and uso["rpd"] >= limites["rpd"]:
        return False, f"tope diario alcanzado ({uso['rpd']}/{limites['rpd']} RPD)"
    if limites.get("tpm") and uso["tpm"] + tokens_estimados > limites["tpm"]:
        return False, f"tope de tokens por minuto ({uso['tpm']}/{limites['tpm']} TPM)"
    if limites.get("tpd") and uso["tpd"] + tokens_estimados > limites["tpd"]:
        return False, f"tope de tokens por día ({uso['tpd']}/{limites['tpd']} TPD)"
    return True, "con cuota"


def _limites(conn: sqlite3.Connection, proveedor: Proveedor) -> dict[str, int]:
    """Los ajustes manuales mandan sobre el catálogo (por si cambian los topes)."""
    limites = dict(proveedor.limites)
    for clave in ("rpm", "rpd", "tpm", "tpd"):
        valor = db.ajuste(conn, f"ia_limite_{proveedor.clave}_{clave}", "")
        if valor:
            try:
                limites[clave] = int(valor)
            except ValueError:
                pass
    return limites


def resumen(conn: sqlite3.Connection) -> dict:
    filas = conn.execute(
        """SELECT proveedor, modelo, SUM(peticiones) AS peticiones,
                  SUM(tokens_entrada) AS entrada, SUM(tokens_salida) AS salida
           FROM ai_usage WHERE dia=? GROUP BY proveedor, modelo ORDER BY peticiones DESC""",
        (_dia(),),
    ).fetchall()
    return {
        "dia": _dia(),
        "por_modelo": [dict(f) for f in filas],
        "total_peticiones": sum(f["peticiones"] for f in filas),
        "total_tokens": sum((f["entrada"] or 0) + (f["salida"] or 0) for f in filas),
    }


def reiniciar_dia(conn: sqlite3.Connection, dia: str | None = None) -> int:
    """Borra el contador de un día. Sólo para pruebas o corrección manual."""
    objetivo = dia or _dia()
    with db.transaccion(conn):
        cur = conn.execute("DELETE FROM ai_usage WHERE dia=?", (objetivo,))
    return cur.rowcount
