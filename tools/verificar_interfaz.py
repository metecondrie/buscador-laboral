"""Verificación de la interfaz sobre un socket real, en un proceso nuevo.

El entorno de esta sesión bloquea las conexiones a `127.0.0.1` entre procesos
distintos, así que el servidor y el cliente corren en el mismo proceso: el
socket, uvicorn y las rutas son los reales, no un TestClient en memoria.

Uso: python tools/verificar_interfaz.py [puerto] [--buscar]

`--buscar` lanza además una búsqueda real completa y espera a que termine, para
comprobar el criterio de aceptación: pulsar «Buscar ahora» y ver el avance con
resultados que se incorporan.
"""

from __future__ import annotations

import http.cookiejar
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import uvicorn  # noqa: E402

from buscador import config, db, ingest, worker  # noqa: E402
from buscador.web import crear_app  # noqa: E402

_argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
PUERTO = int(_argumentos[0]) if _argumentos else 8802
BUSCAR = "--buscar" in sys.argv


def esperar(servidor, abridor, base: str, limite: float = 25.0) -> bool:
    fin = time.time() + limite
    while time.time() < fin:
        try:
            with abridor.open(f"{base}/salud", timeout=2) as respuesta:
                if respuesta.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    return False


def main() -> int:
    rutas = config.crear_estructura()
    db.inicializar(rutas.db)
    conexion = db.conectar(rutas.db)
    try:
        ingest.sembrar_fuentes(conexion)
        worker.asegurar_perfil(conexion, rutas)
    finally:
        conexion.close()

    app = crear_app()
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PUERTO,
                                             log_level="error", access_log=False))
    app.state.servidor = servidor
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()

    jarra = http.cookiejar.CookieJar()
    abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                          urllib.request.HTTPCookieProcessor(jarra))
    base = f"http://127.0.0.1:{PUERTO}"
    resultados: list[tuple[str, bool, str]] = []

    def anotar(nombre: str, ok: bool, detalle: str = "") -> None:
        resultados.append((nombre, ok, detalle))

    if not esperar(servidor, abridor, base):
        print("El servidor no respondió en el tiempo previsto.")
        servidor.should_exit = True
        return 1

    try:
        with abridor.open(f"{base}/salud", timeout=5) as r:
            anotar("GET /salud", r.status == 200, str(r.status))

        enlace = f"{base}/entrar?token={app.state.token}"
        with abridor.open(enlace, timeout=5) as r:
            anotar("GET /entrar", r.status == 200, str(r.status))

        paginas = ["/config", "/ofertas", "/dudosas", "/validacion", "/fuentes",
                   "/actividad", "/diagnostico", "/historial", "/duplicados"]
        for ruta in paginas:
            with abridor.open(f"{base}{ruta}", timeout=20) as r:
                cuerpo = r.read().decode("utf-8", errors="replace")
                anotar(f"GET {ruta}", r.status == 200 and "Internal Server Error" not in cuerpo,
                       str(r.status))

        try:  # sólo POST: 405 es lo correcto, urllib lo trata como error
            with abridor.open(f"{base}/ia", timeout=5) as r:
                anotar("GET /ia (debe ser 405)", r.status == 405, str(r.status))
        except urllib.error.HTTPError as error:
            anotar("GET /ia (debe ser 405)", error.code == 405, str(error.code))

        with abridor.open(f"{base}/config", timeout=10) as r:
            html = r.read().decode("utf-8", errors="replace")
        csrf = re.search(r'name="csrf" value="([^"]+)"', html)
        if not csrf:
            anotar("POST /ia diagnosticar", False, "no se encontró el token CSRF")
        else:
            datos = urllib.parse.urlencode({
                "csrf": csrf.group(1), "accion": "diagnosticar", "proveedor": "gemini",
            }).encode()
            with abridor.open(f"{base}/ia", data=datos, timeout=40) as r:
                anotar("POST /ia diagnosticar", r.status == 200, str(r.status))

            with abridor.open(f"{base}/config", timeout=10) as r:
                html = r.read().decode("utf-8", errors="replace")
                anotar("Configuración muestra el diagnóstico",
                       'data-diagnostico="1"' in html, "")
                anotar("La página no expone la clave", "AIza" not in html, "")

            # Acciones que no tocan credenciales reales: guardar configuración y
            # verificar modelos (consulta sólo el catálogo del proveedor).
            for accion, campos in (
                ("guardar", {"cascada": "gemini:gemini-3.5-flash-lite",
                             "presupuesto": "0", "limite_llamadas": "20",
                             "datos": "0", "cache": "1", "proveedores": ["gemini"]}),
                ("verificar", {"proveedor": "gemini"}),
            ):
                carga = {"csrf": csrf.group(1), "accion": accion, **campos}
                datos = urllib.parse.urlencode(carga, doseq=True).encode()
                with abridor.open(f"{base}/ia", data=datos, timeout=30) as r:
                    anotar(f"POST /ia {accion}", r.status == 200, str(r.status))

            # --- búsqueda manual con progreso -----------------------------
            with abridor.open(f"{base}/ofertas", timeout=10) as r:
                html = r.read().decode("utf-8", errors="replace")
            anotar("Ofertas muestra «Buscar ahora»",
                   'id="btn-buscar"' in html and "Buscar ahora" in html, "")
            anotar("Ofertas tiene contenedor de lista incremental",
                   'id="lista-ofertas"' in html, "")
            anotar("Ofertas tiene panel de progreso",
                   'id="panel-busqueda"' in html, "")

            with abridor.open(f"{base}/static/progreso.js", timeout=5) as r:
                js = r.read().decode("utf-8", errors="replace")
            anotar("GET /static/progreso.js", r.status == 200 and "/progreso.json" in js,
                   str(r.status))

            with abridor.open(f"{base}/progreso.json", timeout=10) as r:
                inicial = json.loads(r.read().decode("utf-8"))
            anotar("GET /progreso.json sin corrida",
                   r.status == 200 and "fuentes" in inicial and "ofertas" in inicial,
                   f"estado {inicial.get('estado')}")

            datos = urllib.parse.urlencode({"csrf": csrf.group(1)}).encode()
            with abridor.open(f"{base}/buscar/ahora", data=datos, timeout=20) as r:
                arranque = json.loads(r.read().decode("utf-8"))
            anotar("POST /buscar/ahora", r.status == 200 and arranque.get("iniciada") is True,
                   str(arranque.get("motivo")))

            # Doble pulsación: la segunda debe ver la corrida en curso.
            with abridor.open(f"{base}/buscar/ahora", data=datos, timeout=20) as r:
                segunda = json.loads(r.read().decode("utf-8"))
            anotar("Doble pulsación no duplica la corrida",
                   segunda.get("iniciada") is False, str(segunda.get("motivo")))

            # Sin `--buscar` la corrida se cancela: deja el sistema limpio, prueba
            # la cancelación y no alarga la verificación. Se espera a que la base
            # la publique, o la cancelación llegaría después del final.
            cancelada_por_el_script = False
            if not BUSCAR:
                for _ in range(40):
                    with abridor.open(f"{base}/progreso.json", timeout=10) as r:
                        if json.loads(r.read().decode("utf-8")).get("activo"):
                            break
                    time.sleep(0.25)
                with abridor.open(f"{base}/buscar/cancelar", data=datos, timeout=20) as r:
                    cancelacion = json.loads(r.read().decode("utf-8"))
                cancelada_por_el_script = bool(cancelacion.get("cancelada"))
                anotar("POST /buscar/cancelar sobre una corrida en curso",
                       cancelada_por_el_script, str(cancelacion.get("motivo"))[:80])

            # La corrida arranca en un hilo: hay que esperar a que la base la
            # publique antes de dar por terminada la observación.
            fases: list[str] = []
            arrancada = False
            maximo = time.time() + 240
            while time.time() < maximo:
                with abridor.open(f"{base}/progreso.json", timeout=10) as r:
                    foto = json.loads(r.read().decode("utf-8"))
                if foto.get("activo"):
                    arrancada = True
                    actual = foto["fuentes"].get("actual")
                    marca = (f"{foto['fuentes']['procesadas']}/{foto['fuentes']['total']}"
                             + (f" {actual}" if actual else "")
                             + f" · {foto['ofertas']['clasificadas']} clasificadas"
                             + f" · {foto['ofertas']['nuevas']} nuevas")
                    if not fases or fases[-1] != marca:
                        fases.append(marca)
                    time.sleep(0.7)
                    continue
                if arrancada or cancelada_por_el_script:
                    break
                time.sleep(0.4)   # todavía no se publicó la corrida
            # Cuenta avances distintos, no vueltas del bucle: un reloj que avanza
            # no prueba que la búsqueda progrese.
            anotar("El progreso se movió durante la búsqueda",
                   len(fases) >= 2 if BUSCAR else arrancada,
                   f"{len(fases)} estados distintos · último: {fases[-1] if fases else '—'}")
            anotar("La corrida quedó cerrada, sin fantasmas",
                   foto.get("activo") is False and foto.get("estado") != "running",
                   f"estado {foto.get('estado')}")

            if BUSCAR:
                anotar("Búsqueda terminada", foto.get("estado") == "completed",
                       f"estado {foto.get('estado')} · "
                       f"{foto['fuentes']['procesadas']}/{foto['fuentes']['total']} fuentes")
                resumen = foto.get("resumen") or {}
                anotar("Resumen final con duración y candidatas",
                       resumen.get("duracion_ms") is not None and "candidatas" in resumen,
                       f"{resumen.get('nuevas')} nuevas · "
                       f"{resumen.get('candidatas_nuevas')} candidatas nuevas · "
                       f"{resumen.get('candidatas')} en el catálogo")
                anotar("El progreso sobrevive a la recarga",
                       foto.get("run_id") is not None
                       and json.loads(abridor.open(f"{base}/progreso.json", timeout=10)
                                      .read().decode("utf-8")).get("run_id") == foto.get("run_id"),
                       f"run {foto.get('run_id')}")
                with abridor.open(f"{base}/ofertas", timeout=20) as r:
                    html = r.read().decode("utf-8", errors="replace")
                anotar("Ofertas sigue renderizando tras la búsqueda",
                       r.status == 200 and 'id="lista-ofertas"' in html, str(r.status))
    finally:
        servidor.should_exit = True
        hilo.join(timeout=10)

    print("\nVerificación sobre socket real (uvicorn + HTTP):")
    fallos = 0
    for nombre, ok, detalle in resultados:
        estado = "ok" if ok else "FALLO"
        if not ok:
            fallos += 1
        print(f"  [{estado:^5}] {nombre} {('· ' + detalle) if detalle else ''}")
    print(f"\n{len(resultados) - fallos}/{len(resultados)} comprobaciones correctas")
    return 0 if fallos == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
