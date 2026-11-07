"""Adaptador F10: Arbeitnow (API JSON pública con paginación por página)."""

from __future__ import annotations

import html

from .. import fetch
from ..textutil import fecha_iso, html_a_texto, url_canonica
from .base import Adaptador, Observacion, ResultadoFuente, estado_desde_error

API = "https://www.arbeitnow.com/api/job-board-api"
DOMINIOS = ("arbeitnow.com",)


class Arbeitnow(Adaptador):
    source_id = "F10"
    publisher_key = "arbeitnow"
    nombre = "Arbeitnow"
    url_base = "https://www.arbeitnow.com"
    endpoint = API
    metodo = "api-json"
    autorizacion = "API pública gratuita; los términos piden enlace de vuelta y uso moderado"
    atribucion = "Enlace al aviso en Arbeitnow"
    cuota = "300 elementos por página; una página por corrida"
    frecuencia = "actualización horaria; paginación por número de página"
    parser_version = "arbeitnow-1.0.0"
    dominios = DOMINIOS

    def fetch(self, limite: int, cursor: str | None = None,
              particion=None) -> ResultadoFuente:
        pagina = cursor or "1"
        url = f"{API}?page={pagina}"
        try:
            datos, respuesta = fetch.descargar_json(url, DOMINIOS)
        except fetch.ErrorFuente as exc:
            return estado_desde_error(exc, self.source_id)

        if not isinstance(datos, dict) or "data" not in datos:
            return ResultadoFuente(
                source_id=self.source_id, estado="schema_changed",
                http_status=respuesta.http_status, error_code="schema_changed",
                error_msg="la respuesta no contiene la clave 'data'",
            )

        elementos = datos.get("data") or []
        observaciones: list[Observacion] = []
        for trabajo in elementos:
            if len(observaciones) >= limite:
                break
            obs = self._normalizar(trabajo)
            if obs is not None:
                observaciones.append(obs)

        siguiente = (datos.get("links") or {}).get("next")
        return ResultadoFuente(
            source_id=self.source_id,
            estado="success" if observaciones else "empty_valid",
            observaciones=observaciones,
            http_status=respuesta.http_status,
            cursor_nuevo=str(int(pagina) + 1) if siguiente else None,
            detalle={
                "pagina": pagina,
                "devueltos": len(elementos),
                "tomados": len(observaciones),
                "con_remoto": sum(1 for t in elementos if t.get("remote")),
            },
        )

    def _normalizar(self, trabajo: dict) -> Observacion | None:
        if not isinstance(trabajo, dict):
            return None
        titulo = (trabajo.get("title") or "").strip()
        slug = (trabajo.get("slug") or "").strip()
        enlace = trabajo.get("url") or ""
        if not titulo or not enlace:
            return None

        # `description` llega con entidades escapadas dos veces.
        descripcion = html.unescape(trabajo.get("description") or "")
        ubicacion = (trabajo.get("location") or "").strip()
        remoto = bool(trabajo.get("remote"))
        if remoto and "remote" not in ubicacion.lower():
            ubicacion = f"{ubicacion} (remote)".strip() if ubicacion else "Remote"
        tipos = trabajo.get("job_types") or []
        etiquetas = trabajo.get("tags") or []

        return Observacion(
            source_id=self.source_id,
            external_id=slug or enlace,
            url=url_canonica(enlace),
            titulo=titulo,
            empresa=(trabajo.get("company_name") or "").strip() or None,
            descripcion_html=descripcion,
            publicado_en=fecha_iso(trabajo.get("created_at")),
            region=ubicacion or None,
            salario=None,
            seniority=None,
            categoria_fuente=", ".join(str(t) for t in tipos) or None,
            skills=", ".join(str(e) for e in etiquetas) or None,
            extra={
                "texto_plano": html_a_texto(descripcion),
                "remoto": remoto,
                "tipos": tipos,
                "etiquetas": etiquetas,
            },
            field_status={
                "empresa": "known" if trabajo.get("company_name") else "unknown",
                "region": "known" if ubicacion else "unknown",
                "salario": "unknown",
                "publicado_en": "known" if trabajo.get("created_at") else "unknown",
                "seniority": "unknown",
            },
            evidencia=[{"campo": "region", "texto": ubicacion, "ubicacion": "data[].location"}]
            if ubicacion
            else [],
        )
