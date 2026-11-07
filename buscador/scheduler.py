"""Búsqueda automática cada 12 horas (T06).

Dos caminos independientes y reversibles:

1. **En segundo plano dentro de la aplicación**: un hilo que despierta cada
   minuto y lanza la corrida cuando venció el intervalo. Requiere la interfaz
   abierta.
2. **Programador de tareas de Windows**: dos disparos diarios que ejecutan
   `buscar-automatico.cmd` sin necesidad de tener la interfaz abierta. Se
   activa sólo con el comando explícito `buscador programar --activar`.

Ambos comparten el mismo registro de corridas y el mismo candado, de modo que
nunca se solapan.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, db, logs

NOMBRE_TAREA = "BuscadorLaboral-12h"
CAUSAS_AUTOMATICAS = ("automatica", "programada")


def intervalo_horas(conn: sqlite3.Connection) -> int:
    try:
        valor = int(db.ajuste(conn, "intervalo_horas", str(config.INTERVALO_HORAS)))
    except ValueError:
        return config.INTERVALO_HORAS
    return valor if valor > 0 else config.INTERVALO_HORAS


def _ultima_automatica(conn: sqlite3.Connection) -> str | None:
    fila = conn.execute(
        f"""SELECT started_at FROM runs
            WHERE causa IN ({','.join('?' * len(CAUSAS_AUTOMATICAS))})
            ORDER BY id DESC LIMIT 1""",
        CAUSAS_AUTOMATICAS,
    ).fetchone()
    return fila["started_at"] if fila else None


def proxima(conn: sqlite3.Connection, ahora: datetime | None = None) -> datetime:
    ahora = ahora or datetime.now(timezone.utc)
    ultima = _ultima_automatica(conn)
    if not ultima:
        return ahora
    try:
        marca = datetime.fromisoformat(ultima.replace("Z", "+00:00"))
    except ValueError:
        return ahora
    return marca + timedelta(hours=intervalo_horas(conn))


def estado(conn: sqlite3.Connection, consultar_windows: bool = False) -> dict:
    ahora = datetime.now(timezone.utc)
    siguiente = proxima(conn, ahora)
    return {
        "intervalo_horas": intervalo_horas(conn),
        "ultima_automatica": _ultima_automatica(conn),
        "proxima": siguiente.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "vencida": siguiente <= ahora,
        "tarea_windows": estado_windows() if consultar_windows else estado_windows_cacheado(conn),
    }


def estado_windows_cacheado(conn: sqlite3.Connection) -> dict:
    """Lee el último estado conocido sin invocar al Programador de tareas."""
    valor = db.ajuste(conn, "tarea_windows", "desconocida")
    return {
        "disponible": sys.platform == "win32",
        "registrada": valor == "registrada",
        "detalle": f"último control: {valor}",
        "consultado": False,
    }


def debe_correr(conn: sqlite3.Connection, ahora: datetime | None = None) -> bool:
    return proxima(conn, ahora) <= (ahora or datetime.now(timezone.utc))


def corresponde_corrida(conn: sqlite3.Connection, ahora: datetime | None = None) -> bool:
    """Decisión completa del ciclo interno: activado por el usuario y vencido."""
    if db.ajuste(conn, "corrida_automatica", "0") != "1":
        return False
    return debe_correr(conn, ahora)


class HiloProgramado(threading.Thread):
    """Despierta cada `pausa` segundos y lanza la corrida cuando corresponde."""

    def __init__(self, pausa: int = 60) -> None:
        super().__init__(daemon=True, name="buscador-programado")
        self.pausa = pausa
        self._detener = threading.Event()
        self.ultimo_resultado: dict | None = None
        self.ultimo_error: str | None = None

    def detener(self) -> None:
        self._detener.set()

    def run(self) -> None:  # pragma: no cover - se ejercita con el servidor real
        from . import worker

        while not self._detener.is_set():
            try:
                conn = db.conectar(config.rutas().db)
                try:
                    corresponde = corresponde_corrida(conn)
                finally:
                    conn.close()
                if corresponde:
                    self.ultimo_resultado = worker.correr(causa="automatica")
                    logs.registrar("corrida_automatica", resultado=self.ultimo_resultado.get("estado"))
            except Exception as exc:  # noqa: BLE001 - el hilo no debe morir
                self.ultimo_error = repr(exc)
                logs.registrar("corrida_automatica_error", error=repr(exc))
            self._detener.wait(self.pausa)


# --- Programador de tareas de Windows -------------------------------------

def _schtasks() -> str | None:
    if sys.platform != "win32":
        return None
    for base in (os.environ.get("SystemRoot", r"C:\Windows"),):
        candidato = Path(base) / "System32" / "schtasks.exe"
        if candidato.exists():
            return str(candidato)
    return "schtasks"


def _script_automatico() -> Path:
    return Path(__file__).resolve().parent.parent / "buscar-automatico.cmd"


def estado_windows() -> dict:
    ejecutable = _schtasks()
    if ejecutable is None:
        return {"disponible": False, "motivo": "sólo Windows"}
    try:
        proceso = subprocess.run(
            [ejecutable, "/Query", "/TN", NOMBRE_TAREA],
            capture_output=True, text=True, timeout=20, check=False,
        )
        return {
            "disponible": True,
            "registrada": proceso.returncode == 0,
            "detalle": (proceso.stdout or proceso.stderr or "").strip()[:400],
            "consultado": True,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"disponible": True, "registrada": False, "detalle": repr(exc), "consultado": True}


def activar_windows(intervalo: int | None = None) -> dict:
    """Registra (o reemplaza) la tarea. Requiere permiso del usuario."""
    ejecutable = _schtasks()
    if ejecutable is None:
        return {"ok": False, "motivo": "el Programador de tareas sólo existe en Windows"}
    script = _script_automatico()
    if not script.exists():
        return {"ok": False, "motivo": f"falta el lanzador {script.name}"}
    horas = intervalo or config.INTERVALO_HORAS
    comando = f'"{script}"'
    try:
        proceso = subprocess.run(
            [ejecutable, "/Create", "/TN", NOMBRE_TAREA, "/TR", comando,
             "/SC", "HOURLY", "/MO", str(horas), "/RL", "LIMITED", "/F"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "comando": comando, "intervalo_horas": horas,
                "motivo": f"no se pudo ejecutar el Programador de tareas: {exc}"}
    return {
        "ok": proceso.returncode == 0,
        "comando": comando,
        "intervalo_horas": horas,
        "detalle": (proceso.stdout or proceso.stderr or "").strip()[:400],
    }


def desactivar_windows() -> dict:
    ejecutable = _schtasks()
    if ejecutable is None:
        return {"ok": False, "motivo": "sólo Windows"}
    try:
        proceso = subprocess.run(
            [ejecutable, "/Delete", "/TN", NOMBRE_TAREA, "/F"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "motivo": f"no se pudo ejecutar el Programador de tareas: {exc}"}
    return {"ok": proceso.returncode == 0,
            "detalle": (proceso.stdout or proceso.stderr or "").strip()[:400]}


def esperar_turno(conn: sqlite3.Connection, ahora: datetime | None = None) -> float:
    """Segundos hasta la próxima corrida; 0 si ya corresponde."""
    delta = (proxima(conn, ahora) - (ahora or datetime.now(timezone.utc))).total_seconds()
    return max(0.0, delta)


def dormir_hasta_turno(conn: sqlite3.Connection, maximo: int = 3600) -> float:
    """Espera acotada, útil para un proceso de consola que corre de forma continua."""
    segundos = min(esperar_turno(conn), maximo)
    if segundos > 0:
        time.sleep(segundos)
    return segundos
