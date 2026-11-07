"""Adaptador F08: Jobspresso (feed RSS de avisos remotos)."""

from __future__ import annotations

import re

from ..textutil import html_a_texto, url_canonica
from . import comun
from .base import Adaptador, Observacion, ResultadoFuente, estado_desde_error

FEED = "https://jobspresso.co/feed/?post_type=job_listing"
DOMINIOS = ("jobspresso.co",)
_RESTOS = re.compile(r"The post .*? appeared first on .*?\.?\s*$", re.DOTALL)


class Jobspresso(Adaptador):
    source_id = "F08"
    publisher_key = "jobspresso"
    nombre = "Jobspresso"
    url_base = "https://jobspresso.co"
    endpoint = FEED
    metodo = "rss"
    autorizacion = "feed RSS público"
    atribucion = "Enlace al aviso original en Jobspresso"
    cuota = "no documentada; una solicitud por corrida"
    frecuencia = "feed de últimos avisos"
    parser_version = "jobspresso-1.0.0"
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

        empresa, region = _autor(nodo)
        titulo = _limpiar_titulo(titulo_crudo)
        # content:encoded trae el aviso completo; description viene recortada.
        descripcion = comun.texto(nodo, "content:encoded", comun.NS) or comun.texto(nodo, "description")
        descripcion = _RESTOS.sub("", descripcion).strip()
        publicado = comun.fecha(nodo)

        return Observacion(
            source_id=self.source_id,
            external_id=comun.guid(nodo, enlace),
            url=url_canonica(enlace),
            titulo=titulo,
            empresa=empresa,
            descripcion_html=descripcion,
            publicado_en=publicado,
            region=region,
            salario=None,
            seniority=None,
            categoria_fuente=None,
            skills=None,
            extra={"texto_plano": html_a_texto(descripcion), "titulo_crudo": titulo_crudo},
            field_status={
                "empresa": "known" if empresa else "unknown",
                "region": "known" if region else "unknown",
                "salario": "unknown",
                "publicado_en": "known" if publicado else "unknown",
                "seniority": "unknown",
            },
            evidencia=[{"campo": "region", "texto": region, "ubicacion": "item/dc:creator"}]
            if region
            else [],
        )


def _autor(nodo) -> tuple[str | None, str | None]:
    """`dc:creator` publica "Empresa<br>⚲ Ubicación" en el mismo campo."""
    crudo = comun.texto(nodo, "dc:creator", comun.NS)
    if not crudo:
        return None, None
    partes = re.split(r"<br\s*/?>", crudo, maxsplit=1)
    empresa = re.sub(r"<[^>]+>", "", partes[0]).replace("&nbsp;", " ").strip() or None
    region = None
    if len(partes) > 1:
        region = re.sub(r"<[^>]+>", "", partes[1]).replace("&nbsp;", " ").strip(" ⚲ \u2699,") or None
    return empresa, region


def _limpiar_titulo(valor: str) -> str:
    return re.sub(r"\s+", " ", valor.replace("\u2013", "-")).strip()
