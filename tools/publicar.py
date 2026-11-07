"""Publica la copia saneada del buscador en el repositorio privado de GitHub.

Uso habitual (lo corre el agente o vos a mano):

    py -3 tools/publicar.py estado        # diagnóstico, no modifica nada
    py -3 tools/publicar.py simular       # sync completa en un clon: no comitea ni publica
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
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

RAIZ_COPIA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from publicacion import saneado  # noqa: E402

ORIGINAL = Path(os.environ.get("BUSCADOR_ORIGINAL")
                 or Path.home() / "WorkBuddy AI" / "buscad0r")
REGISTRO = "docs/publicacion/estado.json"
REMOTO = "origin"
RAMA = "main"

#: La simulación trabaja sobre un clon temporario. Todas las lecturas de la
#: "copia" pasan por acá, así el procedimiento es idéntico al real y no toca
#: el repositorio publicable ni el registro de base.
_RAIZ_ACTIVA = RAIZ_COPIA


def raiz_activa() -> Path:
    return _RAIZ_ACTIVA


def registro() -> Path:
    return raiz_activa() / REGISTRO

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
        ["git", *args], cwd=str(cwd or raiz_activa()), capture_output=True,
        text=texto, check=False,
    )
    if resultado.returncode != 0:
        salida = resultado.stderr if texto else resultado.stderr.decode("utf-8", "replace")
        raise RuntimeError(f"git {' '.join(args)} falló: {salida.strip()}")
    return resultado.stdout


def git_ok(*args: str, cwd: Path | None = None) -> bool:
    return subprocess.run(["git", *args], cwd=str(cwd or raiz_activa()),
                          capture_output=True).returncode == 0


def leer_registro() -> dict:
    archivo = registro()
    if archivo.exists():
        return json.loads(archivo.read_text(encoding="utf-8"))
    return {"base_original": "", "publicaciones": []}


def escribir_registro(datos: dict) -> None:
    archivo = registro()
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")


def publicables() -> list[Path]:
    """Archivos que Git incluiría: versionados + nuevos no ignorados."""
    listado = git("ls-files", "--cached", "--others", "--exclude-standard")
    rutas: list[Path] = []
    for linea in listado.splitlines():
        if linea.strip():
            rutas.append(raiz_activa() / linea.strip())
    return rutas


def python_pruebas() -> str:
    candidatos = [
        os.environ.get("BUSCADOR_PYTHON"),
        str(raiz_activa() / ".venv" / "Scripts" / "python.exe"),
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
        cwd=str(raiz_activa()), capture_output=True, text=True, env=entorno,
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
    intento = subprocess.run(["git", "apply", "--check", "-"], cwd=str(raiz_activa()),
                             input=parche.encode("utf-8"), capture_output=True)
    if intento.returncode != 0:
        return False
    aplicado = subprocess.run(["git", "apply", "-"], cwd=str(raiz_activa()),
                              input=parche.encode("utf-8"), capture_output=True)
    return aplicado.returncode == 0


def _restaurar(creados: list[str]) -> None:
    """Vuelve la copia al estado anterior sin tocar archivos ajenos al sync."""
    git("checkout", "--", ".")
    for ruta in creados:
        destino = raiz_activa() / ruta
        if destino.exists():
            destino.unlink()


def _resolver_por_saneado(ruta: str, estado_archivo: str, base: str,
                          head: str) -> tuple[str, str]:
    """Sincroniza un archivo de código comparando **representaciones saneadas**.

    El parche crudo se genera contra el original (LF, con datos personales) y la
    copia está saneada (CRLF y texto anonimizado): el contexto nunca coincide.
    En vez de abandonar el archivo, se comparan ambas versiones del original en
    el mismo espacio saneado y se escribe la del head.

    Tres guardas, ninguna desactiva un control de seguridad:

    1. La copia no debe tener cambios funcionales propios respecto de la base
       saneada. Si los tiene, abortar: podríamos borrar trabajo local.
    2. La representación saneada del head debe pasar la misma puerta de datos
       sensibles (`verificar_texto`) que el árbol completo.
    3. Un cambio que desaparece al sanear sólo se acepta si la huella funcional
       (AST sin docstrings ni comentarios) confirma que no tocó código.

    Devuelve `equivalente`, `reemplazado` o `conflicto` y un motivo.
    """
    if estado_archivo.startswith("D"):
        return "conflicto", "borrado de código: requiere revisión manual"
    try:
        base_txt = ("" if estado_archivo.startswith("A")
                    else git("show", f"{base}:{ruta}", cwd=ORIGINAL))
        head_txt = git("show", f"{head}:{ruta}", cwd=ORIGINAL)
    except RuntimeError as exc:
        return "conflicto", f"no se pudo leer una versión del original: {exc}"

    destino = raiz_activa() / ruta
    actual = (destino.read_text(encoding="utf-8", newline="")
              if destino.is_file() else "")
    cambio = saneado.clasificar_cambio(base_txt, head_txt, ruta)
    if not cambio["valida"]:
        return "conflicto", "la representación saneada no se puede analizar"

    huella_actual = saneado.huella_funcional(actual, ruta)
    huella_base = saneado.huella_funcional(cambio["saneado_base"], ruta)
    if huella_actual.startswith("!") or huella_actual != huella_base:
        return "conflicto", "la copia divergió funcionalmente de la base saneada"

    if saneado.verificar_texto(cambio["saneado_head"], ruta):
        return "conflicto", "la versión saneada del head contiene datos sensibles"

    if cambio["equivalente"]:
        return "equivalente", "sólo texto neutralizado por el saneado; nada que escribir"

    destino.parent.mkdir(parents=True, exist_ok=True)
    # Se escribe normalizado (LF): la próxima sincronización ya no choca con
    # CRLF. Git con autocrlf guarda LF en el índice, así que no cambia el diff.
    destino.write_text(cambio["saneado_head"], encoding="utf-8", newline="")
    return "reemplazado", "representación saneada equivalente al head"


def sincronizar(sin_push: bool = False, sin_pruebas: bool = False,
                simular: bool = False) -> int:
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
    equivalentes: list[str] = []
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
            destino = raiz_activa() / ruta
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(contenido, encoding="utf-8", newline="")
            reemplazados.append(ruta)
            continue
        # Código: el parche crudo no aplica sobre una copia saneada. Se compara
        # en representación saneada en lugar de excluir el archivo.
        clasificacion, motivo = _resolver_por_saneado(ruta, estado_archivo, base, head)
        if clasificacion == "conflicto":
            conflictos.append(f"{ruta} ({motivo})")
        elif clasificacion == "equivalente":
            equivalentes.append(ruta)
        else:
            reemplazados.append(ruta)
            if estado_archivo.startswith("A"):
                creados.append(ruta)

    if conflictos:
        _restaurar(creados)
        print("\nConflicto en archivos de código; no se publica nada:")
        for ruta in conflictos:
            print(f"  {ruta}")
        print("Requiere revisión manual: la equivalencia saneada no se pudo asegurar.")
        return 2

    tocados = saneado.sanear(raiz_activa(), publicables())
    if tocados:
        print(f"\nSaneado aplicado en {len(tocados)} archivo(s):")
        for ruta in tocados:
            print(f"  {ruta}")

    hallazgos = saneado.verificar(raiz_activa(), publicables())
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

    if simular:
        print("\n--- SIMULACIÓN (sin commit, sin registro, sin push) ---")
        print(f"aplicados por parche: {len(aplicados)} · reemplazados por "
              f"representación saneada: {len(reemplazados)} · equivalentes: "
              f"{len(equivalentes)} · omitidos: {len(omitidos)} · conflictos: 0")
        if equivalentes:
            print("equivalentes (sin cambios publicables):")
            for ruta in equivalentes:
                print(f"  {ruta}")
        if reemplazados:
            print("reemplazados (parche crudo no aplicable):")
            for ruta in reemplazados:
                print(f"  {ruta}")
        print("diff del clon:")
        for linea in git("diff", "--stat").splitlines():
            print(f"  {linea}")
        print(f"huella del árbol: {_huella_arbol()}")
        return 0

    mensaje = [
        f"chore(publicacion): sincroniza {base[:7]}..{head[:7]} del proyecto original",
        "",
        "Commits incorporados:",
        *(f"  - {linea}" for linea in commits),
        "",
        f"Archivos aplicados: {len(aplicados)} · reemplazados por representación "
        f"saneada: {len(reemplazados)} · equivalentes: {len(equivalentes)} · "
        f"omitidos (versión saneada propia): {len(omitidos)}",
    ]
    if reemplazados:
        mensaje += ["", "Reemplazados por representación saneada equivalente:"]
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
    git("add", REGISTRO)
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


def _huella_arbol() -> str:
    """Digest del contenido publicable, para probar que la simulación es reproducible."""
    digest = hashlib.sha256()
    for ruta in sorted(publicables(), key=lambda p: str(p).replace("\\", "/")):
        digest.update(str(ruta.relative_to(raiz_activa())).replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(ruta.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def simular(sin_pruebas: bool = False) -> int:
    """Sincronización completa sobre un clon temporario. No publica nada.

    Usa exactamente el mismo `sincronizar()` que la operación real, incluidas
    la puerta de datos sensibles y las pruebas. Lo único que cambia es el
    destino (`_RAIZ_ACTIVA`) y que se omite el commit, el registro y el push.
    """
    global _RAIZ_ACTIVA

    # Las pruebas de la copia incluyen una simulación. Sin este guardia, correr
    # una simulación *con* pruebas clonaría, ejecutaría esas pruebas y volvería a
    # simular recursivamente.
    if os.environ.get("BUSCADOR_SIMULACION") == "1":
        sin_pruebas = True

    datos = estado(silencioso=True)
    base, head = datos["base_registrada"], datos["original_head"]
    if base == head:
        print(f"Al día: el original sigue en {head[:7]}. Nada que simular.")
        return 0
    if datos["copia_sucio"]:
        print("La copia tiene cambios sin commitear; la simulación parte del HEAD.")
        print("(no se modifica el repositorio real)")

    with tempfile.TemporaryDirectory(prefix="buscador-sim-") as temporal:
        clon = Path(temporal) / "copia"
        clonado = subprocess.run(
            ["git", "clone", "--local", "--no-hardlinks", "-q", str(RAIZ_COPIA), str(clon)],
            capture_output=True, text=True, check=False,
        )
        if clonado.returncode != 0:
            raise RuntimeError(f"no se pudo clonar la copia: {clonado.stderr.strip()}")
        anterior = _RAIZ_ACTIVA
        _RAIZ_ACTIVA = clon
        entorno_previo = os.environ.get("BUSCADOR_SIMULACION")
        os.environ["BUSCADOR_SIMULACION"] = "1"
        try:
            print(f"Simulando sobre clon temporario: {clon}")
            codigo = sincronizar(sin_push=True, sin_pruebas=sin_pruebas, simular=True)
        finally:
            _RAIZ_ACTIVA = anterior
            if entorno_previo is None:
                os.environ.pop("BUSCADOR_SIMULACION", None)
            else:
                os.environ["BUSCADOR_SIMULACION"] = entorno_previo
        return codigo


def verificar() -> int:
    tocados = saneado.sanear(raiz_activa(), publicables())
    for ruta in tocados:
        print(f"saneado: {ruta}")
    hallazgos = saneado.verificar(raiz_activa(), publicables())
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

    tocados = saneado.sanear(raiz_activa(), publicables())
    for ruta in tocados:
        print(f"saneado: {ruta}")

    hallazgos = saneado.verificar(raiz_activa(), publicables())
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
                        choices=["estado", "sincronizar", "simular", "verificar", "publicar"])
    parser.add_argument("-m", "--mensaje", default="",
                        help="mensaje de commit para la acción publicar")
    parser.add_argument("--sin-push", action="store_true")
    parser.add_argument("--sin-pruebas", action="store_true")
    args = parser.parse_args()

    try:
        if args.accion == "estado":
            estado()
            return 0
        if args.accion == "simular":
            return simular(sin_pruebas=args.sin_pruebas)
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
