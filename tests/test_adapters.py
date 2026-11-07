"""Adaptadores contra fixtures versionados: no son verificación de la fuente real."""

from __future__ import annotations

import json

import pytest

from buscador import fetch
from buscador.adapters import Himalayas, Jobicy, WeWorkRemotely
from buscador.fetch import Respuesta
from conftest import FIXTURES


def _respuesta(cuerpo: bytes, tipo: str = "application/json") -> Respuesta:
    return Respuesta(cuerpo=cuerpo, http_status=200, url_final="https://ejemplo", content_type=tipo)


def test_wwr_parsea_fixture(monkeypatch):
    xml = (FIXTURES / "wwr.xml").read_bytes()
    monkeypatch.setattr(fetch, "descargar", lambda url, dominios, aceptar="*/*": _respuesta(xml, "application/rss+xml"))
    resultado = WeWorkRemotely().fetch(10)
    assert resultado.estado == "success"
    assert len(resultado.observaciones) == 3
    primera = resultado.observaciones[0]
    assert primera.empresa == "Acme Data"
    assert primera.titulo == "Junior Data Analyst"
    assert primera.region == "Anywhere in the World"
    # La tercera trae utm_source: se elimina al canonicalizar.
    assert "utm_source" not in resultado.observaciones[2].url


def test_himalayas_parsea_salario_y_seniority(monkeypatch):
    datos = (FIXTURES / "himalayas.json").read_bytes()
    monkeypatch.setattr(fetch, "descargar_json", lambda url, dominios: (json.loads(datos), _respuesta(datos)))
    resultado = Himalayas().fetch(10)
    assert resultado.estado == "success"
    assert resultado.cursor_nuevo == "cursor-de-prueba"
    primero = resultado.observaciones[0]
    assert primero.salario["moneda"] == "USD"
    assert primero.salario["naturaleza"] == "desconocido"
    assert primero.seniority == "Entry-level"


def test_jobicy_parsea_listas_de_industria(monkeypatch):
    datos = (FIXTURES / "jobicy.json").read_bytes()
    monkeypatch.setattr(fetch, "descargar_json", lambda url, dominios: (json.loads(datos), _respuesta(datos)))
    resultado = Jobicy().fetch(10)
    assert resultado.estado == "success"
    assert resultado.observaciones[0].external_id == "900001"
    assert resultado.observaciones[0].categoria_fuente == "Data Analysis"


@pytest.mark.parametrize("codigo", ["rate_limited", "auth_required", "access_restricted", "network_error"])
def test_error_tipado_no_lanza_excepcion(monkeypatch, codigo):
    def fallar(url, dominios):
        raise fetch.ErrorFuente(codigo, "fallo simulado", 429)

    monkeypatch.setattr(fetch, "descargar_json", fallar)
    resultado = Himalayas().fetch(5)
    assert resultado.estado == codigo
    assert resultado.error_code == codigo
    assert resultado.observaciones == []


def test_schema_cambiado_se_detecta(monkeypatch):
    datos = b'{"algo": 1}'
    monkeypatch.setattr(fetch, "descargar_json", lambda url, dominios: (json.loads(datos), _respuesta(datos)))
    resultado = Himalayas().fetch(5)
    assert resultado.estado == "schema_changed"


def test_dominio_no_aprobado_se_rechaza():
    with pytest.raises(fetch.ErrorFuente) as excinfo:
        fetch.descargar("https://example.com/datos", ("python.org",))
    assert excinfo.value.codigo == "access_restricted"


def test_destino_privado_se_rechaza():
    from buscador.textutil import es_url_publica

    valido, motivo = es_url_publica("http://127.0.0.1:8000/x")
    assert not valido
    assert "pública" in motivo or "local" in motivo
