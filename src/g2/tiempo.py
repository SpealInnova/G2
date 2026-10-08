"""Relojes de G2: hora UTC, tiempo monotonico y si la hora es confiable (D-016, esquema).

Todo registro de la base lleva tres datos de tiempo (ver 001_esquema_inicial.sql):
  * ``ts_ms``       hora UTC en milisegundos (epoch);
  * ``ts_confiable`` 1 si el reloj estaba sincronizado al tomar la hora, 0 si no;
  * ``mono_ms``     milisegundos del reloj monotonico (en Linux, desde el arranque del
                    sistema), que nunca retrocede y sirve para corregir la hora despues.

La Raspberry Pi 3 no tiene reloj de tiempo real: al arrancar sin red su hora puede ser
falsa hasta que se sincroniza por NTP. Por eso se registra si es confiable.
"""

from __future__ import annotations

import subprocess
import time


class RelojSistema:
    """Reloj real. ``confiable()`` consulta a systemd si el reloj esta sincronizado."""

    def __init__(self, vigencia_s: float = 30.0) -> None:
        self._vigencia = vigencia_s
        self._ultima_consulta = float("-inf")
        self._valor = True

    def ahora_ms(self) -> int:
        return time.time_ns() // 1_000_000

    def mono_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000

    def confiable(self) -> bool:
        """True si la hora esta sincronizada. En una maquina sin ``timedatectl`` (un PC de
        desarrollo) se supone que si. La consulta se repite cada ``vigencia_s`` segundos
        y tiene tiempo maximo, para no bloquear a quien la llama."""
        ahora = time.monotonic()
        if ahora - self._ultima_consulta >= self._vigencia:
            self._ultima_consulta = ahora
            try:
                salida = subprocess.run(
                    ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                    capture_output=True, text=True, timeout=3, check=False)
                if salida.returncode == 0:
                    self._valor = salida.stdout.strip().lower() == "yes"
            except (OSError, subprocess.SubprocessError):
                pass                    # sin timedatectl: se conserva el valor anterior
        return self._valor


class RelojPrueba:
    """Reloj controlable para pruebas."""

    def __init__(self, ahora_ms: int = 1_700_000_000_000, mono_ms: int = 10_000,
                 confiable: bool = True) -> None:
        self._ahora, self._mono, self._confiable = ahora_ms, mono_ms, confiable

    def ahora_ms(self) -> int:
        return self._ahora

    def mono_ms(self) -> int:
        return self._mono

    def confiable(self) -> bool:
        return self._confiable

    def avanzar(self, ms: int) -> None:
        self._ahora += ms
        self._mono += ms

    def fijar_confiable(self, valor: bool) -> None:
        self._confiable = valor
