"""Utilidades compartidas por los adaptadores.

Concentra el parseo de RSS, la partición de títulos y la lectura de salarios
publicados como texto libre. Ninguna función inventa datos ausentes: si el
campo no está, queda en `None` y el `field_status` lo declara `unknown`.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from typing import Any

from .. import fetch
from ..textutil import fecha_iso

NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "atom": "http://www.w3.org/2005/Atom",
}

# Muchos feeds usan entidades HTML (&rsquo;, &nbsp;) que no existen en XML.
_ENTIDAD_DESCONOCIDA = re.compile(
    r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)[a-zA-Z][a-zA-Z0-9]{1,31};"
)


def _reparar_entidades(cuerpo: bytes) -> bytes:
    """Convierte entidades HTML en caracteres literales sin tocar las de XML."""
    texto = cuerpo.decode("utf-8", errors="replace")
    return _ENTIDAD_DESCONOCIDA.sub(lambda m: html.unescape(m.group(0)), texto).encode("utf-8")


def descargar_feed(url: str, dominios: tuple[str, ...]) -> tuple[ET.Element, fetch.Respuesta]:
    """Descarga un feed y devuelve la raíz XML. Lanza ErrorFuente si no es XML."""
    respuesta = fetch.descargar(url, dominios, aceptar="application/rss+xml, application/xml;q=0.9")
    try:
        return ET.fromstring(respuesta.cuerpo), respuesta
    except ET.ParseError as primero:
        try:
            return ET.fromstring(_reparar_entidades(respuesta.cuerpo)), respuesta
        except ET.ParseError:
            raise fetch.ErrorFuente("schema_changed", f"XML inválido: {primero}",
                                    respuesta.http_status) from primero


def canal(root: ET.Element) -> ET.Element:
    return root.find("channel") if root.find("channel") is not None else root


def items(root: ET.Element) -> list[ET.Element]:
    nodo = canal(root)
    encontrados = nodo.findall("item")
    if encontrados:
        return encontrados
    return nodo.findall("atom:entry", NS)


def texto(nodo: ET.Element | None, etiqueta: str, ns: dict[str, str] | None = None) -> str:
    if nodo is None:
        return ""
    hijo = nodo.find(etiqueta, ns or {})
    if hijo is None or hijo.text is None:
        return ""
    return hijo.text.strip()


def enlace(nodo: ET.Element) -> str:
    """RSS usa <link>texto</link>; Atom usa <link href="..."/>."""
    valor = texto(nodo, "link")
    if valor:
        return valor
    hijo = nodo.find("atom:link", NS)
    if hijo is not None:
        return (hijo.get("href") or "").strip()
    return ""


def guid(nodo: ET.Element, alternativo: str) -> str:
    valor = texto(nodo, "guid") or texto(nodo, "atom:id", NS)
    return valor or alternativo


def fecha(nodo: ET.Element) -> str | None:
    for etiqueta in ("pubDate", "published", "updated", "atom:updated"):
        valor = texto(nodo, etiqueta, NS)
        if valor:
            convertida = fecha_iso(valor)
            if convertida:
                return convertida
    return None


def partir_empresa(titulo: str, separadores: tuple[str, ...] = (" at ", " @ ", ": ")) -> tuple[str | None, str]:
    """Devuelve (empresa, título). No inventa empresa cuando no hay prefijo."""
    for separador in separadores:
        if separador in titulo:
            izquierda, derecha = titulo.split(separador, 1)
            izquierda, derecha = izquierda.strip(), derecha.strip()
            if not izquierda or not derecha:
                continue
            if separador in {" at ", " @ "}:
                return derecha, izquierda
            return izquierda, derecha
    return None, titulo.strip()


_MONEDAS = {
    "$": "USD", "us$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR",
    "£": "GBP", "gbp": "GBP", "ars": "ARS", "r$": "BRL", "brl": "BRL",
}
_PERIODOS = (
    ("hour", "hour"), ("hr", "hour"), ("hora", "hour"),
    ("month", "month"), ("mes", "month"),
    ("year", "year"), ("annual", "year"), ("año", "year"),
    ("day", "day"), ("dia", "day"),
)
_NUMERO = re.compile(r"(\d[\d.,]*)\s*([kK])?")
_MILES_PUNTO = re.compile(r"^\d{1,3}(?:\.\d{3})+$")


def _normalizar_monto(crudo: str) -> float | None:
    """Convierte 70,000 · 2.500 · 1.200.000 sin cambiar el orden de magnitud."""
    limpio = crudo.strip()
    if _MILES_PUNTO.match(limpio):
        limpio = limpio.replace(".", "")
    limpio = limpio.replace(",", "")
    try:
        return float(limpio)
    except ValueError:
        return None


def salario_texto(valor: str | None) -> dict[str, Any] | None:
    """Lee un salario publicado como texto libre. No convierte período ni moneda."""
    if not valor:
        return None
    base = valor.strip().lower()
    if not base or base in {"competitive", "negotiable", "doe", "tbd", "n/a"}:
        return None

    moneda = None
    for simbolo, codigo in _MONEDAS.items():
        if simbolo in base:
            moneda = codigo
            break

    periodo = None
    for pista, normalizado in _PERIODOS:
        if re.search(rf"\b{pista}\b", base):
            periodo = normalizado
            break

    montos: list[float] = []
    for crudo, miles in _NUMERO.findall(base):
        numero = _normalizar_monto(crudo)
        if numero is None:
            continue
        if miles:
            numero *= 1000
        if 0 < numero <= 10_000_000:
            montos.append(numero)

    if not montos:
        return None
    montos.sort()
    if len(montos) == 1:
        return _salario(montos[0], None, moneda, periodo)
    return _salario(montos[0], montos[-1], moneda, periodo)


def _salario(minimo: float, maximo: float | None, moneda: str | None,
             periodo: str | None) -> dict[str, Any]:
    return {
        "min": minimo,
        "max": maximo,
        "moneda": moneda,
        "periodo": periodo,
        "naturaleza": "desconocido",
        "horas": None,
    }
