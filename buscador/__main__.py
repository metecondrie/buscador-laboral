"""Punto de entrada: interfaz local, corridas, respaldos, diagnóstico y programación."""

from __future__ import annotations

import argparse
import json
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn

from . import (adapters, ai, backups, config, db, diagnostics, incidents,
               perfil_guard, queue, scheduler, validacion, verify, worker)
from .ai.cliente import Cliente
from .web import crear_app


def _puerto_libre(preferido: int) -> int:
    for puerto in range(preferido, preferido + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((config.HOST_LOCAL, puerto))
            except OSError:
                continue
            return puerto
    raise RuntimeError("sin puerto libre en 127.0.0.1")


def _imprimir(datos) -> None:
    print(json.dumps(datos, ensure_ascii=False, indent=2, default=str))


def cmd_ui(args: argparse.Namespace) -> int:
    rutas = config.crear_estructura()
    db.inicializar(rutas.db)
    conn = db.conectar(rutas.db)
    try:
        perfil = worker.asegurar_perfil(conn, rutas)
        from . import ingest

        ingest.sembrar_fuentes(conn)
        worker.sincronizar_reglas(conn, perfil["id"])
    finally:
        conn.close()

    app = crear_app()
    puerto = _puerto_libre(args.puerto)
    servidor = uvicorn.Server(
        uvicorn.Config(app, host=config.HOST_LOCAL, port=puerto, log_level="warning", access_log=False)
    )
    app.state.servidor = servidor
    registro = rutas.data / "servidor.json"
    registro.write_text(
        json.dumps({"puerto": puerto, "token": app.state.stop_token, "iniciado": config.ahora_utc()}),
        encoding="utf-8",
    )

    hilo = None
    conn = db.conectar(rutas.db)
    try:
        if db.ajuste(conn, "corrida_automatica", "0") == "1":
            hilo = scheduler.HiloProgramado()
            hilo.start()
            app.state.programado = hilo
    finally:
        conn.close()

    enlace = f"http://{config.HOST_LOCAL}:{puerto}/entrar?token={app.state.token}"
    print("=" * 72)
    print(f"Buscador laboral · MVP {config.VERSION_APP}")
    print(f"Datos:   {rutas.raiz}")
    print(f"Abrir:   {enlace}")
    if hilo is not None:
        print("Automático: activado (cada %d h)" % config.INTERVALO_HORAS)
    else:
        print("Automático: desactivado (se activa en Configuración)")
    print("Cerrar:  botón 'Salir de la aplicación' en Configuración")
    print("=" * 72, flush=True)
    if args.abrir:
        import webbrowser

        webbrowser.open(enlace)
    servidor.run()
    if hilo is not None:
        hilo.detener()
    registro.unlink(missing_ok=True)
    print("Servidor detenido.")
    return 0


def cmd_stop(_: argparse.Namespace) -> int:
    rutas = config.rutas()
    registro = rutas.data / "servidor.json"
    if not registro.exists():
        print("No hay un servidor registrado. ¿Está abierta la aplicación?")
        return 1
    datos = json.loads(registro.read_text(encoding="utf-8"))
    peticion = urllib.request.Request(
        f"http://{config.HOST_LOCAL}:{datos['puerto']}/detener",
        method="POST",
        headers={"X-Stop-Token": datos["token"]},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=10) as respuesta:
            print(f"Cierre solicitado: HTTP {respuesta.status}")
            return 0
    except (urllib.error.URLError, OSError) as exc:
        print(f"No se pudo contactar al servidor: {exc}. Borrando registro obsoleto.")
        registro.unlink(missing_ok=True)
        return 1


def cmd_buscar(args: argparse.Namespace) -> int:
    fuentes = [f.strip() for f in args.fuentes.split(",")] if args.fuentes else None
    resultado = worker.correr(causa=args.causa, limite=args.limite, fuentes=fuentes)
    if args.json:
        _imprimir(resultado)
    else:
        if resultado.get("estado") != "ok":
            print(f"Corrida no ejecutada: {resultado.get('motivo', resultado.get('estado'))}")
            return 1
        print(f"Corrida {resultado['run_id']} en {resultado['duracion_ms'] / 1000:.1f} s")
        print(f"Observaciones: {resultado['observaciones']} · relevantes acumuladas: {resultado['relevantes']}")
        for fuente in resultado["fuentes"]:
            print(
                f"  {fuente['source_id']} {fuente['nombre'][:24]:<24} {fuente['estado']:<13} "
                f"obs={fuente['observaciones']:>3} nuevas={fuente['nuevas']:>3} "
                f"rel={fuente.get('relevantes', 0):>4}"
                + (f"  error={fuente['error'][:60]}" if fuente.get("error") else "")
            )
        print(f"Tareas: {resultado['tareas_procesadas']} · avisos nuevos: {resultado['avisos_entregados']}")
        if args.respaldo:
            print(f"Respaldo: {json.dumps(_respaldar(), ensure_ascii=False)}")
    return 0 if resultado.get("estado") == "ok" else 1


def _respaldar(etiqueta: str = "") -> dict:
    rutas = config.crear_estructura()
    db.inicializar(rutas.db)
    conn = db.conectar(rutas.db)
    try:
        resultado = backups.crear(conn, rutas, etiqueta)
        resultado["limpiados"] = backups.limpiar(rutas)
    finally:
        conn.close()
    return resultado


def cmd_respaldar(args: argparse.Namespace) -> int:
    _imprimir(_respaldar(args.etiqueta or "manual"))
    return 0


def cmd_restaurar(args: argparse.Namespace) -> int:
    archivo = Path(args.archivo)
    if not archivo.is_absolute():
        archivo = config.rutas().backups / archivo
    try:
        _imprimir(backups.restaurar(archivo))
    except (FileNotFoundError, ValueError) as exc:
        print(f"No se restauró: {exc}")
        return 1
    return 0


def cmd_exportar(args: argparse.Namespace) -> int:
    rutas = config.crear_estructura()
    db.inicializar(rutas.db)
    conn = db.conectar(rutas.db)
    try:
        _imprimir(backups.exportar_csv(conn, rutas, solo_guardadas=args.guardadas))
    finally:
        conn.close()
    return 0


def cmd_verificar(args: argparse.Namespace) -> int:
    rutas = config.crear_estructura()
    db.inicializar(rutas.db)
    conn = db.conectar(rutas.db)
    try:
        solo = [f.strip() for f in args.fuentes.split(",")] if args.fuentes else None
        datos = verify.verificar_todas(conn, limite=args.limite, solo=solo)
    finally:
        conn.close()
    if args.salida:
        destino = Path(args.salida)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Evidencia escrita en {destino}")
    if args.json or not args.salida:
        _imprimir(datos)
    else:
        for fila in datos["fuentes"]:
            print(
                f"{fila['source_id']} {fila['nombre'][:22]:<22} {fila['estado']:<12} "
                f"obs={fila['observaciones']:>3} rel={fila['relevantes']:>3} "
                f"({fila['porcentaje_relevante']:>5.1f} %) {'aceptada' if fila['aceptada'] else 'revisar'}"
            )
        print(json.dumps(datos["resumen"], ensure_ascii=False))
    return 0 if datos["resumen"]["aceptadas"] >= 1 else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    rutas = config.crear_estructura()
    db.inicializar(rutas.db)
    conn = db.conectar(rutas.db)
    try:
        datos = diagnostics.resumen(conn, rutas)
        datos["fuentes_registradas"] = adapters.metadatos()
    finally:
        conn.close()
    if args.json:
        _imprimir(datos)
        return 0
    base = datos["base"]
    print(f"Buscador {datos['app']['version']} · reglas {datos['app']['rules']} · esquema {datos['app']['esquema']}")
    print(f"Python {datos['entorno']['python']} · SQLite {datos['entorno']['sqlite']} · {datos['entorno']['sistema']}")
    print(f"Datos:  {datos['rutas']['raiz']}")
    print(f"Base:   {datos['rutas']['base']}")
    print(f"PRAGMA: {base['pragmas']}")
    print(f"Conteos: {base['conteos']}")
    print(f"Elegibilidad: {base['elegibilidad']}")
    print(f"Cola: {datos['cola']}")
    print(f"Programación: cada {datos['programacion']['intervalo_horas']} h · "
          f"próxima {datos['programacion']['proxima']} · "
          f"tarea Windows {'registrada' if datos['programacion']['tarea_windows'].get('registrada') else 'no registrada'}")
    print(f"IA: {'lista' if datos['ia']['listo'] else 'no disponible'} ({datos['ia']['motivo']})")
    print("Fuentes:")
    for sid, salud in datos["fuentes"].items():
        incidente = salud["incidente"]
        print(f"  {sid} último={salud['ultimo_estado'] or '—':<12} obs={salud['observaciones_ultima']:>3} "
              f"rel={salud['relevantes_ultima']:>4} "
              + (f"incidente={incidente['codigo']}" if incidente else ""))
    abiertos = datos["incidentes"]["abiertos"]
    print(f"Incidentes abiertos: {len(abiertos)}")
    for incidente in abiertos[:10]:
        print(f"  {incidente['source_id'] or '—'} {incidente['codigo']}: {(incidente['mensaje'] or '')[:90]}")
    return 0


def cmd_incidentes(args: argparse.Namespace) -> int:
    rutas = config.crear_estructura()
    db.inicializar(rutas.db)
    conn = db.conectar(rutas.db)
    try:
        if args.resolver:
            cuantos = incidents.resolver(conn, source_id=args.fuente or None)
            print(f"Incidentes resueltos: {cuantos}")
            return 0
        _imprimir({"abiertos": incidents.abiertos(conn), "codigos": incidents.resumen_codigos(conn)})
    finally:
        conn.close()
    return 0


def cmd_reclasificar(args: argparse.Namespace) -> int:
    rutas = config.crear_estructura()
    db.inicializar(rutas.db)
    conn = db.conectar(rutas.db)
    try:
        perfil = worker.asegurar_perfil(conn, rutas)
        # Fase 2A: NO invalidar todos los análisis. Con la misma versión de
        # reglas, el INSERT ... ON CONFLICT DO UPDATE reescribía
        # componentes_json/razones_json/creado_en de la fila histórica y la
        # devolvía a obsoleto=0: se perdía el historial. Sólo se aparta lo que
        # pertenece a OTRA versión de reglas; el resto se conserva intacto.
        with db.transaccion(conn):
            cur = conn.execute(
                "UPDATE analyses SET obsoleto=1 "
                "WHERE obsoleto=0 AND rules_version<>?",
                (config.RULES_VERSION,),
            )
        apartados = cur.rowcount
        # Encola únicamente las ofertas que quedaron sin análisis vigente y
        # drena la cola (determinista, sin red, sin IA, sin avisos externos).
        resultado = worker.reclasificar_faltantes(conn)
        print(json.dumps({"perfil": perfil["version"], "apartados_por_version": apartados,
                          "faltantes": resultado.get("faltantes", 0),
                          "encoladas_ahora": resultado.get("encoladas_ahora", 0),
                          "procesadas": resultado.get("procesadas", 0),
                          "reglas": config.RULES_VERSION}, ensure_ascii=False))
    finally:
        conn.close()
    return 0


def cmd_validacion(args: argparse.Namespace) -> int:
    rutas = config.crear_estructura()
    db.inicializar(rutas.db)
    conn = db.conectar(rutas.db)
    try:
        if args.crear:
            muestra_id = validacion.crear_muestra(conn)
            print(f"Muestra {muestra_id} lista con {validacion.metricas(conn, muestra_id)['total']} ofertas.")
            return 0
        muestra_id = validacion.muestra_activa(conn)
        if muestra_id is None:
            print("No hay muestra todavía. Usá --crear.")
            return 1
        if args.exportar:
            destino = Path(args.exportar)
            destino.parent.mkdir(parents=True, exist_ok=True)
            filas = validacion.items(conn, muestra_id)
            import csv

            with destino.open("w", encoding="utf-8-sig", newline="") as manejador:
                escritor = csv.writer(manejador, delimiter=";")
                escritor.writerow(["n", "titulo", "empresa", "fuente", "modalidad", "region",
                                   "elegibilidad", "compatibilidad", "confianza", "motivo",
                                   "veredicto", "comentario"])
                for indice, fila in enumerate(filas, start=1):
                    escritor.writerow([
                        indice, fila["titulo"], fila["empresa"] or "", fila["fuente_principal"],
                        fila["modalidad"] or "", fila["territorio"] or "",
                        fila["elegibilidad"] or "", fila["score"] if fila["score"] is not None else "",
                        fila["confianza"] or "", fila["motivo_elegibilidad"] or "",
                        fila["veredicto"] or "", fila["comentario"] or "",
                    ])
            print(f"Exportado a {destino}")
            return 0
        _imprimir(validacion.metricas(conn, muestra_id))
    finally:
        conn.close()
    return 0


def cmd_diagnosticar(args: argparse.Namespace) -> int:
    rutas = config.crear_estructura()
    db.inicializar(rutas.db)
    conn = db.conectar(rutas.db)
    try:
        destino = diagnostics.paquete(conn, rutas)
    finally:
        conn.close()
    print(f"Paquete de diagnóstico: {destino}")
    return 0


def cmd_programar(args: argparse.Namespace) -> int:
    rutas = config.crear_estructura()
    db.inicializar(rutas.db)
    conn = db.conectar(rutas.db)
    try:
        if args.activar:
            db.guardar_ajuste(conn, "corrida_automatica", "1")
            resultado = scheduler.activar_windows(args.intervalo)
            db.guardar_ajuste(conn, "tarea_windows",
                              "registrada" if resultado.get("ok") else "no registrada")
            db.guardar_ajuste(conn, "tarea_windows_detalle",
                              (resultado.get("detalle") or resultado.get("motivo") or "")[:300])
            _imprimir({"ajuste_interno": "activado", **resultado})
            return 0 if resultado.get("ok") else 1
        if args.desactivar:
            db.guardar_ajuste(conn, "corrida_automatica", "0")
            resultado = scheduler.desactivar_windows()
            db.guardar_ajuste(conn, "tarea_windows",
                              "no registrada" if resultado.get("ok") else "desconocida")
            _imprimir({"ajuste_interno": "desactivado", **resultado})
            return 0
        _imprimir(scheduler.estado(conn, consultar_windows=args.estado))
    finally:
        conn.close()
    return 0


def cmd_ia(args: argparse.Namespace) -> int:
    rutas = config.crear_estructura()
    db.inicializar(rutas.db)
    conn = db.conectar(rutas.db)
    try:
        if args.habilitar:
            db.guardar_ajuste(conn, "ia_habilitada", "1")
        if args.deshabilitar:
            db.guardar_ajuste(conn, "ia_habilitada", "0")
        if args.autorizar_pago:
            db.guardar_ajuste(conn, "ia_autorizo_pago", "1")
        if args.revocar_pago:
            db.guardar_ajuste(conn, "ia_autorizo_pago", "0")
        if args.permiso_datos is not None:
            db.guardar_ajuste(conn, "ia_datos_ofertas", "1" if args.permiso_datos else "0")
        if args.presupuesto is not None:
            ai.fijar_limite(conn, args.presupuesto)
            db.guardar_ajuste(conn, "ia_presupuesto_usd", str(args.presupuesto))
        if args.cascada:
            referencias = [r.strip() for r in args.cascada.split(",") if r.strip()]
            invalidas = [r for r in referencias if ai.parsear(r) is None]
            if invalidas:
                print(f"Referencias desconocidas: {', '.join(invalidas)}")
                return 1
            db.guardar_ajuste(conn, "ia_cascada", ",".join(referencias))
        if args.proveedores is not None:
            elegidos = [p.strip() for p in args.proveedores.split(",") if p.strip()]
            db.guardar_ajuste(conn, "ia_proveedores_habilitados", ",".join(elegidos))

        if args.modelos:
            _imprimir(ai.catalogo())
            return 0
        if args.diagnosticar:
            from .ai import diagnostico

            _imprimir(diagnostico.diagnosticar(conn, args.diagnosticar))
            return 0
        if args.verificar:
            _imprimir(Cliente(conn).verificar_modelos(args.verificar))
            return 0
        if args.probar:
            print("Aviso: esta prueba hace una llamada real y consume cuota del proveedor.")
            _imprimir(Cliente(conn).probar_conexion(args.probar, consumir_cuota=True))
            return 0
        _imprimir(ai.estado(conn))
    finally:
        conn.close()
    return 0


def cmd_perfil(args: argparse.Namespace) -> int:
    rutas = config.crear_estructura()
    db.inicializar(rutas.db)
    conn = db.conectar(rutas.db)
    try:
        if args.real:
            from . import perfil as perfil_mod
            # Fase 2A: el origen canónico es profile_versions.activo=1. PERFIL_EJEMPLO
            # declara B2 y `nivel` por habilidad; aplicarlo sin control cambia los
            # veredictos en silencio. Se valida ANTES de escribir perfil.json.
            propuesto = perfil_mod.perfil(rutas)
            try:
                perfil_guard.validar_reemplazo(
                    perfil_guard.perfil_activo(conn), propuesto)
            except perfil_guard.ReemplazoPerfilBloqueado as exc:
                print("perfil --real BLOQUEADO; no se escribió nada.", file=sys.stderr)
                for motivo in exc.diferencias:
                    print("  - " + motivo, file=sys.stderr)
                print("Usá un perfil equivalente al activo o una autorización explícita.",
                      file=sys.stderr)
                return 2
            perfil = worker.guardar_perfil(conn, rutas, propuesto,
                                           origen=perfil_mod.ORIGEN)
            print(f"Perfil real {perfil['version']} aplicado; "
                  f"{perfil['encoladas']} ofertas reencoladas.")
            return 0
        if args.importar:
            datos = json.loads(Path(args.importar).read_text(encoding="utf-8"))
            try:
                perfil_guard.validar_reemplazo(
                    perfil_guard.perfil_activo(conn), datos)
            except perfil_guard.ReemplazoPerfilBloqueado as exc:
                print("perfil --importar BLOQUEADO; no se escribió nada.", file=sys.stderr)
                for motivo in exc.diferencias:
                    print("  - " + motivo, file=sys.stderr)
                return 2
            perfil = worker.guardar_perfil(conn, rutas, datos, origen="importado")
            print(f"Perfil {perfil['version']} aplicado; {perfil['encoladas']} ofertas reencoladas.")
            return 0
        perfil = worker.asegurar_perfil(conn, rutas)
        _imprimir({"version": perfil["version"], "perfil": perfil["datos"]})
    finally:
        conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="buscador", description=f"Buscador laboral local (MVP {config.VERSION_APP})"
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    ui = sub.add_parser("ui", help="abre la interfaz local")
    ui.add_argument("--puerto", type=int, default=config.PUERTO_PREFERIDO)
    ui.add_argument("--abrir", action="store_true", help="abre el navegador con el enlace de sesión")
    ui.set_defaults(func=cmd_ui)

    buscar = sub.add_parser("buscar", help="ejecuta una corrida")
    buscar.add_argument("--limite", type=int, default=config.MAX_OBSERVACIONES_POR_FUENTE)
    buscar.add_argument("--fuentes", default="", help="lista separada por comas, por ejemplo F01,F03")
    buscar.add_argument("--causa", default="manual-cli",
                        choices=["manual-cli", "manual-ui", "automatica", "programada"])
    buscar.add_argument("--json", action="store_true", help="imprime el resultado completo")
    buscar.add_argument("--respaldo", action="store_true", help="crea un respaldo al terminar")
    buscar.set_defaults(func=cmd_buscar)

    doctor = sub.add_parser("doctor", help="estado, PRAGMA, fuentes e incidentes")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    stop = sub.add_parser("stop", help="cierra el servidor local de forma ordenada")
    stop.set_defaults(func=cmd_stop)

    respaldar = sub.add_parser("respaldar", help="crea un respaldo verificado")
    respaldar.add_argument("--etiqueta", default="")
    respaldar.set_defaults(func=cmd_respaldar)

    restaurar = sub.add_parser("restaurar", help="restaura un respaldo verificado")
    restaurar.add_argument("archivo")
    restaurar.set_defaults(func=cmd_restaurar)

    exportar = sub.add_parser("exportar", help="exporta ofertas a CSV")
    exportar.add_argument("--guardadas", action="store_true")
    exportar.set_defaults(func=cmd_exportar)

    verificar = sub.add_parser("verificar-fuentes", help="comprueba las fuentes contra su respuesta real")
    verificar.add_argument("--limite", type=int, default=20)
    verificar.add_argument("--fuentes", default="")
    verificar.add_argument("--salida", default="")
    verificar.add_argument("--json", action="store_true")
    verificar.set_defaults(func=cmd_verificar)

    incidentes = sub.add_parser("incidentes", help="lista o resuelve incidentes")
    incidentes.add_argument("--resolver", action="store_true")
    incidentes.add_argument("--fuente", default="")
    incidentes.set_defaults(func=cmd_incidentes)

    valid = sub.add_parser("validacion", help="muestra de 25 ofertas para revisar a mano")
    valid.add_argument("--crear", action="store_true", help="crea la muestra fija")
    valid.add_argument("--exportar", default="", help="escribe un CSV con los veredictos")
    valid.set_defaults(func=cmd_validacion)

    reclasificar = sub.add_parser("reclasificar", help="recalcula todas las ofertas con las reglas actuales")
    reclasificar.set_defaults(func=cmd_reclasificar)

    diagnosticar = sub.add_parser("diagnosticar", help="genera un paquete de diagnóstico")
    diagnosticar.set_defaults(func=cmd_diagnosticar)

    programar = sub.add_parser("programar", help="búsqueda automática cada 12 horas")
    grupo = programar.add_mutually_exclusive_group()
    grupo.add_argument("--activar", action="store_true")
    grupo.add_argument("--desactivar", action="store_true")
    grupo.add_argument("--estado", action="store_true")
    programar.add_argument("--intervalo", type=int, default=config.INTERVALO_HORAS)
    programar.set_defaults(func=cmd_programar)

    ia = sub.add_parser("ia", help="estado, catálogo y pruebas de proveedores de IA")
    ia.add_argument("--habilitar", action="store_true")
    ia.add_argument("--deshabilitar", action="store_true")
    ia.add_argument("--autorizar-pago", action="store_true",
                    help="habilita proveedores de pago (requiere decisión explícita)")
    ia.add_argument("--revocar-pago", action="store_true")
    ia.add_argument("--permiso-datos", dest="permiso_datos", action="store_true", default=None,
                    help="permite enviar texto de ofertas al proveedor")
    ia.add_argument("--sin-permiso-datos", dest="permiso_datos", action="store_false")
    ia.add_argument("--presupuesto", type=float, default=None)
    ia.add_argument("--cascada", default="", help="lista separada por comas: proveedor:modelo")
    ia.add_argument("--proveedores", default=None, help="proveedores habilitados, separados por comas")
    ia.add_argument("--modelos", action="store_true", help="imprime el catálogo de modelos")
    ia.add_argument("--diagnosticar", nargs="?", const="gemini", default="",
                    help="diagnostica la credencial: formato, endpoints y causa del rechazo")
    ia.add_argument("--verificar", default="", help="consulta el catálogo del proveedor (no consume cuota)")
    ia.add_argument("--probar", default="", help="prueba real de conexión; consume cuota")
    ia.set_defaults(func=cmd_ia)

    perfil = sub.add_parser("perfil", help="muestra, aplica o importa el perfil")
    perfil.add_argument("--importar", default="")
    perfil.add_argument("--real", action="store_true",
                        help="aplica el perfil fundamentado en la memoria de el usuario")
    perfil.set_defaults(func=cmd_perfil)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
