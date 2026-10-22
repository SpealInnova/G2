"""Arranque de g2-ui:  ``python3 -m g2.pantalla [opciones]``.

Necesita que g2-core publique su estado en la carpeta de ``--run`` (o de ``G2_RUN``, p. ej. /run/g2) y la
pantalla conectada al puerto serie (``/dev/serial0``, 9600 baudios). Corre como servicio de systemd
(systemd/g2-ui.service) con watchdog por progreso: avisa a systemd despues de cada vuelta.
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
from g2.nucleo import notificacion
from g2.pantalla.datos import DatosPantalla, estado_red
from g2.pantalla.enlace import EnlaceSerie, detectar_baudios
from g2.pantalla.interfaz import Interfaz


def main() -> int:
    ap = argparse.ArgumentParser(description="g2-ui: interfaz de la pantalla Nextion")
    ap.add_argument("--bd", help="ruta de la base (o G2_BD, o ~/g2/datos/g2.db); se abre solo para lectura")
    ap.add_argument("--run", help="carpeta compartida con g2-core (o G2_RUN)")
    ap.add_argument("--serie", default="/dev/serial0", help="puerto serie de la pantalla")
    ap.add_argument("--baudios", default="auto",
                    help="velocidad del puerto serie, o 'auto' para probar 115200 y 9600 (por omision)")
    ap.add_argument("--periodo", type=float, default=0.05, help="segundos entre vueltas (0.05)")
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

    if args.baudios == "auto":
        baudios = detectar_baudios(args.serie)
        if baudios is None:
            baudios = 9600
            logging.warning("la pantalla no respondio a 115200 ni a 9600: se usa 9600 y se sigue intentando")
        else:
            logging.info("la pantalla responde a %d baudios", baudios)
    else:
        baudios = int(args.baudios)
    enlace = EnlaceSerie(args.serie, baudios)
    interfaz = Interfaz(enlace, ipc.ClienteNucleo(carpeta), DatosPantalla(ruta_bd), red=estado_red)
    interfaz.iniciar()
    logging.info("g2-ui %s en marcha (pantalla %s a %d baudios, estado en %s)", __version__, args.serie,
                 baudios, carpeta)
    notificacion.listo(f"g2-ui {__version__} en marcha")
    try:
        while not parar["si"]:
            interfaz.paso()
            notificacion.latido()                       # watchdog por progreso: solo si la vuelta termino
            time.sleep(args.periodo)
    finally:
        notificacion.deteniendo()
        enlace.cerrar()
    logging.info("g2-ui detenido")
    return 0


if __name__ == "__main__":
    sys.exit(main())
