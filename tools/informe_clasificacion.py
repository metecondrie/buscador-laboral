"""Informe reproducible del catálogo clasificado. **Sólo lectura.**

Reproduce los números del informe `docs/INFORME_CLASIFICACION.md` a partir de la
base operativa, sin escribir nada y sin tocar la aplicación.

    py -3 tools/informe_clasificacion.py              # markdown a la salida
    py -3 tools/informe_clasificacion.py --json       # json a la salida
    py -3 tools/informe_clasificacion.py --db RUTA    # otra base (sólo lectura)

La base se abre siempre con `mode=ro`: el proceso no puede escribir en ella y no
adquiere bloqueos de escritura, de modo que la búsqueda programada puede seguir
corriendo mientras se lee.

Qué NO hace este script: no reclasifica, no modifica reglas, umbrales, perfil ni
scheduler, y no escribe en ningún lado. Es un lector.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

#: Dimensiones del filtro duro, en el orden en que las define `buscador/rules.py`.
DIMENSIONES = ("categoria", "territorio", "modalidad", "formacion",
               "seniority", "idioma", "viajes")

#: Familias de territorio. Tokens en minúsculas; la primera que coincide gana.
FAMILIAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("remoto global declarado", (
        "anywhere in the world", "anywhere", "worldwide", "global", "remote",
        "home based - worldwide", "home based - emea", "remote worldwide",
        "todo el mundo")),
    ("Estados Unidos / Canada / America del Norte", (
        "united states", "usa", "u.s.", "north america", "est or ct", "est/ct",
        "canada", "new york", "san francisco", "austin", "boston", "denver", "texas",
        "california", "miami", "houston", "chicago", "seattle", "portland",
        "los angeles", "philadelphia", "atlanta", "dallas", "palo alto",
        "virgin islands", "bahamas", "any state")),
    ("Reino Unido", ("united kingdom", "uk", "london", "manchester", "bristol",
                     "edinburgh", "wales", "scotland", "ireland")),
    ("Latinoamerica", ("argentina", "buenos aires", "mexico", "colombia", "brazil",
                       "brasil", "chile", "peru", "uruguay", "paraguay", "bolivia",
                       "ecuador", "venezuela", "costa rica", "panama", "guatemala",
                       "honduras", "nicaragua", "el salvador", "cuba", "dominicana",
                       "puerto rico", "latam", "latin america", "sao paulo",
                       "sao paulo", "montevideo", "bogota", "lima", "santiago",
                       "caracas", "guadalajara", "monterrey", "ciudad de mexico",
                       "aguascalientes")),
    ("Asia-Pacifico", ("india", "philippines", "singapore", "japan", "china",
                       "australia", "new zealand", "korea", "taiwan", "malaysia",
                       "vietnam", "indonesia", "thailand", "hong kong", "asia-pacific",
                       "apac", "new delhi", "mumbai", "bangalore", "pune", "sydney",
                       "pakistan", "afghanistan", "bali")),
    ("Africa y Oriente Medio", ("israel", "emirates", "united arab emirates", "saudi",
                                "egypt", "nigeria", "kenya", "south africa", "morocco",
                                "turkey", "turkiye", "qatar", "jordan", "lebanon")),
    ("Europa (sin Reino Unido)", (
        "germany", "berlin", "munich", "munchen", "hamburg", "frankfurt", "nuremberg",
        "koln", "cologne", "dusseldorf", "heidelberg", "darmstadt", "hannover",
        "hanover", "stuttgart", "freiburg", "regensburg", "aachen", "gilching",
        "bad salzungen", "halle", "storkow", "vilshofer", "dortmund", "parsdorf",
        "konstanz", "kassel", "augsburg", "alphaville", "bottrop", "bonn", "bremen",
        "bielefeld", "bad homburg", "bad saarow", "lubeck", "mainz", "kiel",
        "time zone: cet", "cet (+/- 3 hours)", "westeuropa", "spain", "madrid",
        "barcelona", "portugal", "lisbon", "porto", "italy", "milan", "rome", "italia",
        "france", "paris", "poland", "warsaw", "netherlands", "amsterdam", "utrecht",
        "rotterdam", "sweden", "norway", "finland", "denmark", "copenhagen", "oslo",
        "stockholm", "helsinki", "belgium", "brussels", "austria", "vienna",
        "switzerland", "zurich", "basel", "geneva", "czechia", "prague", "slovakia",
        "hungary", "budapest", "romania", "bucharest", "bulgaria", "sofia", "greece",
        "athens", "croatia", "zagreb", "serbia", "belgrade", "ukraine", "moldova",
        "albania", "cyprus", "estonia", "tallinn", "latvia", "riga", "lithuania",
        "vilnius", "iceland", "luxembourg", "malta", "emea", "europe")),
)

#: Normaliza texto para comparar sin acentos: los avisos traen "México",
#: "München" o "Köln" y los tokens de las familias van sin tilde.
def _sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in normalizado if not unicodedata.combining(c)).lower()


#: Motivos que contienen estas palabras son territorio aunque la fuente no lo diga.
def familia_territorio(valor: str | None) -> str:
    if not valor:
        return "sin territorio declarado"
    base = _sin_acentos(valor)
    for nombre, tokens in FAMILIAS:
        for token in tokens:
            if token in base:
                return nombre
    return "otra region no clasificada"


def abrir(db: Path) -> sqlite3.Connection:
    """Abre la base en modo **solo lectura**. Nunca escribe."""
    conexion = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conexion.row_factory = sqlite3.Row
    return conexion


def _consulta(conexion: sqlite3.Connection, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    return conexion.execute(sql, args).fetchall()


def analizar(db: Path) -> dict:
    conexion = abrir(db)
    try:
        totales = {r["elegibilidad"]: r["n"]
                    for r in _consulta(
                        conexion,
                        "SELECT elegibilidad, COUNT(*) AS n FROM analyses "
                        "WHERE obsoleto=0 GROUP BY elegibilidad")}

        # --- desglose por fuente -------------------------------------------
        por_fuente = [dict(r) for r in _consulta(
            conexion,
            "SELECT s.source_id AS id, s.nombre AS fuente, COUNT(*) AS n "
            "FROM analyses a JOIN jobs j ON a.job_id=j.id "
            "JOIN sources s ON j.fuente_principal=s.source_id "
            "WHERE a.obsoleto=0 AND a.elegibilidad='incompatible' "
            "GROUP BY s.source_id ORDER BY n DESC")]

        # --- desglose por categoría ----------------------------------------
        por_categoria = [dict(r) for r in _consulta(
            conexion,
            "SELECT COALESCE(j.categoria, '(sin categoria)') AS categoria, "
            "COUNT(*) AS n FROM analyses a JOIN jobs j ON a.job_id=j.id "
            "WHERE a.obsoleto=0 AND a.elegibilidad='incompatible' "
            "GROUP BY j.categoria ORDER BY n DESC")]

        # --- desglose por territorio (familiar + detalle) --------------------
        crudo_territorio = _consulta(
            conexion,
            "SELECT COALESCE(j.territorio, '(sin territorio)') AS territorio, "
            "COUNT(*) AS n FROM analyses a JOIN jobs j ON a.job_id=j.id "
            "WHERE a.obsoleto=0 AND a.elegibilidad='incompatible' "
            "GROUP BY j.territorio ORDER BY n DESC")
        familias: Counter = Counter()
        for fila in crudo_territorio:
            valor = None if fila["territorio"] == "(sin territorio)" else fila["territorio"]
            familias[familia_territorio(valor)] += fila["n"]

        # --- desglose por experiencia (seniority declarado) ----------------
        por_experiencia = [dict(r) for r in _consulta(
            conexion,
            "SELECT COALESCE(o.seniority, '(sin seniority declarado)') AS seniority, "
            "COUNT(DISTINCT a.job_id) AS n FROM analyses a "
            "JOIN job_observations jo ON jo.job_id=a.job_id "
            "JOIN observations o ON o.id=jo.observation_id "
            "WHERE a.obsoleto=0 AND a.elegibilidad='incompatible' "
            "GROUP BY o.seniority ORDER BY n DESC")]

        # --- dimensión principal del descarte --------------------------------
        # El motor ya elige el motivo más específico (`motivos_dudos` de
        # `rules.evaluar`). Se recupera la dimensión cruzando ese motivo con
        # las razones de tipo "excluye" del propio análisis, en vez de adivinar
        # por palabras clave.
        principal: Counter = Counter()
        sin_dimension = 0
        for fila in _consulta(
                conexion,
                "SELECT a.motivo_elegibilidad AS motivo, a.razones_json AS razones "
                "FROM analyses a WHERE a.obsoleto=0 AND a.elegibilidad='incompatible'"):
            motivo = (fila["motivo"] or "").strip()
            try:
                razones = json.loads(fila["razones"] or "[]")
            except (json.JSONDecodeError, TypeError):
                razones = []
            excluyentes = [r for r in razones
                           if r.get("efecto") == "excluye" and r.get("tipo") in DIMENSIONES]
            dimension = None
            for razon in excluyentes:
                texto = (razon.get("texto") or "").strip()
                if texto and (texto in motivo or motivo in texto):
                    dimension = razon["tipo"]
                    break
            if dimension is None and excluyentes:
                dimension = excluyentes[0]["tipo"]
            if dimension is None:
                sin_dimension += 1
            else:
                principal[dimension] += 1

        # --- idioma: ofertas descartadas por requisito de idioma -------------
        por_idioma = Counter()
        for fila in _consulta(
                conexion,
                "SELECT a.razones_json AS razones FROM analyses a "
                "WHERE a.obsoleto=0 AND a.elegibilidad='incompatible'"):
            try:
                razones = json.loads(fila["razones"] or "[]")
            except (json.JSONDecodeError, TypeError):
                razones = []
            for razon in razones:
                if razon.get("efecto") == "excluye" and razon.get("tipo") == "idioma":
                    texto = (razon.get("texto") or "").strip()
                    por_idioma[texto] += 1

        # --- dudosas: por qué dudan ------------------------------------------
        duda_dimensiones: Counter = Counter()
        for fila in _consulta(
                conexion,
                "SELECT a.razones_json AS razones FROM analyses a "
                "WHERE a.obsoleto=0 AND a.elegibilidad='doubtful'"):
            try:
                razones = json.loads(fila["razones"] or "[]")
            except (json.JSONDecodeError, TypeError):
                razones = []
            for razon in razones:
                if razon.get("efecto") == "duda":
                    duda_dimensiones[razon.get("tipo")] += 1

        # --- elegibles y dudosas por fuente y categoría -----------------------
        resumen_clases = {}
        for clase in ("eligible", "doubtful"):
            por_f = [dict(r) for r in _consulta(
                conexion,
                "SELECT s.source_id AS id, s.nombre AS fuente, COUNT(*) AS n "
                "FROM analyses a JOIN jobs j ON a.job_id=j.id "
                "JOIN sources s ON j.fuente_principal=s.source_id "
                "WHERE a.obsoleto=0 AND a.elegibilidad=? "
                "GROUP BY s.source_id ORDER BY n DESC", (clase,))]
            por_c = [dict(r) for r in _consulta(
                conexion,
                "SELECT COALESCE(j.categoria, '(sin categoria)') AS categoria, "
                "COUNT(*) AS n FROM analyses a JOIN jobs j ON a.job_id=j.id "
                "WHERE a.obsoleto=0 AND a.elegibilidad=? "
                "GROUP BY j.categoria ORDER BY n DESC", (clase,))]
            resumen_clases[clase] = {"por_fuente": por_f, "por_categoria": por_c}

        # --- contexto del catálogo -------------------------------------------
        contexto = {
            "reglas": _consulta(
                conexion,
                "SELECT rules_version, COUNT(*) AS n FROM analyses "
                "WHERE obsoleto=0 GROUP BY rules_version")[0]["rules_version"],
            "version_app": _consulta(
                conexion,
                "SELECT valor FROM settings WHERE clave='version_app'")
            and _consulta(conexion,
                          "SELECT valor FROM settings WHERE clave='version_app'")[0]["valor"],
            "ofertas_totales": _consulta(
                conexion, "SELECT COUNT(*) AS n FROM jobs")[0]["n"],
            "analyses_totales": _consulta(
                conexion, "SELECT COUNT(*) AS n FROM analyses")[0]["n"],
            "analyses_vigentes": _consulta(
                conexion, "SELECT COUNT(*) AS n FROM analyses WHERE obsoleto=0")[0]["n"],
            "confianza": [dict(r) for r in _consulta(
                conexion,
                "SELECT COALESCE(confianza, '(sin confianza)') AS confianza, "
                "COUNT(*) AS n FROM analyses WHERE obsoleto=0 GROUP BY confianza "
                "ORDER BY n DESC")],
            "categorias_publicadas": _consulta(
                conexion,
                "SELECT COUNT(DISTINCT categoria) AS n FROM jobs "
                "WHERE categoria IS NOT NULL")[0]["n"],
        }

        return {
            "base": str(db),
            "contexto": contexto,
            "totales": totales,
            "total": sum(totales.values()),
            "por_fuente": por_fuente,
            "por_categoria": por_categoria,
            "por_familia_territorio": dict(familias.most_common()),
            "territorio_detalle": [dict(r) for r in crudo_territorio[:25]],
            "por_experiencia": por_experiencia,
            "dimension_principal": dict(principal.most_common()),
            "sin_dimension_principal": sin_dimension,
            "por_idioma": dict(por_idioma.most_common()),
            "duda_dimensiones": dict(duda_dimensiones.most_common()),
            "clases": resumen_clases,
        }
    finally:
        conexion.close()


def a_markdown(datos: dict) -> str:
    lineas: list[str] = []
    ctx = datos["contexto"]
    tot = datos["totales"]
    lineas.append("# Clasificación del catálogo · informe reproducible")
    lineas.append("")
    lineas.append(f"Base: `{datos['base']}` (abierta en `mode=ro`, sin escrituras).")
    lineas.append(f"Reglas: `{ctx['reglas']}` · ofertas: {ctx['ofertas_totales']} · "
                  f"análisis vigentes: {ctx['analyses_vigentes']} de {ctx['analyses_totales']}.")
    lineas.append("")
    lineas.append("## Distribución")
    lineas.append("")
    lineas.append("| Clase | Ofertas |")
    lineas.append("| --- | ---: |")
    for clase in ("eligible", "doubtful", "incompatible"):
        lineas.append(f"| {clase} | {tot.get(clase, 0):,} |".replace(",", "."))
    lineas.append(f"| **total** | **{datos['total']:,}** |".replace(",", "."))
    lineas.append("")
    lineas.append("## Dimensión principal del descarte (una por oferta)")
    lineas.append("")
    lineas.append("| Dimensión | Ofertas |")
    lineas.append("| --- | ---: |")
    for dim, n in datos["dimension_principal"].items():
        lineas.append(f"| {dim} | {n:,} |".replace(",", "."))
    if datos["sin_dimension_principal"]:
        lineas.append(f"| (sin dimensión recuperable) | {datos['sin_dimension_principal']} |")
    lineas.append("")
    lineas.append("## Por fuente")
    lineas.append("")
    lineas.append("| Fuente | Incompatibles |")
    lineas.append("| --- | ---: |")
    for fila in datos["por_fuente"]:
        lineas.append(f"| {fila['id']} · {fila['fuente']} | {fila['n']} |")
    lineas.append("")
    lineas.append("## Por familia de territorio")
    lineas.append("")
    lineas.append("| Familia | Incompatibles |")
    lineas.append("| --- | ---: |")
    for nombre, n in datos["por_familia_territorio"].items():
        lineas.append(f"| {nombre} | {n} |")
    lineas.append("")
    lineas.append("## Por categoría")
    lineas.append("")
    lineas.append("| Categoría | Incompatibles |")
    lineas.append("| --- | ---: |")
    for fila in datos["por_categoria"]:
        lineas.append(f"| {fila['categoria']} | {fila['n']} |")
    lineas.append("")
    lineas.append("## Por experiencia declarada (seniority)")
    lineas.append("")
    lineas.append("| Seniority | Ofertas |")
    lineas.append("| --- | ---: |")
    for fila in datos["por_experiencia"]:
        lineas.append(f"| {fila['seniority']} | {fila['n']} |")
    lineas.append("")
    lineas.append("## Por idioma (motivos de descarte)")
    lineas.append("")
    lineas.append("| Motivo | Ofertas |")
    lineas.append("| --- | ---: |")
    for texto, n in datos["por_idioma"].items():
        lineas.append(f"| {texto} | {n} |")
    lineas.append("")
    lineas.append("## Por qué dudan las dudosas")
    lineas.append("")
    lineas.append("| Dimensión | Ofertas |")
    lineas.append("| --- | ---: |")
    for dim, n in datos["duda_dimensiones"].items():
        lineas.append(f"| {dim} | {n} |")
    lineas.append("")
    return "\n".join(lineas)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default="", help="ruta de la base (por defecto, la operativa)")
    parser.add_argument("--json", action="store_true", help="salida en json")
    args = parser.parse_args()

    if args.db:
        db = Path(args.db)
    else:
        local = os.environ.get("LOCALAPPDATA", "")
        db = Path(local) / "BuscadorLaboral" / "data" / "buscador.db"
    if not db.exists():
        print(f"no existe la base: {db}", file=sys.stderr)
        return 2

    datos = analizar(db)
    if args.json:
        print(json.dumps(datos, ensure_ascii=False, indent=2))
    else:
        print(a_markdown(datos))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
