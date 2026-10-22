"""Servicio de red del nucleo: mide la red y ejecuta los cambios FUERA del ciclo principal (D-040).

Cambiar de red puede tardar uno o dos minutos (activar el perfil, comprobar internet y, si falla, volver a la red
anterior), y ``nmcli`` tambien tarda en consultarse. El ciclo del nucleo no puede esperar eso: sigue leyendo los
sensores, evaluando alarmas y dando su latido al watchdog. Por eso este servicio corre en un HILO propio:

  * cada ``intervalo_s`` toma una foto del estado de la red y de las redes cercanas;
  * ejecuta, de una en una, las peticiones de cambio de red y de busqueda que le deja el nucleo;
  * deja el RESULTADO de cada cambio para que el nucleo lo recoja y lo escriba en la base: el nucleo es el unico que
    escribe (D-005), asi que este hilo NUNCA toca la base de datos.

La contrasena solo vive en la peticion mientras se ejecuta y se borra al terminar.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from g2.red.gestor import GestorRed, ResultadoRed

REGISTRO = logging.getLogger("g2.red")


@dataclass
class _Peticion:
    ssid: str
    contrasena: str
    oculta: bool


class ServicioRed:
    def __init__(self, gestor: GestorRed, *, intervalo_s: float = 10.0, intervalo_redes_s: float = 30.0,
                 mono=time.monotonic) -> None:
        self.gestor = gestor
        self.intervalo_s, self.intervalo_redes_s = intervalo_s, intervalo_redes_s
        self._mono = mono
        self._cerrojo = threading.Lock()
        self._despertar = threading.Event()
        self._hilo: threading.Thread | None = None
        self._parar = False
        self._peticion: _Peticion | None = None
        self._buscar = False
        self._en_curso: str | None = None                       # nombre de la red que se esta intentando
        self._resultado: tuple[str, ResultadoRed] | None = None
        self._ultimo_resultado: dict | None = None
        self._estado: dict | None = None
        self._redes: list[dict] = []
        self._t_estado = self._t_redes = float("-inf")

    # ------------------------------------------------------------------ lo que usa el nucleo
    def iniciar(self) -> None:
        self._hilo = threading.Thread(target=self._bucle, name="g2-red", daemon=True)
        self._hilo.start()

    def detener(self) -> None:
        self._parar = True
        self._despertar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=5)

    def solicitar_cambio(self, ssid: str, contrasena: str, oculta: bool = False) -> bool:
        """Pide cambiar de red. False si ya hay un cambio en curso o pendiente (solo se hace uno a la vez)."""
        with self._cerrojo:
            if self._en_curso is not None or self._peticion is not None:
                return False
            self._peticion = _Peticion(ssid, contrasena, oculta)
            self._en_curso = ssid                               # la interfaz ya puede mostrar "conectando"
        self._despertar.set()
        return True

    def solicitar_busqueda(self) -> None:
        self._buscar = True
        self._despertar.set()

    def resultado_pendiente(self) -> tuple[str, ResultadoRed] | None:
        """``(ssid, resultado)`` del ultimo cambio terminado, una sola vez (despues se borra)."""
        with self._cerrojo:
            resultado, self._resultado = self._resultado, None
        return resultado

    def estado(self) -> dict:
        """Foto para publicar a la interfaz: la red actual, las redes cercanas y el estado del cambio."""
        with self._cerrojo:
            return {"red": self._estado, "redes": list(self._redes),
                    "cambio": {"en_curso": self._en_curso, "ultimo": self._ultimo_resultado}}

    # ------------------------------------------------------------------ el hilo
    def _bucle(self) -> None:
        while not self._parar:
            self.ciclo()
            self._despertar.wait(timeout=1.0)
            self._despertar.clear()

    def ciclo(self) -> None:
        """Una vuelta del hilo (publica para poder probarse sin hilos): atiende lo pendiente y refresca si toca."""
        with self._cerrojo:
            peticion, self._peticion = self._peticion, None
            buscar, self._buscar = self._buscar, False
        if peticion is not None:
            self._ejecutar_cambio(peticion)
            self._t_estado = self._t_redes = float("-inf")           # tras un cambio, refrescar ya
        elif buscar:
            self._refrescar_redes(buscar_de_nuevo=True)
        ahora = self._mono()
        if ahora - self._t_estado >= self.intervalo_s:
            self._t_estado = ahora
            try:
                foto = self.gestor.estado().como_diccionario()
            except Exception:                                         # nada del gestor debe tumbar el hilo
                REGISTRO.exception("no se pudo leer el estado de la red")
                foto = None
            with self._cerrojo:
                self._estado = foto
        if ahora - self._t_redes >= self.intervalo_redes_s:
            self._refrescar_redes(buscar_de_nuevo=False)

    def _refrescar_redes(self, buscar_de_nuevo: bool) -> None:
        self._t_redes = self._mono()
        try:
            redes = [{"ssid": r.ssid, "senal": r.senal, "seguridad": r.seguridad}
                     for r in self.gestor.escanear(buscar_de_nuevo)]
        except Exception:
            REGISTRO.exception("no se pudo buscar redes")
            return
        with self._cerrojo:
            self._redes = redes

    def _ejecutar_cambio(self, peticion: _Peticion) -> None:
        try:
            resultado = self.gestor.configurar(peticion.ssid, peticion.contrasena, peticion.oculta)
        except Exception:
            REGISTRO.exception("fallo inesperado al cambiar de red")
            resultado = ResultadoRed(False, "Error inesperado al cambiar de red", motivo="error")
        finally:
            peticion.contrasena = ""                                  # la contrasena ya no hace falta
        with self._cerrojo:
            self._resultado = (peticion.ssid, resultado)
            self._ultimo_resultado = {"ssid": peticion.ssid, "ok": resultado.ok, "mensaje": resultado.mensaje,
                                      "revertida": resultado.revertida, "sin_internet": resultado.sin_internet,
                                      "motivo": resultado.motivo}
            self._en_curso = None
