"""Emulador del ADS1263 para probar el controlador sin hardware (D-024).

Imita lo que el controlador necesita del chip, segun la hoja de datos (SBAS661C):
registros con sus valores de fabrica, los comandos RESET, START1, STOP1, RDATA1, RREG y
WREG, el byte de estado, la suma de control y el reinicio de la conversion cuando se
escriben ciertos registros. El tiempo es simulado: un ``RelojFalso`` que avanza cuando el
controlador "espera", de modo que las pruebas son rapidas y exactas.

Simplificaciones (no modela): ADC2, IDAC, GPIO del chip, calibraciones, alarmas del PGA,
ni el desfase del filtro digital; en modo chopper solo duplica el periodo de conversion.

Inyeccion de fallas para las pruebas: ``congelado`` (no llegan datos nuevos),
``corromper_suma`` (la suma de control sale mal) y ``simular_reinicio()``.
"""

from __future__ import annotations

import math
import random
from typing import Callable

from g2.hardware import ads1263 as A

# Fuente de señal: tension diferencial (V) entre dos entradas en un instante (s).
Fuente = Callable[[int, int, float], float]


class RelojFalso:
    """Reloj simulado: ``esperar`` avanza el tiempo en vez de dormir."""

    def __init__(self, t0: float = 1000.0) -> None:
        self.t = t0

    def ahora(self) -> float:
        return self.t

    def esperar(self, segundos: float) -> None:
        self.t += segundos


class Ads1263Emulado:
    """Puerto SPI simulado que se comporta como un ADS1263."""

    def __init__(self, reloj: RelojFalso, fuente: Fuente | None = None, *,
                 ruido_uv: float = 0.0, semilla: int = 1234, id_chip: int = 0x23) -> None:
        self.reloj = reloj
        self.fuente: Fuente = fuente or (lambda p, n, t: 0.0)
        self.ruido_uv = ruido_uv
        self._azar = random.Random(semilla)
        self.id_chip = id_chip
        self.congelado = False
        self.corromper_suma = False
        self.regs: dict[int, int] = {}
        self.corriendo = False
        self._t0 = reloj.ahora()
        self._indice_generado = 0
        self._codigo = 0
        self._nuevo = False
        self._reiniciar_registros()

    # -- estado del chip ----------------------------------------------------------------
    def _reiniciar_registros(self) -> None:
        self.regs = {A.REG_ID: self.id_chip, A.REG_POWER: 0x11, A.REG_INTERFACE: 0x05,
                     A.REG_MODE0: 0x00, A.REG_MODE1: 0x80, A.REG_MODE2: 0x04,
                     A.REG_INPMUX: 0x01, A.REG_REFMUX: 0x00}
        self.corriendo = False
        self._nuevo = False
        self._indice_generado = 0

    def _reiniciar_conversion(self) -> None:
        self._t0 = self.reloj.ahora()
        self._indice_generado = 0
        self._nuevo = False

    def reiniciar(self) -> None:
        """Reinicio por hardware (pin RESET)."""
        self._reiniciar_registros()

    def simular_reinicio(self) -> None:
        """Simula un reinicio inesperado del chip (por ejemplo, un bache de energia)."""
        self._reiniciar_registros()

    # -- modelo de conversion ---------------------------------------------------------------
    def _periodo_s(self) -> float:
        sps = {v: k for k, v in A.VELOCIDADES_SPS.items()}[self.regs[A.REG_MODE2] & 0x0F]
        chopper = (self.regs[A.REG_MODE0] >> 4) & 0b11 in (0b01, 0b11)
        return (2 if chopper else 1) / sps

    def _canal(self) -> tuple[int, int]:
        mux = self.regs[A.REG_INPMUX]
        return mux >> 4, mux & 0x0F

    def _vref(self) -> float:
        return A.VREF_AVDD_NOMINAL if self.regs[A.REG_REFMUX] == A.REFMUX_AVDD else A.VREF_INTERNA

    def _ganancia(self) -> int:
        return {v: k for k, v in A.GANANCIAS.items()}[(self.regs[A.REG_MODE2] >> 4) & 0b111]

    def _actualizar_conversion(self) -> None:
        if not self.corriendo or self.congelado:
            return
        periodo = self._periodo_s()
        completadas = math.floor((self.reloj.ahora() - self._t0) / periodo)
        if completadas > self._indice_generado:
            p, n = self._canal()
            t_conv = self._t0 + completadas * periodo
            volt = self.fuente(p, n, t_conv) + self._azar.gauss(0.0, self.ruido_uv * 1e-6)
            gan = self._ganancia()
            codigo = round(volt * gan * 2 ** 31 / self._vref())
            self._codigo = max(-2 ** 31, min(2 ** 31 - 1, codigo))      # satura en el rango
            self._indice_generado = completadas
            self._nuevo = True

    # -- interfaz SPI ------------------------------------------------------------------------
    def transferir(self, datos: bytes) -> bytes:
        cmd = datos[0]
        rx = bytearray(len(datos))
        if cmd in (A.CMD_RESET, A.CMD_RESET | 1):
            self._reiniciar_registros()
        elif cmd in (A.CMD_START1, A.CMD_START1 | 1):
            self.corriendo = True
            self._reiniciar_conversion()
        elif cmd in (A.CMD_STOP1, A.CMD_STOP1 | 1):
            self.corriendo = False
        elif cmd in (A.CMD_RDATA1, A.CMD_RDATA1 | 1):
            self._actualizar_conversion()
            status = (A.STATUS_ADC1_NUEVO if self._nuevo else 0) \
                | (A.STATUS_REINICIO if self.regs[A.REG_POWER] & A.POWER_RESET else 0)
            dato = (self._codigo & 0xFFFFFFFF).to_bytes(4, "big")
            suma = A.checksum(dato) ^ (0xFF if self.corromper_suma else 0)
            salida = bytes([0, status]) + dato + bytes([suma])
            rx[:len(salida)] = salida[:len(rx)]
            self._nuevo = False
        elif 0x20 <= cmd <= 0x3F:                                   # RREG
            reg, cuantos = cmd & 0x1F, datos[1] + 1
            for i in range(cuantos):
                if 2 + i < len(rx):
                    rx[2 + i] = self.regs.get(reg + i, 0)
        elif 0x40 <= cmd <= 0x5F:                                   # WREG
            reg, cuantos = cmd & 0x1F, datos[1] + 1
            for i, valor in enumerate(datos[2:2 + cuantos]):
                self.regs[reg + i] = valor
            # Estos registros reinician la conversion del ADC1 (Tabla 9-34, columna "ADC restart").
            if any(reg <= r < reg + cuantos for r in (3, 4, 5, 6, 0x0D, 0x0E, 0x0F)):
                self._reiniciar_conversion()
        return bytes(rx)
