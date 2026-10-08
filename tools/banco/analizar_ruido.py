"""Analiza el ruido de una captura del ADC y propone una frecuencia de corte del filtro.

Se ejecuta en el PC (necesita numpy y scipy):

    python tools/banco/analizar_ruido.py captura.csv --respuesta-s 11 --mv-por-pct 10

Que calcula:
  1. Estadistica basica y velocidad de muestreo real.
  2. Densidad espectral de potencia (metodo de Welch): en que frecuencias esta el ruido.
  3. Desviacion de Allan: cuanto baja el ruido al promediar durante mas tiempo y a partir
     de que tiempo deja de bajar (deriva).
  4. Para varias frecuencias de corte de un filtro pasabajos de primer orden, el ruido que
     quedaria (integrando el espectro), su equivalente en % de O2, el retardo que anade y
     los valores de R y C para realizarlo en analogico (con R = 1 kOhm).

Como elegir la frecuencia de corte (criterio):
  * La señal util es lenta: el sensor tarda ``respuesta_s`` en llegar al 90 % ante un cambio
    de gas (11 s en el manual). El ancho de banda de esa respuesta es ~0.35 / respuesta_s.
  * Se elige un corte varias veces por encima de ese ancho de banda (para no deformar la
    respuesta) y lo mas bajo posible (para quitar ruido). El programa sugiere el corte que
    deja el retardo del filtro por debajo de ``--retardo-max-s``.

Limitacion: describe el ruido de lo que estuviera conectado al tomar la captura.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
from scipy import signal

# numpy 2 renombro trapz a trapezoid.
_integrar = getattr(np, "trapezoid", None) or np.trapz


def cargar(ruta: str) -> tuple[np.ndarray, np.ndarray, str]:
    cabecera = ""
    with open(ruta, encoding="utf-8") as f:
        primera = f.readline()
        if primera.startswith("#"):
            cabecera = primera.strip()
    datos = np.loadtxt(ruta, delimiter=",", skiprows=2 if cabecera else 1)
    return datos[:, 0], datos[:, 1], cabecera


def allan_overlapping(x: np.ndarray, fs: float, taus_s: list[float]) -> list[tuple[float, float]]:
    """Desviacion de Allan solapada para varios tiempos de promediado."""
    resultado = []
    for tau in taus_s:
        m = int(round(tau * fs))
        if m < 1 or 2 * m >= len(x):
            continue
        medias = np.convolve(x, np.ones(m) / m, mode="valid")        # medias moviles
        diferencias = medias[m:] - medias[:-m]
        resultado.append((m / fs, float(np.sqrt(0.5 * np.mean(diferencias ** 2)))))
    return resultado


def main() -> int:
    # La consola de Windows usa una codificacion que no tiene "≈"; se fuerza UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Analisis de ruido de una captura del ADC")
    ap.add_argument("captura")
    ap.add_argument("--respuesta-s", type=float, default=11.0,
                    help="tiempo de respuesta del sensor al 90 %% (manual: 11 s)")
    ap.add_argument("--mv-por-pct", type=float, default=10.0)
    ap.add_argument("--retardo-max-s", type=float, default=1.0,
                    help="retardo maximo aceptable del filtro (constante de tiempo)")
    ap.add_argument("--r-ohm", type=float, default=1000.0, help="R para el filtro analogico")
    ap.add_argument("--grafica", help="guarda una grafica PNG en esta ruta")
    args = ap.parse_args()

    t, v, cabecera = cargar(args.captura)
    fs = (len(t) - 1) / (t[-1] - t[0])
    x = v - np.mean(v)
    pct = lambda voltios: voltios * 1000.0 / args.mv_por_pct          # V -> % de O2

    print(f"Captura: {len(v)} muestras, {t[-1] - t[0]:.1f} s, {fs:.1f} muestras/s  {cabecera}")
    print(f"Promedio {np.mean(v):.6f} V | desviacion {np.std(v) * 1e6:.1f} µV | "
          f"pico a pico {(v.max() - v.min()) * 1e6:.1f} µV "
          f"(≈ {pct(v.max() - v.min()):.4f} % de O2)\n")

    # --- Espectro (Welch) ---------------------------------------------------------------
    nperseg = min(len(x), int(2 ** np.floor(np.log2(len(x) / 4))))
    f, psd = signal.welch(x, fs=fs, nperseg=nperseg, detrend="constant")     # V^2/Hz
    print(f"Espectro (resolucion {f[1]:.3f} Hz). Ruido por banda (rms):")
    bandas = [(0.0, 0.1), (0.1, 0.5), (0.5, 2), (2, 10), (10, fs / 2)]
    for a, b in bandas:
        sel = (f >= a) & (f < b)
        if sel.sum() < 1:
            continue
        rms = np.sqrt(_integrar(psd[sel], f[sel])) if sel.sum() > 1 else 0.0
        print(f"   {a:6.2f} – {b:6.2f} Hz : {rms * 1e6:9.1f} µV rms  (≈ {pct(rms):.4f} % de O2)")
    picos, _ = signal.find_peaks(psd, prominence=np.max(psd) * 0.02)
    mayores = sorted(picos, key=lambda i: -psd[i])[:5]
    if mayores:
        print("   Picos principales (Hz): " + ", ".join(f"{f[i]:.2f}" for i in sorted(mayores)))
    print()

    # --- Allan ----------------------------------------------------------------------------
    taus = [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 40]
    print("Desviacion de Allan (ruido al promediar durante τ):")
    for tau, sigma in allan_overlapping(x, fs, taus):
        print(f"   τ = {tau:6.2f} s : {sigma * 1e6:9.2f} µV  (≈ {pct(sigma):.5f} % de O2)")
    print()

    # --- Frecuencia de corte ----------------------------------------------------------------
    f_senal = 0.35 / args.respuesta_s
    print(f"Ancho de banda de la señal util ≈ 0.35 / {args.respuesta_s:g} s = {f_senal:.3f} Hz")
    print("Filtro pasabajos de primer orden (ruido restante integrando el espectro):")
    print(f"   corte Hz | constante τ s | ruido rms µV | % de O2 | C para R={args.r_ohm:.0f} Ω")
    elegido = None
    for fc in (0.03, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20):
        if fc >= fs / 2:
            continue
        h2 = 1.0 / (1.0 + (f / fc) ** 2)
        rms = float(np.sqrt(_integrar(psd * h2, f)))
        tau = 1.0 / (2 * np.pi * fc)
        c = 1.0 / (2 * np.pi * args.r_ohm * fc)
        marca = ""
        if fc >= 3 * f_senal and tau <= args.retardo_max_s and elegido is None:
            elegido, marca = fc, "  <- sugerido"
        print(f"   {fc:8.2f} | {tau:13.2f} | {rms * 1e6:12.1f} | {pct(rms):7.4f} | "
              f"{c * 1e6:10.2f} µF{marca}")
    if elegido:
        print(f"\nSugerencia: corte ≈ {elegido:g} Hz (≥ 3× el ancho de banda de la señal, retardo "
              f"≤ {args.retardo_max_s:g} s). Mejor hacerlo en digital (promedio o filtro de primer "
              "orden en g2-core): sin componentes, sin deriva y ajustable.")
    else:
        print("\nNingun corte cumple los criterios; revise --retardo-max-s o la captura.")

    if args.grafica:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ejes = plt.subplots(1, 3, figsize=(15, 4))
        ejes[0].plot(t, (v - np.mean(v)) * 1e6, lw=0.5)
        ejes[0].set(title="Serie (sin promedio)", xlabel="s", ylabel="µV")
        ejes[1].loglog(f[1:], np.sqrt(psd[1:]) * 1e6)
        ejes[1].axvline(f_senal, color="r", ls="--", label="ancho de banda de la señal")
        ejes[1].set(title="Densidad espectral", xlabel="Hz", ylabel="µV/√Hz")
        ejes[1].legend()
        a = allan_overlapping(x, fs, taus)
        ejes[2].loglog([p[0] for p in a], [p[1] * 1e6 for p in a], "o-")
        ejes[2].set(title="Desviacion de Allan", xlabel="τ (s)", ylabel="µV")
        for e in ejes:
            e.grid(True, which="both", alpha=0.3)
        fig.tight_layout()
        fig.savefig(args.grafica, dpi=110)
        print(f"Grafica guardada en {args.grafica}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
