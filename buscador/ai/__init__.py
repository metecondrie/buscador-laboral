"""Capa de IA del buscador laboral.

Diseño: **USD 0 por defecto**. La cascada usa modelos con cuota gratuita
(Gemini Flash-Lite/Flash, Groq GPT-OSS, Cloudflare Workers AI). DeepSeek queda
como último recurso y sólo se activa con autorización explícita de gasto.

La IA es opcional: el rastreador, las reglas deterministas y la interfaz
funcionan completos sin ella. Su salida es una segunda opinión con evidencia
citada, nunca un reemplazo de las restricciones obligatorias.
"""

from . import analisis, cache, cola, credenciales, cuotas
from .cliente import (Candidato, Cliente, Politica, Rechazo, SinCuota,
                      catalogo_para_ui, estado, fijar_limite, periodo,
                      presupuesto, transporte_http)
from .esquema import AnalisisIA, Evidencia
from .proveedores import (CASCADA_POR_DEFECTO, PROVEEDORES, Modelo, Proveedor,
                          catalogo, obtener, parsear)

__all__ = [
    "AnalisisIA",
    "CASCADA_POR_DEFECTO",
    "Candidato",
    "Cliente",
    "Evidencia",
    "Modelo",
    "Politica",
    "PROVEEDORES",
    "Proveedor",
    "Rechazo",
    "SinCuota",
    "analisis",
    "cache",
    "catalogo",
    "catalogo_para_ui",
    "cola",
    "credenciales",
    "cuotas",
    "estado",
    "fijar_limite",
    "obtener",
    "parsear",
    "periodo",
    "presupuesto",
    "transporte_http",
]
