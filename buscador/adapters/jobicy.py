"""Adaptador F03: Jobicy (API JSON v2, atribución con enlace directo).

Particiona por industria para que el listado se acerque a las categorías del
perfil; la API rechaza con 400 las industrias que no reconoce.
"""

from __future__ import annotations

from .. import fetch
from ..textutil import fecha_iso, html_a_texto, url_canonica
from .base import Adaptador, Observacion, Particion, ResultadoFuente, estado_desde_error, salario

API = "https://jobicy.com/api/v2/remote-jobs"
DOMINIOS = ("jobicy.com",)


class Jobicy(Adaptador):
    source_id = "F03"
    publisher_key = "jobicy"
    nombre = "Jobicy"
    url_base = "https://jobicy.com"
    endpoint = API
    metodo = "api-json"
    autorizacion = "API pública v2"
    atribucion = "Crédito a Jobicy con enlace directo a la fuente y al aviso"
    cuota = "máximo 50 por solicitud según la API"
    frecuencia = "feed mutable; una solicitud por partición"
    parser_version = "jobicy-1.1.0"
    dominios = DOMINIOS
    # La API acepta `industry`, `tag` y `geo`. Las etiquetas devuelven lotes más
    # cercanos al perfil que el listado general (medido, no supuesto).
    #
    # F04: `geo=latam` está verificado contra el endpoint el 2026-11-10 — la
    # respuesta devuelve `appliedFilters: {"geo": "latam"}` y todos los avisos
    # declaran LATAM en `jobGeo`. Se usa UNA partición geográfica, no una por
    # categoría, para no multiplicar solicitudes sobre el mismo feed.
    particiones = (
        Particion("latam", "LATAM", {"geo": "latam"}),
        Particion("soporte", "Atención al cliente", {"tag": "customer support"}),
        Particion("analista", "Analista", {"tag": "analyst"}),
        Particion("reportes", "Reportes", {"tag": "reporting analyst"}),
        Particion("datos", "Carga de datos", {"tag": "data entry"}),
    )

    def fetch(self, limite: int, cursor: str | None = None,
              particion: Particion | None = None) -> ResultadoFuente:
        from urllib.parse import urlencode

        params = {"count": str(max(1, min(limite, 50)))}
        if particion:
            params.update(particion.params)
        if cursor:
            params["cursor"] = cursor
        url = f"{API}?{urlencode(params)}"
        try:
            datos, respuesta = fetch.descargar_json(url, DOMINIOS)
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
            cursor_nuevo=datos.get("nextCursor") or None,
            detalle={
                "particion": particion.clave if particion else "general",
                "job_count": datos.get("jobCount"),
                "devueltos": len(trabajos),
                "tomados": len(observaciones),
                "has_more": datos.get("hasMore"),
            },
        )

    def _normalizar(self, trabajo: dict) -> Observacion | None:
        if not isinstance(trabajo, dict):
            return None
        titulo = (trabajo.get("jobTitle") or "").strip()
        identificador = trabajo.get("id")
        enlace = trabajo.get("url") or ""
        if not titulo or identificador in (None, "") or not enlace:
            return None

        descripcion = trabajo.get("jobDescription") or trabajo.get("jobExcerpt") or ""
        tipo = trabajo.get("jobType")
        if isinstance(tipo, list):
            tipo = ", ".join(str(t) for t in tipo)
        industria = trabajo.get("jobIndustry")
        if isinstance(industria, list):
            industria = ", ".join(str(i) for i in industria)
        sal = salario(
            trabajo.get("salaryMin"),
            trabajo.get("salaryMax"),
            trabajo.get("salaryCurrency"),
            trabajo.get("salaryPeriod"),
        )
        geo = (trabajo.get("jobGeo") or "").strip()
        nivel = (trabajo.get("jobLevel") or "").strip()

        return Observacion(
            source_id=self.source_id,
            external_id=str(identificador),
            url=url_canonica(enlace),
            titulo=titulo,
            empresa=(trabajo.get("companyName") or "").strip() or None,
            descripcion_html=descripcion,
            publicado_en=fecha_iso(trabajo.get("pubDate")),
            region=geo or None,
            salario=sal,
            seniority=nivel or None,
            categoria_fuente=industria,
            skills=None,
            extra={
                "tipo_contrato": tipo,
                "texto_plano": html_a_texto(descripcion),
                "slug": trabajo.get("jobSlug"),
                "nivel": nivel,
            },
            field_status={
                "empresa": "known" if trabajo.get("companyName") else "unknown",
                "region": "known" if geo else "unknown",
                "salario": "known" if sal else "unknown",
                "publicado_en": "known" if trabajo.get("pubDate") else "unknown",
                "seniority": "known" if nivel else "unknown",
            },
            evidencia=[{"campo": "region", "texto": geo, "ubicacion": "jobs[].jobGeo"}]
            if geo
            else [],
        )
