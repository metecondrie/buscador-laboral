"""Adaptador F11: Remotive (API JSON pública de avisos remotos)."""

from __future__ import annotations

from .. import fetch
from ..textutil import fecha_iso, html_a_texto, url_canonica
from .base import Adaptador, Observacion, ResultadoFuente, estado_desde_error
from .comun import salario_texto

API = "https://remotive.com/api/remote-jobs"
DOMINIOS = ("remotive.com",)


class Remotive(Adaptador):
    source_id = "F11"
    publisher_key = "remotive"
    nombre = "Remotive"
    url_base = "https://remotive.com"
    endpoint = API
    metodo = "api-json"
    autorizacion = "API pública; la fuente documenta límites de uso razonable"
    atribucion = "Enlace al aviso original en Remotive"
    cuota = "la API devuelve un listado corto; una solicitud por corrida"
    # F04: verificado el 2026-11-10 — `?category=Customer Support` devuelve
    # categorías mezcladas (Software Development, Writing, Marketing...). El
    # parámetro se acepta y se ignora, así que no se particiona por categoría:
    # sería tráfico redundante sobre el mismo feed.
    frecuencia = "feed mutable; los filtros por categoría no alteran el resultado"
    parser_version = "remotive-1.0.0"
    dominios = DOMINIOS

    def fetch(self, limite: int, cursor: str | None = None,
              particion=None) -> ResultadoFuente:
        try:
            datos, respuesta = fetch.descargar_json(API, DOMINIOS)
        except fetch.ErrorFuente as exc:
            return estado_desde_error(exc, self.source_id)

        if not isinstance(datos, dict) or "jobs" not in datos:
            return ResultadoFuente(
                source_id=self.source_id, estado="schema_changed",
                http_status=respuesta.http_status, error_code="schema_changed",
                error_msg="la respuesta no contiene la clave 'jobs'",
            )

        trabajos = datos.get("jobs") or []
        observaciones: list[Observacion] = []
        for trabajo in trabajos:
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
            detalle={
                "job_count": datos.get("job-count"),
                "devueltos": len(trabajos),
                "tomados": len(observaciones),
            },
        )

    def _normalizar(self, trabajo: dict) -> Observacion | None:
        if not isinstance(trabajo, dict):
            return None
        identificador = trabajo.get("id")
        titulo = (trabajo.get("title") or "").strip()
        enlace = trabajo.get("url") or ""
        if identificador in (None, "") or not titulo or not enlace:
            return None

        descripcion = trabajo.get("description") or ""
        region = (trabajo.get("candidate_required_location") or "").strip()
        categoria = (trabajo.get("category") or "").strip()
        etiquetas = trabajo.get("tags") or []
        sal = salario_texto(trabajo.get("salary"))

        return Observacion(
            source_id=self.source_id,
            external_id=str(identificador),
            url=url_canonica(enlace),
            titulo=titulo,
            empresa=(trabajo.get("company_name") or "").strip() or None,
            descripcion_html=descripcion,
            publicado_en=fecha_iso(trabajo.get("publication_date")),
            region=region or None,
            salario=sal,
            seniority=None,
            categoria_fuente=categoria or None,
            skills=", ".join(str(e) for e in etiquetas) or None,
            extra={
                "texto_plano": html_a_texto(descripcion),
                "tipo_contrato": trabajo.get("job_type"),
                "salario_texto": trabajo.get("salary"),
                "categoria": categoria,
            },
            field_status={
                "empresa": "known" if trabajo.get("company_name") else "unknown",
                "region": "known" if region else "unknown",
                "salario": "known" if sal else "unknown",
                "publicado_en": "known" if trabajo.get("publication_date") else "unknown",
                "seniority": "unknown",
            },
            evidencia=[
                {"campo": "region", "texto": region, "ubicacion": "jobs[].candidate_required_location"},
                {"campo": "salario", "texto": trabajo.get("salary"), "ubicacion": "jobs[].salary"},
            ]
            if region or trabajo.get("salary")
            else [],
        )
