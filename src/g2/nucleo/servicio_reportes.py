"""Servicio de reportes del nucleo: lanza el reporte en un PROCESO aparte y sigue su avance (D-044).

Por que un proceso y no un hilo: dibujar cientos de paginas es trabajo de CPU en Python; en el mismo proceso del nucleo le
quitaria tiempo a la lectura de los sensores y al latido del watchdog (los hilos de Python comparten el GIL). En un proceso
con prioridad baja, el nucleo ni se entera, y si el reporte falla o se cancela, solo termina ese proceso.

El nucleo es el unico que escribe en la base (D-005): este servicio NUNCA la toca; deja el RESULTADO para que el nucleo lo
recoja y lo registre como evento. El proceso hijo lee la base en solo lectura y obtiene solo el nombre del equipo (la
contrasena del PDF) de ella: nunca viaja por la linea de comandos.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

REGISTRO = logging.getLogger("g2.reportes")
TIEMPO_MAXIMO_S = 900.0                          # un reporte de una semana tarda ~30 s; mas de 15 min es que algo se colgo
ESPERA_TERMINAR_S = 8.0                          # lo que se espera a que el proceso termine tras pedirselo antes de matarlo


def _lanzar_proceso(ruta_bd: Path, desde: str, hasta: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", "g2.reportes", "--bd", str(ruta_bd), "--desde", desde, "--hasta", hasta],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1)


class ServicioReportes:
    def __init__(self, ruta_bd: Path, *, lanzar: Callable[[Path, str, str], subprocess.Popen] | None = None,
                 mono: Callable[[], float] = time.monotonic, tiempo_maximo_s: float = TIEMPO_MAXIMO_S) -> None:
        self.ruta_bd = Path(ruta_bd)
        self._lanzar = lanzar or _lanzar_proceso
        self._mono = mono
        self.tiempo_maximo_s = tiempo_maximo_s
        self._cerrojo = threading.Lock()
        self._proceso: subprocess.Popen | None = None
        self._hilo: threading.Thread | None = None
        self._inicio = 0.0
        self._cancelado = False
        self._avance: dict = {"fase": "", "progreso": 0, "mensaje": ""}
        self._rango: tuple[str, str] | None = None
        self._resultado: dict | None = None                # lo que espera recoger el nucleo
        self._ultimo: dict | None = None                    # lo que se muestra en la pantalla
        self._numero = 0

    # ------------------------------------------------------------------ lo que usa el nucleo
    @property
    def en_curso(self) -> bool:
        with self._cerrojo:
            return self._proceso is not None

    def iniciar(self, desde: str, hasta: str) -> bool:
        """Lanza el reporte de ``desde`` a ``hasta`` (``AAAA-MM-DD``). False si ya hay uno en curso."""
        with self._cerrojo:
            if self._proceso is not None:
                return False
            self._proceso = self._lanzar(self.ruta_bd, desde, hasta)
            self._rango, self._cancelado, self._inicio = (desde, hasta), False, self._mono()
            self._avance = {"fase": "usb", "progreso": 0, "mensaje": "Iniciando..."}
            self._hilo = threading.Thread(target=self._leer, args=(self._proceso,), name="g2-reporte", daemon=True)
            self._hilo.start()
        return True

    def cancelar(self) -> bool:
        """Pide al proceso que pare (SIGTERM: borra lo que haya dejado a medias). False si no hay nada en curso."""
        with self._cerrojo:
            proceso = self._proceso
            if proceso is None:
                return False
            self._cancelado = True
        try:
            proceso.terminate()
        except OSError:
            pass
        return True

    def vigilar(self) -> None:
        """Si el reporte lleva demasiado, lo mata (se llama en cada vuelta del nucleo; es barato)."""
        with self._cerrojo:
            proceso, vencido = self._proceso, self._mono() - self._inicio > self.tiempo_maximo_s
        if proceso is not None and vencido and proceso.poll() is None:
            REGISTRO.error("el reporte lleva mas de %d s: se detiene", self.tiempo_maximo_s)
            proceso.kill()

    def detener(self) -> None:
        """Cierre del nucleo: no se deja un reporte corriendo."""
        proceso = self._proceso
        if proceso is not None and proceso.poll() is None:
            self._cancelado = True
            proceso.terminate()
            try:
                proceso.wait(timeout=ESPERA_TERMINAR_S)
            except subprocess.TimeoutExpired:
                proceso.kill()
        if self._hilo is not None:
            self._hilo.join(timeout=2)

    def resultado_pendiente(self) -> dict | None:
        """El resultado del ultimo reporte terminado, una sola vez (despues se borra)."""
        with self._cerrojo:
            resultado, self._resultado = self._resultado, None
        return resultado

    def estado(self) -> dict:
        """Foto para publicar a la interfaz."""
        with self._cerrojo:
            en_curso = self._proceso is not None
            return {"en_curso": en_curso, **(self._avance if en_curso else {}),
                    "desde": self._rango[0] if self._rango else None, "hasta": self._rango[1] if self._rango else None,
                    "ultimo": self._ultimo}

    # ------------------------------------------------------------------ el hilo que lee al proceso
    def _leer(self, proceso: subprocess.Popen) -> None:
        final: dict | None = None
        try:
            for linea in proceso.stdout:                                  # type: ignore[union-attr]
                linea = linea.strip()
                try:
                    aviso = json.loads(linea)
                except ValueError:
                    if linea:
                        REGISTRO.info("reporte: %s", linea[:200])
                    continue
                if not isinstance(aviso, dict):
                    continue
                if aviso.get("fase") in ("resultado", "error", "cancelado"):
                    final = aviso
                else:
                    with self._cerrojo:
                        self._avance = {"fase": str(aviso.get("fase", "")), "progreso": int(aviso.get("progreso", 0)),
                                        "mensaje": str(aviso.get("mensaje", ""))}
        except (OSError, ValueError):
            pass
        codigo = proceso.wait()
        self._terminar(final, codigo)

    def _terminar(self, final: dict | None, codigo: int) -> None:
        with self._cerrojo:
            desde, hasta = self._rango or ("", "")
            cancelado = self._cancelado or (final or {}).get("fase") == "cancelado"
            if final is not None and final.get("fase") == "resultado":
                resultado = {"ok": True, "desde": desde, "hasta": hasta, **final["resultado"],
                             "mensaje": "Reporte copiado a la memoria USB"}
            elif cancelado:
                resultado = {"ok": False, "cancelado": True, "desde": desde, "hasta": hasta,
                             "mensaje": "Reporte cancelado"}
            else:
                motivo = (final or {}).get("mensaje") or f"El reporte terminó con error (código {codigo})"
                resultado = {"ok": False, "cancelado": False, "desde": desde, "hasta": hasta, "mensaje": str(motivo)}
            self._numero += 1
            resultado["numero"] = self._numero
            self._resultado, self._ultimo = dict(resultado), dict(resultado)
            self._proceso = None
