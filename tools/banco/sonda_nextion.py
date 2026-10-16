"""Sonda de banco: pregunta a la pantalla Nextion que modelo es (solo lectura).

Se ejecuta EN la Raspberry Pi, con la pantalla conectada al UART principal (/dev/serial0):

    python3 tools/banco/sonda_nextion.py

Envia el comando ``connect`` de Nextion y muestra la respuesta, que tiene la forma:

    comok <touch>,<reservado>-<..>,<modelo>,<version firmware>,<codigo MCU>,<numero de serie>,<flash en bytes>

No cambia nada de la pantalla ni de la Pi. Prueba las velocidades habituales (la de fabrica
es 9600 baudios). Usa solo la biblioteca estandar (``termios``), asi no hace falta instalar nada.

Conexion (3.3 V, ver HARDWARE.md): TXD de la Pi (GPIO14, pin 8) a RX de la pantalla; RXD de la
Pi (GPIO15, pin 10) a TX de la pantalla; GND comun. La pantalla se alimenta con 5 V de una
fuente adecuada, no de los pines GPIO.
"""

from __future__ import annotations

import os
import select
import sys
import termios
import time

PUERTO = "/dev/serial0"
VELOCIDADES = [9600, 115200, 57600, 38400, 19200, 4800, 2400]
FIN = b"\xff\xff\xff"
_BAUDIOS = {9600: termios.B9600, 115200: termios.B115200, 57600: termios.B57600,
            38400: termios.B38400, 19200: termios.B19200, 4800: termios.B4800, 2400: termios.B2400}


def preguntar(velocidad: int, espera_s: float = 1.2) -> bytes:
    """Abre el puerto a ``velocidad``, envia ``connect`` y devuelve lo que responda."""
    fd = os.open(PUERTO, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        atributos = termios.tcgetattr(fd)
        atributos[0] = 0                                    # iflag: sin conversiones
        atributos[1] = 0                                    # oflag
        atributos[2] = termios.CS8 | termios.CREAD | termios.CLOCAL      # 8N1
        atributos[3] = 0                                    # lflag: modo crudo
        atributos[4] = atributos[5] = _BAUDIOS[velocidad]
        termios.tcsetattr(fd, termios.TCSANOW, atributos)
        termios.tcflush(fd, termios.TCIOFLUSH)
        os.write(fd, FIN + b"connect" + FIN)                # los 3 FF iniciales limpian el bufer
        recibido = b""
        limite = time.monotonic() + espera_s
        while time.monotonic() < limite:
            listo, _, _ = select.select([fd], [], [], 0.1)
            if listo:
                recibido += os.read(fd, 256)
        return recibido
    finally:
        os.close(fd)


def interpretar(respuesta: bytes) -> str | None:
    """Texto de la respuesta ``comok`` si la hay."""
    texto = respuesta.replace(FIN, b"\n").decode("latin-1", errors="replace")
    for linea in texto.splitlines():
        if linea.startswith("comok"):
            return linea
    return None


def main() -> int:
    if not os.path.exists(PUERTO):
        print(f"No existe {PUERTO}: el UART no esta habilitado (scripts/aprovisionar_pi.sh).")
        return 2
    for velocidad in VELOCIDADES:
        try:
            respuesta = preguntar(velocidad)
        except OSError as error:
            print(f"No se pudo abrir {PUERTO}: {error}")
            return 2
        linea = interpretar(respuesta)
        print(f"{velocidad:>6} baudios: " + (linea if linea else
              (f"respuesta sin 'comok': {respuesta!r}" if respuesta else "sin respuesta")))
        if linea:
            partes = linea.split(",")
            if len(partes) >= 7:
                print("\nLa pantalla responde:")
                print(f"   modelo           : {partes[2]}")
                print(f"   firmware         : {partes[3]}")
                print(f"   numero de serie  : {partes[5]}")
                print(f"   memoria flash    : {int(partes[6]) / 1024 / 1024:.0f} MB")
                print(f"   velocidad (baud) : {velocidad}")
            return 0
    print("\nLa pantalla no respondio a ninguna velocidad: revise la conexion (TX y RX cruzados, "
          "GND comun, alimentacion de 5 V) o que este encendida.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
