"""Validación humana del ranking.

La muestra de 25 queda **fijada en la base** cuando se crea: así las respuestas
del usuario sobreviven a cualquier reclasificación posterior y las métricas siguen
siendo comparables.

La selección es la misma que genera `tools/muestra_validacion.py`: las elegibles
y dudosas de arriba, los falsos positivos conocidos y títulos afines que
quedaron fuera (para detectar falsos negativos).

Nada acá simula veredictos: si no hay respuestas, las métricas dicen «sin datos».
"""

from __future__ import annotations

import json
import sqlite3

from . import config, db

VEREDICTOS = ("si", "no", "duda")
CRITERIO = "elegibles y dudosas + falsos positivos conocidos + afines descartados"
TOTAL_MUESTRA = 25

CASOS_CONOCIDOS = [
    "Risk&AI Manager", "Paid Ads Specialist", "Software Engineer Infrastructure",
    "Agile Program Manager", "Commercial Data Scientist", "Product Owner",
    "Contracts Manager Federal",
]


def _candidatas(conn: sqlite3.Connection) -> list[dict]:
    return [dict(f) for f in conn.execute(
        """SELECT j.id, j.titulo, a.elegibilidad, a.score
           FROM jobs j JOIN analyses a ON a.job_id = j.id AND a.obsoleto = 0
           WHERE j.merged_into IS NULL
           ORDER BY CASE a.elegibilidad WHEN 'eligible' THEN 0
                                        WHEN 'doubtful' THEN 1 ELSE 2 END,
                    a.score DESC"""
    ).fetchall()]


def seleccionar(conn: sqlite3.Connection, total: int = TOTAL_MUESTRA) -> list[str]:
    filas = _candidatas(conn)
    elegidas: list[str] = []
    vistos: set[str] = set()

    def agregar(identificador: str) -> None:
        if identificador not in vistos and len(elegidas) < total:
            vistos.add(identificador)
            elegidas.append(identificador)

    for fila in [f for f in filas if f["elegibilidad"] in {"eligible", "doubtful"}][:12]:
        agregar(fila["id"])

    for titulo in CASOS_CONOCIDOS:
        for fila in filas:
            if (fila["titulo"] or "").strip().lower() == titulo.strip().lower():
                agregar(fila["id"])
                break

    afin = [
        f for f in filas if f["elegibilidad"] == "incompatible"
        and any(p in (f["titulo"] or "").lower()
                for p in ("analyst", "analista", "support", "soporte", "assistant",
                          "data entry", "reporting"))
    ]
    for fila in afin:
        agregar(fila["id"])

    for fila in filas:
        agregar(fila["id"])
    return elegidas


def crear_muestra(conn: sqlite3.Connection, total: int = TOTAL_MUESTRA) -> int:
    """Crea (o reutiliza) una muestra fija. Devuelve su id."""
    existente = conn.execute(
        "SELECT id FROM validation_samples ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if existente is not None:
        return int(existente["id"])
    elegidas = seleccionar(conn, total)
    with db.transaccion(conn):
        cur = conn.execute(
            "INSERT INTO validation_samples (criterio, total, creada_en) VALUES (?,?,?)",
            (CRITERIO, len(elegidas), config.ahora_utc()),
        )
        muestra_id = int(cur.lastrowid)
        for orden, job_id in enumerate(elegidas, start=1):
            conn.execute(
                "INSERT INTO validation_items (muestra_id, job_id, orden) VALUES (?,?,?)",
                (muestra_id, job_id, orden),
            )
    return muestra_id


def muestra_activa(conn: sqlite3.Connection) -> int | None:
    fila = conn.execute("SELECT id FROM validation_samples ORDER BY id DESC LIMIT 1").fetchone()
    return int(fila["id"]) if fila else None


def items(conn: sqlite3.Connection, muestra_id: int) -> list[dict]:
    """Las 25 ofertas con lo necesario para decidir, incluido el texto."""
    filas = conn.execute(
        """SELECT i.orden, i.job_id, j.titulo, j.empresa, j.url_atribucion, j.modalidad,
                  j.territorio, j.estado_vigencia, j.publicado_en, j.fuente_principal,
                  a.elegibilidad, a.score, a.confianza, a.motivo_elegibilidad, a.razones_json,
                  a.incertidumbres_json, a.componentes_json,
                  (SELECT o.descripcion_texto FROM observations o
                     JOIN job_observations jo ON jo.observation_id = o.id
                    WHERE jo.job_id = j.id ORDER BY o.detectado_en DESC LIMIT 1) AS descripcion,
                  (SELECT o.url FROM observations o
                     JOIN job_observations jo ON jo.observation_id = o.id
                    WHERE jo.job_id = j.id ORDER BY o.detectado_en DESC LIMIT 1) AS url_fuente,
                  r.veredicto, r.comentario, r.actualizado_en
           FROM validation_items i
           JOIN jobs j ON j.id = i.job_id
           LEFT JOIN analyses a ON a.job_id = j.id AND a.obsoleto = 0
           LEFT JOIN validation_reviews r ON r.muestra_id = i.muestra_id AND r.job_id = i.job_id
           WHERE i.muestra_id = ?
           ORDER BY i.orden""",
        (muestra_id,),
    ).fetchall()
    salida = []
    for fila in filas:
        datos = dict(fila)
        for campo in ("razones_json", "incertidumbres_json", "componentes_json"):
            crudo = datos.pop(campo, None)
            clave = campo.replace("_json", "")
            try:
                datos[clave] = json.loads(crudo) if crudo else []
            except json.JSONDecodeError:
                datos[clave] = []
        datos["descripcion"] = (datos.get("descripcion") or "")[:2500]
        salida.append(datos)
    return salida


def registrar(conn: sqlite3.Connection, muestra_id: int, job_id: str,
              veredicto: str, comentario: str = "") -> dict:
    if veredicto not in VEREDICTOS:
        raise ValueError(f"veredicto inválido: {veredicto}")
    fila = conn.execute(
        """SELECT a.elegibilidad, a.score FROM analyses a
           WHERE a.job_id=? AND a.obsoleto=0 ORDER BY a.id DESC LIMIT 1""",
        (job_id,),
    ).fetchone()
    ahora = config.ahora_utc()
    with db.transaccion(conn):
        conn.execute(
            """INSERT INTO validation_reviews
                   (muestra_id, job_id, veredicto, comentario, estado_previo, score_previo,
                    creado_en, actualizado_en)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(muestra_id, job_id) DO UPDATE SET
                   veredicto=excluded.veredicto, comentario=excluded.comentario,
                   actualizado_en=excluded.actualizado_en""",
            (muestra_id, job_id, veredicto, comentario[:800],
             fila["elegibilidad"] if fila else None,
             fila["score"] if fila else None, ahora, ahora),
        )
    return {"job_id": job_id, "veredicto": veredicto}


def metricas(conn: sqlite3.Connection, muestra_id: int) -> dict:
    filas = items(conn, muestra_id)
    revisadas = [f for f in filas if f["veredicto"]]
    si = [f for f in revisadas if f["veredicto"] == "si"]
    no = [f for f in revisadas if f["veredicto"] == "no"]
    duda = [f for f in revisadas if f["veredicto"] == "duda"]

    resueltas = len(si) + len(no)
    precision = round(100 * len(si) / resueltas, 1) if resueltas else None
    falsos_positivos = [f for f in no if f["elegibilidad"] in {"eligible", "doubtful"}]
    falsos_negativos = [f for f in si if f["elegibilidad"] == "incompatible"]

    por_regla = {}
    for fila in revisadas:
        clave = fila["elegibilidad"] or "sin_analisis"
        cubo = por_regla.setdefault(clave, {"si": 0, "no": 0, "duda": 0})
        cubo[fila["veredicto"]] += 1

    return {
        "muestra": muestra_id,
        "total": len(filas),
        "revisadas": len(revisadas),
        "pendientes": len(filas) - len(revisadas),
        "si": len(si), "no": len(no), "duda": len(duda),
        "precision_pct": precision,
        "falsos_positivos": len(falsos_positivos),
        "falsos_negativos": len(falsos_negativos),
        "tasa_falsos_positivos_pct": round(100 * len(falsos_positivos) / resueltas, 1) if resueltas else None,
        "por_regla": por_regla,
        "ejemplos_falsos_positivos": [
            {"titulo": f["titulo"], "score": f["score"], "comentario": f["comentario"]}
            for f in falsos_positivos[:5]
        ],
        "ejemplos_falsos_negativos": [
            {"titulo": f["titulo"], "motivo": f["motivo_elegibilidad"], "comentario": f["comentario"]}
            for f in falsos_negativos[:5]
        ],
        "conclusion": _conclusion(len(revisadas), len(filas), precision),
    }


def _conclusion(revisadas: int, total: int, precision: float | None) -> str:
    if revisadas == 0:
        return "sin datos: todavía no hay veredictos cargados"
    if revisadas < total:
        return f"parcial: {revisadas} de {total} revisadas"
    if precision is None:
        return "revisión completa, pero sin casos «sí» ni «no»: no se puede calcular precisión"
    if precision >= 80:
        return "el ranking acierta en la mayoría de los casos revisados"
    if precision >= 60:
        return "el ranking acierta a medias: hay que ajustar las reglas"
    return "el ranking está fallando: revisar categorías y modalidad antes de confiar en el orden"
