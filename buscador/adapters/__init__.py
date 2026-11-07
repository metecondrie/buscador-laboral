"""Registro de adaptadores habilitados.

Once fuentes verificadas contra su respuesta real (ver
`docs/evidencia/fuentes-verificacion.json`). Cada entrada declara método,
autorización y atribución para que la comprobación sea auditable.
"""

from __future__ import annotations

from .arbeitnow import Arbeitnow
from .ats import Ashby, Greenhouse, Lever
from .base import Adaptador, Observacion, Particion, ResultadoFuente
from .himalayas import Himalayas
from .jobicy import Jobicy
from .jobspresso import Jobspresso
from .nodesk import NoDesk
from .pythonjobs import PythonOrgJobs
from .remoteok import RemoteOK
from .remotive import Remotive
from .themuse import TheMuse
from .workingnomads import WorkingNomads
from .wwr import WeWorkRemotely

ADAPTADORES = {
    "F01": WeWorkRemotely,
    "F02": Himalayas,
    "F03": Jobicy,
    "F04": RemoteOK,
    "F05": TheMuse,
    "F06": WorkingNomads,
    "F07": NoDesk,
    "F08": Jobspresso,
    "F09": PythonOrgJobs,
    "F10": Arbeitnow,
    "F11": Remotive,
    "F12": Greenhouse,
    "F13": Lever,
    "F14": Ashby,
}


def obtener(source_id: str) -> Adaptador:
    clase = ADAPTADORES.get(source_id)
    if clase is None:
        raise KeyError(f"adaptador no registrado: {source_id}")
    return clase()


def metadatos() -> list[dict]:
    return [
        {
            "source_id": clase.source_id,
            "publisher_key": clase.publisher_key,
            "nombre": clase.nombre,
            "url_base": clase.url_base,
            "endpoint": clase.endpoint,
            "metodo": clase.metodo,
            "autorizacion": clase.autorizacion,
            "atribucion": clase.atribucion,
            "cuota": clase.cuota,
            "frecuencia": clase.frecuencia,
            "parser_version": clase.parser_version,
            "particiones": [p.clave for p in clase().particiones],
        }
        for clase in ADAPTADORES.values()
    ]


__all__ = ["ADAPTADORES", "Adaptador", "Observacion", "Particion", "ResultadoFuente",
           "obtener", "metadatos"]
