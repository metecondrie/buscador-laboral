"""Genera la muestra de 25 ofertas reales para validar el ranking a mano.

La selección es determinista y busca los casos que importan:

- las elegibles y dudosas de arriba (¿acierta?),
- los falsos positivos conocidos que las reglas nuevas descartan (¿se corrigió?),
- títulos afines que quedaron incompatibles (¿hay falsos negativos?).

Escribe `docs/muestra-validacion.md` (para leer) y `.csv` (para completar).
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


def seleccionar(todas: list[dict]) -> list[dict]:
    elegidas: list[dict] = []
    vistos: set[str] = set()

    def agregar(fila: dict) -> None:
        if fila["id"] not in vistos and len(elegidas) < 25:
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
    for fila in afin[: max(0, 25 - len(elegidas))]:
        agregar(fila)

    for fila in todas:
        if len(elegidas) >= 25:
            break
        agregar(fila)
    return elegidas


def main() -> int:
    ruta = Path(os.environ["LOCALAPPDATA"]) / "BuscadorLaboral" / "data" / "buscador.db"
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    elegidas = seleccionar(filas(conn))

    DESTINO_CSV.parent.mkdir(parents=True, exist_ok=True)
    with DESTINO_CSV.open("w", encoding="utf-8-sig", newline="") as manejador:
        escritor = csv.writer(manejador, delimiter=";")
        escritor.writerow(["n", "titulo", "empresa", "fuente", "modalidad", "region",
                           "elegibilidad", "compatibilidad", "confianza", "motivo",
                           "veredicto", "comentario"])
        for indice, fila in enumerate(elegidas, start=1):
            escritor.writerow([
                indice, fila["titulo"], fila["empresa"] or "", fila["fuente_principal"],
                fila["modalidad"] or "", fila["territorio"] or "",
                fila["elegibilidad"], fila["score"] if fila["score"] is not None else "",
                fila["confianza"] or "", fila["motivo_elegibilidad"] or "", "", "",
            ])

    lineas = [
        "# Muestra de validación del ranking",
        "",
        "25 ofertas reales tomadas de la base, elegidas para que puedas evaluar el criterio.",
        "No están filtradas para que «queden bien»: incluyen los falsos positivos que reportaste",
        "y títulos afines que quedaron descartados, para detectar también falsos negativos.",
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
        f"Generada desde `buscador.db` con reglas {json.dumps('rules-2.0.0')} y perfil real.",
        "",
        "| # | Oferta | Empresa | Fuente | Modalidad | Elegibilidad | Compat. | Confianza | Por qué |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for indice, fila in enumerate(elegidas, start=1):
        compatibilidad = f"{fila['score']:.0f}" if fila["score"] is not None else "—"
        lineas.append(
            f"| {indice} | {fila['titulo'][:58]} | {(fila['empresa'] or '—')[:24]} | "
            f"{fila['fuente_principal']} | {fila['modalidad'] or '—'} | {fila['elegibilidad']} | "
            f"{compatibilidad} | {fila['confianza'] or '—'} | {(fila['motivo_elegibilidad'] or '')[:60]} |"
        )
    lineas += [
        "",
        "## Qué mirar",
        "",
        "1. ¿Las dos elegibles son realmente postulables desde Argentina, en remoto?",
        "2. ¿Alguna dudosa debería ser elegible? (territorio o modalidad mal leídos)",
        "3. ¿Alguna incompatible con título afín debería estar arriba? (falso negativo)",
        "4. ¿La confianza declarada coincide con lo que ves en el aviso?",
        "",
        "El CSV completo está en `docs/muestra-validacion.csv`.",
    ]
    DESTINO_MD.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(json.dumps({"ofertas": len(elegidas), "markdown": str(DESTINO_MD),
                      "csv": str(DESTINO_CSV)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
