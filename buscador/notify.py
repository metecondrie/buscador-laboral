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
    """Marca los avisos encolados como entregados y registra el intento.

    `delivered` significa **disponible en la bandeja local**, no que se haya
    enviado un correo, un mensaje externo ni una postulación. La bandeja es el
    canal primario; el escritorio es una tostada opcional del mismo equipo.
    """
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


def resumen_bandeja(conn: sqlite3.Connection) -> dict:
    """Separa histórico, lectura y vigencia de la recomendación.

    La pastilla del navegador muestra `no_leidos` (avisos históricos sin leer).
    `vigentes_sin_leer` es la parte que todavía corresponde a una oferta elegible:
    sirve para no presentar un aviso viejo como si fuera una recomendación actual.
    """
    avisos = bandeja(conn, limite=10000)
    sin_leer = [a for a in avisos if not a["leido"]]
    return {
        "total": len(avisos),
        "historicos": len(avisos),
        "leidos": len(avisos) - len(sin_leer),
        "no_leidos": len(sin_leer),
        "vigentes": sum(1 for a in avisos if not a["desactualizado"]),
        "vigentes_sin_leer": sum(1 for a in sin_leer if not a["desactualizado"]),
        "desactualizados": sum(1 for a in avisos if a["desactualizado"]),
        "con_puntaje_cambiado": sum(1 for a in avisos if a["cambio_puntaje"]),
    }


def marcar_leidos(conn: sqlite3.Connection) -> int:
    with db.transaccion(conn):
        cur = conn.execute(
            "UPDATE notifications SET leido_en=? WHERE leido_en IS NULL", (config.ahora_utc(),)
        )
    return cur.rowcount


def bandeja(conn: sqlite3.Connection, limite: int = 100) -> list[dict]:
    """Avisos listos para mostrar: campos legibles, sin JSON crudo.

    Cada registro distingue tres momentos que la pantalla no debe mezclar:

    - **al avisar**: puntaje y confianza guardados en el payload, tal como eran
      cuando se emitió el aviso. Nunca cambian.
    - **ahora**: puntaje y elegibilidad del análisis vigente. Cambian cuando se
      actualizan las reglas o el perfil.
    - **estado del aviso**: `queued`/`delivered` significa «está en la bandeja»,
      no que se haya enviado nada a ningún lado. La lectura es `leido_en`.
    """
    filas = conn.execute(
        """SELECT n.id, n.clave, n.estado, n.creado_en, n.leido_en, n.entregado_en,
                  n.payload_json, n.canal,
                  j.titulo, j.empresa, j.url_atribucion, j.id AS job_id,
                  a.score AS score_actual, a.elegibilidad AS elegibilidad_actual,
                  a.confianza AS confianza_actual
           FROM notifications n
           JOIN jobs j ON j.id = n.job_id
           LEFT JOIN analyses a ON a.job_id = j.id AND a.obsoleto = 0
           ORDER BY n.id DESC LIMIT ?""",
        (limite,),
    ).fetchall()

    avisos = []
    for f in filas:
        try:
            payload = json.loads(f["payload_json"])
        except (TypeError, json.JSONDecodeError):
            payload = {}
        score_al_avisar = payload.get("score")
        score_actual = f["score_actual"]
        elegibilidad = f["elegibilidad_actual"]
        # Un aviso emitido cuando la oferta era elegible no debe presentarse como
        # recomendación vigente si el análisis actual ya no lo dice.
        desactualizado = (
            elegibilidad is None
            or elegibilidad != "eligible"
            or score_actual is None
        )
        cambio_puntaje = (
            score_al_avisar is not None and score_actual is not None
            and abs(float(score_actual) - float(score_al_avisar)) >= 1
        )
        avisos.append({
            "id": f["id"],
            "job_id": f["job_id"],
            "titulo": f["titulo"],
            "empresa": f["empresa"],
            "url": f["url_atribucion"],
            "creado_en": f["creado_en"],
            "leido": f["leido_en"] is not None,
            "leido_en": f["leido_en"],
            # El aviso vive en la bandeja local; "delivered" no es un envío externo.
            "canal": "bandeja local",
            "estado_db": f["estado"],
            "score_al_avisar": score_al_avisar,
            "score_actual": score_actual,
            "confianza_al_avisar": payload.get("confianza"),
            "confianza_actual": f["confianza_actual"],
            "elegibilidad_actual": elegibilidad,
            "desactualizado": desactualizado,
            "cambio_puntaje": cambio_puntaje,
        })
    return avisos
