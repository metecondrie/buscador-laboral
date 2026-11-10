"""Guardia de reemplazo del perfil (Fase 2B).

Origen canónico: `profile_versions` con `activo=1`. `buscador/perfil.py:PERFIL_EJEMPLO`
es un objeto DIFERENTE: declara inglés B2 y un campo ``nivel`` por habilidad, y
su uso en la evaluación produce veredictos distintos (comprobado en el piloto 1E:
Bybit 40,3 `eligible` contra 25,7 `doubtful` con el perfil operativo).

`perfil --real` e `perfil --importar` escriben ese objeto sobre el perfil activo
sin avisar. Esta guardia detiene cualquier reemplazo que cambie las propiedades
que alteran la clasificación. No normaliza ni repara nada: si hay diferencias,
lanza `ReemplazoPerfilBloqueado` con el detalle y la operación no escribe nada.

Fase 2B — comparación semántica completa
----------------------------------------
La versión de Fase 2A sólo miraba la *presencia* del campo ``nivel``: un perfil
que pasaba de ``nivel: "básico"`` a ``nivel: "avanzado"`` (o que cambiaba el
nivel de una sola habilidad) era aceptado en silencio. Tampoco comparaba
``salario`` ni ``disponibilidad``, que `rules.evaluar` usa para puntuar.

Ahora se compara **todo** el perfil operativo, campo por campo y valor por
valor, con estas reglas:

* se ignoran únicamente los metadatos que no intervienen en la clasificación
  (``version``, ``origen``, ``nota``, ``identidad``, ``requiere_confirmacion``);
* cualquier campo desconocido se trata como operativo (falla cerrado: si
  aparece y difiere, bloquea);
* la comparación es semántica: se ignoran espacios sobrantes, mayúsculas y el
  orden de listas, pero **no** se ignoran valores distintos;
* cada diferencia se informa con su ruta y sus dos valores, para que el usuario
  sepa exactamente qué cambiaría.

Uso en `__main__.cmd_perfil`::

    activo = perfil_guard.perfil_activo(conn)
    perfil_guard.validar_reemplazo(activo, propuesto)
    # recién acá guardar_perfil(...)
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

# Campos que no participan de `rules.evaluar`: cambiarlos no altera veredictos.
CAMPOS_METADATO = frozenset({
    "version",
    "origen",
    "nota",
    "identidad",
    "requiere_confirmacion",
})

# Orden estable para los informes.
CAMPOS_OPERATIVOS = (
    "idioma",
    "habilidades",
    "categorias",
    "experiencia",
    "territorio",
    "restricciones",
    "formacion",
    "salario",
    "disponibilidad",
)


class ReemplazoPerfilBloqueado(RuntimeError):
    """El perfil propuesto no es equivalente al perfil operativo activo."""

    def __init__(self, diferencias: list[str]):
        self.diferencias = diferencias
        super().__init__(
            "reemplazo de perfil bloqueado: " + "; ".join(diferencias)
        )


# --------------------------------------------------------------------------- #
# Normalización canónica
# --------------------------------------------------------------------------- #

def _texto(valor: Any) -> str:
    """Colapsa espacios: 'B1 ' y 'B1' son el mismo valor."""
    return " ".join(str(valor).split())


def _clave(valor: Any) -> str:
    return _texto(valor).casefold()


def _orden(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, default=str)


def _canon(valor: Any) -> Any:
    """Forma canónica: claves en minúscula, texto normalizado, listas ordenadas."""
    if isinstance(valor, dict):
        return {_clave(k): _canon(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        items = [_canon(v) for v in valor]
        return sorted(items, key=_orden)
    if isinstance(valor, str):
        # Mayúsculas y espacios son cosméticos: "B1", "b1 " y " B1" son el
        # mismo nivel. Un valor distinto ("B2") sigue siendo distinto.
        return _clave(valor)
    return valor


def _plano(valor: Any, prefijo: str = "") -> dict[str, Any]:
    """Aplana un valor canónico en {ruta: valor} para diff legible."""
    salida: dict[str, Any] = {}
    if isinstance(valor, dict):
        for clave in sorted(valor):
            ruta = f"{prefijo}.{clave}" if prefijo else clave
            salida.update(_plano(valor[clave], ruta))
    elif isinstance(valor, list):
        for indice, item in enumerate(valor):
            salida.update(_plano(item, f"{prefijo}[{indice}]"))
    else:
        salida[prefijo or "valor"] = valor
    return salida


def _difs_planas(actual: Any, propuesto: Any, limite: int = 6) -> list[str]:
    """Diferencias 'ruta: a -> b' entre dos valores canónicos."""
    pa, pp = _plano(actual), _plano(propuesto)
    detalles: list[str] = []
    for ruta in sorted(set(pa) | set(pp)):
        va, vp = pa.get(ruta, "<ausente>"), pp.get(ruta, "<ausente>")
        if va != vp:
            detalles.append(f"{ruta}: {va!r} -> {vp!r}")
    if len(detalles) > limite:
        resto = len(detalles) - limite
        detalles = detalles[:limite] + [f"… y {resto} diferencia(s) más"]
    return detalles


# --------------------------------------------------------------------------- #
# Habilidades
# --------------------------------------------------------------------------- #

def _habilidades(perfil: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """{nombre: atributos} con nombres normalizados y duplicados desambiguados.

    El perfil operativo declara 'Git' dos veces. Se ordena por la forma canónica
    completa antes de numerar, para que el resultado no dependa del orden del
    archivo.
    """
    entradas = []
    for habilidad in perfil.get("habilidades") or []:
        if not isinstance(habilidad, dict):
            entradas.append((_clave(habilidad), {}))
            continue
        atributos = {_clave(k): _canon(v) for k, v in habilidad.items()
                     if _clave(k) != "nombre"}
        entradas.append((_clave(habilidad.get("nombre", "")), atributos))
    entradas.sort(key=lambda par: (par[0], _orden(par[1])))

    salida: dict[str, dict[str, Any]] = {}
    for nombre, atributos in entradas:
        clave, n = nombre, 2
        while clave in salida:
            clave = f"{nombre}#{n}"
            n += 1
        salida[clave] = atributos
    return salida


def _mensaje_habilidades(actual: dict[str, Any],
                         propuesto: dict[str, Any]) -> str | None:
    ha, hp = _habilidades(actual), _habilidades(propuesto)
    if ha == hp:
        return None
    detalles: list[str] = []
    for nombre in sorted(set(ha) | set(hp)):
        if nombre not in hp:
            detalles.append(f"falta '{nombre}'")
            continue
        if nombre not in ha:
            detalles.append(f"sobra '{nombre}'")
            continue
        da, dp = _plano(ha[nombre]), _plano(hp[nombre])
        for ruta in sorted(set(da) | set(dp)):
            va, vp = da.get(ruta, "<ausente>"), dp.get(ruta, "<ausente>")
            if va != vp:
                detalles.append(f"'{nombre}'.{ruta}: {va!r} -> {vp!r}")
    if len(detalles) > 8:
        resto = len(detalles) - 8
        detalles = detalles[:8] + [f"… y {resto} diferencia(s) más"]
    return (f"habilidades {len(ha)} -> {len(hp)}: " + "; ".join(detalles))


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #

def diferencias(actual: dict[str, Any], propuesto: dict[str, Any]) -> list[str]:
    """Diferencias que cambian la clasificación. Lista vacía = reemplazo seguro."""
    problemas: list[str] = []

    operativos_a = {k for k in actual if _clave(k) not in CAMPOS_METADATO}
    operativos_p = {k for k in propuesto if _clave(k) not in CAMPOS_METADATO}

    faltan = sorted(operativos_a - operativos_p)
    if faltan:
        problemas.append(f"campos operativos ausentes en el propuesto: {faltan}")
    nuevos = sorted(operativos_p - operativos_a)
    if nuevos:
        problemas.append(f"campos operativos nuevos sin comparación previa: {nuevos}")

    # `idioma` se informa primero y con el texto histórico ("inglés B1 -> B2").
    if "idioma" in operativos_a and "idioma" in operativos_p:
        ia = actual.get("idioma") or {}
        ip = propuesto.get("idioma") or {}
        if _canon(ia) != _canon(ip):
            if _clave(ia.get("ingles")) != _clave(ip.get("ingles")):
                problemas.append(f"inglés {ia.get('ingles')!r} -> {ip.get('ingles')!r}")
            otros = {k: (ia.get(k), ip.get(k)) for k in set(ia) | set(ip)
                     if _clave(k) != "ingles" and _canon(ia.get(k)) != _canon(ip.get(k))}
            if otros:
                problemas.append("idioma difiere: " + "; ".join(
                    f"{k}: {a!r} -> {b!r}" for k, (a, b) in sorted(otros.items())))

    if "habilidades" in operativos_a and "habilidades" in operativos_p:
        mensaje = _mensaje_habilidades(actual, propuesto)
        if mensaje:
            problemas.append(mensaje)

    if "categorias" in operativos_a and "categorias" in operativos_p:
        ca = {_clave(x) for x in (actual.get("categorias") or [])}
        cp = {_clave(x) for x in (propuesto.get("categorias") or [])}
        if ca != cp:
            problemas.append(
                f"categorías: faltan {sorted(ca - cp)}, sobran {sorted(cp - ca)}")

    ya_informados = {"idioma", "habilidades", "categorias"}
    for campo in sorted((operativos_a & operativos_p) - ya_informados):
        va, vp = _canon(actual.get(campo)), _canon(propuesto.get(campo))
        if va == vp:
            continue
        detalles = _difs_planas(va, vp)
        problemas.append(f"{campo} difiere: " + "; ".join(detalles))

    return problemas


def validar_reemplazo(actual: dict[str, Any], propuesto: dict[str, Any]) -> None:
    """No devuelve nada si es seguro; lanza si el reemplazo cambia resultados."""
    problemas = diferencias(actual, propuesto)
    if problemas:
        raise ReemplazoPerfilBloqueado(problemas)


def hash_semantico(perfil: dict[str, Any]) -> str:
    """SHA-256 del perfil operativo canónico (metadatos excluidos)."""
    operativo = {
        _clave(k): _canon(v)
        for k, v in perfil.items()
        if _clave(k) not in CAMPOS_METADATO
    }
    crudo = json.dumps(operativo, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()


def perfil_activo(conn: sqlite3.Connection) -> dict[str, Any]:
    """Lee el perfil canónico desde `profile_versions` (nunca desde `PERFIL_EJEMPLO`)."""
    fila = conn.execute(
        "SELECT perfil_json FROM profile_versions WHERE activo=1"
    ).fetchone()
    if fila is None:
        raise ReemplazoPerfilBloqueado(["no hay perfil activo en profile_versions"])
    return json.loads(fila[0] if isinstance(fila, (tuple, list)) else fila["perfil_json"])
