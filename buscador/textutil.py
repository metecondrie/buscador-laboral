"""Utilidades de texto, hashes, URLs y fechas.

El contenido de una oferta es dato delimitado: se convierte a texto plano
y nunca se renderiza como HTML activo (sección 12 del plan).
"""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
import socket
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ETIQUETAS = re.compile(r"<[^>]+>")
ESPACIOS = re.compile(r"[ \t\r\f\v]+")
SALTOS = re.compile(r"\n{3,}")
BLOQUES = re.compile(r"</(p|div|li|h[1-6]|tr|br)>|<br\s*/?>", re.IGNORECASE)

PARAMS_SEGUIMIENTO = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "ref", "referrer", "source", "src", "trk",
    "tracking", "fbclid", "gclid", "mc_cid", "mc_eid", "lever-source",
}


def html_a_texto(valor: str | None) -> str:
    if not valor:
        return ""
    texto = BLOQUES.sub("\n", valor)
    texto = ETIQUETAS.sub("", texto)
    texto = html.unescape(texto)
    texto = texto.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lineas = [ESPACIOS.sub(" ", linea).strip() for linea in texto.split("\n")]
    texto = "\n".join(linea for linea in lineas if linea)
    return SALTOS.sub("\n\n", texto).strip()


def normalizar(valor: str | None) -> str:
    """Minúsculas sin acentos ni signos, para comparar sin inventar datos."""
    if not valor:
        return ""
    base = unicodedata.normalize("NFKD", valor)
    base = "".join(c for c in base if not unicodedata.combining(c))
    base = re.sub(r"[^a-z0-9]+", " ", base.lower())
    return " ".join(base.split())


def hash_texto(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def hash_semantico(datos: dict) -> str:
    """Hash estable de contenido decisivo, sin fechas de captura ni HTML."""
    limpio = json.dumps(datos, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hash_texto(limpio)


def slug(valor: str, maximo: int = 60) -> str:
    base = normalizar(valor).replace(" ", "-")
    return base[:maximo].strip("-") or "sin-titulo"


def url_canonica(url: str) -> str:
    """Quita parámetros de seguimiento conocidos y ordena la query."""
    partes = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(partes.query, keep_blank_values=False)
        if k.lower() not in PARAMS_SEGUIMIENTO and not k.lower().startswith("utm_")
    ]
    ruta = partes.path.rstrip("/") or "/"
    return urlunsplit((partes.scheme.lower(), partes.netloc.lower(), ruta, urlencode(query), ""))


def dominio(url: str) -> str:
    return urlsplit(url).hostname or ""


def es_url_publica(url: str) -> tuple[bool, str]:
    """Rechaza esquemas y destinos internos antes de cualquier descarga."""
    partes = urlsplit(url)
    if partes.scheme not in {"https", "http"}:
        return False, f"esquema no permitido: {partes.scheme or 'vacío'}"
    host = partes.hostname
    if not host:
        return False, "sin host"
    if host.lower() in {"localhost", "localhost.localdomain"}:
        return False, "host local"
    try:
        infos = socket.getaddrinfo(host, partes.port or (443 if partes.scheme == "https" else 80))
    except socket.gaierror as exc:
        return False, f"no resuelve: {exc}"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False, f"IP no pública: {ip}"
    return True, "ok"


def fecha_iso(valor: str | int | float | None) -> str | None:
    """Convierte RFC 822, ISO 8601 o epoch a UTC ISO 8601 con Z."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return _desde_epoch(float(valor))
    texto = str(valor).strip()
    if texto.isdigit():
        return _desde_epoch(float(texto))
    try:
        dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        return _formatear(dt)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(texto)
        return _formatear(dt)
    except (TypeError, ValueError):
        return None


def _desde_epoch(valor: float) -> str:
    return _formatear(datetime.fromtimestamp(valor, tz=timezone.utc))


def _formatear(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def dias_desde(iso: str | None, referencia: datetime | None = None) -> int | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    ref = referencia or datetime.now(timezone.utc)
    return max((ref - dt).days, 0)
