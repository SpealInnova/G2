"""Catalogo de claves de configuracion (D-027): unica fuente de verdad.

Cada clave declara su tipo, su valor por defecto, sus limites y quien puede cambiarla
(``pantalla`` = la Nextion, ``plataforma`` = la web, ``local`` = herramientas por SSH y
el propio equipo). La base de datos guarda solo el valor vigente (tabla ``config``) y
cada cambio (tabla ``config_historial``); este modulo decide que valores son validos.

Los valores por defecto vienen de D-027 (definidos por el usuario) y de las propuestas que
el usuario acepto. Una clave nueva se agrega aqui y se siembra sola al abrir la base.
"""

from __future__ import annotations

from dataclasses import dataclass

ORIGENES_EDICION = frozenset({"pantalla", "plataforma", "local"})
TODOS = ORIGENES_EDICION
SOLO_LOCAL = frozenset({"local"})

TIPOS = ("entero", "real", "texto", "booleano")


class ErrorConfig(Exception):
    """Clave desconocida, valor invalido u origen sin permiso."""


@dataclass(frozen=True)
class Clave:
    nombre: str
    tipo: str                           # entero | real | texto | booleano
    defecto: str                        # siempre como texto, ya normalizado
    descripcion: str
    unidad: str = ""
    minimo: float | None = None
    maximo: float | None = None
    editable_por: frozenset[str] = TODOS


def _c(nombre, tipo, defecto, descripcion, unidad="", minimo=None, maximo=None, editable_por=TODOS):
    return Clave(nombre, tipo, str(defecto), descripcion, unidad, minimo, maximo, editable_por)


_LISTA = [
    # --- Identidad del equipo (se fija al instalar; solo localmente) -----------------------
    _c("equipo.id", "texto", "", "Identificador del equipo ante la plataforma (equipo_id).",
       editable_por=SOLO_LOCAL),
    _c("equipo.nombre", "texto", "", "Nombre descriptivo del equipo.", editable_por=SOLO_LOCAL),

    # --- Muestreo (D-027) --------------------------------------------------------------------
    _c("muestreo.intervalo_guardado_s", "entero", 15,
       "Cada cuanto se guarda un registro de lecturas en la base (promedio, minimo y maximo).",
       "s", 1, 3600),
    _c("muestreo.intervalo_pantalla_s", "entero", 1,
       "Cada cuanto se actualiza la pantalla Nextion.", "s", 1, 60),
    _c("plataforma.intervalo_visualizacion_s", "entero", 15,
       "Cada cuanto la plataforma web muestra datos nuevos de este equipo.", "s", 1, 3600),

    # --- Alarmas de oxigeno (D-027): configurables por pantalla y plataforma ---------------------
    _c("alarma.o2_bajo_pct", "real", 20.0,
       "Alarma de oxigeno bajo: se activa cuando el oxigeno es menor que este valor.",
       "% O2", 0, 100),
    _c("alarma.o2_alto_pct", "real", 92.0,
       "Alarma de oxigeno alto: se activa cuando el oxigeno es mayor que este valor.",
       "% O2", 0, 100),
    _c("alarma.o2_retardo_s", "entero", 10,
       "Tiempo que la condicion debe mantenerse antes de activar la alarma.", "s", 0, 600),
    _c("alarma.o2_histeresis_pct", "real", 0.5,
       "Margen para desactivar la alarma (evita que oscile en el limite).", "% O2", 0, 10),
    _c("alarma.discrepancia_pct", "real", 0.5,
       "Diferencia entre sensores a partir de la cual se alarma por discrepancia.", "% O2", 0, 10),

    # --- Salud de la Raspberry Pi (D-011, D-013, D-027) ------------------------------------------
    _c("salud.intervalo_min", "entero", 30, "Cada cuanto se registra el estado de salud.",
       "min", 1, 1440),
    _c("salud.temp_cpu_aviso_c", "real", 60.0,
       "Temperatura del procesador de la Raspberry Pi que dispara el aviso.", "°C", 30, 90),
    _c("salud.ram_aviso_pct", "real", 85.0, "Uso de memoria RAM que dispara el aviso.", "%", 10, 100),
    _c("salud.disco_aviso_libre_pct", "real", 20.0,
       "Espacio libre en la tarjeta por debajo del cual se avisa (junto con el valor en GB).",
       "%", 1, 90),
    _c("salud.disco_aviso_libre_gb", "real", 2.0,
       "Espacio libre en GB por debajo del cual se avisa (lo que ocurra primero).", "GB", 0.1, 1000),
    _c("salud.disco_critico_libre_pct", "real", 10.0,
       "Espacio libre por debajo del cual la alarma es critica.", "%", 1, 90),
    _c("salud.disco_critico_libre_gb", "real", 1.0,
       "Espacio libre en GB por debajo del cual la alarma es critica.", "GB", 0.1, 1000),
    _c("salud.repeticion_min_s", "entero", 300,
       "Tiempo minimo entre dos registros de salud por la misma causa.", "s", 10, 86400),

    # --- Eventos y retencion (D-010) --------------------------------------------------------------
    _c("evento.agrupar_s", "entero", 60,
       "Eventos identicos dentro de este tiempo se agrupan en un solo registro.", "s", 0, 3600),
    _c("retencion.lectura_dias", "entero", 365,
       "Dias que se conservan las lecturas (solo se borra lo ya confirmado por la plataforma).",
       "dias", 1, 3650),
    _c("retencion.evento_dias", "entero", 365,
       "Dias que se conservan los eventos (solo lo confirmado por la plataforma).", "dias", 1, 3650),
    _c("retencion.salud_dias", "entero", 14,
       "Dias que se conserva el estado de salud (solo lo confirmado por la plataforma).",
       "dias", 1, 3650),

    # --- Estado interno (no lo edita el usuario) ---------------------------------------------------
    _c("sistema.apagado_limpio", "booleano", 1,
       "Marca interna: 1 si el nucleo termino de forma ordenada la ultima vez.",
       editable_por=SOLO_LOCAL),
]

CLAVES: dict[str, Clave] = {c.nombre: c for c in _LISTA}

# Reglas entre claves: (clave_a, "<", clave_b) exige a < b.
RELACIONES = [
    ("alarma.o2_bajo_pct", "<", "alarma.o2_alto_pct"),
    ("salud.disco_critico_libre_pct", "<", "salud.disco_aviso_libre_pct"),
    ("salud.disco_critico_libre_gb", "<", "salud.disco_aviso_libre_gb"),
]

_VERDADEROS = {"1", "true", "si", "sí", "yes", "on"}
_FALSOS = {"0", "false", "no", "off"}


def obtener(nombre: str) -> Clave:
    try:
        return CLAVES[nombre]
    except KeyError:
        raise ErrorConfig(f"clave de configuracion desconocida: {nombre!r}") from None


def normalizar(clave: Clave, valor: object) -> str:
    """Convierte ``valor`` al texto canonico de su tipo y verifica los limites.

    Raises:
        ErrorConfig: si el valor no es del tipo o sale de los limites.
    """
    try:
        if clave.tipo == "entero":
            texto = str(valor).strip()
            numero = float(texto)
            if numero != int(numero):
                raise ValueError("no es entero")
            canonico = str(int(numero))
        elif clave.tipo == "real":
            numero = float(str(valor).strip())
            if numero != numero or numero in (float("inf"), float("-inf")):
                raise ValueError("no es un numero finito")
            canonico = repr(numero)
        elif clave.tipo == "booleano":
            texto = str(valor).strip().lower()
            if texto in _VERDADEROS:
                canonico, numero = "1", 1.0
            elif texto in _FALSOS:
                canonico, numero = "0", 0.0
            else:
                raise ValueError("use 1/0, true/false o si/no")
        else:                                           # texto
            canonico = str(valor).strip()
            if len(canonico) > 200:
                raise ValueError("maximo 200 caracteres")
            return canonico
    except (ValueError, TypeError) as error:
        raise ErrorConfig(f"{clave.nombre}: valor {valor!r} no valido ({error})") from None

    if clave.tipo in ("entero", "real"):
        if clave.minimo is not None and numero < clave.minimo:
            raise ErrorConfig(f"{clave.nombre}: {canonico} es menor que el minimo {clave.minimo}")
        if clave.maximo is not None and numero > clave.maximo:
            raise ErrorConfig(f"{clave.nombre}: {canonico} es mayor que el maximo {clave.maximo}")
    return canonico


def validar_relaciones(nombre: str, nuevo: str, leer) -> None:
    """Verifica las reglas entre claves con el valor ``nuevo`` de ``nombre``.

    ``leer(clave)`` devuelve el valor vigente (texto) de otra clave.

    Raises:
        ErrorConfig: si el cambio dejaria dos claves en una relacion invalida.
    """
    for a, _op, b in RELACIONES:
        if nombre not in (a, b):
            continue
        va = float(nuevo if nombre == a else leer(a))
        vb = float(nuevo if nombre == b else leer(b))
        if not va < vb:
            raise ErrorConfig(f"{a} ({va}) debe ser menor que {b} ({vb})")


def verificar_catalogo() -> list[str]:
    """Autocomprobacion: cada valor por defecto debe ser valido. Devuelve los problemas."""
    problemas = []
    for clave in CLAVES.values():
        if clave.tipo not in TIPOS:
            problemas.append(f"{clave.nombre}: tipo desconocido {clave.tipo}")
            continue
        try:
            if normalizar(clave, clave.defecto) != clave.defecto and clave.tipo != "real":
                problemas.append(f"{clave.nombre}: el defecto no esta normalizado")
        except ErrorConfig as error:
            problemas.append(str(error))
    for a, _op, b in RELACIONES:
        if not float(CLAVES[a].defecto) < float(CLAVES[b].defecto):
            problemas.append(f"los defectos de {a} y {b} incumplen su relacion")
    return problemas
