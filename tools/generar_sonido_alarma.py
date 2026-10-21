"""Genera el sonido de alarma de la pantalla Nextion (nextion/sonidos/alarma.wav).

Es distinto del pitido de los botones (tools/generar_sonido_pulsacion.py): un tono doble alterno
(880 Hz y 660 Hz, dos veces, unos 0.7 s en total) que se distingue bien de un toque y no es un
chirrido continuo. La pantalla lo reproduce UNA vez; es la Raspberry Pi quien lo repite cada pocos
segundos mientras haya una alarma sin acusar (D-032), asi, si la Pi falla, el sonido se detiene solo.

WAV sin compresion, mono, 16 bits, 16 kHz. Solo biblioteca estandar.

Uso:  python tools/generar_sonido_alarma.py
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

SALIDA = Path(__file__).resolve().parent.parent / "nextion" / "sonidos" / "alarma.wav"
MUESTREO_HZ = 16000
AMPLITUD = 0.8                      # fraccion del maximo; el volumen real lo fija la pantalla
RAMPA_S = 0.010                     # entrada y salida suaves de cada tono (evita el "clic")
# (frecuencia en Hz, duracion en s); una frecuencia 0 es un silencio
PATRON = [(880, 0.16), (660, 0.16), (0, 0.04), (880, 0.16), (660, 0.16)]


def _tono(frecuencia: float, duracion: float) -> bytes:
    total = int(duracion * MUESTREO_HZ)
    rampa = max(1, int(RAMPA_S * MUESTREO_HZ))
    datos = bytearray()
    for n in range(total):
        if frecuencia == 0:
            valor = 0.0
        else:
            envolvente = min(1.0, n / rampa, (total - 1 - n) / rampa)
            valor = AMPLITUD * envolvente * math.sin(2 * math.pi * frecuencia * n / MUESTREO_HZ)
        datos += struct.pack("<h", int(valor * 32767))
    return bytes(datos)


def main() -> None:
    muestras = b"".join(_tono(f, d) for f, d in PATRON)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(SALIDA), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(MUESTREO_HZ)
        w.writeframes(muestras)
    print(f"{SALIDA.name}: {len(muestras) // 2 / MUESTREO_HZ:.2f} s, {SALIDA.stat().st_size} bytes")


if __name__ == "__main__":
    main()
