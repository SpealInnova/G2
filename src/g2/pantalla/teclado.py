"""Logica del teclado numerico de la pantalla (pagina ``teclado``): que se esta tecleando, el buffer y la
validacion de los valores, con mensajes pensados para leerse en la pantalla (D-038).

Es logica PURA: no habla con la pantalla ni con la base. La interfaz le pasa cada tecla y le pregunta que
mostrar. La pantalla no guarda nada de lo tecleado (principio 1 de la especificacion del HMI): cada tecla
avisa a la Pi, que lleva el buffer; y en modo PIN muestra un asterisco por digito.
"""

from __future__ import annotations

from typing import Callable

from g2.configuracion import catalogo
from g2.configuracion.catalogo import ErrorConfig
from g2.seguridad import pin as seguridad_pin

# (pagina, boton) -> clave de configuracion que edita (secciones 8 y 11 de la especificacion).
EDITABLES = {("alarmas", "v_bajo"): "alarma.o2_bajo_pct", ("alarmas", "v_alto"): "alarma.o2_alto_pct",
             ("alarmas", "v_retardo"): "alarma.o2_retardo_s", ("alarmas", "v_histeresis"): "alarma.o2_histeresis_pct",
             ("alarmas", "v_acuse"): "alarma.acuse_silencio_s",
             ("config", "v_guardado"): "muestreo.intervalo_guardado_s",
             ("config", "v_pantalla"): "muestreo.intervalo_pantalla_s",
             ("config", "v_discrepancia"): "alarma.discrepancia_pct"}
ROTULOS = {"alarma.o2_bajo_pct": "Oxígeno bajo (%)", "alarma.o2_alto_pct": "Oxígeno alto (%)",
           "alarma.o2_retardo_s": "Retardo (s)", "alarma.o2_histeresis_pct": "Histéresis (%)",
           "alarma.acuse_silencio_s": "Tiempo de acuse (s)",
           "muestreo.intervalo_guardado_s": "Guardado de datos (s)",
           "muestreo.intervalo_pantalla_s": "Actualizar pantalla (s)",
           "alarma.discrepancia_pct": "Diferencia entre sensores (%)"}
# Pagina a la que se vuelve al cancelar o terminar un cambio.
PAGINA_DE = {"alarmas": "alarmas", "config": "config"}
LARGO_MAX_VALOR = 8
DIGITOS = {f"k_{d}": str(d) for d in range(10)}


class Entrada:
    """Lo que se esta tecleando: un PIN (``modo = "pin"``) o el valor de una clave (``"valor"``)."""

    def __init__(self, modo: str, clave: str | None = None) -> None:
        if modo not in ("pin", "valor"):
            raise ValueError(modo)
        self.modo, self.clave, self.buffer = modo, clave, ""
        self.entero = bool(clave) and catalogo.obtener(clave).tipo == "entero"

    @property
    def largo_max(self) -> int:
        return seguridad_pin.LARGO_MAX if self.modo == "pin" else LARGO_MAX_VALOR

    def tecla(self, control: str) -> bool:
        """Aplica una tecla; devuelve True si el buffer cambio. El punto solo se admite en un valor real
        y una sola vez; ``±`` se ignora porque ningun ajuste actual admite negativos."""
        antes = self.buffer
        if control in DIGITOS:
            if len(self.buffer) < self.largo_max:
                self.buffer += DIGITOS[control]
        elif control == "k_punto":
            if self.modo == "valor" and not self.entero and "." not in self.buffer:
                self.buffer += "." if self.buffer else "0."
        elif control == "b_borrar":
            self.buffer = self.buffer[:-1]
        elif control == "b_limpiar":
            self.buffer = ""
        return self.buffer != antes

    def mostrar(self) -> str:
        """Texto del campo ``valor``: asteriscos si es un PIN, para que no se lea por encima del hombro."""
        return "*" * len(self.buffer) if self.modo == "pin" else self.buffer


def _rango(clave: str) -> str:
    c = catalogo.obtener(clave)
    unidad = f" {c.unidad}" if c.unidad else ""
    return f"Entre {c.minimo:g} y {c.maximo:g}{unidad}"


def ayuda_valor(clave: str, actual: str) -> str:
    """Mensaje al abrir el teclado de un valor: el valor vigente y el rango permitido."""
    return f"Actual: {actual}. {_rango(clave)}"


def validar_valor(clave: str, texto: str, leer_actual: Callable[[str], str]) -> tuple[str | None, str]:
    """Valida lo tecleado con las MISMAS reglas del catalogo que aplica el nucleo.

    Devuelve ``(valor_normalizado, "")`` si es valido o ``(None, mensaje)`` con el motivo en lenguaje claro.
    ``leer_actual(clave)`` entrega el valor vigente de otra clave (para reglas como minimo < maximo).
    """
    if not texto:
        return None, "Escriba un valor"
    definicion = catalogo.obtener(clave)
    try:
        nuevo = catalogo.normalizar(definicion, texto.rstrip("."))      # "20." se toma como 20
    except ErrorConfig:
        return None, _rango(clave)                                        # fuera de limites o no numerico
    try:
        catalogo.validar_relaciones(clave, nuevo, leer_actual)
    except ErrorConfig:
        if clave == "alarma.o2_bajo_pct":
            return None, f"Debe ser menor que el máximo ({float(leer_actual('alarma.o2_alto_pct')):g} %)"
        if clave == "alarma.o2_alto_pct":
            return None, f"Debe ser mayor que el mínimo ({float(leer_actual('alarma.o2_bajo_pct')):g} %)"
        return None, "El valor no cumple las reglas entre ajustes"
    return nuevo, ""
