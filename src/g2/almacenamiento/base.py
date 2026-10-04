"""Apertura de conexiones a la base de datos interna de G2.

Regla de propiedad (decision D-009): un solo proceso, ``g2-core``, escribe en la
base. Los demas servicios (``g2-uplink``, ``g2-ui``) la abren en modo solo
lectura con :func:`abrir_lectura`, y piden los cambios a ``g2-core`` por el
socket local. Asi no hay escrituras concurrentes que se bloqueen entre si.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

# Tiempo maximo, en milisegundos, que una conexion espera si la base esta
# ocupada, antes de fallar con "database is locked".
ESPERA_OCUPADA_MS = 5000


def _sha256(texto: str | None) -> str | None:
    """Huella SHA-256 (64 caracteres hexadecimales) de un texto UTF-8.

    SQLite no trae una funcion de huella propia; se registra esta para que los
    disparadores de la cadena de auditoria (migracion 003) puedan calcularla.
    """
    if texto is None:
        return None
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def registrar_funciones(conexion: sqlite3.Connection) -> None:
    """Registra en la conexion las funciones SQL propias de G2 (``sha256``).

    Toda conexion que escriba en tablas de auditoria la necesita: si falta, los
    disparadores fallan con "no such function" y la escritura se rechaza. Es
    deliberado: una escritura hecha con una herramienta externa (por ejemplo el
    cliente ``sqlite3``) no puede saltarse la cadena de auditoria en silencio.
    """
    conexion.create_function("sha256", 1, _sha256, deterministic=True)


def _configurar(conexion: sqlite3.Connection, *, solo_lectura: bool) -> None:
    """Aplica los PRAGMA comunes a toda conexion.

    ``foreign_keys`` se activa en cada conexion porque SQLite lo deja apagado
    por omisia; sin esto las referencias entre tablas no se verifican.
    """
    conexion.execute("PRAGMA foreign_keys = ON")
    conexion.execute(f"PRAGMA busy_timeout = {ESPERA_OCUPADA_MS}")
    if solo_lectura:
        # Aun si el codigo se equivoca, esta conexion no puede modificar datos.
        conexion.execute("PRAGMA query_only = ON")


def abrir_escritura(ruta: str | Path) -> sqlite3.Connection:
    """Abre (o crea) la base con permiso de escritura. Solo para ``g2-core``.

    Configuracion de durabilidad:
      * ``journal_mode = WAL``: las escrituras se anotan en un archivo aparte;
        una caida de energia no corrompe la base y los lectores no bloquean al
        escritor.
      * ``synchronous = NORMAL``: en modo WAL no hay riesgo de corrupcion; en
        un corte de energia solo podrian perderse las ultimas transacciones
        aun no volcadas. Se elige sobre ``FULL`` para reducir las escrituras a
        la tarjeta SD (menos desgaste y menos consumo).

    Devuelve una conexion con ``isolation_level = None`` (autocommit): las
    transacciones se controlan de forma explicita con BEGIN/COMMIT, de modo
    que nunca quede una transaccion abierta sin que el codigo lo note.

    Raises:
        sqlite3.Error: si la base no se puede abrir o configurar.
    """
    conexion = sqlite3.connect(str(ruta), isolation_level=None)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA journal_mode = WAL")
    conexion.execute("PRAGMA synchronous = NORMAL")
    _configurar(conexion, solo_lectura=False)
    registrar_funciones(conexion)
    return conexion


def abrir_lectura(ruta: str | Path) -> sqlite3.Connection:
    """Abre la base existente solo para lectura (``g2-uplink`` y ``g2-ui``).

    Raises:
        sqlite3.OperationalError: si el archivo no existe (no se crea uno nuevo).
    """
    uri = Path(ruta).resolve().as_uri() + "?mode=ro"
    conexion = sqlite3.connect(uri, uri=True, isolation_level=None)
    conexion.row_factory = sqlite3.Row
    _configurar(conexion, solo_lectura=True)
    registrar_funciones(conexion)  # la verificacion de la cadena la usa al leer
    return conexion
