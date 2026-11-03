"""Sensor de temperatura y humedad DHT22 (AM2302) por un solo cable (D-051).

El DHT22 no tiene bus: la Pi baja la linea 1-2 ms, la suelta, y el sensor contesta con 40 bits cuya duracion en alto
es el dato (unos 27 us = 0, unos 70 us = 1). Hacerlo desde Python con ``sleep`` y ``read`` no es fiable en Linux (un
retraso de 50 us corrompe un bit), asi que aqui NO se mide el tiempo en Python: se pide al nucleo de Linux que anote
cada flanco con su hora (libgpiod v2, cola de eventos con marca de tiempo del kernel) y despues se decodifican los
pulsos ya medidos. ``decodificar`` es una funcion pura y se prueba sin hardware. Medido en la Pi 3 B+: el kernel tarda
0,3 a 0,8 ms en armar la deteccion de flancos tras soltar la linea, por lo que se pierden los primeros 1 a 4 bits;
``decodificar`` los reconstruye (son ceros).

Cableado (modulo de 3 pines, con su resistencia): VCC a 3,3 V, GND, DATA al GPIO elegido (por omision GPIO4, pin 7).
El sensor suelto de 4 pines necesita ademas 4,7-10 kOhm entre DATA y 3,3 V. NO alimentarlo a 5 V con DATA directo al
GPIO: la Pi 3 B+ admite 3,3 V en sus pines.

Este modulo no escribe en la base ni conoce al nucleo; ``servicio_ambiente`` lo llama desde su propio hilo.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Sequence

PIN_POR_OMISION = 4
CHIP_POR_OMISION = "/dev/gpiochip0"
PULSO_UNO_US = 50.0                       # un pulso alto de mas de esto es un 1 (el 0 dura ~27 us y el 1 ~70 us)
PULSO_MAXIMO_US = 150.0                   # un pulso alto de mas de esto no es un bit
BITS = 40
BITS_PERDIDOS_MAX = 6                    # los 6 primeros bits (humedad alta) valen 0: se pueden reconstruir
TEMPERATURA_MIN_C, TEMPERATURA_MAX_C = -40.0, 80.0       # rango del sensor segun su hoja de datos
HUMEDAD_MIN_PCT, HUMEDAD_MAX_PCT = 0.0, 100.0
ESPERA_ENTRE_INTENTOS_S = 2.1             # el sensor necesita >= 2 s entre lecturas

Borde = tuple[bool, int]                  # (True = flanco de subida, marca de tiempo en nanosegundos)


class ErrorDht(Exception):
    """La lectura no sirvio. ``motivo``: sin_respuesta | incompleta | pulso | suma | rango | hardware."""

    def __init__(self, motivo: str, detalle: str = "") -> None:
        super().__init__(f"{motivo}: {detalle}" if detalle else motivo)
        self.motivo = motivo


@dataclass(frozen=True)
class LecturaDht:
    temperatura_c: float
    humedad_pct: float


def decodificar(bordes: Sequence[Borde]) -> LecturaDht:
    """Convierte los flancos capturados en temperatura y humedad.

    Los pulsos altos son: el que da la Pi al soltar la linea, la respuesta del sensor (~80 us) y los 40 bits. Pasar la
    linea a entrada tarda 0,3 a 0,8 ms en el kernel y el sensor ya esta contestando, asi que en la Pi real SIEMPRE se
    pierden los primeros pulsos (a veces 1 y a veces 4 bits). Eso se compensa: los primeros 6 bits del dato son la parte
    alta de la humedad, que como no pasa de 100 % (0x03E8) vale siempre 0; se rellenan con ceros hasta ``BITS_PERDIDOS_MAX``
    bits y la suma de comprobacion confirma el resultado. Se prueba primero la interpretacion que supone menos bits
    perdidos; el primer pulso puede ser la respuesta del sensor y no un bit, asi que tambien se prueba sin el.

    Raises:
        ErrorDht: sin_respuesta (la linea no se movio), incompleta (faltan mas de ``BITS_PERDIDOS_MAX`` pulsos), pulso
            (uno no es un bit), suma (la suma de comprobacion no cuadra) o rango (el valor es imposible para el sensor).
    """
    altos: list[float] = []
    subida: int | None = None
    for es_subida, ts_ns in bordes:
        if es_subida:
            subida = ts_ns
        elif subida is not None:
            altos.append((ts_ns - subida) / 1000.0)                  # microsegundos
            subida = None
    if len(altos) < BITS - BITS_PERDIDOS_MAX:
        if len(bordes) <= 2:
            raise ErrorDht("sin_respuesta", "el sensor no contesta (revisar cableado y alimentacion)")
        raise ErrorDht("incompleta", f"{len(altos)} pulsos de {BITS}")
    candidatos: list[tuple[int, list[float]]] = []                   # (bits perdidos, pulsos que serian los ultimos bits)
    for saltar in (0, 1):
        pulsos = altos[saltar:][-BITS:]
        perdidos = BITS - len(pulsos)
        if 0 <= perdidos <= BITS_PERDIDOS_MAX and (perdidos, pulsos) not in candidatos:
            candidatos.append((perdidos, pulsos))
    candidatos.sort(key=lambda c: c[0])
    primero: ErrorDht | None = None
    for perdidos, pulsos in candidatos:
        try:
            return _valores([0] * perdidos + _bits(pulsos))
        except ErrorDht as error:
            primero = primero or error
    assert primero is not None
    raise primero


def _bits(pulsos: Sequence[float]) -> list[int]:
    if any(p <= 0 or p > PULSO_MAXIMO_US for p in pulsos):
        raise ErrorDht("pulso", "un pulso no tiene la duracion de un bit")
    return [1 if p > PULSO_UNO_US else 0 for p in pulsos]


def _valores(bits: list[int]) -> LecturaDht:
    octetos = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, BITS, 8)]
    if (octetos[0] + octetos[1] + octetos[2] + octetos[3]) & 0xFF != octetos[4]:
        raise ErrorDht("suma", "la suma de comprobacion no cuadra")
    humedad = ((octetos[0] << 8) | octetos[1]) / 10.0
    temperatura = (((octetos[2] & 0x7F) << 8) | octetos[3]) / 10.0
    if octetos[2] & 0x80:
        temperatura = -temperatura
    if not (HUMEDAD_MIN_PCT <= humedad <= HUMEDAD_MAX_PCT and TEMPERATURA_MIN_C <= temperatura <= TEMPERATURA_MAX_C):
        raise ErrorDht("rango", f"{temperatura:.1f} C y {humedad:.1f} % no son posibles para el sensor")
    return LecturaDht(temperatura, humedad)


def capturar_gpiod(pin: int = PIN_POR_OMISION, chip: str = CHIP_POR_OMISION) -> list[Borde]:
    """Pide una lectura al sensor y devuelve los flancos que dejo en la linea (solo en la Pi, con python3-libgpiod).

    La linea sale como salida en alto, se baja 2 ms (arranque) y se pasa a entrada con deteccion de flancos en UNA sola
    llamada (una salida no admite deteccion de flancos: el kernel responde EINVAL). Aun asi se pierden los primeros bits y
    ``decodificar`` los reconstruye. La linea se libera siempre al terminar.
    """
    try:
        import gpiod
        from gpiod.line import Bias, Direction, Edge, Value
    except ImportError as error:
        raise ErrorDht("hardware", "falta python3-libgpiod (solo se puede leer en la Raspberry Pi)") from error
    try:
        peticion = gpiod.request_lines(
            chip, consumer="g2-dht22", event_buffer_size=256,
            config={pin: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE)})
    except OSError as error:
        raise ErrorDht("hardware", f"no se pudo reservar el GPIO{pin}: {error}") from error
    bordes: list[Borde] = []
    try:
        time.sleep(0.05)                                              # la linea en reposo, en alto
        peticion.set_value(pin, Value.INACTIVE)
        time.sleep(0.002)                                             # arranque: al menos 1 ms en bajo
        peticion.reconfigure_lines({pin: gpiod.LineSettings(
            direction=Direction.INPUT, edge_detection=Edge.BOTH, bias=Bias.PULL_UP)})
        limite = time.monotonic() + 0.1
        while time.monotonic() < limite and peticion.wait_edge_events(0.05 if not bordes else 0.01):
            for evento in peticion.read_edge_events(256):
                bordes.append((evento.event_type == gpiod.EdgeEvent.Type.RISING_EDGE, evento.timestamp_ns))
    except OSError as error:
        raise ErrorDht("hardware", f"fallo al leer el GPIO{pin}: {error}") from error
    finally:
        peticion.release()
    return bordes


class Dht22:
    """Lee el DHT22 con reintentos. ``leer`` bloquea unos segundos si la lectura falla: llamarlo desde un hilo."""

    def __init__(self, pin: int = PIN_POR_OMISION, chip: str = CHIP_POR_OMISION, *, intentos: int = 5,
                 capturar: Callable[[], Sequence[Borde]] | None = None,
                 dormir: Callable[[float], None] = time.sleep) -> None:
        self.pin, self.chip, self.intentos = pin, chip, max(1, intentos)
        self._capturar = capturar or (lambda: capturar_gpiod(pin, chip))
        self._dormir = dormir

    def leer(self) -> LecturaDht:
        """Una lectura buena, o ``ErrorDht`` con el motivo del ultimo intento."""
        ultimo: ErrorDht | None = None
        for intento in range(self.intentos):
            if intento:
                self._dormir(ESPERA_ENTRE_INTENTOS_S)
            try:
                return decodificar(self._capturar())
            except ErrorDht as error:
                if error.motivo == "hardware":
                    raise                                             # reintentar no arregla un GPIO ocupado ni falta de libreria
                ultimo = error
        assert ultimo is not None
        raise ultimo


class DhtSimulado:
    """Sensor falso para correr el nucleo sin hardware (``--emulado``) y para las pruebas: devuelve valores fijos que
    pueden cambiarse, o falla si ``error`` tiene un texto."""

    def __init__(self, temperatura_c: float = 24.5, humedad_pct: float = 55.0) -> None:
        self.temperatura_c, self.humedad_pct = temperatura_c, humedad_pct
        self.error: str | None = None

    def leer(self) -> LecturaDht:
        if self.error is not None:
            raise ErrorDht("sin_respuesta", self.error)
        return LecturaDht(self.temperatura_c, self.humedad_pct)
