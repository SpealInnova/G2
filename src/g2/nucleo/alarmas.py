"""Motor de alarmas por sensor (D-031, D-032, D-033).

Cada sensor evalua POR SEPARADO sus dos alarmas de oxigeno, ``ALM_O2_BAJO`` y ``ALM_O2_ALTO``, mas
``ALM_SENSOR_INVALIDO`` si deja de entregar una señal valida. Aparte hay una alarma del sistema,
``ALM_SENSORES_DISCREPANTES``, entre los dos sensores.

Cada condicion pasa por tres estados::

    INACTIVA --(entra la condicion)--> PENDIENTE --(se mantiene ``retardo_s``)--> ACTIVA
        ^                                  |                                        |
        +------(se pierde antes)-----------+          (sale de la zona + histeresis)+--> cierra

* **Retardo** (``alarma.o2_retardo_s``): la condicion debe mantenerse seguida ese tiempo; si se
  pierde antes, empieza de cero. Evita alarmas por un pico.
* **Histeresis** (``alarma.o2_histeresis_pct``): la alarma baja se cierra cuando el valor supera el
  minimo MAS la histeresis; la alta, cuando baja del maximo MENOS la histeresis. Evita que oscile en
  el limite.
* **Acuse** (D-031): acusar silencia el SONIDO ``alarma.acuse_silencio_s`` (120 s por defecto), no
  cierra la alarma ni apaga los relevos. Si la alarma sigue activa al vencer el silencio, el sonido
  vuelve. Una alarma NUEVA suena al instante aunque otras ya estuvieran acusadas.
* **Relevos** (D-033): el relevo de oxigeno bajo se activa mientras CUALQUIER sensor tenga
  ``ALM_O2_BAJO`` activa, y el de oxigeno alto con ``ALM_O2_ALTO``; no dependen del acuse.

El motor no mide el tiempo por su cuenta: recibe ``ahora_s`` (segundos monotonicos) en cada
llamada, asi las pruebas son exactas y no dependen del reloj real. Todo cambio de estado queda en
la base por medio del ``Almacen`` (alarma, sus revisiones y la cadena de auditoria).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from g2.almacenamiento.almacen import Almacen

INACTIVA, PENDIENTE, ACTIVA = "inactiva", "pendiente", "activa"

ALM_BAJO = "ALM_O2_BAJO"
ALM_ALTO = "ALM_O2_ALTO"
ALM_INVALIDO = "ALM_SENSOR_INVALIDO"
ALM_DISCREPANCIA = "ALM_SENSORES_DISCREPANTES"

MAX_LARGO_AVISO = 60               # ``txt_maxl`` del componente ``aviso`` de la pantalla
# El valor extremo de una alarma (``valor_pico``) solo se reescribe en la base cuando se mueve al menos esto
# (en % de O2, o en puntos de diferencia para la discrepancia), y siempre al cerrar la alarma o al apagar el
# nucleo. Sin este umbral, el ruido del sensor (milesimas de %) hacia una revision, un eslabon de auditoria
# y una entrada de la cola de envio por cada nuevo minimo: 191 revisiones en una sola alarma (prueba del
# 2026-10-21), con desgaste de la tarjeta SD.
PICO_MIN_CAMBIO = 0.5
ORIGEN = "g2-core"


@dataclass(frozen=True)
class Umbrales:
    """Valores de configuracion que usa el motor (claves ``alarma.*``)."""

    bajo_pct: float = 20.0
    alto_pct: float = 92.0
    retardo_s: float = 10.0
    histeresis_pct: float = 0.5
    discrepancia_pct: float = 0.5
    acuse_silencio_s: float = 120.0

    @classmethod
    def desde_almacen(cls, almacen: Almacen) -> "Umbrales":
        leer = almacen.config_tipada
        return cls(bajo_pct=float(leer("alarma.o2_bajo_pct")), alto_pct=float(leer("alarma.o2_alto_pct")),
                   retardo_s=float(leer("alarma.o2_retardo_s")),
                   histeresis_pct=float(leer("alarma.o2_histeresis_pct")),
                   discrepancia_pct=float(leer("alarma.discrepancia_pct")),
                   acuse_silencio_s=float(leer("alarma.acuse_silencio_s")))


class Condicion:
    """Una condicion con retardo e histeresis (el estado de UNA alarma de UN sensor)."""

    def __init__(self, codigo: str, sensor_id: int | None) -> None:
        self.codigo = codigo
        self.sensor_id = sensor_id
        self.estado = INACTIVA
        self.desde_s = 0.0
        self.alarma_id: int | None = None
        self.acusada = False
        self.pico: float | None = None            # el extremo real, al dia en memoria
        self.pico_guardado: float | None = None   # el ultimo extremo escrito en la base

    def reiniciar(self) -> None:
        self.estado, self.alarma_id, self.acusada = INACTIVA, None, False
        self.pico = self.pico_guardado = None

    def actualizar(self, entra: bool, sale: bool, retardo_s: float, ahora_s: float) -> str | None:
        """Avanza el estado. ``entra``: el valor esta en la zona de alarma; ``sale``: ya salio de
        ella con la histeresis. Devuelve ``'activar'``, ``'cerrar'`` o ``None``."""
        if self.estado == INACTIVA:
            if entra:
                if retardo_s <= 0:
                    self.estado = ACTIVA
                    return "activar"
                self.estado, self.desde_s = PENDIENTE, ahora_s
        elif self.estado == PENDIENTE:
            if not entra:
                self.estado = INACTIVA                       # se perdio antes del retardo
            elif ahora_s - self.desde_s >= retardo_s:
                self.estado = ACTIVA
                return "activar"
        elif self.estado == ACTIVA and sale:
            self.estado = INACTIVA
            return "cerrar"
        return None


class MotorAlarmas:
    """Evalua las alarmas de todos los sensores y lleva su estado, el acuse y el sonido."""

    def __init__(self, almacen: Almacen, nombres_sensores: dict[int, str]) -> None:
        self.a = almacen
        self.nombres = dict(nombres_sensores)
        self._bajo: dict[int, Condicion] = {}
        self._alto: dict[int, Condicion] = {}
        self._invalido: dict[int, Condicion] = {}
        self._discrepancia = Condicion(ALM_DISCREPANCIA, None)
        self._ultimo: dict[int, float | None] = {}
        self._silencio_hasta_s = float("-inf")

    # ------------------------------------------------------------------ condiciones
    def _cond(self, grupo: dict[int, Condicion], codigo: str, sensor_id: int) -> Condicion:
        if sensor_id not in grupo:
            grupo[sensor_id] = Condicion(codigo, sensor_id)
        return grupo[sensor_id]

    def _todas(self) -> Iterable[Condicion]:
        yield from self._bajo.values()
        yield from self._alto.values()
        yield from self._invalido.values()
        yield self._discrepancia

    def actualizar_sensores(self, nombres: dict[int, str]) -> None:
        """Cambia los nombres conocidos (por ejemplo, si se da de alta otro sensor)."""
        self.nombres.update(nombres)

    def _nombre(self, sensor_id: int) -> str:
        return self.nombres.get(sensor_id, f"sensor {sensor_id}")

    # ------------------------------------------------------------------ arranque
    def recuperar(self, ahora_s: float) -> int:
        """Retoma las alarmas que quedaron abiertas en la base si el nucleo se reinicio, para no
        duplicarlas ni dejarlas abiertas para siempre. Las ya acusadas vuelven a sonar (el silencio
        no se conserva tras un reinicio). Devuelve cuantas retomo."""
        n = 0
        for sensor_id in self.nombres:
            for grupo, codigo in ((self._bajo, ALM_BAJO), (self._alto, ALM_ALTO),
                                  (self._invalido, ALM_INVALIDO)):
                n += self._retomar(self._cond(grupo, codigo, sensor_id))
        n += self._retomar(self._discrepancia)
        self._silencio_hasta_s = ahora_s
        return n

    def _retomar(self, cond: Condicion) -> int:
        alarma_id = self.a.alarma_activa(cond.codigo, cond.sensor_id)
        if alarma_id is None:
            return 0
        fila = self.a.db.execute("SELECT estado, valor_pico FROM alarma WHERE id = ?",
                                 (alarma_id,)).fetchone()
        cond.estado, cond.alarma_id = ACTIVA, alarma_id
        cond.acusada = fila["estado"] == "acusada"
        cond.pico = cond.pico_guardado = fila["valor_pico"]
        return 1

    def guardar_picos(self) -> None:
        """Escribe en la base los extremos que aun no se han guardado (cierre ordenado del nucleo)."""
        for cond in self._todas():
            if cond.estado == ACTIVA:
                self._guardar_pico(cond)

    def _guardar_pico(self, cond: Condicion) -> None:
        if cond.alarma_id is not None and cond.pico is not None and cond.pico != cond.pico_guardado:
            self.a.actualizar_pico(cond.alarma_id, cond.pico)
            cond.pico_guardado = cond.pico

    # ------------------------------------------------------------------ evaluacion
    def evaluar(self, valores: dict[int, float | None], umbrales: Umbrales, ahora_s: float) -> list[str]:
        """Evalua un instante. ``valores``: % de O2 de cada sensor HABILITADO, o ``None`` si no hay
        señal valida. Devuelve un texto por cada alarma que se abrio o se cerro (para el registro
        de actividad)."""
        cambios: list[str] = []
        for sensor_id in {c.sensor_id for c in self._todas() if c.sensor_id is not None} - set(valores):
            self._soltar_sensor(sensor_id, cambios)
        for sensor_id, o2 in valores.items():
            self._ultimo[sensor_id] = o2
            nombre = self._nombre(sensor_id)
            self._avanzar(self._cond(self._invalido, ALM_INVALIDO, sensor_id),
                          entra=o2 is None, sale=o2 is not None, retardo_s=umbrales.retardo_s,
                          ahora_s=ahora_s, valor=None, umbral=None, modo_pico=None,
                          mensaje=f"{nombre} sin señal válida", cambios=cambios)
            bajo = self._cond(self._bajo, ALM_BAJO, sensor_id)
            alto = self._cond(self._alto, ALM_ALTO, sensor_id)
            if o2 is None:                       # sin dato no hay evidencia: lo pendiente se descarta
                for c in (bajo, alto):
                    if c.estado == PENDIENTE:
                        c.reiniciar()
                continue
            self._avanzar(bajo, entra=o2 < umbrales.bajo_pct,
                          sale=o2 >= umbrales.bajo_pct + umbrales.histeresis_pct,
                          retardo_s=umbrales.retardo_s, ahora_s=ahora_s, valor=o2,
                          umbral=umbrales.bajo_pct, modo_pico="min", cambios=cambios,
                          mensaje=f"Oxígeno bajo en {nombre}: {o2:.1f} % (mínimo {umbrales.bajo_pct:.1f} %)")
            self._avanzar(alto, entra=o2 > umbrales.alto_pct,
                          sale=o2 <= umbrales.alto_pct - umbrales.histeresis_pct,
                          retardo_s=umbrales.retardo_s, ahora_s=ahora_s, valor=o2,
                          umbral=umbrales.alto_pct, modo_pico="max", cambios=cambios,
                          mensaje=f"Oxígeno alto en {nombre}: {o2:.1f} % (máximo {umbrales.alto_pct:.1f} %)")
        self._evaluar_discrepancia(valores, umbrales, ahora_s, cambios)
        return cambios

    def _evaluar_discrepancia(self, valores, umbrales: Umbrales, ahora_s: float, cambios) -> None:
        validos = [v for v in valores.values() if v is not None]
        if len(validos) >= 2:
            diferencia = max(validos) - min(validos)
            entra = diferencia > umbrales.discrepancia_pct
            sale = diferencia <= umbrales.discrepancia_pct / 2      # histeresis: la mitad del limite
        else:                                    # con un solo sensor no hay con que comparar
            diferencia, entra, sale = None, False, True
        self._avanzar(self._discrepancia, entra=entra, sale=sale, retardo_s=umbrales.retardo_s,
                      ahora_s=ahora_s, valor=diferencia, umbral=umbrales.discrepancia_pct,
                      modo_pico="max", cambios=cambios,
                      mensaje=f"Los sensores difieren {diferencia or 0:.2f} % "
                              f"(límite {umbrales.discrepancia_pct:.2f} %)")

    def _soltar_sensor(self, sensor_id: int, cambios: list[str]) -> None:
        """El sensor se deshabilito: sus alarmas abiertas se cierran y su estado se descarta."""
        for grupo in (self._bajo, self._alto, self._invalido):
            cond = grupo.get(sensor_id)
            if cond is None:
                continue
            if cond.estado == ACTIVA and cond.alarma_id is not None:
                self._guardar_pico(cond)
                self.a.cerrar_alarma(cond.alarma_id)
                cambios.append(f"cierra {cond.codigo} de {self._nombre(sensor_id)} (sensor deshabilitado)")
            cond.reiniciar()
        self._ultimo.pop(sensor_id, None)

    def _avanzar(self, cond: Condicion, *, entra: bool, sale: bool, retardo_s: float, ahora_s: float,
                 valor: float | None, umbral: float | None, modo_pico: str | None, mensaje: str,
                 cambios: list[str]) -> None:
        accion = cond.actualizar(entra, sale, retardo_s, ahora_s)
        if accion == "activar":
            cond.pico = cond.pico_guardado = valor
            cond.acusada = False
            cond.alarma_id = self.a.abrir_alarma(cond.codigo, sensor_id=cond.sensor_id,
                                                 umbral=umbral, valor=valor, mensaje=mensaje)
            cambios.append(f"abre {cond.codigo}: {mensaje}")
            if cond.codigo == ALM_INVALIDO:
                self.a.registrar_evento("SEN_FALLA", ORIGEN, sensor_id=cond.sensor_id, mensaje=mensaje)
        elif accion == "cerrar":
            if cond.alarma_id is not None:
                self._guardar_pico(cond)                 # el extremo final queda exacto en el registro
                self.a.cerrar_alarma(cond.alarma_id)
            cambios.append(f"cierra {cond.codigo}"
                           + (f" de {self._nombre(cond.sensor_id)}" if cond.sensor_id else ""))
            if cond.codigo == ALM_INVALIDO:
                self.a.registrar_evento("SEN_RECUPERADO", ORIGEN, sensor_id=cond.sensor_id,
                                        mensaje=f"{self._nombre(cond.sensor_id)} volvió a entregar señal")
            cond.reiniciar()
        elif cond.estado == ACTIVA and valor is not None and modo_pico and cond.alarma_id is not None:
            extremo = min if modo_pico == "min" else max
            cond.pico = valor if cond.pico is None else extremo(cond.pico, valor)
            if cond.pico_guardado is None or abs(cond.pico - cond.pico_guardado) >= PICO_MIN_CAMBIO:
                self._guardar_pico(cond)

    # ------------------------------------------------------------------ acuse y sonido
    def acusar(self, actor: str, ahora_s: float, umbrales: Umbrales) -> int:
        """Boton Acusar (D-031): acusa TODAS las alarmas activas de los dos sensores y silencia el
        sonido ``acuse_silencio_s``. Pulsarlo otra vez con alarmas ya acusadas reinicia ese tiempo.
        Devuelve cuantas alarmas se acusaron en esta llamada."""
        nuevas, hay_activas = 0, False
        for cond in self._todas():
            if cond.estado != ACTIVA or cond.alarma_id is None:
                continue
            hay_activas = True
            if not cond.acusada and self.a.acusar_alarma(cond.alarma_id, actor):
                cond.acusada = True
                nuevas += 1
        if hay_activas:
            self._silencio_hasta_s = ahora_s + umbrales.acuse_silencio_s
        return nuevas

    def debe_sonar(self, ahora_s: float) -> bool:
        """True si la pantalla debe sonar ahora: hay una alarma activa SIN acusar (suena al
        instante), o solo hay acusadas y ya vencio el silencio."""
        activas = [c for c in self._todas() if c.estado == ACTIVA]
        if not activas:
            return False
        if any(not c.acusada for c in activas):
            return True
        return ahora_s >= self._silencio_hasta_s

    def hay_sin_acusar(self) -> bool:
        """True si hay alguna alarma activa sin acusar (la pantalla hace parpadear el recuadro)."""
        return any(c.estado == ACTIVA and not c.acusada for c in self._todas())

    # ------------------------------------------------------------------ salidas hacia fuera
    def rele_bajo(self) -> bool:
        """Relevo de oxigeno bajo: activo mientras cualquier sensor tenga la alarma (no depende del acuse)."""
        return any(c.estado == ACTIVA for c in self._bajo.values())

    def rele_alto(self) -> bool:
        return any(c.estado == ACTIVA for c in self._alto.values())

    def estado_sensor(self, sensor_id: int) -> tuple[str, bool]:
        """Texto del recuadro de estado del sensor y si su alarma esta acusada.

        Textos: ``NORMAL``, ``BAJA``, ``ALTA`` o ``SIN SEÑAL`` (ver ESPECIFICACION_HMI.md).
        """
        def activa(grupo: dict[int, Condicion]) -> Condicion | None:
            c = grupo.get(sensor_id)
            return c if c is not None and c.estado == ACTIVA else None

        if self._ultimo.get(sensor_id, 0.0) is None:
            return "SIN SEÑAL", False
        for grupo, texto in ((self._bajo, "BAJA"), (self._alto, "ALTA")):
            cond = activa(grupo)
            if cond is not None:
                return texto, cond.acusada
        return "NORMAL", False

    def texto_aviso(self) -> str:
        """Linea de avisos de la pantalla: resumen de las alarmas activas, maximo 60 letras."""
        partes: list[str] = []
        for sensor_id in sorted(self.nombres):
            valor = self._ultimo.get(sensor_id)
            for grupo, texto in ((self._bajo, "BAJO"), (self._alto, "ALTO")):
                cond = grupo.get(sensor_id)
                if cond is not None and cond.estado == ACTIVA:
                    mostrado = valor if valor is not None else cond.pico
                    partes.append(f"S{sensor_id} {texto}" + (f" {mostrado:.1f} %" if mostrado is not None else ""))
            cond = self._invalido.get(sensor_id)
            if cond is not None and cond.estado == ACTIVA:
                partes.append(f"S{sensor_id} SIN SEÑAL")
        if self._discrepancia.estado == ACTIVA:
            partes.append("SENSORES DIFIEREN")
        if not partes:
            return "Sin alarmas"
        return "  ".join(partes)[:MAX_LARGO_AVISO]
