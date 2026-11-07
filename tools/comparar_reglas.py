"""Compara las reglas anteriores con las actuales sobre el mismo corpus.

Extrae `buscador/rules.py` del commit indicado, lo carga como módulo aparte y
evalúa las mismas ofertas dos veces:

- antes: reglas 1.1.0 con el perfil de demostración;
- después: reglas 2.0.0 con el perfil real.

No escribe nada: sólo informa. Sirve para documentar qué se ganó y qué se perdió
al endurecer el ranking.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from buscador import rules as reglas_nuevas  # noqa: E402
from buscador.perfil import PERFIL_EJEMPLO  # noqa: E402
from buscador.textutil import html_a_texto  # noqa: E402
from buscador.worker import PERFIL_DEMO  # noqa: E402


def cargar_reglas(commit: str = "a271702"):
    fuente = subprocess.run(
        ["git", "show", f"{commit}:buscador/rules.py"],
        cwd=RAIZ, capture_output=True, text=True, check=True,
    ).stdout
    fuente = fuente.replace("from .config import", "from buscador.config import")
    fuente = fuente.replace("from .textutil import", "from buscador.textutil import")
    archivo = Path(tempfile.gettempdir()) / f"rules_{commit}.py"
    archivo.write_text(fuente, encoding="utf-8")
    especificacion = importlib.util.spec_from_file_location(f"rules_{commit}", archivo)
    modulo = importlib.util.module_from_spec(especificacion)
    sys.modules[especificacion.name] = modulo  # dataclasses necesita el módulo registrado
    especificacion.loader.exec_module(modulo)
    return modulo


def ofertas(conn: sqlite3.Connection) -> list[dict]:
    filas = conn.execute(
        """SELECT j.id, j.titulo, j.empresa, j.territorio, j.publicado_en, j.salario_json,
                  j.fuente_principal,
                  (SELECT o.descripcion_texto FROM observations o
                     JOIN job_observations jo ON jo.observation_id=o.id
                    WHERE jo.job_id=j.id ORDER BY o.detectado_en DESC LIMIT 1) AS texto,
                  (SELECT o.seniority FROM observations o
                     JOIN job_observations jo ON jo.observation_id=o.id
                    WHERE jo.job_id=j.id ORDER BY o.detectado_en DESC LIMIT 1) AS seniority,
                  (SELECT o.categoria_fuente FROM observations o
                     JOIN job_observations jo ON jo.observation_id=o.id
                    WHERE jo.job_id=j.id ORDER BY o.detectado_en DESC LIMIT 1) AS categoria
           FROM jobs j WHERE j.merged_into IS NULL"""
    ).fetchall()
    salida = []
    for fila in filas:
        datos = dict(fila)
        datos["texto"] = html_a_texto(datos.get("texto") or "")
        datos["region"] = datos.pop("territorio")
        datos["salario"] = json.loads(datos["salario_json"]) if datos.get("salario_json") else None
        datos["tipo_contrato"] = datos.get("categoria")
        salida.append(datos)
    return salida


def main() -> int:
    ruta = Path(os.environ["LOCALAPPDATA"]) / "BuscadorLaboral" / "data" / "buscador.db"
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    filas = ofertas(conn)
    antiguas = cargar_reglas()

    resumen = {"total": len(filas), "antes": {}, "despues": {}, "cambios": {}}
    perdidas, ganadas = [], []

    for oferta in filas:
        previa = antiguas.evaluar(oferta, PERFIL_DEMO)
        actual = reglas_nuevas.evaluar(oferta, PERFIL_EJEMPLO)
        for etiqueta, evaluacion, destino in (
            ("antes", previa, resumen["antes"]),
            ("despues", actual, resumen["despues"]),
        ):
            destino[evaluacion.elegibilidad] = destino.get(evaluacion.elegibilidad, 0) + 1

        antes_relevante = previa.elegibilidad in {"eligible", "doubtful"}
        ahora_relevante = actual.elegibilidad in {"eligible", "doubtful"}
        if antes_relevante and not ahora_relevante:
            perdidas.append({
                "titulo": oferta["titulo"], "empresa": oferta["empresa"],
                "motivo_antes": "elegible/dudosa",
                "motivo_ahora": actual.motivo_elegibilidad,
                "score_antes": previa.score,
            })
        elif ahora_relevante and not antes_relevante:
            ganadas.append({"titulo": oferta["titulo"], "motivo": actual.motivo_elegibilidad})

    resumen["cambios"] = {"dejaron_de_ser_relevantes": len(perdidas), "pasaron_a_relevantes": len(ganadas)}
    resumen["ejemplos_perdidas"] = perdidas[:12]
    resumen["ejemplos_ganadas"] = ganadas[:8]

    print(json.dumps(resumen, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
