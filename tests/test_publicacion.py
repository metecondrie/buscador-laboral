"""Guardián de la copia publicable.

Estas pruebas fallan si algún archivo del repositorio contiene datos personales,
credenciales o artefactos que no deben publicarse, y si el saneado deja de ser
idempotente. Corren sin red y sin datos de nadie.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "tools"))

from publicacion import saneado  # noqa: E402


def test_no_hay_datos_personales_ni_credenciales():
    hallazgos = saneado.verificar(RAIZ, saneado.archivos(RAIZ))
    assert hallazgos == [], "la copia publicable tiene datos sensibles: " + "; ".join(hallazgos)


def test_el_saneado_es_idempotente(tmp_path):
    muestra = tmp_path / "nota.md"
    muestra.write_text("Listo.\n", encoding="utf-8")
    assert saneado.sanear(tmp_path) == []
    assert muestra.read_text(encoding="utf-8") == "Listo.\n"


def test_las_exclusiones_de_git_cubren_los_datos_locales():
    ignorados = (RAIZ / ".gitignore").read_text(encoding="utf-8")
    for patron in ("data/", "logs/", "backups/", "exports/", "*.db",
                   "perfil.local.json", ".env", ".venv/"):
        assert patron in ignorados, f".gitignore no excluye {patron}"
