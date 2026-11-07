"""Esquema de la respuesta de IA y armado del prompt.

La IA devuelve un JSON validado con Pydantic. Si no valida, se descarta la
respuesta y se reintenta con otro modelo: nunca se aplica a medias.

Regla dura: la IA **no puede** anular una restricción obligatoria del motor de
reglas (territorio, modalidad, seniority excluyente) sin una cita textual del
aviso. El campo `evidencia` es obligatorio y se contrasta contra el texto.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..rules import CATEGORIAS

Niveles = Literal["trainee", "junior", "semi_senior", "senior", "manager", "desconocido"]
Modalidades = Literal["remote", "hybrid", "onsite", "desconocida"]
Territorios = Literal["argentina", "latam", "mundial", "restringida", "desconocida"]


class Evidencia(BaseModel):
    campo: str = Field(min_length=1, max_length=60)
    cita: str = Field(min_length=3, max_length=400)


class SalarioIA(BaseModel):
    minimo: float | None = None
    maximo: float | None = None
    moneda: str | None = None
    periodo: Literal["hour", "day", "month", "year", "desconocido"] = "desconocido"


class AnalisisIA(BaseModel):
    categoria: str | None = None
    seniority: Niveles = "desconocido"
    habilidades_obligatorias: list[str] = Field(default_factory=list, max_length=30)
    habilidades_deseables: list[str] = Field(default_factory=list, max_length=30)
    anios_experiencia: int | None = Field(default=None, ge=0, le=40)
    idiomas: list[str] = Field(default_factory=list, max_length=10)
    elegibilidad_territorial: Territorios = "desconocida"
    paises_restringidos: list[str] = Field(default_factory=list, max_length=20)
    modalidad: Modalidades = "desconocida"
    salario: SalarioIA | None = None
    evidencia: list[Evidencia] = Field(min_length=1, max_length=20)
    incertidumbres: list[str] = Field(default_factory=list, max_length=15)
    explicacion: str = Field(min_length=10, max_length=900)
    confianza: float = Field(ge=0.0, le=1.0)

    @field_validator("categoria")
    @classmethod
    def categoria_valida(cls, valor: str | None) -> str | None:
        if valor is None or valor == "":
            return None
        for categoria in CATEGORIAS:
            if valor.strip().lower() == categoria.lower():
                return categoria
        return None

    @field_validator("habilidades_obligatorias", "habilidades_deseables", "idiomas")
    @classmethod
    def limpiar_listas(cls, valores: list[str]) -> list[str]:
        limpios = []
        for valor in valores:
            texto = str(valor).strip()[:60]
            if texto and texto.lower() not in {v.lower() for v in limpios}:
                limpios.append(texto)
        return limpios


INSTRUCCION = """Sos un analista que extrae datos de avisos laborales para una persona \
que vive en Argentina y sólo puede trabajar en remoto.

Devolvés EXCLUSIVAMENTE un objeto JSON válido, sin texto adicional, sin bloques \
de código y sin comentarios.

Reglas:
1. No inventes. Si un dato no está en el aviso, usá null o "desconocido".
2. Cada campo que afirmes debe tener una cita textual en "evidencia".
3. "modalidad": remote sólo si el aviso lo dice; si no dice nada, "desconocida".
4. "elegibilidad_territorial": "argentina" o "latam" o "mundial" sólo si el aviso \
lo permite explícitamente; "restringida" si exige un país que excluye Argentina; \
si no se aclara, "desconocida". No supongas que "remote" implica mundial.
5. "seniority": usá el título y los años pedidos. "manager" y "senior" no son junior.
6. "categoria" debe ser una de esta lista exacta, o null si ninguna encaja: \
{categorias}.
7. "confianza" es un número entre 0 y 1 sobre la calidad de la evidencia disponible.
8. "explicacion": máximo 60 palabras, en español rioplatense, sin adjetivos comerciales.

Formato exacto:
{{
  "categoria": null,
  "seniority": "desconocido",
  "habilidades_obligatorias": [],
  "habilidades_deseables": [],
  "anios_experiencia": null,
  "idiomas": [],
  "elegibilidad_territorial": "desconocida",
  "paises_restringidos": [],
  "modalidad": "desconocida",
  "salario": {{"minimo": null, "maximo": null, "moneda": null, "periodo": "desconocido"}},
  "evidencia": [{{"campo": "modalidad", "cita": "texto literal del aviso"}}],
  "incertidumbres": [],
  "explicacion": "texto breve",
  "confianza": 0.5
}}"""


def instruccion() -> str:
    return INSTRUCCION.format(categorias=", ".join(CATEGORIAS))


def contenido_oferta(titulo: str, empresa: str | None, region: str | None,
                     texto: str, limite: int = 6000) -> str:
    recortado = re.sub(r"\s+", " ", texto or "").strip()[:limite]
    return (
        f"TÍTULO: {titulo}\n"
        f"EMPRESA: {empresa or 'no publicada'}\n"
        f"REGIÓN DECLARADA: {region or 'no publicada'}\n"
        f"DESCRIPCIÓN:\n{recortado}"
    )


def desde_texto(crudo: str) -> AnalisisIA:
    """Parsea y valida. Acepta respuestas envueltas en ```json ... ```."""
    limpio = crudo.strip()
    if limpio.startswith("```"):
        limpio = re.sub(r"^```[a-zA-Z]*\s*", "", limpio)
        limpio = re.sub(r"\s*```$", "", limpio)
    inicio, fin = limpio.find("{"), limpio.rfind("}")
    if inicio == -1 or fin == -1:
        raise ValueError("la respuesta no contiene un objeto JSON")
    datos = json.loads(limpio[inicio:fin + 1])
    if not isinstance(datos, dict):
        raise ValueError("la raíz del JSON no es un objeto")
    return AnalisisIA.model_validate(datos)


def cita_presente(evidencia: Evidencia, texto: str) -> bool:
    """Comprueba que la cita exista de verdad en el aviso (sin distinguir forma)."""
    from ..textutil import normalizar

    cita = normalizar(evidencia.cita)
    if len(cita) < 4:
        return False
    return cita in normalizar(texto)


def evidencias_verificadas(analisis: AnalisisIA, texto: str) -> tuple[list[Evidencia], list[Evidencia]]:
    validas, invalidas = [], []
    for evidencia in analisis.evidencia:
        (validas if cita_presente(evidencia, texto) else invalidas).append(evidencia)
    return validas, invalidas
