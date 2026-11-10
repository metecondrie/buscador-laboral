"""Modo demostración: datos sintéticos, sin red y en una base aparte.

El buscador real necesita red para traer ofertas. Este módulo permite abrir la
interfaz y ver el circuito completo —ingesta, clasificación, puntaje, avisos—
sin conexión, sin credenciales y **sin tocar** la base operativa: escribe en
`%LOCALAPPDATA%\\BuscadorLaboral-demo` (o en `BUSCADOR_DEMO_DIR`).

Nada de lo que aparece acá es una oferta real: las empresas, los títulos y los
textos son inventados para ejercitar las reglas. La interfaz lo dice en el
encabezado cuando se abre con `--demo`.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from . import config, db, ingest, worker
from .adapters.base import Observacion, ResultadoFuente

#: Fuente sintética. Se usa F01 porque está sembrada y su dominio es propio; los
#: avisos no salen de ningún endpoint.
FUENTE_DEMO = "F01"

#: Ofertas de ejemplo. Cubren los casos que la interfaz necesita mostrar:
#: elegible, dudosa por idioma, dudosa por formación, incompatible por territorio
#: y por modalidad, y una con vigencia sin confirmar.
OFERTAS_DEMO: tuple[dict, ...] = (
    {
        "id": "demo-001",
        "titulo": "Data Analyst",
        "empresa": "Empresa de ejemplo Uno",
        "region": "Anywhere in the World",
        "publicado_en": "2026-11-08T10:00:00Z",
        "texto": (
            "We are looking for a Data Analyst. SQL required. Excel required. "
            "Python required. You will build dashboards, weekly reports and KPIs "
            "for the operations team. Fully remote, open to applicants from all "
            "countries. English B1 required. 1 year of experience."
        ),
    },
    {
        "id": "demo-002",
        "titulo": "Customer Support Specialist",
        "empresa": "Empresa de ejemplo Dos",
        "region": "Argentina",
        "publicado_en": "2026-11-07T09:00:00Z",
        "texto": (
            "Buscamos especialista de atención al cliente. Se requiere Excel y "
            "SQL. Tareas: responder tickets, actualizar el CRM y preparar reportes "
            "semanales. Modalidad remota. Nivel inicial, sin experiencia previa."
        ),
    },
    {
        "id": "demo-003",
        "titulo": "Helpdesk Agent",
        "empresa": "Empresa de ejemplo Tres",
        "region": "LATAM",
        "publicado_en": "2026-11-06T12:00:00Z",
        "texto": (
            "Helpdesk Agent for a remote team. Answer customer tickets in Zendesk, "
            "update the CRM and schedule meetings. Power BI dashboards are "
            "available for the team. Excel required. Fluent English is required."
        ),
    },
    {
        "id": "demo-004",
        "titulo": "Reporting Analyst",
        "empresa": "Empresa de ejemplo Cuatro",
        "region": "United States",
        "publicado_en": "2026-11-05T15:00:00Z",
        "texto": (
            "Reporting Analyst. SQL required. Excel required. Build monthly "
            "reports and dashboards. This is a Worldwide Remote position open to "
            "applicants from all countries."
        ),
    },
    {
        "id": "demo-005",
        "titulo": "Data Analyst",
        "empresa": "Empresa de ejemplo Cinco",
        "region": "Berlin (remote)",
        "publicado_en": "2026-11-04T08:00:00Z",
        "texto": (
            "Data Analyst. SQL required. Excel required. Hybrid, three days per "
            "week in the office in Berlin. Dashboards and reports."
        ),
    },
    {
        "id": "demo-006",
        "titulo": "Business Analyst",
        "empresa": "Empresa de ejemplo Seis",
        "region": "Anywhere in the World",
        "publicado_en": "2025-09-20T08:00:00Z",
        "texto": (
            "Business Analyst. SQL required. Excel required. Requirements, "
            "stakeholders and process mapping. Remote. A bachelor's degree is "
            "strictly required."
        ),
    },
    {
        "id": "demo-007",
        "titulo": "Paid Ads Specialist",
        "empresa": "Empresa de ejemplo Siete",
        "region": "Anywhere in the World",
        "publicado_en": "2026-11-03T11:00:00Z",
        "texto": (
            "Paid Ads Specialist. Run Meta and Google ads campaigns. Excel "
            "required for weekly reporting. Remote."
        ),
    },
    {
        "id": "demo-008",
        "titulo": "Data Entry Clerk",
        "empresa": "Empresa de ejemplo Ocho",
        "region": "Anywhere in the World",
        "publicado_en": "2026-11-02T07:00:00Z",
        "texto": (
            "Data Entry Clerk. Enter data into our systems, review records and "
            "keep files organised. Typing and Microsoft Office required. Remote."
        ),
    },
)


def rutas_demo() -> Path:
    """Raíz de la base de demostración, siempre fuera del repositorio."""
    return Path(os.environ.get("BUSCADOR_DEMO_DIR")
                or (Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
                    / f"{config.APP_NOMBRE}-demo")).resolve()


def _observaciones() -> list[Observacion]:
    return [
        Observacion(
            source_id=FUENTE_DEMO,
            external_id=oferta["id"],
            url=f"https://ejemplo.test/avisos/{oferta['id']}",
            titulo=oferta["titulo"],
            empresa=oferta["empresa"],
            descripcion_html="",
            publicado_en=oferta["publicado_en"],
            region=oferta["region"],
            extra={"texto_plano": oferta["texto"]},
            field_status={"region": "known", "salario": "unknown"},
        )
        for oferta in OFERTAS_DEMO
    ]


def preparar(root: Path | None = None, reiniciar: bool = False) -> dict:
    """Crea la base de demostración y clasifica las ofertas sintéticas.

    No consulta ninguna fuente: arma un `ResultadoFuente` en memoria y lo pasa
    por el mismo camino que una corrida real (`ingest.ingestar` + cola de
    clasificación). Así la demo ejercita el código de producción, no un atajo.
    """
    base = Path(root) if root is not None else rutas_demo()
    rutas = config.crear_estructura(base)
    if reiniciar and rutas.db.exists():
        # Sólo se borra la base de la demo, nunca un directorio completo.
        rutas.db.unlink()

    db.inicializar(rutas.db)
    conn = db.conectar(rutas.db)
    try:
        perfil = worker.asegurar_perfil(conn, rutas)
        ingest.sembrar_fuentes(conn)
        worker.sincronizar_reglas(conn, perfil["id"])
        resultado = ResultadoFuente(source_id=FUENTE_DEMO, estado="success",
                                    observaciones=_observaciones())
        stats = ingest.ingestar(conn, resultado, perfil["id"])
        epoch = uuid.uuid4().hex
        # `procesar_tareas` recibe el perfil completo (con `datos` e `id`), igual
        # que en una corrida real.
        procesadas = worker.procesar_tareas(conn, epoch, perfil=perfil)
        resumen = {
            fila["elegibilidad"]: fila["n"]
            for fila in conn.execute(
                "SELECT elegibilidad, COUNT(*) AS n FROM analyses "
                "WHERE obsoleto=0 GROUP BY elegibilidad").fetchall()
        }
        return {
            "base": str(rutas.raiz),
            "db": str(rutas.db),
            "perfil": perfil["datos"].get("origen"),
            "ofertas": len(_observaciones()),
            "nuevas": stats["nuevas"],
            "clasificadas": procesadas,
            "por_elegibilidad": resumen,
            "aviso": "datos sintéticos de demostración: no son ofertas reales",
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    """Entrada de conveniencia para `python -m buscador.demo`."""
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="buscador.demo",
                                     description="Datos sintéticos para probar sin red")
    parser.add_argument("--reiniciar", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    resultado = preparar(reiniciar=args.reiniciar)
    if args.json:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
    else:
        print(f"Base de demostración: {resultado['db']}")
        print(f"Ofertas sintéticas: {resultado['ofertas']} "
              f"(clasificadas: {resultado['clasificadas']})")
        print(f"Por elegibilidad: {resultado['por_elegibilidad']}")
        print("Abrí la interfaz con: python -m buscador demo --ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
