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

import ast
import hashlib
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
#: Variante local del contacto: la instalación operativa lo deja como valor por
#: defecto en el código (`... .strip() or "correo"`). El saneado quita el
#: fallback para que la copia publicable dependa sólo del entorno.
_CONTACTO_PERSONAL = re.compile(
    r'(_CONTACTO = os\.environ\.get\("BUSCADOR_CONTACTO", ""\)\.strip\(\))'
    r' or "[^"]*"')
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


# --- Representación saneada en memoria --------------------------------------
#
# La sincronización compara el original con la copia en este mismo espacio:
# misma normalización de saltos de línea, mismas sustituciones, misma huella
# funcional. Un parche crudo nunca puede aplicar limpio sobre un archivo que ya
# fue saneado (la copia tiene CRLF y texto anonimizado), pero la *representación*
# saneada sí es comparable. Ninguna de estas funciones escribe en disco.


def _normalizar_lineas(texto: str) -> str:
    return texto.replace("\r\n", "\n").replace("\r", "\n")


def _es_config_buscador(ruta: str) -> bool:
    return ruta.replace("\\", "/").endswith("buscador/config.py")


def sanear_texto(texto: str, ruta: str, quien: dict | None = None) -> str:
    """Devuelve la representación saneada de un contenido, sin tocar el disco.

    Es la única definición de «saneado»: `sanear()` la usa para los archivos y
    `publicar.py` para comparar versiones del original. Así no hay dos
    saneadores que puedan divergir.
    """
    q = quien if quien is not None else datos()
    resultado = _normalizar_lineas(texto)
    if _es_config_buscador(ruta):
        resultado = _UA_PERSONAL.sub(_UA_SANEADO, resultado)
        # El contacto local como valor por defecto también es dato personal.
        resultado = _CONTACTO_PERSONAL.sub(lambda m: m.group(1), resultado)
    for viejo, nuevo in _sustituciones(q):
        resultado = re.sub(viejo, lambda _, reemplazo=nuevo: reemplazo, resultado)
    for viejo, nuevo in _codigo(q):
        resultado = resultado.replace(viejo, nuevo)
    return resultado


def verificar_texto(texto: str, ruta: str, quien: dict | None = None) -> list[str]:
    """Puerta de control sobre un contenido en memoria (mismas reglas que el árbol)."""
    q = quien if quien is not None else datos()
    contenido, _ = _prohibidos(q)
    hallazgos = []
    for numero, linea in enumerate(_normalizar_lineas(texto).splitlines(), 1):
        for etiqueta, patron in contenido:
            if re.search(patron, linea):
                hallazgos.append(f"{etiqueta}: {ruta}:{numero}")
    return hallazgos


class _SinDocstrings(ast.NodeTransformer):
    """Los docstrings y comentarios no cambian lo que el programa ejecuta."""

    def _limpiar(self, nodo):
        self.generic_visit(nodo)
        cuerpo = getattr(nodo, "body", None)
        if cuerpo and isinstance(cuerpo, list):
            while cuerpo and isinstance(cuerpo[0], ast.Expr) \
                    and isinstance(cuerpo[0].value, ast.Constant) \
                    and isinstance(cuerpo[0].value.value, str):
                cuerpo.pop(0)
        return nodo

    visit_Module = _limpiar
    visit_ClassDef = _limpiar
    visit_FunctionDef = _limpiar
    visit_AsyncFunctionDef = _limpiar


def huella_funcional(texto: str, ruta: str) -> str:
    """Huella de lo ejecutable. Comentarios, docstrings y saltos no cuentan.

    Permite distinguir «el saneador cambió una frase» de «cambió una función».
    Si el Python no se puede parsear devuelve una huella inválida: la
    sincronización la trata como conflicto en lugar de darla por buena.
    """
    limpio = _normalizar_lineas(texto)
    if ruta.endswith(".py"):
        try:
            arbol = _SinDocstrings().visit(ast.parse(limpio))
            return hashlib.sha256(ast.dump(arbol, include_attributes=False)
                                  .encode("utf-8")).hexdigest()
        except (SyntaxError, ValueError):
            return "!no-parsea"
    return hashlib.sha256(limpio.encode("utf-8")).hexdigest()


def clasificar_cambio(base: str, head: str, ruta: str,
                      quien: dict | None = None) -> dict:
    """Compara dos versiones del original en representación saneada.

    - `crudo_difiere`: cambió el archivo en el original.
    - `saneado_difiere`: cambió lo que se publicaría.
    - `funcional`: cambió lo que el código ejecuta (no sólo texto anónimo).
    - `equivalente`: el cambio crudo desaparece al sanear y no es funcional;
      no hay nada que aplicar, pero el archivo **sigue sincronizado**, no se
      excluye de la copia.
    """
    q = quien if quien is not None else datos()
    s_base = sanear_texto(base, ruta, q)
    s_head = sanear_texto(head, ruta, q)
    h_base = huella_funcional(s_base, ruta)
    h_head = huella_funcional(s_head, ruta)
    valida = not h_base.startswith("!") and not h_head.startswith("!")
    funcional = (h_base != h_head) if valida else None
    return {
        "ruta": ruta,
        "crudo_difiere": _normalizar_lineas(base) != _normalizar_lineas(head),
        "saneado_base": s_base,
        "saneado_head": s_head,
        "saneado_difiere": s_base != s_head,
        "funcional": funcional,
        "valida": valida,
        "equivalente": (base != head and s_base == s_head
                        and funcional is False and valida),
    }


# --- Utilidades -------------------------------------------------------------


def _es_texto(ruta: Path) -> bool:
    return ruta.suffix.lower() in EXTENSIONES_TEXTO or ruta.name == ".gitignore"


def _relativa(raiz: Path, ruta: Path) -> str:
    return str(ruta.relative_to(raiz)).replace("\\", "/")


def _leer(ruta: Path) -> str:
    # `Path.read_text(newline=...)` recién existe desde Python 3.13 y el README
    # promete 3.10+: con `open` la lectura es idéntica en toda la banda soportada
    # y conserva los CRLF del archivo (si se normalizaran, el saneado no sería
    # idempotente ni detectable por hash).
    with open(ruta, encoding="utf-8", newline="") as manejador:
        return manejador.read()


def _escribir(ruta: Path, texto: str) -> None:
    with open(ruta, "w", encoding="utf-8", newline="") as manejador:
        manejador.write(texto)


#: Nombres públicos: `publicar.py` también necesita leer y escribir conservando
#: los saltos de línea originales del archivo.
leer_texto = _leer
escribir_texto = _escribir


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
    tocados: list[str] = []
    for ruta in (rutas if rutas is not None else archivos(raiz)):
        if not ruta.is_file() or not _es_texto(ruta):
            continue
        relativa = _relativa(raiz, ruta)
        if relativa in EXENTOS:
            continue
        original = _leer(ruta)
        texto = sanear_texto(original, relativa, quien)
        # La comparación en memoria normaliza saltos, pero el archivo conserva
        # su estilo: cambiar 133 archivos de CRLF a LF no aporta nada y ensucia
        # el diff. `core.autocrlf=true` ya guarda LF en el índice.
        if "\r\n" in original:
            texto = texto.replace("\n", "\r\n")
        if texto != original:
            _escribir(ruta, texto)
            tocados.append(relativa)
    return tocados


def verificar(raiz: Path, rutas: list[Path] | None = None) -> list[str]:
    """Hallazgos que impiden publicar. Lista vacía = árbol limpio."""
    quien = datos()
    _, prohibidas = _prohibidos(quien)
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
        hallazgos.extend(verificar_texto(_leer(ruta), relativa, quien))
    return hallazgos
