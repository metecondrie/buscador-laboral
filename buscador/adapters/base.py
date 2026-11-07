"""Contrato común de los adaptadores de fuente (sección 5 del plan).

Un adaptador declara metadatos verificables (método, autorización, atribución,
cuota) y devuelve observaciones normalizadas. Puede declarar **particiones**:
consultas del mismo editor orientadas a las categorías del perfil. Particionar
mejora la relevancia; no cuenta como fuente adicional.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Particion:
    """Variante de consulta sobre el mismo editor (por categoría, industria o nivel)."""

    clave: str
    etiqueta: str
    params: dict[str, str] = field(default_factory=dict)

    @property
    def query(self) -> str:
        from urllib.parse import urlencode

        return urlencode(self.params, doseq=True)


@dataclass
class Observacion:
    source_id: str
    external_id: str
    url: str
    titulo: str
    empresa: str | None
    descripcion_html: str
    publicado_en: str | None
    region: str | None = None
    salario: dict[str, Any] | None = None
    seniority: str | None = None
    categoria_fuente: str | None = None
    skills: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    field_status: dict[str, str] = field(default_factory=dict)
    evidencia: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ResultadoFuente:
    source_id: str
    estado: str
    observaciones: list[Observacion] = field(default_factory=list)
    cursor_nuevo: str | None = None
    http_status: int | None = None
    error_code: str | None = None
    error_msg: str | None = None
    detalle: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.estado in {"success", "empty_valid"}


class Adaptador:
    """Base de los adaptadores. Los metadatos son obligatorios y auditables."""

    source_id: str = ""
    publisher_key: str = ""
    nombre: str = ""
    url_base: str = ""
    endpoint: str = ""
    metodo: str = ""
    autorizacion: str = ""
    atribucion: str = ""
    cuota: str = ""
    frecuencia: str = ""
    parser_version: str = ""
    dominios: tuple[str, ...] = ()
    particiones: tuple[Particion, ...] = ()

    def fetch(self, limite: int, cursor: str | None = None,
              particion: Particion | None = None) -> ResultadoFuente:
        raise NotImplementedError


def salario(
    minimo: float | None,
    maximo: float | None,
    moneda: str | None,
    periodo: str | None,
) -> dict[str, Any] | None:
    """Guarda magnitudes homogéneas; nunca convierte bruto/neto ni período."""
    if minimo is None and maximo is None:
        return None
    return {
        "min": minimo,
        "max": maximo,
        "moneda": (moneda or "").upper() or None,
        "periodo": (periodo or "").lower() or None,
        "naturaleza": "desconocido",
        "horas": None,
    }


def estado_desde_error(exc: Exception, source_id: str) -> ResultadoFuente:
    """Traduce un ErrorFuente a un resultado tipado, sin perder el status."""
    codigo = getattr(exc, "codigo", "network_error")
    return ResultadoFuente(
        source_id=source_id,
        estado=codigo,
        http_status=getattr(exc, "http_status", None),
        error_code=codigo,
        error_msg=getattr(exc, "mensaje", str(exc)),
    )
