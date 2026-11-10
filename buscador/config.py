"""Configuración y rutas del prototipo local.

Los datos de la aplicación viven fuera del repositorio, en
%LOCALAPPDATA%\\BuscadorLaboral. La variable BUSCADOR_DATA_DIR permite
redirigir todo a un directorio temporal en las pruebas.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

APP_NOMBRE = "BuscadorLaboral"
VERSION_APP = "0.2.0"
RULES_VERSION = "rules-3.1.0"
AGRUPACION_VERSION = "identidad-1.1.0"

HOST_LOCAL = "127.0.0.1"
PUERTO_PREFERIDO = 8765

# User agent identificable y atribución exigida por las fuentes.
# El contacto es opcional y se define en el entorno: BUSCADOR_CONTACTO.
_CONTACTO = os.environ.get("BUSCADOR_CONTACTO", "").strip()
USER_AGENT = "BuscadorLaboral/0.2 (prototipo local"
if _CONTACTO:
    USER_AGENT += f"; contacto: {_CONTACTO}"
USER_AGENT += ")"

LIMITE_BYTES_RESPUESTA = 5 * 1024 * 1024
TIMEOUT_CONEXION_S = 10
TIMEOUT_LECTURA_S = 30

MAX_OBSERVACIONES_POR_FUENTE = 100
MAX_PAGINAS_POR_FUENTE = 3
CONCURRENCIA_FUENTE = 4

# Periodicidad obligatoria del MVP: dos corridas por día.
INTERVALO_HORAS = 12
RESPALDOS_A_CONSERVAR = 14
DIAS_INCIDENTE_ABIERTO = 7

# --- Calibración de alertas (Fase 1F · S01) --------------------------------
# El puntaje de un aviso que cumple todo lo que declara pero no expresa
# experiencia ni formación no llegaba a 75 con el denominador completo: el techo
# real era 73. El umbral se separa del cálculo para poder calibrarlo sin tocar
# las reglas, y la alerta exige cobertura y confianza además del puntaje.
#
# 65 y no 75: el puntaje se calcula sobre todo el peso aplicable, así que un
# aviso que cumple TODO lo que declara pero no expresa experiencia ni formación
# tiene un techo de 73 si declara el nivel de inglés (25 categoría + 40
# habilidades + 8 idioma) y de 69 si el aviso está en inglés sin declararlo (el
# idioma queda en crédito parcial). Con 75 ninguna de esas ofertas podía alertar
# nunca. El techo no se toca regalando puntos por ausencia de datos: se calibra
# el umbral, y la alerta sigue exigiendo elegibilidad, cobertura y confianza.
UMBRAL_AVISO = 65.0
COBERTURA_MINIMA_AVISO = 0.7

# Ajustes por defecto persistidos en la tabla `settings`.
#
# La cascada arranca con los tres modelos gratuitos soportados. Vive acá como
# texto y no importada de `ai.proveedores` para no crear un ciclo de imports;
# `tests/test_ia_cascada.py` comprueba que coincida con `CASCADA_POR_DEFECTO`.
CASCADA_INICIAL = ("gemini:gemini-3.5-flash-lite,"
                   "gemini:gemini-3.6-flash,"
                   "gemini:gemini-3.8-flash")

AJUSTES_POR_DEFECTO = {
    "intervalo_horas": str(INTERVALO_HORAS),
    "corrida_automatica": "0",
    "resolver_experiencia_por_competencias": "1",
    "notificar_escritorio": "0",
    "ia_habilitada": "0",
    "ia_cascada": CASCADA_INICIAL,
    "ia_proveedores_habilitados": "gemini",
    "ia_presupuesto_usd": "0",
    "ia_autorizo_pago": "0",
    "ia_llamadas_por_corrida": "20",
    "ia_datos_ofertas": "0",
    "ia_cache": "1",
    "ia_reintentos": "2",
    "ia_timeout_s": "45",
    "ia_cuenta_cloudflare": "",
    "ia_analisis_por_corrida": "25",
    "ia_credencial_activa": "",
    "umbral_aviso": str(int(UMBRAL_AVISO)),
}


def data_root() -> Path:
    """Raíz de datos personales. Nunca dentro del repositorio."""
    override = os.environ.get("BUSCADOR_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        local = str(Path.home() / "AppData" / "Local")
    return Path(local) / APP_NOMBRE


@dataclass(frozen=True)
class Rutas:
    raiz: Path
    data: Path
    documents: Path
    logs: Path
    cache: Path
    backups: Path
    exports: Path

    @property
    def db(self) -> Path:
        return self.data / "buscador.db"

    @property
    def perfil(self) -> Path:
        return self.data / "perfil.json"

    @property
    def perfil_local(self) -> Path:
        """Semilla del perfil real: fuera del repositorio, excluida de Git."""
        return self.data / "perfil.local.json"

    @property
    def log(self) -> Path:
        return self.logs / "buscador.log"

    @property
    def lock(self) -> Path:
        return self.data / "trabajador.lock"


def rutas(root: Path | None = None) -> Rutas:
    base = Path(root) if root is not None else data_root()
    return Rutas(
        raiz=base,
        data=base / "data",
        documents=base / "documents",
        logs=base / "logs",
        cache=base / "cache",
        backups=base / "backups",
        exports=base / "exports",
    )


def crear_estructura(root: Path | None = None) -> Rutas:
    r = rutas(root)
    for carpeta in (r.raiz, r.data, r.documents, r.logs, r.cache, r.backups, r.exports):
        carpeta.mkdir(parents=True, exist_ok=True)
    return r


def ahora_utc() -> str:
    """Instante UTC en ISO 8601 con sufijo Z, precisión de segundos."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def a_utc(valor: datetime) -> str:
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
