"""Ingestión transaccional: observaciones, identidad y encolado (T02)."""

from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from . import config, db
from .adapters.base import Observacion, ResultadoFuente
from .adapters import metadatos
from .textutil import hash_semantico, hash_texto, normalizar

DIAS_VENTANA_IDENTIDAD = 30
UMBRAL_SUGERENCIA = 0.82
# Ruido de forma, no de fondo: se ignora al comparar títulos.
# El nivel ("junior", "senior") NO se ignora: distingue puestos distintos.
_RUIDO_PUESTO = {
    "remote", "remoto", "hybrid", "hibrido", "full", "time", "part", "tiempo",
    "completo", "parcial", "contract", "contractor", "freelance", "temporary",
    "the", "of", "and", "y", "m", "w", "d", "f", "x",
}


def sanear_textos(conn: sqlite3.Connection) -> int:
    """Corrige títulos y empresas ya guardados con entidades HTML. Idempotente."""
    corregidas = 0
    with db.transaccion(conn):
        for tabla in ("jobs", "observations"):
            filas = conn.execute(
                f"SELECT id, titulo, empresa FROM {tabla} "
                "WHERE titulo LIKE '%&%;%' OR empresa LIKE '%&%;%'"
            ).fetchall()
            for fila in filas:
                titulo = html.unescape(fila["titulo"] or "").strip()
                empresa = html.unescape(fila["empresa"]).strip() if fila["empresa"] else None
                conn.execute(
                    f"UPDATE {tabla} SET titulo=?, empresa=? WHERE id=?",
                    (titulo, empresa, fila["id"]),
                )
                corregidas += 1
    return corregidas


def sembrar_fuentes(conn: sqlite3.Connection) -> None:
    with db.transaccion(conn):
        for meta in metadatos():
            conn.execute(
                """
                INSERT INTO sources (source_id, publisher_key, nombre, url_base, endpoint,
                                     metodo, autorizacion, atribucion, cuota, frecuencia,
                                     parser_version, activo, creado_en)
                VALUES (:source_id, :publisher_key, :nombre, :url_base, :endpoint,
                        :metodo, :autorizacion, :atribucion, :cuota, :frecuencia,
                        :parser_version, 1, :creado_en)
                ON CONFLICT(source_id) DO UPDATE SET
                    nombre=excluded.nombre, endpoint=excluded.endpoint,
                    autorizacion=excluded.autorizacion, atribucion=excluded.atribucion,
                    cuota=excluded.cuota, frecuencia=excluded.frecuencia,
                    parser_version=excluded.parser_version
                """,
                {**meta, "creado_en": config.ahora_utc()},
            )


def abrir_corrida(conn: sqlite3.Connection, causa: str, epoch: str) -> int:
    with db.transaccion(conn):
        cur = conn.execute(
            "INSERT INTO runs (causa, estado, started_at, run_epoch, heartbeat_at) VALUES (?, 'running', ?, ?, ?)",
            (causa, config.ahora_utc(), epoch, config.ahora_utc()),
        )
        return int(cur.lastrowid)


def cerrar_corrida(conn: sqlite3.Connection, run_id: int, estado: str, notas: str | None = None) -> None:
    with db.transaccion(conn):
        conn.execute(
            "UPDATE runs SET estado=?, finished_at=?, notas=? WHERE id=?",
            (estado, config.ahora_utc(), notas, run_id),
        )


def abrir_source_run(conn: sqlite3.Connection, run_id: int, source_id: str, cursor: str | None) -> int:
    with db.transaccion(conn):
        cur = conn.execute(
            """INSERT INTO source_runs (run_id, source_id, estado, started_at, cursor_previo)
               VALUES (?, ?, 'running', ?, ?)""",
            (run_id, source_id, config.ahora_utc(), cursor),
        )
        return int(cur.lastrowid)


def planificar_source_runs(conn: sqlite3.Connection, run_id: int,
                           source_ids: list[str]) -> dict[str, int]:
    """Crea en `pending` una fila por fuente antes de consultar ninguna.

    Es lo que le da un denominador real a la barra de progreso: el total no se
    estima, se conoce al planificar y cada fila cambia de estado cuando esa
    fuente terminó de verdad.
    """
    ids: dict[str, int] = {}
    with db.transaccion(conn):
        for source_id in source_ids:
            cur = conn.execute(
                """INSERT INTO source_runs (run_id, source_id, estado, started_at)
                   VALUES (?, ?, 'pending', ?)""",
                (run_id, source_id, config.ahora_utc()),
            )
            ids[source_id] = int(cur.lastrowid)
        conn.execute("UPDATE runs SET total_fuentes=? WHERE id=?", (len(source_ids), run_id))
    return ids


def iniciar_source_run(conn: sqlite3.Connection, source_run_id: int) -> None:
    """Marca el comienzo de una fuente ya planificada."""
    with db.transaccion(conn):
        conn.execute(
            "UPDATE source_runs SET estado='running', started_at=? WHERE id=?",
            (config.ahora_utc(), source_run_id),
        )


def cancelar_pendientes(conn: sqlite3.Connection, run_id: int) -> int:
    """Cierra como `cancelled` las fuentes que no llegaron a consultarse.

    No toca las que ya terminaron: lo descargado y clasificado se conserva.
    """
    with db.transaccion(conn):
        cur = conn.execute(
            """UPDATE source_runs SET estado='cancelled', finished_at=?
               WHERE run_id=? AND estado IN ('pending','running')""",
            (config.ahora_utc(), run_id),
        )
    return cur.rowcount


def cerrar_source_run(conn: sqlite3.Connection, source_run_id: int, resultado: ResultadoFuente,
                      nuevas: int, actualizadas: int, cursor_nuevo: str | None) -> None:
    with db.transaccion(conn):
        conn.execute(
            """UPDATE source_runs SET estado=?, finished_at=?, http_status=?, observaciones=?,
                   nuevas=?, actualizadas=?, error_code=?, error_msg=?, cursor_nuevo=?, detalle_json=?
               WHERE id=?""",
            (
                resultado.estado,
                config.ahora_utc(),
                resultado.http_status,
                len(resultado.observaciones),
                nuevas,
                actualizadas,
                resultado.error_code,
                resultado.error_msg,
                cursor_nuevo,
                json.dumps(resultado.detalle, ensure_ascii=False),
                source_run_id,
            ),
        )


def ingestar(conn: sqlite3.Connection, resultado: ResultadoFuente, profile_version_id: int | None) -> dict:
    """Persiste el lote válido y encola la clasificación en una transacción breve."""
    stats = {"nuevas": 0, "actualizadas": 0, "sin_cambios": 0, "jobs_nuevos": 0, "encoladas": 0, "vinculadas": 0}
    if not resultado.observaciones:
        return stats

    with db.transaccion(conn):
        for obs in resultado.observaciones:
            _persistir_observacion(conn, obs, stats, profile_version_id)
    return stats


def _persistir_observacion(conn: sqlite3.Connection, obs: Observacion, stats: dict,
                           profile_version_id: int | None) -> None:
    # Las fuentes publican entidades HTML en títulos y empresas ("&amp;").
    # Se desescapan una vez, al entrar, para no arrastrarlas a la vista ni al hash.
    obs.titulo = html.unescape(obs.titulo or "").strip()
    obs.empresa = html.unescape(obs.empresa).strip() if obs.empresa else None
    obs.region = html.unescape(obs.region).strip() if obs.region else None

    texto = obs.extra.get("texto_plano") or ""
    semantic = {
        "titulo": normalizar(obs.titulo),
        "empresa": normalizar(obs.empresa),
        "region": normalizar(obs.region),
        "texto": normalizar(texto)[:4000],
        "salario": obs.salario,
        "publicado": (obs.publicado_en or "")[:10],
    }
    content_hash = hash_semantico(semantic)
    ahora = config.ahora_utc()
    detectado = obs.publicado_en or ahora

    fila = conn.execute(
        "SELECT id, content_hash FROM observations WHERE source_id=? AND external_id=?",
        (obs.source_id, obs.external_id),
    ).fetchone()

    if fila is None:
        cur = conn.execute(
            """INSERT INTO observations (source_id, external_id, url, url_final, titulo, empresa,
                   descripcion_texto, publicado_en, publicado_origen, detectado_en, content_hash,
                   parser_version, field_status_json, evidencia_json,
                   seniority, skills, categoria_fuente)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                obs.source_id, obs.external_id, obs.url, obs.url,
                obs.titulo, obs.empresa, texto, obs.publicado_en, "feed",
                ahora, content_hash, "v1",
                json.dumps(obs.field_status, ensure_ascii=False),
                json.dumps(obs.evidencia, ensure_ascii=False),
                obs.seniority, obs.skills, obs.categoria_fuente,
            ),
        )
        observation_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO observation_versions (observation_id, content_hash, capturado_en, cambios_json) VALUES (?,?,?,?)",
            (observation_id, content_hash, ahora, json.dumps({"tipo": "primera_captura"})),
        )
        stats["nuevas"] += 1
    else:
        observation_id = int(fila["id"])
        if fila["content_hash"] == content_hash:
            stats["sin_cambios"] += 1
        else:
            conn.execute(
                """UPDATE observations SET titulo=?, empresa=?, descripcion_texto=?, publicado_en=?,
                       detectado_en=?, content_hash=?, field_status_json=?, evidencia_json=?,
                       seniority=?, skills=?, categoria_fuente=? WHERE id=?""",
                (
                    obs.titulo, obs.empresa, texto, obs.publicado_en, ahora, content_hash,
                    json.dumps(obs.field_status, ensure_ascii=False),
                    json.dumps(obs.evidencia, ensure_ascii=False),
                    obs.seniority, obs.skills, obs.categoria_fuente, observation_id,
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO observation_versions (observation_id, content_hash, capturado_en, cambios_json) VALUES (?,?,?,?)",
                (observation_id, content_hash, ahora, json.dumps({"tipo": "cambio_material"})),
            )
            stats["actualizadas"] += 1
            conn.execute("UPDATE analyses SET obsoleto=1 WHERE job_id IN (SELECT job_id FROM job_observations WHERE observation_id=?)", (observation_id,))

    job_id = _resolver_oferta(conn, obs, observation_id, content_hash, detectado, stats)
    if job_id and profile_version_id is not None:
        _encolar_clasificacion(conn, job_id, profile_version_id, stats)


def _resolver_oferta(conn: sqlite3.Connection, obs: Observacion, observation_id: int,
                     content_hash: str, detectado: str, stats: dict) -> str | None:
    vinculada = conn.execute(
        "SELECT job_id FROM job_observations WHERE observation_id=?", (observation_id,)
    ).fetchone()
    if vinculada is not None:
        job_id = vinculada["job_id"]
        conn.execute("UPDATE jobs SET ultima_deteccion=? WHERE id=?", (config.ahora_utc(), job_id))
        _actualizar_si_cambio(conn, job_id, obs, content_hash)
        return job_id

    candidato = _buscar_coincidencia_debil(conn, obs)
    if candidato:
        job_id = candidato
        stats["vinculadas"] += 1
    else:
        job_id = "job_" + hash_texto(f"{obs.source_id}|{obs.external_id}")[:20]
        existente = conn.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
        if existente is None:
            conn.execute(
                """INSERT INTO jobs (id, titulo, empresa, categoria, modalidad, territorio, salario_json,
                       estado_vigencia, publicado_en, primera_deteccion, ultima_deteccion, semantic_hash,
                       url_atribucion, fuente_principal)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job_id, obs.titulo, obs.empresa, None, None, obs.region,
                    json.dumps(obs.salario, ensure_ascii=False) if obs.salario else None,
                    _vigencia(obs), obs.publicado_en, config.ahora_utc(), config.ahora_utc(),
                    content_hash, obs.url, obs.source_id,
                ),
            )
            stats["jobs_nuevos"] += 1
            stats["sugerencias"] = stats.get("sugerencias", 0) + _sugerir_fusion(conn, obs, job_id)

    conn.execute(
        """INSERT OR IGNORE INTO job_observations (job_id, observation_id, tipo_match, motivo, agrupacion_version)
           VALUES (?,?,?,?,?)""",
        (
            job_id, observation_id,
            "debil" if candidato else "fuerte",
            "empresa y título equivalentes en ventana de 30 días" if candidato else "identificador de la fuente",
            config.AGRUPACION_VERSION,
        ),
    )
    _actualizar_si_cambio(conn, job_id, obs, content_hash)
    return job_id


def _buscar_coincidencia_debil(conn: sqlite3.Connection, obs: Observacion) -> str | None:
    if not obs.empresa:
        return None
    desde = (datetime.now(timezone.utc) - timedelta(days=DIAS_VENTANA_IDENTIDAD)).isoformat()
    filas = conn.execute(
        """SELECT id, titulo, empresa, ultima_deteccion FROM jobs
           WHERE empresa IS NOT NULL AND ultima_deteccion>=? AND merged_into IS NULL""",
        (desde,),
    ).fetchall()
    objetivo = (normalizar(obs.empresa), normalizar(obs.titulo))
    for fila in filas:
        if (normalizar(fila["empresa"]), normalizar(fila["titulo"])) == objetivo:
            return fila["id"]
    return None


def tokens_puesto(titulo: str) -> set[str]:
    """Tokens significativos del título, sin nivel ni modalidad."""
    return {t for t in normalizar(titulo).split() if t and t not in _RUIDO_PUESTO}


def similitud_titulo(a: str, b: str) -> float:
    """Jaccard sobre tokens del puesto. 1.0 idéntico, 0.0 sin relación."""
    ta, tb = tokens_puesto(a), tokens_puesto(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _sugerir_fusion(conn: sqlite3.Connection, obs: Observacion, job_id: str) -> int:
    """Registra posibles duplicados **entre fuentes** para revisión humana.

    No fusiona: la regla del proyecto prohíbe unir sin identificador fuerte.
    Sólo compara avisos de editores distintos: dos puestos del mismo editor con
    títulos parecidos suelen ser vacantes distintas (junior y senior, por ejemplo).
    """
    if not obs.empresa:
        return 0
    desde = (datetime.now(timezone.utc) - timedelta(days=DIAS_VENTANA_IDENTIDAD)).isoformat()
    candidatos = conn.execute(
        """SELECT id, titulo, empresa, fuente_principal FROM jobs
           WHERE empresa IS NOT NULL AND id<>? AND merged_into IS NULL
             AND ultima_deteccion>=? AND fuente_principal<>?""",
        (job_id, desde, obs.source_id),
    ).fetchall()
    sugeridas = 0
    for fila in candidatos:
        if normalizar(fila["empresa"]) != normalizar(obs.empresa):
            continue
        similitud = similitud_titulo(fila["titulo"], obs.titulo)
        if similitud < UMBRAL_SUGERENCIA:
            continue
        cur = conn.execute(
            """INSERT OR IGNORE INTO merge_reviews
                   (job_origen, job_destino, similitud, motivo, estado, creado_en)
               VALUES (?,?,?,?, 'sugerida', ?)""",
            (job_id, fila["id"], round(similitud, 3),
             f"misma empresa y título {int(similitud * 100)} % equivalente entre "
             f"{obs.source_id} y {fila['fuente_principal']}",
             config.ahora_utc()),
        )
        sugeridas += int(bool(cur.rowcount))
    return sugeridas


def _actualizar_si_cambio(conn: sqlite3.Connection, job_id: str, obs: Observacion, content_hash: str) -> None:
    fila = conn.execute("SELECT semantic_hash FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.execute(
        """UPDATE jobs SET titulo=?, empresa=?, territorio=?, salario_json=?,
               estado_vigencia=?, publicado_en=COALESCE(publicado_en, ?), ultima_deteccion=?
           WHERE id=?""",
        (
            obs.titulo, obs.empresa, obs.region,
            json.dumps(obs.salario, ensure_ascii=False) if obs.salario else None,
            _vigencia(obs), obs.publicado_en, config.ahora_utc(), job_id,
        ),
    )
    if fila is not None and fila["semantic_hash"] != content_hash:
        conn.execute("UPDATE jobs SET semantic_hash=? WHERE id=?", (content_hash, job_id))
        conn.execute("UPDATE analyses SET obsoleto=1 WHERE job_id=?", (job_id,))
    _asegurar_version(conn, job_id)


def _asegurar_version(conn: sqlite3.Connection, job_id: str) -> int:
    job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    fila = conn.execute(
        "SELECT id FROM job_versions WHERE job_id=? AND semantic_hash=?",
        (job_id, job["semantic_hash"]),
    ).fetchone()
    if fila is not None:
        return int(fila["id"])
    cur = conn.execute(
        """INSERT INTO job_versions (job_id, semantic_hash, titulo, empresa, requisitos_json,
               salario_json, vigencia, creado_en) VALUES (?,?,?,?,?,?,?,?)""",
        (
            job_id, job["semantic_hash"], job["titulo"], job["empresa"], "{}",
            job["salario_json"], job["estado_vigencia"], config.ahora_utc(),
        ),
    )
    return int(cur.lastrowid)


def _encolar_clasificacion(conn: sqlite3.Connection, job_id: str, profile_version_id: int, stats: dict) -> None:
    job_version_id = _asegurar_version(conn, job_id)
    clave = f"clasificar:{job_id}:{job_version_id}:{profile_version_id}:{config.RULES_VERSION}"
    ahora = config.ahora_utc()
    cur = conn.execute(
        """INSERT OR IGNORE INTO tasks (kind, unique_key, job_id, job_version_id, profile_version_id,
               rules_version, estado, intentos, next_due, creado_en, actualizado_en)
           VALUES ('clasificar', ?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?)""",
        (clave, job_id, job_version_id, profile_version_id, config.RULES_VERSION, ahora, ahora, ahora),
    )
    if cur.rowcount:
        stats["encoladas"] += 1


def _vigencia(obs: Observacion) -> str:
    expira = obs.extra.get("expira_en")
    if not expira:
        return "open" if obs.publicado_en else "unknown"
    try:
        dt = datetime.fromisoformat(str(expira).replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    return "open" if dt > datetime.now(timezone.utc) else "closed"
