"""Adaptador F07: NoDesk (feed RSS de avisos remotos)."""

from __future__ import annotations

from ..textutil import html_a_texto, url_canonica
from . import comun
from .base import Adaptador, Observacion, ResultadoFuente, estado_desde_error

FEED = "https://nodesk.co/remote-jobs/index.xml"
DOMINIOS = ("nodesk.co",)


class NoDesk(Adaptador):
    source_id = "F07"
    publisher_key = "nodesk"
    nombre = "NoDesk"
    url_base = "https://nodesk.co"
    endpoint = FEED
    metodo = "rss"
    autorizacion = "feed RSS público"
    atribucion = "Enlace al aviso original en NoDesk"
    cuota = "no documentada; una solicitud por corrida"
    frecuencia = "feed de últimos avisos; ventana corta"
    parser_version = "nodesk-1.0.0"
    dominios = DOMINIOS

    def fetch(self, limite: int, cursor: str | None = None,
              particion=None) -> ResultadoFuente:
        try:
            root, respuesta = comun.descargar_feed(FEED, DOMINIOS)
        except Exception as exc:  # noqa: BLE001 - se tipa como ErrorFuente
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
        empresa, titulo = comun.partir_empresa(titulo_crudo, (" at ", " @ "))
        descripcion = comun.texto(nodo, "description")
        publicado = comun.fecha(nodo)

        return Observacion(
            source_id=self.source_id,
            external_id=comun.guid(nodo, enlace),
            url=url_canonica(enlace),
            titulo=titulo,
            empresa=empresa,
            descripcion_html=descripcion,
            publicado_en=publicado,
            region=None,
            salario=None,
            seniority=None,
            categoria_fuente=None,
            skills=None,
            extra={"texto_plano": html_a_texto(descripcion), "titulo_crudo": titulo_crudo},
            field_status={
                "empresa": "known" if empresa else "unknown",
                "region": "unknown",
                "salario": "unknown",
                "publicado_en": "known" if publicado else "unknown",
                "seniority": "unknown",
            },
        )
