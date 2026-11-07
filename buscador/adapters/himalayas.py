"""Adaptador F02: Himalayas (API JSON con cursor)."""

from __future__ import annotations

from .. import fetch
from ..textutil import fecha_iso, html_a_texto, url_canonica
from .base import Adaptador, Observacion, ResultadoFuente, estado_desde_error, salario

API = "https://himalayas.app/jobs/api"
DOMINIOS = ("himalayas.app",)


class Himalayas(Adaptador):
    source_id = "F02"
    publisher_key = "himalayas"
    nombre = "Himalayas"
    url_base = "https://himalayas.app"
    endpoint = API
    metodo = "api-json"
    autorizacion = "API pública documentada"
    atribucion = "Enlace de postulación y atribución a Himalayas; retirar anuncios expirados"
    cuota = "no documentada con precisión; una solicitud por corrida"
    frecuencia = "cursor durable; feed incremental"
    parser_version = "himalayas-1.0.0"
    dominios = DOMINIOS

    def fetch(self, limite: int, cursor: str | None = None,
              particion=None) -> ResultadoFuente:
        parametros = f"limit={max(1, min(limite, 100))}"
        if cursor:
            parametros += f"&cursor={cursor}"
        url = f"{API}?{parametros}"
        try:
            datos, respuesta = fetch.descargar_json(url, DOMINIOS)
        except fetch.ErrorFuente as exc:
            return estado_desde_error(exc, self.source_id)

        if not isinstance(datos, dict) or "jobs" not in datos:
            return ResultadoFuente(
                source_id=self.source_id,
                estado="schema_changed",
                http_status=respuesta.http_status,
                error_code="schema_changed",
                error_msg="la respuesta no contiene la clave 'jobs'",
            )

        trabajos = datos.get("jobs") or []
        observaciones: list[Observacion] = []
        for trabajo in trabajos:
            obs = self._normalizar(trabajo)
            if obs is not None:
                observaciones.append(obs)

        estado = "success" if observaciones else "empty_valid"
        return ResultadoFuente(
            source_id=self.source_id,
            estado=estado,
            observaciones=observaciones,
            http_status=respuesta.http_status,
            cursor_nuevo=datos.get("nextCursor") or None,
            detalle={
                "total_count": datos.get("totalCount"),
                "devueltos": len(trabajos),
                "tomados": len(observaciones),
                "cursor_usado": bool(cursor),
            },
        )

    def _normalizar(self, trabajo: dict) -> Observacion | None:
        titulo = (trabajo.get("title") or "").strip()
        guid = trabajo.get("guid") or ""
        enlace = trabajo.get("applicationLink") or guid
        if not titulo or not guid or not enlace:
            return None

        regiones = trabajo.get("locationRestrictions") or []
        region = ", ".join(regiones) if isinstance(regiones, list) else str(regiones)
        seniority = trabajo.get("seniority") or []
        if isinstance(seniority, list):
            seniority = ", ".join(seniority)
        descripcion = trabajo.get("description") or ""
        sal = salario(
            trabajo.get("minSalary"),
            trabajo.get("maxSalary"),
            trabajo.get("currency"),
            trabajo.get("salaryPeriod"),
        )

        campos_presentes = {
            "empresa": bool(trabajo.get("companyName")),
            "region": bool(region),
            "salario": sal is not None,
            "publicado_en": bool(trabajo.get("pubDate")),
            "seniority": bool(seniority),
        }

        return Observacion(
            source_id=self.source_id,
            external_id=guid,
            url=url_canonica(enlace),
            titulo=titulo,
            empresa=(trabajo.get("companyName") or "").strip() or None,
            descripcion_html=descripcion,
            publicado_en=fecha_iso(trabajo.get("pubDate")),
            region=region or None,
            salario=sal,
            seniority=seniority or None,
            categoria_fuente=", ".join(trabajo.get("categories") or []) or None,
            skills=None,
            extra={
                "tipo_contrato": trabajo.get("employmentType"),
                "expira_en": fecha_iso(trabajo.get("expiryDate")),
                "texto_plano": html_a_texto(descripcion),
                "zona_horaria": trabajo.get("timezoneRestrictions"),
            },
            field_status={
                k: ("known" if v else "unknown") for k, v in campos_presentes.items()
            },
            evidencia=[
                {
                    "campo": "region",
                    "texto": region,
                    "ubicacion": "jobs[].locationRestrictions",
                }
            ]
            if region
            else [],
        )
