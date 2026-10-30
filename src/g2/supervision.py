"""Aviso de reinicio entre servicios (D-012): g2-uplink reinicia a g2-core y deja una nota para que el nucleo la registre.

g2-uplink no escribe en la base (D-009), asi que no puede anotar por si mismo que reinicio al nucleo. Deja la nota
``reinicio_nucleo.json`` en la carpeta compartida (``/run/g2``) y g2-core la lee al arrancar: el arranque queda con la razon
``SVC_BLOQUEO_DETECTADO`` y un evento que dice cuanto tiempo estuvo sin responder. Una nota vieja se ignora: no debe
adjudicarse a un reinicio que no tuvo nada que ver.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

NOMBRE_AVISO = "reinicio_nucleo.json"
EDAD_MAX_AVISO_S = 600.0


def dejar_aviso(carpeta: Path, caido_s: float, reloj=time.time) -> None:
    """Deja la nota (antes de pedir el reinicio). Puede fallar con OSError: quien llama decide."""
    from g2.ipc import _escribir_atomico
    datos = {"creado_s": reloj(), "caido_s": round(caido_s, 1), "origen": "g2-uplink"}
    _escribir_atomico(Path(carpeta) / NOMBRE_AVISO, json.dumps(datos).encode("utf-8"))


def borrar_aviso(carpeta: Path) -> None:
    try:
        (Path(carpeta) / NOMBRE_AVISO).unlink()
    except OSError:
        pass


def tomar_aviso(carpeta: Path | None, reloj=time.time) -> str | None:
    """Lee y borra la nota. Devuelve el mensaje para el evento, o None si no hay nota (o es vieja o ilegible)."""
    if carpeta is None:
        return None
    ruta = Path(carpeta) / NOMBRE_AVISO
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        creado, caido = float(datos["creado_s"]), float(datos["caido_s"])
    except (OSError, ValueError, KeyError, TypeError):
        borrar_aviso(carpeta)
        return None
    borrar_aviso(carpeta)
    if not 0 <= reloj() - creado <= EDAD_MAX_AVISO_S:
        return None
    return f"g2-uplink reinició el núcleo: no respondió durante {caido:.0f} s"
