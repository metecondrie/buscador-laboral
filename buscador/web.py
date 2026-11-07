"""Interfaz local: páginas HTML y acciones. Solo escucha en 127.0.0.1."""

from __future__ import annotations

import hmac
import json
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import (adapters, ai, backups, config, db, diagnostics, incidents, logs, merge,
               notify, progreso, queue, rules, scheduler, validacion, verify, worker)

PLANTILLAS = Path(__file__).with_name("web") / "templates"
ESTATICOS = Path(__file__).with_name("web") / "static"
templates = Jinja2Templates(directory=str(PLANTILLAS))
ACCIONES = {"guardar", "interesar", "descartar", "deshacer"}
MODALIDADES = ("remote", "hybrid", "onsite", "unknown")


def crear_app(token: str | None = None, csrf: str | None = None,
              stop_token: str | None = None) -> FastAPI:
    app = FastAPI(title="Buscador laboral", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token or secrets.token_urlsafe(32)
    app.state.csrf = csrf or secrets.token_urlsafe(24)
    app.state.stop_token = stop_token or secrets.token_urlsafe(24)
    app.state.token_usado = False
    app.state.servidor = None
    app.state.tareas = {
        "corrida": {"estado": "idle", "detalle": ""},
        "verificacion": {"estado": "idle", "detalle": ""},
    }
    app.state.candado = threading.Lock()
    app.state.hilo_corrida = None

    app.mount("/static", StaticFiles(directory=str(ESTATICOS)), name="static")

    @app.middleware("http")
    async def guardia(request: Request, call_next):
        host = (request.headers.get("host") or "").split(":")[0]
        if host not in {"127.0.0.1", "localhost"}:
            return PlainTextResponse("host no permitido", status_code=400)
        ruta = request.url.path
        if ruta in {"/salud", "/entrar", "/detener", "/favicon.ico"} or ruta.startswith("/static"):
            return await call_next(request)
        cookie = request.cookies.get("sesion")
        if not cookie or not hmac.compare_digest(cookie, app.state.token):
            return RedirectResponse("/entrar", status_code=303)
        return await call_next(request)

    @app.get("/salud")
    def salud() -> dict:
        return {"estado": "ok", "app": "buscador", "version": config.VERSION_APP}

    @app.post("/detener")
    def detener(request: Request):
        if not hmac.compare_digest(request.headers.get("x-stop-token", ""), app.state.stop_token):
            return PlainTextResponse("token de control inválido", status_code=403)

        def apagar() -> None:
            if app.state.servidor is not None:
                app.state.servidor.should_exit = True

        threading.Timer(0.3, apagar).start()
        return {"estado": "deteniendo"}

    @app.get("/entrar")
    def entrar(token: str = ""):
        if app.state.token_usado:
            return PlainTextResponse("El enlace de esta sesión ya se usó. Reiniciá la aplicación.", status_code=403)
        if not token or not hmac.compare_digest(token, app.state.token):
            return PlainTextResponse("Token inválido.", status_code=403)
        app.state.token_usado = True
        respuesta = RedirectResponse("/ofertas", status_code=303)
        respuesta.set_cookie("sesion", app.state.token, httponly=True, samesite="strict", max_age=8 * 3600)
        return respuesta

    @contextmanager
    def conn():
        conexion = db.conectar(config.rutas().db)
        try:
            yield conexion
        finally:
            conexion.close()

    def csrf_ok(valor: str) -> bool:
        return bool(valor) and hmac.compare_digest(valor, app.state.csrf)

    def contexto(request: Request, **extra) -> dict:
        base = {"request": request, "csrf": app.state.csrf, "avisos": 0, "perfil_demo": False,
                "version_app": config.VERSION_APP, "incidentes": 0, "duplicados": 0,
                "tareas": app.state.tareas}
        try:
            with conn() as c:
                base["avisos"] = notify.no_leidos(c)
                base["incidentes"] = len(incidents.abiertos(c))
                base["duplicados"] = merge.contar_pendientes(c)
                perfil = c.execute(
                    "SELECT origen FROM profile_versions WHERE activo=1 ORDER BY id DESC LIMIT 1"
                ).fetchone()
                base["perfil_demo"] = bool(perfil and perfil["origen"] == "sintetico_demostracion")
        except sqlite3.Error:
            pass
        base.update(extra)
        return base

    def fuentes_para_filtro(c: sqlite3.Connection) -> list[dict]:
        return [dict(f) for f in c.execute("SELECT source_id, nombre FROM sources ORDER BY source_id").fetchall()]

    def consultar_ofertas(where: str, params: tuple = (), orden: str = "score",
                          limite: int = 200) -> list[dict]:
        ordenes = {
            "score": "a.score DESC, j.publicado_en DESC",
            "recientes": "j.publicado_en DESC, a.score DESC",
            "fuente": "j.fuente_principal, a.score DESC",
            "empresa": "j.empresa, a.score DESC",
            "antiguedad": "j.primera_deteccion DESC",
        }
        sql = f"""
            SELECT j.*, a.elegibilidad, a.score, a.razones_json, a.incertidumbres_json,
                   a.componentes_json, a.rules_version, a.excepcion, a.confianza,
                   a.motivo_elegibilidad,
                   (SELECT accion FROM user_events u WHERE u.job_id=j.id ORDER BY u.id DESC LIMIT 1) AS estado_usuario,
                   (SELECT COUNT(*) FROM job_observations jo WHERE jo.job_id=j.id) AS fuentes_vinculadas
            FROM jobs j
            JOIN analyses a ON a.job_id=j.id AND a.obsoleto=0
            WHERE {where} AND j.merged_into IS NULL
            ORDER BY {ordenes.get(orden, ordenes['score'])}
            LIMIT {int(limite)}
        """
        with conn() as c:
            filas = c.execute(sql, params).fetchall()
        return [_preparar(dict(f)) for f in filas]

    def filtros_ofertas(request: Request, elegibilidad: str | None, titulo: str,
                        nota: str | None = None) -> HTMLResponse:
        q = request.query_params.get("q", "").strip()
        categoria = request.query_params.get("categoria", "").strip()
        fuente = request.query_params.get("fuente", "").strip()
        modalidad = request.query_params.get("modalidad", "").strip()
        orden = request.query_params.get("orden", "score").strip()
        vigencia = request.query_params.get("vigencia", "").strip()
        excepcion = request.query_params.get("excepcion", "").strip()
        estado = request.query_params.get("estado", "").strip()

        condiciones = []
        params: list = []
        if elegibilidad:
            condiciones.append("a.elegibilidad=?")
            params.append(elegibilidad)
        if q:
            condiciones.append("(j.titulo LIKE ? OR j.empresa LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        if categoria:
            condiciones.append("j.categoria=?")
            params.append(categoria)
        if fuente:
            condiciones.append("j.fuente_principal=?")
            params.append(fuente)
        if modalidad:
            condiciones.append("j.modalidad=?")
            params.append(modalidad)
        if vigencia:
            condiciones.append("j.estado_vigencia=?")
            params.append(vigencia)
        if excepcion == "1":
            condiciones.append("a.excepcion=1")
        if estado:
            condiciones.append(
                """j.id IN (SELECT e.job_id FROM user_events e
                            WHERE e.id = (SELECT MAX(id) FROM user_events WHERE job_id=e.job_id)
                            AND e.accion IN ('guardar','interesar','descartar'))"""
            )
        if not condiciones:
            condiciones.append("1=1")

        filas = consultar_ofertas(" AND ".join(condiciones), tuple(params), orden)
        with conn() as c:
            fuentes = fuentes_para_filtro(c)
        return templates.TemplateResponse(
            request, "ofertas.html",
            contexto(request, titulo=titulo, ofertas=filas, q=q, categoria=categoria,
                     fuente=fuente, modalidad=modalidad, orden=orden, vigencia=vigencia,
                     excepcion=excepcion, estado=estado, categorias=rules.CATEGORIAS,
                     fuentes=fuentes, modalidades=MODALIDADES, filtros=True, busqueda=True,
                     nota=nota or "Ordenadas por compatibilidad profesional, luego vigencia y modalidad. "
                                  "El puntaje no es una probabilidad de contratación."),
        )

    @app.get("/", include_in_schema=False)
    def raiz():
        return RedirectResponse("/ofertas", status_code=303)

    @app.get("/ofertas", response_class=HTMLResponse)
    def ofertas(request: Request):
        return filtros_ofertas(request, "eligible", "Ofertas compatibles")

    @app.get("/dudosas", response_class=HTMLResponse)
    def dudosas(request: Request):
        return filtros_ofertas(
            request, "doubtful", "Dudosas para revisar",
            nota="Falta información para decidir. No se descartan ni se avisan. "
                 "Acá aparecen también las ofertas con excepción por competencias.",
        )

    @app.get("/todas", response_class=HTMLResponse)
    def todas(request: Request):
        return filtros_ofertas(request, None, "Todas las ofertas capturadas",
                               nota="Incluye incompatibles, útiles para auditar por qué se descartó cada aviso.")

    @app.get("/guardadas", response_class=HTMLResponse)
    def guardadas(request: Request):
        return filtros_ofertas(
            request, None, "Guardadas y de interés",
            nota="Ofertas donde tu última decisión fue guardar o marcar interés.",
        )

    @app.get("/oferta/{job_id}", response_class=HTMLResponse)
    def detalle(request: Request, job_id: str):
        with conn() as c:
            fila = c.execute(
                """SELECT j.*, a.elegibilidad, a.score, a.razones_json, a.incertidumbres_json,
                          a.componentes_json, a.rules_version, a.excepcion,
                          a.confianza, a.motivo_elegibilidad,
                          (SELECT accion FROM user_events u WHERE u.job_id=j.id ORDER BY u.id DESC LIMIT 1) AS estado_usuario
                   FROM jobs j LEFT JOIN analyses a ON a.job_id=j.id AND a.obsoleto=0 WHERE j.id=?""",
                (job_id,),
            ).fetchone()
            if fila is None:
                return PlainTextResponse("Oferta inexistente", status_code=404)
            observaciones = c.execute(
                """SELECT o.source_id, o.url, o.publicado_en, o.detectado_en, o.descripcion_texto,
                          o.seniority, o.field_status_json, s.nombre
                   FROM observations o JOIN sources s ON s.source_id=o.source_id
                   JOIN job_observations jo ON jo.observation_id=o.id WHERE jo.job_id=?
                   ORDER BY o.detectado_en DESC""",
                (job_id,),
            ).fetchall()
            eventos = c.execute(
                "SELECT accion, creado_en FROM user_events WHERE job_id=? ORDER BY id DESC LIMIT 10", (job_id,)
            ).fetchall()
            versiones = c.execute(
                """SELECT id, semantic_hash, titulo, empresa, vigencia, creado_en
                   FROM job_versions WHERE job_id=? ORDER BY id DESC LIMIT 20""",
                (job_id,),
            ).fetchall()
        oferta = _preparar(dict(fila))
        oferta["observaciones"] = [dict(o) for o in observaciones]
        oferta["eventos"] = [dict(e) for e in eventos]
        oferta["versiones"] = [dict(v) for v in versiones]
        return templates.TemplateResponse(
            request, "detalle.html", contexto(request, titulo=oferta["titulo"], oferta=oferta)
        )

    @app.post("/oferta/{job_id}/accion")
    def accion(request: Request, job_id: str, accion: str = Form(...), csrf: str = Form(""),
               action_id: str = Form("")):
        if not csrf_ok(csrf):
            return PlainTextResponse("CSRF inválido", status_code=400)
        if accion not in ACCIONES:
            return PlainTextResponse("Acción no permitida", status_code=400)
        identificador = action_id or uuid.uuid4().hex
        with conn() as c:
            existe = c.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not existe:
                return PlainTextResponse("Oferta inexistente", status_code=404)
            with db.transaccion(c):
                c.execute(
                    """INSERT OR IGNORE INTO user_events (action_id, job_id, accion, creado_en, version_esperada, payload_json)
                       VALUES (?,?,?,?,?,?)""",
                    (identificador, job_id, accion, config.ahora_utc(), "v1",
                     json.dumps({"origen": "ui"})),
                )
        destino = request.headers.get("referer") or f"/oferta/{job_id}"
        if not destino.startswith("/") or destino.startswith("//"):
            destino = f"/oferta/{job_id}"
        return RedirectResponse(destino, status_code=303)

    # --- validación humana del ranking -----------------------------------
    @app.get("/validacion", response_class=HTMLResponse)
    def validacion_vista(request: Request):
        with conn() as c:
            muestra_id = validacion.muestra_activa(c) or validacion.crear_muestra(c)
            filas = validacion.items(c, muestra_id)
            datos = validacion.metricas(c, muestra_id)
        return templates.TemplateResponse(
            request, "validacion.html",
            contexto(request, titulo="Validación del ranking", items=filas,
                     metricas=datos, muestra=muestra_id),
        )

    @app.post("/validacion/{job_id}")
    def validacion_guardar(request: Request, job_id: str, csrf: str = Form(""),
                           veredicto: str = Form(...), comentario: str = Form(""),
                           muestra: str = Form("")):
        if not csrf_ok(csrf):
            return PlainTextResponse("CSRF inválido", status_code=400)
        with conn() as c:
            muestra_id = int(muestra) if muestra.isdigit() else (validacion.muestra_activa(c) or 0)
            if not muestra_id:
                muestra_id = validacion.crear_muestra(c)
            try:
                validacion.registrar(c, muestra_id, job_id, veredicto, comentario)
            except ValueError as exc:
                return PlainTextResponse(str(exc), status_code=400)
        return RedirectResponse("/validacion#item-" + job_id, status_code=303)

    # --- historial -------------------------------------------------------
    @app.get("/duplicados", response_class=HTMLResponse)
    def duplicados(request: Request):
        with conn() as c:
            filas = merge.sugerencias(c)
        return templates.TemplateResponse(
            request, "duplicados.html",
            contexto(request, titulo="Posibles duplicados", sugerencias=filas),
        )

    @app.post("/duplicados/{review_id}/{accion}")
    def accion_duplicado(request: Request, review_id: int, accion: str, csrf: str = Form("")):
        if not csrf_ok(csrf):
            return PlainTextResponse("CSRF inválido", status_code=400)
        with conn() as c:
            try:
                if accion == "aceptar":
                    merge.aceptar(c, review_id)
                elif accion == "rechazar":
                    merge.rechazar(c, review_id)
                elif accion == "revertir":
                    merge.revertir(c, review_id)
                else:
                    return PlainTextResponse("Acción no permitida", status_code=400)
            except ValueError as exc:
                return PlainTextResponse(str(exc), status_code=400)
        return RedirectResponse("/duplicados", status_code=303)

    @app.get("/historial", response_class=HTMLResponse)
    def historial(request: Request, accion: str = "", limite: int = 100):
        condiciones = ["1=1"]
        params: list = []
        if accion:
            condiciones.append("e.accion=?")
            params.append(accion)
        with conn() as c:
            eventos = [dict(f) for f in c.execute(
                f"""SELECT e.id, e.job_id, e.accion, e.creado_en, j.titulo, j.empresa
                    FROM user_events e JOIN jobs j ON j.id=e.job_id
                    WHERE {' AND '.join(condiciones)}
                    ORDER BY e.id DESC LIMIT ?""",
                (*params, min(int(limite), 300)),
            ).fetchall()]
            versiones = [dict(f) for f in c.execute(
                """SELECT j.id, j.titulo, j.empresa,
                          (SELECT COUNT(*) FROM job_versions v WHERE v.job_id=j.id) AS versiones,
                          (SELECT COUNT(*) FROM job_observations jo WHERE jo.job_id=j.id) AS observaciones,
                          (SELECT GROUP_CONCAT(DISTINCT o.source_id) FROM job_observations jo
                             JOIN observations o ON o.id=jo.observation_id WHERE jo.job_id=j.id) AS fuentes,
                          j.primera_deteccion, j.ultima_deteccion
                   FROM jobs j ORDER BY j.ultima_deteccion DESC LIMIT 60"""
            ).fetchall()]
            corridas = [dict(f) for f in c.execute(
                "SELECT id, causa, estado, started_at, finished_at FROM runs ORDER BY id DESC LIMIT 20"
            ).fetchall()]
        return templates.TemplateResponse(
            request, "historial.html",
            contexto(request, titulo="Historial", eventos=eventos, versiones=versiones,
                     corridas=corridas, accion=accion),
        )

    # --- fuentes ---------------------------------------------------------
    @app.get("/fuentes", response_class=HTMLResponse)
    def fuentes(request: Request):
        with conn() as c:
            filas = [dict(f) for f in c.execute(
                """SELECT s.*,
                       (SELECT estado FROM source_runs r WHERE r.source_id=s.source_id ORDER BY r.id DESC LIMIT 1) AS ultimo_estado,
                       (SELECT started_at FROM source_runs r WHERE r.source_id=s.source_id ORDER BY r.id DESC LIMIT 1) AS ultima_corrida,
                       (SELECT observaciones FROM source_runs r WHERE r.source_id=s.source_id ORDER BY r.id DESC LIMIT 1) AS ultimas_observaciones,
                       (SELECT relevantes FROM source_runs r WHERE r.source_id=s.source_id ORDER BY r.id DESC LIMIT 1) AS ultimos_relevantes,
                       (SELECT COUNT(*) FROM observations o WHERE o.source_id=s.source_id) AS observaciones,
                       (SELECT COUNT(*) FROM jobs j WHERE j.fuente_principal=s.source_id) AS ofertas,
                       (SELECT COUNT(DISTINCT jo.job_id) FROM job_observations jo
                          JOIN observations o ON o.id=jo.observation_id
                          JOIN analyses a ON a.job_id=jo.job_id AND a.obsoleto=0
                        WHERE o.source_id=s.source_id AND a.elegibilidad IN ('eligible','doubtful')) AS relevantes,
                       (SELECT COUNT(*) FROM incidents i WHERE i.source_id=s.source_id AND i.resuelto_en IS NULL) AS incidentes
                   FROM sources s ORDER BY s.source_id""").fetchall()]
            verificaciones = [dict(v) for v in c.execute(
                """SELECT v.source_id, v.fecha, v.resultado, v.notas FROM source_verifications v
                   ORDER BY v.id DESC LIMIT 40"""
            ).fetchall()]
            salud = incidents.salud_por_fuente(c)
        return templates.TemplateResponse(
            request, "fuentes.html",
            contexto(request, titulo="Fuentes", fuentes=filas, verificaciones=verificaciones,
                     salud=salud, tarea=app.state.tareas["verificacion"]),
        )

    @app.post("/fuentes/verificar")
    def verificar_fuentes(request: Request, csrf: str = Form("")):
        if not csrf_ok(csrf):
            return PlainTextResponse("CSRF inválido", status_code=400)
        _lanzar_verificacion(app)
        return RedirectResponse("/fuentes?verificando=1", status_code=303)

    # --- actividad y avisos ----------------------------------------------
    @app.get("/actividad", response_class=HTMLResponse)
    def actividad(request: Request, busqueda: str = ""):
        with conn() as c:
            corridas = [dict(r) for r in c.execute(
                "SELECT * FROM runs ORDER BY id DESC LIMIT 10").fetchall()]
            por_fuente = [dict(r) for r in c.execute(
                "SELECT * FROM source_runs ORDER BY id DESC LIMIT 25").fetchall()]
            avisos = notify.bandeja(c, 50)
            cola = queue.contar(c)
            totales = {
                "ofertas": c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
                "observaciones": c.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
                "analisis": c.execute("SELECT COUNT(*) FROM analyses WHERE obsoleto=0").fetchone()[0],
                "avisos": c.execute("SELECT COUNT(*) FROM notifications").fetchone()[0],
            }
            abiertos = incidents.abiertos(c)
        return templates.TemplateResponse(
            request, "actividad.html",
            contexto(request, titulo="Actividad", corridas=corridas, por_fuente=por_fuente,
                     avisos=avisos, cola=cola, totales=totales, busqueda=busqueda,
                     incidentes_abiertos=abiertos, tarea=app.state.tareas["corrida"]),
        )

    @app.post("/fuentes/{source_id}/estado")
    def estado_fuente(request: Request, source_id: str, csrf: str = Form(""),
                      activo: str = Form("1")):
        """Pausa o reactiva una fuente sin borrar sus datos ni su historial."""
        if not csrf_ok(csrf):
            return PlainTextResponse("CSRF inválido", status_code=400)
        with conn() as c:
            with db.transaccion(c):
                c.execute("UPDATE sources SET activo=? WHERE source_id=?",
                          (1 if activo == "1" else 0, source_id))
        return RedirectResponse("/fuentes", status_code=303)

    @app.post("/buscar")
    def buscar(request: Request, csrf: str = Form(""), volver: str = Form("")):
        """Arranque sin JavaScript: redirige a la página desde la que se pulsó."""
        if not csrf_ok(csrf):
            return PlainTextResponse("CSRF inválido", status_code=400)
        resultado = _lanzar_corrida(app)
        destino = volver if _destino_local(volver) else "/actividad"
        estado = "iniciada" if resultado["iniciada"] else "ocupado"
        separador = "&" if "?" in destino else "?"
        return RedirectResponse(f"{destino}{separador}busqueda={estado}", status_code=303)

    @app.get("/progreso.json")
    def progreso_json(run_id: int | None = None) -> JSONResponse:
        """Estado de la búsqueda tal como está en la base, sin caché.

        Se consulta cada ~1,2 s mientras hay corrida y cada 8 s si no la hay.
        No toca credenciales ni la red: sólo lee tablas.
        """
        with conn() as c:
            datos = progreso.snapshot(c, run_id)
        return JSONResponse(datos, headers={"Cache-Control": "no-store"})

    @app.post("/buscar/ahora")
    def buscar_ahora(request: Request, csrf: str = Form("")) -> JSONResponse:
        """Arranca una corrida y devuelve qué pasó. Una sola, nunca dos.

        Si ya hay una en curso no se lanza otra: se devuelve la que existe para
        que la interfaz muestre su progreso, que es lo que el usuario quería ver.
        """
        if not csrf_ok(csrf):
            return JSONResponse({"iniciada": False, "motivo": "CSRF inválido"}, status_code=400)
        resultado = _lanzar_corrida(app)
        return JSONResponse(resultado, headers={"Cache-Control": "no-store"})

    @app.post("/buscar/cancelar")
    def buscar_cancelar(request: Request, csrf: str = Form("")) -> JSONResponse:
        """Cancelación segura: la fuente en curso termina, el resto no arranca."""
        if not csrf_ok(csrf):
            return JSONResponse({"cancelada": False, "motivo": "CSRF inválido"}, status_code=400)
        with conn() as c:
            viva = progreso.activa(c)
            if viva is None or not viva["viva"]:
                return JSONResponse({"cancelada": False,
                                     "motivo": "no hay una búsqueda en curso"})
            hecho = progreso.marcar_cancelada(c, viva["id"])
        return JSONResponse({
            "cancelada": hecho,
            "run_id": viva["id"],
            "motivo": ("cancelación pedida: se detiene al terminar la fuente actual; "
                       "lo ya descargado y clasificado se conserva")
            if hecho else "la búsqueda ya había terminado",
        })

    @app.post("/avisos/leidos")
    def avisos_leidos(request: Request, csrf: str = Form("")):
        if not csrf_ok(csrf):
            return PlainTextResponse("CSRF inválido", status_code=400)
        with conn() as c:
            notify.marcar_leidos(c)
        return RedirectResponse("/actividad", status_code=303)

    @app.post("/incidentes/resolver")
    def resolver_incidentes(request: Request, csrf: str = Form(""), fuente: str = Form("")):
        if not csrf_ok(csrf):
            return PlainTextResponse("CSRF inválido", status_code=400)
        with conn() as c:
            incidents.resolver(c, source_id=fuente or None)
        return RedirectResponse("/diagnostico", status_code=303)

    # --- configuración ---------------------------------------------------
    @app.get("/config", response_class=HTMLResponse)
    def configuracion(request: Request, guardado: str = ""):
        rutas = config.rutas()
        with conn() as c:
            pragmas = db.pragmas(c)
            perfil = c.execute(
                "SELECT version, origen, creado_en, perfil_json FROM profile_versions WHERE activo=1 ORDER BY id DESC LIMIT 1"
            ).fetchone()
            versiones = [dict(v) for v in c.execute(
                "SELECT version, origen, creado_en FROM profile_versions ORDER BY id DESC LIMIT 5").fetchall()]
            ajustes = {f["clave"]: f["valor"] for f in c.execute("SELECT clave, valor FROM settings").fetchall()}
            prog = scheduler.estado(c)
            ia = ai.estado(c)
            respaldos = backups.listar(rutas)
            credenciales_ia = {}
            for clave_prov, proveedor in ai.PROVEEDORES.items():
                secreto = ai.credenciales.leer(clave_prov, proveedor.variable_clave)
                credenciales_ia[clave_prov] = {
                    "estado": ai.Cliente(c).estado_credencial(proveedor),
                    "origen": ai.credenciales.origen(clave_prov, proveedor.variable_clave),
                    "mascara": ai.credenciales.enmascarar(secreto) if secreto else "",
                    "variable": proveedor.variable_clave,
                }
        perfil_json = json.dumps(json.loads(perfil["perfil_json"]), ensure_ascii=False, indent=2) if perfil else ""
        ultima_prueba = _json_ajuste(ajustes.get("ia_ultima_prueba", ""))
        ultima_verificacion = _json_ajuste(ajustes.get("ia_ultima_verificacion", ""))
        ultimo_diagnostico = _json_ajuste(ajustes.get("ia_ultimo_diagnostico", ""))
        return templates.TemplateResponse(
            request, "config.html",
            contexto(request, titulo="Configuración", rutas=rutas, pragmas=pragmas,
                     perfil=dict(perfil) if perfil else None, versiones=versiones,
                     rules_version=config.RULES_VERSION, perfil_json=perfil_json,
                     datos_perfil=json.loads(perfil["perfil_json"]) if perfil else {},
                     ajustes=ajustes, programacion=prog, ia=ia, proveedores=ai.catalogo(),
                     credenciales_ia=credenciales_ia, cascada_texto="\n".join(ia["politica"]["cascada"]),
                     ultima_prueba=ultima_prueba, ultima_verificacion=ultima_verificacion,
                     ultimo_diagnostico=ultimo_diagnostico,
                     aviso_ia=ajustes.get("ia_aviso", ""),
                     respaldos=respaldos[:8], guardado=guardado, categorias=rules.CATEGORIAS),
        )

    @app.post("/perfil")
    async def guardar_perfil(request: Request):
        formulario = await request.form()
        if not csrf_ok(str(formulario.get("csrf", ""))):
            return PlainTextResponse("CSRF inválido", status_code=400)
        with conn() as c:
            actual = worker.asegurar_perfil(c, config.rutas())["datos"]
            datos = _perfil_desde_formulario(formulario, actual)
            worker.guardar_perfil(c, config.rutas(), datos, origen="manual")
        return RedirectResponse("/config?guardado=perfil", status_code=303)

    @app.post("/programar")
    def programar(request: Request, csrf: str = Form(""), accion: str = Form(...)):
        if not csrf_ok(csrf):
            return PlainTextResponse("CSRF inválido", status_code=400)
        with conn() as c:
            if accion == "activar":
                db.guardar_ajuste(c, "corrida_automatica", "1")
            elif accion == "desactivar":
                db.guardar_ajuste(c, "corrida_automatica", "0")
            elif accion == "windows":
                resultado = scheduler.activar_windows()
                db.guardar_ajuste(c, "tarea_windows",
                                  "registrada" if resultado.get("ok") else "no registrada")
                db.guardar_ajuste(c, "tarea_windows_detalle",
                                  (resultado.get("detalle") or resultado.get("motivo") or "")[:300])
                if resultado.get("ok"):
                    db.guardar_ajuste(c, "corrida_automatica", "1")
            elif accion == "windows-quitar":
                resultado = scheduler.desactivar_windows()
                db.guardar_ajuste(c, "tarea_windows",
                                  "no registrada" if resultado.get("ok") else "desconocida")
                db.guardar_ajuste(c, "tarea_windows_detalle",
                                  (resultado.get("detalle") or resultado.get("motivo") or "")[:300])
                db.guardar_ajuste(c, "corrida_automatica", "0")
        return RedirectResponse("/config?guardado=programacion", status_code=303)

    @app.post("/ia")
    async def configurar_ia(request: Request):
        formulario = await request.form()
        if not csrf_ok(str(formulario.get("csrf", ""))):
            return PlainTextResponse("CSRF inválido", status_code=400)
        accion = str(formulario.get("accion", "guardar"))
        proveedor = str(formulario.get("proveedor", "")).strip()
        with conn() as c:
            if accion == "guardar":
                referencias = [r.strip() for r in str(formulario.get("cascada", "")).replace("\n", ",").split(",")
                               if r.strip()]
                validas = [r for r in referencias if ai.parsear(r) is not None]
                db.guardar_ajuste(c, "ia_cascada", ",".join(validas))
                db.guardar_ajuste(c, "ia_datos_ofertas",
                                  "1" if formulario.get("datos") == "1" else "0")
                db.guardar_ajuste(c, "ia_cache", "1" if formulario.get("cache") == "1" else "0")
                db.guardar_ajuste(c, "ia_autorizo_pago",
                                  "1" if formulario.get("autorizo_pago") == "1" else "0")
                db.guardar_ajuste(c, "ia_cuenta_cloudflare",
                                  str(formulario.get("cuenta_cloudflare", "")).strip())
                db.guardar_ajuste(c, "ia_llamadas_por_corrida",
                                  str(formulario.get("limite_llamadas", "20")).strip() or "20")
                proveedores = formulario.getlist("proveedores") if hasattr(formulario, "getlist") else []
                if proveedores:
                    db.guardar_ajuste(c, "ia_proveedores_habilitados", ",".join(proveedores))
                try:
                    valor = float(str(formulario.get("presupuesto", "0")) or 0)
                except ValueError:
                    valor = 0.0
                ai.fijar_limite(c, valor)
                db.guardar_ajuste(c, "ia_presupuesto_usd", str(valor))
            elif accion == "habilitar":
                db.guardar_ajuste(c, "ia_habilitada", "1")
            elif accion == "deshabilitar":
                db.guardar_ajuste(c, "ia_habilitada", "0")
            elif accion == "clave":
                try:
                    ai.credenciales.guardar(proveedor, str(formulario.get("clave", "")))
                    db.guardar_ajuste(c, f"ia_estado_{proveedor}", "presente")
                    db.guardar_ajuste(c, "ia_aviso", "")
                except (ValueError, RuntimeError) as exc:
                    db.guardar_ajuste(c, "ia_aviso", str(exc)[:200])
            elif accion == "borrar-clave":
                ai.credenciales.borrar(proveedor)
                db.guardar_ajuste(c, f"ia_estado_{proveedor}", "ausente")
            elif accion == "probar":
                referencia = str(formulario.get("referencia", ""))
                resultado = ai.Cliente(c).probar_conexion(referencia, consumir_cuota=True)
                resultado["referencia"] = referencia
                db.guardar_ajuste(c, "ia_ultima_prueba",
                                  json.dumps(resultado, ensure_ascii=False))
            elif accion == "verificar":
                resultado = ai.Cliente(c).verificar_modelos(proveedor)
                resultado["proveedor"] = proveedor
                db.guardar_ajuste(c, "ia_ultima_verificacion",
                                  json.dumps(resultado, ensure_ascii=False))
            elif accion == "diagnosticar":
                from .ai import diagnostico as diag_mod

                resultado = diag_mod.diagnosticar(c, proveedor or "gemini")
                db.guardar_ajuste(c, "ia_ultimo_diagnostico",
                                  json.dumps(_resumen_diagnostico(resultado), ensure_ascii=False))
        return RedirectResponse("/config?guardado=ia", status_code=303)

    @app.post("/respaldo")
    def respaldo(request: Request, csrf: str = Form("")):
        if not csrf_ok(csrf):
            return PlainTextResponse("CSRF inválido", status_code=400)
        with conn() as c:
            backups.crear(c, config.rutas(), "ui")
            backups.limpiar(config.rutas())
        return RedirectResponse("/config?guardado=respaldo", status_code=303)

    @app.post("/exportar")
    def exportar(request: Request, csrf: str = Form(""), guardadas: str = Form("0")):
        if not csrf_ok(csrf):
            return PlainTextResponse("CSRF inválido", status_code=400)
        with conn() as c:
            backups.exportar_csv(c, config.rutas(), solo_guardadas=guardadas == "1")
        return RedirectResponse("/config?guardado=exportacion", status_code=303)

    # --- diagnóstico -----------------------------------------------------
    @app.get("/diagnostico", response_class=HTMLResponse)
    def diagnostico(request: Request):
        with conn() as c:
            datos = diagnostics.resumen(c, config.rutas())
            abiertos = incidents.abiertos(c)
            codigos = incidents.resumen_codigos(c)
            historial_incidentes = incidents.historial(c, 40)
        return templates.TemplateResponse(
            request, "diagnostico.html",
            contexto(request, titulo="Diagnóstico", datos=datos, abiertos=abiertos,
                     codigos=codigos, historial=historial_incidentes),
        )

    @app.post("/diagnostico/paquete")
    def paquete(request: Request, csrf: str = Form("")):
        if not csrf_ok(csrf):
            return PlainTextResponse("CSRF inválido", status_code=400)
        with conn() as c:
            destino = diagnostics.paquete(c, config.rutas())
        return RedirectResponse(f"/diagnostico?paquete={destino.name}", status_code=303)

    @app.post("/salir")
    def salir(request: Request, csrf: str = Form("")):
        if not csrf_ok(csrf):
            return PlainTextResponse("CSRF inválido", status_code=400)

        def detener() -> None:
            if app.state.servidor is not None:
                app.state.servidor.should_exit = True

        threading.Timer(0.5, detener).start()
        return HTMLResponse(
            "<main style='font-family:system-ui;padding:2rem'>"
            "<h1>Servidor detenido</h1><p>Podés cerrar esta pestaña. "
            "Una corrida ya iniciada termina por su cuenta.</p></main>"
        )

    # --- tareas en segundo plano ----------------------------------------
    def _lanzar_corrida(app_: FastAPI) -> dict:
        """Una corrida por vez. Devuelve `{iniciada, motivo, run_id}`.

        Hay tres guardas y cada una cubre un agujero distinto:

        - el candado en memoria evita dos hilos dentro del mismo proceso;
        - la base (`progreso.activa`) evita duplicar entre pestañas;
        - el mutex de archivo distingue una corrida **viva** de una que quedó
          `running` porque el proceso murió. Un latido reciente no prueba que
          alguien esté trabajando; poder tomar el candado sí prueba lo contrario.

        El mutex de `worker.correr` sigue siendo la última red.
        """
        with conn() as c:
            viva = progreso.activa(c)
            if viva is not None and viva["viva"]:
                if _trabajador_ocupado():
                    return {"iniciada": False, "run_id": viva["id"],
                            "motivo": "ya hay una búsqueda en curso: mostrando su progreso"}
                # Latido fresco pero nadie tiene el candado: la corrida quedó
                # colgada. Se cierra y se deja buscar de nuevo.
                progreso.marcar_abandonada(c, viva["id"])
                logs.registrar("corrida_abandonada", run_id=viva["id"])

        with app_.state.candado:
            actual = app_.state.tareas["corrida"]
            if actual["estado"] == "running":
                return {"iniciada": False, "run_id": actual.get("run_id"),
                        "motivo": "ya hay una búsqueda en curso"}
            app_.state.tareas["corrida"] = {"estado": "running", "detalle": "consultando fuentes"}

        def trabajo() -> None:
            try:
                resultado = worker.correr(causa="manual-ui")
                if resultado.get("estado") == "busy":
                    # Otra corrida tiene el candado (por ejemplo la automática).
                    app_.state.tareas["corrida"] = {
                        "estado": "busy",
                        "detalle": resultado.get("motivo", "ya hay una corrida activa"),
                    }
                    return
                estado = ("cancelled" if resultado.get("cancelada")
                          else "ok" if resultado.get("estado") == "ok"
                          else resultado.get("estado", "error"))
                app_.state.tareas["corrida"] = {
                    "estado": estado,
                    "detalle": f"{resultado.get('observaciones', 0)} observaciones · "
                               f"{resultado.get('tareas_procesadas', 0)} clasificadas",
                    "run_id": resultado.get("run_id"),
                }
            except Exception as exc:  # noqa: BLE001 - la interfaz no debe caer
                app_.state.tareas["corrida"] = {"estado": "error", "detalle": repr(exc)[:300]}

        hilo = threading.Thread(target=trabajo, daemon=True, name="corrida-ui")
        app_.state.hilo_corrida = hilo
        hilo.start()
        return {"iniciada": True, "motivo": "búsqueda iniciada", "run_id": None}

    def _lanzar_verificacion(app_: FastAPI) -> bool:
        with app_.state.candado:
            if app_.state.tareas["verificacion"]["estado"] == "running":
                return False
            app_.state.tareas["verificacion"] = {"estado": "running", "detalle": "consultando fuentes"}

        def trabajo() -> None:
            try:
                with conn() as c:
                    datos = verify.verificar_todas(c, limite=15)
                app_.state.tareas["verificacion"] = {
                    "estado": "ok",
                    "detalle": f"{datos['resumen']['aceptadas']}/{datos['resumen']['total']} aceptadas · "
                               f"{datos['resumen']['relevantes']} relevantes",
                }
            except Exception as exc:  # noqa: BLE001
                app_.state.tareas["verificacion"] = {"estado": "error", "detalle": repr(exc)[:300]}
        threading.Thread(target=trabajo, daemon=True, name="verificacion-ui").start()
        return True

    return app


def _perfil_desde_formulario(formulario, actual: dict) -> dict:
    """Reconstruye el perfil desde el formulario sin perder claves desconocidas."""
    datos = dict(actual)

    habilidades = []
    for linea in (formulario.get("habilidades") or "").splitlines():
        nombre = linea.strip()
        if nombre:
            habilidades.append({"nombre": nombre, "evidencia": "declarada por el usuario"})
    if habilidades:
        datos["habilidades"] = habilidades

    datos["idioma"] = {
        "ingles": (formulario.get("ingles") or "B2").strip().upper(),
        "espanol": "nativo",
    }
    try:
        anios = int(formulario.get("anios") or 0)
    except ValueError:
        anios = 0
    datos["experiencia"] = {
        "anios": anios,
        "nivel": (formulario.get("nivel") or "junior").strip(),
    }
    presencial = [p.strip() for p in (formulario.get("presencial") or "").split(",") if p.strip()]
    datos["territorio"] = {
        "residencia": (formulario.get("residencia") or "Argentina").strip(),
        "remoto": formulario.get("remoto") == "1",
        "presencial": presencial,
    }
    categorias = formulario.getlist("categorias") if hasattr(formulario, "getlist") else []
    if categorias:
        datos["categorias"] = list(categorias)
    salario = dict(datos.get("salario") or {})
    for campo, clave in (("ars_referencia", "ars_neto_referencia"), ("ars_objetivo", "ars_neto_objetivo"),
                         ("usd_hora", "usd_hora_freelance")):
        valor = formulario.get(campo)
        if valor not in (None, ""):
            try:
                salario[clave] = int(float(valor))
            except ValueError:
                pass
    datos["salario"] = salario
    datos["disponibilidad"] = {
        "desde": (formulario.get("desde") or "inmediata").strip(),
        "horas_semana": int(float(formulario.get("horas") or 40)),
    }
    datos["origen"] = "manual"
    datos["nota"] = "Perfil cargado desde la interfaz. Revisá que cada habilidad tenga evidencia."
    return datos


def _trabajador_ocupado() -> bool:
    """¿Hay un trabajador con el candado tomado?

    Tomar el mutex y soltarlo enseguida no interfiere con una corrida en curso:
    si alguien lo tiene, `adquirir()` falla y sabemos que está viva.
    """
    mutex = worker.Mutex(config.rutas().lock)
    try:
        return not mutex.adquirir()
    finally:
        mutex.liberar()


def _destino_local(valor: str) -> bool:
    """Sólo rutas internas: evita redirecciones abiertas desde un formulario."""
    return bool(valor) and valor.startswith("/") and not valor.startswith("//")


def _preparar(fila: dict) -> dict:
    for campo in ("razones_json", "incertidumbres_json", "componentes_json"):
        if campo in fila and fila[campo]:
            try:
                fila[campo.replace("_json", "")] = json.loads(fila[campo])
            except (TypeError, json.JSONDecodeError):
                fila[campo.replace("_json", "")] = []
        else:
            fila.setdefault(campo.replace("_json", ""), [])
    if fila.get("salario_json"):
        try:
            fila["salario"] = json.loads(fila["salario_json"])
        except (TypeError, json.JSONDecodeError):
            fila["salario"] = None
    else:
        fila["salario"] = None
    return fila


def _resumen_diagnostico(resultado: dict) -> dict:
    """Versión acotada para guardar en `settings`: sin truncar el JSON.

    Cortar el texto a ciegas rompía el JSON y la página se quedaba sin bloque de
    diagnóstico. Acá se recortan los campos, no el documento.
    """
    return {
        "ok": resultado.get("ok"),
        "estado": resultado.get("estado"),
        "conclusion": (resultado.get("conclusion") or "")[:600],
        "sombra": (resultado.get("sombra") or "")[:300] or None,
        "aviso": resultado.get("aviso"),
        "clave": resultado.get("clave") or {},
        "modelos": resultado.get("modelos") or {},
        "candidatas": resultado.get("candidatas") or [],
        "historial": resultado.get("historial") or {},
        "endpoints": [
            {
                "nombre": (e.get("nombre") or "")[:80],
                "tipo": e.get("tipo"),
                "http": e.get("http"),
                "ok": e.get("ok"),
                "aplicable": e.get("aplicable", True),
                "nota": (e.get("nota") or "")[:120],
                "razones": (e.get("razones") or [])[:3],
                "mensaje": (e.get("mensaje") or "")[:160],
            }
            for e in (resultado.get("endpoints") or [])
        ],
        "fecha": resultado.get("fecha"),
    }


def _json_ajuste(valor: str) -> dict:
    """Lee un ajuste que guarda JSON; devuelve {} si está vacío o roto."""
    if not valor:
        return {}
    try:
        datos = json.loads(valor)
        return datos if isinstance(datos, dict) else {}
    except json.JSONDecodeError:
        return {}
