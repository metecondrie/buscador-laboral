"""Diagnóstico de credenciales de IA, sin exponer la clave.

Reglas que sigue este módulo:

- **La validez la decide la API, no el formato.** Una clave puede no empezar con
  `AIza` ni medir 39 caracteres y funcionar perfectamente. El formato se informa
  como dato, nunca como veredicto.
- **Cada prueba declara su tipo.** Sólo las de Gemini (`catalogo`, `generacion`)
  deciden la conclusión. YouTube y Books son *controles*: Google ya no acepta
  claves de API en esos servicios, así que un 401 ahí **no es** un fallo de
  Gemini y se informa como «no aplica».
- **Si la generación respondió 200, no se sugieren problemas de modelo ni de
  cuota.** Se dice que funciona.
- **El último resultado válido se separa de los errores históricos**, cada uno
  con la fecha y la huella de la credencial que lo produjo: un error viejo de
  otra clave no puede leerse como si fuera el estado actual.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request

from .. import config, db
from .cliente import Politica, presupuesto
from .proveedores import obtener

TIMEOUT = 20
LIMITE_CUERPO = 2 * 1024 * 1024

# Formato histórico de las claves de Google. Es informativo: hay credenciales
# válidas con otra longitud y otro prefijo.
PATRON_GOOGLE = re.compile(r"AIza[0-9A-Za-z_-]{35}")

ESTADOS_VALIDOS = ("funciona", "verificada")


def _leer_cuerpo(respuesta) -> dict:
    try:
        crudo = respuesta.read(LIMITE_CUERPO).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return {}
    try:
        datos = json.loads(crudo)
        return datos if isinstance(datos, dict) else {}
    except json.JSONDecodeError:
        return {}


def _error(error: urllib.error.HTTPError) -> dict:
    cuerpo = _leer_cuerpo(error)
    detalle = cuerpo.get("error", {}) if isinstance(cuerpo, dict) else {}
    razones = [d.get("reason") for d in detalle.get("details", []) if isinstance(d, dict)]
    razones += [e.get("reason") for e in detalle.get("errors", []) if isinstance(e, dict)]
    return {
        "http": error.code,
        "ok": False,
        "estado": detalle.get("status") or "",
        "razones": [r for r in razones if r],
        "mensaje": (detalle.get("message") or "")[:200],
        "cuerpo": {},
    }


def _consultar(url: str, clave: str, cuerpo: dict | None = None) -> dict:
    """Petición por cabecera: la clave nunca viaja en la URL."""
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo else None
    peticion = urllib.request.Request(url, data=datos, method="POST" if cuerpo else "GET")
    peticion.add_header("x-goog-api-key", clave)
    if cuerpo:
        peticion.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT) as respuesta:
            return {"http": respuesta.status, "ok": True, "estado": "OK", "razones": [],
                    "mensaje": "", "cuerpo": _leer_cuerpo(respuesta)}
    except urllib.error.HTTPError as error:
        return _error(error)
    except Exception as error:  # noqa: BLE001
        return {"http": None, "ok": False, "estado": "SIN_RESPUESTA", "razones": [],
                "mensaje": type(error).__name__, "cuerpo": {}}


def _clave(proveedor) -> dict:
    """Credencial resuelta, con su origen y huella."""
    from . import credenciales

    return credenciales.resolver(proveedor.clave, proveedor.variable_clave,
                                 _preferida_global)


_preferida_global: str | None = None


def _pruebas(valor: str) -> list[dict]:
    catalogo = _consultar("https://generativelanguage.googleapis.com/v1beta/models", valor)
    alterno = _consultar("https://generativelanguage.googleapis.com/v1/models", valor)
    generacion = _consultar(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-3.5-flash-lite:generateContent",
        valor,
        cuerpo={"contents": [{"parts": [{"text": "ping"}]}],
                "generationConfig": {"maxOutputTokens": 1}},
    )
    youtube = _consultar(
        "https://www.googleapis.com/youtube/v3/videos?part=id&id=dQw4w9WgXcQ", valor)
    books = _consultar(
        "https://www.googleapis.com/books/v1/volumes?q=test&maxResults=1", valor)

    salida = [
        {"nombre": "Catálogo v1beta", "tipo": "catalogo", **catalogo},
        {"nombre": "Catálogo v1", "tipo": "catalogo_alterno", **alterno},
        {"nombre": "Generación (gemini-3.5-flash-lite)", "tipo": "generacion", **generacion},
        {"nombre": "Control YouTube (no es Gemini)", "tipo": "control", **youtube},
        {"nombre": "Control Books (no es Gemini)", "tipo": "control", **books},
    ]
    for prueba in salida:
        if prueba["tipo"] == "control" and not prueba["ok"]:
            # Google ya no acepta claves de API en estos servicios: un 401 acá no
            # dice nada sobre Gemini.
            if prueba["http"] == 401 or "not supported" in (prueba["mensaje"] or "").lower():
                prueba["aplicable"] = False
                prueba["nota"] = "no aplica: Google exige OAuth en este servicio"
            else:
                prueba["aplicable"] = True
                prueba["nota"] = "control informativo; no afecta a Gemini"
        else:
            prueba["aplicable"] = True
            prueba["nota"] = ""
    return salida


def _modelos(catalogo: dict, proveedor) -> dict:
    configurados = [m.id for m in proveedor.modelos]
    if not catalogo.get("ok"):
        return {"configurados": configurados, "presentes": [], "ausentes": configurados,
                "total": 0}
    disponibles = [
        (entrada.get("name") or "").split("/", 1)[-1]
        for entrada in (catalogo.get("cuerpo") or {}).get("models", [])
        if "generateContent" in (entrada.get("supportedGenerationMethods") or [])
    ]
    return {
        "configurados": configurados,
        "presentes": [m for m in configurados if m in disponibles],
        "ausentes": [m for m in configurados if m not in disponibles],
        "total": len(disponibles),
    }


def _conclusion(pruebas: list[dict], modelos: dict) -> tuple[str, str]:
    """Devuelve (estado, texto). Sólo mira pruebas de Gemini."""
    catalogo = [p for p in pruebas if p["tipo"].startswith("catalogo")]
    generacion = next(p for p in pruebas if p["tipo"] == "generacion")
    cat_ok = any(p["ok"] for p in catalogo)
    gen_ok = generacion["ok"]

    if gen_ok and cat_ok:
        presentes = modelos["presentes"]
        detalle = (f"{len(presentes)} modelo(s) verificado(s): " + ", ".join(presentes)
                   if presentes else f"{modelos['total']} modelos disponibles en el catálogo")
        return "funciona", (f"La clave funciona: catálogo y generación respondieron "
                            f"{generacion['http']}. {detalle}.")
    if gen_ok and not cat_ok:
        return "funciona", ("La generación respondió 200, así que la clave sirve; sólo falló "
                            "el listado de modelos.")

    http = generacion.get("http")
    razones = set(generacion.get("razones") or [])
    mensaje = (generacion.get("mensaje") or "").lower()

    if cat_ok and not gen_ok:
        if http == 429:
            return "cuota", ("La clave es válida (el catálogo respondió 200) pero la cuota "
                             "está agotada ahora mismo: HTTP 429. Se reintenta más tarde.")
        if http == 404:
            return "parcial", ("El catálogo responde, pero el modelo de prueba no está "
                               "disponible para esta clave: HTTP 404.")
        if http in (401, 403):
            return "sin_permiso", ("El catálogo responde pero la generación fue rechazada "
                                   f"(HTTP {http}). Revisá permisos del proyecto.")
        return "parcial", (f"El catálogo responde; la generación falló con HTTP {http}: "
                           f"{generacion.get('mensaje') or 'sin detalle'}")

    if "API_KEY_INVALID" in razones or "not found" in mensaje:
        return "invalida", ("La API no reconoce esta clave: está revocada, fue borrada o "
                            "nunca se generó. Hay que crear otra.")
    if http == 429 or "RESOURCE_EXHAUSTED" in razones:
        return "cuota", "La clave existe pero la cuota está agotada ahora (HTTP 429)."
    if http in (401, 403) or "PERMISSION_DENIED" in razones or "SERVICE_DISABLED" in razones:
        return "sin_permiso", ("La clave existe pero la API no está habilitada o no tiene "
                               f"permiso para el proyecto (HTTP {http}).")
    return "error", (f"No se pudo verificar la clave: HTTP {http or 'sin respuesta'} · "
                     f"{generacion.get('mensaje') or 'sin detalle'}")


def _historial(conn, huella_actual: str | None) -> dict:
    filas = [
        dict(f) for f in conn.execute(
            "SELECT estado, huella_credencial, detalle, creado_en FROM ai_model_checks"
            " ORDER BY id DESC LIMIT 200"
        ).fetchall()
    ]
    ultimo_valido = next((f for f in filas if f["estado"] in ESTADOS_VALIDOS), None)
    agrupado: dict[tuple, dict] = {}
    for fila in filas:
        clave = (fila["estado"], fila["huella_credencial"] or "sin-huella")
        cubo = agrupado.setdefault(clave, {
            "estado": fila["estado"],
            "huella": fila["huella_credencial"],
            "veces": 0,
            "ultima": fila["creado_en"],
            "es_actual": fila["huella_credencial"] == huella_actual,
        })
        cubo["veces"] += 1
    return {
        "ultimo_valido": ultimo_valido,
        "por_estado": sorted(agrupado.values(), key=lambda c: c["ultima"], reverse=True),
        "errores_de_otra_clave": sum(
            1 for f in filas
            if f["estado"] not in ESTADOS_VALIDOS
            and huella_actual and f["huella_credencial"]
            and f["huella_credencial"] != huella_actual
        ),
    }


def diagnosticar(conn, clave_proveedor: str = "gemini") -> dict:
    global _preferida_global
    proveedor = obtener(clave_proveedor)
    if proveedor is None:
        return {"ok": False, "estado": "desconocido", "candidatas": [], "sombra": None,
                "conclusion": "proveedor desconocido", "endpoints": [],
                "clave": {"presente": False}, "modelos": {}, "historial": {}}

    _preferida_global = db.ajuste(conn, "ia_credencial_activa", "") or None
    resuelta = _clave(proveedor)
    valor = resuelta.get("valor")
    if not valor:
        return {"ok": False, "estado": "sin_clave", "candidatas": [], "sombra": None,
                "conclusion": "no hay clave guardada para este proveedor",
                "endpoints": [], "clave": {"presente": False}, "modelos": {},
                "historial": _historial(conn, None)}

    from . import credenciales as _cred

    lista: list[dict] = []
    sombra: str | None = None
    aviso: str | None = None
    try:
        lista = _cred.candidatas(proveedor.clave, proveedor.variable_clave)
        if len(lista) > 1:
            sombra = _cred.hay_sombra(proveedor.clave, proveedor.variable_clave)
    except Exception as exc:  # noqa: BLE001 - el diagnóstico de la API sigue siendo válido
        aviso = f"no se pudieron enumerar las claves: {exc!r}"[:200]

    huella = resuelta.get("huella")
    pruebas = _pruebas(valor)
    catalogo = next(p for p in pruebas if p["tipo"] == "catalogo")
    modelos = _modelos(catalogo, proveedor)
    estado, conclusion = _conclusion(pruebas, modelos)
    if sombra:
        conclusion += " Atención: " + sombra + "."

    clave = {
        "presente": True,
        "origen": resuelta.get("origen"),
        "longitud": len(valor),
        "huella": huella,
        "mascara": "•" * max(len(valor) - 4, 4) + valor[-4:],
        # Informativo: hay claves válidas que no siguen el formato histórico.
        "formato_conocido": bool(PATRON_GOOGLE.fullmatch(valor)),
        "nota_formato": ("el formato no determina la validez; la decide la API"
                         if not PATRON_GOOGLE.fullmatch(valor) else ""),
    }

    resultado = {
        "ok": estado == "funciona",
        "estado": estado,
        "conclusion": conclusion,
        "clave": clave,
        "modelos": modelos,
        "endpoints": [{k: v for k, v in p.items() if k != "cuerpo"} for p in pruebas],
        "candidatas": lista,
        "sombra": sombra,
        "politica": {
            "habilitada": Politica.desde_ajustes(conn).habilitada,
            "presupuesto": presupuesto(conn, Politica.desde_ajustes(conn).presupuesto_mensual_usd),
        },
        "fecha": config.ahora_utc(),
    }
    if aviso:
        resultado["aviso"] = aviso

    with db.transaccion(conn):
        conn.execute(
            "INSERT INTO ai_model_checks (proveedor, modelo, estado, detalle, consumio_cuota,"
            " creado_en, huella_credencial) VALUES (?,?,?,?,?,?,?)",
            (proveedor.clave, None, estado, conclusion[:400],
             1 if pruebas[2]["ok"] else 0, config.ahora_utc(), huella),
        )

    # El historial se arma después de registrar: así «último resultado válido»
    # incluye el de esta corrida y no aparece vacío en una base nueva.
    resultado["historial"] = _historial(conn, huella)

    if estado in ESTADOS_VALIDOS and huella:
        db.guardar_ajuste(conn, "ia_credencial_activa", huella)
    return resultado


def modelos_disponibles(conn, clave_proveedor: str = "gemini") -> dict:
    """Lista los modelos que el proveedor informa para esta clave."""
    global _preferida_global
    proveedor = obtener(clave_proveedor)
    if proveedor is None:
        return {"ok": False, "detalle": "proveedor desconocido"}
    _preferida_global = db.ajuste(conn, "ia_credencial_activa", "") or None
    valor = _clave(proveedor).get("valor")
    if not valor:
        return {"ok": False, "detalle": "sin clave"}
    respuesta = _consultar("https://generativelanguage.googleapis.com/v1beta/models", valor)
    if not respuesta["ok"]:
        return {"ok": False, "http": respuesta["http"], "razones": respuesta["razones"],
                "detalle": respuesta["mensaje"]}
    disponibles = [
        (entrada.get("name") or "").split("/", 1)[-1]
        for entrada in (respuesta["cuerpo"].get("models") or [])
        if "generateContent" in (entrada.get("supportedGenerationMethods") or [])
    ]
    configurados = [m.id for m in proveedor.modelos]
    return {
        "ok": True,
        "total": len(disponibles),
        "disponibles": disponibles,
        "configurados": configurados,
        "presentes": [m for m in configurados if m in disponibles],
        "ausentes": [m for m in configurados if m not in disponibles],
    }


def huella_de(valor: str | None) -> str | None:
    """Huella corta de una credencial. Nunca se expone el valor."""
    if not valor:
        return None
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()[:12]
