"""Datos que la interfaz lee de la base (SOLO LECTURA) y del sistema.

``g2-ui`` abre la base con ``mode=ro`` (D-005: el unico escritor es g2-core). Nada de aqui debe poder
derribar la interfaz: ante cualquier error se devuelven valores por omision y se reintenta despues.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from g2.almacenamiento import auditoria, base
from g2.almacenamiento.almacen import Almacen
from g2.configuracion import catalogo

REGISTRO = logging.getLogger("g2.pantalla")
CLAVES_ALARMAS = ("alarma.o2_bajo_pct", "alarma.o2_alto_pct", "alarma.o2_retardo_s",
                  "alarma.o2_histeresis_pct", "alarma.acuse_silencio_s")
CLAVES_PIN = ("pantalla.pin_vigencia_s", "pantalla.pin_intentos", "pantalla.pin_bloqueo_s")
CLAVES_GENERALES = ("muestreo.intervalo_guardado_s", "muestreo.intervalo_pantalla_s", "alarma.discrepancia_pct",
                    "pantalla.volumen", "pantalla.grafica_espera_s")


class DatosPantalla:
    """Lecturas de la base para las paginas (configuracion, historial de alarmas, cola de envio)."""

    def __init__(self, ruta_bd: Path) -> None:
        self.ruta = Path(ruta_bd)
        self._almacen: Almacen | None = None

    def _abrir(self) -> Almacen | None:
        if self._almacen is None:
            try:
                self._almacen = Almacen(base.abrir_lectura(self.ruta))
            except (sqlite3.Error, OSError) as error:
                REGISTRO.warning("no se pudo abrir la base para lectura: %s", error)
        return self._almacen

    def _fallo(self, error: Exception) -> None:
        REGISTRO.warning("lectura de la base fallo: %s", error)
        if self._almacen is not None:
            try:
                self._almacen.cerrar()
            except sqlite3.Error:
                pass
        self._almacen = None                                    # se reabre en el siguiente intento

    def _config(self, claves: tuple[str, ...]) -> dict[str, float]:
        """Valores de esas claves; con el valor por defecto de cada una si no se puede leer la base."""
        valores = {k: float(catalogo.obtener(k).defecto) for k in claves}
        almacen = self._abrir()
        if almacen is not None:
            try:
                for clave in claves:
                    valores[clave] = float(almacen.config_tipada(clave))
            except (sqlite3.Error, ValueError, KeyError) as error:
                self._fallo(error)
        return valores

    def config_alarmas(self) -> dict[str, float]:
        """Los cinco ajustes de la pagina de alarmas."""
        return self._config(CLAVES_ALARMAS)

    def config_general(self) -> dict[str, float]:
        """Los ajustes de la pagina ``config`` que son numeros."""
        return self._config(CLAVES_GENERALES)

    def datos_del_equipo(self) -> dict[str, str]:
        """Nombre e identificador del equipo (texto; vacios si no se han definido)."""
        valores = {"equipo.nombre": "", "equipo.id": ""}
        almacen = self._abrir()
        if almacen is not None:
            try:
                for clave in valores:
                    valores[clave] = almacen.config_obtener(clave)
            except (sqlite3.Error, KeyError) as error:
                self._fallo(error)
        return valores

    def sensores(self) -> list[dict]:
        """Los sensores dados de alta (con su estado habilitado), por orden."""
        almacen = self._abrir()
        if almacen is None:
            return []
        try:
            return almacen.listar_sensores()
        except sqlite3.Error as error:
            self._fallo(error)
            return []

    def verificar_auditoria(self) -> tuple[bool, int]:
        """Verifica la cadena de auditoria de TODA la base: ``(correcta, numero_de_diferencias)``. Puede tardar
        (crece con la base), asi que la interfaz la corre en segundo plano; abre su propia conexion de solo
        lectura. Si no se puede verificar, se considera NO correcta."""
        try:
            conexion = base.abrir_lectura(self.ruta)
        except (sqlite3.Error, OSError) as error:
            REGISTRO.warning("no se pudo abrir la base para verificar la auditoria: %s", error)
            return False, -1
        try:
            problemas = auditoria.verificar(conexion)
        except sqlite3.Error as error:
            REGISTRO.warning("la verificacion de la auditoria fallo: %s", error)
            return False, -1
        finally:
            conexion.close()
        return not problemas, len(problemas)

    def config_pin(self) -> dict[str, float]:
        """Vigencia del PIN, intentos permitidos y tiempo de bloqueo (D-038)."""
        return self._config(CLAVES_PIN)

    def pin_activo(self) -> dict | None:
        """El PIN que rige hoy (sal y huella, nunca el PIN), o ``None`` si no hay ninguno o no se puede leer:
        sin PIN la pantalla no permite cambios (falla cerrada)."""
        almacen = self._abrir()
        if almacen is None:
            return None
        try:
            return almacen.pin_activo()
        except sqlite3.Error as error:
            self._fallo(error)
            return None

    def historial_alarmas(self, cantidad: int = 6) -> list[dict]:
        """Las alarmas mas recientes, la mas nueva primero."""
        almacen = self._abrir()
        if almacen is None:
            return []
        try:
            filas = almacen.db.execute(
                "SELECT codigo, sensor_id, estado, inicio_ms FROM alarma "
                "ORDER BY inicio_ms DESC, id DESC LIMIT ?", (cantidad,)).fetchall()
            return [dict(f) for f in filas]
        except sqlite3.Error as error:
            self._fallo(error)
            return []

    def cola_pendiente(self) -> int:
        """Registros de la cola de envio que aun no confirma la plataforma."""
        almacen = self._abrir()
        if almacen is None:
            return 0
        try:
            return int(almacen.db.execute(
                "SELECT COUNT(*) FROM cola_envio WHERE estado IN ('pendiente', 'enviado')").fetchone()[0])
        except sqlite3.Error as error:
            self._fallo(error)
            return 0


def estado_red(carpeta: Path = Path("/sys/class/net")) -> str:
    """``CABLE OK``, ``WIFI OK`` o ``SIN RED`` segun el estado del enlace (no prueba internet)."""
    for interfaz, texto in (("eth0", "CABLE OK"), ("wlan0", "WIFI OK")):
        try:
            if (carpeta / interfaz / "operstate").read_text().strip() == "up":
                return texto
        except OSError:
            continue
    return "SIN RED"
