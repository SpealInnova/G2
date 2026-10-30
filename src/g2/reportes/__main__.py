"""Proceso del reporte:  ``python3 -m g2.reportes --desde 2026-10-27 --hasta 2026-10-27``.

Lo lanza g2-core (``g2.nucleo.servicio_reportes``) y tambien se puede usar a mano por SSH. Escribe en la salida una linea
JSON por aviso de avance (``{"fase": ..., "progreso": ..., "mensaje": ...}``) y, al final, ``listo`` con el resultado, ``error``
o ``cancelado``. Termina con 0 (listo), 1 (error) o 3 (cancelado). SIGTERM lo cancela: borra lo que haya dejado a medias.
Con ``--destino`` guarda en esa carpeta en vez de la memoria USB (pruebas).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from pathlib import Path

from g2.reportes import pdf, rango, trabajo, usb

CODIGO_ERROR, CODIGO_CANCELADO = 1, 3


def _emitir(aviso: dict) -> None:
    print(json.dumps(aviso, ensure_ascii=False), flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Genera un reporte PDF cifrado y lo copia a la memoria USB")
    ap.add_argument("--bd", help="ruta de la base (o G2_BD, o ~/g2/datos/g2.db)")
    ap.add_argument("--desde", required=True, help="primer dia (AAAA-MM-DD)")
    ap.add_argument("--hasta", required=True, help="ultimo dia (AAAA-MM-DD)")
    ap.add_argument("--destino", help="carpeta donde guardar en vez de la memoria USB (pruebas)")
    ap.add_argument("--tmp", help="carpeta de trabajo (por omision, una temporal)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")
    try:
        os.nice(15)                                         # el reporte nunca debe quitarle tiempo a la medicion
    except (OSError, AttributeError):
        pass
    parar = {"si": False}
    for senal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(senal, lambda *_: parar.update(si=True))
    ruta = Path(args.bd or os.environ.get("G2_BD") or Path.home() / "g2" / "datos" / "g2.db")
    try:
        desde, hasta = rango.leer_fecha(args.desde), rango.leer_fecha(args.hasta)
        resultado = trabajo.ejecutar(ruta, desde, hasta, emitir=_emitir, cancelado=lambda: parar["si"],
                                     carpeta_tmp=Path(args.tmp) if args.tmp else None,
                                     destino=Path(args.destino) if args.destino else None)
    except trabajo.Cancelado:
        _emitir({"fase": "cancelado", "mensaje": "Reporte cancelado"})
        return CODIGO_CANCELADO
    except (rango.ErrorRango, usb.ErrorUsb, pdf.ErrorReporte) as error:
        _emitir({"fase": "error", "mensaje": str(error)})
        return CODIGO_ERROR
    except Exception as error:                              # nada debe terminar sin avisar el motivo
        logging.getLogger("g2.reportes").exception("el reporte fallo")
        _emitir({"fase": "error", "mensaje": f"Error inesperado: {type(error).__name__}"})
        return CODIGO_ERROR
    _emitir({"fase": "resultado", "progreso": 100, "mensaje": "Reporte listo", "resultado": resultado})
    return 0


if __name__ == "__main__":
    sys.exit(main())
