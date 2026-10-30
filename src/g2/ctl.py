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


def cmd_pin_fijar(args) -> int:
    """Aprovisiona un PIN (D-038). El PIN NUNCA va como argumento (quedaria en el historial del shell y en la
    lista de procesos): se pide por teclado sin mostrarlo, o con ``--desde-stdin`` se lee de la entrada."""
    import getpass
    if args.desde_stdin:
        pin = sys.stdin.readline().strip()
    else:
        pin = getpass.getpass("PIN nuevo (4 a 8 digitos): ")
        if getpass.getpass("Repita el PIN: ") != pin:
            print("Los PIN no coinciden: no se cambio nada.", file=sys.stderr)
            return 2
    almacen = _almacen_escritura(_ruta(args))
    try:
        almacen.pin_fijar(args.tipo, pin, origen="local", actor=args.actor)
    except Exception as error:                                   # formato invalido, p. ej.
        print(f"No se cambio el PIN: {error}", file=sys.stderr)
        return 2
    print(f"PIN de {args.tipo} guardado (solo su huella; el valor no se registra en ninguna parte).")
    almacen.cerrar()
    return 0


def cmd_pin_estado(args) -> int:
    almacen = _almacen_lectura(_ruta(args))
    tipos = almacen.pin_tipos()
    activo = almacen.pin_activo()
    print(f"PIN de fabrica: {'si' if 'fabrica' in tipos else 'no'}   PIN de la plataforma: "
          f"{'si' if 'plataforma' in tipos else 'no'}   rige: {activo['tipo'] if activo else 'NINGUNO (la pantalla no permite cambios)'}")
    almacen.cerrar()
    return 0


def cmd_plataforma_credencial(args) -> int:
    """Guarda el secreto del equipo ante la plataforma (D-046). Como el PIN, NUNCA va como argumento: se pide sin
    mostrarlo, o con ``--desde-stdin`` se lee de la entrada. Queda en un archivo 0600 fuera de la base."""
    import getpass
    from g2.uplink import credencial
    if args.desde_stdin:
        secreto = sys.stdin.readline().strip()
    else:
        secreto = getpass.getpass("Secreto del equipo (el que entrega la plataforma): ")
        if getpass.getpass("Repita el secreto: ") != secreto:
            print("No coinciden: no se cambio nada.", file=sys.stderr)
            return 2
    try:
        ruta = credencial.guardar(secreto)
    except credencial.ErrorCredencial as error:
        print(f"No se guardo el secreto: {error}", file=sys.stderr)
        return 2
    print(f"Secreto guardado en {ruta} (solo lo lee el usuario del servicio; no se registra en la base ni se muestra).")
    return 0


def cmd_plataforma_estado(args) -> int:
    """Como esta el enlace con la plataforma: configuracion, credencial, cola y lo que dice g2-uplink."""
    from g2 import ipc
    from g2.uplink import credencial
    almacen = _almacen_lectura(_ruta(args))
    cfg = {c: almacen.config_obtener(c) for c in ("plataforma.activa", "plataforma.url", "equipo.id",
                                                  "plataforma.intervalo_envio_s", "plataforma.lote_max",
                                                  "plataforma.intervalo_visualizacion_s")}
    cola = {f["estado"]: f["n"] for f in almacen.db.execute("SELECT estado, COUNT(*) AS n FROM cola_envio GROUP BY estado")}
    almacen.cerrar()
    print(f"Activa: {'si' if cfg['plataforma.activa'] == '1' else 'NO'}   URL: {cfg['plataforma.url']}   "
          f"equipo.id: {cfg['equipo.id'] or '(falta)'}")
    print(f"Secreto guardado: {'si' if credencial.existe() else 'NO'}   Lote: {cfg['plataforma.lote_max']} cada "
          f"{cfg['plataforma.intervalo_envio_s']} s   En vivo cada {cfg['plataforma.intervalo_visualizacion_s']} s")
    print("Cola: " + (", ".join(f"{n} {e}" for e, n in sorted(cola.items())) or "vacia"))
    carpeta = ipc.carpeta_por_defecto() or Path("/run/g2")
    try:
        vivo = json.loads((carpeta / "uplink.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("g2-uplink: no publica estado (servicio detenido o sin carpeta de comunicacion)")
        return 0
    print(f"g2-uplink: {vivo.get('estado')}" + (f" - {vivo['detalle']}" if vivo.get("detalle") else "")
          + f"   confirmados en esta sesion: {vivo.get('confirmados')}   rechazados: {vivo.get('rechazados')}")
    nucleo = vivo.get("nucleo")
    if nucleo:
        print(f"g2-core: {'sin respuesta hace %.0f s' % nucleo['sin_respuesta_s'] if nucleo['sin_respuesta_s'] else 'responde'}"
              f"   reinicios pedidos en la ultima hora: {nucleo['reinicios_ultima_hora']}"
              + ("   (limite alcanzado: ya no se insiste)" if nucleo["agotado"] else "")
              + (f"   error: {nucleo['error']}" if nucleo.get("error") else ""))
    return 0


def cmd_cola_descartar(args) -> int:
    """Deja de enviar lo pendiente (registros de prueba). No borra: pasa a 'rechazado' y se queda en el equipo."""
    ruta = _ruta(args)
    pendientes = {f["tabla"]: f["n"] for f in _almacen_lectura(ruta).db.execute(
        "SELECT tabla, COUNT(*) AS n FROM cola_envio WHERE estado IN ('pendiente', 'enviado') GROUP BY tabla ORDER BY tabla")}
    if not pendientes:
        print("No hay nada pendiente de envio.")
        return 0
    print("Pendientes de envio: " + ", ".join(f"{t} {n}" for t, n in pendientes.items()) + f"  (total {sum(pendientes.values())})")
    if not args.confirmar:
        print("No se cambio nada. Para dejar de enviarlos (siguen guardados en el equipo): agregue --confirmar")
        return 0
    almacen = _almacen_escritura(ruta)
    try:
        hecho = almacen.cola_descartar(motivo=args.motivo, actor=args.actor)
    except ErrorAlmacen as error:
        print(f"Error: {error}")
        return 1
    finally:
        almacen.cerrar()
    print(f"Descartados {sum(hecho.values())} registro(s) pendientes ({args.motivo}). Siguen guardados en el equipo; no se enviaran.")
    return 0


def _pedir_al_nucleo(tipo: str, **datos) -> int:
    """Deja una orden para g2-core en la carpeta compartida (el nucleo es el unico que escribe en la base)."""
    from g2 import ipc
    carpeta = ipc.carpeta_por_defecto() or Path("/run/g2")
    if not carpeta.is_dir():
        print(f"No existe {carpeta}: g2-core no esta en marcha.")
        return 1
    identificador = ipc.ClienteNucleo(carpeta).enviar_orden(tipo, origen="local", actor="g2ctl", **datos)
    print(f"Orden {tipo} enviada a g2-core ({identificador}). El resultado queda en el comando, los eventos CAL_* y la tabla calibracion.")
    return 0


def cmd_calibrar_punto(args) -> int:
    """Calibra UN punto de un sensor con gas patron (D-049): el sensor debe tener ese gas ahora. Menos de 50 % es el punto bajo
    (corrige el cero); 50 % o mas es el punto alto (corrige la ganancia)."""
    return _pedir_al_nucleo("calibrar_punto", sensor_id=args.sensor, referencia_pct=args.referencia)


def cmd_calibrar_cancelar(args) -> int:
    return _pedir_al_nucleo("calibrar_cancelar")


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

    p = sub.add_parser("pin-fijar", help="guarda un PIN de la pantalla (se pide sin mostrarlo)")
    p.add_argument("--tipo", choices=("fabrica", "plataforma"), default="fabrica")
    p.add_argument("--actor", default="g2ctl")
    p.add_argument("--desde-stdin", action="store_true", help="lee el PIN de la entrada estandar (aprovisionamiento por SSH)")
    p.set_defaults(f=cmd_pin_fijar)
    sub.add_parser("pin-estado", help="que PIN rige (nunca muestra el valor)").set_defaults(f=cmd_pin_estado)

    p = sub.add_parser("plataforma-credencial", help="guarda el secreto del equipo ante la plataforma (se pide sin mostrarlo)")
    p.add_argument("--desde-stdin", action="store_true", help="lee el secreto de la entrada estandar")
    p.set_defaults(f=cmd_plataforma_credencial)
    sub.add_parser("plataforma-estado", help="estado del enlace con la plataforma y de la cola de envio").set_defaults(
        f=cmd_plataforma_estado)
    p = sub.add_parser("calibrar-punto", help="calibra un punto de un sensor con gas patron (0 = bajo, 98 = alto, 20.9 = aire)")
    p.add_argument("sensor", type=int, help="id del sensor (ver sensores-listar)")
    p.add_argument("referencia", type=float, help="concentracion del gas patron en %% de O2 (0 a 100)")
    p.set_defaults(f=cmd_calibrar_punto)
    sub.add_parser("calibrar-cancelar", help="cancela la calibracion en curso").set_defaults(f=cmd_calibrar_cancelar)
    p = sub.add_parser("cola-descartar", help="deja de enviar lo pendiente, p. ej. registros de prueba (no borra nada)")
    p.add_argument("--motivo", required=True, help="por que se descarta (queda en el evento y en cada entrada)")
    p.add_argument("--actor", default="g2ctl")
    p.add_argument("--confirmar", action="store_true", help="sin esto solo muestra lo que descartaria")
    p.set_defaults(f=cmd_cola_descartar)

    args = ap.parse_args(argv)
    return args.f(args)


if __name__ == "__main__":
    sys.exit(main())
