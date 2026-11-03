"""Sonda de banco: lee el DHT22 y muestra temperatura, humedad y, si falla, el motivo (solo lectura).

Se ejecuta EN la Raspberry Pi:

    python3 tools/banco/sonda_dht22.py                 # GPIO4, 5 lecturas
    python3 tools/banco/sonda_dht22.py --pin 17 -n 10 --crudo

Usa el mismo lector que g2-core (``g2.hardware.dht22``), asi que si aqui funciona, alla tambien. No toca la base ni
los servicios; si g2-core ya esta leyendo el sensor, el GPIO puede estar ocupado (detenerlo un momento o probar antes
de habilitar ``ambiente.activo``). ``--crudo`` muestra la duracion de los pulsos, util para ver si la señal llega.

Cableado del modulo de 3 pines: VCC a 3,3 V (pin 1), GND (pin 6), DATA al GPIO (por omision GPIO4, pin 7).
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))

from g2.hardware import dht22  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Prueba del DHT22")
    ap.add_argument("--pin", type=int, default=dht22.PIN_POR_OMISION, help="GPIO (BCM) de DATA (4)")
    ap.add_argument("-n", type=int, default=5, help="lecturas a pedir (5)")
    ap.add_argument("--crudo", action="store_true", help="mostrar los flancos y la duracion de los pulsos")
    args = ap.parse_args()

    buenas = 0
    for i in range(args.n):
        try:
            bordes = dht22.capturar_gpiod(args.pin)
        except dht22.ErrorDht as error:
            print(f"{i + 1:>2}: {error}")
        else:
            if args.crudo:
                altos = []
                subida = None
                for es_subida, ts in bordes:
                    if es_subida:
                        subida = ts
                    elif subida is not None:
                        altos.append(round((ts - subida) / 1000.0))
                        subida = None
                print(f"    {len(bordes)} flancos; pulsos altos (us): {altos}")
            try:
                lectura = dht22.decodificar(bordes)
            except dht22.ErrorDht as error:
                print(f"{i + 1:>2}: {error}")
            else:
                buenas += 1
                print(f"{i + 1:>2}: {lectura.temperatura_c:.1f} C   {lectura.humedad_pct:.1f} %")
        if i + 1 < args.n:
            time.sleep(dht22.ESPERA_ENTRE_INTENTOS_S)
    print(f"{buenas} de {args.n} lecturas buenas.")
    return 0 if buenas else 1


if __name__ == "__main__":
    sys.exit(main())
