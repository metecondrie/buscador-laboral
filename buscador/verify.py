"""Verificación de fuentes contra su respuesta real.

No simula: descarga cada fuente una vez, normaliza el lote y evalúa con las
reglas activas para estimar cuántas oportunidades aportan a **este** perfil.
El resultado se guarda en `source_verifications` y se puede exportar como
evidencia reproducible.

Criterio de aceptación de una fuente (documentado, no maquillado):

- responde con estado `success`;
- al menos un aviso se normaliza con título, empresa o región y URL;
- el porcentaje de avisos compatibles con las categorías del perfil se reporta
  tal cual, aunque sea bajo. Una fuente con 0 relevantes no se descarta sola:
  queda registrada como de bajo rendimiento.
"""

from __future__ import annotations

import json
import sqlite3
import time

from . import adapters, config, db, rules, worker
from .adapters.base import Observacion, ResultadoFuente


def _oferta_desde_observacion(obs: Observacion) -> dict:
    return {
        "titulo": obs.titulo,
        "empresa": obs.empresa,
        "region": obs.region,
        "texto": obs.extra.get("texto_plano") or "",
        "seniority": obs.seniority,
        "salario": obs.salario,
        "publicado_en": obs.publicado_en,
        "tipo_contrato": obs.categoria_fuente,
    }


def verificar_adaptador(source_id: str, limite: int, perfil: dict) -> dict:
    adaptador = adapters.obtener(source_id)
    inicio = time.perf_counter()
    try:
        resultado = worker.recolectar(adaptador, limite)
    except Exception as exc:  # noqa: BLE001 - se reporta como fallo de la fuente
        resultado = ResultadoFuente(
            source_id=source_id, estado="network_error", error_code="network_error",
            error_msg=f"excepción no controlada: {exc!r}",
        )
    duracion = round((time.perf_counter() - inicio) * 1000, 1)

    evaluaciones = []
    for obs in resultado.observaciones:
        evaluacion = rules.evaluar(_oferta_desde_observacion(obs), perfil)
        evaluaciones.append((obs, evaluacion))

    relevantes = [e for e in evaluaciones if e[1].elegibilidad in {"eligible", "doubtful"}]
    elegibles = [e for e in evaluaciones if e[1].elegibilidad == "eligible"]
    incompatibles = [e for e in evaluaciones if e[1].elegibilidad == "incompatible"]
    con_empresa = sum(1 for o, _ in evaluaciones if o.empresa)
    con_region = sum(1 for o, _ in evaluaciones if o.region)
    con_salario = sum(1 for o, _ in evaluaciones if o.salario)
    categorias: dict[str, int] = {}
    for _, evaluacion in relevantes:
        if evaluacion.categoria:
            categorias[evaluacion.categoria] = categorias.get(evaluacion.categoria, 0) + 1

    aceptada = (
        resultado.estado in {"success", "partial"}
        and len(resultado.observaciones) > 0
        and con_empresa + con_region > 0
    )
    return {
        "source_id": source_id,
        "nombre": adaptador.nombre,
        "metodo": adaptador.metodo,
        "endpoint": adaptador.endpoint,
        "parser_version": adaptador.parser_version,
        "estado": resultado.estado,
        "http_status": resultado.http_status,
        "aceptada": aceptada,
        "observaciones": len(resultado.observaciones),
        "relevantes": len(relevantes),
        "elegibles": len(elegibles),
        "incompatibles": len(incompatibles),
        "porcentaje_relevante": round(100 * len(relevantes) / len(evaluaciones), 1) if evaluaciones else 0.0,
        "con_empresa": con_empresa,
        "con_region": con_region,
        "con_salario": con_salario,
        "categorias": dict(sorted(categorias.items(), key=lambda par: -par[1])),
        "muestra": [
            {
                "titulo": obs.titulo[:120],
                "empresa": obs.empresa,
                "region": obs.region,
                "categoria": evaluacion.categoria,
                "elegibilidad": evaluacion.elegibilidad,
                "score": evaluacion.score,
                "url": obs.url,
            }
            for obs, evaluacion in relevantes[:5]
        ],
        "error": resultado.error_msg,
        "duracion_ms": duracion,
        "particiones": resultado.detalle.get("particiones"),
    }


def verificar_todas(conn: sqlite3.Connection, limite: int = 20,
                    solo: list[str] | None = None) -> dict:
    perfil = worker.asegurar_perfil(conn, config.crear_estructura())
    filas = []
    for meta in adapters.metadatos():
        if solo and meta["source_id"] not in solo:
            continue
        filas.append(verificar_adaptador(meta["source_id"], limite, perfil["datos"]))

    aceptadas = [f for f in filas if f["aceptada"]]
    with db.transaccion(conn):
        for fila in filas:
            conn.execute(
                """INSERT INTO source_verifications (source_id, fecha, metodo, resultado, notas, evidencia_json)
                   VALUES (?,?,?,?,?,?)""",
                (
                    fila["source_id"], config.ahora_utc(), "verificacion-automatica",
                    fila["estado"],
                    f"{fila['relevantes']}/{fila['observaciones']} relevantes",
                    json.dumps({k: v for k, v in fila.items() if k != "muestra"}, ensure_ascii=False),
                ),
            )
    return {
        "fecha": config.ahora_utc(),
        "limite_por_fuente": limite,
        "perfil": {"version": perfil["version"], "origen": perfil["datos"].get("origen")},
        "rules_version": config.RULES_VERSION,
        "fuentes": filas,
        "resumen": {
            "total": len(filas),
            "aceptadas": len(aceptadas),
            "con_relevantes": sum(1 for f in filas if f["relevantes"] > 0),
            "observaciones": sum(f["observaciones"] for f in filas),
            "relevantes": sum(f["relevantes"] for f in filas),
        },
    }
