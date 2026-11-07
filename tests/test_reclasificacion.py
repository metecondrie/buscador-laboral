"""Reclasificación: cambios de perfil, cambios de reglas y cola pendiente.

Cubre el incidente del 07/11: guardar el perfil desde la interfaz marcó todos los
análisis como obsoletos, encoló 1 280 tareas y no las procesó nadie. El catálogo
quedó vacío (`Elegibilidad: {}`), la cola llena y la aplicación sin ofertas.

Tres invariantes que estas pruebas fijan:

1. Guardar el perfil **no** degrada el perfil: el formulario sólo toca lo que
   muestra.
2. Quien invalida análisis **paga** la reclasificación, o la deja explícitamente
   diferida y hay un camino que la cobra.
3. Procesar la cola nunca pierde historia: los análisis anteriores quedan como
   históricos y los nuevos se suman.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from buscador import config, db, diagnostics, ingest, queue, web, worker
from buscador.adapters.base import Observacion, ResultadoFuente
from buscador.web import crear_app


def _obs(ext: str, titulo: str = "Junior Data Analyst", empresa: str = "Acme") -> Observacion:
    return Observacion(
        source_id="F01",
        external_id=ext,
        url=f"https://ejemplo.test/{ext}",
        titulo=titulo,
        empresa=empresa,
        descripcion_html="<p>SQL required. Python desirable.</p>",
        publicado_en="2026-11-02T00:00:00Z",
        region="Anywhere in the World",
        extra={"texto_plano": "SQL required. Python desirable. Excel. Power BI."},
    )


@pytest.fixture
def ofertas(entorno, perfil_id):
    """Deja tres ofertas guardadas y clasificadas, como antes del incidente."""
    entorno.execute("UPDATE analyses SET obsoleto=1")
    ingest.ingestar(
        entorno,
        ResultadoFuente(source_id="F01", estado="success",
                        observaciones=[_obs(f"ext-{i}", empresa=f"Acme {i}") for i in range(3)]),
        perfil_id,
    )
    worker.procesar_tareas(entorno, "epoch-inicial",
                           perfil=worker.asegurar_perfil(entorno, config.rutas()))
    return entorno


def _vigentes(conn) -> dict:
    filas = conn.execute(
        "SELECT elegibilidad, COUNT(*) AS n FROM analyses WHERE obsoleto=0"
        " GROUP BY elegibilidad").fetchall()
    return {f["elegibilidad"]: f["n"] for f in filas}


def _pendientes(conn) -> int:
    tareas = queue.contar(conn)
    return tareas.get("queued", 0) + tareas.get("deferred", 0) + tareas.get("running", 0)


# --- 1. el formulario no degrada el perfil ----------------------------------

def test_guardar_el_perfil_desde_el_formulario_conserva_lo_que_no_edita(ofertas):
    """El incidente empezó acá: se perdieron remoto_obligatorio y los empleos."""
    actual = worker.asegurar_perfil(ofertas, config.rutas())["datos"]
    actual = json.loads(json.dumps(actual))  # copia profunda
    actual["territorio"].update({"remoto_obligatorio": True, "motivo": "salud",
                                 "acepta_hibrido_en_zona": False, "fuente": "memoria:x"})
    actual["experiencia"].update({"empleos": [{"rol": "Operador"}],
                                  "proyectos": [{"nombre": "portfolio"}],
                                  "detalle": "proyectos propios"})
    actual["idioma"]["fuente"] = "memoria:cv"
    actual["disponibilidad"] = {"desde": "inmediata", "horas_semana": 40, "estado": "activo"}

    class Formulario(dict):
        def getlist(self, clave):
            valor = self.get(clave)
            return valor if isinstance(valor, list) else ([valor] if valor else [])

    formulario = Formulario({
        "csrf": "c", "habilidades": "SQL\nPython", "ingles": "B2", "anios": "1",
        "nivel": "junior", "residencia": "Argentina", "remoto": "1",
        "presencial": "La Plata", "categorias": ["Data Analyst"],
        "desde": "inmediata", "horas": "40",
    })

    datos = web._perfil_desde_formulario(formulario, actual)

    assert datos["territorio"]["remoto_obligatorio"] is True
    assert datos["territorio"]["motivo"] == "salud"
    assert datos["territorio"]["acepta_hibrido_en_zona"] is False
    assert datos["territorio"]["fuente"] == "memoria:x"
    assert datos["territorio"]["presencial"] == ["La Plata"]
    assert datos["experiencia"]["empleos"] == [{"rol": "Operador"}]
    assert datos["experiencia"]["proyectos"] == [{"nombre": "portfolio"}]
    assert datos["idioma"]["fuente"] == "memoria:cv"
    assert datos["disponibilidad"]["estado"] == "activo"
    # Y lo que el formulario sí edita, se edita.
    assert datos["experiencia"]["anios"] == 1
    assert [h["nombre"] for h in datos["habilidades"]] == ["SQL", "Python"]


def test_el_formulario_no_borra_presencial_si_el_campo_no_viene(ofertas):
    class Formulario(dict):
        def getlist(self, clave):
            return []

    actual = {"territorio": {"residencia": "Argentina", "remoto": True,
                             "presencial": ["La Plata"], "remoto_obligatorio": True}}
    datos = web._perfil_desde_formulario(Formulario({"remoto": "1"}), actual)
    assert datos["territorio"]["presencial"] == ["La Plata"]
    assert datos["territorio"]["remoto_obligatorio"] is True


def test_desmarcar_remoto_si_cuenta_como_intencion(ofertas):
    class Formulario(dict):
        def getlist(self, clave):
            return []

    actual = {"territorio": {"remoto": True, "presencial": ["La Plata"]}}
    datos = web._perfil_desde_formulario(Formulario({}), actual)
    assert datos["territorio"]["remoto"] is False


# --- 2. quien invalida, paga ------------------------------------------------

def test_guardar_perfil_procesa_la_reclasificacion(ofertas):
    """Con `procesar` por defecto no queda deuda: no hace falta buscar después."""
    datos = worker.asegurar_perfil(ofertas, config.rutas())["datos"]
    datos["experiencia"] = dict(datos["experiencia"], anios=2)

    perfil = worker.guardar_perfil(ofertas, config.rutas(), datos, origen="manual")

    assert perfil["encoladas"] >= 1
    assert perfil["reclasificacion"]["procesadas"] >= 1
    assert _pendientes(ofertas) == 0
    assert sum(_vigentes(ofertas).values()) == 3


def test_perfil_diferido_deja_alerta_y_se_repara(ofertas):
    """Ese es el estado exacto del incidente: catálogo vacío y cola llena."""
    datos = worker.asegurar_perfil(ofertas, config.rutas())["datos"]
    worker.guardar_perfil(ofertas, config.rutas(), datos, origen="manual", procesar=False)

    assert _pendientes(ofertas) == 3
    assert _vigentes(ofertas) == {}
    estado = diagnostics.clasificacion(ofertas)
    assert estado["alerta"] == "sin_clasificaciones"
    assert estado["analizadas"] == 0
    assert estado["pendientes"] == 3

    resultado = worker.procesar_pendientes(ofertas)

    assert resultado["procesadas"] >= 3
    assert _pendientes(ofertas) == 0
    assert sum(_vigentes(ofertas).values()) == 3
    assert diagnostics.clasificacion(ofertas)["alerta"] == ""
    # La historia no se pierde: los análisis viejos siguen ahí, obsoletos.
    historicos = ofertas.execute("SELECT COUNT(*) FROM analyses WHERE obsoleto=1").fetchone()[0]
    assert historicos >= 3


# --- 3. cambio de reglas ----------------------------------------------------

def test_cambio_de_reglas_reclasifica_y_conserva_el_historial(ofertas, monkeypatch):
    antes = ofertas.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
    perfil = worker.asegurar_perfil(ofertas, config.rutas())
    monkeypatch.setattr(config, "RULES_VERSION", "rules-9.9.9")

    encoladas = worker.sincronizar_reglas(ofertas, perfil["id"])
    assert encoladas >= 3
    # Recién sincronizadas: los análisis viejos quedaron obsoletos y la cola llena.
    assert _vigentes(ofertas) == {}
    assert _pendientes(ofertas) >= 3

    worker.procesar_pendientes(ofertas)

    vigentes = ofertas.execute(
        "SELECT COUNT(*), MIN(rules_version) FROM analyses WHERE obsoleto=0").fetchone()
    assert vigentes[0] == 3
    assert vigentes[1] == "rules-9.9.9"
    assert ofertas.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] > antes
    assert _pendientes(ofertas) == 0


def test_una_cola_de_reglas_anteriores_se_descarta(ofertas):
    """Procesar tareas de otra versión de reglas escribiría análisis de otra época."""
    perfil = worker.asegurar_perfil(ofertas, config.rutas())
    job = ofertas.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]
    version = ingest._asegurar_version(ofertas, job)
    queue.encolar(ofertas, "clasificar", "clasificar:vieja:1", job_id=job,
                  job_version_id=version, profile_version_id=perfil["id"],
                  rules_version="rules-0.0.1")

    worker.procesar_pendientes(ofertas)

    assert _pendientes(ofertas) == 0
    assert queue.contar(ofertas).get("skipped", 0) >= 1


def test_tareas_de_un_perfil_anterior_se_descartan(ofertas):
    """Si el perfil cambió, la cola vieja no debe escribir análisis vigentes."""
    perfil_viejo = worker.asegurar_perfil(ofertas, config.rutas())["id"]
    job = ofertas.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]
    version = ingest._asegurar_version(ofertas, job)
    queue.encolar(ofertas, "clasificar", "clasificar:perfil-viejo:1", job_id=job,
                  job_version_id=version, profile_version_id=perfil_viejo)

    datos = worker.asegurar_perfil(ofertas, config.rutas())["datos"]
    worker.guardar_perfil(ofertas, config.rutas(), datos, origen="manual", procesar=False)
    worker.procesar_pendientes(ofertas)

    vigentes_viejos = ofertas.execute(
        "SELECT COUNT(*) FROM analyses WHERE obsoleto=0 AND profile_version_id=?",
        (perfil_viejo,)).fetchone()[0]
    assert vigentes_viejos == 0
    assert _pendientes(ofertas) == 0


# --- 4. recuperación de tareas colgadas -------------------------------------

def test_tarea_running_de_un_proceso_muerto_se_recupera(ofertas):
    perfil = worker.asegurar_perfil(ofertas, config.rutas())
    job = ofertas.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]
    version = ingest._asegurar_version(ofertas, job)
    queue.encolar(ofertas, "clasificar", "clasificar:colgada:1", job_id=job,
                  job_version_id=version, profile_version_id=perfil["id"])
    with ofertas:
        ofertas.execute(
            "UPDATE tasks SET estado='running', locked_by_epoch='epoch-muerto'"
            " WHERE unique_key='clasificar:colgada:1'")

    resultado = worker.procesar_pendientes(ofertas)

    assert resultado["recuperadas"] == 1
    assert resultado["procesadas"] == 1
    assert _pendientes(ofertas) == 0
    assert queue.contar(ofertas).get("running", 0) == 0


def test_procesar_pendientes_no_roba_tareas_de_una_corrida(ofertas):
    """Con una corrida en curso no procesa: la corrida drena al terminar."""
    perfil = worker.asegurar_perfil(ofertas, config.rutas())
    job = ofertas.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]
    version = ingest._asegurar_version(ofertas, job)
    queue.encolar(ofertas, "clasificar", "clasificar:corrida:1", job_id=job,
                  job_version_id=version, profile_version_id=perfil["id"])

    mutex = worker.Mutex(config.rutas().lock)
    assert mutex.adquirir()
    try:
        resultado = worker.procesar_pendientes(ofertas)
    finally:
        mutex.liberar()

    assert resultado["procesadas"] == 0
    assert "corrida en curso" in resultado["omitido"]
    assert _pendientes(ofertas) == 1


def test_una_busqueda_manual_no_deja_tareas_abandonadas(ofertas, monkeypatch):
    """Criterio de aceptación: después de buscar, la cola no queda a medias."""
    class Fuente:
        source_id = "F01"

        def fetch(self, limite, cursor=None):
            return ResultadoFuente(source_id="F01", estado="success",
                                   observaciones=[_obs(f"busqueda-{i}") for i in range(2)])

    monkeypatch.setattr(worker.adapters, "obtener", lambda sid: Fuente())
    worker.correr(causa="prueba", limite=5, fuentes=["F01"], usar_mutex=False)

    tareas = queue.contar(ofertas)
    assert tareas.get("queued", 0) == 0
    assert tareas.get("deferred", 0) == 0
    assert tareas.get("running", 0) == 0
    assert _pendientes(ofertas) == 0
    # Y quedaron clasificadas.
    assert sum(_vigentes(ofertas).values()) >= 1


# --- 5. diagnóstico y arranque ----------------------------------------------

def _cliente(autoreparar: bool = True) -> TestClient:
    cliente = TestClient(crear_app(token="t", csrf="c", autoreparar=autoreparar),
                         base_url="http://127.0.0.1")
    cliente.get("/entrar?token=t")
    return cliente


def test_diagnostico_muestra_numeros_y_no_diccionarios_crudos(ofertas):
    html = _cliente().get("/diagnostico").text

    assert "Ofertas guardadas" in html
    assert "Analizadas (vigentes)" in html
    assert "Elegibles / dudosas / incompatibles" in html
    assert "Análisis históricos" in html
    # Los diccionarios en crudo eran justamente el síntoma.
    assert "{&#39;completed&#39;" not in html
    assert "Elegibilidad</th><td>{}" not in html


def test_diagnostico_avisa_cuando_el_catalogo_quedo_vacio(ofertas):
    datos = worker.asegurar_perfil(ofertas, config.rutas())["datos"]
    worker.guardar_perfil(ofertas, config.rutas(), datos, origen="manual", procesar=False)

    html = _cliente(autoreparar=False).get("/diagnostico").text

    assert "Ningún análisis vigente" in html
    assert "Reclasificar pendientes" in html


def test_el_boton_de_diagnostico_procesa_la_cola(ofertas):
    datos = worker.asegurar_perfil(ofertas, config.rutas())["datos"]
    worker.guardar_perfil(ofertas, config.rutas(), datos, origen="manual", procesar=False)
    cliente = _cliente(autoreparar=False)
    assert _pendientes(ofertas) > 0

    respuesta = cliente.post("/diagnostico/reclasificar", data={"csrf": "c"},
                             follow_redirects=False)

    assert respuesta.status_code == 303
    cliente.app.state.hilo_reclasificacion.join(timeout=30)
    assert _pendientes(ofertas) == 0
    assert sum(_vigentes(ofertas).values()) == 3


def test_el_arranque_repara_el_catalogo_vacio(ofertas):
    """Abrir la aplicación debe alcanzar para salir del estado de incidente."""
    datos = worker.asegurar_perfil(ofertas, config.rutas())["datos"]
    worker.guardar_perfil(ofertas, config.rutas(), datos, origen="manual", procesar=False)
    assert _vigentes(ofertas) == {}

    cliente = _cliente()          # crear_app dispara la autoreparación
    hilo = cliente.app.state.hilo_reclasificacion
    assert hilo is not None
    hilo.join(timeout=30)

    assert _pendientes(ofertas) == 0
    assert sum(_vigentes(ofertas).values()) == 3


def test_el_arranque_no_toca_nada_si_el_catalogo_esta_sano(ofertas):
    cliente = _cliente()
    assert cliente.app.state.hilo_reclasificacion is None
    assert sum(_vigentes(ofertas).values()) == 3


# --- 6. ofertas que quedan sin análisis vigente -----------------------------

def test_una_oferta_invalidada_se_reencola_aunque_su_tarea_ya_estuviera_hecha(ofertas):
    """El `INSERT OR IGNORE` dejaba ofertas sin análisis y sin tarea pendiente.

    Pasaba cuando el análisis se invalidaba después de que la tarea se hubiera
    completado: la clave ya existía, no se reencolaba nada y la oferta quedaba
    invisible en todas las vistas.
    """
    perfil = worker.asegurar_perfil(ofertas, config.rutas())
    job = ofertas.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]
    # La tarea de esa oferta ya se completó…
    assert ofertas.execute(
        "SELECT COUNT(*) FROM tasks WHERE job_id=? AND estado='completed'", (job,)).fetchone()[0]
    # …y después el análisis se invalidó, sin dejar trabajo pendiente.
    with ofertas:
        ofertas.execute("UPDATE analyses SET obsoleto=1 WHERE job_id=?", (job,))
    assert _pendientes(ofertas) == 0

    # Se vuelve a capturar la misma oferta (mismo identificador de la fuente).
    ingest.ingestar(
        ofertas,
        ResultadoFuente(source_id="F01", estado="success",
                        observaciones=[_obs("ext-0", empresa="Acme 0")]),
        perfil["id"],
    )

    pendientes = ofertas.execute(
        "SELECT COUNT(*) FROM tasks WHERE job_id=? AND estado='queued'", (job,)).fetchone()[0]
    assert pendientes == 1
    worker.procesar_pendientes(ofertas)
    assert ofertas.execute(
        "SELECT COUNT(*) FROM analyses WHERE job_id=? AND obsoleto=0", (job,)).fetchone()[0] == 1


def test_reclasificar_faltantes_cierra_el_hueco(ofertas):
    """Sin tareas pendientes pero con ofertas sin análisis: hay que reencolarlas."""
    with ofertas:
        ofertas.execute("UPDATE analyses SET obsoleto=1 WHERE job_id=("
                        "SELECT id FROM jobs LIMIT 1)")
    assert _pendientes(ofertas) == 0
    estado = diagnostics.clasificacion(ofertas)
    assert estado["sin_analisis"] == 1

    resultado = worker.reclasificar_faltantes(ofertas)

    assert resultado["faltantes"] == 1
    assert resultado["procesadas"] >= 1
    assert diagnostics.clasificacion(ofertas)["sin_analisis"] == 0
    assert sum(_vigentes(ofertas).values()) == 3


def test_el_arranque_no_reencola_todo_cada_vez(ofertas):
    """Sin faltantes el arranque es inerte: no reescribe 1 000 análisis por abrir."""
    antes = ofertas.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    _cliente()
    despues = ofertas.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    assert despues == antes


# --- 6. ofertas que quedan sin análisis vigente -----------------------------

def test_una_oferta_invalidada_se_reencola_aunque_su_tarea_ya_estuviera_hecha(ofertas):
    """El `INSERT OR IGNORE` dejaba ofertas sin análisis y sin tarea pendiente.

    Pasaba cuando el análisis se invalidaba después de que la tarea se hubiera
    completado: la clave ya existía, no se reencolaba nada y la oferta quedaba
    invisible en todas las vistas.
    """
    perfil = worker.asegurar_perfil(ofertas, config.rutas())
    job = ofertas.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]
    # La tarea de esa oferta ya se completó…
    assert ofertas.execute(
        "SELECT COUNT(*) FROM tasks WHERE job_id=? AND estado='completed'", (job,)).fetchone()[0]
    # …y después el análisis se invalidó, sin dejar trabajo pendiente.
    with ofertas:
        ofertas.execute("UPDATE analyses SET obsoleto=1 WHERE job_id=?", (job,))
    assert _pendientes(ofertas) == 0

    # Se vuelve a capturar la misma oferta (mismo identificador de la fuente).
    ingest.ingestar(
        ofertas,
        ResultadoFuente(source_id="F01", estado="success",
                        observaciones=[_obs("ext-0", empresa="Acme 0")]),
        perfil["id"],
    )

    pendientes = ofertas.execute(
        "SELECT COUNT(*) FROM tasks WHERE job_id=? AND estado='queued'", (job,)).fetchone()[0]
    assert pendientes == 1
    worker.procesar_pendientes(ofertas)
    assert ofertas.execute(
        "SELECT COUNT(*) FROM analyses WHERE job_id=? AND obsoleto=0", (job,)).fetchone()[0] == 1


def test_reclasificar_faltantes_cierra_el_hueco(ofertas):
    """Sin tareas pendientes pero con ofertas sin análisis: hay que reencolarlas."""
    with ofertas:
        ofertas.execute("UPDATE analyses SET obsoleto=1 WHERE job_id=("
                        "SELECT id FROM jobs LIMIT 1)")
    assert _pendientes(ofertas) == 0
    estado = diagnostics.clasificacion(ofertas)
    assert estado["sin_analisis"] == 1

    resultado = worker.reclasificar_faltantes(ofertas)

    assert resultado["faltantes"] == 1
    assert resultado["procesadas"] >= 1
    assert diagnostics.clasificacion(ofertas)["sin_analisis"] == 0
    assert sum(_vigentes(ofertas).values()) == 3


def test_el_arranque_no_reencola_todo_cada_vez(ofertas):
    """Sin faltantes el arranque es inerte: no reescribe 1 000 análisis por abrir."""
    antes = ofertas.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    _cliente()
    despues = ofertas.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    assert despues == antes


def test_una_oferta_no_queda_con_dos_analisis_vigentes(ofertas):
    """Dos versiones del mismo aviso no deben aparecer dos veces en la lista."""
    perfil = worker.asegurar_perfil(ofertas, config.rutas())
    job = ofertas.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]
    # Una versión nueva del contenido, con su propio análisis.
    with ofertas:
        ofertas.execute(
            "INSERT INTO job_versions (job_id, semantic_hash, titulo, empresa, requisitos_json,"
            " salario_json, vigencia, creado_en) VALUES (?,?,?,?,?,?,?,?)",
            (job, "hash-nuevo", "Junior Data Analyst", "Acme", "{}", None, "open",
             config.ahora_utc()))
        version_nueva = ofertas.execute("SELECT MAX(id) FROM job_versions WHERE job_id=?",
                                        (job,)).fetchone()[0]
        ofertas.execute(
            """INSERT INTO tasks (kind, unique_key, job_id, job_version_id, profile_version_id,
                   rules_version, estado, intentos, next_due, creado_en, actualizado_en)
               VALUES ('clasificar', 'clasificar:dos-versiones:1', ?, ?, ?, ?, 'queued', 0, ?, ?, ?)""",
            (job, version_nueva, perfil["id"], config.RULES_VERSION,
             config.ahora_utc(), config.ahora_utc(), config.ahora_utc()))

    worker.procesar_pendientes(ofertas)

    vigentes = ofertas.execute(
        "SELECT COUNT(*) FROM analyses WHERE job_id=? AND obsoleto=0", (job,)).fetchone()[0]
    assert vigentes == 1
    # Y el conjunto suma exactamente una fila por oferta.
    estado = diagnostics.clasificacion(ofertas)
    assert (estado["elegibles"] + estado["dudosas"] + estado["incompatibles"]
            == estado["analizadas"])


def test_una_oferta_no_queda_con_dos_analisis_vigentes(ofertas):
    """Dos versiones del mismo aviso no deben aparecer dos veces en la lista."""
    perfil = worker.asegurar_perfil(ofertas, config.rutas())
    job = ofertas.execute("SELECT id FROM jobs LIMIT 1").fetchone()["id"]
    # Una versión nueva del contenido, con su propio análisis.
    with ofertas:
        ofertas.execute(
            "INSERT INTO job_versions (job_id, semantic_hash, titulo, empresa, requisitos_json,"
            " salario_json, vigencia, creado_en) VALUES (?,?,?,?,?,?,?,?)",
            (job, "hash-nuevo", "Junior Data Analyst", "Acme", "{}", None, "open",
             config.ahora_utc()))
        version_nueva = ofertas.execute("SELECT MAX(id) FROM job_versions WHERE job_id=?",
                                        (job,)).fetchone()[0]
        ofertas.execute(
            """INSERT INTO tasks (kind, unique_key, job_id, job_version_id, profile_version_id,
                   rules_version, estado, intentos, next_due, creado_en, actualizado_en)
               VALUES ('clasificar', 'clasificar:dos-versiones:1', ?, ?, ?, ?, 'queued', 0, ?, ?, ?)""",
            (job, version_nueva, perfil["id"], config.RULES_VERSION,
             config.ahora_utc(), config.ahora_utc(), config.ahora_utc()))

    worker.procesar_pendientes(ofertas)

    vigentes = ofertas.execute(
        "SELECT COUNT(*) FROM analyses WHERE job_id=? AND obsoleto=0", (job,)).fetchone()[0]
    assert vigentes == 1
    # Y el conjunto suma exactamente una fila por oferta.
    estado = diagnostics.clasificacion(ofertas)
    assert (estado["elegibles"] + estado["dudosas"] + estado["incompatibles"]
            == estado["analizadas"])
