"""Arranque de g2-uplink:  ``python3 -m g2.uplink [opciones]``.

Corre como servicio de systemd (systemd/g2-uplink.service) con watchdog por progreso: avisa a systemd despues de cada vuelta.
Sin credencial, sin ``equipo.id`` o con ``plataforma.activa`` apagada no envia nada (y lo dice en ``/run/g2/uplink.json``).
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

from g2 import __version__, ipc
from g2.almacenamiento import base
from g2.almacenamiento.almacen import Almacen
from g2.nucleo import notificacion
from g2.uplink.servicio import ServicioUplink
from g2.uplink.supervisor import SupervisorNucleo


def main() -> int:
    ap = argparse.ArgumentParser(description="g2-uplink: envio de datos a la plataforma")
    ap.add_argument("--bd", help="ruta de la base (o G2_BD, o ~/g2/datos/g2.db); se abre solo para lectura")
    ap.add_argument("--run", help="carpeta compartida con g2-core (o G2_RUN)")
    ap.add_argument("--periodo", type=float, default=1.0, help="segundos entre vueltas (1)")
    ap.add_argument("--sin-vigilar", action="store_true", help="no vigilar ni reiniciar a g2-core (pruebas a mano)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    carpeta = Path(args.run) if args.run else ipc.carpeta_por_defecto()
    if carpeta is None:
        print("Falta la carpeta de comunicacion con g2-core: use --run o la variable G2_RUN.")
        return 2
    ruta_bd = Path(args.bd or os.environ.get("G2_BD") or Path.home() / "g2" / "datos" / "g2.db")

    parar = {"si": False}
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: parar.update(si=True))

    servicio = ServicioUplink(lambda: Almacen(base.abrir_lectura(ruta_bd)), ipc.ClienteNucleo(carpeta), carpeta,
                              supervisor=None if args.sin_vigilar else SupervisorNucleo(carpeta))
    logging.info("g2-uplink %s en marcha (base %s, estado en %s)", __version__, ruta_bd, carpeta)
    notificacion.listo(f"g2-uplink {__version__} en marcha")
    try:
        while not parar["si"]:
            servicio.paso()
            notificacion.latido()                       # watchdog por progreso: solo si la vuelta termino
            time.sleep(args.periodo)
    finally:
        notificacion.deteniendo()
        servicio.cerrar()
    logging.info("g2-uplink detenido")
    return 0


if __name__ == "__main__":
    sys.exit(main())
