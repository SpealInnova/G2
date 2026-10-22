"""Aviso a systemd (``sd_notify``) sin dependencias: listo, latido del watchdog, estado y cierre.

systemd arranca el nucleo como ``Type=notify``: considera el servicio "listo" cuando el programa lo
avisa (``READY=1``), y con ``WatchdogSec=`` lo REINICIA si deja de recibir el latido (``WATCHDOG=1``)
dentro de ese plazo. El latido se envia solo despues de cada paso completo del ciclo (lectura,
alarmas y base de datos): es un watchdog **por progreso** (D-012), no por "el proceso existe". Si el
ADC o la base se atascan, el ciclo no avanza, el latido se detiene y systemd lo reinicia.

El aviso se manda al socket que indica la variable de entorno ``NOTIFY_SOCKET``; si no existe
(en un PC, en las pruebas o con la herramienta de banco) todo esto no hace nada.
"""

from __future__ import annotations

import os
import socket
import time

_ultimo_latido = float("-inf")
_ultimo_estado = float("-inf")
LATIDO_MIN_S = 1.0               # a lo sumo un latido por segundo
ESTADO_MIN_S = 5.0               # y una actualizacion de STATUS cada 5 s


def _enviar(texto: str) -> bool:
    """Manda ``texto`` al socket de systemd. False si no hay socket o falla el envio."""
    ruta = os.environ.get("NOTIFY_SOCKET")
    if not ruta or not hasattr(socket, "AF_UNIX"):
        return False
    if ruta.startswith("@"):                     # socket "abstracto" de Linux
        ruta = "\0" + ruta[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(ruta)
            s.sendall(texto.encode("utf-8"))
        return True
    except OSError:
        return False


def listo(estado: str = "") -> bool:
    """``READY=1``: el servicio terminó de arrancar."""
    return _enviar("READY=1" + (f"\nSTATUS={estado}" if estado else ""))


def latido(ahora: float | None = None) -> bool:
    """``WATCHDOG=1``. Llamar despues de cada paso completo; limita la frecuencia a ``LATIDO_MIN_S``."""
    global _ultimo_latido
    ahora = time.monotonic() if ahora is None else ahora
    if ahora - _ultimo_latido < LATIDO_MIN_S:
        return False
    _ultimo_latido = ahora
    return _enviar("WATCHDOG=1")


def estado(texto: str, ahora: float | None = None) -> bool:
    """``STATUS=``: lo que muestra ``systemctl status`` (limitado a una vez cada ``ESTADO_MIN_S``)."""
    global _ultimo_estado
    ahora = time.monotonic() if ahora is None else ahora
    if ahora - _ultimo_estado < ESTADO_MIN_S:
        return False
    _ultimo_estado = ahora
    return _enviar(f"STATUS={texto}")


def deteniendo() -> bool:
    """``STOPPING=1``: el cierre ordenado empezó (así systemd no lo toma por un bloqueo)."""
    return _enviar("STOPPING=1")


def plazo_watchdog_s() -> float | None:
    """Plazo del watchdog en segundos si systemd lo configuro (``WATCHDOG_USEC``), si no, None."""
    valor = os.environ.get("WATCHDOG_USEC")
    return int(valor) / 1_000_000 if valor and valor.isdigit() else None
