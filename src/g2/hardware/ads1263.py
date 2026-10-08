"""Controlador del convertidor ADS1263 de Texas Instruments (ADC1, 32 bits).

Fuente de todos los datos: hoja de datos "ADS126x" (SBAS661C, mayo de 2021). Se cita la
seccion o tabla en cada constante. Decision de diseño y configuracion elegida: D-025 en
MEMORIA_TECNICA.md.

Alcance de esta primera version:
  * Solo el convertidor principal ADC1 (32 bits), en conversion continua, con la
    referencia interna de 2.5 V y lectura por comando (RDATA1).
  * Lecturas diferenciales entre dos entradas AINx (cada sensor de oxigeno usa un par).
  * No usa el ADC2, las fuentes de corriente (IDAC), el DAC de prueba ni los GPIO del chip.
  * La autocalibracion de offset (SFOCAL1) queda para una etapa posterior; mientras
    tanto el offset se reduce con el modo chopper (ver ``ConfigAdc.chopper``).

El acceso fisico (SPI, pin CS, pin RESET) esta detras de la interfaz ``PuertoSpi``: la
implementacion real esta en ``puerto_spi_pi.py`` y el emulador en ``ads1263_emulado.py``.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Callable, Protocol

# --- Comandos (Tabla 9-33) ----------------------------------------------------------
CMD_RESET = 0x06
CMD_START1 = 0x08
CMD_STOP1 = 0x0A
CMD_RDATA1 = 0x12
CMD_RREG = 0x20          # 0x20 | direccion, y luego (numero de registros - 1)
CMD_WREG = 0x40          # 0x40 | direccion, y luego (numero de registros - 1)

# --- Registros (Tabla 9-34) ---------------------------------------------------------
REG_ID = 0x00
REG_POWER = 0x01
REG_INTERFACE = 0x02
REG_MODE0 = 0x03
REG_MODE1 = 0x04
REG_MODE2 = 0x05
REG_INPMUX = 0x06
REG_REFMUX = 0x0F

# --- Valores y campos de bits --------------------------------------------------------
DEV_ID_ADS1263 = 0b001                 # bits 7..5 del registro ID (Tabla 9-35)
POWER_INTREF = 0x01                    # referencia interna de 2.5 V habilitada (Tabla 9-36)
POWER_RESET = 0x10                     # indicador de reinicio: 1 = hubo un reinicio
INTERFACE_STATUS_Y_CHECKSUM = 0x05     # byte de estado + byte de suma de control (Tabla 9-37)
REFMUX_INTERNA_2V5 = 0x00              # referencia interna de 2.5 V (valor de fabrica)
REFMUX_AVDD = 0x24                     # referencia = VAVDD - VAVSS: RMUXP=100, RMUXN=100 (Tabla 9-46)
VREF_INTERNA = 2.5                     # voltios
VREF_AVDD_NOMINAL = 5.0                # voltios; la real depende de la alimentacion de 5 V del HAT

# Byte de estado (Tabla 9-18)
STATUS_ADC1_NUEVO = 0x40               # bit 6: dato nuevo desde la ultima lectura
STATUS_REF_BAJA = 0x10                 # bit 4: referencia baja (alarma)
STATUS_PGA_BAJO = 0x08                 # bit 3: salida del PGA bajo VAVSS + 0.2 V
STATUS_PGA_ALTO = 0x04                 # bit 2: salida del PGA sobre VAVDD - 0.2 V
STATUS_PGA_DIFERENCIAL = 0x02          # bit 1: salida diferencial del PGA > 105 % de FS
STATUS_REINICIO = 0x01                 # bit 0: el chip se reinicio desde el ultimo borrado

# Filtros digitales, bits 7..5 de MODE1 (Tabla 9-39)
FILTROS = {"sinc1": 0, "sinc2": 1, "sinc3": 2, "sinc4": 3, "fir": 4}

# Velocidad de datos, bits 3..0 de MODE2 (Tabla 9-40). Con el filtro FIR solo se
# permiten 2.5, 5, 10 y 20 SPS.
VELOCIDADES_SPS = {2.5: 0, 5: 1, 10: 2, 16.6: 3, 20: 4, 50: 5, 60: 6, 100: 7,
                   400: 8, 1200: 9, 2400: 10, 4800: 11, 7200: 12, 14400: 13,
                   19200: 14, 38400: 15}
VELOCIDADES_FIR = {2.5, 5, 10, 20}

# Ganancias del PGA, bits 6..4 de MODE2 (Tabla 9-40)
GANANCIAS = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4, 32: 5}

# Entradas del multiplexor (Tabla 9-41): AIN0..AIN9 = 0..9, AINCOM = 10
AINCOM = 0x0A

CONSTANTE_CHECKSUM = 0x9B              # se suma a los 4 bytes de datos (sec. 9.4.7.3.3.1)


class ErrorAdc(Exception):
    """Error general del convertidor."""


class ErrorChipNoEsperado(ErrorAdc):
    """El dispositivo no responde como un ADS1263 (no esta conectado, o SPI mal)."""


class ErrorTiempoAgotado(ErrorAdc):
    """No llego un dato nuevo dentro del tiempo maximo."""


class ErrorChecksum(ErrorAdc):
    """La suma de control del dato recibido no coincide (error de comunicacion)."""


class ErrorChipReiniciado(ErrorAdc):
    """El chip se reinicio (por ejemplo, por un bache de energia): hay que reconfigurarlo."""


class PuertoSpi(Protocol):
    """Interfaz fisica que necesita el controlador."""

    def transferir(self, datos: bytes) -> bytes:
        """Activa CS, envia ``datos`` y devuelve los bytes recibidos (misma longitud,
        full duplex), y libera CS."""

    def reiniciar(self) -> None:
        """Reinicio por hardware del chip (pin RESET) y espera de arranque."""


@dataclass(frozen=True)
class ConfigAdc:
    """Configuracion del ADC1. Los valores por omision son los de D-025."""

    ganancia: int = 1                  # 1, 2, 4, 8, 16 o 32
    pga_derivacion: bool = True        # True = PGA en derivacion (bypass): ver D-025
    filtro: str = "fir"                # sinc1..sinc4 o fir
    sps: float = 20                    # muestras por segundo (ver VELOCIDADES_SPS)
    chopper: bool = False              # modo chopper de entrada (reduce el offset)
    # "interna" = 2.5 V precisos (la que se usa para medir el sensor, rango ±2.5 V).
    # "avdd" = la alimentacion analogica de 5 V como referencia (rango ±5 V): solo para
    # DIAGNOSTICO de tensiones mayores de 2.5 V; no es precisa (hereda la tolerancia de los
    # 5 V del HAT).
    referencia: str = "interna"

    @property
    def vref(self) -> float:
        return VREF_INTERNA if self.referencia == "interna" else VREF_AVDD_NOMINAL

    @property
    def refmux(self) -> int:
        return REFMUX_INTERNA_2V5 if self.referencia == "interna" else REFMUX_AVDD

    def validar(self) -> None:
        if self.referencia not in ("interna", "avdd"):
            raise ValueError(f"referencia no valida: {self.referencia}")
        if self.ganancia not in GANANCIAS:
            raise ValueError(f"ganancia no valida: {self.ganancia}")
        if self.filtro not in FILTROS:
            raise ValueError(f"filtro no valido: {self.filtro}")
        if self.sps not in VELOCIDADES_SPS:
            raise ValueError(f"velocidad no valida: {self.sps}")
        if self.filtro == "fir" and self.sps not in VELOCIDADES_FIR:
            raise ValueError("con el filtro FIR solo se permiten 2.5, 5, 10 y 20 SPS")

    def registros(self) -> bytes:
        """Valores de MODE0, MODE1 y MODE2 (INPMUX lo fija cada lectura)."""
        self.validar()
        mode0 = (0 << 6) | ((0b01 if self.chopper else 0b00) << 4)    # continuo, delay 0
        mode1 = FILTROS[self.filtro] << 5                              # sin polarizacion
        mode2 = ((1 if self.pga_derivacion else 0) << 7) | (GANANCIAS[self.ganancia] << 4) \
            | VELOCIDADES_SPS[self.sps]
        return bytes([mode0, mode1, mode2])


@dataclass(frozen=True)
class Lectura:
    """Resultado de una conversion."""

    tension_v: float
    codigo: int                        # entero de 32 bits con signo (Tabla 9-19)
    status: int                        # byte de estado crudo
    canal: tuple[int, int]             # (entrada positiva, entrada negativa)
    pga_activo: bool = True            # False si el PGA esta en derivacion

    @property
    def alarmas(self) -> list[str]:
        """Alarmas de la referencia y, solo si el PGA esta activo, las del PGA.

        Con el PGA en derivacion los monitores del PGA no tienen sentido: en la prueba
        con el hardware real (2026-10-08) el bit de salida alta del PGA aparecio activo
        con el PGA en derivacion, asi que se ignoran en ese caso.
        """
        nombres = {STATUS_REF_BAJA: "referencia_baja"}
        if self.pga_activo:
            nombres.update({STATUS_PGA_BAJO: "pga_salida_baja", STATUS_PGA_ALTO: "pga_salida_alta",
                            STATUS_PGA_DIFERENCIAL: "pga_sobrerrango"})
        return [n for bit, n in nombres.items() if self.status & bit]


def codigo_a_tension(codigo: int, ganancia: int, vref: float = VREF_INTERNA) -> float:
    """Convierte el codigo de 32 bits a voltios: V = codigo * VREF / (ganancia * 2**31)."""
    return codigo * vref / (ganancia * 2 ** 31)


def checksum(datos4: bytes) -> int:
    """Suma de control: suma de los 4 bytes de datos mas 0x9B, modulo 256 (sec. 9.4.7.3.3.1)."""
    return (sum(datos4) + CONSTANTE_CHECKSUM) & 0xFF


class Ads1263:
    """Controlador del ADC1 del ADS1263.

    Uso tipico::

        adc = Ads1263(puerto)          # puerto real o emulado
        adc.iniciar()                  # reinicia, identifica, configura y arranca
        lectura = adc.leer_diferencial(0, 1)   # sensor 1: AIN0 - AIN1
        lectura = adc.leer_diferencial(2, 3)   # sensor 2: AIN2 - AIN3

    Toda espera tiene tiempo maximo (D-012): ninguna llamada puede bloquear el proceso.
    """

    def __init__(self, puerto: PuertoSpi, config: ConfigAdc | None = None, *,
                 ahora: Callable[[], float] = time.monotonic,
                 esperar: Callable[[float], None] = time.sleep) -> None:
        self._puerto = puerto
        self.config = config or ConfigAdc()
        self.config.validar()
        self._ahora = ahora
        self._esperar = esperar
        self._mux_actual: int | None = None

    # -- registros -------------------------------------------------------------------
    def leer_registro(self, direccion: int, cantidad: int = 1) -> bytes:
        """RREG: lee ``cantidad`` registros consecutivos desde ``direccion`` (sec. 9.5.6)."""
        tx = bytes([CMD_RREG | direccion, cantidad - 1]) + bytes(cantidad)
        return self._puerto.transferir(tx)[2:]

    def escribir_registros(self, direccion: int, valores: bytes) -> None:
        """WREG: escribe registros consecutivos (sec. 9.5.7). Escribir MODE0..INPMUX en un
        solo comando los aplica juntos y reinicia la conversion una sola vez (Tabla 9-34)."""
        tx = bytes([CMD_WREG | direccion, len(valores) - 1]) + valores
        self._puerto.transferir(tx)

    # -- arranque ----------------------------------------------------------------------
    def iniciar(self) -> None:
        """Reinicia, identifica, configura y arranca las conversiones.

        Raises:
            ErrorChipNoEsperado: si el chip no es un ADS1263 o no queda configurado.
        """
        self._puerto.reiniciar()
        self._mux_actual = None
        self.identificar()
        self.configurar()
        self._puerto.transferir(bytes([CMD_START1]))

    def identificar(self) -> int:
        """Lee el registro ID y comprueba que sea un ADS1263 (bits 7..5 = 001).

        Returns:
            El registro ID completo (los bits 4..0 son la revision del chip).
        """
        ident = self.leer_registro(REG_ID)[0]
        if ident >> 5 != DEV_ID_ADS1263:
            raise ErrorChipNoEsperado(f"ID=0x{ident:02X}: no es un ADS1263")
        return ident

    def configurar(self) -> None:
        """Escribe la configuracion y la verifica leyendola de vuelta."""
        self.escribir_registros(REG_INTERFACE, bytes([INTERFACE_STATUS_Y_CHECKSUM]))
        self.escribir_registros(REG_REFMUX, bytes([self.config.refmux]))
        mux_inicial = (0 << 4) | 1                                  # AIN0 - AIN1
        bloque = self.config.registros() + bytes([mux_inicial])     # MODE0, MODE1, MODE2, INPMUX
        self.escribir_registros(REG_MODE0, bloque)
        # Borra el indicador de reinicio para poder detectar un reinicio inesperado despues.
        self.escribir_registros(REG_POWER, bytes([POWER_INTREF]))

        leido = self.leer_registro(REG_MODE0, 4)
        if leido != bloque:
            raise ErrorChipNoEsperado(
                f"la configuracion no quedo guardada: escrito {bloque.hex()}, leido {leido.hex()}")
        if self.leer_registro(REG_INTERFACE)[0] != INTERFACE_STATUS_Y_CHECKSUM:
            raise ErrorChipNoEsperado("el registro INTERFACE no quedo como se escribio")
        self._mux_actual = mux_inicial

    # -- lectura -------------------------------------------------------------------------
    def leer_diferencial(self, positiva: int, negativa: int, tiempo_max_s: float = 1.0) -> Lectura:
        """Lee la tension diferencial entre dos entradas (``positiva`` - ``negativa``).

        Cambiar de entrada reinicia la conversion y el primer dato nuevo ya es de la
        entrada nueva (conversion de ciclo unico), asi que se espera el primer dato nuevo.

        Args:
            positiva, negativa: numeros de entrada 0..9 (AIN0..AIN9) o 10 (AINCOM).
            tiempo_max_s: espera maxima por un dato nuevo.

        Raises:
            ErrorTiempoAgotado: si no llega un dato nuevo a tiempo.
            ErrorChecksum: si el dato llega corrupto.
            ErrorChipReiniciado: si el chip se reinicio (hay que llamar a ``iniciar``).
        """
        mux = ((positiva & 0x0F) << 4) | (negativa & 0x0F)
        if mux != self._mux_actual:
            self.escribir_registros(REG_INPMUX, bytes([mux]))
            self._mux_actual = mux

        limite = self._ahora() + tiempo_max_s
        while True:
            # RDATA1: opcode + 6 bytes de relleno. La respuesta empieza tras el opcode:
            # [ignorado, STATUS, DATO(4), CHECKSUM] (Figura 9-44).
            rx = self._puerto.transferir(bytes([CMD_RDATA1]) + bytes(6))
            status, datos, chk = rx[1], rx[2:6], rx[6]
            if status & STATUS_REINICIO:
                raise ErrorChipReiniciado("el ADS1263 se reinicio; reconfigurar con iniciar()")
            if status & STATUS_ADC1_NUEVO:
                if chk != checksum(datos):
                    raise ErrorChecksum(
                        f"suma de control incorrecta: recibido 0x{chk:02X}, "
                        f"calculado 0x{checksum(datos):02X}")
                codigo = struct.unpack(">i", datos)[0]
                return Lectura(codigo_a_tension(codigo, self.config.ganancia, self.config.vref), codigo,
                               status, (positiva, negativa),
                               pga_activo=not self.config.pga_derivacion)
            if self._ahora() >= limite:
                raise ErrorTiempoAgotado(
                    f"sin dato nuevo en {tiempo_max_s:.2f} s (entradas {positiva}-{negativa})")
            self._esperar(0.002)       # menos que el periodo de una conversion (50 ms a 20 SPS)

    def detener(self) -> None:
        """Detiene las conversiones (STOP1)."""
        self._puerto.transferir(bytes([CMD_STOP1]))
