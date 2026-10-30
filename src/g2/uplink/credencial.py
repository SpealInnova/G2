"""El secreto del equipo ante la plataforma: un archivo aparte, de uso exclusivo del usuario (D-022, D-042).

No va en el codigo, ni en la base (que se sincroniza y se respalda), ni en la configuracion, ni en el repositorio. Se guarda
con ``g2ctl plataforma-credencial`` (se pide sin mostrarlo). Cada equipo tiene el suyo: robar uno no sirve para los demas.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

NOMBRE = "plataforma.secreto"
MIN_LARGO = 24                              # un secreto generado (p. ej. 32 bytes en base64 o hexadecimal) tiene mas
MAX_LARGO = 256
_VALIDO = re.compile(r"[A-Za-z0-9._~+/=-]+")      # va en una cabecera HTTP: nada de espacios ni caracteres raros


class ErrorCredencial(Exception):
    """No hay secreto, no es valido o el archivo esta al alcance de otros usuarios."""


def carpeta() -> Path:
    return Path(os.environ.get("G2_SECRETOS") or Path.home() / "g2" / "secretos")


def validar(secreto: str) -> str:
    secreto = secreto.strip()
    if not MIN_LARGO <= len(secreto) <= MAX_LARGO or not _VALIDO.fullmatch(secreto):
        raise ErrorCredencial(f"El secreto debe tener entre {MIN_LARGO} y {MAX_LARGO} caracteres, sin espacios "
                              "(letras, numeros y . _ ~ + / = -)")
    return secreto


def guardar(secreto: str, donde: Path | None = None) -> Path:
    """Guarda el secreto (sustituye el anterior) en un archivo 0600 dentro de una carpeta 0700."""
    secreto = validar(secreto)
    donde = Path(donde) if donde else carpeta()
    donde.mkdir(parents=True, exist_ok=True)
    try:
        donde.chmod(0o700)
    except OSError:
        pass
    ruta = donde / NOMBRE
    temporal = ruta.with_name(f".{NOMBRE}.{os.getpid()}.tmp")
    descriptor = os.open(temporal, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as archivo:
        archivo.write(secreto + "\n")
    os.replace(temporal, ruta)
    return ruta


def leer(donde: Path | None = None) -> str:
    """El secreto guardado. Se niega si el archivo lo pueden leer otros usuarios (alguien lo copio o lo creo a mano)."""
    ruta = (Path(donde) if donde else carpeta()) / NOMBRE
    try:
        modo = ruta.stat().st_mode
        texto = ruta.read_text(encoding="ascii")
    except FileNotFoundError:
        raise ErrorCredencial("No hay secreto guardado (use: python3 -m g2.ctl plataforma-credencial)") from None
    except (OSError, UnicodeDecodeError) as error:
        raise ErrorCredencial(f"No se pudo leer el secreto: {error}") from None
    if os.name == "posix" and stat.S_IMODE(modo) & 0o077:
        raise ErrorCredencial(f"El archivo del secreto es legible por otros usuarios ({ruta}); corrija con chmod 600")
    return validar(texto)


def existe(donde: Path | None = None) -> bool:
    return ((Path(donde) if donde else carpeta()) / NOMBRE).is_file()
