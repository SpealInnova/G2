"""Captura una serie de tiempo de una entrada del ADS1263 a un archivo CSV.

Se ejecuta EN la Raspberry Pi. Sirve para estudiar el ruido (espectro y desviacion de
Allan) con ``analizar_ruido.py`` y decidir con datos cuanta filtracion conviene.

    cd ~/g2/dev && PYTHONPATH=src python3 tools/banco/capturar_adc.py --segundos 90 > captura.csv

Salida (CSV por la salida estandar; los mensajes van a la salida de errores):
    # sps=100 filtro=sinc4 par=0-1
    t_s,voltios
    0.0000,1.660123
    ...

La velocidad por omision (100 SPS, filtro sinc4) deja ver frecuencias hasta ~40 Hz y se
lee sin perder muestras con el controlador actual (espera de 2 ms entre sondeos). Para
velocidades mayores habria que usar el pin DRDY o reducir la espera.
"""

from __future__ import annotations

import argparse
import sys
import time

from g2.hardware import ads1263 as A
from g2.hardware.puerto_spi_pi import PuertoSpiPi


def main() -> int:
    ap = argparse.ArgumentParser(description="Captura de una entrada del ADS1263 a CSV")
    ap.add_argument("--par", default="0-1")
    ap.add_argument("--segundos", type=float, default=60.0)
    ap.add_argument("--sps", type=float, default=100.0)
    ap.add_argument("--filtro", default="sinc4")
    args = ap.parse_args()
    positiva, negativa = (int(x) for x in args.par.split("-"))
    config = A.ConfigAdc(filtro=args.filtro, sps=args.sps)

    tiempos: list[float] = []
    valores: list[float] = []
    huecos = 0
    with PuertoSpiPi() as puerto:
        adc = A.Ads1263(puerto, config)
        adc.iniciar()
        adc.leer_diferencial(positiva, negativa)            # descarta el primer dato
        t0 = time.monotonic()
        periodo = 1.0 / args.sps
        while (ahora := time.monotonic() - t0) < args.segundos:
            lectura = adc.leer_diferencial(positiva, negativa, tiempo_max_s=2.0)
            t = time.monotonic() - t0
            if tiempos and t - tiempos[-1] > 1.6 * periodo:
                huecos += 1                                 # se perdio al menos una muestra
            tiempos.append(t)
            valores.append(lectura.tension_v)
        adc.detener()

    print(f"# sps={args.sps} filtro={args.filtro} par={args.par}")
    print("t_s,voltios")
    for t, v in zip(tiempos, valores):
        print(f"{t:.4f},{v:.7f}")
    tasa = len(valores) / (tiempos[-1] - tiempos[0]) if len(valores) > 1 else 0.0
    print(f"capturadas {len(valores)} muestras a {tasa:.1f} por segundo; huecos: {huecos}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
