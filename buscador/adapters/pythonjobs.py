"""Adaptador F09: Python.org Jobs (feed RSS del listado oficial)."""

from __future__ import annotations

import html
import re

from ..textutil import html_a_texto, url_canonica
from . import comun
from .base import Adaptador, Observacion, ResultadoFuente, estado_desde_error

FEED = "https://www.python.org/jobs/feed/rss/"
DOMINIOS = ("python.org",)
_LOCALIDAD = re.compile(r"^([^\n<]{2,80}?)\s*\n")


class PythonOrgJobs(Adaptador):
    source_id = "F09"
    publisher_key = "pythonorg"
    nombre = "Python.org Jobs"
    url_base = "https://www.python.org"
    endpoint = FEED
    metodo = "rss"
    autorizacion = "feed RSS público"
    atribucion = "Enlace a la ficha en Python.org Jobs"
    cuota = "no documentada; una solicitud por corrida"
    frecuencia = "feed de últimos avisos publicados"
    parser_version = "pythonorg-1.0.0"
    dominios = DOMINIOS

    def fetch(self, limite: int, cursor: str | None = None,
              particion=None) -> ResultadoFuente:
        try:
            root, respuesta = comun.descargar_feed(FEED, DOMINIOS)
        except Exception as exc:  # noqa: BLE001
            return estado_desde_error(exc, self.source_id)

        nodos = comun.items(root)
        observaciones: list[Observacion] = []
        for nodo in nodos:
            if len(observaciones) >= limite:
                break
            obs = self._normalizar(nodo)
            if obs is not None:
                observaciones.append(obs)

        return ResultadoFuente(
            source_id=self.source_id,
            estado="success" if observaciones else "empty_valid",
            observaciones=observaciones,
            http_status=respuesta.http_status,
            detalle={"items_en_feed": len(nodos), "tomados": len(observaciones)},
        )

    def _normalizar(self, nodo) -> Observacion | None:
        titulo_crudo = comun.texto(nodo, "title")
        enlace = comun.enlace(nodo)
        if not titulo_crudo or not enlace:
            return None

        empresa, titulo = _partir(titulo_crudo)
        crudo = html.unescape(comun.texto(nodo, "description"))
        region, cuerpo = _separar_localidad(crudo)
        publicado = comun.fecha(nodo)

        return Observacion(
            source_id=self.source_id,
            external_id=comun.guid(nodo, enlace),
            url=url_canonica(enlace),
            titulo=titulo,
            empresa=empresa,
            descripcion_html=cuerpo,
            publicado_en=publicado,
            region=region,
            salario=None,
            seniority=None,
            categoria_fuente=None,
            skills=None,
            extra={"texto_plano": html_a_texto(cuerpo), "titulo_crudo": titulo_crudo},
            field_status={
                "empresa": "known" if empresa else "unknown",
                "region": "known" if region else "unknown",
                "salario": "unknown",
                "publicado_en": "known" if publicado else "unknown",
                "seniority": "unknown",
            },
            evidencia=[{"campo": "region", "texto": region, "ubicacion": "item/description:primera línea"}]
            if region
            else [],
        )


def _partir(titulo: str) -> tuple[str | None, str]:
    """Python.org publica "Puesto, Organización"."""
    if "," in titulo:
        puesto, organizacion = titulo.rsplit(",", 1)
        if puesto.strip() and organizacion.strip():
            return organizacion.strip(), puesto.strip()
    return None, titulo.strip()


def _separar_localidad(crudo: str) -> tuple[str | None, str]:
    """La primera línea del campo description declara la ubicación."""
    coincidencia = _LOCALIDAD.match(crudo)
    if coincidencia:
        return coincidencia.group(1).strip(), crudo[coincidencia.end():].strip()
    return None, crudo
