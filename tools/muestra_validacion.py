"""Genera la muestra de ofertas reales para validar el ranking a mano.

La selección es determinista y busca los casos que importan:

- las elegibles y dudosas de arriba (¿acierta?),
- los falsos positivos conocidos que las reglas nuevas descartan (¿se corrigió?),
- títulos afines que quedaron incompatibles (¿hay falsos negativos?).

Escribe `docs/muestra-validacion.md` (para leer), `.csv` (para completar) y
`.meta.json` (procedencia: reglas, perfil, fecha y tamaño).

V02: la salida es **saneada**. Antes el CSV incluía título y empresa del aviso,
que son datos identificables de terceros, y el MD declaraba `rules-2.0.0` fijo
aunque se ejecutara con otra versión. Ahora sólo se publica lo que hace falta
para revisar el criterio, y la procedencia se escribe sola.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
DESTINO_MD = RAIZ / "docs" / "muestra-validacion.md"
DESTINO_CSV = RAIZ / "docs" / "muestra-validacion.csv"
DESTINO_META = RAIZ / "docs" / "muestra-validacion.meta.json"
#: Tamaño por defecto. Se puede ampliar con `--tamano N`; la muestra publicada
#: tiene 44 filas porque se generó con un corte más amplio que el actual.
TAMANO_MUESTRA = 25
#: Columnas publicadas. Sin título, sin empresa, sin URL y sin identificador: la
#: versión con datos originales queda en el proyecto de trabajo, no en Git.
COLUMNAS = ["n", "fuente", "modalidad", "region", "elegibilidad", "compatibilidad",
            "confianza", "dimension_principal", "motivo", "veredicto", "comentario"]

CASOS_CONOCIDOS = [
    "Risk&AI Manager",
    "Paid Ads Specialist",
    "Software Engineer Infrastructure",
    "Agile Program Manager",
    "Commercial Data Scientist",
    "Customer Support (Season Contractor)",
    "MEDICAL VIRTUAL ASSISTANT",
    "Product Owner",
    "Contracts Manager Federal",
]


def filas(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(f) for f in conn.execute(
            """SELECT j.id, j.titulo, j.empresa, j.modalidad, j.territorio, j.fuente_principal,
                      j.estado_vigencia, j.publicado_en,
                      a.elegibilidad, a.score, a.confianza, a.motivo_elegibilidad,
                      a.excepcion, a.razones_json
               FROM jobs j JOIN analyses a ON a.job_id = j.id AND a.obsoleto = 0
               WHERE j.merged_into IS NULL
               ORDER BY CASE a.elegibilidad WHEN 'eligible' THEN 0
                                            WHEN 'doubtful' THEN 1 ELSE 2 END,
                        a.score DESC"""
        ).fetchall()
    ]


def seleccionar(todas: list[dict], tamano: int = TAMANO_MUESTRA) -> list[dict]:
    elegidas: list[dict] = []
    vistos: set[str] = set()

    def agregar(fila: dict) -> None:
        if fila["id"] not in vistos and len(elegidas) < tamano:
            vistos.add(fila["id"])
            elegidas.append(fila)

    for fila in [f for f in todas if f["elegibilidad"] in {"eligible", "doubtful"}][:12]:
        agregar(fila)

    for titulo in CASOS_CONOCIDOS:
        for fila in todas:
            if fila["titulo"].strip().lower() == titulo.strip().lower():
                agregar(fila)
                break

    # Títulos afines que quedaron fuera: sirven para detectar falsos negativos.
    afin = [f for f in todas if f["elegibilidad"] == "incompatible"
            and any(p in (f["titulo"] or "").lower()
                    for p in ("analyst", "analista", "support", "soporte", "assistant",
                              "data entry", "reporting", "bi "))]
    for fila in afin[: max(0, tamano - len(elegidas))]:
        agregar(fila)

    for fila in todas:
        if len(elegidas) >= tamano:
            break
        agregar(fila)
    return elegidas


def dimension_principal(razones_json: str | None) -> str:
    """Dimensión que decide el veredicto: la primera razón con efecto duro.

    V02: el CSV publicado tenía esta columna pero ninguna herramienta la
    producía, así que la atribución de dimensiones no era reproducible.
    """
    try:
        razones = json.loads(razones_json or "[]")
    except (TypeError, ValueError):
        return "-"
    for razon in razones:
        if razon.get("efecto") in {"excluye", "duda"}:
            return razon.get("tipo") or "-"
    return "-"


def main(argv: list[str] | None = None) -> int:
    from buscador import config

    argumentos = list(argv if argv is not None else sys.argv[1:])
    tamano = TAMANO_MUESTRA
    if "--tamano" in argumentos:
        posicion = argumentos.index("--tamano")
        try:
            tamano = max(1, int(argumentos[posicion + 1]))
        except (IndexError, ValueError):
            print("--tamano necesita un número entero", file=sys.stderr)
            return 2
        del argumentos[posicion:posicion + 2]

    ruta = Path(os.environ["LOCALAPPDATA"]) / "BuscadorLaboral" / "data" / "buscador.db"
    conn = sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    elegidas = seleccionar(filas(conn), tamano)

    DESTINO_CSV.parent.mkdir(parents=True, exist_ok=True)
    # V02: UTF-8 sin BOM y sin título ni empresa. El BOM hacía que la primera
    # columna se leyera como «\ufeffn» y rompía cualquier consumidor automático.
    with DESTINO_CSV.open("w", encoding="utf-8", newline="") as manejador:
        escritor = csv.writer(manejador, delimiter=";")
        escritor.writerow(COLUMNAS)
        for indice, fila in enumerate(elegidas, start=1):
            escritor.writerow([
                indice, fila["fuente_principal"], fila["modalidad"] or "",
                fila["territorio"] or "", fila["elegibilidad"],
                fila["score"] if fila["score"] is not None else "",
                fila["confianza"] or "",
                dimension_principal(fila.get("razones_json")),
                fila["motivo_elegibilidad"] or "", "", "",
            ])

    DESTINO_META.write_text(json.dumps({
        "generado_en": config.ahora_utc(),
        "reglas": config.RULES_VERSION,
        "tamano": len(elegidas),
        "tamano_solicitado": tamano,
        "columnas": COLUMNAS,
        "saneada": True,
        "nota": "Sin título, empresa, URL ni identificador de aviso.",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lineas = [
        "# Muestra de validación del ranking",
        "",
        f"Muestra de **{len(elegidas)} ofertas** tomada del catálogo clasificado con "
        f"`{config.RULES_VERSION}`.",
        "",
        "**No contiene datos identificables**: sin empresa, sin título del puesto, sin URL",
        "y sin identificador de aviso. La versión con los datos originales no se publica.",
        "",
        "La selección es determinista y busca los casos que importan: las elegibles y",
        "dudosas de arriba, los falsos positivos conocidos y títulos afines que quedaron",
        "descartados (para detectar también falsos negativos).",
        "",
        "Cómo usarla: en el CSV, escribí en **veredicto** una de estas opciones y, si querés,",
        "un comentario corto.",
        "",
        "| Veredicto | Significado |",
        "|---|---|",
        "| `si` | Vale la pena postularse |",
        "| `no` | No sirve (decime por qué en el comentario) |",
        "| `duda` | Falta información para decidir |",
        "",
        f"Generada desde `buscador.db` (sólo lectura) con reglas `{config.RULES_VERSION}`.",
        "La procedencia exacta queda en `muestra-validacion.meta.json`.",
        "",
        "| # | Fuente | Modalidad | Región | Elegibilidad | Compat. | Confianza | Dimensión | Por qué |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for indice, fila in enumerate(elegidas, start=1):
        compatibilidad = f"{fila['score']:.0f}" if fila["score"] is not None else "—"
        lineas.append(
            f"| {indice} | {fila['fuente_principal']} | {fila['modalidad'] or '—'} | "
            f"{(fila['territorio'] or '—')[:32]} | {fila['elegibilidad']} | "
            f"{compatibilidad} | {fila['confianza'] or '—'} | "
            f"{dimension_principal(fila.get('razones_json'))} | "
            f"{(fila['motivo_elegibilidad'] or '')[:60]} |"
        )
    lineas += [
        "",
        "## Qué mirar",
        "",
        "1. ¿Las elegibles son realmente postulables desde Argentina, en remoto?",
        "2. ¿Alguna dudosa debería ser elegible? (territorio o modalidad mal leídos)",
        "3. ¿Alguna incompatible con título afín debería estar arriba? (falso negativo)",
        "4. ¿La confianza declarada coincide con lo que ves en el aviso?",
        "",
        "El CSV completo está en `docs/muestra-validacion.csv`.",
    ]
    DESTINO_MD.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(json.dumps({"ofertas": len(elegidas), "markdown": str(DESTINO_MD),
                      "csv": str(DESTINO_CSV), "meta": str(DESTINO_META)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
