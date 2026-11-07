"""Respaldos, restauración, exportación, programación, incidentes y diagnóstico."""

from __future__ import annotations

import csv
import json
import zipfile
from datetime import datetime, timedelta, timezone

from buscador import (backups, config, db, diagnostics, incidents, scheduler,
                      verify, worker)


def _sembrar(conn, perfil_id, titulo="Data Analyst", empresa="Acme", ext="x1"):
    from buscador import ingest
    from buscador.adapters.base import Observacion, ResultadoFuente

    obs = Observacion(
        source_id="F01", external_id=ext, url=f"https://ejemplo.test/{ext}",
        titulo=titulo, empresa=empresa, descripcion_html="<p>SQL required.</p>",
        publicado_en="2026-11-01T00:00:00Z", region="Anywhere in the World",
        extra={"texto_plano": "SQL required. Python desirable."},
    )
    ingest.ingestar(conn, ResultadoFuente("F01", "success", [obs]), perfil_id)
    worker.procesar_tareas(conn, "epoch-sembrado")


def test_respaldo_verificado_y_restauracion(entorno, perfil_id):
    _sembrar(entorno, perfil_id)
    rutas = config.rutas()
    creado = backups.crear(entorno, rutas, "prueba")
    assert creado["verificado"] is True
    assert creado["integridad"] == "ok"
    archivo = creado["archivo"]

    listado = backups.listar(rutas)
    assert any(f["archivo"] == creado["archivo"].replace("\\", "/").split("/")[-1] for f in listado)

    verificacion = backups.verificar(archivo)
    assert verificacion["ok"] is True
    assert verificacion["jobs"] >= 1

    # Se destruye el estado y se restaura desde el respaldo.
    with db.transaccion(entorno):
        entorno.execute("DELETE FROM jobs")
    assert entorno.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0

    # Restaurar exige la base libre: es lo que ocurre al cerrar la aplicación.
    entorno.close()
    restaurado = backups.restaurar(archivo, rutas)
    assert restaurado["respaldo_previo"]
    conn = db.conectar(rutas.db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] >= 1
        assert db.pragmas(conn)["user_version"] == db.VERSION_ESQUEMA
    finally:
        conn.close()


def test_retencion_borra_los_mas_antiguos(entorno, perfil_id, tmp_path):
    rutas = config.rutas()
    for indice in range(4):
        destino = rutas.backups / f"buscador-2026010{indice}T000000Z.db"
        destino.write_bytes(b"x")
        import os
        os.utime(destino, (1000 + indice, 1000 + indice))
    borrados = backups.limpiar(rutas, conservar=2)
    assert len(borrados) == 2
    assert len(backups.listar(rutas)) == 2


def test_exportacion_neutraliza_formulas(entorno, perfil_id):
    _sembrar(entorno, perfil_id, titulo="=HYPERLINK(\"http://mal\")", empresa="+Suma")
    resultado = backups.exportar_csv(entorno, config.rutas())
    with open(resultado["archivo"], encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.reader(archivo, delimiter=";"))
    cuerpo = "\n".join(",".join(f) for f in filas[1:])
    assert "'=HYPERLINK" in cuerpo
    assert "'+Suma" in cuerpo


def test_programacion_cada_doce_horas(entorno):
    ahora = datetime.now(timezone.utc)
    assert scheduler.debe_correr(entorno, ahora) is True  # nunca corrió
    with db.transaccion(entorno):
        entorno.execute(
            "INSERT INTO runs (causa, estado, started_at, run_epoch) VALUES ('automatica','completed',?,?)",
            (config.ahora_utc(), "epoch-auto-1"),
        )
    assert scheduler.debe_correr(entorno, ahora) is False
    assert scheduler.debe_correr(entorno, ahora + timedelta(hours=12, minutes=1)) is True
    assert scheduler.intervalo_horas(entorno) == 12


def test_intervalo_configurable(entorno):
    db.guardar_ajuste(entorno, "intervalo_horas", "6")
    assert scheduler.intervalo_horas(entorno) == 6
    db.guardar_ajuste(entorno, "intervalo_horas", "no-es-numero")
    assert scheduler.intervalo_horas(entorno) == config.INTERVALO_HORAS


def test_incidente_no_se_duplica_y_se_cierra_al_recuperar(entorno):
    incidents.registrar(entorno, "F01", "network_error", "timeout")
    incidents.registrar(entorno, "F01", "network_error", "timeout de nuevo")
    assert len(incidents.abiertos(entorno)) == 1
    assert incidents.resolver_por_exito(entorno, "F01") == 1
    assert incidents.abiertos(entorno) == []
    historial = incidents.historial(entorno)
    assert historial and historial[0]["resuelto_en"]


def test_paquete_de_diagnostico_sin_secretos(entorno, perfil_id):
    _sembrar(entorno, perfil_id)
    incidents.registrar(entorno, "F02", "rate_limited", "HTTP 429")
    destino = diagnostics.paquete(entorno, config.rutas())
    assert zipfile.is_zipfile(destino)
    with zipfile.ZipFile(destino) as paquete:
        nombres = set(paquete.namelist())
        assert {"diagnostico.json", "corridas.json", "incidentes.json", "LEEME.txt"} <= nombres
        texto = paquete.read("diagnostico.json").decode("utf-8")
        datos = json.loads(texto)
        assert "base" in datos and "fuentes" in datos
        assert "api_key" not in texto.lower()


def test_doctor_incluye_fuentes_y_salud(entorno):
    resumen = diagnostics.resumen(entorno, config.rutas())
    assert resumen["app"]["esquema"] == db.VERSION_ESQUEMA
    assert set(resumen["fuentes"]) >= {"F01", "F02", "F03"}
    assert "programacion" in resumen and "ia" in resumen


def test_verificacion_no_persiste_ofertas(entorno, perfil_id, monkeypatch):
    """Verificar fuentes mide; no debe ingerir avisos en la base."""
    from buscador.adapters.base import Observacion, ResultadoFuente

    class _Falsa:
        source_id = "F01"
        nombre = "Falsa"
        metodo = "test"
        endpoint = "https://ejemplo.test"
        parser_version = "test-1"
        particiones = ()

        def fetch(self, limite, cursor=None, particion=None):
            return ResultadoFuente("F01", "success", [Observacion(
                source_id="F01", external_id="e1", url="https://ejemplo.test/e1",
                titulo="Data Analyst", empresa="Acme", descripcion_html="<p>SQL required</p>",
                publicado_en="2026-11-01T00:00:00Z", region="Anywhere in the World",
                extra={"texto_plano": "SQL required. Python desirable."},
            )])

    monkeypatch.setattr(verify.adapters, "metadatos", lambda: [{
        "source_id": "F01", "publisher_key": "x", "nombre": "Falsa", "url_base": "https://ejemplo.test",
        "endpoint": "https://ejemplo.test", "metodo": "test", "autorizacion": "test",
        "atribucion": "test", "cuota": "test", "frecuencia": "test", "parser_version": "test-1",
    }])
    monkeypatch.setattr(verify.adapters, "obtener", lambda sid: _Falsa())
    datos = verify.verificar_todas(entorno, limite=5)
    assert datos["fuentes"][0]["relevantes"] == 1
    assert datos["resumen"]["aceptadas"] == 1
    assert entorno.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    assert entorno.execute("SELECT COUNT(*) FROM source_verifications").fetchone()[0] == 1


def test_ciclo_interno_respeta_el_interruptor(entorno):
    """El hilo de 12 h no corre si el usuario no lo activó, aunque esté vencido."""
    ahora = datetime.now(timezone.utc)
    db.guardar_ajuste(entorno, "corrida_automatica", "0")
    assert scheduler.corresponde_corrida(entorno, ahora) is False

    db.guardar_ajuste(entorno, "corrida_automatica", "1")
    assert scheduler.corresponde_corrida(entorno, ahora) is True  # nunca corrió

    with db.transaccion(entorno):
        entorno.execute(
            "INSERT INTO runs (causa, estado, started_at, run_epoch) VALUES ('automatica','completed',?,?)",
            (config.ahora_utc(), "epoch-ciclo"),
        )
    assert scheduler.corresponde_corrida(entorno, ahora) is False
    assert scheduler.corresponde_corrida(entorno, ahora + timedelta(hours=12, minutes=2)) is True
