"""Respaldos consistentes, verificación, restauración y exportación (T08)."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config, db


def _marca() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def crear(conn: sqlite3.Connection, rutas: config.Rutas | None = None,
          etiqueta: str = "") -> dict:
    """Copia consistente con `VACUUM INTO` (no requiere detener la aplicación)."""
    rutas = rutas or config.rutas()
    rutas.backups.mkdir(parents=True, exist_ok=True)
    sufijo = f"-{etiqueta}" if etiqueta else ""
    destino = rutas.backups / f"buscador-{_marca()}{sufijo}.db"
    if destino.exists():  # dos respaldos en el mismo segundo
        destino = rutas.backups / f"buscador-{_marca()}-{etiqueta or 'auto'}-2.db"
    conn.execute("VACUUM INTO ?", (str(destino),))
    digest = _sha256(destino)
    ok, detalle = db.integridad(destino)
    with db.transaccion(conn):
        conn.execute(
            "INSERT INTO backup_log (archivo, bytes, sha256, verificado, creado_en) VALUES (?,?,?,?,?)",
            (destino.name, destino.stat().st_size, digest, 1 if ok else 0, config.ahora_utc()),
        )
    return {
        "archivo": str(destino),
        "bytes": destino.stat().st_size,
        "sha256": digest,
        "integridad": detalle,
        "verificado": ok,
    }


def listar(rutas: config.Rutas | None = None) -> list[dict]:
    rutas = rutas or config.rutas()
    if not rutas.backups.exists():
        return []
    archivos = sorted(rutas.backups.glob("buscador-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "archivo": p.name,
            "ruta": str(p),
            "bytes": p.stat().st_size,
            "modificado": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }
        for p in archivos
    ]


def verificar(archivo: Path) -> dict:
    archivo = Path(archivo)
    ok, detalle = db.integridad(archivo)
    datos = {"archivo": archivo.name, "integridad": detalle, "ok": ok}
    if ok:
        conn = sqlite3.connect(f"file:{archivo.as_posix()}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            for tabla in ("jobs", "observations", "analyses", "notifications"):
                try:
                    datos[tabla] = conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
                except sqlite3.Error:
                    datos[tabla] = None
            datos["user_version"] = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
    return datos


def restaurar(archivo: Path, rutas: config.Rutas | None = None,
              conservar_actual: bool = True) -> dict:
    """Restaura un respaldo. Antes respalda el estado actual para poder volver."""
    rutas = rutas or config.rutas()
    archivo = Path(archivo)
    if not archivo.exists():
        raise FileNotFoundError(f"no existe el respaldo: {archivo}")
    ok, detalle = db.integridad(archivo)
    if not ok:
        raise ValueError(f"el respaldo no pasa la verificación de integridad: {detalle}")

    previo = None
    if rutas.db.exists() and conservar_actual:
        conn = db.conectar(rutas.db)
        try:
            previo = crear(conn, rutas, etiqueta="previo-restauracion")
        finally:
            conn.close()

    try:
        for sufijo in ("-wal", "-shm"):
            Path(str(rutas.db) + sufijo).unlink(missing_ok=True)
        shutil.copy2(archivo, rutas.db)
    except PermissionError as exc:
        raise ValueError(
            "no se pudo reemplazar la base porque está en uso: cerrá la aplicación "
            f"(o el proceso que la tenga abierta) y volvé a intentar ({exc})"
        ) from exc
    db.inicializar(rutas.db)
    return {"restaurado": archivo.name, "respaldo_previo": (previo or {}).get("archivo")}


def limpiar(rutas: config.Rutas | None = None, conservar: int | None = None) -> list[str]:
    """Elimina los respaldos más antiguos por encima de la retención."""
    rutas = rutas or config.rutas()
    conservar = conservar or config.RESPALDOS_A_CONSERVAR
    archivos = sorted(rutas.backups.glob("buscador-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    borrados: list[str] = []
    for archivo in archivos[conservar:]:
        archivo.unlink(missing_ok=True)
        borrados.append(archivo.name)
    return borrados


def exportar_csv(conn: sqlite3.Connection, rutas: config.Rutas | None = None,
                 solo_guardadas: bool = False) -> dict:
    """Exporta el listado con su análisis vigente y el estado del usuario."""
    rutas = rutas or config.rutas()
    rutas.exports.mkdir(parents=True, exist_ok=True)
    archivo = rutas.exports / f"ofertas-{_marca()}.csv"
    filtro = ""
    if solo_guardadas:
        filtro = """AND j.id IN (SELECT e.job_id FROM user_events e
                     WHERE e.id = (SELECT MAX(id) FROM user_events WHERE job_id=e.job_id)
                     AND e.accion IN ('guardar','interesar'))"""
    filas = conn.execute(
        f"""SELECT j.id, j.titulo, j.empresa, j.categoria, j.modalidad, j.territorio,
                   j.estado_vigencia, j.publicado_en, j.salario_json, j.url_atribucion,
                   j.fuente_principal, a.elegibilidad, a.score,
                   (SELECT accion FROM user_events u WHERE u.job_id=j.id ORDER BY u.id DESC LIMIT 1) AS estado_usuario
            FROM jobs j LEFT JOIN analyses a ON a.job_id=j.id AND a.obsoleto=0
            WHERE 1=1 {filtro}
            ORDER BY a.score DESC NULLS LAST, j.publicado_en DESC"""
    ).fetchall()
    columnas = ["id", "titulo", "empresa", "categoria", "modalidad", "territorio",
                "estado_vigencia", "publicado_en", "salario", "url", "fuente",
                "elegibilidad", "score", "estado_usuario"]
    with archivo.open("w", encoding="utf-8-sig", newline="") as manejador:
        escritor = csv.writer(manejador, delimiter=";")
        escritor.writerow(columnas)
        for fila in filas:
            salario = ""
            if fila["salario_json"]:
                try:
                    datos = json.loads(fila["salario_json"])
                    salario = " ".join(
                        str(datos.get(k)) for k in ("min", "max", "moneda", "periodo") if datos.get(k)
                    )
                except json.JSONDecodeError:
                    salario = ""
            escritor.writerow([
                _celda(fila["id"]), _celda(fila["titulo"]), _celda(fila["empresa"]),
                _celda(fila["categoria"]), _celda(fila["modalidad"]), _celda(fila["territorio"]),
                _celda(fila["estado_vigencia"]), _celda(fila["publicado_en"]), salario,
                _celda(fila["url_atribucion"]), _celda(fila["fuente_principal"]),
                _celda(fila["elegibilidad"]), fila["score"] or "",
                _celda(fila["estado_usuario"]),
            ])
    return {"archivo": str(archivo), "filas": len(filas)}


def _celda(valor) -> str:
    """Neutraliza una celda que la planilla interpretaría como fórmula (CSV injection)."""
    texto = "" if valor is None else str(valor)
    if texto[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + texto
    return texto


def _sha256(archivo: Path) -> str:
    digest = hashlib.sha256()
    with archivo.open("rb") as manejador:
        for bloque in iter(lambda: manejador.read(1024 * 256), b""):
            digest.update(bloque)
    return digest.hexdigest()
