"""Prueba de IA sobre **una sola oferta real**, con cuota gratuita confirmada.

Este script está pensado para validar el circuito completo (credencial → cascada
→ cuota → respuesta estructurada → evidencia verificada) gastando lo mínimo
posible: una oferta, un modelo, un tope duro de una llamada.

Antes de tocar la red comprueba, y aborta si algo no se cumple:

- el proveedor no exige pago (`requiere_pago is False`);
- el modelo está declarado dentro de la cuota gratuita y con precio 0;
- el presupuesto mensual es 0 y el pago no está autorizado;
- hay credencial resuelta (se informa origen y huella, nunca el valor);
- la ventana de cuota del proveedor admite una petición más.

La habilitación de la IA y la autorización para enviar texto de ofertas suelen
estar apagadas: el script las enciende **sólo durante la corrida** y las devuelve
a su valor original al terminar, incluso si falla.

Uso:
    python tools/prueba_ia_oferta.py                  # elige la mejor oferta dudosa
    python tools/prueba_ia_oferta.py --job-id job_xx
    python tools/prueba_ia_oferta.py --listar         # sólo muestra candidatas
    python tools/prueba_ia_oferta.py --sin-encender   # no toca los ajustes
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from buscador import db  # noqa: E402
from buscador.ai import analisis as analisis_mod  # noqa: E402
from buscador.ai import cuotas  # noqa: E402
from buscador.ai import cuotas  # noqa: E402
from buscador.ai.cliente import (Cliente, Politica, Rechazo, SinCuota, consumo,  # noqa: E402
                                 presupuesto)
from buscador.ai.proveedores import parsear  # noqa: E402

MIN_TEXTO = 400


def _candidatas(conn: sqlite3.Connection, limite: int = 12) -> list[dict]:
    """Ofertas reales analizadas por el motor de reglas, con texto suficiente."""
    filas = conn.execute(
        """
        SELECT j.id, j.titulo, j.empresa, j.territorio, a.elegibilidad, a.score,
               (SELECT LENGTH(o.descripcion_texto) FROM observations o
                  JOIN job_observations jo ON jo.observation_id = o.id
                 WHERE jo.job_id = j.id
                 ORDER BY LENGTH(o.descripcion_texto) DESC LIMIT 1) AS largo
          FROM jobs j
          JOIN analyses a ON a.job_id = j.id AND a.obsoleto = 0
         WHERE a.elegibilidad IN ('eligible', 'doubtful')
        """
    ).fetchall()
    lista = [
        dict(f) for f in filas
        if (f["largo"] or 0) >= MIN_TEXTO
    ]
    # Primero las dudosas (donde la IA aporta algo), con más texto y mejor score.
    lista.sort(key=lambda o: (o["elegibilidad"] != "doubtful", -(o["largo"] or 0)))
    return lista[:limite]


def _elegir(conn: sqlite3.Connection, job_id: str | None) -> dict | None:
    if job_id:
        fila = conn.execute(
            "SELECT j.id, j.titulo, j.empresa, j.territorio FROM jobs j WHERE j.id = ?",
            (job_id,),
        ).fetchone()
        return dict(fila) if fila else None
    candidatas = _candidatas(conn)
    return candidatas[0] if candidatas else None


def _precondiciones(conn: sqlite3.Connection, referencia: str) -> tuple[bool, list[str], dict]:
    """Comprueba que la corrida es gratis y posible. No consume nada."""
    problemas: list[str] = []
    datos: dict = {}

    par = parsear(referencia)
    if par is None:
        return False, [f"referencia de modelo inválida: {referencia}"], {}
    proveedor, modelo = par

    datos["proveedor"] = proveedor.clave
    datos["modelo"] = modelo.id
    datos["requiere_pago"] = proveedor.requiere_pago
    datos["dentro_cuota_gratuita"] = modelo.dentro_cuota_gratuita
    datos["usd_entrada_1m"] = modelo.usd_entrada_1m
    datos["usd_salida_1m"] = modelo.usd_salida_1m

    if proveedor.requiere_pago:
        problemas.append(f"{proveedor.clave} exige pago")
    if not modelo.dentro_cuota_gratuita:
        problemas.append(f"{modelo.id} no está dentro de la cuota gratuita")
    if modelo.usd_entrada_1m or modelo.usd_salida_1m:
        problemas.append(f"{modelo.id} tiene precio por token distinto de 0")

    tope = Politica.desde_ajustes(conn).presupuesto_mensual_usd
    caja = presupuesto(conn, tope)
    datos["presupuesto_usd"] = caja["limite_usd"]
    datos["gastado_usd"] = caja["gastado_usd"]
    if caja["limite_usd"] > 0:
        problemas.append(f"hay presupuesto asignado (USD {caja['limite_usd']})")
    if caja["gastado_usd"] > 0:
        problemas.append(f"ya hay gasto registrado (USD {caja['gastado_usd']})")
    if db.ajuste(conn, "ia_autorizo_pago", "0") == "1":
        problemas.append("el pago está autorizado; esta prueba debe correr sin gasto")

    cred = Cliente(conn)._credencial(proveedor)
    datos["credencial_origen"] = cred.get("origen")
    datos["credencial_huella"] = cred.get("huella")
    datos["credencial_longitud"] = cred.get("longitud")
    if not cred.get("valor"):
        problemas.append("no hay credencial para el proveedor")

    hay, motivo = cuotas.verificar(conn, proveedor, modelo, tokens_estimados=6000)
    datos["cuota"] = motivo
    if not hay:
        problemas.append(f"sin cuota disponible: {motivo}")

    return not problemas, problemas, datos


def _encender(conn: sqlite3.Connection) -> dict[str, str]:
    """Enciende IA y autorización de datos por la duración de la corrida."""
    originales = {
        "ia_habilitada": db.ajuste(conn, "ia_habilitada", "0"),
        "ia_datos_ofertas": db.ajuste(conn, "ia_datos_ofertas", "0"),
    }
    db.guardar_ajuste(conn, "ia_habilitada", "1")
    db.guardar_ajuste(conn, "ia_datos_ofertas", "1")
    return originales


def _restaurar(conn: sqlite3.Connection, originales: dict[str, str]) -> None:
    for clave, valor in originales.items():
        db.guardar_ajuste(conn, clave, valor)


def _ultima_llamada(conn: sqlite3.Connection) -> dict | None:
    fila = conn.execute(
        "SELECT proveedor, modelo, proposito, estado, tokens_entrada, tokens_salida,"
        " costo_usd, cuota_consumida, huella_credencial, duracion_ms, error, creado_en"
        " FROM ai_calls ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(fila) if fila else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", default=None, help="oferta concreta a analizar")
    parser.add_argument("--modelo", default=None,
                        help="referencia proveedor:modelo (por defecto, la primera de la cascada)")
    parser.add_argument("--listar", action="store_true", help="muestra candidatas y sale")
    parser.add_argument("--sin-encender", action="store_true",
                        help="no modifica ia_habilitada ni ia_datos_ofertas")
    args = parser.parse_args(argv)

    conn = db.conectar()
    try:
        if args.listar:
            print("Ofertas reales con texto suficiente (dudosas primero):")
            for oferta in _candidatas(conn):
                print(f"  {oferta['id']}  {oferta['elegibilidad']:9} "
                      f"{oferta['largo']:>6} car.  {oferta['titulo'][:52]}")
            return 0

        cascada = Politica.desde_ajustes(conn).cascada
        referencia = args.modelo or (cascada[0] if cascada else "gemini:gemini-3.5-flash-lite")

        oferta = _elegir(conn, args.job_id)
        if oferta is None:
            print("No hay ofertas analizadas con texto suficiente. Corré el recolector primero.")
            return 1

        print("=" * 78)
        print("Prueba de IA · una sola oferta · cuota gratuita")
        print("=" * 78)
        print(f"Oferta   : {oferta['titulo'][:60]}")
        print(f"Empresa  : {oferta.get('empresa') or '—'}")
        print(f"Región   : {oferta.get('territorio') or '—'}")
        print(f"id       : {oferta['id']}")
        if oferta.get("elegibilidad"):
            print(f"Reglas   : {oferta['elegibilidad']} · score {oferta.get('score')}")
        print(f"Modelo   : {referencia}")
        print("-" * 78)

        ok, problemas, datos = _precondiciones(conn, referencia)
        print("Precondiciones de costo cero:")
        print(f"  requiere_pago ............. {datos.get('requiere_pago')}")
        print(f"  dentro_cuota_gratuita ..... {datos.get('dentro_cuota_gratuita')}")
        print(f"  precio por 1M tokens ...... entrada {datos.get('usd_entrada_1m')}"
              f" / salida {datos.get('usd_salida_1m')}")
        print(f"  presupuesto / gastado ..... USD {datos.get('presupuesto_usd')}"
              f" / USD {datos.get('gastado_usd')}")
        print(f"  credencial ................ {datos.get('credencial_origen')}"
              f" · huella {datos.get('credencial_huella')}"
              f" · {datos.get('credencial_longitud')} car.")
        print(f"  cuota ..................... {datos.get('cuota')}")
        if problemas:
            print("\nABORTADO: la corrida no cumple las condiciones de costo cero.")
            for problema in problemas:
                print(f"  - {problema}")
            return 2
        print("  resultado ................. APTA (no puede generar gasto)")
        print("-" * 78)

        originales: dict[str, str] = {}
        try:
            if not args.sin_encender:
                originales = _encender(conn)
            politica = Politica.desde_ajustes(conn)
            # Tope duro: una sola llamada, sin importar la configuración guardada.
            politica.llamadas_por_corrida = 1
            cliente = Cliente(conn, politica)

            resultado = analisis_mod.analizar_uno(cliente, conn, oferta["id"])
        except Rechazo as exc:
            print(f"Rechazado por la política: {exc.motivo} ({exc.codigo})")
            return 3
        except SinCuota as exc:
            print("Sin cuota disponible:")
            for fallo in exc.detalle:
                print(f"  - {fallo.get('referencia')}: {fallo.get('motivo')}")
            return 4
        except ValueError as exc:
            print(f"La oferta no se puede analizar: {exc}")
            return 5
        finally:
            if originales:
                _restaurar(conn, originales)

        llamada = _ultima_llamada(conn)
        print("Resultado del análisis:")
        print(f"  proveedor / modelo ....... {resultado['proveedor']} / {resultado['modelo']}")
        print(f"  complejidad .............. {resultado['complejidad']}")
        print(f"  caché .................... {resultado['cache']}")
        print(f"  confianza ................ {resultado['confianza']}")
        print(f"  evidencias válidas ....... {resultado['evidencias_validas']}")
        print(f"  evidencias no verificadas  {resultado['evidencias_invalidas']}")
        print(f"  costo .................... USD {resultado['costo_usd']}")

        if llamada:
            print("\nRegistro de la llamada (ai_calls):")
            print(f"  estado ................... {llamada['estado']}")
            print(f"  tokens entrada / salida .. {llamada['tokens_entrada']} / {llamada['tokens_salida']}")
            print(f"  cuota consumida .......... {llamada['cuota_consumida']}")
            print(f"  huella de la credencial .. {llamada['huella_credencial']}")
            print(f"  duración ................. {llamada['duracion_ms']} ms")
            if llamada["error"]:
                print(f"  error .................... {llamada['error'][:200]}")

        guardado = analisis_mod.ultimo(conn, oferta["id"])
        if guardado:
            print("\nSegunda opinión guardada (ai_analyses):")
            print(f"  categoría ................ {guardado['categoria']}")
            print(f"  seniority ................ {guardado['seniority']}")
            print(f"  modalidad ................ {guardado['modalidad']}")
            print(f"  elegibilidad territorial . {guardado['elegibilidad_territorial']}")
            print(f"  años de experiencia ...... {guardado['anios_experiencia']}")
            print(f"  habilidades obligatorias . {', '.join(guardado['habilidades_obligatorias']) or '—'}")
            print(f"  explicación .............. {(guardado['explicacion'] or '')[:400]}")
            if guardado["incertidumbres"]:
                print(f"  incertidumbres ........... {'; '.join(guardado['incertidumbres'])[:300]}")

        print("\nConsumo acumulado tras la prueba:")
        resumen = consumo(conn)
        hoy = resumen["hoy"]
        print(f"  generaciones correctas ... {hoy['solicitudes_exitosas']}")
        print(f"  intentos fallidos ........ {hoy['intentos_fallidos']}")
        print(f"  tokens entrada / salida .. {hoy['tokens_entrada']} / {hoy['tokens_salida']}")
        print(f"  cuota consumida .......... {hoy['cuota_consumida']}")
        print(f"  gasto .................... USD {hoy['costo_usd']}")
        print(f"  presupuesto del mes ...... USD {resumen['presupuesto']['limite_usd']}"
              f" (gastado USD {resumen['presupuesto']['gastado_usd']})")
        print("\nJSON:")
        print(json.dumps({"oferta": oferta["id"], "resultado": resultado,
                          "llamada": llamada, "consumo": hoy}, ensure_ascii=False, indent=2))
        return 0 if resultado.get("costo_usd", 0) == 0 else 6
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
