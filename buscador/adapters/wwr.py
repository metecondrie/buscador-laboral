"""Adaptador F01: We Work Remotely (RSS público, atribución requerida).

Usa particiones por categoría del sitio para acercar el listado a las
categorías del perfil, en lugar de depender sólo del feed general.
"""

from __future__ import annotations

from ..textutil import html_a_texto, url_canonica
from . import comun
from .base import Adaptador, Observacion, Particion, ResultadoFuente, estado_desde_error

RSS = "https://weworkremotely.com/remote-jobs.rss"
DOMINIOS = ("weworkremotely.com",)
CATEGORIAS = "https://weworkremotely.com/categories/{}.rss"


class WeWorkRemotely(Adaptador):
    source_id = "F01"
    publisher_key = "weworkremotely"
    nombre = "We Work Remotely"
    url_base = "https://weworkremotely.com"
    endpoint = RSS
    metodo = "rss"
    autorizacion = "feed RSS público"
    atribucion = "Enlace al aviso original en We Work Remotely; no se usa su logo"
    cuota = "sin cuota documentada; una solicitud por partición y corrida"
    frecuencia = "feed mutable; reconsultar con solapamiento"
    parser_version = "wwr-1.1.0"
    dominios = DOMINIOS
    particiones = (
        Particion("general", "Feed general", {"url": RSS}),
        Particion("soporte", "Atención al cliente",
                  {"url": CATEGORIAS.format("remote-customer-support-jobs")}),
        Particion("negocio", "Gestión y finanzas",
                  {"url": CATEGORIAS.format("remote-management-and-finance-jobs")}),
    )

    def fetch(self, limite: int, cursor: str | None = None,
              particion: Particion | None = None) -> ResultadoFuente:
        url = (particion.params.get("url") if particion else None) or RSS
        try:
            root, respuesta = comun.descargar_feed(url, DOMINIOS)
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
            cursor_nuevo=comun.fecha(canal_build(root)),
            detalle={
                "particion": particion.clave if particion else "general",
                "items_en_feed": len(nodos),
                "tomados": len(observaciones),
            },
        )

    def _normalizar(self, item) -> Observacion | None:
        titulo_crudo = comun.texto(item, "title")
        enlace = comun.enlace(item)
        if not titulo_crudo or not enlace:
            return None
        empresa, titulo = _partir_titulo(titulo_crudo)
        region = comun.texto(item, "region") or None
        skills = comun.texto(item, "skills") or None
        descripcion = comun.texto(item, "description")
        publicado = comun.fecha(item)

        return Observacion(
            source_id=self.source_id,
            external_id=comun.guid(item, enlace),
            url=url_canonica(enlace),
            titulo=titulo,
            empresa=empresa,
            descripcion_html=descripcion,
            publicado_en=publicado,
            region=region,
            salario=None,
            seniority=None,
            categoria_fuente=comun.texto(item, "category") or None,
            skills=skills,
            extra={
                "tipo_contrato": comun.texto(item, "type") or None,
                "texto_plano": html_a_texto(descripcion),
                "titulo_crudo": titulo_crudo,
            },
            field_status={
                "empresa": "known" if empresa else "unknown",
                "region": "known" if region else "unknown",
                "salario": "unknown",
                "publicado_en": "known" if publicado else "unknown",
                "seniority": "unknown",
            },
            evidencia=[{"campo": "region", "texto": region, "ubicacion": "item/region"}]
            if region
            else [],
        )


def canal_build(root):
    nodo = root.find("channel")
    return nodo if nodo is not None else root


def _partir_titulo(valor: str) -> tuple[str | None, str]:
    """WWR publica "Empresa: Puesto"; no inventar empresa cuando no hay prefijo."""
    if ": " in valor:
        empresa, titulo = valor.split(": ", 1)
        if empresa and titulo:
            return empresa.strip(), titulo.strip()
    return None, valor.strip()
