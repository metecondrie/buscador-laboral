"""Adaptadores nuevos contra fixtures versionados.

Un fixture prueba el parser, no la disponibilidad de la fuente. La verificación
contra la respuesta real se registra en `docs/evidencia/fuentes-verificacion.json`.
"""

from __future__ import annotations

import json

import pytest

from buscador import fetch
from buscador.adapters import (Arbeitnow, Jobspresso, NoDesk, PythonOrgJobs,
                               RemoteOK, Remotive, TheMuse, WorkingNomads)
from buscador.adapters.comun import salario_texto
from buscador.fetch import Respuesta
from conftest import FIXTURES


def _respuesta(cuerpo: bytes, tipo: str = "application/json") -> Respuesta:
    return Respuesta(cuerpo=cuerpo, http_status=200, url_final="https://ejemplo", content_type=tipo)


def _json(nombre: str):
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


def _fijar_json(monkeypatch, datos):
    monkeypatch.setattr(fetch, "descargar_json", lambda url, dominios: (datos, _respuesta(b"")))


def _fijar_xml(monkeypatch, nombre: str):
    cuerpo = (FIXTURES / nombre).read_bytes()
    monkeypatch.setattr(
        fetch, "descargar",
        lambda url, dominios, aceptar="*/*": _respuesta(cuerpo, "application/rss+xml"),
    )


def test_remoteok_salta_el_aviso_legal(monkeypatch):
    _fijar_json(monkeypatch, _json("remoteok.json"))
    resultado = RemoteOK().fetch(10)
    assert resultado.estado == "success"
    assert len(resultado.observaciones) == 2
    primera = resultado.observaciones[0]
    assert primera.external_id.isdigit()
    assert primera.empresa
    # El primer elemento del listado es un aviso legal sin `id`: no debe entrar.
    assert all(o.titulo for o in resultado.observaciones)


def test_themuse_normaliza_empresa_ubicacion_y_nivel(monkeypatch):
    _fijar_json(monkeypatch, _json("themuse.json"))
    resultado = TheMuse().fetch(10)
    assert resultado.estado == "success"
    primera = resultado.observaciones[0]
    assert primera.empresa
    assert primera.region
    assert primera.seniority


def test_workingnomads_usa_la_url_como_identidad(monkeypatch):
    _fijar_json(monkeypatch, _json("workingnomads.json"))
    resultado = WorkingNomads().fetch(10)
    assert resultado.estado == "success"
    assert resultado.observaciones[0].external_id.startswith("https://")


def test_arbeitnow_desescapa_html_dos_veces(monkeypatch):
    _fijar_json(monkeypatch, _json("arbeitnow.json"))
    resultado = Arbeitnow().fetch(10)
    assert resultado.estado == "success"
    assert resultado.cursor_nuevo == "2"
    assert "&lt;" not in resultado.observaciones[0].descripcion_html


def test_remotive_lee_salario_en_texto_libre(monkeypatch):
    datos = _json("remotive.json")
    datos["jobs"][0]["salary"] = "$70,000 - $90,000 /year"
    _fijar_json(monkeypatch, datos)
    resultado = Remotive().fetch(10)
    salario = resultado.observaciones[0].salario
    assert salario is not None
    assert salario["min"] == 70000
    assert salario["max"] == 90000
    assert salario["moneda"] == "USD"
    assert salario["periodo"] == "year"
    assert salario["naturaleza"] == "desconocido"


@pytest.mark.parametrize("texto,esperado", [
    ("Competitive", None),
    ("", None),
    ("USD 45 per hour", (45.0, None, "USD", "hour")),
    ("€2.500 - €3.000 /month", (2500.0, 3000.0, "EUR", "month")),
])
def test_salario_texto_no_inventa(texto, esperado):
    resultado = salario_texto(texto)
    if esperado is None:
        assert resultado is None
    else:
        assert (resultado["min"], resultado["max"], resultado["moneda"], resultado["periodo"]) == esperado


def test_nodesk_repara_entidades_html(monkeypatch):
    """NoDesk publica &rsquo;, que no existe en XML: debe repararse, no fallar."""
    _fijar_xml(monkeypatch, "nodesk.xml")
    resultado = NoDesk().fetch(10)
    assert resultado.estado == "success"
    assert len(resultado.observaciones) == 2
    assert resultado.observaciones[0].empresa == "Northwind"
    assert resultado.observaciones[1].empresa == "Contoso"


def test_jobspresso_separa_empresa_y_region_del_autor(monkeypatch):
    _fijar_xml(monkeypatch, "jobspresso.xml")
    resultado = Jobspresso().fetch(10)
    assert resultado.estado == "success"
    primera = resultado.observaciones[0]
    assert primera.empresa == "Initech"
    assert "Anywhere" in (primera.region or "")
    # El pie "The post ... appeared first on" no debe quedar en el texto.
    assert "appeared first on" not in primera.descripcion_html


def test_pythonorg_separa_organizacion_y_localidad(monkeypatch):
    _fijar_xml(monkeypatch, "pythonjobs.xml")
    resultado = PythonOrgJobs().fetch(10)
    assert resultado.estado == "success"
    primera = resultado.observaciones[0]
    assert primera.empresa == "Umbrella Corp"
    assert primera.titulo == "Data Engineer"
    assert primera.region == "Remote, Remote"
    # El HTML se conserva para la ficha; el texto plano es el que se analiza.
    assert "<p>" not in primera.extra["texto_plano"]
    assert "Build pipelines" in primera.extra["texto_plano"]


def test_todas_las_fuentes_declaran_metadatos():
    from buscador import adapters

    assert len(adapters.ADAPTADORES) >= 10
    for meta in adapters.metadatos():
        for campo in ("source_id", "nombre", "endpoint", "metodo", "autorizacion",
                      "atribucion", "cuota", "frecuencia", "parser_version"):
            assert meta[campo], f"{meta.get('source_id')} sin {campo}"
        assert meta["endpoint"].startswith("https://")
