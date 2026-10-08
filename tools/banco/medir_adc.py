"""Herramienta de banco: mide una entrada del ADS1263 y calcula promedio y ruido.

Se ejecuta EN la Raspberry Pi (por SSH), con SPI habilitado:

    cd ~/g2/dev && PYTHONPATH=src python3 tools/banco/medir_adc.py --referencia-v 1.4985

Sirve para decidir la configuracion del ADC con datos (D-025): se miden las mismas
entradas con distintas configuraciones y se comparan promedio, dispersion y diferencia
con una referencia medida con multimetro.

Ejemplos:
    # Una pila de ~1.5 V en AIN0 (+) y AIN1 (-), 200 muestras, configuracion recomendada
    python3 tools/banco/medir_adc.py --par 0-1 --muestras 200 --referencia-v 1.4985

    # Comparar todas las configuraciones predefinidas
    python3 tools/banco/medir_adc.py --comparar --muestras 100 --referencia-v 1.4985

Salidas: texto legible, o JSON con --json (util para guardar la medicion como evidencia).
No escribe en la base de datos ni cambia nada del sistema.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time

from g2.hardware import ads1263 as A
from g2.hardware.puerto_spi_pi import PuertoSpiPi

# Configuraciones predefinidas para comparar.
PRESETS = {
    "recomendada":  A.ConfigAdc(),                                           # PGA en derivacion, FIR 20 SPS
    "sinc4_20":     A.ConfigAdc(filtro="sinc4", sps=20),
    "chopper_fir":  A.ConfigAdc(chopper=True),
    "fir_10":       A.ConfigAdc(sps=10),
    "sinc4_100":    A.ConfigAdc(filtro="sinc4", sps=100),
    "pga_g1":       A.ConfigAdc(pga_derivacion=False),                       # PGA activo, ganancia 1
    "pga_g2":       A.ConfigAdc(ganancia=2, pga_derivacion=False),
    # DIAGNOSTICO (no para medir el sensor): referencia de 5 V (AVDD), rango ±5 V, para ver
    # tensiones mayores de 2.5 V. Es aproximada: depende de los 5 V reales del HAT.
    "diagnostico_5v": A.ConfigAdc(referencia="avdd"),
}

LIMITE_SEGURO_V = 2.4        # por encima, la lectura se acerca a la saturacion (±2.5 V)


def medir(puerto: PuertoSpiPi, config: A.ConfigAdc, positiva: int, negativa: int,
          muestras: int) -> dict:
    """Mide ``muestras`` lecturas con una configuracion y devuelve las estadisticas."""
    adc = A.Ads1263(puerto, config)
    adc.iniciar()
    descartar = 3                                   # deja estabilizar el filtro tras el arranque
    errores = {"tiempo_agotado": 0, "checksum": 0}
    valores: list[float] = []
    alarmas: set[str] = set()
    t0 = time.monotonic()
    for i in range(muestras + descartar):
        try:
            lectura = adc.leer_diferencial(positiva, negativa, tiempo_max_s=2.0)
        except A.ErrorTiempoAgotado:
            errores["tiempo_agotado"] += 1
            continue
        except A.ErrorChecksum:
            errores["checksum"] += 1
            continue
        if i >= descartar:
            valores.append(lectura.tension_v)
            alarmas.update(lectura.alarmas)
    duracion = time.monotonic() - t0
    adc.detener()

    resultado = {"muestras_validas": len(valores), "errores": errores,
                 "duracion_s": round(duracion, 2), "alarmas": sorted(alarmas)}
    if len(valores) >= 2:
        resultado.update(
            promedio_v=statistics.fmean(valores),
            desviacion_uv=statistics.stdev(valores) * 1e6,
            pico_a_pico_uv=(max(valores) - min(valores)) * 1e6,
            minimo_v=min(valores), maximo_v=max(valores),
            lecturas_por_s=round(len(valores) / duracion, 2),
        )
    return resultado


def describir(nombre: str, config: A.ConfigAdc, r: dict, referencia_v: float | None,
              mv_por_pct: float) -> str:
    lineas = [f"[{nombre}] ganancia={config.ganancia} pga={'derivacion' if config.pga_derivacion else 'activo'} "
              f"filtro={config.filtro} {config.sps} SPS chopper={'si' if config.chopper else 'no'} "
              f"referencia={config.referencia}"]
    if "promedio_v" not in r:
        lineas.append(f"   sin datos suficientes (errores: {r['errores']})")
        return "\n".join(lineas)
    lineas.append(f"   promedio      = {r['promedio_v'] * 1000:.4f} mV")
    lineas.append(f"   desviacion    = {r['desviacion_uv']:.2f} µV   pico a pico = {r['pico_a_pico_uv']:.1f} µV"
                  f"   (≈ {r['pico_a_pico_uv'] / 1000 / mv_por_pct:.5f} % de O2)")
    if referencia_v is not None:
        dif_mv = (r["promedio_v"] - referencia_v) * 1000
        lineas.append(f"   vs multimetro = {dif_mv:+.4f} mV   (≈ {dif_mv / mv_por_pct:+.4f} % de O2)")
    lineas.append(f"   {r['lecturas_por_s']} lecturas/s, {r['muestras_validas']} validas en {r['duracion_s']} s"
                  f", errores {r['errores']}" + (f", alarmas {r['alarmas']}" if r["alarmas"] else ""))
    if config.referencia == "avdd":
        lineas.append("   NOTA: referencia de 5 V aproximada (diagnostico); no usar para calibrar.")
    elif abs(r["promedio_v"]) > LIMITE_SEGURO_V:
        lineas.append("   AVISO: la tension esta cerca del limite de ±2.5 V; revise la conexion.")
    return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--par", default="0-1", help="entradas positiva-negativa, por ejemplo 0-1 o 2-3")
    ap.add_argument("--muestras", type=int, default=100)
    ap.add_argument("--preset", choices=sorted(PRESETS), default="recomendada")
    ap.add_argument("--comparar", action="store_true", help="mide con todas las configuraciones")
    ap.add_argument("--referencia-v", type=float, default=None,
                    help="tension medida con multimetro, en voltios")
    ap.add_argument("--mv-por-pct", type=float, default=10.0,
                    help="escala del sensor de oxigeno, mV por %% de O2 (10 para el 01117707)")
    ap.add_argument("--json", action="store_true", help="salida en JSON")
    args = ap.parse_args()

    positiva, negativa = (int(x) for x in args.par.split("-"))
    # --comparar no incluye el preset de diagnostico (no es una configuracion de medicion).
    nombres = [n for n in sorted(PRESETS) if n != "diagnostico_5v"] if args.comparar else [args.preset]
    salida = {}
    with PuertoSpiPi() as puerto:
        for nombre in nombres:
            try:
                salida[nombre] = medir(puerto, PRESETS[nombre], positiva, negativa, args.muestras)
            except A.ErrorAdc as error:
                salida[nombre] = {"error": str(error), "muestras_validas": 0, "errores": {}}
            if not args.json:
                if "error" in salida[nombre]:
                    print(f"[{nombre}] ERROR: {salida[nombre]['error']}")
                else:
                    print(describir(nombre, PRESETS[nombre], salida[nombre],
                                    args.referencia_v, args.mv_por_pct))
    if args.json:
        print(json.dumps({"par": args.par, "referencia_v": args.referencia_v,
                          "resultados": salida}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
