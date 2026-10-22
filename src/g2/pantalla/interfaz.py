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

Pendiente (siguientes etapas): las paginas reportes y calibracion.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Callable, Protocol

from g2.configuracion import catalogo
from g2.ipc import ClienteNucleo
from g2.pantalla import protocolo as P
from g2.pantalla import teclado as tec
from g2.pantalla import texto as txt
from g2.pantalla import vistas
from g2.pantalla.protocolo import (CodigoResultado, Evento, PaginaCargada, PantallaEncendida,
                                   RespuestaNumero, Toque)
from g2.red.gestor import ErrorRed, validar_credenciales
from g2.seguridad import pin as seguridad_pin

REGISTRO = logging.getLogger("g2.pantalla")

PAGINAS_EN_CONSTRUCCION = ("b_calib",)
MENSAJE_EN_CONSTRUCCION = "Página en construcción"
CONTROLES_DEL_TECLADO = set(tec.DIGITOS) | {"k_punto", "k_signo", "b_borrar", "b_limpiar"}
DURACION_RESULTADO_S = 20.0
VOLUMEN_MINIMO = 10                      # lo mas bajo al que la proteccion deja el volumen
BAJA_DE_VOLUMEN = 20                     # cuanto baja el volumen cada vez que la pantalla se reinicia al sonar
VENTANA_REINICIOS_S = 60.0               # reinicios por sonido que se cuentan juntos
REINICIOS_PARA_CALLAR = 3                # a este numero de reinicios se desactiva el sonido
SONIDO_CALLADO_S = 600.0                 # por cuanto tiempo (la alarma visual y los relevos siguen igual)
GRACIA_SONIDO_S = 4.0                    # un reinicio tan pronto despues de un `play` se atribuye al sonido
_SIN_VER = object()                       # marca: todavia no se ha visto el estado del cambio de red


class Enlace(Protocol):
    def enviar(self, orden: str) -> None: ...
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
                 segundo_plano: Callable[[Callable[[], None]], None] = _en_hilo) -> None:
        self.enlace, self.cliente, self.datos = enlace, cliente, datos
        self._reloj, self._hora, self._red = reloj, hora, red
        self.repetir_sonido_s, self.max_edad_s, self.mensaje_s = repetir_sonido_s, max_edad_s, mensaje_s
        self._segundo_plano = segundo_plano
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

    # ------------------------------------------------------------------ arranque
    def iniciar(self) -> None:
        """Fija el volumen y lleva la pantalla a la pagina principal; el resto lo hace el evento de pagina cargada."""
        self._fijar_volumen()
        self._tx(P.orden_pagina("principal"))

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
            self._soltar_teclado()
            self._soltar_texto()
            self._confirmacion = None
            self._cache.clear()
            self._tx(P.orden_pagina("principal"))
        elif isinstance(evento, PaginaCargada):
            REGISTRO.info("pagina cargada: %s", evento.pagina)
            self.pagina = evento.pagina
            if evento.pagina != "teclado":
                self._soltar_teclado()                       # se salio del teclado por otra via
            if evento.pagina != "texto":
                self._soltar_texto()                         # y lo que se escribia (puede ser una contrasena) se descarta
            if evento.pagina != "confirmar":
                self._confirmacion = None
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
        elif isinstance(evento, CodigoResultado):
            if evento.codigo != 0x01:
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
        REGISTRO.info("toque: %s.%s", toque.pagina, toque.control)
        pagina, control = toque.pagina, toque.control
        if pagina == "principal":
            self._toque_principal(control)
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
        elif pagina == "teclado":
            self._toque_teclado(control)
        elif pagina == "confirmar":
            self._toque_confirmar(control)
        else:
            REGISTRO.debug("toque sin accion: %s.%s", pagina, control)

    def _toque_principal(self, control: str) -> None:
        destinos = {"b_alarmas": "alarmas", "b_config": "config", "b_sistema": "sistema", "b_red": "red"}
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
            self._poner_resultado("Reportes: próxima etapa")
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
        activo = self.datos.pin_activo()
        self._pin_tipo = activo["tipo"] if activo else None

    def _refrescar(self, ahora: float) -> None:
        estado, edad = self.cliente.leer_estado()
        responde = estado is not None and edad <= self.max_edad_s
        if ahora - self._t_fase >= self.MEDIO_PARPADEO_S:
            self._fase, self._t_fase = not self._fase, ahora
        if ahora - self._t_datos >= self.DATOS_S:
            self._leer_datos(ahora)
        self._atender_auditoria()
        self._leer_red(estado if responde else None)
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
        elif self.pagina == "texto":
            vista = self._vista_texto()
        elif self.pagina == "confirmar" and self._confirmacion is not None:
            vista = vistas.vista_confirmar(self._confirmacion[0], self._confirmacion[1])
        elif self.pagina == "teclado":
            vista = self._vista_teclado(ahora)
        if vista is not None:
            self._enviar_cambios(vista, escapar=self.pagina == "texto")
        if (responde and estado.get("sonar") and ahora - self._t_sonido >= self.repetir_sonido_s
                and ahora >= self._sonido_callado_hasta):
            self._t_sonido = self._t_play = ahora
            self._tx(P.ORDEN_SONIDO_ALARMA)       # la repite la Pi: si se detiene, deja de sonar

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
