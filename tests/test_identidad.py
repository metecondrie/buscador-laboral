"""Identidad, deduplicación y cola durable (P06, P14)."""

from __future__ import annotations

from buscador import config, db, ingest, queue
from buscador.adapters.base import Observacion, ResultadoFuente


def _observacion(source_id: str = "F01", external_id: str = "ext-1", **cambios) -> Observacion:
    base = dict(
        source_id=source_id,
        external_id=external_id,
        url="https://weworkremotely.com/remote-jobs/acme-junior-data-analyst",
        titulo="Junior Data Analyst",
        empresa="Acme",
        descripcion_html="<p>SQL required.</p>",
        publicado_en="2026-11-01T00:00:00Z",
        region="Anywhere in the World",
        extra={"texto_plano": "SQL required. Python desirable."},
    )
    base.update(cambios)
    return Observacion(**base)


def _ingestar(conn, obs: Observacion, perfil_id: int) -> dict:
    resultado = ResultadoFuente(source_id=obs.source_id, estado="success", observaciones=[obs])
    return ingest.ingestar(conn, resultado, perfil_id)


def test_misma_observacion_no_duplica(entorno, perfil_id):
    obs = _observacion()
    primera = _ingestar(entorno, obs, perfil_id)
    segunda = _ingestar(entorno, obs, perfil_id)

    assert primera["nuevas"] == 1
    assert segunda["sin_cambios"] == 1
    assert entorno.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    assert entorno.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    assert entorno.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_cambio_material_crea_version_y_tarea_nueva(entorno, perfil_id):
    _ingestar(entorno, _observacion(), perfil_id)
    modificada = _observacion(
        external_id="ext-1",
        descripcion_html="<p>SQL y Power BI obligatorios.</p>",
        extra={"texto_plano": "SQL y Power BI obligatorios. Python deseable."},
    )
    stats = _ingestar(entorno, modificada, perfil_id)

    assert stats["actualizadas"] == 1
    assert entorno.execute("SELECT COUNT(*) FROM observation_versions").fetchone()[0] == 2
    assert entorno.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 2
    assert entorno.execute("SELECT COUNT(*) FROM analyses WHERE obsoleto=1").fetchone()[0] == 0


def test_misma_oferta_en_dos_fuentes_se_vincula(entorno, perfil_id):
    _ingestar(entorno, _observacion(source_id="F01", external_id="ext-1"), perfil_id)
    _ingestar(
        entorno,
        _observacion(
            source_id="F02",
            external_id="https://himalayas.app/companies/acme/jobs/junior-data-analyst",
            url="https://himalayas.app/companies/acme/jobs/junior-data-analyst",
        ),
        perfil_id,
    )

    assert entorno.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    assert entorno.execute("SELECT COUNT(*) FROM job_observations").fetchone()[0] == 2
    tipos = {f["tipo_match"] for f in entorno.execute("SELECT tipo_match FROM job_observations")}
    assert tipos == {"fuerte", "debil"}


def test_reclamo_atomico_y_recuperacion(entorno):
    queue.encolar(entorno, "clasificar", "clave-1")
    queue.encolar(entorno, "clasificar", "clave-2")

    primera = queue.reclamar(entorno, "epoch-a", limite=10)
    assert len(primera) == 2
    assert queue.reclamar(entorno, "epoch-a", limite=10) == []

    # Simula caída: la tarea queda tomada por una época abandonada.
    recuperadas = queue.recuperar_huerfanas(entorno, "epoch-b")
    assert recuperadas == 2
    segunda = queue.reclamar(entorno, "epoch-b", limite=10)
    assert len(segunda) == 2


def test_tarea_completada_no_se_reclama(entorno):
    queue.encolar(entorno, "clasificar", "clave-3")
    tarea = queue.reclamar(entorno, "epoch-a", limite=1)[0]
    queue.completar(entorno, tarea["id"])
    assert queue.reclamar(entorno, "epoch-a", limite=5) == []
    assert queue.contar(entorno) == {"completed": 1}


def test_encolar_es_idempotente(entorno):
    assert queue.encolar(entorno, "clasificar", "clave-4") is True
    assert queue.encolar(entorno, "clasificar", "clave-4") is False
    assert entorno.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_corrida_abandonada_se_marca(entorno):
    epoch_vieja = "epoch-vieja"
    run_id = ingest.abrir_corrida(entorno, "prueba", epoch_vieja)
    queue.recuperar_huerfanas(entorno, "epoch-nueva")
    estado = entorno.execute("SELECT estado FROM runs WHERE id=?", (run_id,)).fetchone()["estado"]
    assert estado == "abandoned"


def test_entidades_html_se_desescapan_al_ingresar(entorno, perfil_id):
    from buscador import ingest
    from buscador.adapters.base import Observacion, ResultadoFuente

    obs = Observacion(
        source_id="F01", external_id="ent-1", url="https://ejemplo.test/ent-1",
        titulo="Customer Support &amp; Travel", empresa="Aisles &amp; Abroad",
        descripcion_html="<p>SQL required.</p>", publicado_en="2026-11-01T00:00:00Z",
        region="Anywhere in the World", extra={"texto_plano": "SQL required."},
    )
    ingest.ingestar(entorno, ResultadoFuente("F01", "success", [obs]), perfil_id)
    fila = entorno.execute("SELECT titulo, empresa FROM jobs").fetchone()
    assert fila["titulo"] == "Customer Support & Travel"
    assert fila["empresa"] == "Aisles & Abroad"


def test_saneamiento_corrige_filas_viejas(entorno, perfil_id):
    from buscador import ingest

    with entorno:
        entorno.execute(
            "INSERT INTO jobs (id, titulo, empresa, estado_vigencia, primera_deteccion, ultima_deteccion,"
            " semantic_hash, fuente_principal) VALUES ('j1', 'Ops &amp; Support', 'A &amp; B', 'open',"
            " '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z', 'h', 'F01')"
        )
    assert ingest.sanear_textos(entorno) == 1
    fila = entorno.execute("SELECT titulo, empresa FROM jobs WHERE id='j1'").fetchone()
    assert fila["titulo"] == "Ops & Support"
    assert ingest.sanear_textos(entorno) == 0
