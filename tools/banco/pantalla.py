"""Banco de la pantalla Nextion: envia ordenes y muestra, ya decodificados, los toques que recibe.

Se ejecuta EN la Raspberry Pi con la pantalla conectada al UART principal (/dev/serial0):

    python3 tools/banco/pantalla.py "page teclado" 'valor.txt="20.5"'      # envia y escucha
    python3 tools/banco/pantalla.py --solo-escuchar                         # solo muestra toques
    python3 tools/banco/pantalla.py --baudios 115200 "page principal"

Cada orden se envia terminada en FF FF FF (formato de Nextion) y en iso-8859-1, igual que lo hace g2-ui.
Despues escucha hasta Ctrl+C (o hasta --tiempo segundos) y decodifica lo que llegue (toques, paginas
cargadas, respuestas a ``get`` y codigos de error). NO cambia nada de la Pi.

Los codigos de pagina y de control NO se repiten aqui: vienen de ``g2.pantalla.protocolo``, la misma
biblioteca que usa g2-ui. IMPORTANTE: el puerto serie es de uso exclusivo; si el servicio g2-ui esta corriendo,
hay que detenerlo antes (``sudo systemctl stop g2-ui``) y volver a iniciarlo despues.
"""

from __future__ import annotations

import argparse
import os
import select
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))      # usar el codigo del mismo repositorio
from g2.pantalla import protocolo as P                                   # noqa: E402

PUERTO = "/dev/serial0"

# Nombres que usan las pruebas y quien ya conoce esta herramienta; todos salen de la biblioteca.
FIN = P.FIN
CONTROLES = P.CONTROLES
separar = P.separar
codificar_orden = P.codificar_orden


def decodificar(trama: bytes) -> str:
    """Texto legible de UNA trama (sin los FF FF FF finales)."""
    return P.describir(P.interpretar(trama))


def abrir(baudios: int) -> int:
    import termios                                            # solo existe en Linux (la Pi)
    velocidades = {9600: termios.B9600, 19200: termios.B19200, 38400: termios.B38400,
                   57600: termios.B57600, 115200: termios.B115200}
    if baudios not in velocidades:
        raise SystemExit(f"Velocidad no admitida: {baudios} (use {sorted(velocidades)})")
    fd = os.open(PUERTO, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    atributos = termios.tcgetattr(fd)
    atributos[0] = atributos[1] = atributos[3] = 0            # sin conversiones, modo crudo
    atributos[2] = termios.CS8 | termios.CREAD | termios.CLOCAL      # 8N1
    atributos[4] = atributos[5] = velocidades[baudios]
    termios.tcsetattr(fd, termios.TCSANOW, atributos)
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("ordenes", nargs="*", help='ordenes de Nextion, p. ej. "page teclado"')
    ap.add_argument("--baudios", type=int, default=9600, help="velocidad (la de fabrica es 9600)")
    ap.add_argument("--tiempo", type=float, default=0, help="segundos a escuchar (0 = hasta Ctrl+C)")
    ap.add_argument("--solo-escuchar", action="store_true", help="no enviar nada")
    args = ap.parse_args()
    if not os.path.exists(PUERTO):
        print(f"No existe {PUERTO}: el UART no esta habilitado (scripts/aprovisionar_pi.sh).")
        return 2
    fd = abrir(args.baudios)
    try:
        if not args.solo_escuchar:
            for orden in args.ordenes:
                os.write(fd, FIN + codificar_orden(orden))     # los FF iniciales limpian el buffer
                print(f">> {orden}", flush=True)
                time.sleep(0.15)
        print("Escuchando toques (Ctrl+C para salir)...", flush=True)
        limite = time.monotonic() + args.tiempo if args.tiempo else None
        pendiente = b""
        while limite is None or time.monotonic() < limite:
            listo, _, _ = select.select([fd], [], [], 0.2)
            if listo:
                tramas, pendiente = separar(pendiente + os.read(fd, 256))
                for trama in tramas:
                    print(f"{time.strftime('%H:%M:%S')}  {decodificar(trama)}", flush=True)
    except KeyboardInterrupt:
        print()
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
