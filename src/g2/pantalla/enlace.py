"""Enlace con la pantalla: el puerto serie real y uno emulado para las pruebas.

Los dos ofrecen lo mismo a la interfaz: ``enviar(orden)`` y ``eventos()`` (los eventos que llegaron
desde la ultima vez, ya decodificados). Ninguno bloquea: g2-ui nunca debe quedarse esperando a la
pantalla (D-012).
"""

from __future__ import annotations

import os
import select
import time

from g2.pantalla import protocolo as P


VELOCIDADES_CANDIDATAS = (115200, 9600)           # la de fabrica de Nextion es 9600; se prefiere la rapida si la hay


def _probar_velocidad(puerto: str, baudios: int, espera_s: float = 0.8) -> bool:
    """True si la pantalla responde ``comok`` al comando ``connect`` a esa velocidad (solo Linux)."""
    enlace = EnlaceSerie(puerto, baudios)
    try:
        enlace.enviar_crudo(P.FIN + b"connect" + P.FIN)
        limite = time.monotonic() + espera_s
        recibido = b""
        while time.monotonic() < limite:
            recibido += enlace.leer_crudo()
            if b"comok" in recibido.replace(b"\x00", b""):
                return True
            time.sleep(0.05)
        return False
    finally:
        enlace.cerrar()


def detectar_baudios(puerto: str = "/dev/serial0", candidatas: tuple[int, ...] = VELOCIDADES_CANDIDATAS,
                     probar=_probar_velocidad) -> int | None:
    """Velocidad a la que responde la pantalla, probando las candidatas en orden; ``None`` si no responde a ninguna.
    Asi la interfaz funciona igual si el ``.tft`` deja la pantalla a 9600 (fabrica) o a 115200 (``bauds=115200`` en
    Program.s), y un cambio de velocidad no deja a la pantalla incomunicada."""
    for baudios in candidatas:
        try:
            if probar(puerto, baudios):
                return baudios
        except OSError:
            continue
    return None


class _EnlaceBase:
    def __init__(self) -> None:
        self._pendiente = b""

    def _leer_bytes(self) -> bytes:                      # lo implementa cada enlace
        raise NotImplementedError

    def eventos(self) -> list[P.Evento]:
        """Eventos recibidos desde la llamada anterior. Una trama incompleta espera a la siguiente."""
        datos = self._leer_bytes()
        if not datos and not self._pendiente:
            return []
        tramas, self._pendiente = P.separar(self._pendiente + datos)
        return [P.interpretar(t) for t in tramas]


class EnlaceSerie(_EnlaceBase):
    """Puerto serie de la Raspberry Pi (``/dev/serial0``, 8N1). La pantalla de fabrica va a 9600."""

    def __init__(self, puerto: str = "/dev/serial0", baudios: int = 9600) -> None:
        super().__init__()
        import termios                                    # solo existe en Linux (la Pi)
        velocidades = {9600: termios.B9600, 19200: termios.B19200, 38400: termios.B38400,
                       57600: termios.B57600, 115200: termios.B115200}
        if baudios not in velocidades:
            raise ValueError(f"velocidad no admitida: {baudios} (use {sorted(velocidades)})")
        self._fd = os.open(puerto, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        atributos = termios.tcgetattr(self._fd)
        atributos[0] = atributos[1] = atributos[3] = 0          # sin conversiones, modo crudo
        atributos[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        atributos[4] = atributos[5] = velocidades[baudios]
        termios.tcsetattr(self._fd, termios.TCSANOW, atributos)
        termios.tcflush(self._fd, termios.TCIOFLUSH)
        os.write(self._fd, P.FIN)                                # los FF iniciales limpian el buffer de la pantalla

    def _leer_bytes(self) -> bytes:
        try:
            return os.read(self._fd, 512)
        except BlockingIOError:
            return b""

    def enviar_crudo(self, datos: bytes) -> None:
        self._escribir(datos)

    def leer_crudo(self) -> bytes:
        return self._leer_bytes()

    def enviar(self, orden: str) -> None:
        self._escribir(P.codificar_orden(orden))

    def _escribir(self, datos: bytes) -> None:
        limite = time.monotonic() + 0.5
        while datos and time.monotonic() < limite:
            try:
                escritos = os.write(self._fd, datos)
                datos = datos[escritos:]
            except BlockingIOError:                              # el buffer del puerto esta lleno: esperar un poco
                select.select([], [self._fd], [], 0.05)

    def cerrar(self) -> None:
        os.close(self._fd)


class EnlaceEmulado(_EnlaceBase):
    """Pantalla simulada: guarda las ordenes enviadas y permite inyectar toques, para las pruebas."""

    def __init__(self) -> None:
        super().__init__()
        self.enviadas: list[str] = []
        self._entrada = b""

    def _leer_bytes(self) -> bytes:
        datos, self._entrada = self._entrada, b""
        return datos

    def enviar(self, orden: str) -> None:
        self.enviadas.append(orden)

    def cerrar(self) -> None:
        pass

    # ---- ayudas de prueba -------------------------------------------------------------------------
    def inyectar(self, trama: bytes) -> None:
        self._entrada += trama + P.FIN

    def tocar(self, pagina: str, control: str) -> None:
        """Simula que el usuario suelta el boton ``control`` de la pagina ``pagina``."""
        codigo_pagina = P.CODIGO_PAGINA[pagina]
        codigo_control = next(c for c, n in P.CONTROLES[codigo_pagina].items() if n == control)
        self.inyectar(bytes([0x65, codigo_pagina, codigo_control, 0x00]))

    def pagina_cargada(self, pagina: str) -> None:
        self.inyectar(bytes([0x65, P.CODIGO_PAGINA[pagina], P.PAGINA_CARGADA, 0x00]))

    def encendida(self) -> None:
        self.inyectar(bytes([0x88]))

    def responder_numero(self, valor: int) -> None:
        self.inyectar(bytes([0x71]) + int(valor).to_bytes(4, "little", signed=True))

    def ordenes_con(self, texto: str) -> list[str]:
        return [o for o in self.enviadas if texto in o]
