"""Auditoría de credenciales de Gemini en la máquina.

Sólo lee. No borra, no reemplaza y no imprime valores: compara huellas SHA-256
de los primeros 12 caracteres hexadecimales.

Fuentes revisadas:

1. variable de entorno del **proceso** actual;
2. variable de entorno del **usuario** (HKCU\\Environment);
3. variable de entorno del **sistema** (HKLM\\...\\Session Manager\\Environment);
4. Administrador de credenciales de Windows (entradas genéricas);
5. almacén DPAPI propio en `%LOCALAPPDATA%\\BuscadorLaboral\\credenciales`;
6. archivos `.env` u otros que contengan claves, dentro del proyecto y de los datos.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import os
import re
import sys
import winreg
from ctypes import wintypes
from pathlib import Path

CRED_TYPE_GENERIC = 1
PATRON = re.compile(r"AIza[0-9A-Za-z_-]{35}")


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def huella(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()[:12]


def describir(valor: str | None) -> str:
    if not valor:
        return "ausente"
    limpio = valor.strip()
    extra = "" if limpio == valor else " (con espacios al borde)"
    return f"{len(limpio)} car. · huella {huella(limpio)} · {'formato AIza' if PATRON.fullmatch(limpio) else 'formato irregular'}{extra}"


def del_registro(raiz, ruta: str, nombre: str) -> str | None:
    try:
        with winreg.OpenKey(raiz, ruta) as clave:
            valor, _ = winreg.QueryValueEx(clave, nombre)
            return str(valor) if valor else None
    except (FileNotFoundError, OSError):
        return None


def enumerar_credenciales() -> list[dict]:
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    cantidad = wintypes.DWORD()
    puntero = ctypes.POINTER(ctypes.POINTER(_CREDENTIAL))()
    advapi.CredEnumerateW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD),
                                      ctypes.POINTER(ctypes.POINTER(ctypes.POINTER(_CREDENTIAL)))]
    advapi.CredEnumerateW.restype = wintypes.BOOL
    if not advapi.CredEnumerateW(None, 0, ctypes.byref(cantidad), ctypes.byref(puntero)):
        return []
    salida = []
    try:
        for indice in range(cantidad.value):
            cred = puntero[indice].contents
            blob = b""
            if cred.CredentialBlobSize:
                blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
            texto = ""
            for codec in ("utf-16-le", "utf-8", "latin-1"):
                try:
                    candidato = blob.decode(codec)
                except UnicodeDecodeError:
                    continue
                if PATRON.search(candidato) or ("AIza" in candidato and len(candidato) < 200):
                    texto = candidato
                    break
                texto = texto or candidato
            salida.append({
                "objetivo": cred.TargetName or "",
                "usuario": cred.UserName or "",
                "tipo": cred.Type,
                "bytes": cred.CredentialBlobSize,
                "texto": texto.strip(),
            })
    finally:
        advapi.CredFree.argtypes = [ctypes.c_void_p]
        advapi.CredFree(puntero)
    return salida


def descifrar_dpapi(datos: bytes) -> str | None:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    entrada = _BLOB(len(datos), ctypes.cast(ctypes.create_string_buffer(datos, len(datos)),
                                            ctypes.POINTER(ctypes.c_char)))
    salida = _BLOB()
    crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(_BLOB), ctypes.c_void_p,
                                           ctypes.POINTER(_BLOB), ctypes.c_void_p,
                                           ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB)]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    if not crypt32.CryptUnprotectData(ctypes.byref(entrada), None, None, None, None, 0,
                                      ctypes.byref(salida)):
        return None
    try:
        return ctypes.string_at(salida.pbData, salida.cbData).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return None
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


def main() -> int:
    print("=" * 74)
    print("AUDITORÍA DE CREDENCIALES — sólo lectura, sin exponer valores")
    print("=" * 74)

    hallazgos: list[dict] = []

    # 1-3: variables de entorno
    print("\n[1] Variables de entorno")
    proceso = os.environ.get("GEMINI_API_KEY")
    usuario = del_registro(winreg.HKEY_CURRENT_USER, "Environment", "GEMINI_API_KEY")
    sistema = del_registro(winreg.HKEY_LOCAL_MACHINE,
                           r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
                           "GEMINI_API_KEY")
    for etiqueta, valor in (("proceso", proceso), ("usuario (HKCU)", usuario),
                            ("sistema (HKLM)", sistema)):
        print(f"  {etiqueta:<16} {describir(valor)}")
        if valor:
            hallazgos.append({"origen": f"entorno:{etiqueta}", "valor": valor.strip()})

    # 4: Administrador de credenciales
    print("\n[4] Administrador de credenciales de Windows")
    credenciales = enumerar_credenciales()
    interesantes = [
        c for c in credenciales
        if any(p in c["objetivo"].lower() for p in ("gemini", "buscador", "google", "api"))
        or PATRON.search(c["texto"] or "")
    ]
    print(f"  entradas totales: {len(credenciales)} · coincidentes: {len(interesantes)}")
    for c in interesantes:
        tiene_clave = bool(PATRON.search(c["texto"] or "")) or (c["texto"] or "").startswith("AIza")
        print(f"  · objetivo={c['objetivo']!r} usuario={c['usuario']!r} bytes={c['bytes']} "
              f"clave={'sí' if tiene_clave else 'no'}")
        if tiene_clave:
            hallazgos.append({"origen": f"credenciales:{c['objetivo']}", "valor": c["texto"]})

    # 5: DPAPI propio
    print("\n[5] Almacén DPAPI del buscador")
    carpeta = Path(os.environ.get("LOCALAPPDATA", "")) / "BuscadorLaboral" / "credenciales"
    if carpeta.exists():
        archivos = sorted(carpeta.glob("*.bin"))
        print(f"  {len(archivos)} archivo(s) en {carpeta}")
        for archivo in archivos:
            try:
                valor = descifrar_dpapi(base64.b64decode(archivo.read_bytes()))
            except Exception as error:  # noqa: BLE001
                valor = None
                print(f"  · {archivo.name}: no se pudo descifrar ({type(error).__name__})")
                continue
            print(f"  · {archivo.name}: {describir(valor)}")
            if valor:
                hallazgos.append({"origen": f"dpapi:{archivo.name}", "valor": valor.strip()})
    else:
        print("  no existe la carpeta")

    # 6: archivos con claves dentro del proyecto y de los datos
    print("\n[6] Archivos con claves embebidas")
    raices = [Path(__file__).resolve().parents[1],
              Path(os.environ.get("LOCALAPPDATA", "")) / "BuscadorLaboral"]
    for raiz in raices:
        if not raiz.exists():
            continue
        for archivo in raiz.rglob("*"):
            if not archivo.is_file() or archivo.suffix.lower() in {".pyc", ".db", ".png", ".jpg"}:
                continue
            if ".venv" in str(archivo) or ".git" in str(archivo):
                continue
            try:
                texto = archivo.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for encontrada in PATRON.findall(texto):
                print(f"  · {archivo}: huella {huella(encontrada)}")
                hallazgos.append({"origen": f"archivo:{archivo.name}", "valor": encontrada})

    # 4. Huellas únicas
    print("\n[4] Huellas distintas encontradas")
    unicas: dict[str, list[str]] = {}
    for hallazgo in hallazgos:
        unicas.setdefault(huella(hallazgo["valor"]), []).append(hallazgo["origen"])
    for marca, origenes in unicas.items():
        print(f"  {marca}: {len(origenes)} origen(es) -> {', '.join(sorted(set(origenes)))}")
    if not unicas:
        print("  ninguna")
    if len(unicas) > 1:
        print(f"\n  ATENCIÓN: hay {len(unicas)} claves distintas almacenadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
