from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def aislar_credenciales(monkeypatch, tmp_path):
    """Ninguna prueba lee, escribe ni borra credenciales reales del sistema.

    Sin esto, un test que esperaba una clave de mentira podía terminar usando la
    credencial real del usuario y, si fallaba, imprimirla en el reporte.
    """
    from buscador.ai import credenciales

    monkeypatch.setattr(credenciales, "_leer_credencial", lambda proveedor: None)
    monkeypatch.setattr(credenciales, "_guardar_credencial", lambda proveedor, clave: False)
    monkeypatch.setattr(credenciales, "_borrar_credencial", lambda proveedor: False)
    monkeypatch.setattr(credenciales, "_ruta_dpapi",
                        lambda proveedor: tmp_path / "credencial-aislada.bin")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def aislar_red(monkeypatch):
    """Ninguna prueba debe salir a internet por accidente.

    Se bloquea en el socket y no en `fetch.descargar` para que las validaciones
    previas de la descarga (dominio no aprobado, esquema, destino privado) sigan
    ejecutándose tal cual: esas pruebas no llegan a conectar.
    """
    import socket

    original = socket.socket.connect
    locales = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}

    def connect(self, address):  # noqa: ANN001
        host = address[0] if isinstance(address, tuple) else ""
        if str(host) not in locales:
            raise OSError(f"prueba sin red: conexión a {host!r} bloqueada")
        return original(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("BUSCADOR_DATA_DIR", str(tmp_path / "datos"))
    from buscador import config, db, ingest

    rutas = config.crear_estructura()
    db.inicializar(rutas.db)
    conn = db.conectar(rutas.db)
    ingest.sembrar_fuentes(conn)
    yield conn
    conn.close()


@pytest.fixture
def perfil_id(entorno):
    from buscador import config, worker

    return worker.asegurar_perfil(entorno, config.crear_estructura())["id"]
