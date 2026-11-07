"""Registro local depurado: IDs, conteos y errores; nunca secretos ni contenido completo."""

from __future__ import annotations

import json
from pathlib import Path

from . import config


def registrar(evento: str, **campos) -> None:
    ruta: Path = config.crear_estructura().log
    linea = {"ts": config.ahora_utc(), "evento": evento, **campos}
    with ruta.open("a", encoding="utf-8") as archivo:
        archivo.write(json.dumps(linea, ensure_ascii=False) + "\n")
