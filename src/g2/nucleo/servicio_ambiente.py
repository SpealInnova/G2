"""Servicio del ambiente del nucleo: lee temperatura y humedad (DHT22) FUERA del ciclo principal (D-051).

Una lectura del DHT22 tarda desde unos 60 ms hasta unos 10 s si falla y hay que reintentar (el sensor pide 2 s entre
lecturas). El ciclo del nucleo no puede esperar eso: sigue leyendo los sensores de oxigeno y dando su latido al
watchdog (D-012). Por eso este servicio corre en un HILO propio, igual que ``servicio_red``:

  * cada ``intervalo_s`` pide una lectura al sensor;
  * deja cada resultado (bueno o con su error) en una cola corta;
  * el nucleo recoge la cola en su ciclo y es el UNICO que escribe en la base (D-005): este hilo NUNCA toca la base.

El sensor es opcional: si no esta o falla, el equipo sigue midiendo oxigeno igual.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from g2.hardware.dht22 import ErrorDht, LecturaDht
from g2.nucleo.senal import CALIDAD_INESTABLE, CALIDAD_SIN_DATOS

REGISTRO = logging.getLogger("g2.ambiente")
COLA_MAX = 600                                   # si el nucleo tardara en recoger, se descartan las mas viejas


@dataclass(frozen=True)
class Muestra:
    """Resultado de una lectura: o los dos valores, o el motivo del fallo."""

    mono_s: float
    temperatura_c: float | None = None
    humedad_pct: float | None = None
    error: str | None = None

    @property
    def buena(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class ResumenAmbiente:
    """Lo que se guarda de un intervalo del ambiente. ``temperatura`` y ``humedad`` son ``(prom, min, max)`` o
    ``None`` si no hubo ninguna lectura buena."""

    n_intentos: int
    n_buenas: int
    temperatura: tuple[float, float, float] | None
    humedad: tuple[float, float, float] | None

    @property
    def calidad(self) -> int:
        """Marcas de ``medicion_periferico.calidad`` (mismas que ``lectura``): 32 sin datos, 16 si hubo fallos."""
        if self.n_buenas == 0:
            return CALIDAD_SIN_DATOS
        return CALIDAD_INESTABLE if self.n_buenas < self.n_intentos else 0


class AcumuladorAmbiente:
    """Suma las lecturas de un intervalo para guardar promedio, minimo y maximo (D-007)."""

    def __init__(self) -> None:
        self._intentos = 0
        self._t: list[float] = []
        self._h: list[float] = []

    @property
    def n_intentos(self) -> int:
        return self._intentos

    def agregar(self, muestra: Muestra) -> None:
        self._intentos += 1
        if muestra.buena:
            self._t.append(muestra.temperatura_c)
            self._h.append(muestra.humedad_pct)

    def cerrar(self) -> ResumenAmbiente:
        """Entrega el resumen y deja el acumulador vacio para el siguiente intervalo."""
        def estadistica(valores: list[float]) -> tuple[float, float, float] | None:
            return (sum(valores) / len(valores), min(valores), max(valores)) if valores else None

        resumen = ResumenAmbiente(self._intentos, len(self._t), estadistica(self._t), estadistica(self._h))
        self._intentos, self._t, self._h = 0, [], []
        return resumen


class ServicioAmbiente:
    def __init__(self, lector: Callable[[], LecturaDht], *, intervalo_s: float = 10.0, mono=time.monotonic) -> None:
        """``lector``: devuelve una ``LecturaDht`` o lanza ``ErrorDht``. ``intervalo_s`` puede cambiarse en marcha."""
        self._lector = lector
        self.intervalo_s = intervalo_s
        self._mono = mono
        self._cerrojo = threading.Lock()
        self._despertar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._parar = False
        self._cola: deque[Muestra] = deque(maxlen=COLA_MAX)

    # ------------------------------------------------------------------ lo que usa el nucleo
    def iniciar(self) -> None:
        self._hilo = threading.Thread(target=self._bucle, name="g2-ambiente", daemon=True)
        self._hilo.start()

    def detener(self) -> None:
        self._parar = True
        self._despertar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=15)                  # una lectura con reintentos puede tardar unos segundos

    def tomar(self) -> list[Muestra]:
        """Las lecturas hechas desde la ultima vez, de la mas vieja a la mas nueva (despues se borran)."""
        with self._cerrojo:
            muestras = list(self._cola)
            self._cola.clear()
        return muestras

    # ------------------------------------------------------------------ el hilo
    def _bucle(self) -> None:
        while not self._parar:
            self.ciclo()
            self._despertar.wait(timeout=max(self.intervalo_s, 2.0))
            self._despertar.clear()

    def ciclo(self) -> None:
        """Una lectura (publica para poder probarse sin hilos)."""
        try:
            lectura = self._lector()
            muestra = Muestra(self._mono(), lectura.temperatura_c, lectura.humedad_pct)
        except ErrorDht as error:
            muestra = Muestra(self._mono(), error=str(error))
        except Exception as error:                       # nada del sensor debe tumbar el hilo
            REGISTRO.exception("fallo inesperado al leer el sensor de ambiente")
            muestra = Muestra(self._mono(), error=f"inesperado: {type(error).__name__}")
        with self._cerrojo:
            self._cola.append(muestra)
