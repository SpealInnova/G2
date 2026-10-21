"""Salidas de alarma hacia el mundo fisico: los relevos (D-033).

El nucleo solo pide "relevo de oxigeno bajo activo / inactivo" y "relevo de oxigeno alto activo /
inactivo". Como se traduce eso a pines depende de decisiones que SIGUEN PENDIENTES (D-033): la placa
RPi Relay Board es de nivel bajo y los relevos van energizados en normal, de modo que el estado de
los pines durante el arranque y la caida del programa decide si una falla se nota o no (opciones A,
B y C del diagnostico). Por eso aqui solo hay la interfaz y una version emulada; la version que
maneja los GPIO 26, 20 y 21 se escribe cuando esa decision este tomada y medida en la placa real.
"""

from __future__ import annotations

from typing import Protocol


class SalidasAlarma(Protocol):
    def fijar(self, *, bajo: bool, alto: bool) -> None:
        """``bajo``/``alto`` True = alarma activa (el aparato de alarma debe avisar)."""


class SalidasEmuladas:
    """Guarda el ultimo estado pedido y cuantas veces cambio; sirve para pruebas y para correr el
    nucleo sin placa de relevos."""

    def __init__(self) -> None:
        self.bajo = False
        self.alto = False
        self.cambios = 0

    def fijar(self, *, bajo: bool, alto: bool) -> None:
        if (bajo, alto) != (self.bajo, self.alto):
            self.cambios += 1
        self.bajo, self.alto = bajo, alto
