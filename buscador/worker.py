"""Trabajador de una corrida: fuentes, cola, clasificación y avisos."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

from . import (adapters, config, db, ingest, incidents, logs, merge, notify, perfil as perfil_mod,
               progreso, queue, rules)
from .adapters.base import ResultadoFuente
from .textutil import hash_semantico

PERFIL_DEMO = {  # sólo para pruebas y demostración
    
    "version": "perfil-demo-1",
    "origen": "sintetico_demostracion",
    "requiere_confirmacion": True,
    "nota": (
        "Perfil de demostración para recorrer el flujo completo. No es el CV de ninguna persona real "
        "y debe reemplazarse por datos verificados antes de tratar los resultados como reales."
    ),
    "habilidades": [
        {"nombre": "SQL", "evidencia": "portfolio propio de análisis"},
        {"nombre": "Python", "evidencia": "portfolio propio de análisis"},
        {"nombre": "Excel", "evidencia": "uso declarado en el plan"},
        {"nombre": "Power BI", "evidencia": "portfolio propio de auditoría"},
        {"nombre": "PostgreSQL", "evidencia": "portfolio propio de auditoría"},
        {"nombre": "Google Sheets", "evidencia": "automatizaciones propias"},
        {"nombre": "Apps Script", "evidencia": "agente de búsqueda propio"},
        {"nombre": "Git", "evidencia": "repositorios propios"},
        {"nombre": "ETL", "evidencia": "portfolio propio de datos"},
    ],
    "idioma": {"ingles": "B2", "espanol": "nativo"},
    "experiencia": {"anios": 1, "nivel": "junior"},
    "territorio": {"residencia": "Argentina", "remoto": True, "presencial": ["La Plata"]},
    "categorias": rules.CATEGORIAS,
    "salario": {
        "ars_neto_referencia": None,
        "ars_neto_objetivo": None,
        "usd_hora_freelance": None,
        "nota": "sin valores: se cargan en el perfil local, fuera del repositorio",
    },
    "disponibilidad": {"desde": "inmediata", "horas_semana": 40},
}


class MutexOcupado(RuntimeError):
    pass


class Mutex:
    """Exclusión de corridas con un archivo bloqueado por el sistema operativo."""

    def __init__(self, ruta: Path) -> None:
        self.ruta = ruta
        self._archivo = None

    def adquirir(self) -> bool:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._archivo = open(self.ruta, "a+")
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self._archivo.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._archivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self._archivo.close()
            self._archivo = None
            return False

    def liberar(self) -> None:
        if self._archivo is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                self._archivo.seek(0)
                msvcrt.locking(self._archivo.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._archivo.fileno(), fcntl.LOCK_UN)
        finally:
            self._archivo.close()
            self._archivo = None

    def __enter__(self) -> "Mutex":
        if not self.adquirir():
            raise MutexOcupado("ya hay una corrida activa")
        return self

    def __exit__(self, *exc) -> None:
        self.liberar()


def asegurar_perfil(conn: sqlite3.Connection, rutas: config.Rutas) -> dict:
    if rutas.perfil.exists():
        datos = json.loads(rutas.perfil.read_text(encoding="utf-8"))
    else:
        datos = perfil_mod.perfil(rutas)
        rutas.perfil.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    version = str(datos.get("version") or hash_semantico(datos)[:12])
    datos["version"] = version
    fila = conn.execute("SELECT id FROM profile_versions WHERE version=?", (version,)).fetchone()
    with db.transaccion(conn):
        if fila is None:
            cur = conn.execute(
                "INSERT INTO profile_versions (version, perfil_json, origen, creado_en, activo) VALUES (?,?,?,?,1)",
                (version, json.dumps(datos, ensure_ascii=False), datos.get("origen", "manual"), config.ahora_utc()),
            )
            profile_id = int(cur.lastrowid)
        else:
            profile_id = int(fila["id"])
        conn.execute("UPDATE profile_versions SET activo=0 WHERE id<>?", (profile_id,))
        conn.execute("UPDATE profile_versions SET activo=1 WHERE id=?", (profile_id,))
    return {"id": profile_id, "datos": datos, "version": version}


def guardar_perfil(conn: sqlite3.Connection, rutas: config.Rutas, datos: dict,
                   origen: str = "manual", procesar: bool = True) -> dict:
    """Persiste el perfil, crea una versión nueva y fuerza la reclasificación.

    Cambiar el perfil invalida **todos** los análisis: los puntajes dependen de
    él. Por eso se marcan obsoletos y se reencola todo.

    `procesar=True` paga esa deuda en el acto. Si un llamador lo desactiva —la
    interfaz, para no bloquear el request— queda obligado a drenar la cola por su
    cuenta; si no lo hace, el catálogo queda vacío y la aplicación muestra cero
    clasificaciones vigentes aunque la cola esté llena. Ese fue el incidente del
    07/11: perfiles v3 guardados desde la web, 1 280 tareas encoladas y nada que
    las procesara.
    """
    datos = dict(datos)
    datos["version"] = f"perfil-{config.ahora_utc().replace(':', '').replace('-', '')}"
    datos["origen"] = origen
    datos["requiere_confirmacion"] = origen == "sintetico_demostracion"
    rutas.perfil.parent.mkdir(parents=True, exist_ok=True)
    rutas.perfil.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    perfil = asegurar_perfil(conn, rutas)
    with db.transaccion(conn):
        conn.execute("UPDATE analyses SET obsoleto=1")
    encoladas = reclasificar_todo(conn, perfil["id"])
    perfil["encoladas"] = encoladas
    perfil["reclasificacion"] = procesar_pendientes(conn) if procesar else {"procesadas": 0,
                                                                          "omitido": "diferida"}
    return perfil


def reclasificar_faltantes(conn: sqlite3.Connection, maximo: int = 20000) -> dict:
    """Encola y clasifica las ofertas que quedaron sin análisis vigente.

    Cierra el hueco entre «no hay tareas pendientes» y «hay ofertas sin
    clasificar»: puede haber ofertas cuya tarea se completó y cuyo análisis se
    invalidó después sin que nadie lo reemplazara.
    """
    faltantes = [
        fila["id"] for fila in conn.execute(
            """SELECT j.id FROM jobs j
               WHERE j.merged_into IS NULL
                 AND NOT EXISTS (SELECT 1 FROM analyses a
                                  WHERE a.job_id=j.id AND a.obsoleto=0)""").fetchall()
    ]
    encoladas = 0
    perfil = asegurar_perfil(conn, config.rutas())
    for job_id in faltantes:
        version = ingest._asegurar_version(conn, job_id)
        clave = f"clasificar:{job_id}:{version}:{perfil['id']}:{config.RULES_VERSION}"
        if queue.encolar(conn, "clasificar", clave, reencolar_si_completada=True,
                         job_id=job_id, job_version_id=version,
                         profile_version_id=perfil["id"]):
            encoladas += 1
    resultado = procesar_pendientes(conn, maximo=maximo)
    resultado["faltantes"] = len(faltantes)
    resultado["encoladas_ahora"] = encoladas
    if faltantes:
        logs.registrar("faltantes_encoladas", faltantes=len(faltantes), encoladas=encoladas)
    return resultado


def procesar_pendientes(conn: sqlite3.Connection, maximo: int = 20000,
                        usar_mutex: bool = True) -> dict:
    """Drena la cola de clasificación: determinista, sin red y sin IA.

    No consulta fuentes, no llama a ningún proveedor y no gasta cuota: sólo aplica
    las reglas a las ofertas que ya están guardadas. Es la operación que faltaba
    cuando la cola quedaba encolada por un cambio de perfil o de reglas.

    Si hay una corrida en curso no hace nada: esa corrida drena la cola al
    terminar, y dos escritores sobre las mismas tareas se pisarían.
    """
    antes = queue.contar(conn)
    pendientes = antes.get("queued", 0) + antes.get("deferred", 0) + antes.get("running", 0)
    if not pendientes:
        return {"procesadas": 0, "recuperadas": 0, "antes": antes, "despues": antes,
                "omitido": "", "duracion_ms": 0.0}

    mutex = Mutex(config.rutas().lock) if usar_mutex else None
    if mutex is not None and not mutex.adquirir():
        return {"procesadas": 0, "recuperadas": 0, "antes": antes, "despues": antes,
                "omitido": "hay una corrida en curso", "duracion_ms": 0.0}
    try:
        epoch = uuid.uuid4().hex
        recuperadas = queue.recuperar_tareas(conn, epoch)
        perfil = asegurar_perfil(conn, config.rutas())
        # La cola puede traer trabajo planeado para un perfil anterior: procesarlo
        # escribiría análisis de un perfil que ya no está activo.
        descartadas = queue.descartar_obsoletas(conn, perfil["id"])
        inicio = time.perf_counter()
        procesadas = procesar_tareas(conn, epoch, maximo=maximo, perfil=perfil)
        duracion = round((time.perf_counter() - inicio) * 1000, 1)
        despues = queue.contar(conn)
        logs.registrar("cola_procesada", procesadas=procesadas, recuperadas=recuperadas,
                       descartadas=descartadas, antes=antes, despues=despues,
                       duracion_ms=duracion)
        return {"procesadas": procesadas, "recuperadas": recuperadas,
                "descartadas": descartadas, "antes": antes, "despues": despues,
                "omitido": "", "duracion_ms": duracion}
    finally:
        if mutex is not None:
            mutex.liberar()


def reclasificar_todo(conn: sqlite3.Connection, profile_version_id: int) -> int:
    """Encola la clasificación de todas las ofertas vigentes para el perfil nuevo."""
    filas = conn.execute("SELECT id, semantic_hash FROM jobs").fetchall()
    encoladas = 0
    for fila in filas:
        job_version_id = ingest._asegurar_version(conn, fila["id"])
        clave = f"clasificar:{fila['id']}:{job_version_id}:{profile_version_id}:{config.RULES_VERSION}"
        ahora = config.ahora_utc()
        with db.transaccion(conn):
            # Reencolar siempre: una tarea ya completada con la misma clave debe
            # volver a la cola, o la reclasificación no haría nada. Salvo que la
            # esté ejecutando otro: robarle la tarea dejaría dos escritores sobre
            # la misma oferta.
            cur = conn.execute(
                """INSERT INTO tasks (kind, unique_key, job_id, job_version_id, profile_version_id,
                       rules_version, estado, intentos, next_due, creado_en, actualizado_en)
                   VALUES ('clasificar', ?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?)
                   ON CONFLICT(unique_key) DO UPDATE SET
                       estado='queued', intentos=0, next_due=excluded.next_due,
                       locked_by_epoch=NULL, locked_at=NULL, error=NULL,
                       actualizado_en=excluded.actualizado_en
                   WHERE estado <> 'running'""",
                (clave, fila["id"], job_version_id, profile_version_id, config.RULES_VERSION,
                 ahora, ahora, ahora),
            )
        encoladas += 1 if cur.rowcount is not None else 0
    return encoladas


def sincronizar_reglas(conn: sqlite3.Connection, profile_version_id: int) -> int:
    """Reclasifica si cambió la versión de reglas: evita análisis de dos épocas.

    Sin esto, una corrida nueva convive con análisis viejos y el listado mezcla
    criterios distintos sin avisar.
    """
    desactualizados = conn.execute(
        "SELECT COUNT(*) FROM analyses WHERE obsoleto=0 AND rules_version<>?",
        (config.RULES_VERSION,),
    ).fetchone()[0]
    if not desactualizados:
        return 0
    with db.transaccion(conn):
        conn.execute("UPDATE analyses SET obsoleto=1 WHERE rules_version<>?", (config.RULES_VERSION,))
    encoladas = reclasificar_todo(conn, profile_version_id)
    logs.registrar("reglas_sincronizadas", analisis_obsoletos=desactualizados, encoladas=encoladas)
    return encoladas


def correr(causa: str = "manual", limite: int | None = None,
           fuentes: list[str] | None = None, usar_mutex: bool = True) -> dict:
    """Una corrida completa: fuentes, ingesta, clasificación y avisos.

    El progreso se publica escribiendo en la base (`runs.heartbeat_at` y el
    estado de cada fila de `source_runs`), no llamando a la interfaz. Así el
    panel se puede abrir desde cualquier pestaña, recargar la página o esperar a
    que termine sin perder nada.

    Dos detalles que hacen visible el avance antes del final:

    - las fuentes se planifican en `pending` antes de consultar la primera, así
      hay un total real contra el que medir;
    - la cola de clasificación se drena después de **cada** fuente, de modo que
      las ofertas nuevas aparecen en la lista mientras el resto sigue bajando.
    """
    rutas = config.crear_estructura()
    db.inicializar(rutas.db)
    limite = limite or config.MAX_OBSERVACIONES_POR_FUENTE

    mutex = Mutex(rutas.lock) if usar_mutex else None
    if mutex is not None and not mutex.adquirir():
        return {"estado": "busy", "motivo": "ya hay una corrida activa"}

    conn = db.conectar(rutas.db)
    inicio = time.perf_counter()
    run_id: int | None = None
    try:
        perfil = asegurar_perfil(conn, rutas)
        ingest.sembrar_fuentes(conn)
        ingest.sanear_textos(conn)
        resincronizadas = sincronizar_reglas(conn, perfil["id"])
        descartadas = queue.descartar_obsoletas(conn, perfil["id"])
        epoch = uuid.uuid4().hex
        run_id = ingest.abrir_corrida(conn, causa, epoch)
        recuperadas = queue.recuperar_huerfanas(conn, epoch)
        progreso.latido(conn, run_id)

        plan, omitidas = _planificar_fuentes(conn, fuentes)
        source_runs = ingest.planificar_source_runs(conn, run_id, [sid for sid, _ in plan])

        detalle_fuentes: list[dict] = []
        procesadas = 0
        cancelada = False

        for sid, meta in plan:
            if progreso.cancelada(conn, run_id):
                cancelada = True
                logs.registrar("corrida_cancelada", run_id=run_id, antes_de=sid)
                break

            sr_id = source_runs[sid]
            ingest.iniciar_source_run(conn, sr_id)
            progreso.latido(conn, run_id)
            adaptador = adapters.obtener(sid)
            t0 = time.perf_counter()
            try:
                resultado = recolectar(adaptador, limite)
            except Exception as exc:  # noqa: BLE001 - una fuente no debe tumbar la corrida
                resultado = ResultadoFuente(
                    source_id=sid, estado="network_error", error_code="network_error",
                    error_msg=f"excepción no controlada: {exc!r}",
                )
            stats = ingest.ingestar(conn, resultado, perfil["id"])
            ingest.cerrar_source_run(conn, sr_id, resultado, stats["nuevas"],
                                     stats["actualizadas"], resultado.cursor_nuevo)
            if not resultado.ok:
                incidents.registrar(conn, sid, resultado.error_code or resultado.estado,
                                    resultado.error_msg, run_id)
            elif resultado.estado in {"success", "empty_valid"}:
                incidents.resolver_por_exito(conn, sid)
            detalle_fuentes.append(
                {
                    "source_id": sid,
                    "nombre": meta["nombre"],
                    "estado": resultado.estado,
                    "http_status": resultado.http_status,
                    "observaciones": len(resultado.observaciones),
                    "nuevas": stats["nuevas"],
                    "actualizadas": stats["actualizadas"],
                    "sin_cambios": stats["sin_cambios"],
                    "vinculadas": stats["vinculadas"],
                    "encoladas": stats["encoladas"],
                    "error": resultado.error_msg,
                    "particiones": resultado.detalle.get("particiones"),
                    "ms": round((time.perf_counter() - t0) * 1000, 1),
                }
            )
            # Clasificar ya: lo que entró de esta fuente se puede ver sin
            # esperar a que termine la corrida entera.
            procesadas += procesar_tareas(conn, epoch, perfil=perfil, run_id=run_id)
            progreso.latido(conn, run_id)

        if cancelada:
            ingest.cancelar_pendientes(conn, run_id)

        procesadas += procesar_tareas(conn, epoch, perfil=perfil, run_id=run_id)
        merge.depurar(conn)
        relevancia = medir_relevancia(conn, run_id)
        for fila in detalle_fuentes:
            datos = relevancia.get(fila["source_id"], {})
            fila["relevantes"] = datos.get("relevantes", 0)
            fila["duplicadas"] = datos.get("duplicadas", 0)
        avisos = despachar_avisos(conn)

        duracion_ms = round((time.perf_counter() - inicio) * 1000, 1)
        estado_final = "cancelled" if cancelada else "completed"
        # El resumen se arma con la misma lectura que usa la interfaz: una sola
        # definición de "candidatas", "nuevas" y compañía. Se guarda **antes** de
        # cerrar la corrida: así nadie puede ver `completed` con el resumen vacío.
        foto = progreso.snapshot(conn, run_id)
        resumen = {
            "estado": estado_final,
            "causa": causa,
            "duracion_ms": duracion_ms,
            "fuentes_total": foto["fuentes"]["total"],
            "fuentes_procesadas": foto["fuentes"]["procesadas"],
            "fuentes_ok": foto["fuentes"]["completadas"],
            "fuentes_fallidas": foto["fuentes"]["fallidas"],
            "errores": [
                {"source_id": f["source_id"], "nombre": f["nombre"],
                 "motivo": f["error"] or f["estado"]}
                for f in detalle_fuentes if f["estado"] not in {"success", "empty_valid", "partial"}
            ],
            "revisadas": foto["ofertas"]["revisadas"],
            "nuevas": foto["ofertas"]["nuevas"],
            "duplicadas": foto["ofertas"]["duplicadas"],
            "elegibles": foto["ofertas"]["elegibles"],
            "dudosas": foto["ofertas"]["dudosas"],
            "incompatibles": foto["ofertas"]["incompatibles"],
            # `candidatas` es el catálogo vigente (lo postulable ahora);
            # `candidatas_nuevas` es lo que esta búsqueda sumó.
            "candidatas": foto["ofertas"]["elegibles"] + foto["ofertas"]["dudosas"],
            "candidatas_nuevas": (foto["ofertas"]["elegibles_nuevas"]
                                  + foto["ofertas"]["dudosas_nuevas"]),
            "clasificadas": foto["ofertas"]["clasificadas"],
        }
        progreso.guardar_resumen(conn, run_id, resumen)
        ingest.cerrar_corrida(conn, run_id, estado_final,
                             json.dumps(detalle_fuentes, ensure_ascii=False))
        logs.registrar(
            "corrida",
            run_id=run_id,
            causa=causa,
            estado=estado_final,
            duracion_ms=duracion_ms,
            tareas=procesadas,
            avisos=avisos,
            fuentes=[{"id": f["source_id"], "estado": f["estado"], "obs": f["observaciones"],
                      "rel": f.get("relevantes")} for f in detalle_fuentes],
        )
        total_obs = sum(f["observaciones"] for f in detalle_fuentes)
        total_rel = sum(f.get("relevantes", 0) for f in detalle_fuentes)
        return {
            "estado": "ok" if not cancelada else "cancelled",
            "cancelada": cancelada,
            "run_id": run_id,
            "run_epoch": epoch,
            "duracion_ms": duracion_ms,
            "tareas_recuperadas": recuperadas,
            "tareas_procesadas": procesadas,
            "reclasificadas_por_reglas": resincronizadas,
            "avisos_entregados": avisos,
            "observaciones": total_obs,
            "relevantes": total_rel,
            "fuentes": detalle_fuentes,
            "pausadas": omitidas,
            "resumen": resumen,
            "cola": queue.contar(conn),
        }
    except Exception as exc:
        # Una corrida que revienta deja rastro: si queda `running`, la interfaz
        # mostraría una búsqueda que ya no existe.
        if run_id is not None:
            try:
                with db.transaccion(conn):
                    conn.execute(
                        "UPDATE runs SET estado='failed', finished_at=?, notas=? WHERE id=?",
                        (config.ahora_utc(), repr(exc)[:500], run_id),
                    )
            except sqlite3.Error:
                pass
        raise
    finally:
        conn.close()
        if mutex is not None:
            mutex.liberar()


def _planificar_fuentes(conn: sqlite3.Connection,
                        fuentes: list[str] | None) -> tuple[list[tuple[str, dict]], list[str]]:
    """Fuentes que se van a consultar, en orden, y las pausadas que se omiten."""
    pausadas = {
        fila["source_id"]
        for fila in conn.execute("SELECT source_id FROM sources WHERE activo=0").fetchall()
    }
    plan: list[tuple[str, dict]] = []
    omitidas: list[str] = []
    for meta in adapters.metadatos():
        sid = meta["source_id"]
        if fuentes and sid not in fuentes:
            continue
        if not fuentes and sid in pausadas:
            omitidas.append(sid)
            continue
        plan.append((sid, meta))
    return plan, omitidas


def recolectar(adaptador: adapters.Adaptador, limite: int) -> ResultadoFuente:
    """Reúne las particiones del adaptador y, si aplica, pagina el cursor."""
    if getattr(adaptador, "particiones", ()):
        return _recolectar_particiones(adaptador, limite)
    return _fetch_con_paginas(adaptador, limite, config.MAX_PAGINAS_POR_FUENTE)


def _recolectar_particiones(adaptador: adapters.Adaptador, limite: int) -> ResultadoFuente:
    """Cada partición es una consulta independiente; los errores se aíslan."""
    observaciones: list = []
    vistos: set[str] = set()
    detalle_particiones: list[dict] = []
    errores: list[str] = []
    exitos = 0
    codigo_error = None
    http_status = None
    cupo = max(1, limite // max(1, len(adaptador.particiones)))
    restante = limite

    for particion in adaptador.particiones:
        if restante <= 0:
            break
        try:
            parcial = adaptador.fetch(min(cupo, restante), None, particion)
        except Exception as exc:  # noqa: BLE001 - se aísla por partición
            detalle_particiones.append({"clave": particion.clave, "estado": "network_error",
                                        "tomados": 0, "error": repr(exc)[:200]})
            errores.append(f"{particion.clave}: {exc!r}")
            codigo_error = codigo_error or "network_error"
            continue

        if not parcial.ok:
            codigo_error = codigo_error or parcial.error_code or parcial.estado
            http_status = http_status or parcial.http_status
            errores.append(f"{particion.clave}: {parcial.estado}")
            detalle_particiones.append({"clave": particion.clave, "estado": parcial.estado,
                                        "tomados": 0, "error": parcial.error_msg})
            continue

        exitos += 1
        nuevas = 0
        for obs in parcial.observaciones:
            if obs.external_id in vistos or restante <= 0:
                continue
            vistos.add(obs.external_id)
            observaciones.append(obs)
            nuevas += 1
            restante -= 1
        detalle_particiones.append({"clave": particion.clave, "estado": parcial.estado,
                                    "tomados": nuevas})

    if exitos == 0 and errores:
        estado = codigo_error or "network_error"
    elif errores:
        estado = "partial"
    else:
        estado = "success" if observaciones else "empty_valid"

    return ResultadoFuente(
        source_id=adaptador.source_id,
        estado=estado,
        observaciones=observaciones,
        http_status=http_status,
        error_code=codigo_error if estado not in {"success", "empty_valid"} else None,
        error_msg="; ".join(errores)[:500] or None,
        detalle={"particiones": detalle_particiones, "tomados": len(observaciones)},
    )


def _fetch_con_paginas(adaptador, limite: int, paginas: int = 3) -> ResultadoFuente:
    """Sigue el cursor de la fuente para no quedarse con la primera página."""
    primero = adaptador.fetch(limite)
    if not primero.ok or not primero.cursor_nuevo:
        return primero

    vistos = {o.external_id for o in primero.observaciones}
    observaciones = list(primero.observaciones)
    cursor = primero.cursor_nuevo
    estado = primero.estado
    detalle = dict(primero.detalle)
    detalle["paginas"] = 1

    for numero in range(2, paginas + 1):
        if len(observaciones) >= limite or not cursor:
            break
        try:
            siguiente = adaptador.fetch(min(limite - len(observaciones), limite), cursor)
        except Exception as exc:  # noqa: BLE001 - se conserva lo ya obtenido
            detalle["pagina_fallida"] = f"{numero}: {exc!r}"
            estado = "partial"
            break
        if not siguiente.ok:
            detalle["pagina_fallida"] = f"{numero}: {siguiente.estado}"
            estado = "partial"
            break
        nuevas = [o for o in siguiente.observaciones if o.external_id not in vistos]
        for obs in nuevas:
            vistos.add(obs.external_id)
        observaciones.extend(nuevas)
        detalle["paginas"] = numero
        cursor = siguiente.cursor_nuevo
        if not nuevas:
            break

    return ResultadoFuente(
        source_id=primero.source_id,
        estado=estado,
        observaciones=observaciones,
        cursor_nuevo=cursor,
        http_status=primero.http_status,
        detalle=detalle,
    )


def medir_relevancia(conn: sqlite3.Connection, run_id: int) -> dict[str, dict]:
    """Cuenta, por fuente, cuántas ofertas distintas aportan algo utilizable.

    Mide rendimiento real, no volumen capturado: una fuente que trae 100 avisos
    y ninguna oportunidad relevante queda retratada como tal.
    """
    relevantes = {
        fila["source_id"]: fila["n"]
        for fila in conn.execute(
            """SELECT o.source_id AS source_id, COUNT(DISTINCT jo.job_id) AS n
               FROM job_observations jo
               JOIN observations o ON o.id = jo.observation_id
               JOIN analyses a ON a.job_id = jo.job_id AND a.obsoleto = 0
               WHERE a.elegibilidad IN ('eligible','doubtful')
               GROUP BY o.source_id"""
        ).fetchall()
    }
    duplicadas = {
        fila["source_id"]: fila["n"]
        for fila in conn.execute(
            """SELECT o.source_id AS source_id, COUNT(*) AS n
               FROM job_observations jo
               JOIN observations o ON o.id = jo.observation_id
               WHERE jo.tipo_match = 'debil'
               GROUP BY o.source_id"""
        ).fetchall()
    }
    resultado: dict[str, dict] = {}
    for fila in conn.execute("SELECT id, source_id FROM source_runs WHERE run_id=?", (run_id,)).fetchall():
        datos = {
            "relevantes": int(relevantes.get(fila["source_id"], 0)),
            "duplicadas": int(duplicadas.get(fila["source_id"], 0)),
        }
        resultado[fila["source_id"]] = datos
        with db.transaccion(conn):
            conn.execute(
                "UPDATE source_runs SET relevantes=?, duplicadas=? WHERE id=?",
                (datos["relevantes"], datos["duplicadas"], fila["id"]),
            )
    return resultado


def clasificar(conn: sqlite3.Connection, tarea: dict, perfil: dict,
               run_id: int | None = None) -> dict:
    job = conn.execute("SELECT * FROM jobs WHERE id=?", (tarea["job_id"],)).fetchone()
    if job is None:
        raise ValueError(f"oferta inexistente: {tarea['job_id']}")
    # --- Fase 2A: integridad del historial ---------------------------------
    # 1) Una tarea encolada para otra versión de reglas no debe escribir sobre
    #    el catálogo vigente (quedan tareas viejas tras un rollback).
    reglas_tarea = tarea.get("rules_version") or config.RULES_VERSION
    if reglas_tarea != config.RULES_VERSION:
        return {"omitida": "tarea de otra versión de reglas", "reglas": reglas_tarea}
    # 2) Nunca resucitar una fila que un ROLLBACK marcó obsoleta. La señal no es
    #    `obsoleto=1` a secas: una invalidación normal (observación nueva,
    #    cambio de perfil) también aparta la fila y DEBE poder reclasificarse.
    #    Es rollback si la oferta ya tiene un análisis VIGENTE de otra versión de
    #    reglas. Se mira por oferta y no por la clave exacta de la tarea: una
    #    tarea rezagada puede traer otro `job_version_id` y, sin esta guardia,
    #    crearía una fila nueva de la versión revertida (Fase 2B).
    otra_epoca = conn.execute(
        "SELECT COUNT(*) FROM analyses WHERE job_id=? AND obsoleto=0 AND rules_version<>?",
        (tarea["job_id"], config.RULES_VERSION),
    ).fetchone()[0]
    if otra_epoca:
        return {"omitida": "hay un análisis vigente de otra versión (rollback); "
                           "no se resucita"}
    obs = conn.execute(
        """SELECT o.* FROM observations o
           JOIN job_observations jo ON jo.observation_id = o.id
           WHERE jo.job_id=? ORDER BY o.detectado_en DESC LIMIT 1""",
        (tarea["job_id"],),
    ).fetchone()

    oferta = {
        "id": job["id"],
        "titulo": job["titulo"],
        "empresa": job["empresa"],
        "region": job["territorio"],
        "texto": (obs["descripcion_texto"] if obs else "") or "",
        "seniority": obs["seniority"] if obs else None,
        "salario": json.loads(job["salario_json"]) if job["salario_json"] else None,
        "publicado_en": job["publicado_en"],
        "fuente_principal": job["fuente_principal"],
        "tipo_contrato": (obs["categoria_fuente"] if obs else None),
    }
    evaluacion = rules.evaluar(oferta, perfil["datos"])
    if job["estado_vigencia"] == "closed":
        evaluacion.vigencia = "closed"
    alertar = _corresponde_aviso(evaluacion)
    # Clave estable por oferta y canal: un cambio cosmético no genera otro aviso.
    clave_aviso = f"{job['id']}|inbox|alta"
    payload = {
        "job_id": job["id"],
        "titulo": job["titulo"],
        "empresa": job["empresa"],
        "score": evaluacion.compatibilidad,
        "confianza": evaluacion.confianza,
        "razones": evaluacion.razones_texto()[:3],
        "url": job["url_atribucion"],
        "excepcion": evaluacion.excepcion,
    }

    with db.transaccion(conn):
        conn.execute(
            """INSERT INTO analyses (job_id, job_version_id, profile_version_id, rules_version,
                   elegibilidad, score, componentes_json, razones_json, incertidumbres_json,
                   creado_en, obsoleto, excepcion, confianza, motivo_elegibilidad, run_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?,?,?)
               ON CONFLICT(job_id, job_version_id, profile_version_id, rules_version) DO UPDATE SET
                   elegibilidad=excluded.elegibilidad, score=excluded.score,
                   componentes_json=excluded.componentes_json, razones_json=excluded.razones_json,
                   incertidumbres_json=excluded.incertidumbres_json,
                   -- Fase 2A: creado_en es historia, no se reescribe al reproducir
                   -- una tarea tras una interrupción. Sólo se refresca el veredicto.
                   creado_en=analyses.creado_en, obsoleto=0, excepcion=excluded.excepcion,
                   confianza=excluded.confianza,
                   motivo_elegibilidad=excluded.motivo_elegibilidad,
                   run_id=excluded.run_id""",
            (
                job["id"], tarea["job_version_id"], tarea["profile_version_id"], config.RULES_VERSION,
                evaluacion.elegibilidad, evaluacion.compatibilidad,
                json.dumps([c.__dict__ for c in evaluacion.componentes], ensure_ascii=False),
                json.dumps(evaluacion.razones, ensure_ascii=False),
                json.dumps(evaluacion.incertidumbres, ensure_ascii=False),
                config.ahora_utc(), 1 if evaluacion.excepcion else 0,
                evaluacion.confianza, evaluacion.motivo_elegibilidad, run_id,
            ),
        )
        # Una oferta, un análisis vigente. La clave única incluye `job_version_id`,
        # así que dos versiones del mismo aviso dejaban dos filas vigentes: la
        # oferta aparecía duplicada en las listas y los contadores sumaban de más.
        conn.execute(
            """UPDATE analyses SET obsoleto=1
               WHERE job_id=? AND obsoleto=0
                 AND NOT (job_version_id=? AND profile_version_id=? AND rules_version=?)""",
            (job["id"], tarea["job_version_id"], tarea["profile_version_id"],
             config.RULES_VERSION),
        )
        conn.execute(
            "UPDATE jobs SET categoria=?, estado_vigencia=?, modalidad=? WHERE id=?",
            (evaluacion.categoria, evaluacion.vigencia, evaluacion.modalidad, job["id"]),
        )
        aviso = False
        if alertar:
            cur = conn.execute(
                """INSERT OR IGNORE INTO notifications (clave, job_id, canal, estado, payload_json, creado_en)
                   VALUES (?,?, 'inbox', 'queued', ?, ?)""",
                (clave_aviso, job["id"], json.dumps(payload, ensure_ascii=False), config.ahora_utc()),
            )
            aviso = bool(cur.rowcount)
    return {
        "elegibilidad": evaluacion.elegibilidad,
        "compatibilidad": evaluacion.compatibilidad,
        "confianza": evaluacion.confianza,
        "aviso": aviso,
    }


def _corresponde_aviso(evaluacion: rules.Evaluacion) -> bool:
    return (
        evaluacion.elegibilidad == "eligible"
        and evaluacion.compatibilidad is not None
        and evaluacion.compatibilidad >= 75
        and evaluacion.confianza != "baja"
        and evaluacion.vigencia == "open"
        and evaluacion.cobertura >= 0.7
        and not evaluacion.decisivas
    )


def despachar_avisos(conn: sqlite3.Connection) -> int:
    """La bandeja durable es el destino; el escritorio es opcional y tolerante a fallos."""
    return notify.despachar(conn)


def procesar_tareas(conn: sqlite3.Connection, epoch: str, maximo: int = 5000,
                    perfil: dict | None = None, run_id: int | None = None) -> int:
    perfil = perfil or asegurar_perfil(conn, config.rutas())
    procesadas = 0
    while procesadas < maximo:
        lote = queue.reclamar(conn, epoch, limite=50)
        if not lote:
            break
        for tarea in lote:
            procesadas += 1
            try:
                if tarea["kind"] == "clasificar":
                    job = conn.execute("SELECT semantic_hash FROM jobs WHERE id=?", (tarea["job_id"],)).fetchone()
                    if job is None:
                        queue.completar(conn, tarea["id"])
                        continue
                    clasificar(conn, tarea, perfil, run_id=run_id)
                    queue.completar(conn, tarea["id"])
                else:
                    queue.fallar(conn, tarea["id"], f"tipo de tarea desconocido: {tarea['kind']}")
            except Exception as exc:  # noqa: BLE001 - la cola debe sobrevivir a un fallo aislado
                queue.fallar(conn, tarea["id"], repr(exc))
                incidents.registrar(conn, tarea.get("job_id"), "clasificacion_fallida", repr(exc))
                logs.registrar("tarea_fallida", tarea=tarea["id"], job=tarea.get("job_id"), error=repr(exc))
    return procesadas
