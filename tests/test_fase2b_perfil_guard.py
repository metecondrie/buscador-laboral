"""Pruebas de la guardia de perfil (Fase 2B).

Complementan `test_fase2a.py`: la guardia de Fase 2A sólo detectaba la
*presencia* del campo ``nivel`` y no miraba salario ni disponibilidad. Cada
prueba parte de una copia del perfil activo y cambia **un** aspecto, para que el
fallo señale exactamente qué comparación falta.

No tocan datos personales: trabajan sobre copias en memoria del perfil canónico.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from buscador import config, perfil_guard  # noqa: E402


def _db_referencia() -> Path:
    """Base de referencia: variable explícita, copia aislada o la operativa.

    En el paquete de activación la copia vive en `<repo>/../datos/data/`; en
    producción no existe y se usa la base operativa, siempre en `mode=ro` y
    copiada con la API de backup antes de escribir nada.
    """
    explicita = os.environ.get("BUSCADOR_DB_REF")
    if explicita:
        return Path(explicita)
    aislada = RAIZ.parent / "datos" / "data" / "buscador.db"
    if aislada.exists():
        return aislada
    configurada = config.rutas().db
    if configurada.exists():
        return configurada
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "BuscadorLaboral" / "data" / "buscador.db"
    return configurada


DB = _db_referencia()
pytestmark = pytest.mark.skipif(not DB.exists(), reason=f"falta la base de referencia {DB}")


@pytest.fixture(scope="module")
def activo() -> dict:
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return perfil_guard.perfil_activo(conn)
    finally:
        conn.close()


def clon(perfil: dict) -> dict:
    return copy.deepcopy(perfil)


def _habilidad(perfil: dict, nombre: str) -> dict:
    for h in perfil["habilidades"]:
        if str(h.get("nombre", "")).casefold() == nombre.casefold():
            return h
    raise AssertionError(f"el perfil no tiene la habilidad {nombre!r}")


# --------------------------------------------------------------------------- #
# Casos pedidos
# --------------------------------------------------------------------------- #

def test_ingles_b1_contra_b2_bloquea(activo):
    propuesto = clon(activo)
    assert propuesto["idioma"]["ingles"] == "B1"
    propuesto["idioma"]["ingles"] = "B2"
    problemas = perfil_guard.diferencias(activo, propuesto)
    assert len(problemas) == 1
    assert "inglés" in problemas[0] and "B2" in problemas[0]
    with pytest.raises(perfil_guard.ReemplazoPerfilBloqueado):
        perfil_guard.validar_reemplazo(activo, propuesto)


def test_nivel_distinto_de_una_habilidad_bloquea(activo):
    propuesto = clon(activo)
    _habilidad(propuesto, "SQL")["nivel"] = "avanzado"
    problemas = perfil_guard.diferencias(activo, propuesto)
    assert len(problemas) == 1, problemas
    assert "nivel" in problemas[0] and "'sql'" in problemas[0].lower()
    assert "avanzado" in problemas[0]
    with pytest.raises(perfil_guard.ReemplazoPerfilBloqueado):
        perfil_guard.validar_reemplazo(activo, propuesto)


def test_nivel_que_cambia_de_valor_bloquea(activo):
    """El caso que la guardia de 2A dejaba pasar: nivel presente en ambos."""
    base = clon(activo)
    for h in base["habilidades"]:
        h["nivel"] = "básico"
    propuesto = clon(base)
    _habilidad(propuesto, "Python")["nivel"] = "avanzado"

    assert perfil_guard.diferencias(base, propuesto), "no detectó el cambio de nivel"
    problemas = perfil_guard.diferencias(base, propuesto)
    assert len(problemas) == 1
    assert "python" in problemas[0].lower() and "avanzado" in problemas[0]


def test_habilidad_faltante_bloquea(activo):
    propuesto = clon(activo)
    propuesto["habilidades"] = [h for h in propuesto["habilidades"]
                                if str(h.get("nombre", "")).casefold() != "docker"]
    problemas = perfil_guard.diferencias(activo, propuesto)
    assert any("falta 'docker'" in p for p in problemas), problemas


def test_habilidad_agregada_bloquea(activo):
    propuesto = clon(activo)
    propuesto["habilidades"].append({"nombre": "Rust"})
    problemas = perfil_guard.diferencias(activo, propuesto)
    assert any("sobra 'rust'" in p for p in problemas), problemas


def test_cambio_de_salario_bloquea(activo):
    propuesto = clon(activo)
    propuesto["salario"]["ars_neto_objetivo"] += 100000
    problemas = perfil_guard.diferencias(activo, propuesto)
    assert len(problemas) == 1, problemas
    assert "salario" in problemas[0] and "ars_neto_objetivo" in problemas[0]


def test_cambio_de_disponibilidad_bloquea(activo):
    propuesto = clon(activo)
    propuesto["disponibilidad"]["horas_semana"] = 20
    problemas = perfil_guard.diferencias(activo, propuesto)
    assert len(problemas) == 1, problemas
    assert "disponibilidad" in problemas[0] and "horas_semana" in problemas[0]


def test_perfil_identico_se_permite(activo):
    assert perfil_guard.diferencias(activo, clon(activo)) == []
    perfil_guard.validar_reemplazo(activo, clon(activo))


# --------------------------------------------------------------------------- #
# Casos adicionales que blindan la comparación
# --------------------------------------------------------------------------- #

def test_diferencias_cosmeticas_se_permiten(activo):
    propuesto = clon(activo)
    propuesto["idioma"]["ingles"] = "  b1 "
    propuesto["habilidades"] = list(reversed(propuesto["habilidades"]))
    propuesto["categorias"] = [c.upper() for c in propuesto["categorias"]]
    assert perfil_guard.diferencias(activo, propuesto) == []


def test_metadatos_no_bloquean(activo):
    propuesto = clon(activo)
    propuesto["version"] = "perfil-20991231T000000Z"
    propuesto["origen"] = "importado"
    propuesto["nota"] = "texto distinto"
    assert perfil_guard.diferencias(activo, propuesto) == []


def test_campo_desconocido_se_trata_como_operativo(activo):
    propuesto = clon(activo)
    propuesto["modalidad_preferida"] = "remoto"
    problemas = perfil_guard.diferencias(activo, propuesto)
    assert any("nuevos sin comparación previa" in p for p in problemas), problemas


def test_restricciones_y_territorio_se_comparan(activo):
    propuesto = clon(activo)
    propuesto["territorio"]["remoto_obligatorio"] = False
    assert any("territorio" in p for p in perfil_guard.diferencias(activo, propuesto))

    propuesto = clon(activo)
    propuesto["restricciones"]["no_postular_automaticamente"] = False
    assert any("restricciones" in p for p in perfil_guard.diferencias(activo, propuesto))


def test_formacion_y_experiencia_se_comparan(activo):
    propuesto = clon(activo)
    propuesto["experiencia"]["anios"] = 3
    assert any("experiencia" in p for p in perfil_guard.diferencias(activo, propuesto))

    propuesto = clon(activo)
    propuesto["formacion"][0]["estado"] = "completado"
    assert any("formacion" in p for p in perfil_guard.diferencias(activo, propuesto))


def test_hash_semantico_ignora_metadatos(activo):
    propuesto = clon(activo)
    propuesto["version"] = "otra"
    assert perfil_guard.hash_semantico(activo) == perfil_guard.hash_semantico(propuesto)
    propuesto["salario"]["ars_neto_objetivo"] += 1
    assert perfil_guard.hash_semantico(activo) != perfil_guard.hash_semantico(propuesto)


def test_cli_importar_con_salario_distinto_no_escribe(activo, tmp_path: Path):
    # La copia de 31 MB va a E:, no al Temporal de C:.
    raiz = Path(r"E:\respaldos_buscador\fase2b\tmp_tests")
    raiz.mkdir(parents=True, exist_ok=True)
    datos = Path(tempfile.mkdtemp(prefix="cli_", dir=raiz))
    (datos / "data").mkdir(parents=True)
    origen = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    destino = sqlite3.connect(str(datos / "data" / "buscador.db"))
    try:
        origen.backup(destino)
    finally:
        destino.close()
        origen.close()
    perfil = datos / "data" / "perfil.json"
    perfil.write_text(json.dumps(activo, ensure_ascii=False), encoding="utf-8")

    propuesto = clon(activo)
    propuesto["salario"]["ars_neto_objetivo"] += 50000
    entrada = tmp_path / "perfil_nuevo.json"
    entrada.write_text(json.dumps(propuesto, ensure_ascii=False), encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(RAIZ)
    env["BUSCADOR_DATA_DIR"] = str(datos)
    try:
        r = subprocess.run([sys.executable, "-m", "buscador", "perfil", "--importar", str(entrada)],
                           cwd=str(RAIZ), env=env, capture_output=True, text=True, timeout=180)
        assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
        assert "BLOQUEADO" in r.stderr
        assert "salario" in r.stderr
        assert json.loads(perfil.read_text(encoding="utf-8")) == activo
    finally:
        shutil.rmtree(datos, ignore_errors=True)
