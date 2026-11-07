"""Cliente de IA: cascada, cuotas, caché, reintentos y contabilidad.

Principios:

- **USD 0 por defecto.** Sólo se usan modelos con cuota gratuita. Un proveedor
  de pago requiere habilitación explícita y autorización de gasto separada.
- **Sin cuota no se pierde nada:** la tarea vuelve a la cola y se reintenta más
  tarde; el rastreador y las reglas deterministas siguen funcionando.
- **Toda llamada deja rastro** en `ai_calls`: proveedor, modelo, tokens, costo,
  duración, si consumió cuota y el estado. Nunca la credencial.
- **El transporte se inyecta**, así las pruebas no tocan la red ni gastan.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from .. import config, db
from . import cache as cache_mod
from . import credenciales, cuotas
from .esquema import AnalisisIA, desde_texto
from .proveedores import (CASCADA_POR_DEFECTO, PROVEEDORES, PROVEEDORES_ACTIVOS,
                          Modelo, Proveedor,
                          catalogo as catalogo_modelos)
from .proveedores import obtener as obtener_proveedor
from .proveedores import parsear

NIVELES = {"rapido": 0, "equilibrado": 1, "profundo": 2}

_PATRON_CLAVE = re.compile(r"AIza[0-9A-Za-z_-]{35}|sk-[A-Za-z0-9_-]{16,}|gsk_[A-Za-z0-9]{20,}")


def redactar(texto: str) -> str:
    """Quita cualquier credencial de un texto antes de persistirlo o mostrarlo."""
    return _PATRON_CLAVE.sub("[CLAVE-REDACTADA]", texto or "")

_PATRON_CLAVE = re.compile(r"AIza[0-9A-Za-z_-]{35}|sk-[A-Za-z0-9_-]{16,}|gsk_[A-Za-z0-9]{20,}")


def redactar(texto: str) -> str:
    """Quita cualquier credencial de un texto antes de persistirlo o mostrarlo."""
    return _PATRON_CLAVE.sub("[CLAVE-REDACTADA]", texto or "")


class Rechazo(RuntimeError):
    """Una política impidió la llamada. No es un fallo de red."""

    def __init__(self, motivo: str, codigo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo
        self.codigo = codigo


class SinCuota(RuntimeError):
    """No queda cuota gratuita en ningún modelo de la cascada."""

    def __init__(self, detalle: list[dict], reintentar_en_segundos: int = 900) -> None:
        super().__init__("sin cuota gratuita disponible")
        self.detalle = detalle
        self.reintentar_en_segundos = reintentar_en_segundos


def transporte_http(url: str, headers: dict[str, str], cuerpo: dict | None,
                    timeout: int, metodo: str = "POST") -> dict:
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    peticion = urllib.request.Request(
        url, data=datos, method=metodo,
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            crudo = respuesta.read(4 * 1024 * 1024).decode("utf-8", errors="replace")
            try:
                return json.loads(crudo)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"respuesta no JSON: {crudo[:200]}") from exc
    except urllib.error.HTTPError as exc:
        detalle = exc.read(2048).decode("utf-8", errors="replace")
        error = RuntimeError(f"HTTP {exc.code}: {detalle[:300]}")
        error.codigo_http = exc.code  # type: ignore[attr-defined]
        error.reintentar_en = _retry_after(exc.headers)  # type: ignore[attr-defined]
        raise error from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"fallo de red: {exc}") from exc


def _retry_after(headers) -> int | None:
    valor = headers.get("retry-after") if headers else None
    if valor and str(valor).strip().isdigit():
        return int(str(valor).strip())
    return None


@dataclass
class Politica:
    habilitada: bool = False
    cascada: tuple[str, ...] = CASCADA_POR_DEFECTO
    proveedores_habilitados: frozenset[str] = PROVEEDORES_ACTIVOS
    presupuesto_mensual_usd: float = 0.0
    autorizo_pago: bool = False
    llamadas_por_corrida: int = 0
    permitir_datos_de_ofertas: bool = False
    usar_cache: bool = True
    reintentos: int = 2
    timeout_s: int = 45

    @classmethod
    def desde_ajustes(cls, conn: sqlite3.Connection) -> "Politica":
        cascada_cruda = db.ajuste(conn, "ia_cascada", "")
        cascada = tuple(p.strip() for p in cascada_cruda.split(",") if p.strip()) or CASCADA_POR_DEFECTO
        habilitados = db.ajuste(conn, "ia_proveedores_habilitados", ",".join(PROVEEDORES_ACTIVOS))
        return cls(
            habilitada=db.ajuste(conn, "ia_habilitada", "0") == "1",
            cascada=tuple(r for r in cascada if parsear(r)),
            proveedores_habilitados=frozenset(
                p.strip() for p in habilitados.split(",") if p.strip() in PROVEEDORES
            ),
            presupuesto_mensual_usd=_flotante(db.ajuste(conn, "ia_presupuesto_usd", "0")),
            autorizo_pago=db.ajuste(conn, "ia_autorizo_pago", "0") == "1",
            llamadas_por_corrida=int(_flotante(db.ajuste(conn, "ia_llamadas_por_corrida", "0"))),
            permitir_datos_de_ofertas=db.ajuste(conn, "ia_datos_ofertas", "0") == "1",
            usar_cache=db.ajuste(conn, "ia_cache", "1") == "1",
            reintentos=int(_flotante(db.ajuste(conn, "ia_reintentos", "2"))),
            timeout_s=int(_flotante(db.ajuste(conn, "ia_timeout_s", "45"))),
        )


def _flotante(valor: str) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


def periodo(ahora: datetime | None = None) -> str:
    return (ahora or datetime.now(timezone.utc)).strftime("%Y-%m")


def presupuesto(conn: sqlite3.Connection, limite: float | None = None) -> dict:
    mes = periodo()
    fila = conn.execute("SELECT * FROM ai_budget WHERE periodo=?", (mes,)).fetchone()
    if fila is None:
        with db.transaccion(conn):
            conn.execute(
                "INSERT INTO ai_budget (periodo, limite_usd, gastado_usd, llamadas, actualizado_en)"
                " VALUES (?,?,0,0,?)",
                (mes, limite if limite is not None else 0.0, config.ahora_utc()),
            )
        fila = conn.execute("SELECT * FROM ai_budget WHERE periodo=?", (mes,)).fetchone()
    tope = float(fila["limite_usd"])
    gastado = float(fila["gastado_usd"])
    return {
        "periodo": mes,
        "limite_usd": tope,
        "gastado_usd": round(gastado, 6),
        "disponible_usd": round(max(tope - gastado, 0.0), 6),
        "llamadas": int(fila["llamadas"]),
        "sin_tope": tope <= 0,
    }


def fijar_limite(conn: sqlite3.Connection, limite: float) -> dict:
    presupuesto(conn)
    with db.transaccion(conn):
        conn.execute(
            "UPDATE ai_budget SET limite_usd=?, actualizado_en=? WHERE periodo=?",
            (limite, config.ahora_utc(), periodo()),
        )
    return presupuesto(conn, limite)


@dataclass
class Candidato:
    proveedor: Proveedor
    modelo: Modelo
    estado: str = "listo"
    motivo: str = ""

    @property
    def referencia(self) -> str:
        return f"{self.proveedor.clave}:{self.modelo.id}"


class Cliente:
    def __init__(self, conn: sqlite3.Connection, politica: Politica | None = None,
                 transporte=transporte_http) -> None:
        self.conn = conn
        self.politica = politica or Politica.desde_ajustes(conn)
        self.transporte = transporte
        self.llamadas = 0

    # --- credenciales ----------------------------------------------------
    def _credencial(self, proveedor: Proveedor) -> dict:
        """Resuelve la clave: huella activa > almacén > variable de entorno."""
        preferida = db.ajuste(self.conn, "ia_credencial_activa", "") or None
        return credenciales.resolver(proveedor.clave, proveedor.variable_clave, preferida)

    def _clave(self, proveedor: Proveedor) -> str | None:
        return self._credencial(proveedor).get("valor")

    def estado_credencial(self, proveedor: Proveedor) -> str:
        guardado = db.ajuste(self.conn, f"ia_estado_{proveedor.clave}", "")
        resuelta = self._credencial(proveedor)
        if resuelta.get("valor"):
            return guardado if guardado in {"verificada", "invalida"} else "presente"
        return "ausente"

    # --- cascada ---------------------------------------------------------
    def candidatos(self, complejidad: str = "rapido") -> list[Candidato]:
        """Ordena la cascada según la dificultad del caso y el estado real."""
        minimo = NIVELES.get(complejidad, 0)
        lista: list[Candidato] = []
        for referencia in self.politica.cascada:
            par = parsear(referencia)
            if par is None:
                continue
            proveedor, modelo = par
            candidato = Candidato(proveedor, modelo)
            if proveedor.clave not in self.politica.proveedores_habilitados:
                candidato.estado, candidato.motivo = "deshabilitado", "proveedor deshabilitado"
            elif not self._clave(proveedor):
                candidato.estado, candidato.motivo = "sin_credencial", "falta la clave"
            elif proveedor.requiere_pago and not self.politica.autorizo_pago:
                candidato.estado, candidato.motivo = "pago_no_autorizado", "requiere autorización de gasto"
            else:
                ok, motivo = cuotas.verificar(self.conn, proveedor, modelo)
                if not ok:
                    candidato.estado, candidato.motivo = "sin_cuota", motivo
            lista.append(candidato)

        lista.sort(key=lambda c: (
            0 if c.estado == "listo" else 1,
            0 if NIVELES.get(c.modelo.nivel, 0) >= minimo else 1,
            NIVELES.get(c.modelo.nivel, 0),
        ))
        return lista

    def verificar(self) -> tuple[bool, str]:
        if not self.politica.habilitada:
            return False, "la IA está desactivada en Configuración"
        listos = [c for c in self.candidatos("rapido") if c.estado == "listo"]
        if not listos:
            return False, "ningún modelo de la cascada tiene credencial y cuota disponibles"
        return True, f"{len(listos)} modelo(s) disponibles; primero {listos[0].referencia}"

    # --- costos ----------------------------------------------------------
    def costo(self, modelo: Modelo, tokens_entrada: int, tokens_salida: int) -> float:
        return (tokens_entrada / 1_000_000 * modelo.usd_entrada_1m
                + tokens_salida / 1_000_000 * modelo.usd_salida_1m)

    # --- llamada ---------------------------------------------------------
    def analizar(self, contenido: str, instruccion: str, contenido_hash: str,
                 proposito: str = "analisis", complejidad: str = "rapido",
                 job_id: str | None = None, max_tokens: int = 900) -> dict:
        if not self.politica.habilitada:
            raise Rechazo("la IA está desactivada en Configuración", "no_habilitada")
        if not self.politica.permitir_datos_de_ofertas:
            raise Rechazo(
                "enviar contenido de ofertas a un servicio externo requiere habilitar "
                "'ia_datos_ofertas' en Configuración", "datos_no_autorizados",
            )
        if self.politica.llamadas_por_corrida and self.llamadas >= self.politica.llamadas_por_corrida:
            raise Rechazo(f"cuota de la corrida agotada ({self.politica.llamadas_por_corrida})",
                          "cuota_corrida")

        if self.politica.usar_cache:
            previo = cache_mod.obtener(self.conn, cache_mod.clave(contenido_hash, "cascada"))
            if previo is not None:
                try:
                    analisis_previo = AnalisisIA.model_validate(previo.get("analisis") or {})
                except Exception:  # noqa: BLE001 - caché de una versión anterior
                    analisis_previo = None
                if analisis_previo is not None:
                    return {**previo, "analisis": analisis_previo, "cache": True,
                            "proveedor": "cache", "modelo": "cache", "costo_usd": 0.0}

        candidatos = [c for c in self.candidatos(complejidad) if c.estado == "listo"]
        if not candidatos:
            detalle = [{"referencia": c.referencia, "motivo": c.motivo}
                       for c in self.candidatos(complejidad)]
            raise SinCuota(detalle)

        fallos: list[dict] = []
        for candidato in candidatos:
            try:
                resultado = self._intentar(candidato, instruccion, contenido, proposito,
                                           job_id, max_tokens)
            except SinCuota as exc:
                fallos.extend(exc.detalle)
                continue
            except Rechazo:
                raise
            except Exception as exc:  # noqa: BLE001 - se intenta el siguiente modelo
                fallos.append({"referencia": candidato.referencia, "motivo": repr(exc)[:200]})
                continue
            if self.politica.usar_cache:
                para_cache = {
                    clave_: (valor.model_dump() if hasattr(valor, "model_dump") else valor)
                    for clave_, valor in resultado.items()
                    if clave_ != "cache"
                }
                cache_mod.guardar(
                    self.conn, cache_mod.clave(contenido_hash, "cascada"),
                    candidato.proveedor.clave, candidato.modelo.id, para_cache,
                )
            resultado["cache"] = False
            resultado["fallos_previos"] = fallos
            return resultado

        raise SinCuota(fallos or [{"referencia": "-", "motivo": "sin candidatos"}])

    def _intentar(self, candidato: Candidato, instruccion: str, contenido: str,
                  proposito: str, job_id: str | None, max_tokens: int) -> dict:
        proveedor, modelo = candidato.proveedor, candidato.modelo
        ok, motivo = cuotas.verificar(self.conn, proveedor, modelo,
                                      tokens_estimados=len(contenido) // 3)
        if not ok:
            raise SinCuota([{"referencia": candidato.referencia, "motivo": motivo}])

        tokens_entrada = max(1, (len(instruccion) + len(contenido)) // 4)
        costo_estimado = self.costo(modelo, tokens_entrada, max_tokens)
        saldo = presupuesto(self.conn, self.politica.presupuesto_mensual_usd)
        if costo_estimado > 0 and (saldo["sin_tope"] or costo_estimado > saldo["disponible_usd"]):
            raise Rechazo(
                f"la llamada costaría USD {costo_estimado:.6f} y no hay presupuesto autorizado",
                "presupuesto",
            )

        credencial = self._credencial(proveedor)
        url, headers, cuerpo = self._armar(proveedor, modelo, instruccion, contenido, max_tokens)
        inicio = time.perf_counter()
        try:
            respuesta = self.transporte(url, headers, cuerpo, self.politica.timeout_s)
        except Exception as exc:  # noqa: BLE001 - se registra y se propaga
            duracion = int((time.perf_counter() - inicio) * 1000)
            self._registrar(proveedor, modelo, proposito, job_id, tokens_entrada, 0,
                            round(costo_estimado, 8), "error", repr(exc)[:400], duracion, 0,
                            credencial)
            codigo = getattr(exc, "codigo_http", None)
            if codigo in (401, 403):
                db.guardar_ajuste(self.conn, f"ia_estado_{proveedor.clave}", "invalida")
            if codigo == 429:
                espera = getattr(exc, "reintentar_en", None) or 60
                raise SinCuota([{"referencia": candidato.referencia,
                                 "motivo": f"429; reintentar en {espera} s"}],
                               reintentar_en_segundos=int(espera)) from exc
            raise

        texto, tokens_salida = self._extraer(proveedor, respuesta)
        duracion = int((time.perf_counter() - inicio) * 1000)
        try:
            analisis = desde_texto(texto)
        except Exception as exc:  # noqa: BLE001 - respuesta inválida
            self._registrar(proveedor, modelo, proposito, job_id, tokens_entrada,
                            tokens_salida, round(self.costo(modelo, tokens_entrada, tokens_salida), 8),
                            "invalida", f"no valida el esquema: {exc}"[:400], duracion, 1,
                            credencial)
            raise RuntimeError(f"respuesta inválida de {candidato.referencia}") from exc

        costo_real = self.costo(modelo, tokens_entrada, tokens_salida)
        self._registrar(proveedor, modelo, proposito, job_id, tokens_entrada, tokens_salida,
                        round(costo_real, 8), "ok", None, duracion, 1, credencial)
        cuotas.registrar(self.conn, proveedor.clave, modelo.id, tokens_entrada, tokens_salida)
        if costo_real > 0:
            with db.transaccion(self.conn):
                self.conn.execute(
                    "UPDATE ai_budget SET gastado_usd = gastado_usd + ?, llamadas = llamadas + 1,"
                    " actualizado_en=? WHERE periodo=?",
                    (costo_real, config.ahora_utc(), periodo()),
                )
        db.guardar_ajuste(self.conn, f"ia_estado_{proveedor.clave}", "verificada")
        if credencial.get("huella"):
            # La que funcionó queda como preferida: una variable vieja no vuelve a taparla.
            db.guardar_ajuste(self.conn, "ia_credencial_activa", credencial["huella"])
        self.llamadas += 1
        return {
            "analisis": analisis,
            "texto": texto,
            "proveedor": proveedor.clave,
            "modelo": modelo.id,
            "tokens_entrada": tokens_entrada,
            "tokens_salida": tokens_salida,
            "costo_usd": round(costo_real, 8),
            "duracion_ms": duracion,
        }

    def _registrar(self, proveedor: Proveedor, modelo: Modelo, proposito: str,
                   job_id: str | None, entrada: int, salida: int, costo: float,
                   estado: str, error: str | None, duracion: int, cuota: int,
                   credencial: dict | None = None) -> None:
        credencial = credencial or {}
        with db.transaccion(self.conn):
            self.conn.execute(
                """INSERT INTO ai_calls (proveedor, modelo, proposito, job_id, tokens_entrada,
                       tokens_salida, costo_usd, estado, error, creado_en, duracion_ms,
                       cuota_consumida, huella_credencial)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (proveedor.clave, modelo.id, proposito, job_id, entrada, salida, costo,
                 estado, redactar(error)[:500], config.ahora_utc(), duracion, cuota,
                 credencial.get("huella")),
            )

    def _armar(self, proveedor: Proveedor, modelo: Modelo, instruccion: str,
               contenido: str, max_tokens: int) -> tuple[str, dict, dict]:
        clave = self._clave(proveedor) or ""
        if proveedor.familia == "gemini":
            # La clave va por cabecera: en la URL termina en logs de proxy y en
            # mensajes de error. Google documenta `x-goog-api-key` para esto.
            url = proveedor.endpoint.format(modelo=modelo.id)
            return url, {"x-goog-api-key": clave}, {
                "systemInstruction": {"parts": [{"text": instruccion}]},
                "contents": [{"role": "user", "parts": [{"text": contenido}]}],
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                },
            }
        if proveedor.familia == "cloudflare":
            variable = proveedor.extra.get("cuenta_variable", "")
            cuenta = os.environ.get(variable, "") or db.ajuste(self.conn, "ia_cuenta_cloudflare", "")
            if not cuenta:
                raise Rechazo("falta el identificador de cuenta de Cloudflare", "sin_cuenta")
            return proveedor.endpoint.format(cuenta=cuenta), {"Authorization": f"Bearer {clave}"}, {
                "model": modelo.id,
                "messages": [{"role": "system", "content": instruccion},
                             {"role": "user", "content": contenido}],
                "max_tokens": max_tokens,
                "temperature": 0.1,
            }
        return proveedor.endpoint, {"Authorization": f"Bearer {clave}"}, {
            "model": modelo.id,
            "messages": [{"role": "system", "content": instruccion},
                         {"role": "user", "content": contenido}],
            "max_tokens": max_tokens,
            "temperature": 0.1,
        }

    def _extraer(self, proveedor: Proveedor, respuesta: dict) -> tuple[str, int]:
        if proveedor.familia == "gemini":
            candidatos = respuesta.get("candidates") or []
            if not candidatos:
                raise RuntimeError("la respuesta de Gemini no trae candidatos")
            partes = (candidatos[0].get("content") or {}).get("parts") or []
            texto = "".join(p.get("text", "") for p in partes).strip()
            uso = respuesta.get("usageMetadata") or {}
            return texto, int(uso.get("candidatesTokenCount") or 0)
        opciones = respuesta.get("choices") or []
        if not opciones:
            raise RuntimeError("la respuesta no trae 'choices'")
        texto = ((opciones[0].get("message") or {}).get("content") or "").strip()
        uso = respuesta.get("usage") or {}
        return texto, int(uso.get("completion_tokens") or 0)

    # --- diagnóstico -----------------------------------------------------
    def probar_conexion(self, clave_modelo: str, consumir_cuota: bool = True) -> dict:
        """Prueba real y acotada. Informa si consume cuota."""
        par = parsear(clave_modelo)
        if par is None:
            return {"ok": False, "estado": "modelo_desconocido", "detalle": clave_modelo,
                    "consumio_cuota": False}
        proveedor, modelo = par
        credencial = self._credencial(proveedor)
        if not credencial.get("valor"):
            return {"ok": False, "estado": "ausente", "detalle": "falta la clave",
                    "consumio_cuota": False}
        inicio = time.perf_counter()
        try:
            url, headers, cuerpo = self._armar(proveedor, modelo,
                                               'Respondé sólo con {"ok": true}', "Prueba.", 20)
            respuesta = self.transporte(url, headers, cuerpo, self.politica.timeout_s)
            texto, tokens_salida = self._extraer(proveedor, respuesta)
        except Exception as exc:  # noqa: BLE001
            codigo = getattr(exc, "codigo_http", None)
            estado = "invalida" if codigo in (401, 403) else "error"
            db.guardar_ajuste(self.conn, f"ia_estado_{proveedor.clave}", estado)
            # Una petición rechazada (clave inválida, sin permiso, cuota) no
            # consume cuota de generación: registrarla como consumida infla el
            # gasto y hace creer que el modelo está funcionando.
            self._registrar(proveedor, modelo, "prueba", None, 0, 0, 0.0, estado,
                            repr(exc)[:400], int((time.perf_counter() - inicio) * 1000),
                            0, credencial)
            return {"ok": False, "estado": estado, "detalle": repr(exc)[:300],
                    "consumio_cuota": False}
        duracion = int((time.perf_counter() - inicio) * 1000)
        self._registrar(proveedor, modelo, "prueba", None, 0, tokens_salida, 0.0, "ok", None,
                        duracion, 1 if consumir_cuota else 0, credencial)
        db.guardar_ajuste(self.conn, f"ia_estado_{proveedor.clave}", "verificada")
        if credencial.get("huella"):
            db.guardar_ajuste(self.conn, "ia_credencial_activa", credencial["huella"])
        return {"ok": True, "estado": "verificada", "detalle": texto[:120],
                "consumio_cuota": consumir_cuota, "duracion_ms": duracion}

    def verificar_modelos(self, clave_proveedor: str) -> dict:
        """Consulta el catálogo del proveedor y contrasta los identificadores."""
        proveedor = obtener_proveedor(clave_proveedor)
        if proveedor is None:
            return {"ok": False, "detalle": "proveedor desconocido", "presentes": [], "ausentes": []}
        credencial = self._credencial(proveedor)
        clave = credencial.get("valor")
        huella = credencial.get("huella")
        if not clave:
            return {"ok": False, "detalle": "falta la clave", "estado": "ausente",
                    "presentes": [], "ausentes": [m.id for m in proveedor.modelos]}
        if proveedor.familia == "gemini":
            # Cabecera, no `?key=`: una clave en la URL termina en logs de proxy
            # y en el mensaje de cualquier excepción que incluya la dirección.
            url = "https://generativelanguage.googleapis.com/v1beta/models"
            headers: dict[str, str] = {"x-goog-api-key": clave}
        elif proveedor.clave == "groq":
            url = "https://api.groq.com/openai/v1/models"
            headers = {"Authorization": f"Bearer {clave}"}
        elif proveedor.clave == "deepseek":
            url = "https://api.deepseek.com/models"
            headers = {"Authorization": f"Bearer {clave}"}
        else:
            return {"ok": False, "estado": "no_verificable", "presentes": [],
                    "ausentes": [m.id for m in proveedor.modelos],
                    "detalle": "Cloudflare requiere el identificador de cuenta"}
        try:
            datos = self.transporte(url, headers, None, self.politica.timeout_s, "GET")
        except Exception as exc:  # noqa: BLE001
            codigo = getattr(exc, "codigo_http", None)
            estado = "invalida" if codigo in (400, 401, 403) else "error"
            if estado == "invalida":
                db.guardar_ajuste(self.conn, f"ia_estado_{proveedor.clave}", "invalida")
            self._registrar_check(proveedor.clave, None, estado, repr(exc)[:300], 0, huella)
            return {"ok": False, "estado": estado, "detalle": repr(exc)[:200],
                    "presentes": [], "ausentes": [m.id for m in proveedor.modelos]}
        disponibles = set()
        for entrada in (datos.get("data") or datos.get("models") or []):
            identificador = entrada.get("id") or entrada.get("name") or ""
            if identificador.startswith("models/"):
                identificador = identificador.split("/", 1)[1]
            disponibles.add(identificador)
        presentes = [m.id for m in proveedor.modelos if m.id in disponibles]
        ausentes = [m.id for m in proveedor.modelos if m.id not in disponibles]
        estado_ = "verificada" if presentes else "sin_coincidencias"
        if presentes:
            db.guardar_ajuste(self.conn, f"ia_estado_{proveedor.clave}", "verificada")
        self._registrar_check(proveedor.clave, None, estado_,
                              f"{len(presentes)} de {len(proveedor.modelos)} presentes", 0, huella)
        return {
            "ok": True,
            "estado": estado_,
            "presentes": presentes,
            "ausentes": ausentes,
            "total_proveedor": len(disponibles),
        }

    def _registrar_check(self, proveedor: str, modelo: str | None, estado: str,
                         detalle: str, consumio: int, huella: str | None = None) -> None:
        with db.transaccion(self.conn):
            self.conn.execute(
                "INSERT INTO ai_model_checks (proveedor, modelo, estado, detalle,"
                " consumio_cuota, creado_en, huella_credencial) VALUES (?,?,?,?,?,?,?)",
                (proveedor, modelo, estado, (detalle or "")[:400], consumio,
                 config.ahora_utc(), huella),
            )


def consumo(conn: sqlite3.Connection) -> dict:
    """Solicitudes, tokens, cuota y gasto, separando éxitos de intentos fallidos."""
    def resumen(desde: str | None = None) -> dict:
        where = "WHERE substr(creado_en,1,10)=substr(?,1,10)" if desde else ""
        params = (desde,) if desde else ()
        fila = conn.execute(
            f"""SELECT
                   COALESCE(SUM(CASE WHEN estado='ok' THEN 1 ELSE 0 END),0) AS exitosas,
                   COALESCE(SUM(CASE WHEN estado<>'ok' THEN 1 ELSE 0 END),0) AS fallidas,
                   COALESCE(SUM(CASE WHEN estado='ok' THEN tokens_entrada ELSE 0 END),0) AS tok_in,
                   COALESCE(SUM(CASE WHEN estado='ok' THEN tokens_salida ELSE 0 END),0) AS tok_out,
                   COALESCE(SUM(cuota_consumida),0) AS cuota,
                   COALESCE(SUM(costo_usd),0) AS costo
               FROM ai_calls {where}""",
            params,
        ).fetchone()
        return {
            "solicitudes_exitosas": int(fila["exitosas"]),
            "intentos_fallidos": int(fila["fallidas"]),
            "tokens_entrada": int(fila["tok_in"]),
            "tokens_salida": int(fila["tok_out"]),
            "cuota_consumida": int(fila["cuota"]),
            "costo_usd": round(float(fila["costo"]), 8),
        }

    por_huella = [
        dict(f) for f in conn.execute(
            """SELECT COALESCE(huella_credencial,'sin-huella') AS huella,
                      COUNT(*) AS intentos,
                      SUM(CASE WHEN estado='ok' THEN 1 ELSE 0 END) AS exitosas,
                      MAX(creado_en) AS ultima
               FROM ai_calls GROUP BY huella ORDER BY intentos DESC"""
        ).fetchall()
    ]
    return {
        "total": resumen(),
        "hoy": resumen(config.ahora_utc()),
        "por_credencial": por_huella,
        "presupuesto": presupuesto(conn),
    }


def estado(conn: sqlite3.Connection) -> dict:
    politica = Politica.desde_ajustes(conn)
    cliente = Cliente(conn, politica)
    try:
        listo, motivo = cliente.verificar()
    except Rechazo as exc:
        listo, motivo = False, exc.motivo
    candidatos = [
        {
            "referencia": c.referencia,
            "proveedor": c.proveedor.clave,
            "nombre": c.proveedor.nombre,
            "modelo": c.modelo.id,
            "nivel": c.modelo.nivel,
            "gratuito": c.modelo.dentro_cuota_gratuita,
            "estado": c.estado,
            "motivo": c.motivo,
            "credencial": cliente.estado_credencial(c.proveedor),
            "requiere_pago": c.proveedor.requiere_pago,
        }
        for c in cliente.candidatos("rapido")
    ]
    return {
        "politica": {
            "habilitada": politica.habilitada,
            "cascada": list(politica.cascada),
            "proveedores_habilitados": sorted(politica.proveedores_habilitados),
            "presupuesto_mensual_usd": politica.presupuesto_mensual_usd,
            "autorizo_pago": politica.autorizo_pago,
            "llamadas_por_corrida": politica.llamadas_por_corrida,
            "datos_de_ofertas": politica.permitir_datos_de_ofertas,
            "cache": politica.usar_cache,
        },
        "listo": listo,
        "motivo": motivo,
        "candidatos": candidatos,
        "presupuesto": presupuesto(conn, politica.presupuesto_mensual_usd),
        "cuotas": cuotas.resumen(conn),
        "consumo": consumo(conn),
        "credencial_activa": db.ajuste(conn, "ia_credencial_activa", "") or None,
        "cache": cache_mod.estadisticas(conn),
        "ultimas": [
            dict(f) for f in conn.execute(
                "SELECT proveedor, modelo, proposito, tokens_entrada, tokens_salida, costo_usd,"
                " estado, duracion_ms, cuota_consumida, creado_en FROM ai_calls"
                " ORDER BY id DESC LIMIT 12"
            ).fetchall()
        ],
    }


def catalogo_para_ui() -> list[dict]:
    return catalogo_modelos()
