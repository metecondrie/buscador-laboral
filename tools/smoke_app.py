"""Aplicación mínima para la prueba de arranque de T01.

No es la interfaz del producto ni el motor de búsqueda: solo comprueba
que FastAPI arranca, responde en loopback y se puede cerrar de forma
ordenada sin dejar procesos ni sockets abiertos.
"""

from __future__ import annotations

import sqlite3
import sys

from fastapi import FastAPI

app = FastAPI(
    title="Buscador laboral - prueba de arranque",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/salud")
def salud() -> dict[str, str]:
    """Devuelve las versiones reales del intérprete en uso."""
    return {
        "estado": "ok",
        "python": sys.version.split()[0],
        "sqlite": sqlite3.sqlite_version,
        "prefijo": sys.prefix,
    }
