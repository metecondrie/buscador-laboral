"""Prueba de arranque de T01: Uvicorn en 127.0.0.1, consulta y cierre.

Arranca la aplicación en un hilo, espera a que el servidor esté listo,
consulta /salud por HTTP, pide el cierre ordenado, espera el hilo y
confirma que el puerto dejó de aceptar conexiones.

Uso:
    .venv\\Scripts\\python.exe tools\\smoke_test.py

Salida: un JSON por stdout. Código 0 si el resultado es "passed".
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn

from smoke_app import app

HOST = "127.0.0.1"
PUERTO_BASE = 8011
ESPERA_ARRANQUE_S = 30
ESPERA_CIERRE_S = 15


def buscar_puerto_libre(desde: int = PUERTO_BASE) -> int:
    for puerto in range(desde, desde + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, puerto))
            except OSError:
                continue
            return puerto
    raise RuntimeError(f"sin puerto libre en {HOST}:{desde}-{desde + 19}")


def puerto_acepta_conexiones(puerto: int, espera: float = 0.3) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(espera)
        return s.connect_ex((HOST, puerto)) == 0


def main() -> int:
    puerto = buscar_puerto_libre()
    config = uvicorn.Config(
        app,
        host=HOST,
        port=puerto,
        log_level="warning",
        access_log=False,
    )
    servidor = uvicorn.Server(config)
    hilo = threading.Thread(target=servidor.run, name="uvicorn-smoke", daemon=True)

    inicio = time.perf_counter()
    hilo.start()

    limite = time.perf_counter() + ESPERA_ARRANQUE_S
    while not servidor.started and time.perf_counter() < limite and hilo.is_alive():
        time.sleep(0.01)

    if not servidor.started:
        print(
            json.dumps(
                {
                    "host": HOST,
                    "puerto": puerto,
                    "resultado": "failed",
                    "motivo": "el servidor no llegó a iniciar",
                    "hilo_vivo": hilo.is_alive(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    arranque_ms = round((time.perf_counter() - inicio) * 1000, 1)
    url = f"http://{HOST}:{puerto}/salud"

    try:
        with urllib.request.urlopen(url, timeout=10) as respuesta:
            estado_http = respuesta.status
            cuerpo = json.load(respuesta)
    except Exception as exc:  # noqa: BLE001 - la prueba debe reportar el fallo, no ocultarlo
        servidor.should_exit = True
        hilo.join(timeout=ESPERA_CIERRE_S)
        print(
            json.dumps(
                {
                    "host": HOST,
                    "puerto": puerto,
                    "url": url,
                    "arranque_ms": arranque_ms,
                    "resultado": "failed",
                    "motivo": f"falló la consulta HTTP: {exc!r}",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    cierre_inicio = time.perf_counter()
    servidor.should_exit = True
    hilo.join(timeout=ESPERA_CIERRE_S)
    cierre_ms = round((time.perf_counter() - cierre_inicio) * 1000, 1)

    hilo_terminado = not hilo.is_alive()
    puerto_cerrado = not puerto_acepta_conexiones(puerto)
    aprobado = (
        estado_http == 200
        and cuerpo.get("estado") == "ok"
        and hilo_terminado
        and puerto_cerrado
    )

    print(
        json.dumps(
            {
                "host": HOST,
                "puerto": puerto,
                "url": url,
                "arranque_ms": arranque_ms,
                "http_status": estado_http,
                "cuerpo": cuerpo,
                "cierre_ordenado": hilo_terminado,
                "cierre_ms": cierre_ms,
                "puerto_cerrado": puerto_cerrado,
                "resultado": "passed" if aprobado else "failed",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if aprobado else 1


if __name__ == "__main__":
    raise SystemExit(main())
