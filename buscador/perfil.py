"""Perfil laboral de ejemplo, sin datos personales.

Este módulo **no contiene el perfil real**. El repositorio sólo publica:

- la estructura del perfil y las ponderaciones por nivel de habilidad;
- un perfil de ejemplo genérico, con el que la aplicación funciona de punta a
  punta y las pruebas corren sin datos de nadie.

El perfil real vive **fuera del repositorio**, en
``%LOCALAPPDATA%\\BuscadorLaboral\\data\\perfil.json`` (lo administra la interfaz)
o, como semilla, en ``...\\data\\perfil.local.json``. Ese archivo se mezcla sobre
el perfil de ejemplo cuando existe y está excluido por ``.gitignore``.

Qué se sacó del código publicable y por qué:

- identidad, trayectoria y proyectos concretos: datos personales;
- formación y títulos: datos personales;
- bandas salariales: datos personales pendientes de ratificación;
- el motivo de la restricción de modalidad: dato de salud.

La restricción en sí (``territorio.remoto_obligatorio``) sigue en el perfil de
ejemplo como *regla configurable*, sin explicar su causa.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

VERSION = "perfil-ejemplo-1"
ORIGEN = "sintetico_ejemplo"

NIVELES_HABILIDAD = ("demostrada", "intermedia", "basica")

#: Zona presencial de ejemplo. Se reemplaza con la del perfil local.
ZONA_EJEMPLO = "La Plata"

PERFIL_EJEMPLO: dict[str, Any] = {
    "version": VERSION,
    "origen": ORIGEN,
    "requiere_confirmacion": True,
    "nota": (
        "Perfil de ejemplo sin datos personales. El perfil real se carga desde "
        "data/perfil.local.json o desde Configuración, y vive fuera del repositorio."
    ),
    "identidad": {
        "nombre": "Perfil de ejemplo",
        "residencia": "Argentina",
        "zona_laboral": [ZONA_EJEMPLO],
        "fuente": "ejemplo",
    },
    "habilidades": [
        # Demostradas: hay un artefacto propio que las respalda.
        {"nombre": "SQL", "nivel": "demostrada",
         "evidencia": "consultas propias sobre bases relacionales"},
        {"nombre": "PostgreSQL", "nivel": "demostrada",
         "evidencia": "modelo y consultas de un proyecto propio"},
        {"nombre": "Python", "nivel": "demostrada",
         "evidencia": "scripts y automatizaciones propias"},
        {"nombre": "Power BI", "nivel": "demostrada",
         "evidencia": "tablero propio de ejemplo"},
        {"nombre": "Excel", "nivel": "demostrada",
         "evidencia": "uso sostenido en análisis propios"},
        {"nombre": "Google Sheets", "nivel": "demostrada",
         "evidencia": "automatizaciones propias sobre planillas"},
        {"nombre": "Apps Script", "nivel": "demostrada",
         "evidencia": "automatizaciones sobre Sheets"},
        {"nombre": "Git", "nivel": "demostrada",
         "evidencia": "repositorios propios, incluido este buscador"},
        {"nombre": "ETL", "nivel": "demostrada",
         "evidencia": "carga y depuración de datos de ejemplo"},
        {"nombre": "Data Visualization", "nivel": "demostrada",
         "evidencia": "tableros de ejemplo"},
        # Intermedias: se usan, sin artefacto específico que las acredite.
        {"nombre": "Statistics", "nivel": "intermedia",
         "evidencia": "formación y docencia de estadística"},
        {"nombre": "Pandas", "nivel": "intermedia", "evidencia": "análisis exploratorio propio"},
        {"nombre": "Power Query", "nivel": "intermedia", "evidencia": "preparación de datos"},
        {"nombre": "API", "nivel": "intermedia", "evidencia": "consumo de APIs en este buscador"},
        {"nombre": "Git", "nivel": "intermedia", "evidencia": "(duplicado intencional, se conserva el mayor)"},
        # Básicas: nociones, sin práctica sostenida.
        {"nombre": "Machine Learning", "nivel": "basica", "evidencia": "curso introductorio"},
        {"nombre": "Docker", "nivel": "basica", "evidencia": "uso exploratorio"},
        {"nombre": "dbt", "nivel": "basica", "evidencia": "tutoriales"},
        {"nombre": "Airflow", "nivel": "basica", "evidencia": "tutoriales"},
        {"nombre": "Tableau", "nivel": "basica", "evidencia": "exploración, sin proyectos"},
        {"nombre": "Looker Studio", "nivel": "basica", "evidencia": "exploración, sin proyectos"},
    ],
    "idioma": {"ingles": "B2", "espanol": "nativo", "fuente": "ejemplo"},
    "experiencia": {
        "anios": 1,
        "nivel": "junior",
        "detalle": (
            "Experiencia de ejemplo basada en proyectos propios, no en empleo "
            "formal en el área de datos."
        ),
        "empleos": [],
        "proyectos": [],
    },
    "formacion": [
        {"titulo": "Formación terciaria (ejemplo)", "estado": "no finalizada",
         "acreditado": False},
        {"titulo": "Curso de iniciación a Python", "estado": "completado",
         "acreditado": True},
        {"titulo": "Curso de Business Intelligence", "estado": "completado",
         "acreditado": True},
    ],
    "territorio": {
        "residencia": "Argentina",
        "remoto": True,
        "remoto_obligatorio": True,
        "presencial": [ZONA_EJEMPLO],
        "motivo": "remoto obligatorio declarado en el perfil local (sin detalle)",
        "acepta_hibrido_en_zona": True,
        "fuente": "ejemplo",
    },
    "categorias": [
        "Data Analyst",
        "Business Analyst",
        "BI Analyst",
        "Reporting Analyst",
        "SQL Analyst",
        "Data Operations",
        "Research Analyst",
        "VA/Data Entry",
        "Customer Support",
    ],
    "salario": {
        "ars_neto_referencia": None,
        "ars_neto_objetivo": None,
        "usd_hora_freelance": None,
        "estado": "pendiente_ratificacion",
        "nota": "sin valores en el repositorio: se cargan en el perfil local",
    },
    "disponibilidad": {"desde": "inmediata", "horas_semana": 40, "estado": "ejemplo"},
    "restricciones": {
        "sin_gastos_sin_autorizacion": True,
        "no_postular_automaticamente": True,
        "ingles": "intermedio (B2)",
    },
}


def _fusionar(base: dict[str, Any], encima: dict[str, Any]) -> dict[str, Any]:
    """Mezcla recursiva: los diccionarios se combinan, el resto se reemplaza."""
    for clave, valor in encima.items():
        if isinstance(valor, dict) and isinstance(base.get(clave), dict):
            _fusionar(base[clave], valor)
        else:
            base[clave] = copy.deepcopy(valor)
    return base


def ruta_local(rutas: Any | None = None) -> Path:
    """Archivo de semilla del perfil real, fuera del repositorio."""
    from . import config

    return (rutas or config.rutas()).perfil_local


def perfil(rutas: Any | None = None) -> dict:
    """Perfil de ejemplo, con el perfil local mezclado encima si existe."""
    datos = copy.deepcopy(PERFIL_EJEMPLO)
    ruta = ruta_local(rutas)
    try:
        if ruta.exists():
            local = json.loads(ruta.read_text(encoding="utf-8"))
            if isinstance(local, dict):
                datos = _fusionar(datos, local)
                datos["origen"] = local.get("origen") or "perfil-local"
                datos["requiere_confirmacion"] = bool(local.get("requiere_confirmacion", False))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass
    return datos


def peso_habilidad(nivel: str | None) -> float:
    """Peso de una habilidad según su nivel. Desconocido no es cero, es 0,5."""
    return {"demostrada": 1.0, "intermedia": 0.7, "basica": 0.4}.get((nivel or "").lower(), 0.5)
