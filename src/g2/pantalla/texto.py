"""Teclado de texto completo de la pagina ``texto`` (D-040): letras, mayusculas, numeros y simbolos.

Sirve para escribir el nombre y la contrasena de una red WiFi, que pueden llevar cualquier caracter ASCII imprimible. La
pantalla solo tiene 40 teclas de caracteres (4 filas de 10) y unas pocas de control, asi que el teclado trabaja por
CAPAS: la Pi reescribe las etiquetas de las 40 teclas al cambiar de capa y, cuando llega un toque, traduce la posicion
de la tecla (``t_00`` a ``t_39``) al caracter que tiene en la capa actual. Asi la pantalla sigue siendo "tonta".

Es logica PURA: no habla con la pantalla ni con la red. La contrasena se VE mientras se escribe (para poder comprobar
que esta bien escrita: una clave mal tecleada hace perder tiempo y deja el equipo sin red); ``Ocultar`` la cambia a
asteriscos, por ejemplo si hay alguien mirando.
"""

from __future__ import annotations

TECLAS = 40                                                    # t_00 ... t_39
ANCHO_VISIBLE = 24                                             # caracteres que caben en el campo ``valor``
CAPAS = {
    "minusculas": "1234567890" "qwertyuiop" "asdfghjklñ" "zxcvbnm.-_",
    "mayusculas": "1234567890" "QWERTYUIOP" "ASDFGHJKLÑ" "ZXCVBNM.-_",
    # Los 32 simbolos ASCII imprimibles; los 8 espacios del final son teclas vacias (no hacen nada).
    "simbolos": "!@#$%^&*()" "-_=+[]{}|\\" ";:'\",./?<>" "~`" + " " * 8,
}
CAPA_INICIAL = "minusculas"


class EntradaTexto:
    """Lo que se esta escribiendo: un nombre de red (``secreto=False``) o una contrasena (``secreto=True``)."""

    def __init__(self, secreto: bool, largo_max: int, inicial: str = "") -> None:
        self.secreto, self.largo_max = secreto, largo_max
        self.buffer = inicial
        self.capa = CAPA_INICIAL
        self.visible = True                                     # tambien la contrasena: quien escribe debe poder comprobarla

    # ------------------------------------------------------------------ teclas
    def tecla(self, control: str) -> bool:
        """Aplica un toque (``t_07``, ``b_mayus``, ``b_borrar``...). Devuelve True si algo cambio (el texto, la capa o
        la visibilidad)."""
        antes = (self.buffer, self.capa, self.visible)
        if control.startswith("t_") and control[2:].isdigit() and int(control[2:]) < TECLAS:
            caracter = CAPAS[self.capa][int(control[2:])]
            if caracter != " " and len(self.buffer) < self.largo_max:      # " " en una capa es una tecla vacia
                self.buffer += caracter
        elif control == "b_espacio":
            if len(self.buffer) < self.largo_max:
                self.buffer += " "
        elif control == "b_borrar":
            self.buffer = self.buffer[:-1]
        elif control == "b_limpiar":
            self.buffer = ""
        elif control == "b_mayus":
            self.capa = "mayusculas" if self.capa == "minusculas" else "minusculas"
        elif control == "b_simbolos":
            self.capa = CAPA_INICIAL if self.capa == "simbolos" else "simbolos"
        elif control == "b_ver":
            if self.secreto:
                self.visible = not self.visible
        return (self.buffer, self.capa, self.visible) != antes

    # ------------------------------------------------------------------ lo que se muestra
    def mostrar(self) -> str:
        """Texto del campo ``valor``: asteriscos si es secreto y esta oculto; si no cabe, los ultimos caracteres."""
        texto = self.buffer if self.visible else "*" * len(self.buffer)
        if len(texto) > ANCHO_VISIBLE:
            texto = "..." + texto[-(ANCHO_VISIBLE - 3):]
        return texto

    def rotulos(self) -> list[str]:
        """Etiqueta de cada una de las 40 teclas en la capa actual (vacia si la tecla no hace nada)."""
        return [c if c != " " else "" for c in CAPAS[self.capa]]

    def rotulo_mayus(self) -> str:
        return "abc" if self.capa == "mayusculas" else "ABC"

    def rotulo_simbolos(self) -> str:
        return "abc" if self.capa == "simbolos" else "#+="

    def rotulo_ver(self) -> str:
        if not self.secreto:
            return ""
        return "Ocultar" if self.visible else "Ver"
