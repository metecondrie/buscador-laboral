"""Vista de «candidatas para postularse».

Independiente de la elegibilidad estricta: reúne las ofertas que **no tienen una
barrera demostrada** y las ordena por compatibilidad, mostrando qué requisitos
están confirmados, cuáles se desconocen y qué barreras posibles quedan.

Regla que ordena todo el módulo: una categoría, experiencia o habilidad que el
motor no reconoce es **información faltante**, no un requisito incumplido. Por
eso las candidatas incluyen ofertas con categoría desconocida; lo que nunca
incluyen es una barrera demostrada (territorio restringido, presencialidad,
idioma superior al perfil, seniority excluyente, título obligatorio).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from . import config

#: Efectos de una razón que cuentan como barrera posible para el revisor.
_EFECTOS_BARRERA = {"duda", "excluye"}


@dataclass
class Candidata:
    job_id: str
    titulo: str
    empresa: str | None
    fuente: str
    territorio: str | None
    modalidad: str
    vigencia: str
    categoria: str | None
    score: float | None
    confianza: str
    url: str | None
    confirmados: list[str] = field(default_factory=list)
    desconocidos: list[str] = field(default_factory=list)
    barreras: list[str] = field(default_factory=list)
    #: True cuando el alcance territorial está confirmado compatible. Se calcula
    #: desde el TIPO de la razón, no desde el texto: una frase como «la fuente
    #: restringe la ubicación a United States» no dice «territorio» en ningún lado.
    territorio_confirmado: bool = True

    def como_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "titulo": self.titulo,
            "empresa": self.empresa,
            "fuente": self.fuente,
            "territorio": self.territorio,
            "modalidad": self.modalidad,
            "vigencia": self.vigencia,
            "categoria": self.categoria,
            "score": self.score,
            "confianza": self.confianza,
            "url": self.url,
            "confirmados": self.confirmados,
            "desconocidos": self.desconocidos,
            "barreras": self.barreras,
        }


def _componentes(componentes_json: str | None) -> tuple[list[str], list[str]]:
    """(confirmados, desconocidos) a partir de los componentes guardados."""
    confirmados: list[str] = []
    desconocidos: list[str] = []
    for c in json.loads(componentes_json or "[]"):
        nombre = c.get("nombre") or "?"
        estado = c.get("estado") or ""
        detalle = (c.get("detalle") or "").strip()
        texto = f"{nombre}: {detalle}" if detalle else nombre
        if estado in {"cumplido", "parcial"}:
            confirmados.append(texto)
        elif estado == "sin_datos":
            desconocidos.append(texto)
    return confirmados, desconocidos


def _barreras(razones_json: str | None,
              incertidumbres_json: str | None) -> tuple[list[str], bool]:
    """(barreras, territorio_confirmado)."""
    barreras: list[str] = []
    territorio_ok = True
    for razon in json.loads(razones_json or "[]"):
        tipo = razon.get("tipo")
        efecto = razon.get("efecto")
        if tipo == "territorio" and efecto in _EFECTOS_BARRERA:
            territorio_ok = False
        if efecto in _EFECTOS_BARRERA and razon.get("texto"):
            barreras.append(razon["texto"])
    for texto in json.loads(incertidumbres_json or "[]"):
        if texto not in barreras:
            barreras.append(texto)
    return barreras, territorio_ok


def listar(conn: sqlite3.Connection, limite: int = 60,
           solo_territorio_confirmado: bool = True) -> list[Candidata]:
    """Candidatas ordenadas por compatibilidad y evidencia.

    `solo_territorio_confirmado` deja fuera las ofertas donde la fuente y el
    cuerpo se contradicen sobre el alcance: son revisables, pero no «candidatas»
    hasta que alguien confirme desde dónde se contrata.
    """
    filas = conn.execute(
        """SELECT j.id, j.titulo, j.empresa, j.fuente_principal, j.territorio,
                  j.modalidad, j.estado_vigencia, j.categoria, j.url_atribucion,
                  a.elegibilidad, a.score, a.confianza, a.componentes_json,
                  a.razones_json, a.incertidumbres_json
           FROM jobs j
           JOIN analyses a ON a.job_id = j.id AND a.obsoleto = 0
           WHERE j.merged_into IS NULL
             AND a.elegibilidad IN ('eligible', 'doubtful')
           ORDER BY CASE a.elegibilidad WHEN 'eligible' THEN 0 ELSE 1 END,
                    a.score DESC"""
    ).fetchall()

    candidatas: list[Candidata] = []
    for f in filas:
        confirmados, desconocidos = _componentes(f["componentes_json"])
        barreras, territorio_ok = _barreras(f["razones_json"], f["incertidumbres_json"])
        candidata = Candidata(
            job_id=f["id"], titulo=f["titulo"], empresa=f["empresa"],
            fuente=f["fuente_principal"], territorio=f["territorio"],
            modalidad=f["modalidad"] or "unknown", vigencia=f["estado_vigencia"],
            categoria=f["categoria"], score=f["score"], confianza=f["confianza"] or "",
            url=f["url_atribucion"], confirmados=confirmados,
            desconocidos=desconocidos, barreras=barreras,
            territorio_confirmado=territorio_ok,
        )
        if solo_territorio_confirmado and not candidata.territorio_confirmado:
            continue
        candidatas.append(candidata)

    # Orden: vigentes primero, luego compatibilidad, luego confianza.
    orden_confianza = {"alta": 0, "media": 1, "baja": 2}
    candidatas.sort(key=lambda c: (0 if c.vigencia == "open" else 1,
                                   -(c.score or 0),
                                   orden_confianza.get(c.confianza, 3)))
    return candidatas[:limite]


def resumen(candidatas: list[Candidata]) -> dict:
    return {
        "total": len(candidatas),
        "vigentes": sum(1 for c in candidatas if c.vigencia == "open"),
        "con_categoria": sum(1 for c in candidatas if c.categoria),
        "sin_categoria": sum(1 for c in candidatas if not c.categoria),
        "con_score": sum(1 for c in candidatas if c.score is not None),
        "reglas": config.RULES_VERSION,
    }


def texto(candidatas: list[Candidata], maximo: int = 25) -> str:
    """Listado legible para la consola."""
    lineas = [f"Candidatas para postularse · {config.RULES_VERSION}",
              f"{len(candidatas)} ofertas con territorio confirmado y sin barrera demostrada", ""]
    for indice, c in enumerate(candidatas[:maximo], start=1):
        score = f"{c.score:.1f}" if c.score is not None else "s/d"
        lineas.append(f"{indice:2}. [{score}] {c.titulo[:56]} — {c.empresa or 's/e'} "
                      f"({c.fuente}, {c.vigencia})")
        territorio = (c.territorio or "sin territorio")
        if len(territorio) > 70:
            territorio = territorio[:67] + "…"
        lineas.append(f"    {territorio} · {c.modalidad} · "
                      f"categoría {c.categoria or 'sin reconocer'}")
        if c.confirmados:
            lineas.append(f"    confirmado: {'; '.join(c.confirmados[:3])[:180]}")
        if c.desconocidos:
            lineas.append(f"    sin datos : {'; '.join(c.desconocidos[:3])[:180]}")
        if c.barreras:
            lineas.append(f"    a revisar : {'; '.join(c.barreras[:2])[:180]}")
        if c.url:
            lineas.append(f"    {c.url}")
        lineas.append("")
    if len(candidatas) > maximo:
        lineas.append(f"… y {len(candidatas) - maximo} más (usar --limite).")
    return "\n".join(lineas)
