"""g2-ui: la interfaz de la pantalla Nextion (D-005, D-029, D-032, D-038, D-039).

La pantalla es "tonta": solo muestra y avisa de los toques (principio 1 de la especificacion del HMI).
Esta clase hace todo lo demas:

  * **Navegacion**: toda pagina nueva la ordena la Pi (``page ...``), asi puede exigir el PIN antes de
    abrir una pagina protegida y puede forzar una pagina (principio 2).
  * **Pintar**: convierte el estado del nucleo en ordenes para la pantalla (``vistas``), enviando solo
    lo que cambio, y cada vez que una pagina termina de cargarse la repinta entera (evento ``FE``).
  * **Alarmas** (D-032): hace parpadear el recuadro del sensor mientras la alarma no se acusa y repite el
    sonido cada pocos segundos (si esta interfaz se detiene, el sonido se detiene solo).
  * **Todo lo delicado pide PIN** (D-038): cambiar un ajuste, apagar un sensor, reiniciar, verificar la auditoria.
    ``_requerir_pin`` abre el teclado si no hay un PIN vigente y, con el PIN correcto, sigue con lo pendiente.
    El PIN se verifica AQUI contra su huella (de la base, en solo lectura) y nunca viaja ni se registra; al
    nucleo solo se le avisa el RESULTADO para que quede como evento de seguridad.
  * **Confirmar**: lo que interrumpe el servicio (apagar un sensor, reiniciar) pasa ademas por una pagina de Si / No.
  * **Ordenes al nucleo**: la interfaz nunca escribe en la base (D-005). Deja ordenes (acusar, cambiar un ajuste,
    habilitar un sensor, reiniciar, resultado de la auditoria) que el nucleo valida, registra y ejecuta.
  * Si el nucleo deja de publicar, NO se muestran valores viejos como si fueran actuales: los recuadros pasan
    a ``SIN SEÑAL`` y el aviso dice ``Núcleo sin respuesta``.

  * **Red** (D-040): estado de la conexion, redes cercanas y cambio de red escribiendo el nombre y la contrasena con
    el teclado de texto completo (o tocando una red cercana). Todo pide PIN y confirmacion; el cambio lo hace el
    nucleo con reversion automatica si la red nueva falla, y la contrasena nunca se registra.

  * **Grafica en tiempo** (D-043): tras ``pantalla.grafica_espera_s`` (10 s) sin tocar la pantalla, y solo desde ``principal``, abre la
    pagina ``grafica`` con las dos senales; un toque la cierra. Si salta una alarma sin acusar o el nucleo deja de responder, vuelve
    sola a ``principal`` para que se vea el aviso. Toda esta logica es de la Pi: la pantalla solo dibuja lo que se le manda.

  * **Reportes** (D-044): el rango de fechas (dias completos, maximo una semana) se escribe con el teclado numerico, hay un boton
    para el reporte de hoy, y la memoria USB debe llamarse igual que el equipo. Pide PIN. El reporte lo hace el nucleo en un
    proceso aparte; esta pagina solo muestra su avance y resultado.

Pendiente (siguientes etapas): la pagina calibracion.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import date
from typing import Callable, Protocol

from g2.configuracion import catalogo
from g2.ipc import ClienteNucleo
from g2.pantalla import grafica
from g2.pantalla import protocolo as P
from g2.pantalla import teclado as tec
from g2.pantalla import texto as txt
from g2.pantalla import vistas
from g2.pantalla.protocolo import (CodigoResultado, DatosRecibidos, Evento, ListoParaDatos, PaginaCargada,
                                   PantallaEncendida, RespuestaNumero, TocarPantalla, Toque)
from g2.red.gestor import ErrorRed, validar_credenciales
from g2.reportes import rango as rango_reporte
from g2.seguridad import pin as seguridad_pin

REGISTRO = logging.getLogger("g2.pantalla")

PAGINAS_EN_CONSTRUCCION: tuple[str, ...] = ()
MENSAJE_EN_CONSTRUCCION = "Página en construcción"
CONTROLES_DEL_TECLADO = set(tec.DIGITOS) | {"k_punto", "k_signo", "b_borrar", "b_limpiar"}
DURACION_RESULTADO_S = 20.0
VOLUMEN_MINIMO = 10                      # lo mas bajo al que la proteccion deja el volumen
BAJA_DE_VOLUMEN = 20                     # cuanto baja el volumen cada vez que la pantalla se reinicia al sonar
VENTANA_REINICIOS_S = 60.0               # reinicios por sonido que se cuentan juntos
REINICIOS_PARA_CALLAR = 3                # a este numero de reinicios se desactiva el sonido
SONIDO_CALLADO_S = 600.0                 # por cuanto tiempo (la alarma visual y los relevos siguen igual)
GRACIA_SONIDO_S = 4.0                    # un reinicio tan pronto despues de un `play` se atribuye al sonido
ESPERA_BLOQUE_S = 4.0                    # lo que se espera la respuesta de la pantalla a un `addt` antes de usar `add`
ESPERA_CAMBIO_GRAFICA_S = 3.0            # tras abrir o cerrar la grafica por su cuenta, no se vuelve a pedir antes de esto
RECHAZOS_PARA_DESACTIVAR_GRAFICA = 3     # ordenes de la grafica rechazadas por la pantalla antes de desactivarla
ESPERA_CARGA_S = 2.0                     # tras ordenar una pagina, lo que se espera su aviso de carga sin pintar la anterior
USB_CADA_S = 3.0                         # cada cuanto se revisa la memoria USB mientras se mira la pagina de reportes
ESPERA_ORDEN_REPORTE_S = 6.0             # tras pedir un reporte, lo que se espera a que el nucleo lo acepte
ESPERA_ORDEN_CALIBRACION_S = 6.0         # lo mismo para una calibracion
REFERENCIA_AIRE = 20.9                   # el atajo `Aire` de la pagina de calibracion
_SIN_VER = object()                       # marca: todavia no se ha visto el estado del cambio de red


class Enlace(Protocol):
    def enviar(self, orden: str) -> None: ...
    def enviar_crudo(self, datos: bytes) -> None: ...
    def eventos(self) -> list[Evento]: ...


class Datos(Protocol):
    def config_alarmas(self) -> dict[str, float]: ...
    def config_general(self) -> dict[str, float]: ...
    def config_pin(self) -> dict[str, float]: ...
    def datos_del_equipo(self) -> dict[str, str]: ...
    def sensores(self) -> list[dict]: ...
    def pin_activo(self) -> dict | None: ...
    def historial_alarmas(self, cantidad: int = 6) -> list[dict]: ...
    def cola_pendiente(self) -> int: ...
    def verificar_auditoria(self) -> tuple[bool, int]: ...
    def zona_horaria(self) -> str: ...
    def contar_registros(self, inicio_ms: int, fin_ms: int) -> int | None: ...
    def estado_usb(self, nombre: str) -> tuple[str, bool]: ...
    def calibraciones_vigentes(self) -> dict[int, dict]: ...


def _en_hilo(tarea: Callable[[], None]) -> None:
    """Corre ``tarea`` en un hilo aparte: la interfaz no se queda esperando una verificacion larga."""
    threading.Thread(target=tarea, daemon=True).start()


class Interfaz:
    REFRESCO_S = 0.25              # cada cuanto se revisa el estado del nucleo
    MEDIO_PARPADEO_S = 0.5         # el parpadeo es de 1 Hz: cambia de fase cada medio segundo
    DATOS_S = 2.0                  # cada cuanto se leen la base y la red
    ESPERA_CAMBIO_S = 1.0          # tras pedir un cambio, cuanto se espera antes de releer la base

    def __init__(self, enlace: Enlace, cliente: ClienteNucleo, datos: Datos, *,
                 reloj: Callable[[], float] = time.monotonic,
                 hora: Callable[[], str] = lambda: time.strftime("%H:%M"),
                 red: Callable[[], str] = lambda: "SIN RED",
                 repetir_sonido_s: float = 3.0, max_edad_s: float = 5.0, mensaje_s: float = 3.0,
                 segundo_plano: Callable[[Callable[[], None]], None] = _en_hilo,
                 hoy: Callable[[str], date] = rango_reporte.hoy) -> None:
        self.enlace, self.cliente, self.datos = enlace, cliente, datos
        self._reloj, self._hora, self._red = reloj, hora, red
        self.repetir_sonido_s, self.max_edad_s, self.mensaje_s = repetir_sonido_s, max_edad_s, mensaje_s
        self._segundo_plano = segundo_plano
        self._hoy_en = hoy
        self._ultimas_ordenes: deque[str] = deque(maxlen=6)
        # ---- volumen y proteccion contra reinicios al sonar (D-041) ----
        self._volumen: int | None = None                         # volumen vigente (la proteccion puede bajarlo)
        self._t_play = float("-inf")                             # cuando se ordeno el ultimo sonido de alarma
        self._reinicios_por_sonido: list[float] = []
        self._sonido_callado_hasta = float("-inf")
        self.pagina: str | None = None
        self._cache: dict[str, str | int] = {}
        self._fase = True
        self._t_fase = self._t_refresco = self._t_sonido = self._t_datos = float("-inf")
        self._mensaje: tuple[str, float] | None = None
        self._config: dict[str, float] = {}
        self._historial: list[dict] = []
        self._sensores: list[dict] = []
        self._equipo: dict[str, str] = {}
        self._pin_tipo: str | None = None
        self._cola, self._red_texto = 0, "SIN RED"
        self._proto_pedido = False
        self.protocolo_compatible: bool | None = None
        self.protocolo_version: int | None = None
        # ---- teclado, PIN y confirmacion (D-038) ----
        self._entrada: tec.Entrada | None = None                 # lo que se esta tecleando
        self._tras_pin: Callable[[], None] | None = None         # lo que sigue cuando el PIN sea correcto
        self._regreso = "alarmas"                                # pagina a la que se vuelve al cancelar o terminar
        self._aviso_teclado: tuple[str, bool] = ("", False)      # (texto, es_error)
        self._confirmacion: tuple[str, str, Callable[[], None], str] | None = None
        self._pin_hasta = float("-inf")                          # el PIN aceptado vale hasta este instante
        self._fallos = 0
        self._bloqueado_hasta = float("-inf")
        # ---- red y teclado de texto (D-040) ----
        self._texto: txt.EntradaTexto | None = None              # lo que se esta escribiendo (nombre o contrasena)
        self._texto_etapa = ""                                   # "ssid" o "clave"
        self._red_ssid: str | None = None
        self._red_oculta = False                                 # la red no se vio en la busqueda: puede estar oculta
        self._clave_obligatoria = False                          # la red se vio con seguridad: no admite clave vacia
        self._aviso_texto: tuple[str, bool] = ("", False)
        self._red_info: dict | None = None                       # foto de la red que publica el nucleo
        self._redes: list[dict] = []
        self._cambio_visto: object = _SIN_VER
        # ---- pagina sistema (D-039) ----
        self._resultado: tuple[str, bool, float, str] | None = None   # (texto, es_error, hasta cuando, en que pagina)
        self._auditoria_en_curso = False
        self._auditoria_resultado: tuple[bool, int] | None = None
        # ---- reportes (D-044) ----
        self._zona = "America/Bogota"                       # zona horaria de los reportes (la lee de la base)
        self._rep_desde: date | None = None
        self._rep_hasta: date | None = None
        self._rep_registros: int | None = None                   # filas que traeria el rango elegido
        self._rep_usb: tuple[str, bool] = ("Buscando la memoria USB...", False)
        self._rep_usb_pedido = float("-inf")
        self._rep_usb_en_curso = False
        self._rep_en_curso = False                               # el nucleo esta generando un reporte
        self._rep_visto: object = _SIN_VER                       # numero del ultimo resultado ya visto
        self._rep_enviado = float("-inf")                        # cuando se pidio el ultimo reporte (hasta que el nucleo lo acepte)
        self._toques_bloqueados = False                          # la pantalla de verdad ignora los toques de la pagina actual
        # ---- calibracion de cero en aire (D-048) ----
        self._calibraciones: dict[int, dict] = {}                # la calibracion vigente de cada sensor calibrado
        self._cal_sensor = 1                                     # el sensor elegido en la pagina de calibracion (1 o 2)
        self._cal_gas = 0.0                                      # la concentracion del gas patron elegida, en %
        self._cal_en_curso = False                               # el nucleo esta calibrando un sensor
        self._cal_visto: object = _SIN_VER                       # numero de la ultima calibracion ya vista
        self._cal_enviado = float("-inf")                        # cuando se pidio la ultima (hasta que el nucleo la acepte)
        # ---- grafica en tiempo (D-043) ----
        self._hist = grafica.HistorialGrafica()
        self._t_muestra = float("-inf")
        self._ultimo_toque = self._reloj()                       # el ultimo toque en cualquier punto de la pantalla
        self._t_cambio = float("-inf")                           # cuando la Pi abrio o cerro la grafica por su cuenta
        self._cambio_pedido = ""
        self._grafica_disponible = True                          # False si el .tft no trae la pagina ``grafica``
        self._rechazos_grafica = 0                               # ordenes de la grafica que la pantalla rechazo (desde que se abrio)
        self._cerrando_grafica = False                           # ya se ordeno volver a la principal: no se dibuja mas
        self._t_pagina_pedida = float("-inf")                    # cuando se ordeno la ultima pagina (hasta que cargue, no se pinta la vieja)
        self._grafica_dibujada = 0                               # muestras que ya se le mandaron a la pantalla
        self._grafica_marca: tuple | None = None                 # (eje, limites) con que se dibujo: si cambian, se redibuja todo
        self._con_bloques = True                                 # redibujar con addt; si no responde, con add
        self._bloques: deque[tuple[int, bytes]] = deque()
        self._espera_datos: str | None = None                    # "listo" o "fin" mientras un addt recibe sus bytes
        self._t_espera = 0.0
        self._diferidas: list[str] = []                          # ordenes que esperan a que termine el addt

    # ------------------------------------------------------------------ arranque
    def iniciar(self) -> None:
        """Fija el volumen y lleva la pantalla a la pagina principal; el resto lo hace el evento de pagina cargada."""
        self._fijar_volumen()
        self._tx(P.orden_pagina("principal"))
        self._tx(P.ORDEN_INFORMAR_TOQUES)

    def _fijar_volumen(self) -> None:
        """Pone el volumen de la pantalla. Lo hace la Pi (no el .HMI) porque con un volumen alto el altavoz consume mas
        de lo que aguanta la fuente de la pantalla y esta se REINICIA al sonar (comprobado: 70 reinicia, 50 y 60 no)."""
        if self._volumen is None:
            configurado = int(self.datos.config_general().get("pantalla.volumen", 50))
            self._volumen = max(0, min(100, configurado))
        self._tx(f"volume={self._volumen}")

    def _atribuir_reinicio_al_sonido(self, ahora: float) -> None:
        """La pantalla encendio sola justo despues de un sonido de alarma: se baja el volumen y, si insiste, se calla
        el sonido un rato. La alarma visual (el recuadro rojo) y los relevos NO dependen del sonido."""
        self._reinicios_por_sonido = [t for t in self._reinicios_por_sonido if ahora - t < VENTANA_REINICIOS_S] + [ahora]
        anterior = self._volumen if self._volumen is not None else 50
        self._volumen = max(VOLUMEN_MINIMO, anterior - BAJA_DE_VOLUMEN)
        REGISTRO.error("la pantalla se reinicio al sonar la alarma (volumen %d demasiado alto para su fuente): se baja a %d",
                       anterior, self._volumen)
        if len(self._reinicios_por_sonido) >= REINICIOS_PARA_CALLAR:
            self._sonido_callado_hasta = ahora + SONIDO_CALLADO_S
            REGISTRO.error("la pantalla sigue reiniciandose al sonar: el sonido de alarma se desactiva %d min "
                           "(la alarma visual y los relevos siguen)", SONIDO_CALLADO_S // 60)

    # ------------------------------------------------------------------ ciclo
    def paso(self) -> None:
        """Atiende lo que llego de la pantalla y refresca lo que se muestra. Se llama muchas veces por segundo."""
        for evento in self.enlace.eventos():
            self.atender(evento)
        ahora = self._reloj()
        self._vigilar_transferencia(ahora)
        if ahora - self._t_refresco >= self.REFRESCO_S:
            self._t_refresco = ahora
            self._refrescar(ahora)

    def atender(self, evento: Evento) -> None:
        if isinstance(evento, PantallaEncendida):
            REGISTRO.info("la pantalla se encendio: se reinicia la sesion")
            ahora = self._reloj()
            if ahora - self._t_play <= GRACIA_SONIDO_S:
                self._atribuir_reinicio_al_sonido(ahora)
            self._fijar_volumen()                            # el .HMI vuelve a poner el suyo al encender: la Pi lo corrige
            self.pagina, self._proto_pedido = None, False
            self._toques_bloqueados = False                  # al reiniciarse vuelve con los toques habilitados
            self._soltar_teclado()
            self._soltar_texto()
            self._confirmacion = None
            self._cache.clear()
            self._terminar_transferencia(enviar=False)       # la pantalla se reinicio: lo que esperaba ya no existe
            self._grafica_disponible, self._ultimo_toque = True, ahora      # puede haber traido un .tft nuevo
            self._tx(P.orden_pagina("principal"))
            self._tx(P.ORDEN_INFORMAR_TOQUES)
        elif isinstance(evento, PaginaCargada):
            REGISTRO.info("pagina cargada: %s", evento.pagina)
            self.pagina = evento.pagina
            self._toques_bloqueados = False                  # una pagina recien cargada trae sus toques habilitados
            self._t_pagina_pedida = float("-inf")
            if evento.pagina != "teclado":
                self._soltar_teclado()                       # se salio del teclado por otra via
            if evento.pagina != "texto":
                self._soltar_texto()                         # y lo que se escribia (puede ser una contrasena) se descarta
            if evento.pagina != "confirmar":
                self._confirmacion = None
            if evento.pagina == "grafica":
                self._grafica_marca = None                   # al abrirla se dibuja todo: la pantalla la trae vacia
                self._rechazos_grafica = 0
                self._cerrando_grafica = False
            else:
                self._terminar_transferencia()
            self._cache.clear()                              # la pantalla repinta sus valores iniciales al cargar
            self._t_refresco = self._t_datos = float("-inf")     # se repinta, con datos recien leidos, en esta vuelta
            if not self._proto_pedido:
                self._proto_pedido = True
                self._tx(P.ORDEN_LEER_PROTOCOLO)
        elif isinstance(evento, RespuestaNumero):
            if self.protocolo_compatible is None and self._proto_pedido:
                self.protocolo_version = evento.valor
                self.protocolo_compatible = evento.valor == P.VERSION_PROTOCOLO
                if self.protocolo_compatible:
                    REGISTRO.info("protocolo de la pantalla: version %d (compatible)", evento.valor)
                else:
                    REGISTRO.error("la pantalla trae el protocolo %d y esta interfaz espera el %d: "
                                   "cargue el .tft que corresponde", evento.valor, P.VERSION_PROTOCOLO)
        elif isinstance(evento, TocarPantalla):
            self._ultimo_toque = self._reloj()
        elif isinstance(evento, ListoParaDatos):
            self._datos_listos()
        elif isinstance(evento, DatosRecibidos):
            self._datos_recibidos()
        elif isinstance(evento, CodigoResultado):
            if (evento.codigo == 0x03 and self._cambio_pedido == "grafica"
                    and self._reloj() - self._t_cambio < ESPERA_CAMBIO_GRAFICA_S):
                self._grafica_disponible = False
                REGISTRO.error("la pantalla no tiene la pagina 'grafica': la grafica queda desactivada hasta que se "
                               "cargue un .tft que la incluya")
            elif evento.codigo != 0x01 and not self._rechazo_de_la_grafica(evento.descripcion):
                REGISTRO.warning("la pantalla rechazo una orden: %s (ultimas enviadas: %s)", evento.descripcion,
                                 " | ".join(self._ultimas_ordenes))
        elif isinstance(evento, Toque):
            self._toque(evento)
        else:
            REGISTRO.debug("evento sin atender: %s", P.describir(evento))

    def _tx(self, orden: str) -> None:
        """Envia una orden a la pantalla y se acuerda de las ultimas, para poder decir cual rechazo la pantalla (su
        respuesta de error no dice a cual se refiere). El campo del teclado de texto NO se guarda: puede llevar una
        contrasena visible."""
        if self._espera_datos is not None:                  # un addt esta recibiendo bytes: nada debe mezclarse con ellos
            self._diferidas.append(orden)
            return
        self._tx_ahora(orden)

    def _tx_ahora(self, orden: str) -> None:
        if orden.startswith("page "):
            self._t_pagina_pedida = self._reloj()
        self._ultimas_ordenes.append("<campo de texto>" if "texto.valor" in orden else orden)
        self.enlace.enviar(orden)

    def _ir(self, pagina: str) -> None:
        """Ordena ir a una pagina (si ya se esta en ella no se recarga, para que no parpadee)."""
        if self.pagina != pagina:
            self._tx(P.orden_pagina(pagina))
        else:
            self._t_refresco = float("-inf")

    def _soltar_teclado(self) -> None:
        self._entrada, self._tras_pin = None, None

    def _toque(self, toque: Toque) -> None:
        if self._pantalla_bloqueada():
            REGISTRO.info("toque ignorado (pantalla bloqueada): %s.%s", toque.pagina, toque.control)
            return
        REGISTRO.info("toque: %s.%s", toque.pagina, toque.control)
        self._ultimo_toque = self._reloj()
        pagina, control = toque.pagina, toque.control
        if pagina == "principal":
            self._toque_principal(control)
        elif pagina == "grafica":
            if control == "salir":
                self._cerrando_grafica = True
                self._tx(P.orden_pagina("principal"))
        elif pagina == "alarmas":
            if control == "b_volver":
                self._tx(P.orden_pagina("principal"))
            elif (pagina, control) in tec.EDITABLES:
                self._editar(tec.EDITABLES[(pagina, control)], "alarmas")
        elif pagina == "config":
            self._toque_config(control)
        elif pagina == "red":
            self._toque_red(control)
        elif pagina == "texto":
            self._toque_texto(control)
        elif pagina == "sistema":
            self._toque_sistema(control)
        elif pagina == "reportes":
            self._toque_reportes(control)
        elif pagina == "calibracion":
            self._toque_calibracion(control)
        elif pagina == "teclado":
            self._toque_teclado(control)
        elif pagina == "confirmar":
            self._toque_confirmar(control)
        else:
            REGISTRO.debug("toque sin accion: %s.%s", pagina, control)

    def _toque_principal(self, control: str) -> None:
        destinos = {"b_alarmas": "alarmas", "b_config": "config", "b_sistema": "sistema", "b_red": "red",
                    "b_calib": "calibracion"}
        if control in destinos:
            self._tx(P.orden_pagina(destinos[control]))
        elif control == "b_acuse":
            identificador = self.cliente.enviar_orden("acusar", actor="pantalla")
            REGISTRO.info("acuse pedido al nucleo (orden %s)", identificador)
        elif control in PAGINAS_EN_CONSTRUCCION:
            self._mensaje = (MENSAJE_EN_CONSTRUCCION, self._reloj() + self.mensaje_s)
            self._t_refresco = float("-inf")

    # ------------------------------------------------------------------ config
    def _toque_config(self, control: str) -> None:
        if control == "b_volver":
            self._tx(P.orden_pagina("principal"))
        elif ("config", control) in tec.EDITABLES:
            self._editar(tec.EDITABLES[("config", control)], "config")
        elif control in ("v_sensor1", "v_sensor2"):
            self._alternar_sensor(int(control[-1]))

    def _alternar_sensor(self, n: int) -> None:
        if n > len(self._sensores):
            return
        sensor = self._sensores[n - 1]
        if sensor["habilitado"]:
            pregunta = f"¿Apagar el Sensor {n}?"
            detalle = "Dejará de medirse y de generar alarmas. Siempre debe quedar al menos un sensor activo."
            self._requerir_pin(lambda: self._confirmar(
                pregunta, detalle, lambda: self._ordenar_sensor(sensor["id"], False), "config"), "config")
        else:
            self._requerir_pin(lambda: (self._ordenar_sensor(sensor["id"], True), self._ir("config")), "config")

    def _ordenar_sensor(self, sensor_id: int, habilitado: bool) -> None:
        identificador = self.cliente.enviar_orden("sensor_habilitar", actor="pantalla",
                                                  sensor_id=sensor_id, habilitado=habilitado)
        REGISTRO.info("sensor %d %s (orden %s)", sensor_id, "habilitado" if habilitado else "apagado", identificador)
        self._t_datos = self._reloj() + self.ESPERA_CAMBIO_S - self.DATOS_S

    # ------------------------------------------------------------------ sistema
    def _toque_sistema(self, control: str) -> None:
        if control == "b_volver":
            self._tx(P.orden_pagina("principal"))
        elif control == "b_reportes":
            self._abrir_reportes()
        elif control == "b_servicios":
            self._requerir_pin(lambda: self._confirmar(
                "¿Reiniciar los servicios?", "La medición y la pantalla se interrumpen unos segundos.",
                lambda: self._pedir_sistema("reiniciar_servicios", "Reiniciando servicios..."), "sistema"), "sistema")
        elif control == "b_reiniciar":
            self._requerir_pin(lambda: self._confirmar(
                "¿Reiniciar el equipo?",
                "La medición se interrumpe cerca de un minuto y las alarmas externas pueden activarse unos segundos.",
                lambda: self._pedir_sistema("reiniciar_equipo", "Reiniciando el equipo..."), "sistema"), "sistema")
        elif control == "b_auditoria":
            self._requerir_pin(self._lanzar_auditoria, "sistema")

    def _pedir_sistema(self, accion: str, texto: str) -> None:
        identificador = self.cliente.enviar_orden("sistema_accion", actor="pantalla", accion=accion)
        REGISTRO.info("accion del sistema pedida al nucleo: %s (orden %s)", accion, identificador)
        self._poner_resultado(texto)

    def _poner_resultado(self, texto: str, error: bool = False, segundos: float = DURACION_RESULTADO_S,
                         pagina: str = "sistema") -> None:
        """Mensaje de resultado para la linea ``res`` de una pagina (por omision, la de sistema)."""
        self._resultado = (texto, error, self._reloj() + segundos, pagina)
        self._t_refresco = float("-inf")

    def _lanzar_auditoria(self) -> None:
        """Verifica la cadena de auditoria en segundo plano (puede tardar) y despues avisa el resultado al nucleo."""
        self._ir("sistema")
        if self._auditoria_en_curso:
            return
        self._auditoria_en_curso = True
        self._poner_resultado("Verificando auditoría...", segundos=3600)
        self._segundo_plano(self._auditar)

    def _auditar(self) -> None:
        try:
            self._auditoria_resultado = self.datos.verificar_auditoria()
        except Exception:                                    # nada debe dejar la verificacion colgada
            REGISTRO.exception("la verificacion de la auditoria fallo")
            self._auditoria_resultado = (False, -1)

    def _atender_auditoria(self) -> None:
        if self._auditoria_resultado is None:
            return
        (correcta, diferencias), self._auditoria_resultado = self._auditoria_resultado, None
        self._auditoria_en_curso = False
        self.cliente.enviar_orden("auditoria_resultado", actor="pantalla", correcta=correcta,
                                  diferencias=max(diferencias, 0))
        if correcta:
            self._poner_resultado("Auditoría íntegra: sin diferencias")
        elif diferencias < 0:
            self._poner_resultado("No se pudo verificar la auditoría", error=True)
        else:
            self._poner_resultado(f"AUDITORÍA ALTERADA: {diferencias} diferencia(s)", error=True)
        REGISTRO.info("auditoria verificada: %s (%d diferencias)", "integra" if correcta else "NO integra", diferencias)

    # ------------------------------------------------------------------ reportes (D-044)
    def _hoy(self) -> date:
        """El dia de hoy en la zona de los reportes (si la zona guardada no es valida, la de Colombia)."""
        try:
            return self._hoy_en(self._zona)
        except rango_reporte.ErrorRango:
            return self._hoy_en("America/Bogota")

    def _abrir_reportes(self) -> None:
        """Abre la pagina de reportes con el rango en el dia de hoy."""
        self._rep_desde = self._rep_hasta = self._hoy()
        self._rep_registros, self._rep_usb_pedido = None, float("-inf")
        self._t_datos = float("-inf")
        self._tx(P.orden_pagina("reportes"))

    def _toque_reportes(self, control: str) -> None:
        if control == "b_volver":
            self._tx(P.orden_pagina("sistema"))
        elif control in ("v_desde", "v_hasta"):
            self._editar_fecha(control[2:])
        elif control == "b_hoy":
            hoy = self._hoy()
            self._rep_desde = self._rep_hasta = hoy
            self._iniciar_reporte(hoy, hoy)
        elif control == "b_generar":
            if self._rep_desde is not None and self._rep_hasta is not None:
                self._iniciar_reporte(self._rep_desde, self._rep_hasta)

    def _editar_fecha(self, cual: str) -> None:
        """Abre el teclado numerico para escribir la fecha inicial o final (no pide PIN: solo elige el rango)."""
        actual = self._rep_desde if cual == "desde" else self._rep_hasta
        self._regreso = "reportes"
        self._entrada = tec.Entrada("fecha", cual)
        self._aviso_teclado = (f"Actual: {rango_reporte.formato_fecha(actual or self._hoy())}. Escriba 8 dígitos (DDMMAAAA)", False)
        self._tx(P.orden_pagina("teclado"))

    def _aceptar_fecha(self, entrada: tec.Entrada) -> None:
        dia, motivo = tec.validar_fecha(entrada.buffer, self._hoy())
        if dia is None:
            self._aviso_teclado = (motivo, True)
            return
        if entrada.clave == "desde":
            self._rep_desde = dia
        else:
            self._rep_hasta = dia
        self._entrada, self._rep_registros, self._t_datos = None, None, float("-inf")
        self._tx(P.orden_pagina("reportes"))

    def _iniciar_reporte(self, desde: date, hasta: date) -> None:
        """Comprueba todo lo que la pantalla puede comprobar (para no pedir el PIN en balde) y pide el PIN para generar."""
        def aviso(texto: str) -> None:
            self._poner_resultado(texto, error=True, segundos=8, pagina="reportes")

        if self._rep_en_curso:
            aviso("Ya hay un reporte en curso")
            return
        try:
            rango_reporte.validar(desde, hasta, self._hoy())
        except rango_reporte.ErrorRango as error:
            aviso(str(error))
            return
        if not self._equipo.get("equipo.nombre"):
            aviso("Defina el nombre del equipo (es la contraseña del reporte)")
            return
        if not self._rep_usb[1]:
            aviso(self._rep_usb[0])
            return
        self._requerir_pin(lambda: self._enviar_reporte(desde, hasta), "reportes")

    def _enviar_reporte(self, desde: date, hasta: date) -> None:
        identificador = self.cliente.enviar_orden("reporte_generar", actor="pantalla", desde=desde.isoformat(),
                                                  hasta=hasta.isoformat())
        REGISTRO.info("reporte pedido al nucleo: %s a %s (orden %s)", desde, hasta, identificador)
        self._rep_enviado = self._reloj()
        self._poner_resultado("Iniciando el reporte...", segundos=ESPERA_ORDEN_REPORTE_S, pagina="reportes")
        self._ir("reportes")

    def _calibrando(self) -> bool:
        """El nucleo calibra un sensor (o acaba de recibir la orden)."""
        return self._cal_en_curso or self._cal_enviado > float("-inf")

    def _pantalla_bloqueada(self) -> bool:
        """Mientras el equipo genera un reporte o calibra un sensor (o acaba de recibir la orden) la pantalla no atiende NINGUN
        toque: nadie puede salir de la pagina, cambiar las fechas ni pedir otra cosa, y asi nada interrumpe el proceso ni se
        manipula a medias. Se deduce del estado del nucleo: si este deja de responder, la pantalla se libera sola (no puede
        quedar bloqueada)."""
        return self._rep_en_curso or self._rep_enviado > float("-inf") or self._calibrando()

    def _aplicar_bloqueo(self, ahora: float) -> None:
        """Hace que la pantalla de verdad ignore los toques (``tsw 255,0``) y no salga de la pagina de reportes. Los toques
        tambien se descartan en la Pi (``_toque``): esto es el aviso visible y la segunda barrera. Una pagina nueva trae los
        toques habilitados, asi que la orden se repite cada vez que carga una."""
        bloqueada = self._pantalla_bloqueada()
        destino = "calibracion" if self._calibrando() else "reportes"
        cargada = self.pagina is not None and ahora - self._t_pagina_pedida >= ESPERA_CARGA_S
        if bloqueada and self.pagina not in (None, destino) and cargada:
            if destino == "reportes" and (self._rep_desde is None or self._rep_hasta is None):   # se reinicio la interfaz con un reporte en curso
                self._rep_desde = self._rep_hasta = self._hoy()
            self._tx(P.orden_pagina(destino))
        elif bloqueada and not self._toques_bloqueados and cargada and self.pagina == destino:
            self._tx(P.ORDEN_BLOQUEAR_TOQUES)
            self._toques_bloqueados = True
        elif not bloqueada and self._toques_bloqueados:
            self._tx(P.ORDEN_DESBLOQUEAR_TOQUES)
            self._toques_bloqueados = False

    def _leer_usb(self, nombre: str) -> None:
        """Revisa la memoria USB (puede tardar: corre en segundo plano)."""
        try:
            self._rep_usb = self.datos.estado_usb(nombre)
        except Exception:                                        # nada debe dejar la revision colgada
            REGISTRO.exception("no se pudo revisar la memoria USB")
            self._rep_usb = ("No se pudo revisar la memoria USB", False)
        finally:
            self._rep_usb_en_curso = False

    def _leer_reporte(self, ahora: float, estado: dict | None) -> None:
        """Toma del estado del nucleo si hay un reporte en curso y el resultado del ultimo. El resultado solo se muestra si
        aparece MIENTRAS se mira (el de antes de arrancar esta interfaz es viejo y se ignora)."""
        reporte = (estado or {}).get("reporte")
        self._rep_en_curso = bool(reporte and reporte.get("en_curso"))
        if self._rep_en_curso:
            self._rep_enviado = float("-inf")
        if reporte is None:
            return
        ultimo = reporte.get("ultimo")
        numero = ultimo["numero"] if ultimo else None
        if numero != self._rep_visto:
            if self._rep_visto is not _SIN_VER and ultimo is not None:
                self._rep_enviado = float("-inf")
                if ultimo["ok"]:
                    texto = (f"Listo: {ultimo.get('filas', '?')} filas, {ultimo.get('paginas', '?')} págs. "
                             f"Huella {str(ultimo.get('sha256', ''))[:12]}")
                    if not ultimo.get("desmontada", True):
                        texto += " (retire la USB con cuidado)"
                    self._poner_resultado(texto, segundos=120, pagina="reportes")
                else:
                    self._poner_resultado(ultimo["mensaje"], error=not ultimo.get("cancelado"), segundos=120,
                                          pagina="reportes")
            self._rep_visto = numero
        elif (self._rep_enviado > float("-inf") and not self._rep_en_curso
              and ahora - self._rep_enviado > ESPERA_ORDEN_REPORTE_S):
            self._rep_enviado = float("-inf")
            self._poner_resultado("El equipo no aceptó el reporte", error=True, segundos=20, pagina="reportes")

    # ------------------------------------------------------------------ calibracion por puntos (D-048, D-049)
    def _toque_calibracion(self, control: str) -> None:
        if control == "b_volver":
            self._tx(P.orden_pagina("principal"))
        elif control in ("v_s1", "v_s2"):
            self._cal_sensor = int(control[-1])
            self._t_refresco = float("-inf")
        elif control in ("b_bajo", "b_aire"):
            self._cal_gas = 0.0 if control == "b_bajo" else REFERENCIA_AIRE
            self._t_refresco = float("-inf")
        elif control == "v_gas":
            self._editar_gas()
        elif control == "b_iniciar":
            self._iniciar_calibracion()

    def _editar_gas(self) -> None:
        """Abre el teclado numerico para escribir la concentracion del gas patron (no pide PIN: el PIN se pide al calibrar)."""
        self._regreso = "calibracion"
        self._entrada = tec.Entrada("gas")
        self._aviso_teclado = (f"Actual: {vistas.formato_gas(self._cal_gas)} %. Entre 0 y 100 %", False)
        self._tx(P.orden_pagina("teclado"))

    def _aceptar_gas(self, entrada: tec.Entrada) -> None:
        valor, motivo = tec.validar_gas(entrada.buffer)
        if valor is None:
            self._aviso_teclado = (motivo, True)
            return
        self._cal_gas, self._entrada = valor, None
        self._tx(P.orden_pagina("calibracion"))

    def _iniciar_calibracion(self) -> None:
        """Comprueba lo que la pantalla puede comprobar (para no pedir el PIN en balde) y pide PIN y confirmacion."""
        def aviso(texto: str) -> None:
            self._poner_resultado(texto, error=True, segundos=8, pagina="calibracion")

        n, gas = self._cal_sensor, self._cal_gas
        if n > len(self._sensores) or not self._sensores[n - 1]["habilitado"]:
            aviso(f"El Sensor {n} no está activo")
            return
        if not any(s["habilitado"] for i, s in enumerate(self._sensores) if i != n - 1):
            aviso("Encienda el otro sensor: debe seguir vigilando")
            return
        sensor_id = self._sensores[n - 1]["id"]
        punto = "alto" if gas >= 50.0 else "bajo"
        self._requerir_pin(lambda: self._confirmar(
            f"¿Calibrar el Sensor {n} con gas de {vistas.formato_gas(gas)} %?",
            f"Punto {punto}. El sensor debe tener ese gas ahora. Sus alarmas se suspenden y la pantalla se bloquea.",
            lambda: self._enviar_calibracion(sensor_id, gas), "calibracion"), "calibracion")

    def _enviar_calibracion(self, sensor_id: int, gas: float) -> None:
        identificador = self.cliente.enviar_orden("calibrar_punto", actor="pantalla", sensor_id=sensor_id, referencia_pct=gas)
        REGISTRO.info("calibracion del sensor %d con gas de %g %% pedida al nucleo (orden %s)", sensor_id, gas, identificador)
        self._cal_enviado = self._reloj()
        self._poner_resultado("Iniciando la calibración...", segundos=ESPERA_ORDEN_CALIBRACION_S, pagina="calibracion")

    def _leer_calibracion(self, ahora: float, estado: dict | None) -> None:
        """Toma del estado del nucleo si hay una calibracion en curso y el resultado de la ultima (solo el de las que terminan
        MIENTRAS se mira: lo anterior a esta interfaz es viejo y se ignora)."""
        cal = (estado or {}).get("calibracion")
        self._cal_en_curso = bool(cal and cal.get("en_curso"))
        if self._cal_en_curso:
            self._cal_enviado = float("-inf")
        if cal is None:
            return
        ultima = cal.get("ultima")
        numero = ultima["numero"] if ultima else None
        if numero != self._cal_visto:
            if self._cal_visto is not _SIN_VER and ultima is not None:
                self._cal_enviado = float("-inf")
                self._poner_resultado(f"{ultima['nombre']}: {ultima['mensaje']}",
                                      error=not ultima["ok"] and not ultima.get("cancelada"), segundos=120, pagina="calibracion")
            self._cal_visto = numero
        elif (self._cal_enviado > float("-inf") and not self._cal_en_curso
              and ahora - self._cal_enviado > ESPERA_ORDEN_CALIBRACION_S):
            self._cal_enviado = float("-inf")
            self._poner_resultado("El equipo no aceptó la calibración", error=True, segundos=20, pagina="calibracion")

    def _informacion_del_rango(self) -> tuple[str, bool]:
        """La linea ``i2``: cuantos dias y registros cubre el rango elegido, o por que no sirve (en rojo)."""
        try:
            dias = rango_reporte.validar(self._rep_desde, self._rep_hasta, self._hoy())     # type: ignore[arg-type]
        except rango_reporte.ErrorRango as error:
            return str(error), True
        if self._rep_registros is None:
            return f"{dias} día(s)", False
        if self._rep_registros == 0:
            return "Sin registros en esas fechas", True
        if self._rep_registros > rango_reporte.MAX_FILAS:
            return "Demasiados registros: elija menos días", True
        return f"{dias} día(s) · {self._rep_registros} registros por sensor", False

    # ------------------------------------------------------------------ red (D-040)
    def _toque_red(self, control: str) -> None:
        if control == "b_volver":
            self._tx(P.orden_pagina("principal"))
        elif control == "b_buscar":
            self.cliente.enviar_orden("red_buscar", actor="pantalla")
            self._poner_resultado("Buscando redes...", segundos=8, pagina="red")
        elif control == "b_conectar":
            self._requerir_pin(self._pedir_ssid, "red")
        elif control in ("n1", "n2", "n3", "n4"):
            indice = int(control[1]) - 1
            if indice < len(self._redes):
                red = self._redes[indice]
                self._requerir_pin(lambda: self._elegir_red_vista(red), "red")

    def _pedir_ssid(self) -> None:
        """Etapa 1 de escribir una red: su nombre."""
        self._texto, self._texto_etapa = txt.EntradaTexto(secreto=False, largo_max=32), "ssid"
        self._aviso_texto = ("Escriba el nombre exacto de la red (distingue mayúsculas)", False)
        self._ir("texto")

    def _elegir_red_vista(self, red: dict) -> None:
        """Se toco una red de la lista de redes cercanas: se salta escribir el nombre."""
        self._siguiente_etapa_de_red(red["ssid"], oculta=False, con_seguridad=bool(red["seguridad"]))

    def _siguiente_etapa_de_red(self, ssid: str, oculta: bool, con_seguridad: bool | None) -> None:
        """Tras tener el nombre: pide la contrasena (o confirma directo si la red es abierta).
        ``con_seguridad`` es None si la red no se vio en la busqueda (se admite una contrasena vacia = abierta)."""
        self._red_ssid, self._red_oculta = ssid, oculta
        self._clave_obligatoria = bool(con_seguridad)
        if con_seguridad is False:
            self._confirmar_red(ssid, "")
            return
        self._texto, self._texto_etapa = txt.EntradaTexto(secreto=True, largo_max=63), "clave"
        self._aviso_texto = (("Entre 8 y 63 caracteres" if self._clave_obligatoria
                              else "Entre 8 y 63 caracteres. Vacío = red abierta"), False)
        self._ir("texto")

    def _toque_texto(self, control: str) -> None:
        if self._texto is None:
            REGISTRO.debug("toque del teclado de texto sin una entrada activa: %s", control)
            return
        if control == "b_cancelar":
            self._soltar_texto()
            self._tx(P.orden_pagina("red"))
        elif control == "b_aceptar":
            self._aceptar_texto()
            self._t_refresco = float("-inf")
        elif self._texto.tecla(control):
            if self._aviso_texto[1]:
                self._aviso_texto = ("", False)                  # el error anterior ya no aplica
            self._t_refresco = float("-inf")

    def _aceptar_texto(self) -> None:
        entrada = self._texto
        assert entrada is not None
        if self._texto_etapa == "ssid":
            ssid = entrada.buffer
            if not ssid.strip():
                self._aviso_texto = ("Escriba el nombre de la red", True)
                return
            conocida = next((r for r in self._redes if r["ssid"] == ssid), None)
            self._siguiente_etapa_de_red(ssid, oculta=conocida is None,
                                         con_seguridad=None if conocida is None else bool(conocida["seguridad"]))
            return
        clave = entrada.buffer
        if self._clave_obligatoria and not clave:
            self._aviso_texto = ("Esta red necesita contraseña", True)
            return
        try:
            validar_credenciales(self._red_ssid or "", clave)
        except ErrorRed as error:
            self._aviso_texto = (str(error), True)
            return
        self._confirmar_red(self._red_ssid or "", clave)

    def _confirmar_red(self, ssid: str, clave: str) -> None:
        """Ultima etapa: pregunta Si / No. La contrasena solo vive en esta funcion hasta que se envia la orden."""
        detalle = "El equipo puede quedar sin red hasta un minuto. Si no logra conectarse, vuelve a la red anterior."
        if not clave:
            detalle = "Red abierta (sin contraseña). " + detalle
        oculta = self._red_oculta
        self._soltar_texto()
        self._confirmar(f"¿Conectar a «{ssid}»?", detalle,
                        lambda: self._pedir_cambio_de_red(ssid, clave, oculta), "red")

    def _pedir_cambio_de_red(self, ssid: str, clave: str, oculta: bool) -> None:
        identificador = self.cliente.enviar_orden("red_configurar", actor="pantalla", ssid=ssid, contrasena=clave,
                                                  oculta=oculta)
        REGISTRO.info("cambio de red pedido al nucleo: %r (orden %s)", ssid, identificador)   # nunca la contrasena
        self._poner_resultado("Enviando el cambio de red...", segundos=10, pagina="red")

    def _soltar_texto(self) -> None:
        self._texto, self._texto_etapa, self._red_ssid = None, "", None

    def _vista_texto(self) -> vistas.Vista | None:
        entrada = self._texto
        if entrada is None:
            return None
        titulo = ("Nombre de la red" if self._texto_etapa == "ssid"
                  else f"Contraseña de {(self._red_ssid or '')[:18]}")
        mensaje, error = self._aviso_texto
        return vistas.vista_texto(entrada, titulo=titulo, mensaje=mensaje, mensaje_es_error=error)

    # ------------------------------------------------------------------ confirmar
    def _confirmar(self, pregunta: str, detalle: str, al_aceptar: Callable[[], None], regreso: str) -> None:
        self._confirmacion = (pregunta, detalle, al_aceptar, regreso)
        self._tx(P.orden_pagina("confirmar"))

    def _toque_confirmar(self, control: str) -> None:
        if self._confirmacion is None:
            return
        _, _, al_aceptar, regreso = self._confirmacion
        self._confirmacion = None
        if control == "b_si":
            al_aceptar()
        self._tx(P.orden_pagina(regreso))

    # ------------------------------------------------------------------ teclado y PIN (D-038)
    def _bloqueado(self, ahora: float) -> bool:
        return ahora < self._bloqueado_hasta

    def _requerir_pin(self, continuacion: Callable[[], None], regreso: str) -> None:
        """Ejecuta ``continuacion`` si hay un PIN vigente; si no, abre el teclado a pedirlo y la ejecuta cuando
        sea correcto. ``regreso`` es la pagina a la que se vuelve si se cancela."""
        self._regreso = regreso
        if self._reloj() < self._pin_hasta:
            continuacion()
            return
        self._tras_pin = continuacion
        self._entrada = tec.Entrada("pin")
        self._aviso_teclado = ("Escriba el PIN y pulse Aceptar", False)
        self._tx(P.orden_pagina("teclado"))

    def _editar(self, clave: str, regreso: str) -> None:
        self._requerir_pin(lambda: self._abrir_valor(clave), regreso)

    def _abrir_valor(self, clave: str) -> None:
        self._entrada = tec.Entrada("valor", clave)
        self._aviso_teclado = (tec.ayuda_valor(clave, self._actual_texto(clave)), False)
        self._ir("teclado")

    def _actual_texto(self, clave: str) -> str:
        """Valor vigente de una clave, escrito como lo muestran las paginas (con su unidad)."""
        definicion = catalogo.obtener(clave)
        valor = self._config.get(clave, 0.0)
        unidad = definicion.unidad.replace(" O2", "")
        numero = f"{int(valor)}" if definicion.tipo == "entero" else f"{valor:.1f}"
        return f"{numero} {unidad}".strip()

    def _toque_teclado(self, control: str) -> None:
        if self._entrada is None:
            REGISTRO.debug("toque del teclado sin una entrada activa: %s", control)
            return
        ahora = self._reloj()
        if control == "b_cancelar":
            self._soltar_teclado()
            self._tx(P.orden_pagina(self._regreso))
        elif control == "b_aceptar":
            self._aceptar(ahora)
        elif control in CONTROLES_DEL_TECLADO:
            if self._bloqueado(ahora):
                return                                           # bloqueado: las teclas no hacen nada
            if self._entrada.tecla(control) and self._aviso_teclado[1]:
                self._aviso_teclado = ("", False)                # el error anterior ya no aplica
            self._t_refresco = float("-inf")

    def _aceptar(self, ahora: float) -> None:
        entrada = self._entrada
        assert entrada is not None
        if entrada.modo == "pin":
            self._aceptar_pin(entrada, ahora)
        elif entrada.modo == "fecha":
            self._aceptar_fecha(entrada)
        elif entrada.modo == "gas":
            self._aceptar_gas(entrada)
        else:
            self._aceptar_valor(entrada, ahora)
        self._t_refresco = float("-inf")

    def _aceptar_pin(self, entrada: tec.Entrada, ahora: float) -> None:
        if self._bloqueado(ahora):
            return
        activo = self.datos.pin_activo()
        if activo is None:                                       # fallo cerrado: sin PIN configurado no hay cambios
            self._aviso_teclado = ("PIN no configurado: no se permiten cambios", True)
            REGISTRO.error("se intento una accion protegida pero el equipo no tiene PIN configurado")
            return
        if len(entrada.buffer) < seguridad_pin.LARGO_MIN:
            self._aviso_teclado = (f"El PIN tiene al menos {seguridad_pin.LARGO_MIN} dígitos", True)
            return
        configuracion = self.datos.config_pin()
        if seguridad_pin.verificar(entrada.buffer, activo["sal"], activo["huella"], activo["iteraciones"]):
            self._fallos = 0
            self._pin_hasta = ahora + float(configuracion["pantalla.pin_vigencia_s"])
            self.cliente.enviar_orden("pin_resultado", actor="pantalla", resultado="aceptado")
            REGISTRO.info("PIN aceptado (%s); vale %d s", activo["tipo"], configuracion["pantalla.pin_vigencia_s"])
            continuacion, self._tras_pin, self._entrada = self._tras_pin, None, None
            if continuacion is not None:
                continuacion()                                   # lo que se quedo esperando el PIN
            else:
                self._ir(self._regreso)
            return
        self._fallos += 1
        entrada.buffer = ""
        permitidos = int(configuracion["pantalla.pin_intentos"])
        REGISTRO.warning("PIN incorrecto (%d de %d)", self._fallos, permitidos)
        if self._fallos >= permitidos:
            espera = float(configuracion["pantalla.pin_bloqueo_s"])
            self._bloqueado_hasta = ahora + espera
            self.cliente.enviar_orden("pin_resultado", actor="pantalla", resultado="bloqueado", intentos=self._fallos)
            REGISTRO.warning("teclado bloqueado %d s por intentos fallidos", espera)
            self._fallos = 0
            self._aviso_teclado = ("Escriba el PIN y pulse Aceptar", False)     # lo que se vera al terminar el bloqueo
        else:
            self.cliente.enviar_orden("pin_resultado", actor="pantalla", resultado="fallido", intentos=self._fallos)
            self._aviso_teclado = (f"PIN incorrecto. Intentos restantes: {permitidos - self._fallos}", True)

    def _aceptar_valor(self, entrada: tec.Entrada, ahora: float) -> None:
        clave = entrada.clave
        if ahora >= self._pin_hasta:                             # el PIN vencio mientras se tecleaba
            self._tras_pin = lambda: self._abrir_valor(clave)
            self._entrada = tec.Entrada("pin")
            self._aviso_teclado = ("El PIN venció: escríbalo otra vez", True)
            return
        valor, motivo = tec.validar_valor(clave, entrada.buffer, lambda k: str(self._config.get(k, 0.0)))
        if valor is None:
            self._aviso_teclado = (motivo, True)
            return
        identificador = self.cliente.enviar_orden("config_fijar", actor="pantalla", clave=clave, valor=valor)
        REGISTRO.info("cambio pedido al nucleo: %s = %s (orden %s)", clave, valor, identificador)
        self._entrada = None
        self._t_datos = ahora + self.ESPERA_CAMBIO_S - self.DATOS_S    # releer la base cuando el nucleo ya lo aplico
        self._tx(P.orden_pagina(self._regreso))

    def _vista_teclado(self, ahora: float) -> vistas.Vista | None:
        entrada = self._entrada
        if entrada is None:
            return None
        if self._bloqueado(ahora):
            restante = int(self._bloqueado_hasta - ahora) + 1
            mensaje, error = f"Bloqueado por intentos fallidos. Espere {restante} s", True
        else:
            mensaje, error = self._aviso_teclado
        if entrada.modo == "pin":
            titulo, rotulo = "Ingrese el PIN", "PIN"
        elif entrada.modo == "gas":
            titulo, rotulo = "Gas patrón", "Concentración de O2 (%)"
        elif entrada.modo == "fecha":
            titulo = "Fecha del reporte"
            rotulo = "Desde (día/mes/año)" if entrada.clave == "desde" else "Hasta (día/mes/año)"
        else:
            titulo, rotulo = "Ajustar", tec.ROTULOS[entrada.clave]
        return vistas.vista_teclado(titulo=titulo, rotulo=rotulo, valor=entrada.mostrar(),
                                    mensaje=mensaje, mensaje_es_error=error)

    # ------------------------------------------------------------------ pintar
    def _leer_datos(self, ahora: float) -> None:
        self._t_datos = ahora
        self._config = {**self.datos.config_alarmas(), **self.datos.config_general()}
        self._historial = self.datos.historial_alarmas(6)
        self._cola, self._red_texto = self.datos.cola_pendiente(), self._red()
        self._sensores = self.datos.sensores()
        self._equipo = self.datos.datos_del_equipo()
        self._calibraciones = self.datos.calibraciones_vigentes()
        self._zona = self.datos.zona_horaria()
        if self.pagina == "reportes" and self._rep_desde is not None and self._rep_hasta is not None:
            try:
                rango_reporte.validar(self._rep_desde, self._rep_hasta, self._hoy())
                self._rep_registros = self.datos.contar_registros(
                    *rango_reporte.limites_ms(self._rep_desde, self._rep_hasta, self._zona))
            except rango_reporte.ErrorRango:
                self._rep_registros = None
        activo = self.datos.pin_activo()
        self._pin_tipo = activo["tipo"] if activo else None

    def _refrescar(self, ahora: float) -> None:
        estado, edad = self.cliente.leer_estado()
        responde = estado is not None and edad <= self.max_edad_s
        self._muestrear(ahora, estado if responde else None)
        if ahora - self._t_fase >= self.MEDIO_PARPADEO_S:
            self._fase, self._t_fase = not self._fase, ahora
        if ahora - self._t_datos >= self.DATOS_S:
            self._leer_datos(ahora)
        self._atender_auditoria()
        self._leer_red(estado if responde else None)
        self._leer_reporte(ahora, estado if responde else None)
        self._leer_calibracion(ahora, estado if responde else None)
        self._aplicar_bloqueo(ahora)
        if (self.pagina == "reportes" and not self._rep_en_curso and not self._rep_usb_en_curso
                and ahora - self._rep_usb_pedido >= USB_CADA_S):
            self._rep_usb_pedido, self._rep_usb_en_curso = ahora, True
            nombre = self._equipo.get("equipo.nombre", "")
            self._segundo_plano(lambda: self._leer_usb(nombre))
        mensaje = None
        if self._mensaje is not None:
            if ahora < self._mensaje[1]:
                mensaje = self._mensaje[0]
            else:
                self._mensaje = None
        resultado, resultado_error = None, False
        if self._resultado is not None:
            if ahora >= self._resultado[2]:
                self._resultado = None
            elif self._resultado[3] == self.pagina:             # cada pagina muestra solo SUS resultados
                resultado, resultado_error = self._resultado[0], self._resultado[1]
        vista = None
        if self.pagina == "principal":
            vista = vistas.vista_principal(estado, nucleo_responde=responde, fase_encendida=self._fase,
                                           hora=self._hora(), red=self._red_texto, cola=self._cola,
                                           mensaje=mensaje)
        elif self.pagina == "alarmas" and self._config:
            vista = vistas.vista_alarmas(self._config, self._historial)
        elif self.pagina == "config" and self._config:
            vista = vistas.vista_config(self._config, self._sensores, self._equipo)
        elif self.pagina == "sistema":
            vista = vistas.vista_sistema(estado, nucleo_responde=responde, protocolo=self.protocolo_version,
                                         cola=self._cola, pin=self._pin_tipo, resultado=resultado,
                                         resultado_es_error=resultado_error)
        elif self.pagina == "red":
            red = (estado or {}).get("red") if responde else None
            vista = vistas.vista_red(self._red_info, self._redes, (red or {}).get("cambio"), nucleo_responde=responde,
                                     resultado=resultado, resultado_es_error=resultado_error)
        elif self.pagina == "reportes" and self._rep_desde is not None and self._rep_hasta is not None:
            reporte = ((estado or {}).get("reporte") or {}) if responde else {}
            informacion, informacion_error = self._informacion_del_rango()
            vista = vistas.vista_reportes(
                desde=rango_reporte.formato_fecha(self._rep_desde), hasta=rango_reporte.formato_fecha(self._rep_hasta),
                informacion=informacion, informacion_es_error=informacion_error,
                usb_texto=self._rep_usb[0], usb_lista=self._rep_usb[1], en_curso=self._pantalla_bloqueada(),
                progreso=int(reporte.get("progreso", 0)) if self._rep_en_curso else 0,
                avance=str(reporte.get("mensaje", "")) if self._rep_en_curso else "Iniciando el reporte...",
                resultado=resultado, resultado_es_error=resultado_error)
        elif self.pagina == "calibracion":
            vista = vistas.vista_calibracion(
                sensores=self._sensores, vivos=(estado or {}).get("sensores", []) if responde else [],
                calibraciones=self._calibraciones, elegido=self._cal_sensor, referencia=self._cal_gas,
                calibracion=(estado or {}).get("calibracion") if responde else None, en_curso=self._calibrando(),
                resultado=resultado, resultado_es_error=resultado_error)
        elif self.pagina == "texto":
            vista = self._vista_texto()
        elif self.pagina == "confirmar" and self._confirmacion is not None:
            vista = vistas.vista_confirmar(self._confirmacion[0], self._confirmacion[1])
        elif self.pagina == "teclado":
            vista = self._vista_teclado(ahora)
        elif self.pagina == "grafica":
            vista = vistas.vista_grafica(estado, nucleo_responde=responde, marcas=self._hist.marcas(),
                                         ventana=grafica.formato_ventana(self._hist.puntos * grafica.PERIODO_S))
        if vista is not None and ahora - self._t_pagina_pedida >= ESPERA_CARGA_S:
            # mientras llega el aviso de la pagina nueva, la pantalla ya no tiene los componentes de la vieja: pintarlos se rechazaria
            self._enviar_cambios(vista, escapar=self.pagina == "texto")
        self._decidir_grafica(ahora, estado if responde else None)
        self._atender_grafica(ahora)
        if (responde and estado.get("sonar") and ahora - self._t_sonido >= self.repetir_sonido_s
                and ahora >= self._sonido_callado_hasta):
            self._t_sonido = self._t_play = ahora
            self._tx(P.ORDEN_SONIDO_ALARMA)       # la repite la Pi: si se detiene, deja de sonar
        elif (responde and self._cal_en_curso and ahora - self._t_sonido >= self.repetir_sonido_s
              and ahora >= self._sonido_callado_hasta):
            self._t_sonido = self._t_play = ahora      # una alarma del otro sensor tiene prioridad (la rama de arriba)
            self._tx(P.ORDEN_SONIDO_CALIBRANDO)       # la voz «Calibrando», mientras dure

    # ------------------------------------------------------------------ grafica en tiempo (D-043)
    def _muestrear(self, ahora: float, estado: dict | None) -> None:
        """Una muestra por segundo de cada sensor, siempre (no solo con la grafica abierta): al abrirla ya hay historia."""
        if ahora - self._t_muestra < grafica.PERIODO_S:
            return
        self._t_muestra = ahora
        valores: list[float | None] = [None, None]
        if estado is not None:
            for i, s in enumerate(estado["sensores"][:2]):
                if s.get("estado") not in ("SIN SEÑAL", "APAGADO"):
                    valores[i] = s.get("o2")
        self._hist.agregar(valores)

    def _decidir_grafica(self, ahora: float, estado: dict | None) -> None:
        """Abre la grafica tras un rato sin tocar la pantalla (solo desde ``principal`` y sin alarmas por acusar) y la cierra
        si salta una alarma sin acusar o el nucleo deja de responder: el aviso rojo no puede quedar tapado."""
        sin_acusar = bool(estado.get("parpadeo")) if estado is not None else False
        repetido = ahora - self._t_cambio < ESPERA_CAMBIO_GRAFICA_S          # acaba de pedirse lo mismo: espera a la pantalla
        if self.pagina == "principal":
            espera = float(self._config.get("pantalla.grafica_espera_s", 0.0))
            if (not repetido and espera > 0 and self._grafica_disponible and estado is not None and not sin_acusar
                    and ahora - self._ultimo_toque >= espera):
                REGISTRO.info("grafica: %d s sin tocar la pantalla", espera)
                self._t_cambio, self._cambio_pedido = ahora, "grafica"
                self._tx(P.orden_pagina("grafica"))
        elif (self.pagina == "grafica" and (estado is None or sin_acusar)
              and not (repetido and self._cambio_pedido == "principal")):          # volver por una alarma no espera nada
            REGISTRO.info("grafica: vuelve a la principal (%s)",
                          "el nucleo no responde" if estado is None else "hay una alarma sin acusar")
            self._t_cambio, self._cambio_pedido, self._ultimo_toque = ahora, "principal", ahora
            self._cerrando_grafica = True
            self._tx(P.orden_pagina("principal"))

    def _atender_grafica(self, ahora: float) -> None:
        """Con la grafica abierta: la dibuja entera (al abrirla o al cambiar el eje o los limites) o le agrega los puntos nuevos."""
        if self.pagina != "grafica" or self._espera_datos is not None or self._cerrando_grafica:
            return
        cambio_eje = self._hist.ajustar_escala(ahora)
        limites = (float(self._config.get("alarma.o2_bajo_pct", 0.0)), float(self._config.get("alarma.o2_alto_pct", 100.0)))
        marca = (self._hist.bajo, self._hist.alto, limites)
        pendientes = self._hist.total - self._grafica_dibujada
        if cambio_eje or marca != self._grafica_marca or pendientes > self._hist.puntos:
            self._grafica_marca, self._grafica_dibujada = marca, self._hist.total
            self._tx(self._hist.orden_limpiar())
            if self._con_bloques:
                self._bloques = deque(self._hist.bloques_completos(limites))
                self._siguiente_bloque()
            else:
                for orden in self._hist.ordenes_completas(limites):
                    self._tx(orden)
        elif pendientes > 0:
            for orden in self._hist.ordenes_nuevas(pendientes, limites):
                self._tx(orden)
            self._grafica_dibujada = self._hist.total

    def _rechazo_de_la_grafica(self, descripcion: str) -> bool:
        """True si la pantalla rechazo una orden de la grafica (por ejemplo, el Waveform no se llama ``s0``): se cuenta, y a la
        tercera se desactiva la grafica y se vuelve a la principal, en vez de repetir el error dos veces por segundo."""
        if self.pagina != "grafica" or not any(o.startswith(("add s0.id", "addt s0.id", "cle s0.id"))
                                              for o in self._ultimas_ordenes):
            return False
        if not self._grafica_disponible or self._cerrando_grafica:     # lo que aun llega de ordenes ya canceladas no cuenta
            return True
        self._rechazos_grafica += 1
        if self._rechazos_grafica == 1:
            REGISTRO.warning("la pantalla rechazo una orden de la grafica: %s (ultimas enviadas: %s)", descripcion,
                             " | ".join(self._ultimas_ordenes))
        if self._rechazos_grafica >= RECHAZOS_PARA_DESACTIVAR_GRAFICA:
            REGISTRO.error("la pantalla rechaza las ordenes de la grafica (¿el componente Waveform se llama 's0'?): la grafica "
                           "queda desactivada hasta que la pantalla se reinicie")
            self._grafica_disponible, self._cerrando_grafica = False, True
            self._terminar_transferencia()
            self._t_cambio, self._cambio_pedido, self._ultimo_toque = self._reloj(), "principal", self._reloj()
            self._tx(P.orden_pagina("principal"))
        return True

    def _siguiente_bloque(self) -> None:
        """Pide a la pantalla recibir el proximo canal con ``addt``; los bytes salen cuando responde que esta lista."""
        if not self._bloques:
            self._terminar_transferencia()
            return
        canal, datos = self._bloques[0]
        self._tx_ahora(self._hist.orden_bloque(canal, len(datos)))
        self._espera_datos, self._t_espera = "listo", self._reloj()

    def _datos_listos(self) -> None:
        if self._espera_datos != "listo" or not self._bloques:
            return
        self.enlace.enviar_crudo(self._bloques[0][1])
        self._espera_datos, self._t_espera = "fin", self._reloj()

    def _datos_recibidos(self) -> None:
        if self._espera_datos != "fin":
            return
        self._bloques.popleft()
        self._espera_datos = None
        self._siguiente_bloque()

    def _terminar_transferencia(self, enviar: bool = True) -> None:
        """Cierra la transferencia (o la abandona) y envia lo que quedo esperando."""
        self._bloques.clear()
        self._espera_datos = None
        pendientes, self._diferidas = self._diferidas, []
        if enviar:
            for orden in pendientes:
                self._tx_ahora(orden)

    def _vigilar_transferencia(self, ahora: float) -> None:
        """Si la pantalla no responde al ``addt``, se deja de usarlo y la grafica se dibuja con ``add`` (mas lento pero seguro)."""
        if self._espera_datos is not None and ahora - self._t_espera > ESPERA_BLOQUE_S:
            REGISTRO.warning("la pantalla no respondio al addt (%s): la grafica se dibuja con 'add'", self._espera_datos)
            self._con_bloques = False
            self._terminar_transferencia()
            self._grafica_marca = None

    def _leer_red(self, estado: dict | None) -> None:
        """Toma del estado del nucleo la red, las redes cercanas y el resultado del ultimo cambio. El resultado solo se
        muestra si aparece MIENTRAS se mira (el de antes de arrancar esta interfaz es viejo y se ignora)."""
        red = (estado or {}).get("red")
        self._red_info = red["red"] if red else None
        self._redes = red["redes"] if red else []
        if not red:
            return
        ultimo = (red.get("cambio") or {}).get("ultimo")
        if ultimo != self._cambio_visto:
            if self._cambio_visto is not _SIN_VER and ultimo is not None:
                self._poner_resultado(ultimo["mensaje"], error=not ultimo["ok"], segundos=60, pagina="red")
            self._cambio_visto = ultimo

    def _enviar_cambios(self, vista: vistas.Vista, escapar: bool = False) -> None:
        """Envia solo lo que cambio respecto de lo que ya muestra la pantalla. Con ``escapar`` las comillas y barras de
        los textos se escapan (teclado de texto: hay que verlas tal cual)."""
        for clave, valor in vista.items():
            if self._cache.get(clave) != valor:
                self._tx(P.orden_asignar(clave, valor, escapar=escapar))
                self._cache[clave] = valor
