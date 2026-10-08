"""Puerto SPI real para el HAT Waveshare con ADS1263 en la Raspberry Pi.

Implementa la interfaz ``PuertoSpi`` de ``ads1263.py`` con ``spidev`` (bus SPI0) y
``lgpio`` (pines de control). Solo funciona en la Raspberry Pi con SPI habilitado
(scripts/aprovisionar_pi.sh). Las bibliotecas se importan al abrir el puerto, para que el
resto de G2 se pueda importar y probar en cualquier PC.

Pines (BCM) segun la documentacion de Waveshare (HARDWARE.md §3):
    CS = 22 (por software, no el CE0 del SPI), DRDY = 17, RESET = 18.
SPI: modo 1 (CPOL=0, CPHA=1), MSB primero, hasta 8 MHz; se usan 2 MHz.
"""

from __future__ import annotations

import time

CS, DRDY, RESET = 22, 17, 18


class PuertoSpiPi:
    """Acceso fisico al ADS1263 del HAT. Usar como gestor de contexto::

        with PuertoSpiPi() as puerto:
            adc = Ads1263(puerto)
    """

    def __init__(self, cs: int = CS, drdy: int = DRDY, reset: int = RESET,
                 bus: int = 0, dispositivo: int = 0, velocidad_hz: int = 2_000_000) -> None:
        self._cs, self._drdy, self._reset = cs, drdy, reset
        self._bus, self._dispositivo, self._velocidad = bus, dispositivo, velocidad_hz
        self._gpio = None
        self._spi = None
        self._lgpio = None

    def abrir(self) -> None:
        """Abre el bus SPI y reclama los pines de control.

        Raises:
            ImportError: si faltan ``spidev`` o ``lgpio`` (no es una Raspberry Pi).
            OSError: si SPI no esta habilitado o los pines estan ocupados.
        """
        import lgpio
        import spidev
        self._lgpio = lgpio
        self._gpio = lgpio.gpiochip_open(0)
        lgpio.gpio_claim_output(self._gpio, self._cs, 1)       # CS en alto = inactivo
        lgpio.gpio_claim_output(self._gpio, self._reset, 1)
        lgpio.gpio_claim_input(self._gpio, self._drdy)
        self._spi = spidev.SpiDev()
        self._spi.open(self._bus, self._dispositivo)
        self._spi.max_speed_hz = self._velocidad
        self._spi.mode = 0b01

    def cerrar(self) -> None:
        if self._spi is not None:
            self._spi.close()
            self._spi = None
        if self._gpio is not None:
            self._lgpio.gpiochip_close(self._gpio)
            self._gpio = None

    def __enter__(self) -> "PuertoSpiPi":
        self.abrir()
        return self

    def __exit__(self, *_exc) -> None:
        self.cerrar()

    def transferir(self, datos: bytes) -> bytes:
        """Una transaccion completa con CS bajo. CS vuelve a alto aunque falle el SPI."""
        self._lgpio.gpio_write(self._gpio, self._cs, 0)
        try:
            return bytes(self._spi.xfer2(list(datos)))
        finally:
            self._lgpio.gpio_write(self._gpio, self._cs, 1)

    def reiniciar(self) -> None:
        """Reinicio por hardware con el pin RESET (secuencia del fabricante del HAT)."""
        for nivel in (1, 0, 1):
            self._lgpio.gpio_write(self._gpio, self._reset, nivel)
            time.sleep(0.2)

    def drdy(self) -> int:
        """Nivel del pin DRDY (0 = hay un dato nuevo). Util para diagnostico."""
        return self._lgpio.gpio_read(self._gpio, self._drdy)
