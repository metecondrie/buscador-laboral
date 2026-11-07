"""Guardián de la copia publicable y de la sincronización saneada.

Estas pruebas fallan si algún archivo contiene datos personales o credenciales,
si el saneado deja de ser idempotente, si se excluye código necesario para
evitar un conflicto, o si un cambio funcional real pasa desapercibido. Corren
sin red, sin claves y sin usar datos personales reales: se usan valores
sintéticos y los patrones prohibidos se arman por partes para que este mismo
archivo no dispare la puerta que audita.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "tools"))

import publicar  # noqa: E402
from publicacion import saneado  # noqa: E402


def J(*piezas: str) -> str:
    """Junta fragmentos: el archivo fuente nunca contiene el patrón completo."""
    return "".join(piezas)


NOMBRE = "NombreDePrueba"
USUARIO = "UsuarioDePrueba"
CORREO = J("personal", "@", "ejemplo", ".test")
EQUIPO = J("DESK", "TOP-", "ABC1234")
SALUD = J("condición de ", "salud")
BANDA = J('"ars_neto_referencia": ', "123456")

#: Datos personales sintéticos: las reglas se prueban sin leer local.json.
QUIEN = {
    "usuario": USUARIO,
    "correo": CORREO,
    "nombre": NOMBRE,
    "equipo": EQUIPO,
    "bandas": {"ars_referencia": 123456, "ars_objetivo": 234567, "usd_hora": 9},
}

SUCIO = (
    'ruta = r"C:\\Users\\' + USUARIO + '\\AppData\\Local\\Programs\\Python\\Python314"\n'
    + 'otra = "%USERPROFILE%/proyecto"\n'
    + "Contacto: " + CORREO + "\n"
    + "Equipo: " + EQUIPO + "\n"
    + "Nota para " + NOMBRE + ": " + SALUD + " que impide el traslado regular.\n"
    + "Memoria-" + NOMBRE + "\n"
    + BANDA + "\n"
)


# --- 1. la anonimización funciona -------------------------------------------

def test_anonimizacion_funciona():
    assert saneado.verificar_texto(SUCIO, "nota.md", QUIEN), (
        "el documento de prueba no contenía datos personales detectables"
    )
    limpio = saneado.sanear_texto(SUCIO, "nota.md", QUIEN)

    for valor in (USUARIO, CORREO, NOMBRE, EQUIPO, SALUD, BANDA):
        assert valor not in limpio, "quedó un dato sin anonimizar"
    assert "%USERPROFILE%" in limpio or "<RUTA_DEL_USUARIO>" in limpio
    assert "el usuario" in limpio
    assert "restricción declarada" in limpio
    assert '"ars_neto_referencia": None' in limpio
    assert saneado.verificar_texto(limpio, "nota.md", QUIEN) == []
    # Una segunda pasada no cambia nada.
    assert saneado.sanear_texto(limpio, "nota.md", QUIEN) == limpio


def test_el_user_agent_deja_el_contacto_en_el_entorno():
    crudo = J('USER_AGENT = "BuscadorLaboral/0.2 (prototipo local; contacto: ',
              CORREO, ')"\n')
    limpio = saneado.sanear_texto(crudo, "buscador/config.py", QUIEN)
    assert CORREO not in limpio
    assert "BUSCADOR_CONTACTO" in limpio
    assert "os.environ.get" in limpio


def test_sanear_en_disco_es_idempotente_y_conserva_crlf(tmp_path, monkeypatch):
    monkeypatch.setattr(saneado, "datos", lambda: QUIEN)
    muestra = tmp_path / "nota.md"
    muestra.write_bytes(SUCIO.replace("\n", "\r\n").encode("utf-8"))

    assert saneado.sanear(tmp_path) == ["nota.md"]
    primera = muestra.read_bytes()
    assert saneado.sanear(tmp_path) == []
    assert muestra.read_bytes() == primera
    assert b"\r\n" in primera              # no reescribimos 133 archivos por nada
    assert saneado.verificar(tmp_path, saneado.archivos(tmp_path)) == []


# --- 2. no se filtran datos personales ni secretos --------------------------

SECRETOS = [
    J("AI", "za", "A" * 35),
    J("s", "k-", "a" * 24),
    J("gh", "p_", "b" * 24),
    J("github", "_pat_", "c" * 24),
    J("-----BEGIN ", "PRIVATE KEY-----"),
    J("alguien", "@", "gmail", ".", "com"),
    J("DESK", "TOP-", "ZYX9876"),
    SALUD,
    J('"ars_neto_referencia": ', "900000"),
    J("https://", "usuario:clave", "@ejemplo.test"),
]


def test_la_puerta_detecta_cada_tipo_de_secreto():
    for muestra in SECRETOS:
        hallazgos = saneado.verificar_texto(f"dato = {muestra}\n", "x.py", QUIEN)
        assert hallazgos, "la puerta no detectó un patrón prohibido"


def test_el_documento_saneado_no_tiene_hallazgos():
    limpio = saneado.sanear_texto(SUCIO, "nota.md", QUIEN)
    assert saneado.verificar_texto(limpio, "nota.md", QUIEN) == []


def test_la_puerta_sigue_activa_en_el_arbol_y_en_las_reglas():
    assert saneado.verificar(RAIZ, saneado.archivos(RAIZ)) == []
    assert "tools/publicacion/local.json" in saneado.EXENTOS
    assert "tools/publicacion/saneado.py" in saneado.EXENTOS
    ignorados = (RAIZ / ".gitignore").read_text(encoding="utf-8")
    assert "tools/publicacion/local.json" in ignorados
    assert "*.local.json" in ignorados
    versionados = publicar.git("ls-files").splitlines()
    assert "tools/publicacion/local.json" not in versionados


def test_las_rutas_prohibidas_siguen_bloqueadas():
    assert saneado.verificar(RAIZ, [RAIZ / "data" / "buscador.db"])
    assert saneado.verificar(RAIZ, [RAIZ / ".env"])


# --- 3. no se excluye código necesario --------------------------------------

def test_rules_py_no_esta_excluido_y_sigue_en_la_copia():
    assert "buscador/rules.py" not in publicar.NO_SINCRONIZAR
    assert (RAIZ / "buscador" / "rules.py").is_file()
    informe = RAIZ / "docs" / "publicacion" / "simulacion.md"
    if informe.exists():
        assert "buscador/rules.py" in informe.read_text(encoding="utf-8")


def test_un_cambio_de_codigo_se_propaga_completo():
    base = '"""Reglas v1."""\n\ndef umbral():\n    return 75\n'
    head = ('"""Reglas v2."""\n\ndef umbral():\n    return 80\n\n'
            'COBERTURA_MINIMA_DUDA = 0.45\n')
    cambio = saneado.clasificar_cambio(base, head, "buscador/rules.py", QUIEN)

    assert cambio["saneado_difiere"] is True
    assert cambio["funcional"] is True
    assert cambio["equivalente"] is False
    assert "COBERTURA_MINIMA_DUDA" in cambio["saneado_head"]
    assert "return 80" in cambio["saneado_head"]


def test_el_cambio_real_del_original_se_detecta_como_funcional():
    """Con el proyecto original presente: rules-2.0.0 → rules-3.0.0."""
    if not publicar.ORIGINAL.is_dir():
        pytest.skip("el proyecto original no está disponible en este entorno")
    base = publicar.git("show", "78a9d7a:buscador/rules.py", cwd=publicar.ORIGINAL)
    head = publicar.git("show", "HEAD:buscador/rules.py", cwd=publicar.ORIGINAL)
    cambio = saneado.clasificar_cambio(base, head, "buscador/rules.py")
    assert cambio["funcional"] is True
    assert cambio["valida"] is True
    assert len(cambio["saneado_head"]) > len(cambio["saneado_base"])


# --- 4. los cambios funcionales verdaderos siguen detectándose --------------

def test_un_cambio_solo_de_texto_anonimo_es_equivalente():
    # Dos grafías que el saneador reduce a la misma representación: el cambio
    # crudo desaparece y la huella funcional confirma que no tocó código.
    base = '"""Requisito: condición de ' + J("salud") + '."""\n\ndef f():\n    return 1\n'
    head = '"""Requisito: condicion de ' + J("salud") + '."""\n\ndef f():\n    return 1\n'
    cambio = saneado.clasificar_cambio(base, head, "buscador/x.py", QUIEN)
    assert cambio["crudo_difiere"] is True
    assert cambio["saneado_difiere"] is False
    assert cambio["funcional"] is False
    assert cambio["equivalente"] is True


def test_un_cambio_en_el_cuerpo_de_una_funcion_no_es_equivalente():
    base = '"""Doc."""\n\ndef f():\n    return 1\n'
    head = '"""Doc."""\n\ndef f():\n    return 2\n'
    cambio = saneado.clasificar_cambio(base, head, "buscador/x.py", QUIEN)
    assert cambio["funcional"] is True
    assert cambio["equivalente"] is False


def _parchear_git(monkeypatch, base: str, head: str) -> None:
    def falso(*args, **kwargs):
        if args[0] == "show":
            return base if args[1].startswith("BASE:") else head
        raise AssertionError("llamada git inesperada")
    monkeypatch.setattr(publicar, "git", falso)


def test_resolver_escribe_la_representacion_saneada_del_head(tmp_path, monkeypatch):
    ruta = "buscador/x.py"
    base = '"""Doc."""\n\ndef f():\n    return 1\n'
    head = '"""Doc."""\n\ndef f():\n    return 2\n'
    destino = tmp_path / ruta
    destino.parent.mkdir(parents=True)
    destino.write_text(saneado.sanear_texto(base, ruta, QUIEN), encoding="utf-8")
    monkeypatch.setattr(publicar, "raiz_activa", lambda: tmp_path)
    monkeypatch.setattr(saneado, "datos", lambda: QUIEN)
    _parchear_git(monkeypatch, base, head)

    clase, _ = publicar._resolver_por_saneado(ruta, "M", "BASE", "HEAD")
    assert clase == "reemplazado"
    assert "return 2" in destino.read_text(encoding="utf-8")


def test_resolver_rechaza_una_divergencia_funcional_local(tmp_path, monkeypatch):
    ruta = "buscador/x.py"
    base = '"""Doc."""\n\ndef f():\n    return 1\n'
    head = '"""Doc."""\n\ndef f():\n    return 2\n'
    destino = tmp_path / ruta
    destino.parent.mkdir(parents=True)
    destino.write_text('"""Doc."""\n\ndef f():\n    return 999\n', encoding="utf-8")
    monkeypatch.setattr(publicar, "raiz_activa", lambda: tmp_path)
    monkeypatch.setattr(saneado, "datos", lambda: QUIEN)
    _parchear_git(monkeypatch, base, head)

    clase, motivo = publicar._resolver_por_saneado(ruta, "M", "BASE", "HEAD")
    assert clase == "conflicto"
    assert "divergió" in motivo
    assert "return 999" in destino.read_text(encoding="utf-8")  # no se pisó nada


def test_resolver_no_deshabilita_la_puerta_de_secretos(tmp_path, monkeypatch):
    ruta = "buscador/x.py"
    base = '"""Doc."""\n\ndef f():\n    return 1\n'
    head = ('"""Doc."""\n\nCLAVE = "' + J("AI", "za", "A" * 35)
            + '"\n\ndef f():\n    return 2\n')
    destino = tmp_path / ruta
    destino.parent.mkdir(parents=True)
    destino.write_text(saneado.sanear_texto(base, ruta, QUIEN), encoding="utf-8")
    monkeypatch.setattr(publicar, "raiz_activa", lambda: tmp_path)
    monkeypatch.setattr(saneado, "datos", lambda: QUIEN)
    _parchear_git(monkeypatch, base, head)

    clase, motivo = publicar._resolver_por_saneado(ruta, "M", "BASE", "HEAD")
    assert clase == "conflicto"
    assert "sensibles" in motivo
    assert "return 1" in destino.read_text(encoding="utf-8")


def test_resolver_acepta_un_cambio_equivalente_sin_escribir(tmp_path, monkeypatch):
    ruta = "buscador/x.py"
    base = '"""Requisito: condición de ' + J("salud") + '."""\n\ndef f():\n    return 1\n'
    head = '"""Requisito: condicion de ' + J("salud") + '."""\n\ndef f():\n    return 1\n'
    destino = tmp_path / ruta
    destino.parent.mkdir(parents=True)
    original = saneado.sanear_texto(base, ruta, QUIEN)
    destino.write_text(original, encoding="utf-8")
    monkeypatch.setattr(publicar, "raiz_activa", lambda: tmp_path)
    monkeypatch.setattr(saneado, "datos", lambda: QUIEN)
    _parchear_git(monkeypatch, base, head)

    clase, _ = publicar._resolver_por_saneado(ruta, "M", "BASE", "HEAD")
    assert clase == "equivalente"
    assert destino.read_text(encoding="utf-8") == original


# --- 5. sincronización reproducible e idempotente ---------------------------

def _huella_desde_salida(salida: str) -> str:
    encontrado = re.findall(r"huella del árbol: ([0-9a-f]{16})", salida)
    assert encontrado, "la simulación no informó la huella del árbol"
    return encontrado[-1]


def test_dos_simulaciones_producen_el_mismo_arbol(capsys):
    if not publicar.ORIGINAL.is_dir():
        pytest.skip("el proyecto original no está disponible en este entorno")
    assert publicar.simular(sin_pruebas=True) == 0
    primera = _huella_desde_salida(capsys.readouterr().out)
    assert publicar.simular(sin_pruebas=True) == 0
    segunda = _huella_desde_salida(capsys.readouterr().out)
    assert primera == segunda


def test_la_simulacion_no_toca_el_registro_ni_el_repo_real(capsys):
    if not publicar.ORIGINAL.is_dir():
        pytest.skip("el proyecto original no está disponible en este entorno")
    antes = (RAIZ / publicar.REGISTRO).read_bytes()
    head_antes = publicar.git("rev-parse", "HEAD")
    assert publicar.simular(sin_pruebas=True) == 0
    salida = capsys.readouterr().out
    assert "sin commit, sin registro, sin push" in salida
    assert (RAIZ / publicar.REGISTRO).read_bytes() == antes
    assert publicar.git("rev-parse", "HEAD") == head_antes
    assert publicar.raiz_activa() == RAIZ  # se restauró la raíz activa


def test_sincronizar_al_dia_no_cambia_nada(monkeypatch):
    monkeypatch.setattr(publicar, "estado", lambda silencioso=False: {
        "base_registrada": "abc123", "original_head": "abc123",
        "copia_head": "xyz", "copia_sucio": [], "original_sucio": [],
    })
    monkeypatch.setattr(publicar, "git", lambda *args, **kwargs: "")
    assert publicar.sincronizar() == 0


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
