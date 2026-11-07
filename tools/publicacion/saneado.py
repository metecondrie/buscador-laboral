"""Saneado y verificación de la copia publicable del buscador.

La copia `buscador-laboral` se publica en un repositorio **privado** de GitHub.
Este módulo concentra dos responsabilidades:

1. `sanear()` — reescribe los archivos publicables quitando datos personales del
   entorno original (rutas del equipo, correo, nombre, equipo, motivo de salud).
   Es idempotente: aplicarlo dos veces no cambia nada.
2. `verificar()` — puerta de control. Devuelve la lista de hallazgos; si no está
   vacía, no se publica.

Los valores personales **no están escritos acá**: se leen de
`tools/publicacion/local.json` (excluido por `.gitignore`) o se derivan del
entorno. Este archivo se excluye a sí mismo del saneado y de la auditoría porque
contiene las reglas.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

EXTENSIONES_TEXTO = {
    ".py", ".md", ".txt", ".json", ".html", ".js", ".sql", ".cmd",
    ".toml", ".cfg", ".ini", ".yml", ".yaml",
}

#: Contiene las reglas por definición: ni se sanea ni se audita a sí mismo.
EXENTOS = {"tools/publicacion/saneado.py",
           "tools/publicacion/local.json"}

LOCAL = Path(__file__).with_name("local.json")


# --- Datos personales del entorno -------------------------------------------


def _correo_git() -> str:
    try:
        salida = subprocess.run(["git", "config", "--global", "user.email"],
                                capture_output=True, text=True).stdout.strip()
        return salida
    except OSError:
        return ""


def datos() -> dict:
    """Valores a borrar: primero local.json, después el entorno."""
    crudo: dict = {}
    try:
        if LOCAL.exists():
            leido = json.loads(LOCAL.read_text(encoding="utf-8"))
            if isinstance(leido, dict):
                crudo = leido
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        crudo = {}
    return {
        "usuario": str(crudo.get("usuario") or os.environ.get("USERNAME")
                       or Path.home().name or ""),
        "correo": str(crudo.get("correo") or _correo_git()),
        "nombre": str(crudo.get("nombre") or ""),
        "equipo": str(crudo.get("equipo") or ""),
        "bandas": crudo.get("bandas") or {},
    }


def _sustituciones(quien: dict) -> list[tuple[str, str]]:
    reglas: list[tuple[str, str]] = [
        (r"C:\\Users\\" + r"[^\\\"]+", "%USERPROFILE%"),
        (r"C:/Users/" + r"[^/\"]+", "%USERPROFILE%"),
        (r"\bDESKTOP-[A-Z0-9]{7}\b", "<equipo-local>"),
    ]
    if quien["usuario"]:
        # Rutas del equipo, con y sin la carpeta del usuario.
        reglas.insert(0, (re.escape(f"C:\\Users\\{quien['usuario']}\\AppData\\Local\\Programs"
                                    f"\\Python\\Python314"),
                          "%LOCALAPPDATA%\\Programs\\Python\\Python314"))
        reglas.insert(1, (re.escape(f"C:\\Users\\{quien['usuario']}"), "<RUTA_DEL_USUARIO>"))
        reglas.insert(2, (re.escape(f"C:/Users/{quien['usuario']}"), "<RUTA_DEL_USUARIO>"))
    if quien["correo"]:
        reglas.append((re.escape(quien["correo"]), "correo@ejemplo"))
    if quien["equipo"]:
        reglas.append((re.escape(quien["equipo"]), "<equipo-local>"))
    if quien["nombre"]:
        reglas += [
            (rf"\bMemoria-{re.escape(quien['nombre'])}\b", "la memoria personal"),
            (rf"\b{re.escape(quien['nombre'])}\b", "el usuario"),
        ]
    reglas += [
        (r"condici[oó]n de salud que impide el traslado( regular)?",
         "restricción declarada que exige remoto"),
        (r"condici[oó]n de salud", "restricción declarada"),
        (r"virtual obligatorio por salud", "remoto obligatorio por restricción declarada"),
        (r"por salud", "por una restricción declarada"),
    ]
    return reglas


def _codigo(quien: dict) -> list[tuple[str, str]]:
    bandas = quien["bandas"] or {}
    reglas = [
        # El perfil real dejó de ser una constante del repositorio.
        ("PERFIL_REAL", "PERFIL_EJEMPLO"),
        ("perfil_mod.perfil()", "perfil_mod.perfil(rutas)"),
    ]
    referencia = bandas.get("ars_referencia")
    objetivo = bandas.get("ars_objetivo")
    hora = bandas.get("usd_hora")
    if referencia:
        reglas += [
            (f'"ars_neto_referencia": {referencia}', '"ars_neto_referencia": None'),
            (f'if datos_perfil.salario else {referencia}', "if datos_perfil.salario else ''"),
            (f'"ars_referencia": "{referencia}"', '"ars_referencia": "100000"'),
        ]
    if objetivo:
        reglas += [
            (f'"ars_neto_objetivo": {objetivo}', '"ars_neto_objetivo": None'),
            (f'if datos_perfil.salario else {objetivo}', "if datos_perfil.salario else ''"),
            (f'"ars_objetivo": "{objetivo}"', '"ars_objetivo": "200000"'),
        ]
    if hora:
        reglas += [
            (f'"usd_hora_freelance": {hora},', '"usd_hora_freelance": None,'),
            (f'if datos_perfil.salario else {hora}', "if datos_perfil.salario else ''"),
            (f'"usd_hora": "{hora}"', '"usd_hora": "5"'),
        ]
    return reglas


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


def _prohibidos(quien: dict) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    contenido = [
        ("clave de Google", "AIza" + r"[0-9A-Za-z_-]{30,}"),
        ("clave tipo OpenAI", r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{20,}"),
        ("token de GitHub", "gh" + r"p_[A-Za-z0-9]{20,}"),
        ("token fine-grained", "github" + r"_pat_[A-Za-z0-9_]{20,}"),
        ("clave privada", "BEGIN [A-Z ]*" + r"PRIVATE KEY"),
        ("cualquier gmail", r"[A-Za-z0-9._%+-]+" + r"@gmail\.com"),
        ("nombre de equipo", "DESKTOP-" + r"[A-Z0-9]{7}"),
        ("dato de salud", r"condici[oó]n de " + r"salud"),
        ("banda salarial ARS", '"ars_neto_referencia": ' + r"\d"),
        ("URL con credenciales", r"https://[^/\s]+:[^/\s]+@"),
    ]
    if quien["usuario"]:
        contenido.append(("ruta del equipo", re.escape(f"C:\\Users\\{quien['usuario']}")))
    if quien["correo"]:
        contenido.append(("correo personal", re.escape(quien["correo"])))
    if quien["nombre"]:
        contenido += [
            ("nombre propio", rf"\b{re.escape(quien['nombre'])}\b"),
            ("carpeta de memoria personal", f"Memoria-{re.escape(quien['nombre'])}"),
        ]
    rutas = [
        ("base SQLite", r"\.(db|sqlite3|db-wal|db-shm)$"),
        ("archivo .env", r"(^|/)\.env$"),
        ("perfil local", r"perfil\.local\.json$"),
        ("volcado de logs", r"(^|/)logs?/|\.log$"),
    ]
    return contenido, rutas


# --- Utilidades -------------------------------------------------------------


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
    quien = datos()
    sustituciones = _sustituciones(quien)
    codigo = _codigo(quien)
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

        for viejo, nuevo in sustituciones:
            texto = re.sub(viejo, lambda _, reemplazo=nuevo: reemplazo, texto)
        for viejo, nuevo in codigo:
            texto = texto.replace(viejo, nuevo)

        if texto != original:
            _escribir(ruta, texto)
            tocados.append(_relativa(raiz, ruta))
    return tocados


def verificar(raiz: Path, rutas: list[Path] | None = None) -> list[str]:
    """Hallazgos que impiden publicar. Lista vacía = árbol limpio."""
    contenido, prohibidas = _prohibidos(datos())
    candidatas = rutas if rutas is not None else [r for r in raiz.rglob("*") if r.is_file()]
    hallazgos: list[str] = []
    for ruta in candidatas:
        relativa = _relativa(raiz, ruta)
        for etiqueta, patron in prohibidas:
            if re.search(patron, "/" + relativa):
                hallazgos.append(f"{etiqueta}: {relativa}")
                break
        if not ruta.is_file() or not _es_texto(ruta) or relativa in EXENTOS:
            continue
        for numero, linea in enumerate(_leer(ruta).splitlines(), 1):
            for etiqueta, patron in contenido:
                if re.search(patron, linea):
                    hallazgos.append(f"{etiqueta}: {relativa}:{numero}")
    return hallazgos
