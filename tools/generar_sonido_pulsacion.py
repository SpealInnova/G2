"""Genera el pitido corto de pulsacion de botones de la Nextion (nextion/sonidos/pulsacion.wav).

La pantalla NX8048P050 tiene altavoz pero no zumbador, asi que el "pito" es un archivo de audio
que la pantalla reproduce con ``play`` al tocar un boton (ver nextion/ESPECIFICACION_HMI.md).
Es un tono puro de 2 kHz y 70 ms con entrada y salida suaves (evita el "clic" al empezar y
terminar). WAV sin compresion, mono, 16 bits, 16 kHz. Se usa solo la biblioteca estandar.

Uso:  python tools/generar_sonido_pulsacion.py
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

SALIDA = Path(__file__).resolve().parent.parent / "nextion" / "sonidos" / "pulsacion.wav"
FRECUENCIA_HZ = 2000
DURACION_S = 0.070
MUESTREO_HZ = 16000
AMPLITUD = 0.6                 # fraccion del maximo; el volumen real se ajusta en la pantalla
RAMPA_S = 0.008                # entrada y salida suaves


def main() -> None:
    total = int(DURACION_S * MUESTREO_HZ)
    rampa = int(RAMPA_S * MUESTREO_HZ)
    muestras = bytearray()
    for n in range(total):
        envolvente = min(1.0, n / rampa, (total - 1 - n) / rampa)
        valor = AMPLITUD * envolvente * math.sin(2 * math.pi * FRECUENCIA_HZ * n / MUESTREO_HZ)
        muestras += struct.pack("<h", int(valor * 32767))
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(SALIDA), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(MUESTREO_HZ)
        w.writeframes(bytes(muestras))
    print(f"{SALIDA.name}: {total} muestras, {DURACION_S * 1000:.0f} ms, {SALIDA.stat().st_size} bytes")


if __name__ == "__main__":
    main()
