"""Esquema: versión, migraciones idempotentes y ajustes por defecto."""

from __future__ import annotations

import sqlite3

from buscador import config, db


def test_esquema_actual_y_columnas_nuevas(entorno):
    assert db.pragmas(entorno)["user_version"] == db.VERSION_ESQUEMA
    columnas_analisis = {f[1] for f in entorno.execute("PRAGMA table_info(analyses)")}
    assert "excepcion" in columnas_analisis
    columnas_jobs = {f[1] for f in entorno.execute("PRAGMA table_info(jobs)")}
    assert "merged_into" in columnas_jobs
    columnas_source_runs = {f[1] for f in entorno.execute("PRAGMA table_info(source_runs)")}
    assert {"relevantes", "duplicadas"} <= columnas_source_runs
    for tabla in ("settings", "merge_reviews", "ai_calls", "ai_budget", "backup_log", "incidents"):
        existe = entorno.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tabla,)
        ).fetchone()
        assert existe is not None, f"falta la tabla {tabla}"


def test_inicializar_es_idempotente(tmp_path):
    destino = tmp_path / "base.db"
    db.inicializar(destino)
    db.inicializar(destino)
    db.inicializar(destino)
    conn = db.conectar(destino)
    try:
        assert db.pragmas(conn)["user_version"] == db.VERSION_ESQUEMA
        assert conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] >= 1
    finally:
        conn.close()


def test_ajustes_por_defecto_se_siembran_sin_pisar(entorno):
    assert db.ajuste(entorno, "intervalo_horas") == "12"
    db.guardar_ajuste(entorno, "intervalo_horas", "8")
    db.inicializar(config.rutas().db)
    assert db.ajuste(entorno, "intervalo_horas") == "8"


def test_base_mas_nueva_se_rechaza(tmp_path):
    destino = tmp_path / "futura.db"
    conn = sqlite3.connect(destino)
    conn.execute(f"PRAGMA user_version = {db.VERSION_ESQUEMA + 1}")
    conn.commit()
    conn.close()
    try:
        db.inicializar(destino)
    except RuntimeError as exc:
        assert "más nuevo" in str(exc)
    else:
        raise AssertionError("debía rechazar una base de versión superior")


def test_pragmas_de_durabilidad(entorno):
    pragmas = db.pragmas(entorno)
    assert pragmas["journal_mode"] == "wal"
    assert pragmas["synchronous"] == 2
    assert pragmas["foreign_keys"] == 1
    assert pragmas["busy_timeout"] == 5000


def test_toda_migracion_declara_su_version(entorno):
    """Si una migración olvida el PRAGMA, `inicializar` entra en bucle infinito."""
    assert db.VERSION_ESQUEMA >= 9
    for version in range(2, db.VERSION_ESQUEMA + 1):
        archivo = db.MIGRACIONES / f"v{version}.sql"
        assert archivo.exists(), f"falta la migración v{version}"
        assert f"PRAGMA user_version = {version}" in archivo.read_text(encoding="utf-8"), (
            f"v{version}.sql no declara PRAGMA user_version = {version}"
        )


def test_migracion_v8_repara_cuota_de_peticiones_rechazadas(entorno):
    """Un rechazo sin tokens no consume cuota; una respuesta con tokens sí."""
    with entorno:
        for estado, entrada, salida, cuota in (
            ("error", 0, 0, 1),      # rechazada: hay que corregirla
            ("invalida", 0, 0, 1),   # rechazada: hay que corregirla
            ("invalida", 900, 40, 1),  # respondió pero no validó: consumió de verdad
            ("ok", 900, 40, 1),      # correcta: no se toca
        ):
            entorno.execute(
                "INSERT INTO ai_calls (proveedor, modelo, proposito, tokens_entrada,"
                " tokens_salida, costo_usd, estado, creado_en, cuota_consumida)"
                " VALUES ('gemini','gemini-3.5-flash-lite','prueba',?,?,0,?,"
                "'2026-11-07T00:00:00Z',?)",
                (entrada, salida, estado, cuota),
            )
        entorno.executescript((db.MIGRACIONES / "v8.sql").read_text(encoding="utf-8"))

    filas = [
        dict(f) for f in entorno.execute(
            "SELECT estado, tokens_entrada, tokens_salida, cuota_consumida"
            " FROM ai_calls ORDER BY id"
        )
    ]
    assert [f["cuota_consumida"] for f in filas] == [0, 0, 1, 1]
