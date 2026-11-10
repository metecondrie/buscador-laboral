"""Adaptadores para tableros públicos de ATS: Greenhouse, Lever y Ashby.

Son fuentes de **empresa**, no agregadores: cada tablero publica las vacantes de
un empleador. Eso mejora la calidad (el aviso es el original, con su fecha y su
lugar reales) y es lo que permite saber si una empresa contrata en LATAM.

Los tableros se declaran en `ats_boards.json`. Sólo se incluyen los que
respondieron en la verificación del 2026-11-06; los que devolvieron 404 se
retiraron en lugar de dejarlos fallando en cada corrida.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import config, fetch
from ..textutil import fecha_iso, html_a_texto, url_canonica
from .base import Adaptador, Observacion, Particion, ResultadoFuente, estado_desde_error

TABLEROS = Path(__file__).with_name("ats_boards.json")


def cargar_tableros(familia: str) -> list[dict]:
    if not TABLEROS.exists():
        return []
    datos = json.loads(TABLEROS.read_text(encoding="utf-8"))
    return [t for t in datos.get("tableros", []) if t.get("ats") == familia and t.get("activo", True)]


class _BaseATS(Adaptador):
    familia = ""
    dominios: tuple[str, ...] = ()

    @property
    def particiones(self) -> tuple[Particion, ...]:
        """Un tablero es una partición: cada uno es un empleador distinto."""
        return tuple(
            Particion(t["org"], t.get("nombre", t["org"]), {"org": t["org"]})
            for t in cargar_tableros(self.familia)
        )

    def fetch(self, limite: int, cursor: str | None = None,
              particion: Particion | None = None) -> ResultadoFuente:
        org = (particion.params.get("org") if particion else "") or ""
        if not org:
            return ResultadoFuente(source_id=self.source_id, estado="empty_valid",
                                   detalle={"motivo": "tablero sin organización"})
        try:
            # Los tableros de empresa devuelven TODAS las vacantes en una sola
            # respuesta. Una consultora con ~800 puestos supera el límite global
            # de 5 MB y se perdía entera (bluelightconsulting, medido el
            # 2026-11-10). Los ATS son APIs públicas de vacantes: se les da un
            # tope mayor, sin tocar el límite del resto de las fuentes.
            datos, respuesta = fetch.descargar_json(
                self.url_de(org), self.dominios,
                limite_bytes=config.LIMITE_BYTES_RESPUESTA_ATS)
        except fetch.ErrorFuente as exc:
            return estado_desde_error(exc, self.source_id)

        try:
            observaciones = self._normalizar(datos, org)[:limite]
        except (KeyError, TypeError, AttributeError) as exc:
            return ResultadoFuente(
                source_id=self.source_id, estado="schema_changed",
                http_status=respuesta.http_status, error_code="schema_changed",
                error_msg=f"estructura inesperada de {org}: {exc!r}"[:300],
            )
        return ResultadoFuente(
            source_id=self.source_id,
            estado="success" if observaciones else "empty_valid",
            observaciones=observaciones,
            http_status=respuesta.http_status,
            detalle={"org": org, "tomados": len(observaciones)},
        )


class Greenhouse(_BaseATS):
    source_id = "F12"
    publisher_key = "greenhouse"
    nombre = "Greenhouse (tableros de empresa)"
    url_base = "https://boards-api.greenhouse.io"
    endpoint = "https://boards-api.greenhouse.io/v1/boards/{org}/jobs?content=true"
    metodo = "api-json"
    autorizacion = "API pública de tableros; sin clave para lectura"
    atribucion = "Enlace al aviso en el tablero de la empresa"
    cuota = "no documentada; una solicitud por tablero"
    frecuencia = "listado completo por tablero"
    parser_version = "greenhouse-1.0.0"
    familia = "greenhouse"
    dominios = ("greenhouse.io",)

    def url_de(self, org: str) -> str:
        return self.endpoint.format(org=org)

    def _normalizar(self, datos: dict, org: str) -> list[Observacion]:
        salida = []
        for puesto in datos.get("jobs", []):
            titulo = (puesto.get("title") or "").strip()
            enlace = puesto.get("absolute_url") or ""
            identificador = puesto.get("id")
            if not titulo or not enlace or identificador is None:
                continue
            ubicacion = ((puesto.get("location") or {}).get("name") or "").strip()
            contenido = puesto.get("content") or ""
            publicado = fecha_iso(puesto.get("first_published") or puesto.get("updated_at"))
            salida.append(Observacion(
                source_id=self.source_id,
                external_id=f"{org}:{identificador}",
                url=url_canonica(enlace),
                titulo=titulo,
                empresa=(puesto.get("company_name") or org).strip(),
                descripcion_html=contenido,
                publicado_en=publicado,
                region=ubicacion or None,
                extra={"texto_plano": html_a_texto(contenido), "tablero": org,
                       "departamentos": puesto.get("departments")},
                field_status={
                    "empresa": "known",
                    "region": "known" if ubicacion else "unknown",
                    "salario": "unknown",
                    "publicado_en": "known" if publicado else "unknown",
                    "seniority": "unknown",
                },
                evidencia=[{"campo": "region", "texto": ubicacion, "ubicacion": "jobs[].location.name"}]
                if ubicacion else [],
            ))
        return salida


class Lever(_BaseATS):
    source_id = "F13"
    publisher_key = "lever"
    nombre = "Lever (tableros de empresa)"
    url_base = "https://api.lever.co"
    endpoint = "https://api.lever.co/v0/postings/{org}?mode=json"
    metodo = "api-json"
    autorizacion = "API pública de tableros; sin clave para lectura"
    atribucion = "Enlace al aviso en el tablero de la empresa"
    cuota = "no documentada; una solicitud por tablero"
    frecuencia = "listado completo por tablero"
    parser_version = "lever-1.0.0"
    familia = "lever"
    dominios = ("lever.co",)

    def url_de(self, org: str) -> str:
        return self.endpoint.format(org=org)

    def _normalizar(self, datos, org: str) -> list[Observacion]:
        if not isinstance(datos, list):
            raise TypeError("se esperaba una lista de publicaciones")
        salida = []
        for puesto in datos:
            titulo = (puesto.get("text") or "").strip()
            enlace = puesto.get("hostedUrl") or puesto.get("applyUrl") or ""
            identificador = puesto.get("id")
            if not titulo or not enlace or not identificador:
                continue
            categorias = puesto.get("categories") or {}
            ubicacion = (categorias.get("location") or "").strip()
            descripcion = puesto.get("description") or puesto.get("descriptionPlain") or ""
            creado = puesto.get("createdAt")
            publicado = fecha_iso(creado / 1000 if isinstance(creado, (int, float)) else creado)
            salida.append(Observacion(
                source_id=self.source_id,
                external_id=f"{org}:{identificador}",
                url=url_canonica(enlace),
                titulo=titulo,
                empresa=org,
                descripcion_html=descripcion,
                publicado_en=publicado,
                region=ubicacion or None,
                extra={"texto_plano": puesto.get("descriptionPlain") or html_a_texto(descripcion),
                       "tablero": org, "equipo": categorias.get("team"),
                       "tipo_contrato": categorias.get("commitment"),
                       "remoto": puesto.get("workplaceType")},
                field_status={
                    "empresa": "known",
                    "region": "known" if ubicacion else "unknown",
                    "salario": "unknown",
                    "publicado_en": "known" if publicado else "unknown",
                    "seniority": "unknown",
                },
                evidencia=[{"campo": "region", "texto": ubicacion, "ubicacion": "categories.location"}]
                if ubicacion else [],
            ))
        return salida


class Ashby(_BaseATS):
    source_id = "F14"
    publisher_key = "ashby"
    nombre = "Ashby (tableros de empresa)"
    url_base = "https://api.ashbyhq.com"
    endpoint = "https://api.ashbyhq.com/posting-api/job-board/{org}"
    metodo = "api-json"
    autorizacion = "API pública de tableros; sin clave para lectura"
    atribucion = "Enlace al aviso en el tablero de la empresa"
    cuota = "no documentada; una solicitud por tablero"
    frecuencia = "listado completo por tablero"
    parser_version = "ashby-1.0.0"
    familia = "ashby"
    dominios = ("ashbyhq.com",)

    def url_de(self, org: str) -> str:
        return self.endpoint.format(org=org)

    def _normalizar(self, datos: dict, org: str) -> list[Observacion]:
        salida = []
        for puesto in datos.get("jobs", []):
            titulo = (puesto.get("title") or "").strip()
            enlace = puesto.get("jobUrl") or ""
            identificador = puesto.get("id")
            if not titulo or not enlace or not identificador:
                continue
            ubicacion = (puesto.get("location") or "").strip()
            if puesto.get("isRemote") and "remote" not in ubicacion.lower():
                ubicacion = f"{ubicacion} (remote)".strip()
            descripcion = puesto.get("descriptionHtml") or puesto.get("descriptionPlain") or ""
            publicado = fecha_iso(puesto.get("publishedAt"))
            salida.append(Observacion(
                source_id=self.source_id,
                external_id=f"{org}:{identificador}",
                url=url_canonica(enlace),
                titulo=titulo,
                empresa=org,
                descripcion_html=descripcion,
                publicado_en=publicado,
                region=ubicacion or None,
                extra={"texto_plano": puesto.get("descriptionPlain") or html_a_texto(descripcion),
                       "tablero": org, "remoto": bool(puesto.get("isRemote")),
                       "tipo_contrato": puesto.get("employmentType"),
                       "equipo": puesto.get("team")},
                field_status={
                    "empresa": "known",
                    "region": "known" if ubicacion else "unknown",
                    "salario": "unknown",
                    "publicado_en": "known" if publicado else "unknown",
                    "seniority": "unknown",
                },
                evidencia=[{"campo": "region", "texto": ubicacion, "ubicacion": "jobs[].location"}]
                if ubicacion else [],
            ))
        return salida
