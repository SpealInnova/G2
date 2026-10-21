"""De la tension del sensor al % de oxigeno, y su agregado por intervalo de almacenamiento.

El Paracube analogico entrega 10 mV por cada 1 % de O2 (``sensor.mv_por_pct``). La correccion de
cero de una calibracion (``calibracion.offset_pct``) se suma al resultado:

    O2 [%] = tension [mV] / mv_por_pct + offset_pct

Cada intervalo de almacenamiento (D-007, ``muestreo.intervalo_guardado_s``) se guarda como UN
registro con el promedio, el minimo y el maximo de las muestras. Un hueco queda como hueco (n = 0 y
valores nulos), nunca como un cero falso (regla del esquema).
"""

from __future__ import annotations

from dataclasses import dataclass

# Mascara de bits de ``lectura.calidad`` (ver 001_esquema_inicial.sql; 0 = lectura valida).
CALIDAD_SATURADA_BAJA = 1
CALIDAD_SATURADA_ALTA = 2
CALIDAD_EN_SPOC = 4
CALIDAD_DESHABILITADO = 8
CALIDAD_INESTABLE = 16
CALIDAD_SIN_DATOS = 32
CALIDAD_FUERA_DE_RANGO = 64

# Limites de la señal del sensor (evento SEN_SATURADO): fuera de este rango la muestra se marca.
SATURACION_BAJA_PCT = -15.0
SATURACION_ALTA_PCT = 200.0


def tension_a_pct(tension_v: float, mv_por_pct: float, offset_pct: float = 0.0) -> float:
    """% de O2 a partir de la tension diferencial del sensor, en voltios."""
    if mv_por_pct <= 0:
        raise ValueError("mv_por_pct debe ser positivo")
    return tension_v * 1000.0 / mv_por_pct + offset_pct


def calidad_de_muestra(o2_pct: float) -> int:
    """Marcas de calidad de una muestra individual segun su valor."""
    if o2_pct < SATURACION_BAJA_PCT:
        return CALIDAD_SATURADA_BAJA
    if o2_pct > SATURACION_ALTA_PCT:
        return CALIDAD_SATURADA_ALTA
    return 0


@dataclass(frozen=True)
class Resumen:
    """Lo que se guarda de un intervalo, para un sensor."""

    n_muestras: int
    o2_prom: float | None
    o2_min: float | None
    o2_max: float | None
    mv_prom: float | None
    calidad: int


class Acumulador:
    """Junta las muestras de un intervalo de un sensor y las resume al cerrarlo."""

    def __init__(self) -> None:
        self._reiniciar()

    def _reiniciar(self) -> None:
        self._n = 0
        self._suma_o2 = 0.0
        self._suma_mv = 0.0
        self._min: float | None = None
        self._max: float | None = None
        self._invalidas = 0
        self._calidad = 0

    @property
    def n_muestras(self) -> int:
        return self._n

    @property
    def n_intentos(self) -> int:
        """Muestras validas mas intentos fallidos del intervalo en curso."""
        return self._n + self._invalidas

    def agregar(self, o2_pct: float, mv: float) -> None:
        """Una muestra valida."""
        self._n += 1
        self._suma_o2 += o2_pct
        self._suma_mv += mv
        self._min = o2_pct if self._min is None else min(self._min, o2_pct)
        self._max = o2_pct if self._max is None else max(self._max, o2_pct)
        self._calidad |= calidad_de_muestra(o2_pct)

    def agregar_sin_dato(self) -> None:
        """Un intento de lectura que no dio un dato valido."""
        self._invalidas += 1

    def cerrar(self) -> Resumen:
        """Resume el intervalo y deja el acumulador listo para el siguiente.

        Si no hubo ninguna muestra valida: ``n_muestras = 0``, valores nulos y la marca ``sin_datos``.
        Si hubo muestras validas pero tambien intentos fallidos, se agrega la marca ``inestable``
        para que quien lea el registro sepa que el promedio sale de un intervalo con huecos.
        """
        if self._n == 0:
            resumen = Resumen(0, None, None, None, None, CALIDAD_SIN_DATOS)
        else:
            calidad = self._calidad | (CALIDAD_INESTABLE if self._invalidas else 0)
            resumen = Resumen(self._n, self._suma_o2 / self._n, self._min, self._max,
                              self._suma_mv / self._n, calidad)
        self._reiniciar()
        return resumen
