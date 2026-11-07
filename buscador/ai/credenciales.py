"""Almacenamiento local de claves de API.

Tres niveles, en orden de preferencia:

1. Variable de entorno del proceso (útil para pruebas y para CI; no persiste).
2. Administrador de credenciales de Windows, entradas genéricas con objetivo
   `BuscadorLaboral/<proveedor>`. Es el mecanismo pedido y el más seguro de los
   tres: lo protege el propio sistema operativo.
3. Archivo cifrado con DPAPI en `%LOCALAPPDATA%\\BuscadorLaboral\\credenciales`,
   sólo si el Administrador de credenciales no está disponible.

Las claves **nunca** se guardan en SQLite, en el repositorio, en los registros,
en los respaldos ni en las exportaciones. Este módulo no devuelve la clave a
ninguna capa que la pueda imprimir: la interfaz recibe únicamente el estado y una
versión enmascarada.
"""

from __future__ import annotations

import base64
import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

from .. import config

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


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


def _advapi() -> ctypes.WinDLL | None:
    if sys.platform != "win32":
        return None
    try:
        return ctypes.WinDLL("advapi32", use_last_error=True)
    except OSError:
        return None


def _crypt32() -> ctypes.WinDLL | None:
    """DPAPI se exporta desde crypt32.dll, no desde advapi32."""
    if sys.platform != "win32":
        return None
    try:
        return ctypes.WinDLL("crypt32", use_last_error=True)
    except OSError:
        return None


# --- Administrador de credenciales -----------------------------------------

def almacen_disponible() -> bool:
    return _advapi() is not None


def _objetivo(proveedor: str) -> str:
    return f"BuscadorLaboral/{proveedor}"


def _guardar_credencial(proveedor: str, secreto: str) -> bool:
    api = _advapi()
    if api is None:
        return False
    blob = secreto.encode("utf-16-le")
    buffer = ctypes.create_string_buffer(blob, len(blob))
    credencial = _CREDENTIAL()
    credencial.Flags = 0
    credencial.Type = CRED_TYPE_GENERIC
    credencial.TargetName = _objetivo(proveedor)
    credencial.Comment = "clave de API del buscador laboral"
    credencial.CredentialBlobSize = len(blob)
    credencial.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
    credencial.Persist = CRED_PERSIST_LOCAL_MACHINE
    credencial.UserName = "buscador"
    api.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIAL), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    return bool(api.CredWriteW(ctypes.byref(credencial), 0))


def _leer_credencial(proveedor: str) -> str | None:
    api = _advapi()
    if api is None:
        return None
    puntero = ctypes.POINTER(_CREDENTIAL)()
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(_CREDENTIAL))]
    api.CredReadW.restype = wintypes.BOOL
    if not api.CredReadW(_objetivo(proveedor), CRED_TYPE_GENERIC, 0, ctypes.byref(puntero)):
        return None
    try:
        credencial = puntero.contents
        if not credencial.CredentialBlobSize:
            return None
        datos = ctypes.string_at(credencial.CredentialBlob, credencial.CredentialBlobSize)
        return datos.decode("utf-16-le", errors="replace")
    finally:
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree(puntero)


def _borrar_credencial(proveedor: str) -> bool:
    api = _advapi()
    if api is None:
        return False
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    return bool(api.CredDeleteW(_objetivo(proveedor), CRED_TYPE_GENERIC, 0))


# --- Respaldo DPAPI --------------------------------------------------------

def _ruta_dpapi(proveedor: str) -> Path:
    return config.rutas().raiz / "credenciales" / f"{proveedor}.bin"


def _cifrar(texto: str) -> bytes | None:
    api = _crypt32()
    if api is None:
        return None
    datos = texto.encode("utf-8")
    entrada = _BLOB(len(datos), ctypes.cast(ctypes.create_string_buffer(datos, len(datos)),
                                            ctypes.POINTER(ctypes.c_char)))
    salida = _BLOB()
    api.CryptProtectData.argtypes = [ctypes.POINTER(_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_BLOB),
                                     ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                                     ctypes.POINTER(_BLOB)]
    api.CryptProtectData.restype = wintypes.BOOL
    if not api.CryptProtectData(ctypes.byref(entrada), "buscador laboral", None, None, None, 0,
                                ctypes.byref(salida)):
        return None
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


def _descifrar(datos: bytes) -> str | None:
    api = _crypt32()
    if api is None:
        return None
    entrada = _BLOB(len(datos), ctypes.cast(ctypes.create_string_buffer(datos, len(datos)),
                                            ctypes.POINTER(ctypes.c_char)))
    salida = _BLOB()
    api.CryptUnprotectData.argtypes = [ctypes.POINTER(_BLOB), ctypes.c_void_p, ctypes.POINTER(_BLOB),
                                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                                       ctypes.POINTER(_BLOB)]
    api.CryptUnprotectData.restype = wintypes.BOOL
    if not api.CryptUnprotectData(ctypes.byref(entrada), None, None, None, None, 0,
                                  ctypes.byref(salida)):
        return None
    try:
        return ctypes.string_at(salida.pbData, salida.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


# --- API pública -----------------------------------------------------------

def guardar(proveedor: str, secreto: str) -> dict:
    """Guarda la clave y devuelve dónde quedó. Nunca la repite."""
    secreto = (secreto or "").strip()
    if not secreto:
        raise ValueError("la clave está vacía")
    if _guardar_credencial(proveedor, secreto):
        return {"almacen": "credenciales-windows", "objetivo": _objetivo(proveedor)}
    cifrado = _cifrar(secreto)
    if cifrado is None:
        raise RuntimeError("no hay almacén seguro disponible en este sistema")
    ruta = _ruta_dpapi(proveedor)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(base64.b64encode(cifrado))
    try:
        os.chmod(ruta, 0o600)
    except OSError:
        pass
    return {"almacen": "dpapi-archivo", "objetivo": str(ruta)}


def leer(proveedor: str, variable: str | None = None,
         preferida: str | None = None) -> str | None:
    """Devuelve la clave para uso interno. Nunca se expone en la interfaz."""
    return resolver(proveedor, variable, preferida)["valor"]


def _con_valor(proveedor: str, variable: str | None = None) -> list[dict]:
    """Candidatas con su valor, en orden de preferencia: almacén y luego entorno.

    El almacén va primero porque escribir una clave desde la interfaz es una
    acción explícita del usuario; una variable de entorno vieja no debe taparla.
    """
    import hashlib

    salida: list[dict] = []
    vistas: set[str] = set()

    def agregar(origen_: str, valor: str | None) -> None:
        if not valor:
            return
        limpio = valor.strip()
        marca = hashlib.sha256(limpio.encode("utf-8")).hexdigest()[:12]
        if marca in vistas:
            return
        vistas.add(marca)
        salida.append({"origen": origen_, "huella": marca, "longitud": len(limpio),
                       "valor": limpio})

    agregar("credenciales-windows", _leer_credencial(proveedor))
    ruta = _ruta_dpapi(proveedor)
    if ruta.exists():
        try:
            agregar("dpapi-archivo", _descifrar(base64.b64decode(ruta.read_bytes())))
        except (OSError, ValueError):
            pass
    if variable:
        agregar("variable-entorno", os.environ.get(variable))
    return salida


def candidatas(proveedor: str, variable: str | None = None) -> list[dict]:
    """Todas las claves disponibles, con su origen y su huella. Nunca el valor.

    Sirve para detectar el caso peligroso: una variable de entorno vieja que tapa
    la clave recién guardada desde la interfaz.
    """
    import hashlib

    return [{k: v for k, v in c.items() if k != "valor"}
            for c in _con_valor(proveedor, variable)]


def hay_sombra(proveedor: str, variable: str | None = None) -> str | None:
    """Devuelve un aviso si hay más de una clave distinta y una tapa a la otra."""
    lista = candidatas(proveedor, variable)
    if len(lista) < 2:
        return None
    activa = lista[0]
    otras = ", ".join(f"{c['origen']} ({c['huella']})" for c in lista[1:])
    return (f"hay {len(lista)} claves distintas: se usa {activa['origen']} "
            f"({activa['huella']}) y queda tapada {otras}")


def resolver(proveedor: str, variable: str | None = None,
             preferida: str | None = None) -> dict:
    """Elige la credencial a usar. Devuelve origen, huella y valor.

    Prioridad: la huella que ya funcionó, después el almacén (acción explícita
    del usuario) y por último la variable de entorno.
    """
    lista = _con_valor(proveedor, variable)
    if not lista:
        return {"origen": None, "huella": None, "valor": None}
    if preferida:
        for candidata in lista:
            if candidata["huella"] == preferida:
                return candidata
    return lista[0]


def origen(proveedor: str, variable: str | None = None) -> str | None:
    return resolver(proveedor, variable)["origen"]


def borrar(proveedor: str) -> dict:
    borrado_sistema = _borrar_credencial(proveedor)
    ruta = _ruta_dpapi(proveedor)
    borrado_archivo = False
    if ruta.exists():
        ruta.unlink()
        borrado_archivo = True
    return {"credenciales-windows": borrado_sistema, "dpapi-archivo": borrado_archivo}


def enmascarar(clave: str | None) -> str:
    """Devuelve sólo los últimos cuatro caracteres. Nunca la clave completa."""
    if not clave:
        return ""
    return "•" * max(len(clave) - 4, 4) + clave[-4:]
