"""Bandeja de Actividad: registros legibles, puntajes separados y lectura durable.

El problema reportado: la pestaña mostraba el volcado de `payload_json`, `clave`
y `estado` (`delivered`) en crudo, y un mismo aviso parecía tener dos puntajes
distintos. La causa de los dos puntajes es real y legítima: el payload guarda el
puntaje **al emitir el aviso** y `analyses` tiene el **vigente**; lo que faltaba
era no mezclarlos y no presentar una recomendación vieja como actual.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from buscador import config, db, ingest, notify, worker
from buscador.adapters.base import Observacion, ResultadoFuente
from buscador.web import crear_app

TOKEN = "token-actividad"
CSRF = "csrf-actividad"


def _obs(ext: str, titulo: str, empresa: str) -> Observacion:
    return Observacion(
        source_id="F01", external_id=ext, url=f"https://ejemplo.test/{ext}",
        titulo=titulo, empresa=empresa,
        descripcion_html="<p>SQL required. Excel required. Python required. Remote.</p>",
        publicado_en="2026-11-05T00:00:00Z", region="Anywhere in the World",
        extra={"texto_plano": "SQL required. Excel required. Python required. Remote."},
    )


def _aviso(conn, job_id: str, titulo: str, empresa: str, score: float,
           estado: str = "delivered", leido: bool = False) -> int:
    """Inserta una notificación como la genera el motor, con puntaje histórico."""
    payload = {"job_id": job_id, "titulo": titulo, "empresa": empresa,
               "score": score, "confianza": "alta"}
    with db.transaccion(conn):
        cur = conn.execute(
            """INSERT OR IGNORE INTO notifications
                   (clave, job_id, canal, estado, payload_json, creado_en, leido_en)
               VALUES (?,?, 'inbox', ?, ?, ?, ?)""",
            (f"{job_id}|inbox|alta", job_id, estado,
             json.dumps(payload, ensure_ascii=False), config.ahora_utc(),
             config.ahora_utc() if leido else None),
        )
    return cur.lastrowid


@pytest.fixture
def con_avisos(entorno, perfil_id):
    """Tres ofertas reales con análisis vigente y tres avisos con puntajes viejos."""
    ofertas = [
        ("ext-act-1", "Remote Office Assistant", "Coalition Technologies"),
        ("ext-act-2", "Technical Support Engineer", "Alloy"),
        ("ext-act-3", "Remote Data Entry Clerk", "NoGigiddy"),
    ]
    ingest.ingestar(
        entorno,
        ResultadoFuente(source_id="F01", estado="success",
                        observaciones=[_obs(*o) for o in ofertas]),
        perfil_id,
    )
    worker.procesar_tareas(entorno, "epoch-actividad",
                           perfil=worker.asegurar_perfil(entorno, config.crear_estructura()))
    filas = entorno.execute("SELECT id, titulo, empresa FROM jobs ORDER BY id").fetchall()
    scores_viejos = (90.0, 86.0, 100.0)
    for fila, score in zip(filas, scores_viejos):
        _aviso(entorno, fila["id"], fila["titulo"], fila["empresa"], score)
    # Un aviso ya leído, para probar ambos estados de lectura.
    with db.transaccion(entorno):
        entorno.execute(
            "UPDATE notifications SET leido_en=? WHERE id=(SELECT MIN(id) FROM notifications)",
            (config.ahora_utc(),),
        )
    return entorno


@pytest.fixture
def cliente(con_avisos):
    app = crear_app(token=TOKEN, csrf=CSRF)
    c = TestClient(app, base_url="http://127.0.0.1")
    c.get(f"/entrar?token={TOKEN}")
    return c


# --- 1. renderizado ---------------------------------------------------------

def test_actividad_muestra_registros_legibles(cliente, con_avisos):
    html = cliente.get("/actividad").text

    for titulo in ("Remote Office Assistant", "Technical Support Engineer",
                   "Remote Data Entry Clerk"):
        assert titulo in html
    assert "Coalition Technologies" in html
    assert "Alloy" in html
    assert "/oferta/job_" in html                 # enlace a la ficha
    assert "sin leer" in html and "leído" in html  # ambos estados
    assert 'class="badge eligible"' in html       # elegibilidad actual
    # Nada de volcado crudo.
    for crudo in ("payload_json", "clave", "delivered", "{'queued'", "None"):
        assert crudo not in html, f"volcado crudo en la página: {crudo}"


def test_actividad_no_muestra_estado_de_entrega_como_envio(cliente, con_avisos):
    """`delivered` = está en la bandeja local; no es un correo ni una postulación."""
    html = cliente.get("/actividad").text
    assert "bandeja local" in html
    assert "delivered" not in html
    assert "queued" not in html
    # Y no se creó ninguna postulación por despachar avisos.
    assert con_avisos.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 0


# --- 2. puntaje histórico vs vigente ----------------------------------------

def test_los_dos_puntajes_se_distinguen_y_no_se_mezclan(con_avisos):
    registros = {r["titulo"]: r for r in notify.bandeja(con_avisos)}

    oficina = registros["Remote Office Assistant"]
    assert oficina["score_al_avisar"] == 90.0        # inmutable: viene del payload
    assert oficina["score_actual"] is not None
    assert oficina["score_actual"] != 90.0
    assert oficina["cambio_puntaje"] is True
    assert "payload_json" not in oficina
    assert "clave" not in oficina


def test_reclasificar_no_reescribe_el_puntaje_historico(con_avisos):
    antes = {r["id"]: r["score_al_avisar"] for r in notify.bandeja(con_avisos)}
    with db.transaccion(con_avisos):
        con_avisos.execute("UPDATE analyses SET score=33.3 WHERE obsoleto=0")
    despues = {r["id"]: r["score_al_avisar"] for r in notify.bandeja(con_avisos)}
    actuales = [r["score_actual"] for r in notify.bandeja(con_avisos)]

    assert despues == antes            # el histórico no se toca
    assert all(s == 33.3 for s in actuales)  # el vigente sí cambió


def test_una_recomendacion_obsoleta_se_marca_como_tal(con_avisos, cliente):
    """Alloy era elegible al avisar; con las reglas actuales es dudosa."""
    job_id = con_avisos.execute(
        "SELECT id FROM jobs WHERE titulo='Technical Support Engineer'").fetchone()["id"]
    with db.transaccion(con_avisos):
        con_avisos.execute(
            "UPDATE analyses SET elegibilidad='doubtful' WHERE job_id=? AND obsoleto=0",
            (job_id,),
        )

    registro = next(r for r in notify.bandeja(con_avisos) if r["job_id"] == job_id)
    assert registro["desactualizado"] is True
    assert registro["score_al_avisar"] == 86.0

    html = cliente.get("/actividad").text
    assert "badge doubtful" in html
    assert "la recomendación quedó desactualizada" in html
    assert "al avisar" in html


def test_sin_analisis_vigente_no_se_presenta_como_recomendacion_actual(con_avisos, cliente):
    with db.transaccion(con_avisos):
        con_avisos.execute("UPDATE analyses SET obsoleto=1")
    html = cliente.get("/actividad").text
    assert "sin análisis vigente" in html
    assert "la recomendación quedó desactualizada" in html


# --- 3. persistencia y deduplicación ----------------------------------------

def test_el_aviso_se_recupera_tras_reiniciar(con_avisos):
    """Conexión y aplicación nuevas: la bandeja lee lo que está en la base."""
    rutas = config.rutas()
    otra = db.conectar(rutas.db)
    try:
        assert len(notify.bandeja(otra)) == 3
    finally:
        otra.close()

    app = crear_app(token="otro-token", csrf="otro-csrf")
    c = TestClient(app, base_url="http://127.0.0.1")
    c.get("/entrar?token=otro-token")
    assert "Remote Office Assistant" in c.get("/actividad").text


def test_la_clave_unica_evita_avisos_duplicados(con_avisos):
    fila = con_avisos.execute("SELECT id, titulo, empresa FROM jobs LIMIT 1").fetchone()
    _aviso(con_avisos, fila["id"], fila["titulo"], fila["empresa"], 55.0)
    _aviso(con_avisos, fila["id"], fila["titulo"], fila["empresa"], 66.0)

    assert con_avisos.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 3
    registros = notify.bandeja(con_avisos)
    ids = [r["id"] for r in registros]
    assert len(ids) == len(set(ids))
    # El histórico conserva el primer puntaje; reintentar no lo pisa.
    assert next(r for r in registros if r["job_id"] == fila["id"])["score_al_avisar"] in (90.0, 86.0, 100.0)


def test_reclasificar_no_genera_un_segundo_aviso(con_avisos, perfil_id):
    job_id = con_avisos.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]
    worker.reclasificar_todo(con_avisos, perfil_id)
    worker.procesar_pendientes(con_avisos)
    assert con_avisos.execute(
        "SELECT COUNT(*) FROM notifications WHERE job_id=?", (job_id,)).fetchone()[0] == 1


# --- 4. marcado como leído ---------------------------------------------------

def test_marcar_leidos_es_durable_e_idempotente(cliente, con_avisos):
    assert notify.no_leidos(con_avisos) == 2
    respuesta = cliente.post("/avisos/leidos", data={"csrf": CSRF}, follow_redirects=False)
    assert respuesta.status_code == 303
    assert notify.no_leidos(con_avisos) == 0
    assert notify.marcar_leidos(con_avisos) == 0

    html = cliente.get("/actividad").text
    # «sin leer» es texto fijo del resumen de la bandeja y del tooltip del
    # enlace de Actividad: su sola presencia no dice nada del estado guardado.
    # La aserción se acota al componente que sí representa la lectura: la
    # columna «Lectura» de cada aviso y la pastilla del navegador.
    tabla = (html.split("<h2>Bandeja de avisos</h2>", 1)[1]
             .split("<table", 1)[1].split("</table>", 1)[0])
    assert "<b>sin leer</b>" not in tabla
    assert tabla.count("leído") == 3
    enlace_actividad = html.split('<a href="/actividad"', 1)[1].split("</a>", 1)[0]
    assert '<span class="pill"' not in enlace_actividad
    assert "leído" in html


def test_marcar_leidos_exige_csrf(cliente, con_avisos):
    assert cliente.post("/avisos/leidos", data={"csrf": "malo"}).status_code == 400
    assert notify.no_leidos(con_avisos) == 2


def test_despachar_solo_entrega_en_la_bandeja(con_avisos):
    with db.transaccion(con_avisos):
        con_avisos.execute("UPDATE notifications SET estado='queued'")
    entregados = notify.despachar(con_avisos)
    assert entregados == 3
    registros = notify.bandeja(con_avisos)
    assert all(r["estado_db"] == "delivered" for r in registros)
    assert all(r["canal"] == "bandeja local" for r in registros)
    # El estado de entrega no altera la lectura ni crea eventos de usuario.
    assert notify.no_leidos(con_avisos) == 2
    assert con_avisos.execute("SELECT COUNT(*) FROM user_events").fetchone()[0] == 0


# --- 5. regresiones adicionales ---------------------------------------------

def test_la_pastilla_del_nav_es_un_numero_y_no_una_lista(cliente, con_avisos):
    """El bug original: `avisos` (entero) pisado por la lista de la bandeja.

    La cabecera imprimía el `repr` de la lista completa. El contador ahora tiene
    nombre propio (`avisos_no_leidos`) y no puede ser sobrescrito por la ruta.
    """
    html = cliente.get("/actividad").text
    assert '<span class="pill">2</span>' in html
    for crudo in ("&#39;creado_en&#39;", "score_al_avisar", "estado_db",
                  "payload_json", "&#39;leido&#39;"):
        assert crudo not in html, f"volcado crudo en la cabecera: {crudo}"


def test_la_cola_tiene_etiquetas_y_no_un_diccionario(cliente, con_avisos):
    job_id = con_avisos.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]
    ahora = config.ahora_utc()
    with db.transaccion(con_avisos):
        con_avisos.execute(
            """INSERT INTO tasks (kind, unique_key, job_id, rules_version, estado,
                   intentos, next_due, creado_en, actualizado_en)
               VALUES ('clasificar', 'cola-visible:1', ?, 'rules-3.1.0', 'queued',
                       0, ?, ?, ?)""",
            (job_id, ahora, ahora, ahora),
        )
    html = cliente.get("/actividad").text
    assert "cola de clasificación: 1 pendientes" in html
    assert "queued=" not in html


def test_si_el_puntaje_no_cambio_no_se_muestra_una_comparacion(con_avisos):
    """Sólo se aclara «al avisar» cuando el puntaje vigente difiere."""
    job_id = con_avisos.execute(
        "SELECT id FROM jobs WHERE titulo='Remote Office Assistant'").fetchone()["id"]
    with db.transaccion(con_avisos):
        con_avisos.execute(
            "UPDATE analyses SET score=90.0, elegibilidad='eligible' "
            "WHERE job_id=? AND obsoleto=0", (job_id,),
        )
    registro = next(r for r in notify.bandeja(con_avisos) if r["job_id"] == job_id)
    assert registro["score_al_avisar"] == 90.0
    assert registro["cambio_puntaje"] is False
    assert registro["desactualizado"] is False


def test_despachar_no_intenta_tostada_sin_habilitarla(con_avisos, monkeypatch):
    """Con el escritorio apagado, despachar no debe iniciar ningún proceso."""
    llamadas = []
    monkeypatch.setattr(
        notify, "_toast",
        lambda t, m: llamadas.append((t, m)) or (True, "mostrado"),
    )
    with db.transaccion(con_avisos):
        con_avisos.execute("UPDATE notifications SET estado='queued'")
    assert notify.despachar(con_avisos) == 3
    assert llamadas == []


def test_persiste_en_un_proceso_nuevo(con_avisos, tmp_path):
    """Un intérprete distinto lee los mismos avisos desde una copia de la base."""
    datos = tmp_path / "copia" / "data"
    datos.mkdir(parents=True)
    destino = datos / "buscador.db"
    src = sqlite3.connect(config.rutas().db)
    dst = sqlite3.connect(destino)
    src.backup(dst)
    dst.close()
    src.close()

    codigo = (
        "import json\n"
        "from buscador import config, db, notify\n"
        "c = db.conectar(config.rutas().db)\n"
        "r = notify.bandeja(c)\n"
        "print(json.dumps({'n': len(r),\n"
        "                  'titulos': sorted(x['titulo'] for x in r),\n"
        "                  'historicos': sorted(x['score_al_avisar'] for x in r)},\n"
        "                 ensure_ascii=False))\n"
    )
    env = dict(os.environ, BUSCADOR_DATA_DIR=str(datos.parent))
    proceso = subprocess.run(
        [sys.executable, "-c", codigo], env=env, capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parents[1]), check=False,
    )
    assert proceso.returncode == 0, proceso.stderr[-400:]
    leido = json.loads(proceso.stdout.strip().splitlines()[-1])
    assert leido == {
        "n": 3,
        "titulos": ["Remote Data Entry Clerk", "Remote Office Assistant",
                    "Technical Support Engineer"],
        "historicos": [86.0, 90.0, 100.0],
    }


def test_marcar_leidos_no_toca_las_postulaciones(cliente, con_avisos):
    """Leído es un estado del aviso; una postulación es otro hecho."""
    job_id = con_avisos.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]
    with db.transaccion(con_avisos):
        con_avisos.execute(
            "INSERT INTO applications (job_id, estado, fecha, creado_en, actualizado_en) "
            "VALUES (?, 'postulada', '2026-11-06', '2026-11-06T00:00:00Z', "
            "'2026-11-06T00:00:00Z')", (job_id,),
        )
    cliente.post("/avisos/leidos", data={"csrf": CSRF})
    fila = con_avisos.execute(
        "SELECT estado, fecha FROM applications WHERE job_id=?", (job_id,)).fetchone()
    assert fila["estado"] == "postulada"
    assert fila["fecha"] == "2026-11-06"
    assert notify.no_leidos(con_avisos) == 0
