"""Adaptador F04: Remote OK (API JSON pública con atribución obligatoria)."""

from __future__ import annotations

from .. import fetch
from ..textutil import fecha_iso, html_a_texto, url_canonica
from .base import Adaptador, Observacion, ResultadoFuente, estado_desde_error, salario

API = "https://remoteok.com/api"
DOMINIOS = ("remoteok.com",)


class RemoteOK(Adaptador):
    source_id = "F04"
    publisher_key = "remoteok"
    nombre = "Remote OK"
    url_base = "https://remoteok.com"
    endpoint = API
    metodo = "api-json"
    autorizacion = "API pública; sus términos exigen enlace de vuelta y mención de Remote OK"
    atribucion = "Enlace con seguimiento a Remote OK y al aviso original; sin su logotipo"
    cuota = "no documentada; una solicitud por corrida devuelve el listado completo"
    frecuencia = "feed mutable; la respuesta completa se reemplaza con frecuencia"
    parser_version = "remoteok-1.0.0"
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
        descartados = 0
        for trabajo in datos:
            if len(observaciones) >= limite:
                break
            obs = self._normalizar(trabajo)
            if obs is None:
                descartados += 1
                continue
            observaciones.append(obs)

        return ResultadoFuente(
            source_id=self.source_id,
            estado="success" if observaciones else "empty_valid",
            observaciones=observaciones,
            http_status=respuesta.http_status,
            detalle={
                "elementos": len(datos),
                "tomados": len(observaciones),
                "sin_campos": descartados,
                "nota": "el primer elemento del listado es un aviso legal sin datos de puesto",
            },
        )

    def _normalizar(self, trabajo: dict) -> Observacion | None:
        if not isinstance(trabajo, dict):
            return None
        identificador = trabajo.get("id")
        titulo = (trabajo.get("position") or trabajo.get("title") or "").strip()
        enlace = trabajo.get("url") or trabajo.get("apply_url") or ""
        if identificador in (None, "", 0) or not titulo or not enlace:
            return None

        descripcion = trabajo.get("description") or ""
        etiquetas = trabajo.get("tags") or []
        if isinstance(etiquetas, str):
            etiquetas = [e.strip() for e in etiquetas.split(",") if e.strip()]
        ubicacion = (trabajo.get("location") or "").strip()

        minimo = _numero(trabajo.get("salary_min"))
        maximo = _numero(trabajo.get("salary_max"))
        sal = salario(minimo, maximo, "USD", "year") if (minimo or maximo) else None

        return Observacion(
            source_id=self.source_id,
            external_id=str(identificador),
            url=url_canonica(enlace),
            titulo=titulo,
            empresa=(trabajo.get("company") or "").strip() or None,
            descripcion_html=descripcion,
            publicado_en=fecha_iso(trabajo.get("date") or trabajo.get("epoch")),
            region=ubicacion or None,
            salario=sal,
            seniority=None,
            categoria_fuente=None,
            skills=", ".join(str(e) for e in etiquetas) or None,
            extra={
                "texto_plano": html_a_texto(descripcion),
                "slug": trabajo.get("slug"),
                "aplicar_en": trabajo.get("apply_url"),
                "etiquetas": [str(e) for e in etiquetas][:40],
            },
            field_status={
                "empresa": "known" if trabajo.get("company") else "unknown",
                "region": "known" if ubicacion else "unknown",
                "salario": "known" if sal else "unknown",
                "publicado_en": "known" if trabajo.get("date") or trabajo.get("epoch") else "unknown",
                "seniority": "unknown",
            },
            evidencia=[{"campo": "region", "texto": ubicacion, "ubicacion": "items[].location"}]
            if ubicacion
            else [],
        )


def _numero(valor) -> float | None:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero > 0 else None
