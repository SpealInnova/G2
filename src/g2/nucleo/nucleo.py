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

import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable

from g2 import __version__
from g2.almacenamiento.almacen import Almacen
from g2.configuracion.catalogo import ErrorConfig
from g2.nucleo import senal
from g2.nucleo.alarmas import ORIGEN, MotorAlarmas, Umbrales
from g2.nucleo.fuentes import FuenteTension
from g2.nucleo.salud import Medidor, ObservadorSalud
from g2.nucleo.servicio_red import ServicioRed
from g2.red.gestor import ErrorRed, redactar, validar_credenciales
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
                 mono: Callable[[], float] = time.monotonic, version_sw: str = __version__,
                 medidor: Medidor | None = None,
                 ejecutor: Callable[[list[str]], None] | None = None,
                 servicio_red: ServicioRed | None = None) -> None:
        """``medidor``: mide la salud de la Pi (sin el, no se registra ni se alarma por la salud; asi las
        pruebas no dependen de la maquina). ``ejecutor``: lanza un comando del sistema (reiniciar); en
        las pruebas se sustituye para no reiniciar nada."""
        self.a = almacen
        self.fuente = fuente
        self.salidas = salidas or SalidasEmuladas()
        self._mono = mono
        self.version_sw = version_sw
        self.salud = ObservadorSalud(almacen, medidor) if medidor is not None else None
        self._ejecutar = ejecutor or _lanzar
        self.red = servicio_red
        self._cambio_red: tuple[int, str] | None = None           # (id del comando, nombre de la red) en curso
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
        if self.salud is not None:
            self.salud.recuperar()
        self.umbrales = Umbrales.desde_almacen(self.a)
        self._ultima_config_s = ahora
        self._inicio_periodo_s = ahora
        return limpio

    def cerrar(self) -> None:
        """Cierre ordenado: guarda lo que haya del intervalo en curso y marca el apagado limpio."""
        self._guardar_periodo(self._mono())
        if self.motor is not None:
            self.motor.guardar_picos()                 # los extremos de las alarmas que sigan abiertas
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
        if self.salud is not None:
            cambios += self.salud.paso(ahora)
        self._atender_red()
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

    def procesar_orden(self, orden: dict) -> None:
        """Atiende una orden que llego de la interfaz (o, mas adelante, de la plataforma). Toda orden
        se REGISTRA en la tabla ``comando`` con su ``uuid`` (trazabilidad, D-009); si el ``uuid`` ya
        existia no se ejecuta otra vez (idempotente). Hoy el unico tipo es ``acusar``."""
        if not isinstance(orden, dict) or "uuid" not in orden or "tipo" not in orden:
            return                                              # orden mal formada: se ignora
        origen = orden.get("origen") if orden.get("origen") in ("pantalla", "plataforma", "local") else "local"
        # Las contrasenas NUNCA se guardan: el registro de comandos se sincroniza con la plataforma y entra a la
        # cadena de auditoria. Se guarda ``***`` en su lugar (ver g2.red.gestor.redactar).
        parametros = redactar({k: v for k, v in orden.items() if k not in ("uuid", "tipo", "origen", "enviada_s")})
        comando_id, nuevo = self.a.registrar_comando(
            uuid_comando=str(orden["uuid"]), origen=origen, tipo=str(orden["tipo"]),
            parametros=parametros, actor=orden.get("actor"))
        if not nuevo:
            return
        actor = str(orden.get("actor") or origen)
        if orden["tipo"] == "acusar":
            acusadas = self.acusar(actor)
            self.a.finalizar_comando(comando_id, "ok", {"acusadas": acusadas})
        elif orden["tipo"] == "pin_resultado":
            self._registrar_resultado_pin(comando_id, orden)
        elif orden["tipo"] == "config_fijar":
            self._fijar_configuracion(comando_id, orden, origen, actor)
        elif orden["tipo"] == "sensor_habilitar":
            self._habilitar_sensor(comando_id, orden, origen, actor)
        elif orden["tipo"] == "sistema_accion":
            self._accion_del_sistema(comando_id, orden, origen, actor)
        elif orden["tipo"] == "auditoria_resultado":
            self._registrar_auditoria(comando_id, orden, origen)
        elif orden["tipo"] == "red_configurar":
            self._configurar_red(comando_id, orden, origen, actor)
        elif orden["tipo"] == "red_buscar":
            if self.red is None:
                self.a.finalizar_comando(comando_id, "rechazado", {"motivo": "la red no esta disponible"})
            else:
                self.red.solicitar_busqueda()
                self.a.finalizar_comando(comando_id, "ok")
        else:
            self.a.finalizar_comando(comando_id, "rechazado",
                                     {"motivo": f"tipo de orden desconocido: {orden['tipo']}"})

    def _registrar_resultado_pin(self, comando_id: int, orden: dict) -> None:
        """La interfaz verifica el PIN (nunca lo manda) y solo AVISA el resultado, para dejarlo como
        evento de seguridad auditable (D-038). Aqui no llega el PIN, ni acertado ni equivocado."""
        eventos = {"aceptado": "SEG_PIN_ACEPTADO", "fallido": "SEG_PIN_FALLIDO",
                   "bloqueado": "SEG_PIN_BLOQUEADO"}
        resultado = orden.get("resultado")
        if resultado not in eventos:
            self.a.finalizar_comando(comando_id, "rechazado", {"motivo": f"resultado de PIN invalido: {resultado!r}"})
            return
        intentos = orden.get("intentos") if isinstance(orden.get("intentos"), int) else None
        self.a.registrar_evento(eventos[resultado], "g2-ui", mensaje=f"PIN {resultado} en la pantalla",
                                datos={"intentos": intentos} if intentos is not None else None)
        self.a.finalizar_comando(comando_id, "ok")

    def _fijar_configuracion(self, comando_id: int, orden: dict, origen: str, actor: str) -> None:
        """Cambio de un ajuste pedido desde la pantalla (o la plataforma): lo aplica el nucleo con todas las
        validaciones del catalogo, el permiso del origen y el historial. Si no es valido se RECHAZA y
        el motivo queda en el comando (el valor vigente no cambia)."""
        try:
            resultado = self.a.config_fijar(str(orden.get("clave", "")), orden.get("valor"), origen=origen,
                                            actor=actor, comando_id=comando_id)
        except ErrorConfig as error:
            self.a.finalizar_comando(comando_id, "rechazado", {"motivo": str(error)})
            return
        self.a.finalizar_comando(comando_id, "ok", {"clave": resultado.clave, "valor": resultado.valor,
                                                    "cambiado": resultado.cambiado})

    def _habilitar_sensor(self, comando_id: int, orden: dict, origen: str, actor: str) -> None:
        """Enciende o apaga un sensor. NUNCA se apaga el ultimo que queda habilitado: sin sensores el equipo no
        mediria nada ni alarmaria. Al cambiar, se cierra el intervalo en curso para no perder sus muestras."""
        sensor_id, habilitar = orden.get("sensor_id"), orden.get("habilitado")
        existentes = {s["id"]: s for s in self.a.listar_sensores()}
        if not isinstance(sensor_id, int) or sensor_id not in existentes or not isinstance(habilitar, bool):
            self.a.finalizar_comando(comando_id, "rechazado", {"motivo": "sensor o valor invalido"})
            return
        if not habilitar and sum(1 for s in existentes.values() if s["habilitado"] and s["id"] != sensor_id) == 0:
            self.a.finalizar_comando(comando_id, "rechazado",
                                     {"motivo": "debe quedar al menos un sensor habilitado"})
            return
        self._guardar_periodo(self._mono())
        cambio = self.a.fijar_sensor_habilitado(sensor_id, habilitar, origen=origen, actor=actor)
        self._cargar_sensores()
        if self.motor is not None:
            self.motor.actualizar_sensores({s["id"]: s["nombre"] for s in self._todos})
        self.a.finalizar_comando(comando_id, "ok", {"sensor_id": sensor_id, "habilitado": habilitar,
                                                    "cambiado": cambio})

    # ``--no-block`` encola los reinicios y vuelve al instante; el nucleo va ULTIMO. Es necesario: este comando lo
    # lanza el propio nucleo y vive en su grupo de procesos, asi que cuando systemd reinicia al nucleo mata tambien
    # al comando; con el nucleo primero, la interfaz no llegaba a reiniciarse (comprobado en la Pi el 2026-10-21).
    ACCIONES_DEL_SISTEMA = {
        "reiniciar_servicios": ["systemctl", "--no-block", "restart", "g2-ui.service", "g2-core.service"],
        "reiniciar_equipo": ["systemctl", "reboot"],
    }

    def _accion_del_sistema(self, comando_id: int, orden: dict, origen: str, actor: str) -> None:
        """Reinicia los servicios o el equipo. Solo las acciones de una lista cerrada (nada que llegue en la
        orden se ejecuta como comando). El comando se cierra y el evento se registra ANTES de lanzar el
        reinicio, porque este detiene al propio nucleo."""
        accion = orden.get("accion")
        if accion not in self.ACCIONES_DEL_SISTEMA:
            self.a.finalizar_comando(comando_id, "rechazado", {"motivo": f"accion desconocida: {accion!r}"})
            return
        self.a.registrar_evento("SYS_REINICIO_PEDIDO", ORIGEN, mensaje=f"{accion} pedido por {origen}:{actor}")
        self.a.finalizar_comando(comando_id, "ok", {"accion": accion})
        self._ejecutar(list(self.ACCIONES_DEL_SISTEMA[accion]))

    def _configurar_red(self, comando_id: int, orden: dict, origen: str, actor: str) -> None:
        """Pide conectar a otra red. El cambio lo hace el servicio de red en su hilo (puede tardar un minuto); el
        comando queda ``recibido`` hasta que ``_atender_red`` recoge el resultado y lo cierra."""
        ssid, contrasena, oculta = orden.get("ssid"), orden.get("contrasena", ""), orden.get("oculta", False)
        if self.red is None:
            self.a.finalizar_comando(comando_id, "rechazado", {"motivo": "la red no esta disponible"})
            return
        if not isinstance(ssid, str) or not isinstance(contrasena, str) or not isinstance(oculta, bool):
            self.a.finalizar_comando(comando_id, "rechazado", {"motivo": "datos de red invalidos"})
            return
        try:
            validar_credenciales(ssid, contrasena)
        except ErrorRed as error:
            self.a.finalizar_comando(comando_id, "rechazado", {"motivo": str(error)})
            return
        if not self.red.solicitar_cambio(ssid, contrasena, oculta):
            self.a.finalizar_comando(comando_id, "rechazado", {"motivo": "ya hay un cambio de red en curso"})
            return
        self._cambio_red = (comando_id, ssid)
        self.a.registrar_evento("RED_CAMBIO_SOLICITADO", ORIGEN,
                                mensaje=f"Cambio a la red «{ssid}» pedido por {origen}:{actor}")

    def _atender_red(self) -> None:
        """Recoge el resultado de un cambio de red terminado y lo deja registrado (el hilo de red no escribe)."""
        if self.red is None:
            return
        terminado = self.red.resultado_pendiente()
        if terminado is None:
            return
        ssid, resultado = terminado
        comando_id = self._cambio_red[0] if self._cambio_red is not None else None
        self._cambio_red = None
        datos = {"motivo": resultado.motivo, "revertida": resultado.revertida, "sin_internet": resultado.sin_internet}
        if resultado.ok:
            self.a.registrar_evento("RED_CAMBIO_OK", ORIGEN, mensaje=resultado.mensaje, datos=datos)
        else:
            self.a.registrar_evento("RED_CAMBIO_FALLIDO", ORIGEN, mensaje=f"«{ssid}»: {resultado.mensaje}", datos=datos)
        if comando_id is not None:
            self.a.finalizar_comando(comando_id, "ok" if resultado.ok else "error",
                                     {"mensaje": resultado.mensaje, **datos})

    def _registrar_auditoria(self, comando_id: int, orden: dict, origen: str) -> None:
        """La interfaz verifica la cadena de auditoria (solo lectura) y AVISA el resultado para dejarlo registrado."""
        correcta = orden.get("correcta")
        diferencias = orden.get("diferencias") if isinstance(orden.get("diferencias"), int) else 0
        if not isinstance(correcta, bool):
            self.a.finalizar_comando(comando_id, "rechazado", {"motivo": "resultado invalido"})
            return
        if correcta:
            self.a.registrar_evento("SEG_AUDITORIA_VERIFICADA", ORIGEN, mensaje=f"Verificacion pedida desde {origen}")
        else:
            self.a.registrar_evento("SEG_AUDITORIA_ALTERADA", ORIGEN,
                                    mensaje=f"{diferencias} diferencia(s) en la cadena de auditoria",
                                    datos={"diferencias": diferencias})
        self.a.finalizar_comando(comando_id, "ok")

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
        aviso = self.motor.texto_aviso()
        etiquetas = self.salud.etiquetas_activas() if self.salud is not None else []
        if etiquetas:                                   # las alarmas de la Pi se muestran, pero no suenan ni mueven relevos
            aviso = ("  ".join(etiquetas) if aviso == "Sin alarmas" else aviso + "  " + "  ".join(etiquetas))[:60]
        return {"sensores": sensores, "aviso": aviso,
                "sonar": self.motor.debe_sonar(ahora), "parpadeo": self.motor.hay_sin_acusar(),
                "rele_bajo": self.motor.rele_bajo(), "rele_alto": self.motor.rele_alto(),
                "version_sw": self.version_sw,
                "salud": self.salud.ultima.como_diccionario() if self.salud is not None else None,
                "alertas_salud": self.salud.codigos_activos() if self.salud is not None else [],
                "red": self.red.estado() if self.red is not None else None}

    # ------------------------------------------------------------------ ciclo continuo
    def ejecutar(self, detener: Callable[[], bool], *, periodo_s: float = 0.5,
                 dormir: Callable[[float], None] = time.sleep,
                 al_publicar: Callable[[dict], None] | None = None,
                 al_paso: Callable[[], None] | None = None,
                 ordenes: Callable[[], list[dict]] | None = None) -> None:
        """Repite ``paso`` hasta que ``detener()`` sea True.

        * ``ordenes``: devuelve las ordenes pendientes de la interfaz; se atienden al comienzo de cada
          vuelta (y el estado se publica de inmediato, para que el acuse se vea sin esperar).
        * ``al_publicar``: recibe el estado de la pantalla cada ``muestreo.intervalo_pantalla_s``.
        * ``al_paso``: se llama DESPUES de cada paso completo y solo si no hubo excepcion: es el latido
          del watchdog por progreso (D-012).
        """
        ultima_publicacion = float("-inf")
        while not detener():
            inicio = self._mono()
            hubo_ordenes = False
            if ordenes is not None:
                for orden in ordenes():
                    self.procesar_orden(orden)
                    hubo_ordenes = True
            self.paso()
            if al_paso is not None:
                al_paso()
            intervalo = float(self.a.config_tipada("muestreo.intervalo_pantalla_s"))
            if al_publicar is not None and (hubo_ordenes or inicio - ultima_publicacion >= intervalo):
                ultima_publicacion = inicio
                al_publicar(self.estado_pantalla())
            dormir(max(0.0, periodo_s - (self._mono() - inicio)))


def _lanzar(comando: list[str]) -> None:
    """Lanza un comando del sistema sin esperarlo y sin atarlo al nucleo (el reinicio lo detiene). Los permisos
    para ``systemctl restart`` de los servicios de G2 y ``systemctl reboot`` los da la regla de polkit
    ``systemd/50-g2.rules``, sin ``sudo`` (los servicios corren con ``NoNewPrivileges``)."""
    subprocess.Popen(comando, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
