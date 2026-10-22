"""PIN de acceso: formato, huella y verificacion (D-038).

El PIN nunca se guarda ni se registra: solo su huella PBKDF2-HMAC-SHA256 con una sal propia de cada equipo
(``pin_acceso``). Un PIN de 4 digitos tiene solo 10 000 posibilidades: la huella no lo protege de quien
pueda LEER la base, por eso la tabla no se sincroniza ni se publica; lo que protege el PIN en la practica es
el limite de intentos de la pantalla. Las 100 000 iteraciones encarecen cada intento (unos 0.1-0.3 s en una
Raspberry Pi 3), y la comparacion es de tiempo constante.
"""

from __future__ import annotations

import hashlib
import hmac
import os

ITERACIONES = 100_000
LARGO_SAL = 16
LARGO_MIN, LARGO_MAX = 4, 8


class ErrorPin(ValueError):
    """El PIN no tiene un formato valido."""


def validar_formato(pin: str) -> str:
    """Devuelve el PIN si son entre 4 y 8 digitos numericos (el teclado de la pantalla solo tiene numeros)."""
    if not isinstance(pin, str) or not pin.isascii() or not pin.isdigit() or not LARGO_MIN <= len(pin) <= LARGO_MAX:
        raise ErrorPin(f"el PIN debe tener entre {LARGO_MIN} y {LARGO_MAX} digitos numericos")
    return pin


def calcular_huella(pin: str, sal: bytes, iteraciones: int = ITERACIONES) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), sal, iteraciones)


def nueva_huella(pin: str, iteraciones: int = ITERACIONES) -> tuple[bytes, bytes, int]:
    """``(sal, huella, iteraciones)`` de un PIN nuevo, con una sal aleatoria."""
    validar_formato(pin)
    sal = os.urandom(LARGO_SAL)
    return sal, calcular_huella(pin, sal, iteraciones), iteraciones


def verificar(pin: str, sal: bytes, huella: bytes, iteraciones: int) -> bool:
    """True si ``pin`` corresponde a la huella. Cualquier texto que no sea un PIN valido da False."""
    try:
        validar_formato(pin)
    except ErrorPin:
        return False
    return hmac.compare_digest(calcular_huella(pin, bytes(sal), int(iteraciones)), bytes(huella))
