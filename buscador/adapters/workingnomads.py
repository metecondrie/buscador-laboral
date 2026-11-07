"""Adaptador F06: Working Nomads (API JSON pública de avisos remotos)."""

from __future__ import annotations

from .. import fetch
from ..textutil import fecha_iso, html_a_texto, url_canonica
from .base import Adaptador, Observacion, ResultadoFuente, estado_desde_error, salario

API = "https://www.workingnomads.com/api/exposed_jobs/"
DOMINIOS = ("workingnomads.com",)


class WorkingNomads(Adaptador):
    source_id = "F06"
    publisher_key = "workingnomads"
    nombre = "Working Nomads"
    url_base = "https://www.workingnomads.com"
    endpoint = API
    metodo = "api-json"
    autorizacion = "API pública de solo lectura"
    atribucion = "Enlace al aviso en Working Nomads"
    cuota = "no documentada; devuelve el listado vigente completo"
    frecuencia = "feed mutable; listado completo por corrida"
    parser_version = "workingnomads-1.0.0"
    dominios = DOMINIOS

    def fetch(self, limite: int, cursor: str | None = None,
              particion=None) -> ResultadoFuente:
        try:
            datos, respuesta = fetch.descargar_json(API, DOMINIOS)
        except fetch.ErrorFuente as exc:
            return estado_desde_error(exc, self.source_id)

        if not isinstance(datos, list):
            return ResultadoFuente(
                source_id=self.source_id, estado="schema_changed",
                http_status=respuesta.http_status, error_code="schema_changed",
                error_msg="la respuesta no es una lista",
            )

        observaciones: list[Observacion] = []
        for trabajo in datos:
            if len(observaciones) >= limite:
                break
            obs = self._normalizar(trabajo)
            if obs is not None:
                observaciones.append(obs)

        return ResultadoFuente(
            source_id=self.source_id,
            estado="success" if observaciones else "empty_valid",
            observaciones=observaciones,
            http_status=respuesta.http_status,
            detalle={"elementos": len(datos), "tomados": len(observaciones)},
        )

    def _normalizar(self, trabajo: dict) -> Observacion | None:
        if not isinstance(trabajo, dict):
            return None
        titulo = (trabajo.get("title") or "").strip()
        enlace = trabajo.get("url") or ""
        if not titulo or not enlace:
            return None
        descripcion = trabajo.get("description") or ""
        ubicacion = (trabajo.get("location") or "").strip()
        categoria = (trabajo.get("category_name") or "").strip()
        etiquetas = trabajo.get("tags") or ""
        if isinstance(etiquetas, list):
            etiquetas = ", ".join(str(e) for e in etiquetas)
        sal = salario(None, None, None, None)
        texto = html_a_texto(descripcion)

        return Observacion(
            source_id=self.source_id,
            external_id=enlace,
            url=url_canonica(enlace),
            titulo=titulo,
            empresa=(trabajo.get("company_name") or "").strip() or None,
            descripcion_html=descripcion,
            publicado_en=fecha_iso(trabajo.get("pub_date")),
            region=ubicacion or None,
            salario=sal,
            seniority=None,
            categoria_fuente=categoria or None,
            skills=str(etiquetas) or None,
            extra={"texto_plano": texto, "categoria": categoria},
            field_status={
                "empresa": "known" if trabajo.get("company_name") else "unknown",
                "region": "known" if ubicacion else "unknown",
                "salario": "unknown",
                "publicado_en": "known" if trabajo.get("pub_date") else "unknown",
                "seniority": "unknown",
            },
            evidencia=[{"campo": "region", "texto": ubicacion, "ubicacion": "items[].location"}]
            if ubicacion
            else [],
        )
