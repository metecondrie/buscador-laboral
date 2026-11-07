"""Saneado y verificación de la copia publicable del buscador.

La copia `buscador-laboral` se publica en un repositorio **privado** de GitHub.
Este módulo concentra dos responsabilidades:

1. `sanear()` — reescribe los archivos publicables quitando datos personales del
   entorno original (rutas del equipo, correo, nombre, equipo, motivo de salud).
   Es idempotente: aplicarlo dos veces no cambia nada.
2. `verificar()` — puerta de control. Devuelve la lista de hallazgos; si no está
   vacía, no se publica.

Los patrones se arman por concatenación y este archivo queda excluido de ambos
pasos: es el que contiene las reglas, no un archivo a sanear.
"""

from __future__ import annotations

import re
from pathlib import Path

EXTENSIONES_TEXTO = {
    ".py", ".md", ".txt", ".json", ".html", ".js", ".sql", ".cmd",
    ".toml", ".cfg", ".ini", ".yml", ".yaml",
}

#: Contiene las reglas por definición: ni se sanea ni se audita a sí mismo.
EXENTOS = {"tools/publicacion/saneado.py"}

# --- Datos personales: se reemplazan por marcadores -------------------------

_SUSTITUCIONES: list[tuple[str, str]] = [
    # Rutas del equipo.
    (r"C:\\Users\\alele\\WorkBuddy AI\\buscad0r", "<RUTA_DEL_PROYECTO>"),
    (r"C:/Users/alele/WorkBuddy AI/buscad0r", "<RUTA_DEL_PROYECTO>"),
    (r"C:\\Users\\alele\\AppData\\Local\\Programs\\Python\\Python314",
     "%LOCALAPPDATA%\\Programs\\Python\\Python314"),
    (r"C:\\Users\\alele\\AppData", "%LOCALAPPDATA%"),
    (r"C:\\Users\\alele", "<RUTA_DEL_USUARIO>"),
    (r"C:/Users/alele", "<RUTA_DEL_USUARIO>"),
    # Equipo y correo.
    (r"\bDESKTOP-[A-Z0-9]{7}\b", "<equipo-local>"),
    (r"alejoongaro" + r"@gmail\.com", "correo@ejemplo"),
    # Nombre propio y carpetas de memoria personal.
    (r"\bMemoria-Alejo\b", "la memoria personal"),
    (r"\bAlejo\b", "el usuario"),
    (r"\balejo\b", "el usuario"),
    # Motivo de la restricción de modalidad (dato de salud).
    (r"condici[oó]n de salud que impide el traslado( regular)?",
     "restricción declarada que exige remoto"),
    (r"condici[oó]n de salud", "restricción declarada"),
    (r"virtual obligatorio por salud", "remoto obligatorio por restricción declarada"),
    (r"por salud", "por una restricción declarada"),
]

# --- Reemplazos de código que dependen del perfil saneado -------------------

_CODIGO: list[tuple[str, str]] = [
    # El perfil real dejó de ser una constante del repositorio.
    ("PERFIL_REAL", "PERFIL_EJEMPLO"),
    ("perfil_mod.perfil()", "perfil_mod.perfil(rutas)"),
    # Bandas salariales: se cargan en el perfil local.
    ('"ars_neto_referencia": 750000', '"ars_neto_referencia": None'),
    ('"ars_neto_objetivo": 900000', '"ars_neto_objetivo": None'),
    ('"usd_hora_freelance": 10,', '"usd_hora_freelance": None,'),
    # Valores de formulario: sin bandas personales por defecto.
    ('if datos_perfil.salario else 750000', "if datos_perfil.salario else ''"),
    ('if datos_perfil.salario else 900000', "if datos_perfil.salario else ''"),
    ('if datos_perfil.salario else 10', "if datos_perfil.salario else ''"),
    ('"ars_referencia": "750000"', '"ars_referencia": "100000"'),
    ('"ars_objetivo": "900000"', '"ars_objetivo": "200000"'),
    ('"usd_hora": "10"', '"usd_hora": "5"'),
]

_UA_PERSONAL = re.compile(
    r'USER_AGENT = "BuscadorLaboral/0\.2 \(prototipo local; contacto: [^"]*\)"'
)
_UA_SANEADO = (
    "# User agent identificable y atribución exigida por las fuentes.\n"
    "# El contacto es opcional y se define en el entorno: BUSCADOR_CONTACTO.\n"
    '_CONTACTO = os.environ.get("BUSCADOR_CONTACTO", "").strip()\n'
    'USER_AGENT = "BuscadorLaboral/0.2 (prototipo local"\n'
    "if _CONTACTO:\n"
    '    USER_AGENT += f"; contacto: {_CONTACTO}"\n'
    'USER_AGENT += ")"'
)

# --- Patrones prohibidos en la copia publicable -----------------------------

_PROHIBIDOS_CONTENIDO: list[tuple[str, str]] = [
    ("clave de Google", "AIza" + r"[0-9A-Za-z_-]{30,}"),
    ("clave tipo OpenAI", r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{20,}"),
    ("token de GitHub", "gh" + r"p_[A-Za-z0-9]{20,}"),
    ("token fine-grained", "github" + r"_pat_[A-Za-z0-9_]{20,}"),
    ("clave privada", "BEGIN [A-Z ]*" + r"PRIVATE KEY"),
    ("correo personal", "alejoongaro" + r"@gmail\.com"),
    ("cualquier gmail", r"[A-Za-z0-9._%+-]+" + r"@gmail\.com"),
    ("ruta del equipo", r"C:\\Users\\" + r"alele"),
    ("nombre de equipo", r"DESKTOP-" + r"[A-Z0-9]{7}"),
    ("nombre propio", r"\b" + "Alejo" + r"\b"),
    ("carpeta de memoria personal", "Memoria" + r"-Alejo"),
    ("dato de salud", r"condici[oó]n de " + r"salud"),
    ("banda salarial ARS", '"ars_neto_referencia": ' + r"\d"),
    ("URL con credenciales", r"https://[^/\s]+:[^/\s]+@"),
]

_PROHIBIDOS_RUTA: list[tuple[str, str]] = [
    ("base SQLite", r"\.(db|sqlite3|db-wal|db-shm)$"),
    ("archivo .env", r"(^|/)\.env$"),
    ("perfil local", r"perfil\.local\.json$"),
    ("volcado de logs", r"(^|/)logs?/|\.log$"),
]


def _es_texto(ruta: Path) -> bool:
    return ruta.suffix.lower() in EXTENSIONES_TEXTO or ruta.name == ".gitignore"


def _relativa(raiz: Path, ruta: Path) -> str:
    return str(ruta.relative_to(raiz)).replace("\\", "/")


def _leer(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8", newline="")


def _escribir(ruta: Path, texto: str) -> None:
    ruta.write_text(texto, encoding="utf-8", newline="")


def archivos(raiz: Path) -> list[Path]:
    """Todos los archivos de texto del árbol, sin .git ni cachés."""
    salida: list[Path] = []
    for ruta in sorted(raiz.rglob("*")):
        if not ruta.is_file() or not _es_texto(ruta):
            continue
        partes = set(ruta.relative_to(raiz).parts)
        if partes & {".git", "__pycache__", ".pytest_cache", ".venv"}:
            continue
        salida.append(ruta)
    return salida


def sanear(raiz: Path, rutas: list[Path] | None = None) -> list[str]:
    """Aplica las sustituciones. Devuelve los archivos modificados."""
    tocados: list[str] = []
    for ruta in (rutas if rutas is not None else archivos(raiz)):
        if not ruta.is_file() or not _es_texto(ruta):
            continue
        if _relativa(raiz, ruta) in EXENTOS:
            continue
        original = _leer(ruta)
        texto = original

        if ruta.name == "config.py" and "buscador" in str(ruta):
            texto = _UA_PERSONAL.sub(_UA_SANEADO, texto)

        for viejo, nuevo in _SUSTITUCIONES:
            texto = re.sub(viejo, lambda _, reemplazo=nuevo: reemplazo, texto)
        for viejo, nuevo in _CODIGO:
            texto = texto.replace(viejo, nuevo)

        if texto != original:
            _escribir(ruta, texto)
            tocados.append(_relativa(raiz, ruta))
    return tocados


def verificar(raiz: Path, rutas: list[Path] | None = None) -> list[str]:
    """Hallazgos que impiden publicar. Lista vacía = árbol limpio."""
    hallazgos: list[str] = []
    for ruta in (rutas if rutas is not None else archivos(raiz)):
        relativa = _relativa(raiz, ruta)
        for etiqueta, patron in _PROHIBIDOS_RUTA:
            if re.search(patron, "/" + relativa):
                hallazgos.append(f"{etiqueta}: {relativa}")
                break
        if not ruta.is_file() or not _es_texto(ruta) or relativa in EXENTOS:
            continue
        for numero, linea in enumerate(_leer(ruta).splitlines(), 1):
            for etiqueta, patron in _PROHIBIDOS_CONTENIDO:
                if re.search(patron, linea):
                    hallazgos.append(f"{etiqueta}: {relativa}:{numero}")
    return hallazgos
