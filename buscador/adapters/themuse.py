"""Adaptador F05: The Muse (API JSON pública, filtros por categoría, nivel y ubicación)."""

from __future__ import annotations

from .. import fetch
from ..textutil import fecha_iso, html_a_texto, url_canonica
from .base import Adaptador, Observacion, Particion, ResultadoFuente, estado_desde_error

API = "https://www.themuse.com/api/public/jobs"
DOMINIOS = ("themuse.com",)


class TheMuse(Adaptador):
    source_id = "F05"
    publisher_key = "themuse"
    nombre = "The Muse"
    url_base = "https://www.themuse.com"
    endpoint = API
    metodo = "api-json"
    autorizacion = "API pública con paginación; sin clave para lectura"
    atribucion = "Enlace a la ficha original en The Muse"
    cuota = "no documentada; se limita a una página por partición"
    frecuencia = "feed mutable con paginación por número de página"
    parser_version = "themuse-1.0.0"
    dominios = DOMINIOS
    # Particiones orientadas al perfil: analítica de datos y atención al cliente,
    # restringidas a ubicaciones flexibles o remotas cuando la API lo permite.
    particiones = (
        Particion("datos-remoto", "Datos y analítica remoto",
                  {"category": "Data and Analytics", "location": "Flexible / Remote"}),
        Particion("datos-inicial", "Datos y analítica inicial",
                  {"category": "Data and Analytics", "level": "Entry Level"}),
        Particion("soporte-remoto", "Atención al cliente remoto",
                  {"category": "Customer Service", "location": "Flexible / Remote"}),
    )

    def fetch(self, limite: int, cursor: str | None = None,
              particion: Particion | None = None) -> ResultadoFuente:
        params = dict(particion.params) if particion else {}
        params.setdefault("page", cursor or "1")
        from urllib.parse import urlencode

        url = f"{API}?{urlencode(params)}"
        try:
            datos, respuesta = fetch.descargar_json(url, DOMINIOS)
        except fetch.ErrorFuente as exc:
            return estado_desde_error(exc, self.source_id)

        if not isinstance(datos, dict) or "results" not in datos:
            return ResultadoFuente(
                source_id=self.source_id, estado="schema_changed",
                http_status=respuesta.http_status, error_code="schema_changed",
                error_msg="la respuesta no contiene la clave 'results'",
            )

        resultados = datos.get("results") or []
        observaciones: list[Observacion] = []
        for trabajo in resultados:
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
            cursor_nuevo=None,
            detalle={
                "particion": particion.clave if particion else None,
                "devueltos": len(resultados),
                "tomados": len(observaciones),
                "paginas_totales": datos.get("page_count"),
            },
        )

    def _normalizar(self, trabajo: dict) -> Observacion | None:
        identificador = trabajo.get("id")
        titulo = (trabajo.get("name") or "").strip()
        referencias = trabajo.get("refs") or {}
        enlace = referencias.get("landing_page") or ""
        if identificador in (None, "") or not titulo or not enlace:
            return None

        empresa = ((trabajo.get("company") or {}).get("name") or "").strip() or None
        ubicaciones = [u.get("name") for u in (trabajo.get("locations") or []) if u.get("name")]
        niveles = [n.get("name") for n in (trabajo.get("levels") or []) if n.get("name")]
        categorias = [c.get("name") for c in (trabajo.get("categories") or []) if c.get("name")]
        descripcion = trabajo.get("contents") or ""
        region = ", ".join(ubicaciones)

        return Observacion(
            source_id=self.source_id,
            external_id=str(identificador),
            url=url_canonica(enlace),
            titulo=titulo,
            empresa=empresa,
            descripcion_html=descripcion,
            publicado_en=fecha_iso(trabajo.get("publication_date")),
            region=region or None,
            salario=None,
            seniority=", ".join(niveles) or None,
            categoria_fuente=", ".join(categorias) or None,
            skills=None,
            extra={
                "texto_plano": html_a_texto(descripcion),
                "tipo": trabajo.get("type"),
                "short_name": trabajo.get("short_name"),
                "ubicaciones": ubicaciones,
            },
            field_status={
                "empresa": "known" if empresa else "unknown",
                "region": "known" if region else "unknown",
                "salario": "unknown",
                "publicado_en": "known" if trabajo.get("publication_date") else "unknown",
                "seniority": "known" if niveles else "unknown",
            },
            evidencia=[{"campo": "region", "texto": region, "ubicacion": "results[].locations"}]
            if region
            else [],
        )
