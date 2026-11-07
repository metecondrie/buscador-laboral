"""Acceso a SQLite con los PRAGMA de durabilidad del plan (D02)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import config

ESQUEMA = Path(__file__).with_name("schema.sql")
MIGRACIONES = Path(__file__).with_name("migrations")
VERSION_ESQUEMA = 10


def conectar(ruta: Path | None = None) -> sqlite3.Connection:
    destino = Path(ruta) if ruta is not None else config.rutas().db
    destino.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(destino, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def inicializar(ruta: Path | None = None) -> Path:
    """Crea la base si no existe, aplica el esquema y migra versiones previas."""
    destino = Path(ruta) if ruta is not None else config.crear_estructura().db
    conn = conectar(destino)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            conn.executescript(ESQUEMA.read_text(encoding="utf-8"))
            conn.commit()
            _sembrar_ajustes(conn)
            return destino
        if version > VERSION_ESQUEMA:
            raise RuntimeError(
                f"la base usa el esquema {version}, más nuevo que el soportado ({VERSION_ESQUEMA})"
            )
        while version < VERSION_ESQUEMA:
            siguiente = version + 1
            archivo = MIGRACIONES / f"v{siguiente}.sql"
            if not archivo.exists():
                raise RuntimeError(f"falta la migración del esquema {version} a {siguiente}")
            try:
                conn.executescript(archivo.read_text(encoding="utf-8"))
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                raise RuntimeError(f"migración v{siguiente} falló: {exc}") from exc
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        _sembrar_ajustes(conn)
    finally:
        conn.close()
    return destino


def _sembrar_ajustes(conn: sqlite3.Connection) -> None:
    """Crea los ajustes que falten sin pisar los valores ya elegidos."""
    try:
        with transaccion(conn):
            for clave, valor in config.AJUSTES_POR_DEFECTO.items():
                conn.execute(
                    "INSERT OR IGNORE INTO settings (clave, valor, actualizado_en) VALUES (?,?,?)",
                    (clave, valor, config.ahora_utc()),
                )
    except sqlite3.Error:
        # Una base de esquema 1 sin migrar todavía no tiene `settings`.
        pass


@contextmanager
def transaccion(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Transacción breve: confirma al salir, revierte ante cualquier error."""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def pragmas(conn: sqlite3.Connection) -> dict[str, object]:
    return {
        "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
        "synchronous": conn.execute("PRAGMA synchronous").fetchone()[0],
        "foreign_keys": conn.execute("PRAGMA foreign_keys").fetchone()[0],
        "busy_timeout": conn.execute("PRAGMA busy_timeout").fetchone()[0],
        "user_version": conn.execute("PRAGMA user_version").fetchone()[0],
    }


def una(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()):
    fila = conn.execute(sql, params).fetchone()
    return dict(fila) if fila is not None else None


def varias(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> list[dict]:
    return [dict(f) for f in conn.execute(sql, params).fetchall()]


def ajuste(conn: sqlite3.Connection, clave: str, por_defecto: str = "") -> str:
    fila = conn.execute("SELECT valor FROM settings WHERE clave=?", (clave,)).fetchone()
    return fila["valor"] if fila else por_defecto


def guardar_ajuste(conn: sqlite3.Connection, clave: str, valor: str) -> None:
    with transaccion(conn):
        conn.execute(
            """INSERT INTO settings (clave, valor, actualizado_en) VALUES (?,?,?)
               ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor,
                   actualizado_en=excluded.actualizado_en""",
            (clave, valor, config.ahora_utc()),
        )


def integridad(ruta: Path) -> tuple[bool, str]:
    """Comprueba el archivo con `PRAGMA integrity_check` sin abrirlo en escritura."""
    if not Path(ruta).exists():
        return False, "no existe"
    conn = sqlite3.connect(f"file:{Path(ruta).as_posix()}?mode=ro", uri=True)
    try:
        resultado = conn.execute("PRAGMA integrity_check").fetchone()[0]
        return resultado == "ok", str(resultado)
    finally:
        conn.close()
