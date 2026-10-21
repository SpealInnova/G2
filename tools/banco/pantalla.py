"""Banco de la pantalla Nextion: envia ordenes y muestra, ya decodificados, los toques que recibe.

Se ejecuta EN la Raspberry Pi con la pantalla conectada al UART principal (/dev/serial0):

    python3 tools/banco/pantalla.py "page teclado" 'valor.txt="20.5"'      # envia y escucha
    python3 tools/banco/pantalla.py --solo-escuchar                         # solo muestra toques
    python3 tools/banco/pantalla.py --baudios 115200 "page principal"

Cada orden se envia terminada en FF FF FF (formato de Nextion) y en iso-8859-1, igual que lo hara
g2-ui. Despues escucha hasta Ctrl+C (o hasta --tiempo segundos) y decodifica lo que llegue:

    65 PP CC 00 FF FF FF   toque, con los codigos de pagina y control de nextion/ESPECIFICACION_HMI.md
    88 FF FF FF            la pantalla acaba de encender
    70 ... / 71 ...        respuesta de texto / numero a un ``get``
    01 / 00 / 1A ...       confirmacion o error de una orden

NO cambia nada de la Pi. La tabla de nombres de abajo repite la de la especificacion del HMI y
debe mantenerse igual a ella (es una ayuda de banco: g2-ui tendra la suya).
"""

from __future__ import annotations

import argparse
import os
import select
import sys
import time

PUERTO = "/dev/serial0"
FIN = b"\xff\xff\xff"

# Codigos de pagina (PP) de la especificacion, seccion 2.
PAGINAS = {0x00: "principal", 0x01: "alarmas", 0x02: "config", 0x03: "red", 0x04: "calibracion",
           0x05: "sistema", 0x06: "teclado", 0x07: "reportes"}

# Codigos de control (CC) por pagina; FE (pagina cargada) es comun a todas.
CONTROLES = {
    0x00: {0x01: "b_alarmas", 0x02: "b_config", 0x03: "b_red", 0x04: "b_calib",
           0x05: "b_sistema", 0x06: "b_acuse"},
    0x01: {0x01: "v_bajo", 0x02: "v_alto", 0x03: "v_retardo", 0x04: "v_histeresis",
           0x05: "v_acuse", 0x06: "b_volver"},
    0x06: {**{0x10 + d: f"k_{d}" for d in range(10)}, 0x1A: "k_punto", 0x1B: "k_signo",
           0x1C: "b_borrar", 0x1D: "b_limpiar", 0x1E: "b_cancelar", 0x1F: "b_aceptar"},
}
PAGINA_CARGADA = 0xFE

CODIGOS_RESPUESTA = {0x00: "orden invalida", 0x01: "orden correcta", 0x02: "componente inexistente",
                     0x03: "pagina inexistente", 0x04: "imagen inexistente", 0x05: "fuente inexistente",
                     0x1A: "variable o atributo invalido", 0x1B: "operacion con variable invalida",
                     0x1C: "error al asignar", 0x1D: "error de EEPROM", 0x1E: "parametros invalidos",
                     0x1F: "error de E/S", 0x20: "escape invalido", 0x23: "nombre muy largo"}


def decodificar(trama: bytes) -> str:
    """Texto legible de UNA trama (sin los FF FF FF finales)."""
    if not trama:
        return "(vacia)"
    tipo = trama[0]
    if tipo == 0x65 and len(trama) == 4:                      # evento de toque
        pagina, control, pulsado = trama[1], trama[2], trama[3]
        nombre_pagina = PAGINAS.get(pagina, f"pagina?{pagina:02X}")
        if control == PAGINA_CARGADA:
            return f"pagina cargada: {nombre_pagina}"
        nombre = CONTROLES.get(pagina, {}).get(control, f"control?{control:02X}")
        estado = "" if pulsado == 0 else " (pulsado)"
        return f"toque: {nombre_pagina}.{nombre}{estado}"
    if tipo == 0x88:
        return "pantalla encendida (lista)"
    if tipo == 0x70:
        return "texto: " + trama[1:].decode("iso-8859-1", errors="replace")
    if tipo == 0x71 and len(trama) == 5:
        return "numero: " + str(int.from_bytes(trama[1:], "little", signed=True))
    if tipo in CODIGOS_RESPUESTA and len(trama) == 1:
        return "respuesta: " + CODIGOS_RESPUESTA[tipo]
    return "trama desconocida: " + trama.hex(" ").upper()


def separar(buffer: bytes) -> tuple[list[bytes], bytes]:
    """Parte el buffer en tramas completas (terminadas en FF FF FF) y devuelve lo que sobra."""
    tramas = []
    while True:
        i = buffer.find(FIN)
        if i < 0:
            return tramas, buffer
        tramas.append(buffer[:i])
        buffer = buffer[i + 3:]


def codificar_orden(orden: str) -> bytes:
    """Orden de Nextion lista para enviar: texto en iso-8859-1 y terminador FF FF FF."""
    return orden.encode("iso-8859-1") + FIN


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
                print(f">> {orden}")
                time.sleep(0.15)
        print("Escuchando toques (Ctrl+C para salir)...")
        limite = time.monotonic() + args.tiempo if args.tiempo else None
        pendiente = b""
        while limite is None or time.monotonic() < limite:
            listo, _, _ = select.select([fd], [], [], 0.2)
            if listo:
                tramas, pendiente = separar(pendiente + os.read(fd, 256))
                for trama in tramas:
                    print(f"{time.strftime('%H:%M:%S')}  {decodificar(trama)}")
    except KeyboardInterrupt:
        print()
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
