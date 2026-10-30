"""Convierte una grabacion de voz (WAV de cualquier frecuencia, mono o estereo) al formato de audio de la pantalla Nextion.

Formato de salida (el mismo de pulsacion.wav y alarma.wav, que esta pantalla ya acepta): WAV sin compresion, mono, 16 bits,
16 kHz. Ademas: recorta el silencio del inicio y del final (deja 30 ms), suaviza la entrada y la salida (10 ms, evita el
«clic») y normaliza el pico a 0.85 del maximo. El volumen real lo fija la pantalla (``pantalla.volumen``); una voz con ese
pico tiene mucha menos energia que el tono de alarma, que a volumen 50 no reinicia la pantalla (D-041).

Necesita numpy y scipy (solo en el PC de desarrollo).

Uso:  python tools/convertir_sonido_voz.py "C:/Users/.../Calibrando.wav" [nombre_de_salida]
      (la salida queda en nextion/sonidos/<nombre>.wav; por omision, el nombre del archivo en minusculas)
"""

from __future__ import annotations

import sys
import wave
from math import gcd
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

CARPETA = Path(__file__).resolve().parent.parent / "nextion" / "sonidos"
MUESTREO_HZ = 16000
PICO = 0.85
UMBRAL_SILENCIO = 0.03                  # fraccion del pico por debajo de la cual es silencio
MARGEN_S = 0.030
RAMPA_S = 0.010


def leer(ruta: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(ruta), "rb") as w:
        if w.getsampwidth() != 2 or w.getcomptype() != "NONE":
            raise SystemExit("Solo se admite WAV PCM de 16 bits (exporte asi desde su grabadora o Audacity)")
        canales, frecuencia = w.getnchannels(), w.getframerate()
        datos = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768.0
    return datos.reshape(-1, canales).mean(axis=1), frecuencia


def convertir(senal: np.ndarray, frecuencia: int) -> np.ndarray:
    if frecuencia != MUESTREO_HZ:
        divisor = gcd(frecuencia, MUESTREO_HZ)
        senal = resample_poly(senal, MUESTREO_HZ // divisor, frecuencia // divisor)
    senal = senal - senal.mean()                                    # quita el desvio de continua
    activa = np.flatnonzero(np.abs(senal) > UMBRAL_SILENCIO * np.abs(senal).max())
    margen = int(MARGEN_S * MUESTREO_HZ)
    senal = senal[max(0, activa[0] - margen):activa[-1] + margen + 1]
    rampa = int(RAMPA_S * MUESTREO_HZ)
    senal[:rampa] *= np.linspace(0, 1, rampa)
    senal[-rampa:] *= np.linspace(1, 0, rampa)
    return senal * (PICO / np.abs(senal).max())


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    origen = Path(sys.argv[1])
    nombre = sys.argv[2] if len(sys.argv) > 2 else origen.stem.lower()
    senal, frecuencia = leer(origen)
    resultado = convertir(senal, frecuencia)
    CARPETA.mkdir(parents=True, exist_ok=True)
    salida = CARPETA / f"{nombre}.wav"
    with wave.open(str(salida), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(MUESTREO_HZ)
        w.writeframes((np.clip(resultado, -1, 1) * 32767).astype("<i2").tobytes())
    print(f"{origen.name} ({frecuencia} Hz, {len(senal) / frecuencia:.2f} s) -> {salida.name}: "
          f"{len(resultado) / MUESTREO_HZ:.2f} s, {salida.stat().st_size} bytes, mono, 16 bits, {MUESTREO_HZ} Hz")


if __name__ == "__main__":
    main()
