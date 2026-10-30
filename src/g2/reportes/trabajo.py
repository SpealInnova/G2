"""El trabajo completo de un reporte, de la orden a la memoria USB (D-044).

Corre en un PROCESO aparte (``python3 -m g2.reportes``) que lanza g2-core: dibujar cientos de paginas es trabajo de CPU en
Python y, en el mismo proceso del nucleo, le quitaria tiempo a la lectura de los sensores y al latido del watchdog. Asi el
nucleo sigue igual y, si el reporte falla, solo falla el reporte. Lee la base en SOLO LECTURA; el nucleo es quien registra
el resultado (evento ``REPORTE_GENERADO`` / ``REPORTE_FALLIDO``).

Pasos (cada uno avisa su avance con ``emitir``):
  1. comprueba el nombre del equipo (es la contrasena) y el rango de fechas;
  2. busca la memoria USB: debe llamarse igual que el equipo (si no, se para ANTES de gastar tiempo en dibujar);
  3. lee las lecturas y alarmas, y verifica la cadena de auditoria;
  4. dibuja el PDF y lo cifra (AES-256, contrasena = nombre del equipo);
  5. lo copia a la memoria con su huella SHA-256, lo verifica leyendolo de vuelta y la desmonta.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Callable

from g2 import __version__
from g2.almacenamiento import auditoria, base
from g2.reportes import consulta, pdf, rango, usb

REGISTRO = logging.getLogger("g2.reportes")


class Cancelado(Exception):
    """El reporte se cancelo a peticion del usuario."""


def _configuracion(db: sqlite3.Connection, clave: str) -> str:
    fila = db.execute("SELECT valor FROM config WHERE clave = ?", (clave,)).fetchone()
    return str(fila["valor"]) if fila else ""


def nombre_archivo(desde: date, hasta: date, generado_ms: int, nombre_zona: str) -> str:
    """``G2_reporte_2026-10-27_a_2026-10-27_20261027-1015.pdf``. No lleva el nombre del equipo: es la contrasena."""
    fecha, hora = rango.texto_hora(generado_ms, nombre_zona)
    d, m, a = fecha.split("/")
    return f"G2_reporte_{desde.isoformat()}_a_{hasta.isoformat()}_{a}{m}{d}-{hora[:2]}{hora[3:5]}.pdf"


def ejecutar(ruta_bd: Path, desde: date, hasta: date, *, emitir: Callable[[dict], None],
             cancelado: Callable[[], bool] = lambda: False, carpeta_tmp: Path | None = None,
             destino: Path | None = None, ejecutor: usb.Ejecutor = usb.correr,
             ahora_ms: Callable[[], int] | None = None) -> dict:
    """Genera el reporte y lo deja en la memoria USB (o, con ``destino``, en esa carpeta: pruebas y uso por SSH).

    ``emitir`` recibe ``{"fase": ..., "progreso": 0-100, "mensaje": ...}`` a medida que avanza.

    Returns:
        ``{"archivo", "sha256", "filas", "paginas", "cadena_integra", "desmontada", "desde", "hasta"}``

    Raises:
        rango.ErrorRango, usb.ErrorUsb, pdf.ErrorReporte: con un mensaje apto para la pantalla.
        Cancelado: si ``cancelado()`` se vuelve verdadero.
    """
    reloj = ahora_ms or (lambda: int(time.time() * 1000))
    propio = carpeta_tmp is None
    carpeta = Path(tempfile.mkdtemp(prefix="g2-reporte-")) if propio else Path(carpeta_tmp)
    carpeta.mkdir(parents=True, exist_ok=True)

    def avanzar(fase: str, progreso: int, mensaje: str) -> None:
        if cancelado():
            raise Cancelado()
        emitir({"fase": fase, "progreso": progreso, "mensaje": mensaje})

    try:
        conexion = base.abrir_lectura(ruta_bd)
        try:
            nombre = _configuracion(conexion, "equipo.nombre").strip()
            equipo_id = _configuracion(conexion, "equipo.id").strip()
            nombre_zona = _configuracion(conexion, "reporte.zona_horaria") or "America/Bogota"
            if not nombre:
                raise pdf.ErrorReporte("Defina el nombre del equipo (es la contraseña del reporte)")
            rango.validar(desde, hasta, rango.hoy(nombre_zona, reloj()))

            particion = None
            if destino is None:
                avanzar("usb", 2, "Buscando la memoria USB...")
                particion = usb.buscar(nombre, ejecutor)

            avanzar("leyendo", 6, "Leyendo los registros...")
            datos = consulta.construir(conexion, desde, hasta, nombre_zona)
            if not datos.filas:
                raise rango.ErrorRango("No hay registros en esas fechas")
            avanzar("auditoria", 12, "Verificando la auditoría...")
            try:
                cadena = (not (problemas := auditoria.verificar(conexion)), len(problemas))
            except sqlite3.Error:
                cadena = None
        finally:
            conexion.close()

        generado = reloj()
        portada = pdf.Portada(nombre=nombre, equipo_id=equipo_id, version_sw=__version__, generado_ms=generado,
                              cadena=cadena)
        sin_cifrar, cifrado = carpeta / "reporte-sin-cifrar.pdf", carpeta / "reporte.pdf"
        avanzar("dibujando", 20, f"Dibujando {pdf.total_paginas(datos)} páginas...")
        try:
            paginas = pdf.dibujar(datos, portada, sin_cifrar,
                                  progreso=lambda p: emitir({"fase": "dibujando", "progreso": 20 + p * 65 // 100,
                                                             "mensaje": f"Dibujando páginas... {p} %"}),
                                  cancelado=cancelado)
        except pdf.Cancelado:
            raise Cancelado() from None
        avanzar("cifrando", 88, "Protegiendo con contraseña...")
        pdf.cifrar(sin_cifrar, cifrado, nombre)
        sin_cifrar.unlink(missing_ok=True)                              # el PDF abierto no se queda en el equipo

        archivo = nombre_archivo(desde, hasta, generado, nombre_zona)
        avanzar("copiando", 92, "Copiando a la memoria USB...")
        desmontada = True
        if destino is not None:
            destino.mkdir(parents=True, exist_ok=True)
            final, huella = usb.copiar(cifrado, destino, archivo)
        else:
            assert particion is not None
            montaje, montamos = usb.montar(particion, ejecutor)
            try:
                final, huella = usb.copiar(cifrado, montaje, archivo)
            finally:
                desmontada = usb.desmontar(particion, montamos, ejecutor)
        emitir({"fase": "listo", "progreso": 100, "mensaje": "Reporte listo"})
        return {"archivo": final.name, "sha256": huella, "filas": len(datos.filas), "paginas": paginas,
                "cadena_integra": None if cadena is None else cadena[0], "desmontada": desmontada,
                "desde": datos.desde, "hasta": datos.hasta}
    finally:
        if propio:
            shutil.rmtree(carpeta, ignore_errors=True)
        else:
            for sobrante in ("reporte-sin-cifrar.pdf", "reporte.pdf"):
                (carpeta / sobrante).unlink(missing_ok=True)
