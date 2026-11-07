"""Entrega de avisos: bandeja local durable y, opcional, aviso de escritorio.

La bandeja es el canal primario y no depende de nada externo. El aviso de
escritorio es un extra apagado por defecto: se activa desde Configuración y,
si falla, el aviso sigue estando en la bandeja.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys

from . import config, db

CANAL_BANDEJA = "inbox"
CANAL_ESCRITORIO = "escritorio"
MAX_TOSTADAS = 3

_SCRIPT_TOAST = r"""
Add-Type -AssemblyName System.Windows.Forms
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.Visible = $true
$n.ShowBalloonTip(4000, $env:BUSCADOR_TITULO, $env:BUSCADOR_MENSAJE, 'Info')
Start-Sleep -Milliseconds 4500
$n.Dispose()
"""


def despachar(conn: sqlite3.Connection) -> int:
    """Marca los avisos encolados como entregados y registra el intento."""
    pendientes = conn.execute(
        "SELECT id, job_id, payload_json FROM notifications WHERE estado='queued' ORDER BY id"
    ).fetchall()
    if not pendientes:
        return 0

    escritorio = db.ajuste(conn, "notificar_escritorio", "0") == "1"
    entregados = 0
    tostadas = 0
    for fila in pendientes:
        detalle = "bandeja local"
        estado = "delivered"
        if escritorio and tostadas < MAX_TOSTADAS:
            ok, detalle_extra = _toast_desde_payload(fila["payload_json"])
            tostadas += 1
            detalle = f"bandeja local; escritorio: {detalle_extra}"
            if not ok:
                estado = "delivered"  # el aviso existe igual en la bandeja
        with db.transaccion(conn):
            conn.execute(
                "UPDATE notifications SET estado='delivered', entregado_en=? WHERE id=?",
                (config.ahora_utc(), fila["id"]),
            )
            conn.execute(
                "INSERT INTO delivery_attempts (notification_id, intento, estado, detalle, creado_en) VALUES (?,?,?,?,?)",
                (fila["id"], 1, estado, detalle, config.ahora_utc()),
            )
        entregados += 1
    return entregados


def _toast_desde_payload(payload_json: str) -> tuple[bool, str]:
    try:
        datos = json.loads(payload_json)
    except json.JSONDecodeError:
        return False, "payload inválido"
    titulo = f"{datos.get('titulo') or 'Oferta'} · {datos.get('empresa') or 'sin empresa'}"
    puntaje = datos.get("score")
    mensaje = f"Compatibilidad {puntaje}" if puntaje is not None else "Oferta compatible"
    if datos.get("excepcion"):
        mensaje += " (excepción por competencias)"
    return _toast(titulo[:120], mensaje[:180])


def _toast(titulo: str, mensaje: str) -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "el aviso de escritorio sólo está implementado en Windows"
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return False, "no se encontró PowerShell"
    entorno = dict(os.environ)
    entorno["BUSCADOR_TITULO"] = titulo
    entorno["BUSCADOR_MENSAJE"] = mensaje
    try:
        proceso = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", _SCRIPT_TOAST],
            capture_output=True, timeout=25, env=entorno, check=False,
        )
        if proceso.returncode != 0:
            return False, f"código {proceso.returncode}"
        return True, "mostrado"
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"{type(exc).__name__}"


def no_leidos(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM notifications WHERE leido_en IS NULL").fetchone()[0])


def marcar_leidos(conn: sqlite3.Connection) -> int:
    with db.transaccion(conn):
        cur = conn.execute(
            "UPDATE notifications SET leido_en=? WHERE leido_en IS NULL", (config.ahora_utc(),)
        )
    return cur.rowcount


def bandeja(conn: sqlite3.Connection, limite: int = 100) -> list[dict]:
    return [
        dict(f)
        for f in conn.execute(
            """SELECT n.id, n.clave, n.estado, n.creado_en, n.leido_en, n.payload_json,
                      j.titulo, j.empresa, j.url_atribucion, j.id AS job_id,
                      a.score, a.elegibilidad
               FROM notifications n
               JOIN jobs j ON j.id = n.job_id
               LEFT JOIN analyses a ON a.job_id = j.id AND a.obsoleto = 0
               ORDER BY n.id DESC LIMIT ?""",
            (limite,),
        ).fetchall()
    ]
