"""Protocolo de la pantalla Nextion NX8048P050 en G2 (ver nextion/ESPECIFICACION_HMI.md).

Es la UNICA fuente de los codigos de pagina y de control: los usan la interfaz (g2-ui) y la herramienta
de banco (tools/banco/pantalla.py). Si cambia la especificacion del HMI, se cambia aqui.

Pantalla -> Pi: tramas terminadas en ``FF FF FF``:
    65 PP CC 00   toque (PP = codigo de pagina, CC = codigo de control; ver las tablas de abajo)
    88            la pantalla acaba de encender
    67 xx xx yy yy S   toque en cualquier punto (con ``sendxy=1``): coordenadas x, y y S = 1 al pulsar, 0 al soltar
    FE            lista para recibir los datos de un ``addt``;  FD  termino de recibirlos
    70 ...        respuesta de texto a un ``get``;  71 xx xx xx xx   respuesta numerica (little endian)
    00 / 01 / 1A  etc.: codigo de resultado de una orden

Pi -> pantalla: ordenes de Nextion en iso-8859-1 terminadas en ``FF FF FF``, por ejemplo
``principal.o2_1.txt="20.9"`` o ``page alarmas``.
"""

from __future__ import annotations

from dataclasses import dataclass

FIN = b"\xff\xff\xff"
VERSION_PROTOCOLO = 1                       # valor de principal.proto en el HMI

# ---- Codigos de pagina (PP) y de control (CC), seccion 2 de la especificacion ---------------------
PAGINAS = {0x00: "principal", 0x01: "alarmas", 0x02: "config", 0x03: "red", 0x04: "calibracion",
           0x05: "sistema", 0x06: "teclado", 0x07: "reportes", 0x08: "confirmar", 0x09: "texto",
           0x0A: "grafica"}
CODIGO_PAGINA = {nombre: codigo for codigo, nombre in PAGINAS.items()}
PAGINA_CARGADA = 0xFE                       # CC comun a todas las paginas (Postinitialize)

CONTROLES: dict[int, dict[int, str]] = {
    0x00: {0x01: "b_alarmas", 0x02: "b_config", 0x03: "b_red", 0x04: "b_calib",
           0x05: "b_sistema", 0x06: "b_acuse"},
    0x01: {0x01: "v_bajo", 0x02: "v_alto", 0x03: "v_retardo", 0x04: "v_histeresis",
           0x05: "v_acuse", 0x06: "b_volver"},
    0x02: {0x01: "v_guardado", 0x02: "v_pantalla", 0x03: "v_discrepancia", 0x04: "v_sensor1",
           0x05: "v_sensor2", 0x06: "b_volver"},
    0x03: {0x01: "b_conectar", 0x02: "b_buscar", 0x03: "n1", 0x04: "n2", 0x05: "n3", 0x06: "n4",
           0x07: "b_volver"},
    0x05: {0x01: "b_reportes", 0x02: "b_servicios", 0x03: "b_reiniciar", 0x04: "b_auditoria",
           0x05: "b_volver"},
    0x06: {**{0x10 + d: f"k_{d}" for d in range(10)}, 0x1A: "k_punto", 0x1B: "k_signo",
           0x1C: "b_borrar", 0x1D: "b_limpiar", 0x1E: "b_cancelar", 0x1F: "b_aceptar"},
    0x08: {0x01: "b_si", 0x02: "b_no"},
    0x0A: {0x01: "salir"},                  # grafica: un toque en cualquier parte vuelve a la principal
    # Teclado de texto: 40 teclas de caracteres (t_00 a t_39, codigos 00 a 27) y las de control.
    0x09: {**{n: f"t_{n:02d}" for n in range(40)}, 0x30: "b_mayus", 0x31: "b_simbolos", 0x32: "b_espacio",
           0x33: "b_borrar", 0x34: "b_limpiar", 0x35: "b_ver", 0x36: "b_cancelar", 0x37: "b_aceptar"},
}

# ---- Colores RGB565 en decimal, seccion 4 de la especificacion --------------------------------------
COLOR = {"fondo": 63423, "tarjeta": 65535, "texto": 6438, "texto_suave": 25423, "barra": 6504,
         "normal": 1128, "alarma": 51427, "aviso": 62880, "calibrando": 726, "inactivo": 27568,
         "boton": 57085, "boton_pulsado": 48730, "blanco": 65535,
         "sensor1": 6969, "sensor2": 58306}              # colores de las lineas de la grafica (azul y naranja)

CODIGOS_RESPUESTA = {0x00: "orden invalida", 0x01: "orden correcta", 0x02: "componente inexistente",
                     0x03: "pagina inexistente", 0x04: "imagen inexistente", 0x05: "fuente inexistente",
                     0x1A: "variable o atributo invalido", 0x1B: "operacion con variable invalida",
                     0x1C: "error al asignar", 0x1D: "error de EEPROM", 0x1E: "parametros invalidos",
                     0x1F: "error de E/S", 0x20: "escape invalido", 0x23: "nombre muy largo"}


# ---- Eventos que llegan de la pantalla ------------------------------------------------------------------
@dataclass(frozen=True)
class Toque:
    pagina: str
    control: str
    pulsado: bool = False


@dataclass(frozen=True)
class PaginaCargada:
    pagina: str


@dataclass(frozen=True)
class PantallaEncendida:
    pass


@dataclass(frozen=True)
class TocarPantalla:
    """Toque en cualquier punto de la pantalla (llega con ``sendxy=1``): sirve para saber que alguien la esta usando."""
    x: int
    y: int
    pulsado: bool


@dataclass(frozen=True)
class ListoParaDatos:
    """La pantalla esta lista para recibir los bytes de un ``addt``."""


@dataclass(frozen=True)
class DatosRecibidos:
    """La pantalla recibio todos los bytes de un ``addt``."""


@dataclass(frozen=True)
class RespuestaNumero:
    valor: int


@dataclass(frozen=True)
class RespuestaTexto:
    texto: str


@dataclass(frozen=True)
class CodigoResultado:
    codigo: int
    descripcion: str


@dataclass(frozen=True)
class Desconocido:
    datos: bytes


Evento = (Toque | PaginaCargada | PantallaEncendida | TocarPantalla | ListoParaDatos | DatosRecibidos
          | RespuestaNumero | RespuestaTexto | CodigoResultado | Desconocido)


def interpretar(trama: bytes) -> Evento:
    """Convierte UNA trama (sin los FF FF FF finales) en un evento. Los codigos que no estan en las
    tablas no se ocultan: salen como ``pagina?09`` o ``control?7F`` para verlos en el registro."""
    if not trama:
        return Desconocido(b"")
    tipo = trama[0]
    if tipo == 0x65 and len(trama) == 4:
        pagina, control, pulsado = trama[1], trama[2], trama[3]
        nombre_pagina = PAGINAS.get(pagina, f"pagina?{pagina:02X}")
        if control == PAGINA_CARGADA:
            return PaginaCargada(nombre_pagina)
        nombre = CONTROLES.get(pagina, {}).get(control, f"control?{control:02X}")
        return Toque(nombre_pagina, nombre, pulsado != 0)
    if tipo == 0x88 and len(trama) == 1:
        return PantallaEncendida()
    if tipo == 0x67 and len(trama) == 6:
        return TocarPantalla(int.from_bytes(trama[1:3], "big"), int.from_bytes(trama[3:5], "big"), trama[5] != 0)
    if tipo == 0xFE and len(trama) == 1:
        return ListoParaDatos()
    if tipo == 0xFD and len(trama) == 1:
        return DatosRecibidos()
    if tipo == 0x70:
        return RespuestaTexto(trama[1:].decode("iso-8859-1", errors="replace"))
    if tipo == 0x71 and len(trama) == 5:
        return RespuestaNumero(int.from_bytes(trama[1:], "little", signed=True))
    if tipo in CODIGOS_RESPUESTA and len(trama) == 1:
        return CodigoResultado(tipo, CODIGOS_RESPUESTA[tipo])
    return Desconocido(bytes(trama))


def separar(buffer: bytes) -> tuple[list[bytes], bytes]:
    """Parte el buffer en tramas completas (terminadas en FF FF FF) y devuelve lo que sobra."""
    tramas = []
    while True:
        i = buffer.find(FIN)
        if i < 0:
            return tramas, buffer
        tramas.append(buffer[:i])
        buffer = buffer[i + 3:]


def describir(evento: Evento) -> str:
    """Texto legible de un evento (para el registro y la herramienta de banco)."""
    if isinstance(evento, Toque):
        return f"toque: {evento.pagina}.{evento.control}" + (" (pulsado)" if evento.pulsado else "")
    if isinstance(evento, PaginaCargada):
        return f"pagina cargada: {evento.pagina}"
    if isinstance(evento, PantallaEncendida):
        return "pantalla encendida (lista)"
    if isinstance(evento, TocarPantalla):
        return f"toque en ({evento.x}, {evento.y})" + (" (pulsado)" if evento.pulsado else " (soltado)")
    if isinstance(evento, ListoParaDatos):
        return "lista para recibir datos"
    if isinstance(evento, DatosRecibidos):
        return "datos recibidos"
    if isinstance(evento, RespuestaTexto):
        return f"texto: {evento.texto}"
    if isinstance(evento, RespuestaNumero):
        return f"numero: {evento.valor}"
    if isinstance(evento, CodigoResultado):
        return f"respuesta: {evento.descripcion}"
    return "trama desconocida: " + evento.datos.hex(" ").upper()


# ---- Ordenes hacia la pantalla ----------------------------------------------------------------------------
def codificar_orden(orden: str) -> bytes:
    """Orden de Nextion lista para enviar: texto en iso-8859-1 y terminador FF FF FF."""
    return orden.encode("iso-8859-1", errors="replace") + FIN


def _limpiar_texto(texto: str) -> str:
    """Nextion no admite comillas ni saltos de linea dentro de un texto: se sustituyen."""
    return texto.replace('"', "'").replace("\r", " ").replace("\n", " ")


def orden_asignar(clave: str, valor: str | int, escapar: bool = False) -> str:
    """``principal.o2_1.txt`` + ``"20.9"``  ->  ``principal.o2_1.txt="20.9"``; un entero va sin comillas.

    Con ``escapar=True`` las comillas y las barras invertidas del texto se escapan (``\\"`` y ``\\\\``) en lugar de
    sustituirse: lo usan las teclas del teclado de texto y el campo que muestra lo escrito, donde SI hay que ver
    esos caracteres. POR COMPROBAR con la pantalla real (ver ESPECIFICACION_HMI.md)."""
    if isinstance(valor, str):
        if escapar:
            limpio = valor.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")
            return f'{clave}="{limpio}"'
        return f'{clave}="{_limpiar_texto(valor)}"'
    return f"{clave}={int(valor)}"


def orden_pagina(nombre: str) -> str:
    if nombre not in CODIGO_PAGINA:
        raise ValueError(f"pagina desconocida: {nombre!r}")
    return f"page {nombre}"


ORDEN_SONIDO_ALARMA = "play 0,1,0"          # canal 0, audio 1 (alarma.wav), una vez
ORDEN_LEER_PROTOCOLO = "get principal.proto.val"
ORDEN_INFORMAR_TOQUES = "sendxy=1"          # la pantalla avisa de CUALQUIER toque (no solo de los botones)
