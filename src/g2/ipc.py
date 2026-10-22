"""Comunicacion local entre el nucleo (g2-core) y la interfaz (g2-ui) por archivos en /run/g2.

Por que archivos y no un socket: son faciles de inspeccionar (``cat /run/g2/estado.json``), se
prueban igual en un PC que en la Raspberry Pi, no dejan puertos abiertos y viven en memoria
(``/run`` es tmpfs: no desgastan la tarjeta SD). Tienen permisos del usuario del servicio.

  * ``estado.json``     lo escribe el nucleo (cada ~1 s, de forma atomica); lo lee la interfaz. Trae la hora
                        de publicacion: si es vieja, la interfaz sabe que el nucleo no responde.
  * ``ordenes/*.json``  las escribe la interfaz (una orden por archivo); el nucleo las recoge, las
                        registra en la tabla ``comando`` (D-009, trazabilidad) y las borra.

La interfaz NUNCA escribe en la base de datos (D-005): todo cambio pasa por el nucleo.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

NOMBRE_ESTADO = "estado.json"
CARPETA_ORDENES = "ordenes"


def carpeta_por_defecto() -> Path | None:
    """Carpeta de ``G2_RUN`` si la variable existe; si no, None (sin comunicacion)."""
    valor = os.environ.get("G2_RUN")
    return Path(valor) if valor else None


def _escribir_atomico(ruta: Path, datos: bytes, modo: int = 0o644) -> None:
    """Escribe a un archivo temporal y lo renombra: quien lee ve el archivo viejo o el nuevo, nunca
    uno a medias. ``modo`` son los permisos del archivo (las ordenes usan 0600: pueden llevar una contrasena)."""
    temporal = ruta.with_name(f".{ruta.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporal, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, modo)
    with os.fdopen(descriptor, "wb") as archivo:
        archivo.write(datos)
    os.replace(temporal, ruta)


class PublicadorEstado:
    """Lado del nucleo: publica el estado y recoge las ordenes de la interfaz."""

    def __init__(self, carpeta: Path, reloj=time.time) -> None:
        self.carpeta = Path(carpeta)
        self._reloj = reloj
        self.carpeta.mkdir(parents=True, exist_ok=True)
        (self.carpeta / CARPETA_ORDENES).mkdir(exist_ok=True)
        self._secuencia = 0

    def publicar(self, estado: dict) -> None:
        self._secuencia += 1
        documento = {**estado, "publicado_s": self._reloj(), "secuencia": self._secuencia}
        _escribir_atomico(self.carpeta / NOMBRE_ESTADO, json.dumps(documento, ensure_ascii=False).encode("utf-8"))

    def recoger_ordenes(self) -> list[dict]:
        """Lee y BORRA las ordenes pendientes, en el orden en que se enviaron. Una orden ilegible se
        descarta (y se borra) para que no bloquee a las demas."""
        ordenes: list[dict] = []
        for ruta in sorted((self.carpeta / CARPETA_ORDENES).glob("*.json")):
            try:
                ordenes.append(json.loads(ruta.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
            try:
                ruta.unlink()
            except OSError:
                pass
        return ordenes


class ClienteNucleo:
    """Lado de la interfaz: lee el estado del nucleo y le envia ordenes."""

    def __init__(self, carpeta: Path, reloj=time.time) -> None:
        self.carpeta = Path(carpeta)
        self._reloj = reloj
        self._contador = 0

    def leer_estado(self) -> tuple[dict | None, float]:
        """``(estado, edad_s)``: el ultimo estado publicado y hace cuantos segundos. Sin archivo o
        ilegible: ``(None, inf)``."""
        try:
            documento = json.loads((self.carpeta / NOMBRE_ESTADO).read_text(encoding="utf-8"))
            return documento, max(0.0, self._reloj() - float(documento["publicado_s"]))
        except (OSError, ValueError, KeyError):
            return None, float("inf")

    def enviar_orden(self, tipo: str, **datos) -> str:
        """Deja una orden para el nucleo. Devuelve su identificador unico (uuid): con el se registra en
        la tabla ``comando`` y se evita ejecutarla dos veces."""
        carpeta = self.carpeta / CARPETA_ORDENES
        carpeta.mkdir(parents=True, exist_ok=True)
        self._contador += 1
        identificador = str(uuid.uuid4())
        orden = {"uuid": identificador, "tipo": tipo, "origen": "pantalla", **datos,
                 "enviada_s": self._reloj()}
        nombre = f"{int(self._reloj() * 1000):016d}-{self._contador:06d}-{identificador[:8]}.json"
        # Solo el dueno (el usuario de los servicios) la lee: una orden de red lleva la contrasena en claro, y el
        # nucleo la borra apenas la recoge. Vive en /run (memoria), nunca en la tarjeta SD.
        _escribir_atomico(carpeta / nombre, json.dumps(orden, ensure_ascii=False).encode("utf-8"), 0o600)
        return identificador
