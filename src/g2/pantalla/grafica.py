"""Grafica en tiempo de los dos sensores (D-043): historial, escala y ordenes para el componente *Waveform*.

Es logica PURA: no habla con la pantalla. La interfaz le da una muestra por segundo y le pide las ordenes que hay que
enviar. El componente de la pantalla (``s0`` de la pagina ``grafica``) tiene 4 canales con valores de 0 a 255:

    canal 0 = sensor 1,  canal 1 = sensor 2,  canal 2 = limite bajo de alarma,  canal 3 = limite alto de alarma

* **Nivel 0 = sin dato** (sensor sin senal, apagado o nucleo sin respuesta): la linea baja al borde inferior. Los
  valores validos usan los niveles 1 a 255, asi que nunca se confunden con el hueco.
* **Escala automatica**: el eje vertical se ajusta a lo que se ve (con un ancho minimo de 5 % O2), porque con 256 niveles
  una escala fija de 0 a 100 % dejaria 0.39 % por nivel y el ruido normal no se veria. Para que la grafica no salte, solo
  se reescala cuando un valor se sale del eje o cuando el eje quedo mucho mas ancho de lo necesario.
* **Los limites de alarma** solo se dibujan si caen dentro del eje visible.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Sequence

PUNTOS = 700                        # ancho del componente en pixeles = puntos por canal
PERIODO_S = 1.0                     # una muestra por segundo: la ventana es de 700 s (11.7 min)
CANALES_SENSOR = 2
CANAL_BAJO, CANAL_ALTO = 2, 3
OBJETO = "s0.id"                    # el componente Waveform, tal como lo nombra Nextion en add / addt / cle
ANCHO_MINIMO_PCT = 5.0              # ancho minimo del eje vertical
MARGEN = 0.10                       # holgura sobre lo visible, a cada lado
ESPERA_REESCALA_S = 30.0            # no se reduce el eje mas de una vez en este tiempo
SOBRANTE_PARA_REDUCIR = 3.0         # el eje se reduce cuando es 3 veces mas ancho de lo necesario
SIN_DATO = 0


def _redondear_eje(bajo: float, alto: float) -> tuple[float, float]:
    """Lleva el eje a numeros redondos (de 1 en 1 si es estrecho, de 5 en 5 si no), dentro de 0 a 100 y con el ancho minimo."""
    paso = 1.0 if alto - bajo <= 20.0 else 5.0
    bajo, alto = math.floor(bajo / paso) * paso, math.ceil(alto / paso) * paso
    if alto - bajo < ANCHO_MINIMO_PCT:
        alto = bajo + ANCHO_MINIMO_PCT
    if bajo < 0.0:
        bajo, alto = 0.0, max(alto - bajo, ANCHO_MINIMO_PCT)
    if alto > 100.0:
        bajo, alto = max(0.0, bajo - (alto - 100.0)), 100.0
    return bajo, alto


def formato_eje(valor: float) -> str:
    """``21`` si es entero y ``21.5`` si no: lo que se escribe en las marcas del eje vertical."""
    return f"{valor:.0f}" if abs(valor - round(valor)) < 1e-9 else f"{valor:.1f}"


def formato_ventana(segundos: float) -> str:
    """``-11 min`` o ``-45 s``: lo que cubre la grafica, para la marca izquierda del eje del tiempo."""
    return f"-{segundos / 60:.0f} min" if segundos >= 90 else f"-{segundos:.0f} s"


class HistorialGrafica:
    """Las ultimas ``puntos`` muestras de cada sensor y el eje vertical vigente."""

    def __init__(self, puntos: int = PUNTOS) -> None:
        self.puntos = puntos
        self._datos: list[deque[float | None]] = [deque(maxlen=puntos) for _ in range(CANALES_SENSOR)]
        self.total = 0                       # muestras recibidas desde siempre: la interfaz sabe cuantas faltan por dibujar
        self.bajo: float | None = None       # eje vertical vigente (None mientras no haya datos)
        self.alto: float | None = None
        self._t_escala = float("-inf")

    # ------------------------------------------------------------------ datos
    def agregar(self, valores: Sequence[float | None]) -> None:
        """Una muestra por sensor (``None`` = sin dato)."""
        for canal in range(CANALES_SENSOR):
            valor = valores[canal] if canal < len(valores) else None
            self._datos[canal].append(None if valor is None else float(valor))
        self.total += 1

    def cantidad(self) -> int:
        return len(self._datos[0])

    def ultimas(self, canal: int, cuantas: int) -> list[float | None]:
        datos = self._datos[canal]
        cuantas = min(cuantas, len(datos))
        return list(datos)[len(datos) - cuantas:] if cuantas else []

    def _visibles(self) -> list[float]:
        return [v for canal in self._datos for v in canal if v is not None]

    # ------------------------------------------------------------------ escala
    def ajustar_escala(self, ahora: float) -> bool:
        """Revisa el eje vertical y lo cambia si hace falta. Devuelve True si cambio (hay que redibujar todo)."""
        visibles = self._visibles()
        if not visibles:
            return False
        menor, mayor = min(visibles), max(visibles)
        centro, mitad = (menor + mayor) / 2, max(mayor - menor, ANCHO_MINIMO_PCT) * (0.5 + MARGEN)
        ideal = _redondear_eje(centro - mitad, centro + mitad)
        if self.bajo is None or self.alto is None:
            self.bajo, self.alto, self._t_escala = ideal[0], ideal[1], ahora
            return True
        fuera = menor < self.bajo or mayor > self.alto
        muy_ancho = (self.alto - self.bajo) > SOBRANTE_PARA_REDUCIR * (ideal[1] - ideal[0])
        if fuera or (muy_ancho and ahora - self._t_escala >= ESPERA_REESCALA_S):
            if (self.bajo, self.alto) == ideal:
                return False
            self.bajo, self.alto, self._t_escala = ideal[0], ideal[1], ahora
            return True
        return False

    def nivel(self, valor: float | None) -> int:
        """Valor de 0 a 255 para el componente: 0 si no hay dato, 1 a 255 dentro del eje (lo que se sale se recorta)."""
        if valor is None or self.bajo is None or self.alto is None:
            return SIN_DATO
        fraccion = (valor - self.bajo) / (self.alto - self.bajo)
        return max(1, min(255, 1 + round(fraccion * 254)))

    def en_el_eje(self, valor: float) -> bool:
        return self.bajo is not None and self.alto is not None and self.bajo <= valor <= self.alto

    def marcas(self) -> tuple[str, str, str]:
        """Texto de las tres marcas del eje vertical: arriba, en medio y abajo."""
        if self.bajo is None or self.alto is None:
            return "", "", ""
        return formato_eje(self.alto), formato_eje((self.alto + self.bajo) / 2), formato_eje(self.bajo)

    # ------------------------------------------------------------------ ordenes para la pantalla
    def _canales_de_limites(self, limites: Sequence[float]) -> dict[int, int]:
        """``{canal: nivel}`` de los limites de alarma que caen dentro del eje."""
        return {canal: self.nivel(limite) for canal, limite in zip((CANAL_BAJO, CANAL_ALTO), limites)
                if self.en_el_eje(limite)}

    def bloques_completos(self, limites: Sequence[float]) -> list[tuple[int, bytes]]:
        """Para redibujar todo con ``addt``: ``[(canal, bytes)]``, un byte por punto (los canales de limite solo si se ven)."""
        n = self.cantidad()
        bloques = [(canal, bytes(self.nivel(v) for v in self._datos[canal])) for canal in range(CANALES_SENSOR)]
        bloques += [(canal, bytes([nivel]) * n) for canal, nivel in self._canales_de_limites(limites).items()]
        return [(canal, datos) for canal, datos in bloques if datos]

    def ordenes_completas(self, limites: Sequence[float]) -> list[str]:
        """Lo mismo con una orden ``add`` por punto: mas lento (700 puntos x 2 canales), pero funciona sin ``addt``."""
        ordenes = []
        for canal, datos in self.bloques_completos(limites):
            ordenes += [f"add {OBJETO},{canal},{nivel}" for nivel in datos]
        return ordenes

    def ordenes_nuevas(self, cuantas: int, limites: Sequence[float]) -> list[str]:
        """Las ordenes ``add`` de las ultimas ``cuantas`` muestras (una grafica que avanza)."""
        fijos = self._canales_de_limites(limites)
        recientes = [self.ultimas(canal, cuantas) for canal in range(CANALES_SENSOR)]
        ordenes: list[str] = []
        for i in range(len(recientes[0])):
            ordenes += [f"add {OBJETO},{canal},{self.nivel(recientes[canal][i])}" for canal in range(CANALES_SENSOR)]
            ordenes += [f"add {OBJETO},{canal},{nivel}" for canal, nivel in fijos.items()]
        return ordenes

    @staticmethod
    def orden_limpiar() -> str:
        return f"cle {OBJETO},255"                                # 255 = todos los canales

    @staticmethod
    def orden_bloque(canal: int, cantidad: int) -> str:
        return f"addt {OBJETO},{canal},{cantidad}"
