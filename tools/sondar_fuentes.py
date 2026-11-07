"""Sonda de disponibilidad de fuentes candidatas.

No forma parte de la aplicación: sirve para decidir con evidencia qué fuentes
entran al MVP. Descarga una sola vez cada endpoint, sin seguir redirecciones
fuera del dominio, y reporta estado, tipo y forma de la respuesta.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

UA = "BuscadorLaboral/0.2 (verificacion de fuentes)"

CANDIDATAS = [
    ("remoteok", "https://remoteok.com/api", "application/json"),
    ("remotive", "https://remotive.com/api/remote-jobs", "application/json"),
    ("arbeitnow", "https://www.arbeitnow.com/api/job-board-api", "application/json"),
    ("themuse", "https://www.themuse.com/api/public/jobs?page=1", "application/json"),
    ("workingnomads", "https://www.workingnomads.com/api/exposed_jobs/", "application/json"),
    ("nodesk", "https://nodesk.co/remote-jobs/index.xml", "application/xml"),
    ("getonbrd", "https://www.getonbrd.com/api/v0/projects?per_page=20", "application/json"),
    ("pythonjobs", "https://www.python.org/jobs/feed/rss/", "application/xml"),
    ("remoteco", "https://remote.co/remote-jobs/feed/", "application/xml"),
    ("jobspresso", "https://jobspresso.co/feed/?post_type=job_listing", "application/xml"),
    ("hnhiring", "https://hn.algolia.com/api/v1/search?query=hiring&tags=comment&hitsPerPage=5", "application/json"),
    ("https://www.getonbrd.com/api/v0/jobs", "https://www.getonbrd.com/api/v0/jobs", "application/json"),
    ("remotive-cat", "https://remotive.com/api/remote-jobs?category=data", "application/json"),
    ("weworkremotely-programming", "https://weworkremotely.com/categories/remote-programming-jobs.rss", "application/xml"),
    ("himalayas-limit", "https://himalayas.app/jobs/api?limit=1", "application/json"),
    ("jobicy-tag", "https://jobicy.com/api/v2/remote-jobs?count=5&tag=analyst", "application/json"),
]


@dataclass
class Sonda:
    nombre: str
    url: str
    http: int | None = None
    bytes: int = 0
    content_type: str = ""
    forma: str = ""
    claves: str = ""
    items: int | None = None
    error: str = ""


def _forma_json(datos) -> tuple[str, str, int | None]:
    if isinstance(datos, list):
        primero = datos[0] if datos else None
        claves = sorted(primero)[:18] if isinstance(primero, dict) else []
        return "lista", ",".join(str(c) for c in claves), len(datos)
    if isinstance(datos, dict):
        claves = sorted(datos)[:18]
        for clave in ("jobs", "data", "results", "offers", "items"):
            valor = datos.get(clave)
            if isinstance(valor, list):
                primero = valor[0] if valor else None
                sub = sorted(primero)[:18] if isinstance(primero, dict) else []
                return f"objeto.{clave}", ",".join(str(c) for c in sub), len(valor)
        return "objeto", ",".join(str(c) for c in claves), None
    return type(datos).__name__, "", None


def sondar(nombre: str, url: str, aceptar: str) -> Sonda:
    sonda = Sonda(nombre, url)
    peticion = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": aceptar})
    try:
        with urllib.request.urlopen(peticion, timeout=25) as respuesta:
            cuerpo = respuesta.read(3 * 1024 * 1024)
            sonda.http = respuesta.status
            sonda.bytes = len(cuerpo)
            sonda.content_type = respuesta.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        sonda.http = exc.code
        sonda.error = f"HTTP {exc.code}"
        return sonda
    except Exception as exc:  # noqa: BLE001
        sonda.error = f"{type(exc).__name__}: {exc}"
        return sonda

    texto = cuerpo.decode("utf-8", errors="replace")
    if "json" in aceptar:
        try:
            datos = json.loads(texto)
        except json.JSONDecodeError as exc:
            sonda.forma = "json_invalido"
            sonda.error = str(exc)[:120]
            return sonda
        sonda.forma, sonda.claves, sonda.items = _forma_json(datos)
    else:
        sonda.forma = "xml"
        sonda.items = texto.count("<item>") + texto.count("<entry>")
        sonda.claves = "item/entry"
    return sonda


def main() -> int:
    resultados = []
    for nombre, url, aceptar in CANDIDATAS:
        sonda = sondar(nombre, url, aceptar)
        resultados.append(sonda.__dict__)
        estado = sonda.error or "ok"
        print(
            f"{nombre:<26} http={sonda.http} bytes={sonda.bytes:>8} "
            f"forma={sonda.forma:<16} items={sonda.items} {estado}"
        )
        if sonda.claves:
            print(f"{'':<26} claves: {sonda.claves}")
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as archivo:
            json.dump(resultados, archivo, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
