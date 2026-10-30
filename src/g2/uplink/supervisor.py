"""Vigilancia de g2-core por g2-uplink (D-012, vigilancia cruzada).

systemd ya reinicia al nucleo cuando deja de dar su latido (30 s). Esto es la segunda red de seguridad, para lo que ese
watchdog no ve: un nucleo que sigue "vivo" para systemd pero no publica su estado, o que quedo parado. Si el estado del
nucleo falta o esta viejo ``CAIDO_MAX_S`` seguidos, pide a systemd reiniciarlo (la regla de polkit solo permite ``restart``).

Para no empeorar las cosas, con limites: al menos ``ENTRE_REINICIOS_S`` entre un intento y otro y a lo sumo ``MAX_POR_HORA``
por hora. Agotados, deja de intentar y lo dice (en uplink.json y a la plataforma): reiniciar sin fin no arregla lo que un
reinicio no arregla, y seria ruido sobre el equipo que mide el oxigeno.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Callable

from g2 import supervision

REGISTRO = logging.getLogger("g2.uplink")
UNIDAD = "g2-core.service"
CAIDO_MAX_S = 120.0                 # cuatro veces el watchdog del nucleo: si systemd no lo arreglo, hace falta ayuda
ENTRE_REINICIOS_S = 300.0
MAX_POR_HORA = 3
VENTANA_S = 3600.0


def reiniciar_unidad() -> tuple[bool, str]:
    """``systemctl restart g2-core`` (sin sudo: polkit lo permite al usuario pi). Siempre con tiempo maximo."""
    try:
        r = subprocess.run(["systemctl", "restart", UNIDAD], capture_output=True, text=True, timeout=45, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    return r.returncode == 0, (r.stderr or r.stdout or "").strip()[:200]


class SupervisorNucleo:
    def __init__(self, carpeta: Path | None, *, reiniciar: Callable[[], tuple[bool, str]] = reiniciar_unidad,
                 reloj: Callable[[], float] = time.time) -> None:
        self.carpeta, self._reiniciar, self._reloj = carpeta, reiniciar, reloj
        self._caido_desde: float | None = None
        self._intentos: list[float] = []              # instantes (monotonicos) de los reinicios pedidos, dentro de la ventana
        self._ultimo_s: float | None = None           # reloj de pared del ultimo reinicio pedido
        self._detalle: str | None = None
        self._avisado_agotado = False
        self._caido_s = 0.0

    def vigilar(self, nucleo_ok: bool, ahora: float) -> bool:
        """Una vuelta. Devuelve True si en esta pidio el reinicio."""
        self._intentos = [t for t in self._intentos if ahora - t < VENTANA_S]
        if nucleo_ok:
            if self._caido_desde is not None:
                REGISTRO.info("el nucleo volvio a responder tras %.0f s", ahora - self._caido_desde)
            self._caido_desde, self._caido_s, self._avisado_agotado = None, 0.0, False
            return False
        if self._caido_desde is None:
            self._caido_desde = ahora
        self._caido_s = ahora - self._caido_desde
        if self._caido_s < CAIDO_MAX_S:
            return False
        if self._intentos and ahora - self._intentos[-1] < ENTRE_REINICIOS_S:
            return False
        if len(self._intentos) >= MAX_POR_HORA:
            if not self._avisado_agotado:
                self._avisado_agotado = True
                REGISTRO.error("el nucleo sigue sin responder y ya se pidieron %d reinicios en la ultima hora: no se insiste",
                               len(self._intentos))
            return False
        self._intentos.append(ahora)
        self._ultimo_s = self._reloj()
        REGISTRO.warning("el nucleo no responde hace %.0f s: se pide reiniciarlo", self._caido_s)
        avisado = True
        if self.carpeta is not None:
            try:
                supervision.dejar_aviso(self.carpeta, self._caido_s, self._reloj)
            except OSError as error:
                avisado = False
                REGISTRO.warning("no se pudo dejar la nota del reinicio: %s", error)
        ok, detalle = self._reiniciar()
        self._detalle = None if ok else (detalle or "systemctl restart fallo")
        if not ok:
            REGISTRO.error("no se pudo reiniciar el nucleo: %s", self._detalle)
            if avisado and self.carpeta is not None:
                supervision.borrar_aviso(self.carpeta)      # no hubo reinicio: la nota no debe quedar para otro
        return ok

    @property
    def agotado(self) -> bool:
        return len(self._intentos) >= MAX_POR_HORA

    def estado(self) -> dict:
        return {"sin_respuesta_s": round(self._caido_s, 1) if self._caido_desde is not None else 0.0,
                "reinicios_ultima_hora": len(self._intentos), "ultimo_reinicio_s": self._ultimo_s,
                "agotado": self.agotado, "error": self._detalle}
