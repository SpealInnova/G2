"""Calibracion por puntos de UN sensor, con gas patron (D-048, D-049).

El Paracube analogico no se calibra por comando (D-001): la correccion se hace en el equipo. El nucleo convierte la tension
en % de O2 con una recta (``senal.tension_a_pct``)::

    O2 [%] = ganancia * (tension [mV] / mv_por_pct) + cero

Se calibra **un punto a la vez**: el sensor se expone a un gas patron de concentracion conocida (la que el usuario indica:
0,0 % de nitrogeno, el aire a 20,9 %, 98,0 %, 99,8 % u otra) y se mide su tension. Segun la referencia, el punto cae en una de
dos casillas:

  * **bajo**: referencia menor que ``UMBRAL_ALTO_PCT`` (50 %). Fija el cero.
  * **alto**: referencia de 50 % o mas. Fija la pendiente (ganancia).

La calibracion vigente se compone con el ultimo punto medido de cada casilla (el otro se conserva de la calibracion anterior):

  * con los dos puntos:  ``ganancia = (R_alto - R_bajo) / (x_alto - x_bajo)``  y  ``cero = R_bajo - ganancia * x_bajo``, donde ``x`` es
    la tension medida en % (sin corregir);
  * solo el bajo: ``ganancia = 1`` y ``cero = R_bajo - x_bajo`` (corrige unicamente el cero);
  * solo el alto: ``cero = 0`` y ``ganancia = R_alto / x_alto`` (hasta tener un punto bajo).

Siempre se parte de la **tension** medida, no de la lectura ya corregida: calibrar dos veces seguidas no acumula.

Esta clase es la maquina de estados PURA (no toca la base ni la pantalla; recibe el tiempo). Reglas acordadas con el usuario:

  * la medicion es el promedio de una ventana de ``VENTANA_S`` (30 s) cuya variacion de pico a pico no pasa de
    ``ESTABLE_PICO_A_PICO_PCT`` (0,3 %); mientras el sensor se asienta, la ventana se desliza y se espera;
  * una muestra sin señal vacia la ventana (no se promedia con huecos);
  * la calibracion FALLA, y no se aplica, si la ganancia queda fuera de ``GANANCIA_MIN``-``GANANCIA_MAX`` (0,90 a 1,10), si el cero pasa
    de ``CERO_MAX_PCT`` (+-3 %), si los dos puntos distan menos de ``SEPARACION_MIN_PCT`` (50 puntos) o si en ``TOPE_S`` (5 min) la
    señal no se estabiliza. Casi siempre es que el sensor no tenia el gas indicado.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

REFERENCIA_AIRE_PCT = 20.9
UMBRAL_ALTO_PCT = 50.0                      # referencia < 50: punto bajo; >= 50: punto alto
VENTANA_S = 30.0
TOLERANCIA_VENTANA_S = 1.0                  # la ventana puede cubrir 1 s menos que VENTANA_S (las muestras llegan cada 0,5 s)
MIN_MUESTRAS = 10
ESTABLE_PICO_A_PICO_PCT = 0.3
CERO_MAX_PCT = 3.0
GANANCIA_MIN, GANANCIA_MAX = 0.90, 1.10
SEPARACION_MIN_PCT = 50.0
TOPE_S = 300.0
BREVE_MAX = 68                              # el mensaje para la pantalla, con `Sensor 1: ` delante, cabe en 80 letras


def casilla(referencia_pct: float) -> str:
    """``'bajo'`` o ``'alto'`` segun la concentracion del gas patron."""
    return "alto" if referencia_pct >= UMBRAL_ALTO_PCT else "bajo"


@dataclass(frozen=True)
class Punto:
    referencia_pct: float
    mv: float                               # tension media medida, en mV, sin corregir


@dataclass(frozen=True)
class Puntos:
    """Los dos puntos de la calibracion vigente (``None``: todavia no se ha medido)."""
    bajo: Punto | None = None
    alto: Punto | None = None


@dataclass(frozen=True)
class Recta:
    ganancia: float
    cero_pct: float
    puntos: Puntos
    error: str | None = None                # por que se rechaza (la recta se entrega igual, para dejarla en el registro)
    breve: str | None = None                # lo mismo en pocas letras, para la pantalla


def calcular(mv_por_pct: float, punto: Punto, previos: Puntos) -> Recta:
    """La recta que resulta de medir ``punto`` teniendo ``previos``. Si no cumple los limites, ``error`` lo dice."""
    puntos = Puntos(bajo=punto if casilla(punto.referencia_pct) == "bajo" else previos.bajo,
                    alto=punto if casilla(punto.referencia_pct) == "alto" else previos.alto)
    bajo, alto = puntos.bajo, puntos.alto
    error = breve = None
    if bajo is not None and alto is not None:
        x0, x1 = bajo.mv / mv_por_pct, alto.mv / mv_por_pct
        if alto.referencia_pct - bajo.referencia_pct < SEPARACION_MIN_PCT:
            return Recta(1.0, 0.0, puntos, f"Los puntos ({bajo.referencia_pct:g} % y {alto.referencia_pct:g} %) distan menos "
                                           f"de {SEPARACION_MIN_PCT:g} puntos", f"Los gases distan menos de {SEPARACION_MIN_PCT:g} puntos")
        if x1 - x0 <= 0:
            return Recta(1.0, 0.0, puntos, "La señal con el gas alto no es mayor que con el gas bajo: ¿está el gas correcto?",
                         "El gas alto no da más señal que el bajo")
        ganancia = (alto.referencia_pct - bajo.referencia_pct) / (x1 - x0)
        cero = bajo.referencia_pct - ganancia * x0
    elif bajo is not None:
        ganancia, cero = 1.0, bajo.referencia_pct - bajo.mv / mv_por_pct
    else:
        assert alto is not None
        x1 = alto.mv / mv_por_pct
        if x1 <= 0:
            return Recta(1.0, 0.0, puntos, "El sensor no da señal con el gas alto: ¿está el gas correcto?",
                         "Sin señal con el gas alto: ¿gas correcto?")
        ganancia, cero = alto.referencia_pct / x1, 0.0
    if not GANANCIA_MIN <= ganancia <= GANANCIA_MAX:
        error = (f"La ganancia ({ganancia:.3f}) sale de {GANANCIA_MIN:.2f} a {GANANCIA_MAX:.2f}: "
                 "¿está el gas indicado en el sensor?")
        breve = f"Ganancia {ganancia:.2f} (debe ser de {GANANCIA_MIN:.2f} a {GANANCIA_MAX:.2f}): ¿gas correcto?"
    elif abs(cero) > CERO_MAX_PCT:
        error = f"El cero ({cero:+.1f} %) pasa de ±{CERO_MAX_PCT:g} %: ¿está el gas indicado en el sensor?"
        breve = f"Cero {cero:+.1f} % pasa de ±{CERO_MAX_PCT:g}: ¿gas correcto?"
    return Recta(ganancia, cero, puntos, error, breve)


@dataclass(frozen=True)
class ResultadoCalibracion:
    ok: bool
    motivo: str                             # el detalle, para el registro
    referencia_pct: float
    casilla: str                            # "bajo" o "alto"
    mv_prom: float | None = None            # solo si la medicion se completo (aunque despues se haya rechazado)
    recta: Recta | None = None
    variacion_pct: float | None = None
    duracion_s: float = 0.0
    breve: str = ""                         # lo mismo en pocas letras (cabe en una linea de la pantalla)

    @property
    def offset_pct(self) -> float | None:
        return None if self.recta is None else self.recta.cero_pct

    @property
    def ganancia(self) -> float | None:
        return None if self.recta is None else self.recta.ganancia


class CalibracionPunto:
    def __init__(self, *, sensor_id: int, nombre: str, mv_por_pct: float, referencia_pct: float, previos: Puntos,
                 ahora_s: float, comando_id: int | None, actor: str, origen: str) -> None:
        self.sensor_id, self.nombre, self.mv_por_pct = sensor_id, nombre, mv_por_pct
        self.referencia_pct, self.previos = referencia_pct, previos
        self.casilla = casilla(referencia_pct)
        self.comando_id, self.actor, self.origen = comando_id, actor, origen
        self.inicio_s = ahora_s
        self._ventana: deque[tuple[float, float]] = deque()          # (instante, mV)
        self.variacion_pct: float | None = None
        self.mv_actual: float | None = None

    def agregar(self, ahora_s: float, mv: float | None) -> ResultadoCalibracion | None:
        """Una muestra del sensor (``None``: sin señal). Devuelve el resultado cuando ya lo hay."""
        transcurrido = ahora_s - self.inicio_s
        self.mv_actual = mv
        if mv is None:
            self._ventana.clear()
            self.variacion_pct = None
        else:
            self._ventana.append((ahora_s, mv))
            while self._ventana and ahora_s - self._ventana[0][0] > VENTANA_S:
                self._ventana.popleft()
            valores = [v for _, v in self._ventana]
            self.variacion_pct = (max(valores) - min(valores)) / self.mv_por_pct
            cubierto = ahora_s - self._ventana[0][0]
            if cubierto >= VENTANA_S - TOLERANCIA_VENTANA_S and len(valores) >= MIN_MUESTRAS \
                    and self.variacion_pct <= ESTABLE_PICO_A_PICO_PCT:
                return self._concluir(sum(valores) / len(valores), transcurrido)
        if transcurrido >= TOPE_S:
            return ResultadoCalibracion(
                False, f"El sensor no se estabilizó en {TOPE_S / 60:.0f} min (la variación no bajó de "
                       f"{ESTABLE_PICO_A_PICO_PCT} %)", self.referencia_pct, self.casilla,
                variacion_pct=self.variacion_pct, duracion_s=transcurrido, breve=f"No se estabilizó en {TOPE_S / 60:.0f} min")
        return None

    def _concluir(self, mv_prom: float, transcurrido: float) -> ResultadoCalibracion:
        punto = Punto(self.referencia_pct, mv_prom)
        recta = calcular(self.mv_por_pct, punto, self.previos)
        medido = mv_prom / self.mv_por_pct
        comun = dict(referencia_pct=self.referencia_pct, casilla=self.casilla, mv_prom=mv_prom, recta=recta,
                     variacion_pct=self.variacion_pct, duracion_s=transcurrido)
        if recta.error is not None:
            breve = f"Mide {medido:.1f} % con gas de {self.referencia_pct:g} %. {recta.breve}"
            return ResultadoCalibracion(
                False, f"El sensor mide {medido:.1f} % con gas de {self.referencia_pct:g} %. {recta.error}",
                breve=breve if len(breve) <= BREVE_MAX else recta.breve, **comun)
        falta = ""
        if recta.puntos.bajo is None:
            falta = " (falta el punto bajo)"
        elif recta.puntos.alto is None:
            falta = " (falta el punto alto; la ganancia sigue en 1)"
        return ResultadoCalibracion(
            True, f"Punto {self.casilla} {self.referencia_pct:g} % guardado (medía {medido:.2f} %): ganancia "
                  f"{recta.ganancia:.3f}, cero {recta.cero_pct:+.2f} %{falta}",
            breve=f"Punto {self.casilla} {self.referencia_pct:g} % listo: gan. {recta.ganancia:.3f}, cero {recta.cero_pct:+.2f} %",
            **comun)

    def estado(self, ahora_s: float, o2_actual: float | None) -> dict:
        """Lo que la pantalla muestra mientras dura."""
        return {"en_curso": True, "sensor_id": self.sensor_id, "nombre": self.nombre,
                "referencia_pct": self.referencia_pct, "casilla": self.casilla,
                "transcurrido_s": round(ahora_s - self.inicio_s, 1), "tope_s": TOPE_S,
                "variacion_pct": None if self.variacion_pct is None else round(self.variacion_pct, 2),
                "estable_pct": ESTABLE_PICO_A_PICO_PCT, "o2": o2_actual,
                "texto_o2": "--.-" if o2_actual is None else f"{o2_actual:.1f}"}
