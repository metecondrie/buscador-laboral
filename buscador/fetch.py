"""Descarga HTTP acotada: solo HTTPS, dominios aprobados y destinos públicos.

Implementa las fronteras de la sección 12: sin esquemas locales, sin rangos
privados, sin redirecciones fuera del dominio aprobado y con límite de tamaño.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from . import config
from .textutil import es_url_publica

CODIGOS = {
    400: "schema_changed",
    401: "auth_required",
    403: "access_restricted",
    404: "access_restricted",
    410: "access_restricted",
    429: "rate_limited",
}


class ErrorFuente(Exception):
    def __init__(self, codigo: str, mensaje: str, http_status: int | None = None) -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje
        self.http_status = http_status


@dataclass
class Respuesta:
    cuerpo: bytes
    http_status: int
    url_final: str
    content_type: str


def _dominio_permitido(host: str, permitidos: tuple[str, ...]) -> bool:
    host = (host or "").lower()
    return any(host == d or host.endswith("." + d) for d in permitidos)


class _RedireccionSegura(urllib.request.HTTPRedirectHandler):
    def __init__(self, permitidos: tuple[str, ...]) -> None:
        self.permitidos = permitidos
        self.saltos = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        self.saltos += 1
        if self.saltos > 3:
            raise ErrorFuente("network_error", "demasiadas redirecciones")
        host = urlsplit(newurl).hostname or ""
        if not _dominio_permitido(host, self.permitidos):
            raise ErrorFuente("access_restricted", f"redirección fuera del dominio aprobado: {host}")
        publica, motivo = es_url_publica(newurl)
        if not publica:
            raise ErrorFuente("access_restricted", f"redirección rechazada: {motivo}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def descargar(url: str, dominios: tuple[str, ...], aceptar: str = "*/*") -> Respuesta:
    host = urlsplit(url).hostname or ""
    if not _dominio_permitido(host, dominios):
        raise ErrorFuente("access_restricted", f"dominio no aprobado: {host}")
    publica, motivo = es_url_publica(url)
    if not publica:
        raise ErrorFuente("access_restricted", f"destino rechazado: {motivo}")

    peticion = urllib.request.Request(
        url,
        headers={
            "User-Agent": config.USER_AGENT,
            "Accept": aceptar,
            "Accept-Language": "en-US,en;q=0.8,es;q=0.7",
        },
    )
    abridor = urllib.request.build_opener(_RedireccionSegura(dominios))
    try:
        with abridor.open(peticion, timeout=config.TIMEOUT_LECTURA_S) as respuesta:
            cuerpo = respuesta.read(config.LIMITE_BYTES_RESPUESTA + 1)
            if len(cuerpo) > config.LIMITE_BYTES_RESPUESTA:
                raise ErrorFuente(
                    "partial",
                    f"respuesta mayor a {config.LIMITE_BYTES_RESPUESTA} bytes; se descarta",
                    respuesta.status,
                )
            return Respuesta(
                cuerpo=cuerpo,
                http_status=respuesta.status,
                url_final=respuesta.geturl(),
                content_type=respuesta.headers.get("Content-Type", ""),
            )
    except ErrorFuente:
        raise
    except urllib.error.HTTPError as exc:
        codigo = CODIGOS.get(exc.code, "network_error")
        raise ErrorFuente(codigo, f"HTTP {exc.code}", exc.code) from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
        raise ErrorFuente("network_error", f"fallo de red: {exc}") from exc


def descargar_json(url: str, dominios: tuple[str, ...]) -> tuple[Any, Respuesta]:
    respuesta = descargar(url, dominios, aceptar="application/json")
    try:
        return json.loads(respuesta.cuerpo.decode("utf-8")), respuesta
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ErrorFuente("schema_changed", f"JSON inválido: {exc}", respuesta.http_status) from exc


def descargar_xml(url: str, dominios: tuple[str, ...]) -> tuple[bytes, Respuesta]:
    return descargar(url, dominios, aceptar="application/rss+xml, application/xml;q=0.9")
