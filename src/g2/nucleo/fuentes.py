"""De donde salen las tensiones de los sensores.

El nucleo pide la tension de un canal por su nombre (``ads1263:0-1``, el mismo texto que guarda
``sensor.canal``) y recibe voltios, o ``None`` si no hubo una lectura valida. Asi el nucleo no
conoce el hardware y se prueba con una fuente simulada.
"""

from __future__ import annotations

import time
from typing import Callable, Protocol

from g2.hardware import ads1263 as A


class FuenteTension(Protocol):
    def leer(self, canal: str) -> float | None:
        """Tension diferencial del sensor, en voltios; ``None`` si no hay lectura valida."""


def analizar_canal(canal: str) -> tuple[int, int]:
    """``'ads1263:0-1'`` -> ``(0, 1)`` (entrada positiva y negativa del ADC)."""
    try:
        tipo, par = canal.split(":", 1)
        positiva, negativa = (int(x) for x in par.split("-", 1))
    except ValueError as error:
        raise ValueError(f"canal con formato invalido: {canal!r} (se espera ads1263:N-M)") from error
    if tipo != "ads1263":
        raise ValueError(f"tipo de canal no soportado: {tipo!r}")
    return positiva, negativa


class FuenteAds1263:
    """Lee los sensores del ADS1263 real (o emulado).

    Ante un error del ADC no se detiene: devuelve ``None`` (el motor de alarmas lo trata como
    "sin señal"). Si el chip se reinicio, o hay varios errores seguidos, intenta reconfigurarlo, con
    una espera minima entre intentos (D-012: nada bloquea el programa).
    """

    def __init__(self, adc: A.Ads1263, *, tiempo_max_s: float = 1.0,
                 errores_para_reiniciar: int = 3, espera_reinicio_s: float = 5.0,
                 ahora: Callable[[], float] = time.monotonic) -> None:
        self._adc = adc
        self._tiempo_max_s = tiempo_max_s
        self._errores_para_reiniciar = errores_para_reiniciar
        self._espera_reinicio_s = espera_reinicio_s
        self._ahora = ahora
        self._errores_seguidos = 0
        self._ultimo_reinicio = float("-inf")
        self.ultimo_error: str | None = None

    def leer(self, canal: str) -> float | None:
        positiva, negativa = analizar_canal(canal)
        try:
            lectura = self._adc.leer_diferencial(positiva, negativa, tiempo_max_s=self._tiempo_max_s)
        except A.ErrorChipReiniciado as error:
            self._registrar_error(error)
            self._reconfigurar(forzar=True)
            return None
        except A.ErrorAdc as error:
            self._registrar_error(error)
            if self._errores_seguidos >= self._errores_para_reiniciar:
                self._reconfigurar(forzar=False)
            return None
        if "referencia_baja" in lectura.alarmas:         # la referencia interna fallo: dato dudoso
            self._registrar_error(A.ErrorAdc("referencia baja"))
            return None
        self._errores_seguidos = 0
        self.ultimo_error = None
        return lectura.tension_v

    def _registrar_error(self, error: Exception) -> None:
        self._errores_seguidos += 1
        self.ultimo_error = f"{type(error).__name__}: {error}"

    def _reconfigurar(self, *, forzar: bool) -> None:
        ahora = self._ahora()
        if not forzar and ahora - self._ultimo_reinicio < self._espera_reinicio_s:
            return
        self._ultimo_reinicio = ahora
        try:
            self._adc.iniciar()
        except A.ErrorAdc as error:
            self.ultimo_error = f"no se pudo reiniciar el ADC: {error}"


class FuenteSimulada:
    """Tensiones fijas por canal, para pruebas y para correr el nucleo sin ADC. ``tensiones`` puede
    cambiarse en cualquier momento; un canal ausente o con ``None`` simula un sensor sin señal."""

    def __init__(self, tensiones: dict[str, float | None] | None = None) -> None:
        self.tensiones = dict(tensiones or {})

    def leer(self, canal: str) -> float | None:
        return self.tensiones.get(canal)
