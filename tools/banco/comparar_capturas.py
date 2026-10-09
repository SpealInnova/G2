"""Compara varias capturas del ADC lado a lado (pruebas A/B del ruido). Se ejecuta en el PC.

    python tools/banco/comparar_capturas.py reposo=a.csv carga=b.csv piso=c.csv

Cada argumento es ``nombre=archivo.csv`` (archivos de ``capturar_adc.py``). Imprime una
tabla con el promedio, la desviacion, el pico a pico, el ruido por banda de frecuencia
(en µV rms) y la desviacion de Allan a 1 s y 10 s.

Como leerla (prueba A/B): si al cambiar UNA condicion (la fuente, la carga de la Pi, un
filtro) cambia el ruido, esa condicion lo causa. El "piso" (entradas a tierra) es el ruido
que pone el propio ADC; ninguna fuente puede medirse con menos ruido que ese.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy import signal

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analizar_ruido import allan_overlapping, cargar          # noqa: E402

_integrar = getattr(np, "trapezoid", None) or np.trapz
BANDAS = [(0.0, 0.1), (0.1, 1.0), (1.0, 10.0), (10.0, 50.0)]


def resumen(ruta: str) -> dict:
    t, v, _ = cargar(ruta)
    fs = (len(t) - 1) / (t[-1] - t[0])
    x = v - np.mean(v)
    nperseg = min(len(x), int(2 ** np.floor(np.log2(len(x) / 4))))
    f, psd = signal.welch(x, fs=fs, nperseg=nperseg, detrend="constant")
    bandas = []
    for a, b in BANDAS:
        sel = (f >= a) & (f < min(b, fs / 2))
        bandas.append(float(np.sqrt(_integrar(psd[sel], f[sel]))) * 1e6 if sel.sum() > 1 else 0.0)
    # El tiempo real de promediado es (muestras / fs), que casi nunca es exactamente 1.0 o
    # 10.0; por eso se pide cada tau por separado y se toma el unico resultado.
    allan = {}
    for tau in (1.0, 10.0):
        r = allan_overlapping(x, fs, [tau])
        allan[tau] = r[0][1] if r else float("nan")
    return {"n": len(v), "fs": fs, "media": float(np.mean(v)), "std": float(np.std(v)) * 1e6,
            "pp": float(v.max() - v.min()) * 1e6, "bandas": bandas,
            "allan1": allan.get(1.0, float("nan")) * 1e6, "allan10": allan.get(10.0, float("nan")) * 1e6,
            "deriva": float(np.mean(v[-len(v) // 10:]) - np.mean(v[:len(v) // 10])) * 1e6}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    pares = [a.split("=", 1) for a in sys.argv[1:] if "=" in a]
    if not pares:
        print(__doc__)
        return 1
    datos = {nombre: resumen(ruta) for nombre, ruta in pares}
    nombres = list(datos)
    ancho = 13

    def fila(titulo: str, formato) -> None:
        print(f"{titulo:34s}" + "".join(f"{formato(datos[n]):>{ancho}s}" for n in nombres))

    print(" " * 34 + "".join(f"{n:>{ancho}s}" for n in nombres))
    fila("muestras", lambda d: f"{d['n']}")
    fila("promedio (V)", lambda d: f"{d['media']:.6f}")
    fila("desviacion (µV)", lambda d: f"{d['std']:.1f}")
    fila("pico a pico (µV)", lambda d: f"{d['pp']:.0f}")
    fila("deriva fin–inicio (µV)", lambda d: f"{d['deriva']:+.0f}")
    for i, (a, b) in enumerate(BANDAS):
        fila(f"ruido {a:g}–{b:g} Hz (µV rms)", lambda d, i=i: f"{d['bandas'][i]:.1f}")
    fila("Allan τ=1 s (µV)", lambda d: f"{d['allan1']:.1f}")
    fila("Allan τ=10 s (µV)", lambda d: f"{d['allan10']:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
