"""El ciclo de g2-core: leer, convertir, evaluar alarmas, guardar y publicar el estado.

Cada ``paso`` (unas dos veces por segundo):
  1. lee la tension de cada sensor habilitado y la convierte a % de O2 (``senal``);
  2. suma la muestra al acumulador del intervalo y se la pasa al motor de alarmas (``alarmas``);
  3. fija las salidas de los relevos segun las alarmas activas (``salidas``, D-033);
  4. si termino el intervalo de almacenamiento, guarda un registro por sensor (promedio, minimo,
     maximo) con la calibracion vigente;
  5. cada ``muestreo.intervalo_pantalla_s`` entrega el estado listo para mostrar (``estado_pantalla``).

El nucleo es el UNICO escritor de la base (D-005). Si una operacion falla de forma inesperada la
excepcion NO se oculta: el proceso termina y systemd lo reinicia (D-012); al volver, el motor retoma
las alarmas que habian quedado abiertas.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from g2 import __version__
from g2.almacenamiento.almacen import Almacen
from g2.nucleo import senal
from g2.nucleo.alarmas import ORIGEN, MotorAlarmas, Umbrales
from g2.nucleo.fuentes import FuenteTension
from g2.nucleo.salidas import SalidasAlarma, SalidasEmuladas


@dataclass
class SensorActivo:
    """Un sensor habilitado: lo que hace falta para leerlo y resumirlo."""

    id: int
    nombre: str
    canal: str
    mv_por_pct: float
    offset_pct: float
    acumulador: senal.Acumulador = field(default_factory=senal.Acumulador)


class Nucleo:
    """Une la fuente de tensiones, el motor de alarmas, las salidas y la base de datos."""

    def __init__(self, almacen: Almacen, fuente: FuenteTension, salidas: SalidasAlarma | None = None, *,
                 mono: Callable[[], float] = time.monotonic, version_sw: str = __version__) -> None:
        self.a = almacen
        self.fuente = fuente
        self.salidas = salidas or SalidasEmuladas()
        self._mono = mono
        self.version_sw = version_sw
        self.sensores: list[SensorActivo] = []
        self._todos: list[dict] = []                    # filas de la tabla sensor (tambien los apagados)
        self.motor: MotorAlarmas | None = None
        self.umbrales = Umbrales()
        self._valores: dict[int, float | None] = {}
        self._inicio_periodo_s = 0.0
        self._ultima_config_s = float("-inf")

    # ------------------------------------------------------------------ arranque y cierre
    def iniciar(self) -> bool:
        """Registra el arranque, retoma las alarmas abiertas y deja todo listo.

        Devuelve True si el cierre anterior fue ordenado. Si no lo fue, el arranque lleva la razon
        ``SYS_REINICIO_ANORMAL`` y se deja un evento (watchdog, corte de energia o falla del programa).
        """
        limpio = self.a.config_obtener("sistema.apagado_limpio") == "1"
        self.a.registrar_arranque(version_sw=self.version_sw,
                                  razon="SYS_ARRANQUE" if limpio else "SYS_REINICIO_ANORMAL")
        self.a.iniciar_sesion()
        if not limpio:
            self.a.registrar_evento("SYS_REINICIO_ANORMAL", ORIGEN,
                                    mensaje="El cierre anterior del núcleo no fue ordenado")
        if not self.a.reloj.confiable():
            self.a.registrar_evento("SYS_RELOJ_NO_CONFIABLE", ORIGEN)
        ahora = self._mono()
        self._cargar_sensores()
        self.motor = MotorAlarmas(self.a, {s["id"]: s["nombre"] for s in self._todos})
        retomadas = self.motor.recuperar(ahora)
        if retomadas:
            self.a.registrar_evento("SYS_AUTODIAGNOSTICO", ORIGEN,
                                    mensaje=f"Se retomaron {retomadas} alarma(s) abiertas tras el reinicio")
        self.umbrales = Umbrales.desde_almacen(self.a)
        self._ultima_config_s = ahora
        self._inicio_periodo_s = ahora
        return limpio

    def cerrar(self) -> None:
        """Cierre ordenado: guarda lo que haya del intervalo en curso y marca el apagado limpio."""
        self._guardar_periodo(self._mono())
        self.a.cerrar_limpio()

    def _cargar_sensores(self) -> None:
        """Lee de la base la lista de sensores y su calibracion vigente (conserva los acumuladores)."""
        self._todos = self.a.listar_sensores()
        previos = {s.id: s for s in self.sensores}
        nuevos: list[SensorActivo] = []
        for fila in self._todos:
            if not fila["habilitado"]:
                continue
            offset = self.a.db.execute(
                "SELECT COALESCE(offset_pct, 0.0) FROM calibracion WHERE sensor_id = ? AND vigente = 1",
                (fila["id"],)).fetchone()
            sensor = previos.get(fila["id"]) or SensorActivo(
                fila["id"], fila["nombre"], fila["canal"], fila["mv_por_pct"], 0.0)
            sensor.nombre, sensor.canal = fila["nombre"], fila["canal"]
            sensor.mv_por_pct = fila["mv_por_pct"]
            sensor.offset_pct = float(offset[0]) if offset else 0.0
            nuevos.append(sensor)
        self.sensores = nuevos

    # ------------------------------------------------------------------ un paso del ciclo
    def paso(self) -> list[str]:
        """Lee, evalua, actua y guarda si toca. Devuelve los cambios de alarmas de este paso."""
        assert self.motor is not None, "falta llamar a iniciar()"
        ahora = self._mono()
        intervalo_pantalla = float(self.a.config_tipada("muestreo.intervalo_pantalla_s"))
        if ahora - self._ultima_config_s >= intervalo_pantalla:      # la configuracion puede cambiar
            self.umbrales = Umbrales.desde_almacen(self.a)
            self._ultima_config_s = ahora
        valores: dict[int, float | None] = {}
        for sensor in self.sensores:
            tension = self.fuente.leer(sensor.canal)
            if tension is None:
                sensor.acumulador.agregar_sin_dato()
                valores[sensor.id] = None
            else:
                o2 = senal.tension_a_pct(tension, sensor.mv_por_pct, sensor.offset_pct)
                sensor.acumulador.agregar(o2, tension * 1000.0)
                valores[sensor.id] = o2
        self._valores = valores
        cambios = self.motor.evaluar(valores, self.umbrales, ahora)
        self.salidas.fijar(bajo=self.motor.rele_bajo(), alto=self.motor.rele_alto())
        if ahora - self._inicio_periodo_s >= float(self.a.config_tipada("muestreo.intervalo_guardado_s")):
            self._guardar_periodo(ahora)
            self._cargar_sensores()                   # tambien recoge cambios de habilitado o de calibracion
            self.motor.actualizar_sensores({s["id"]: s["nombre"] for s in self._todos})
        return cambios

    def _guardar_periodo(self, ahora_s: float) -> None:
        periodo_ms = int((ahora_s - self._inicio_periodo_s) * 1000)
        self._inicio_periodo_s = ahora_s
        if periodo_ms <= 0:
            return
        for sensor in self.sensores:
            if sensor.acumulador.n_intentos == 0:
                continue                              # no hubo ni intentos (cierre justo tras arrancar)
            r = sensor.acumulador.cerrar()
            self.a.insertar_lectura(sensor_id=sensor.id, periodo_ms=periodo_ms, n_muestras=r.n_muestras,
                                    o2_prom=r.o2_prom, o2_min=r.o2_min, o2_max=r.o2_max,
                                    mv_prom=r.mv_prom, calidad=r.calidad)

    # ------------------------------------------------------------------ interfaz para la pantalla
    def acusar(self, actor: str) -> int:
        """Boton Acusar de la pantalla (o comando de la plataforma). Devuelve las alarmas acusadas."""
        assert self.motor is not None, "falta llamar a iniciar()"
        return self.motor.acusar(actor, self._mono(), self.umbrales)

    def estado_pantalla(self) -> dict:
        """Todo lo que g2-ui necesita para pintar la pantalla y ordenar el sonido (ver
        ESPECIFICACION_HMI.md). ``o2`` es la ultima muestra; ``parpadeo`` es True mientras haya una
        alarma sin acusar (la pantalla alterna el recuadro); ``sonar`` es True cuando debe sonar."""
        assert self.motor is not None, "falta llamar a iniciar()"
        habilitados = {s.id for s in self.sensores}
        sensores = []
        for fila in self._todos:
            sid = fila["id"]
            if sid not in habilitados:
                estado, acusada, o2 = "APAGADO", False, None
            else:
                estado, acusada = self.motor.estado_sensor(sid)
                o2 = self._valores.get(sid)
            sensores.append({"id": sid, "nombre": fila["nombre"], "o2": o2,
                             "texto_o2": "--.-" if o2 is None else f"{o2:.1f}",
                             "estado": estado, "acusada": acusada})
        ahora = self._mono()
        return {"sensores": sensores, "aviso": self.motor.texto_aviso(),
                "sonar": self.motor.debe_sonar(ahora), "parpadeo": self.motor.hay_sin_acusar(),
                "rele_bajo": self.motor.rele_bajo(), "rele_alto": self.motor.rele_alto()}

    # ------------------------------------------------------------------ ciclo continuo
    def ejecutar(self, detener: Callable[[], bool], *, periodo_s: float = 0.5,
                 dormir: Callable[[float], None] = time.sleep,
                 al_publicar: Callable[[dict], None] | None = None) -> None:
        """Repite ``paso`` hasta que ``detener()`` sea True. ``al_publicar`` recibe el estado de la
        pantalla cada ``muestreo.intervalo_pantalla_s``."""
        ultima_publicacion = float("-inf")
        while not detener():
            inicio = self._mono()
            self.paso()
            intervalo = float(self.a.config_tipada("muestreo.intervalo_pantalla_s"))
            if al_publicar is not None and inicio - ultima_publicacion >= intervalo:
                ultima_publicacion = inicio
                al_publicar(self.estado_pantalla())
            dormir(max(0.0, periodo_s - (self._mono() - inicio)))
