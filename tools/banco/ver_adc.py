"""Monitor en vivo de las entradas del ADS1263 (solo lectura). Se ejecuta en la Raspberry Pi.

    cd ~/g2/dev && PYTHONPATH=src python3 tools/banco/ver_adc.py

Cada segundo imprime una linea con el promedio de las lecturas de cada par de entradas
(por omision, sensor 1 = AIN0-AIN1 y sensor 2 = AIN2-AIN3). Se detiene con Ctrl+C.

Opciones utiles:
    --una-vez              imprime una sola linea y termina
    --pares 0-1            solo un par (o "0-1,2-3,0-10": cualquier lista de pares)
    --intervalo 2          segundos entre lineas (promedia las lecturas del intervalo)
    --mv-por-pct 10        escala del sensor de O2 (mV por % de O2) para el valor equivalente

Usa la configuracion definitiva del ADC (D-025: ganancia 1, PGA en derivacion, FIR 20 SPS).
El "% equivalente" solo tiene sentido conectado a un sensor de oxigeno de 10 mV/%.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time

from g2.hardware import ads1263 as A
from g2.hardware.puerto_spi_pi import PuertoSpiPi


def leer_par(adc: A.Ads1263, par: tuple[int, int], duracion_s: float) -> list[float]:
    """Lecturas (en voltios) de un par durante ``duracion_s``, al menos una."""
    limite = time.monotonic() + duracion_s
    valores = [adc.leer_diferencial(*par, tiempo_max_s=2.0).tension_v]
    while time.monotonic() < limite:
        valores.append(adc.leer_diferencial(*par, tiempo_max_s=2.0).tension_v)
    return valores


def main() -> int:
    ap = argparse.ArgumentParser(description="Monitor en vivo del ADS1263")
    ap.add_argument("--pares", default="0-1,2-3")
    ap.add_argument("--intervalo", type=float, default=1.0)
    ap.add_argument("--mv-por-pct", type=float, default=10.0)
    ap.add_argument("--una-vez", action="store_true")
    args = ap.parse_args()
    pares = [tuple(int(x) for x in p.split("-")) for p in args.pares.split(",")]
    por_par = max(args.intervalo / len(pares), 0.06)    # reparte el intervalo entre los pares

    with PuertoSpiPi() as puerto:
        adc = A.Ads1263(puerto)
        adc.iniciar()
        print(f"ADS1263 listo (ganancia 1, PGA en derivacion, FIR 20 SPS). Pares: {args.pares}. "
              "Ctrl+C para salir.")
        try:
            while True:
                partes = []
                for par in pares:
                    try:
                        v = leer_par(adc, par, por_par)
                    except A.ErrorChipReiniciado:
                        adc.iniciar()                       # se reconfigura y se sigue
                        partes.append(f"{par[0]}-{par[1]}: chip reiniciado")
                        continue
                    except A.ErrorAdc as error:
                        partes.append(f"{par[0]}-{par[1]}: ERROR {error}")
                        continue
                    mv = statistics.fmean(v) * 1000
                    ruido = (statistics.stdev(v) * 1e6) if len(v) > 1 else float("nan")
                    partes.append(f"AIN{par[0]}-{par[1]}: {mv:10.3f} mV (±{ruido:6.1f} µV, "
                                  f"≈{mv / args.mv_por_pct:7.3f} %O2, n={len(v)})")
                print(time.strftime("%H:%M:%S"), " | ".join(partes), flush=True)
                if args.una_vez:
                    return 0
        except KeyboardInterrupt:
            print("\nDetenido.")
            adc.detener()
    return 0


if __name__ == "__main__":
    sys.exit(main())
