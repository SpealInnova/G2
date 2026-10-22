"""Arranque de g2-core:  ``python3 -m g2.nucleo [opciones]``.

Con el ADC real (en la Raspberry Pi) lee los sensores dados de alta en la base (``g2ctl
sensores-listar``); con ``--emulado`` usa tensiones simuladas, para probar en un PC. Imprime una
linea de estado cada ``--imprimir-cada`` segundos. Termina con Ctrl+C o con la señal de systemd
(SIGTERM): guarda el intervalo en curso y marca el apagado limpio.

Ejemplos::

    python3 -m g2.nucleo                                # ADC real, base por omision
    python3 -m g2.nucleo --emulado --simular 20.9,15.0  # sensor 1 en 20.9 %, sensor 2 en 15 % (alarma baja)
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

from g2 import __version__, ipc
from g2.almacenamiento.almacen import Almacen
from g2.nucleo import notificacion
from g2.nucleo.fuentes import FuenteAds1263, FuenteSimulada
from g2.nucleo.nucleo import Nucleo
from g2.nucleo.salud import MedidorLinux
from g2.nucleo.servicio_red import ServicioRed
from g2.red.gestor import GestorRed


def _ruta(args) -> Path:
    return Path(args.bd or os.environ.get("G2_BD") or Path.home() / "g2" / "datos" / "g2.db")


def _linea(estado: dict) -> str:
    sensores = " | ".join(f"S{s['id']} {s['texto_o2']:>5} % {s['estado']}"
                          + (" (acusada)" if s["acusada"] else "") for s in estado["sensores"])
    return (f"{sensores} | aviso: {estado['aviso']} | sonido {'SI' if estado['sonar'] else 'no'}"
            f" | relevos bajo={int(estado['rele_bajo'])} alto={int(estado['rele_alto'])}")


def main() -> int:
    ap = argparse.ArgumentParser(description="g2-core: lectura, alarmas y almacenamiento")
    ap.add_argument("--bd", help="ruta de la base (o G2_BD, o ~/g2/datos/g2.db)")
    ap.add_argument("--emulado", action="store_true", help="tensiones simuladas en vez del ADC")
    ap.add_argument("--simular", default="20.9,20.9",
                    help="con --emulado: % de O2 de cada sensor, separados por comas")
    ap.add_argument("--periodo", type=float, default=0.5, help="segundos entre pasos (0.5)")
    ap.add_argument("--duracion", type=float, default=0, help="segundos a correr (0 = hasta Ctrl+C)")
    ap.add_argument("--imprimir-cada", type=float, default=5.0, help="segundos entre lineas de estado")
    ap.add_argument("--run", help="carpeta para hablar con g2-ui (o G2_RUN, p. ej. /run/g2); sin ella no hay interfaz")
    args = ap.parse_args()

    ruta = _ruta(args)
    almacen = Almacen.abrir(ruta)
    sensores = [s for s in almacen.listar_sensores() if s["habilitado"]]
    if not sensores:
        print(f"No hay sensores habilitados en {ruta}. Agregue uno con: python3 -m g2.ctl sensor-agregar")
        almacen.cerrar()
        return 2

    parar = {"si": False}
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: parar.update(si=True))

    contexto = None
    if args.emulado:
        porcentajes = [float(x) for x in args.simular.split(",")]
        fuente = FuenteSimulada({s["canal"]: porcentajes[i % len(porcentajes)] * s["mv_por_pct"] / 1000.0
                                 for i, s in enumerate(sensores)})
    else:
        from g2.hardware import ads1263 as A                       # solo existe en la Pi
        from g2.hardware.puerto_spi_pi import PuertoSpiPi
        contexto = PuertoSpiPi()
        puerto = contexto.__enter__()
        adc = A.Ads1263(puerto)
        adc.iniciar()
        fuente = FuenteAds1263(adc)

    carpeta_run = Path(args.run) if args.run else ipc.carpeta_por_defecto()
    publicador = ipc.PublicadorEstado(carpeta_run) if carpeta_run else None
    servicio_red = None if args.emulado else ServicioRed(GestorRed())     # en un PC no hay nmcli
    nucleo = Nucleo(almacen, fuente, medidor=MedidorLinux(ruta.parent, ruta), servicio_red=servicio_red)
    if servicio_red is not None:
        servicio_red.iniciar()
    limpio = nucleo.iniciar()
    print(f"g2-core {__version__} en marcha. Base: {ruta}. "
          f"Cierre anterior {'ordenado' if limpio else 'NO ordenado'}. Ctrl+C para salir.")
    notificacion.listo(f"g2-core {__version__} en marcha")          # systemd: ya arranco
    try:
        import time
        fin = time.monotonic() + args.duracion if args.duracion else None
        ultima = [float("-inf")]

        def mostrar(estado: dict) -> None:
            if publicador is not None:
                publicador.publicar(estado)                           # para g2-ui
            notificacion.estado(_linea(estado))                       # lo que muestra `systemctl status`
            if time.monotonic() - ultima[0] >= args.imprimir_cada:
                ultima[0] = time.monotonic()
                print(time.strftime("%H:%M:%S"), _linea(estado), flush=True)

        nucleo.ejecutar(lambda: parar["si"] or (fin is not None and time.monotonic() >= fin),
                        periodo_s=args.periodo, al_publicar=mostrar, al_paso=notificacion.latido,
                        ordenes=publicador.recoger_ordenes if publicador is not None else None)
    finally:
        notificacion.deteniendo()
        if servicio_red is not None:
            servicio_red.detener()
        nucleo.cerrar()
        almacen.cerrar()
        if contexto is not None:
            contexto.__exit__(None, None, None)
    print("g2-core detenido (cierre ordenado).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
