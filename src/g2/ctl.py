"""g2ctl: herramienta de linea de comandos para operar G2 por SSH (D-024).

    PYTHONPATH=src python3 -m g2.ctl <comando> [opciones]

Comandos de esta primera version (la base de datos y la configuracion):
    bd-crear            crea la base (o la actualiza) y siembra la configuracion por defecto
    bd-estado           version del esquema, filas por tabla, tamano y cola de envio
    bd-verificar        verifica la cadena de auditoria (sale con codigo 1 si hay problemas)
    config-listar       muestra todas las claves con su valor, defecto, origen y version
    config-fijar C V    cambia una clave (valida, deja historial)
    sensores-listar     muestra los sensores dados de alta
    sensor-agregar      da de alta un sensor de oxigeno
    sensor-serie ID S   anota la serie de la etiqueta de un sensor

Ruta de la base: ``--bd``, o la variable de entorno ``G2_BD``, o ``~/g2/datos/g2.db``.

Nota (D-009): el unico que debe escribir es ``g2-core``. Estos comandos de escritura son de
provisionamiento y de pruebas; cuando exista g2-core, los cambios iran por su socket local.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import g2
from g2.almacenamiento import auditoria, base
from g2.almacenamiento.almacen import Almacen, ErrorAlmacen
from g2.configuracion.catalogo import ErrorConfig


def _ruta(args) -> Path:
    return Path(args.bd or os.environ.get("G2_BD") or Path.home() / "g2" / "datos" / "g2.db")


def _almacen_lectura(ruta: Path) -> Almacen:
    if not ruta.exists():
        raise SystemExit(f"No existe la base {ruta}. Cree una con: bd-crear")
    return Almacen(base.abrir_lectura(ruta))


def _almacen_escritura(ruta: Path) -> Almacen:
    almacen = Almacen.abrir(ruta)
    try:
        almacen.usar_ultimo_arranque()
    except ErrorAlmacen:
        almacen.registrar_arranque(version_sw=f"g2ctl {g2.__version__}", razon="SYS_ARRANQUE")
    return almacen


def _mostrar_estado(estado: dict) -> None:
    print(f"Esquema: version {estado['version_esquema']}   Tamano: {estado['bytes'] / 1024:.0f} KiB")
    arranque = estado["ultimo_arranque"]
    if arranque:
        print(f"Ultimo arranque: {arranque['boot_id']} ({arranque['razon']}, {arranque['version_sw']})")
    print(f"Alarmas abiertas: {estado['alarmas_abiertas']}   "
          f"Pendientes de confirmar con la plataforma: {estado['pendientes_envio']}")
    print("Filas por tabla:")
    for tabla, filas in estado["filas"].items():
        print(f"   {tabla:22s} {filas:>9d}")


def cmd_bd_crear(args) -> int:
    ruta = _ruta(args)
    existia = ruta.exists()
    almacen = Almacen.abrir(ruta)
    print(f"Base {'actualizada' if existia else 'creada'}: {ruta}")
    _mostrar_estado(almacen.estado())
    almacen.cerrar()
    return 0


def cmd_bd_estado(args) -> int:
    almacen = _almacen_lectura(_ruta(args))
    estado = almacen.estado()
    if args.json:
        print(json.dumps(estado, indent=2, ensure_ascii=False))
    else:
        _mostrar_estado(estado)
    return 0


def cmd_bd_verificar(args) -> int:
    conexion = base.abrir_lectura(_ruta(args))
    problemas = auditoria.verificar(conexion)
    if not problemas:
        print("Cadena de auditoria: OK (sin diferencias)")
        return 0
    print(f"Cadena de auditoria: {len(problemas)} problema(s)")
    for p in problemas:
        print(f"   [{p.tipo}] tabla={p.tabla} registro={p.registro_id} eslabon={p.seq}: {p.detalle}")
    return 1


def cmd_config_listar(args) -> int:
    almacen = _almacen_lectura(_ruta(args))
    filas = almacen.config_listar()
    if args.json:
        print(json.dumps(filas, indent=2, ensure_ascii=False))
        return 0
    print(f"{'clave':38s} {'valor':>10s} {'defecto':>10s} {'origen':>11s} {'ver':>4s}")
    for f in filas:
        marca = " " if f["valor"] == f["defecto"] else "*"
        print(f"{f['clave']:38s} {f['valor']:>10s} {str(f['defecto']):>10s} "
              f"{f['origen']:>11s} {f['version']:>4d}{marca}")
    print("(* = distinto del valor por defecto)")
    return 0


def cmd_config_fijar(args) -> int:
    almacen = _almacen_escritura(_ruta(args))
    try:
        r = almacen.config_fijar(args.clave, args.valor, origen="local", actor=args.actor)
    except ErrorConfig as error:
        print(f"No se cambio: {error}", file=sys.stderr)
        return 2
    print(f"{r.clave} = {r.valor}  (version {r.version}, {'cambiado' if r.cambiado else 'sin cambio'})")
    almacen.cerrar()
    return 0


def cmd_sensores_listar(args) -> int:
    almacen = _almacen_lectura(_ruta(args))
    sensores = almacen.listar_sensores()
    if not sensores:
        print("No hay sensores dados de alta. Use: sensor-agregar")
    for s in sensores:
        print(f"[{s['id']}] {s['nombre']:12s} canal={s['canal']:16s} {s['modelo']} "
              f"serie={s['serie_etiqueta'] or '-'} {s['mv_por_pct']} mV/% "
              f"{'habilitado' if s['habilitado'] else 'DESHABILITADO'}")
    return 0


def cmd_sensor_agregar(args) -> int:
    almacen = _almacen_escritura(_ruta(args))
    try:
        sensor_id = almacen.registrar_sensor(
            canal=args.canal, nombre=args.nombre, modelo=args.modelo, mv_por_pct=args.mv_por_pct,
            variante=args.variante, serie_etiqueta=args.serie)
    except Exception as error:                                   # p. ej. canal repetido
        print(f"No se agrego el sensor: {error}", file=sys.stderr)
        return 2
    print(f"Sensor {sensor_id} agregado: {args.nombre} ({args.canal})")
    almacen.cerrar()
    return 0


def cmd_sensor_serie(args) -> int:
    almacen = _almacen_escritura(_ruta(args))
    try:
        almacen.fijar_serie_sensor(args.id, args.serie)
    except ErrorAlmacen as error:
        print(f"No se cambio: {error}", file=sys.stderr)
        return 2
    print(f"Sensor {args.id}: serie {args.serie}")
    almacen.cerrar()
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="g2ctl", description=__doc__.split("\n")[0])
    ap.add_argument("--bd", help="ruta de la base de datos")
    sub = ap.add_subparsers(dest="comando", required=True)

    sub.add_parser("bd-crear").set_defaults(f=cmd_bd_crear)
    p = sub.add_parser("bd-estado"); p.add_argument("--json", action="store_true"); p.set_defaults(f=cmd_bd_estado)
    sub.add_parser("bd-verificar").set_defaults(f=cmd_bd_verificar)
    p = sub.add_parser("config-listar"); p.add_argument("--json", action="store_true"); p.set_defaults(f=cmd_config_listar)
    p = sub.add_parser("config-fijar")
    p.add_argument("clave"); p.add_argument("valor"); p.add_argument("--actor", default="g2ctl")
    p.set_defaults(f=cmd_config_fijar)
    sub.add_parser("sensores-listar").set_defaults(f=cmd_sensores_listar)
    p = sub.add_parser("sensor-agregar")
    p.add_argument("--canal", required=True, help="por ejemplo ads1263:0-1")
    p.add_argument("--nombre", required=True)
    p.add_argument("--modelo", required=True)
    p.add_argument("--mv-por-pct", type=float, default=10.0)
    p.add_argument("--variante"); p.add_argument("--serie")
    p.set_defaults(f=cmd_sensor_agregar)

    p = sub.add_parser("sensor-serie")
    p.add_argument("id", type=int); p.add_argument("serie")
    p.set_defaults(f=cmd_sensor_serie)

    args = ap.parse_args(argv)
    return args.f(args)


if __name__ == "__main__":
    sys.exit(main())
