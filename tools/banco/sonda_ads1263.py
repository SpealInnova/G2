"""Sonda de banco: comprueba que el ADS1263 del HAT responde por SPI (solo lectura).

Se ejecuta EN la Raspberry Pi (no en el PC):

    python3 tools/banco/sonda_ads1263.py

Que hace: reinicia el chip con el pin RESET, lee tres registros por SPI y los compara
con sus valores de fabrica (hoja de datos de TI, ADS126x, mapa de registros). No
configura el convertidor ni lee tensiones; eso lo hara el controlador definitivo.

Pines (BCM) del HAT Waveshare, segun su documentacion: CS = 22 (por software),
DRDY = 17, RESET = 18; SPI0 para MOSI, MISO y SCLK. Requiere SPI habilitado
(scripts/aprovisionar_pi.sh) y las bibliotecas ``spidev`` y ``lgpio``.

Codigo de salida: 0 si detecta el ADS1263, 1 si no.
"""

from __future__ import annotations

import sys
import time

import lgpio
import spidev

CS, DRDY, RESET = 22, 17, 18
CMD_RREG = 0x20            # lectura de registros: 0x20 | direccion
REG_ID, REG_POWER, REG_INTERFACE = 0x00, 0x01, 0x02

# Valores de fabrica tras un reinicio.
POWER_FABRICA = 0x11       # referencia interna activa, sin VBIAS
INTERFACE_FABRICA = 0x05   # byte de estado y CRC activos
ID_ADS1263 = 1             # bits 7..5 del registro ID


def leer_registro(spi: spidev.SpiDev, gpio: int, direccion: int) -> int:
    """Lee un registro. CS se maneja por software (GPIO 22), no con el CE0 del SPI."""
    lgpio.gpio_write(gpio, CS, 0)
    spi.writebytes([CMD_RREG | direccion, 0x00])   # RREG, un registro
    valor = spi.readbytes(1)[0]
    lgpio.gpio_write(gpio, CS, 1)
    return valor


def main() -> int:
    gpio = lgpio.gpiochip_open(0)
    spi = spidev.SpiDev()
    try:
        lgpio.gpio_claim_output(gpio, CS, 1)       # CS en alto = inactivo
        lgpio.gpio_claim_output(gpio, RESET, 1)
        lgpio.gpio_claim_input(gpio, DRDY)

        for nivel in (1, 0, 1):                     # reinicio del chip
            lgpio.gpio_write(gpio, RESET, nivel)
            time.sleep(0.2)

        spi.open(0, 0)
        spi.max_speed_hz = 2_000_000
        spi.mode = 0b01                             # modo 1, MSB primero

        ident = leer_registro(spi, gpio, REG_ID)
        power = leer_registro(spi, gpio, REG_POWER)
        interfaz = leer_registro(spi, gpio, REG_INTERFACE)
        print(f"ID        = 0x{ident:02X}  (dispositivo = {ident >> 5}; ADS1263 da {ID_ADS1263})")
        print(f"POWER     = 0x{power:02X}  (fabrica: 0x{POWER_FABRICA:02X})")
        print(f"INTERFACE = 0x{interfaz:02X}  (fabrica: 0x{INTERFACE_FABRICA:02X})")
        print("DRDY (GPIO17) =", lgpio.gpio_read(gpio, DRDY))

        ok = (ident >> 5 == ID_ADS1263) and power == POWER_FABRICA and interfaz == INTERFACE_FABRICA
        print("RESULTADO:", "ADS1263 DETECTADO" if ok else "sin respuesta valida del ADS1263")
        return 0 if ok else 1
    finally:
        spi.close()
        lgpio.gpiochip_close(gpio)


if __name__ == "__main__":
    sys.exit(main())
