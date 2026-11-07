"""Publica la copia saneada del buscador en el repositorio privado de GitHub.

Uso habitual (lo corre el agente o vos a mano):

    py -3 tools/publicar.py estado        # diagnóstico, no modifica nada
    py -3 tools/publicar.py sincronizar   # trae commits nuevos del original, verifica y publica
    py -3 tools/publicar.py verificar     # saneado + pruebas, sin commit ni push

Reglas que implementa:

- Sólo se sincroniza **lo commiteado** en el proyecto original: si otra sesión
  tiene archivos sucios, no se copian (se informan).
- El diff se aplica por archivo. Si un archivo de código no aplica limpio, se
  aborta entero y no se publica nada. Si es documentación, se toma la versión
  del original y se vuelve a sanear.
- `tools/publicacion/saneado.py` decide qué se reemplaza y qué está prohibido.
- Nunca usa `--force`, nunca cambia la visibilidad del repositorio y nunca
  toca el repositorio original.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ_COPIA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from publicacion import saneado  # noqa: E402

ORIGINAL = Path(os.environ.get("BUSCADOR_ORIGINAL")
                 or Path.home() / "WorkBuddy AI" / "buscad0r")
REGISTRO = RAIZ_COPIA / "docs" / "publicacion" / "estado.json"
REMOTO = "origin"
RAMA = "main"

#: Archivos que la copia no recibe del original: tienen versión saneada propia.
NO_SINCRONIZAR = {
    "buscador/perfil.py",  # el perfil real no se publica
    "README.md",           # instrucciones propias de la copia publicable
    "docs/sincronizacion-github.md",
    "tools/publicar.py",
    "tools/publicacion/saneado.py",
    "tools/publicacion/__init__.py",
    "docs/publicacion/estado.json",
    "tests/test_publicacion.py",
}


def git(*args: str, cwd: Path | None = None, texto: bool = True) -> str:
    resultado = subprocess.run(
        ["git", *args], cwd=str(cwd or RAIZ_COPIA), capture_output=True,
        text=texto, check=False,
    )
    if resultado.returncode != 0:
        salida = resultado.stderr if texto else resultado.stderr.decode("utf-8", "replace")
        raise RuntimeError(f"git {' '.join(args)} falló: {salida.strip()}")
    return resultado.stdout


def git_ok(*args: str, cwd: Path | None = None) -> bool:
    return subprocess.run(["git", *args], cwd=str(cwd or RAIZ_COPIA),
                          capture_output=True).returncode == 0


def leer_registro() -> dict:
    if REGISTRO.exists():
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    return {"base_original": "", "publicaciones": []}


def escribir_registro(datos: dict) -> None:
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    REGISTRO.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")


def publicables() -> list[Path]:
    """Archivos que Git incluiría: versionados + nuevos no ignorados."""
    listado = git("ls-files", "--cached", "--others", "--exclude-standard")
    rutas: list[Path] = []
    for linea in listado.splitlines():
        if linea.strip():
            rutas.append(RAIZ_COPIA / linea.strip())
    return rutas


def python_pruebas() -> str:
    candidatos = [
        os.environ.get("BUSCADOR_PYTHON"),
        str(RAIZ_COPIA / ".venv" / "Scripts" / "python.exe"),
        str(ORIGINAL / ".venv" / "Scripts" / "python.exe"),
        sys.executable,
    ]
    for candidato in candidatos:
        if not candidato or not Path(candidato).exists():
            continue
        prueba = subprocess.run([candidato, "-m", "pytest", "--version"],
                                capture_output=True, text=True)
        if prueba.returncode == 0:
            return candidato
    raise RuntimeError("no encontré un Python con pytest; definí BUSCADOR_PYTHON")


def correr_pruebas() -> tuple[bool, str]:
    interprete = python_pruebas()
    entorno = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    resultado = subprocess.run(
        [interprete, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=str(RAIZ_COPIA), capture_output=True, text=True, env=entorno,
    )
    resumen = (resultado.stdout or "").strip().splitlines()
    cola = "\n".join(resumen[-3:]) if resumen else (resultado.stderr or "")[-400:]
    return resultado.returncode == 0, cola


def estado(silencioso: bool = False) -> dict:
    datos = {
        "original_head": git("rev-parse", "HEAD", cwd=ORIGINAL).strip(),
        "original_sucio": [
            linea for linea in git("status", "--porcelain", cwd=ORIGINAL).splitlines()
            if linea.strip()
        ],
        "copia_head": git("rev-parse", "HEAD").strip(),
        "copia_sucio": [l for l in git("status", "--porcelain").splitlines() if l.strip()],
        "base_registrada": leer_registro().get("base_original", ""),
    }
    if not silencioso:
        print(f"original  {datos['original_head'][:7]}  "
              f"(base registrada {datos['base_registrada'][:7] or '—'})")
        if datos["original_sucio"]:
            print(f"  sin commitear en el original ({len(datos['original_sucio'])}), "
                  f"no se sincroniza:")
            for linea in datos["original_sucio"][:8]:
                print(f"    {linea}")
        print(f"copia     {datos['copia_head'][:7]}  "
              f"({len(datos['copia_sucio'])} archivo(s) sin commitear)")
    return datos


def _aplicar(parche: str) -> bool:
    """Intenta aplicar un parche por archivo. No deja el árbol a medias."""
    if not parche.strip():
        return True
    intento = subprocess.run(["git", "apply", "--check", "-"], cwd=str(RAIZ_COPIA),
                             input=parche.encode("utf-8"), capture_output=True)
    if intento.returncode != 0:
        return False
    aplicado = subprocess.run(["git", "apply", "-"], cwd=str(RAIZ_COPIA),
                              input=parche.encode("utf-8"), capture_output=True)
    return aplicado.returncode == 0


def _restaurar(creados: list[str]) -> None:
    """Vuelve la copia al estado anterior sin tocar archivos ajenos al sync."""
    git("checkout", "--", ".")
    for ruta in creados:
        destino = RAIZ_COPIA / ruta
        if destino.exists():
            destino.unlink()


def sincronizar(sin_push: bool = False, sin_pruebas: bool = False) -> int:
    datos = estado(silencioso=True)
    base = datos["base_registrada"]
    head = datos["original_head"]

    if git("status", "--porcelain", "--untracked-files=no").strip():
        print("La copia tiene cambios sin commitear en archivos versionados. "
              "No sincronizo sobre eso.")
        return 2
    if not base:
        print("No hay base registrada en docs/publicacion/estado.json.")
        return 2
    if base == head:
        print(f"Al día: el original sigue en {head[:7]}.")
        return 0
    if not git_ok("cat-file", "-e", f"{base}^{{commit}}", cwd=ORIGINAL):
        print(f"La base {base[:7]} ya no existe en el original (historial reescrito). "
              f"Requiere revisión manual.")
        return 2

    commits = git("log", "--format=%h %s", f"{base}..{head}", cwd=ORIGINAL).splitlines()
    print(f"Sincronizando {base[:7]}..{head[:7]} ({len(commits)} commit/s):")
    for linea in commits:
        print(f"  {linea}")

    listado = git("diff", "--name-status", base, head, cwd=ORIGINAL).splitlines()
    aplicados, reemplazados, omitidos, conflictos, creados = [], [], [], [], []
    for linea in listado:
        partes = linea.split("\t")
        estado_archivo, ruta = partes[0], partes[-1]
        if ruta in NO_SINCRONIZAR:
            omitidos.append(ruta)
            continue
        parche = git("diff", base, head, "--", ruta, cwd=ORIGINAL)
        if _aplicar(parche):
            aplicados.append(ruta)
            if estado_archivo.startswith("A"):
                creados.append(ruta)
            continue
        if ruta.startswith("docs/") and estado_archivo != "D":
            contenido = git("show", f"{head}:{ruta}", cwd=ORIGINAL)
            destino = RAIZ_COPIA / ruta
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(contenido, encoding="utf-8", newline="")
            reemplazados.append(ruta)
        else:
            conflictos.append(ruta)

    if conflictos:
        _restaurar(creados)
        print("\nConflicto en archivos de código; no se publica nada:")
        for ruta in conflictos:
            print(f"  {ruta}")
        print("Resolvelo a mano en la copia y volvé a ejecutar.")
        return 2

    tocados = saneado.sanear(RAIZ_COPIA, publicables())
    if tocados:
        print(f"\nSaneado aplicado en {len(tocados)} archivo(s):")
        for ruta in tocados:
            print(f"  {ruta}")

    hallazgos = saneado.verificar(RAIZ_COPIA, publicables())
    if hallazgos:
        print("\nDatos sensibles detectados; no se publica:")
        for hallazgo in hallazgos[:20]:
            print(f"  {hallazgo}")
        if len(hallazgos) > 20:
            print(f"  … y {len(hallazgos) - 20} más")
        return 2

    if not sin_pruebas:
        print("\nPruebas…")
        bien, cola = correr_pruebas()
        print(f"  {cola}")
        if not bien:
            print("Pruebas en rojo: el trabajo queda local, no se publica.")
            return 3

    if not git("status", "--porcelain").strip():
        print("Sin cambios que publicar.")
        return 0

    mensaje = [
        f"chore(publicacion): sincroniza {base[:7]}..{head[:7]} del proyecto original",
        "",
        "Commits incorporados:",
        *(f"  - {linea}" for linea in commits),
        "",
        f"Archivos aplicados: {len(aplicados)} · reemplazados por conflicto en docs: "
        f"{len(reemplazados)} · omitidos (versión saneada propia): {len(omitidos)}",
    ]
    if reemplazados:
        mensaje += ["", "Reemplazados por la versión del original + saneado:"]
        mensaje += [f"  - {ruta}" for ruta in reemplazados]
    git("add", "-A")
    git("commit", "-q", "-m", "\n".join(mensaje))

    registro = leer_registro()
    registro["base_original"] = head
    registro.setdefault("publicaciones", []).append({
        "original_hasta": head,
        "original_desde": base,
        "commits": commits,
        "archivos": {"aplicados": aplicados, "reemplazados": reemplazados,
                     "omitidos": omitidos},
        "cuando": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    })
    escribir_registro(registro)
    git("add", str(REGISTRO.relative_to(RAIZ_COPIA)))
    git("commit", "-q", "--amend", "--no-edit")

    publicado = git("rev-parse", "HEAD").strip()
    print(f"\nCommit local: {publicado[:7]}")

    if sin_push:
        print("Push omitido (--sin-push).")
        return 0

    git("push", REMOTO, RAMA)
    git("fetch", "-q", REMOTO)
    remoto = git("rev-parse", f"{REMOTO}/{RAMA}").strip()
    if remoto != publicado:
        print(f"El remoto quedó en {remoto[:7]} y el local en {publicado[:7]}.")
        return 4
    print(f"Publicado en {REMOTO}/{RAMA} = {publicado[:7]}")
    return 0


def verificar() -> int:
    tocados = saneado.sanear(RAIZ_COPIA, publicables())
    for ruta in tocados:
        print(f"saneado: {ruta}")
    hallazgos = saneado.verificar(RAIZ_COPIA, publicables())
    for hallazgo in hallazgos:
        print(f"hallazgo: {hallazgo}")
    bien, cola = correr_pruebas()
    print(cola)
    return 0 if (bien and not hallazgos) else 1


def publicar(mensaje: str, sin_push: bool = False) -> int:
    """Publica cambios hechos en la copia: sanea, verifica, prueba y sube."""
    if not mensaje.strip():
        print("Falta el mensaje del commit (--mensaje).")
        return 2
    if not git("status", "--porcelain").strip():
        print("No hay cambios que publicar.")
        return 0

    tocados = saneado.sanear(RAIZ_COPIA, publicables())
    for ruta in tocados:
        print(f"saneado: {ruta}")

    hallazgos = saneado.verificar(RAIZ_COPIA, publicables())
    if hallazgos:
        print("Datos sensibles detectados; no se publica:")
        for hallazgo in hallazgos[:20]:
            print(f"  {hallazgo}")
        return 2

    print("Pruebas…")
    bien, cola = correr_pruebas()
    print(f"  {cola}")
    if not bien:
        print("Pruebas en rojo: el trabajo queda local, no se publica.")
        return 3

    git("add", "-A")
    git("commit", "-q", "-m", mensaje)
    publicado = git("rev-parse", "HEAD").strip()
    print(f"Commit local: {publicado[:7]}  {mensaje.splitlines()[0]}")

    if sin_push:
        print("Push omitido (--sin-push).")
        return 0

    git("push", REMOTO, RAMA)
    git("fetch", "-q", REMOTO)
    remoto = git("rev-parse", f"{REMOTO}/{RAMA}").strip()
    if remoto != publicado:
        print(f"El remoto quedó en {remoto[:7]} y el local en {publicado[:7]}.")
        return 4
    print(f"Publicado en {REMOTO}/{RAMA} = {publicado[:7]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Publicación privada del buscador")
    parser.add_argument("accion", nargs="?", default="sincronizar",
                        choices=["estado", "sincronizar", "verificar", "publicar"])
    parser.add_argument("-m", "--mensaje", default="",
                        help="mensaje de commit para la acción publicar")
    parser.add_argument("--sin-push", action="store_true")
    parser.add_argument("--sin-pruebas", action="store_true")
    args = parser.parse_args()

    try:
        if args.accion == "estado":
            estado()
            return 0
        if args.accion == "verificar":
            return verificar()
        if args.accion == "publicar":
            return publicar(args.mensaje, sin_push=args.sin_push)
        return sincronizar(sin_push=args.sin_push, sin_pruebas=args.sin_pruebas)
    except RuntimeError as error:
        print(f"error: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
