"""Aplicacion ordenada de las migraciones SQL de la base de datos interna.

Cada migracion es un archivo ``NNN_descripcion.sql`` en la carpeta ``sql/``. El
numero ``NNN`` es la version del esquema. Reglas:

  * Las migraciones se aplican en orden numerico, una sola vez.
  * Una migracion ya publicada no se edita: los cambios se hacen con una
    migracion nueva (asi el historial del esquema es auditable).
  * Cada migracion corre dentro de una transaccion: o se aplica completa o no
    se aplica nada.
  * La version aplicada se guarda en ``PRAGMA user_version`` y en la tabla
    ``esquema_version`` (con fecha y descripcion).
"""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

CARPETA_SQL = Path(__file__).parent / "sql"
_PATRON = re.compile(r"^(\d{3})_(.+)\.sql$")


class ErrorMigracion(Exception):
    """Una migracion no se pudo aplicar o el conjunto de archivos es invalido."""


def _listar(carpeta: Path) -> list[tuple[int, str, Path]]:
    """Devuelve las migraciones ordenadas como (version, descripcion, ruta).

    Raises:
        ErrorMigracion: si hay versiones repetidas o con huecos (por ejemplo
            existe la 003 pero no la 002), lo que indicaria un archivo perdido.
    """
    encontradas = []
    for ruta in carpeta.glob("*.sql"):
        coincide = _PATRON.match(ruta.name)
        if coincide:
            encontradas.append((int(coincide.group(1)), coincide.group(2), ruta))
    encontradas.sort(key=lambda m: m[0])
    versiones = [m[0] for m in encontradas]
    if versiones != list(range(1, len(versiones) + 1)):
        raise ErrorMigracion(f"Las versiones de migracion deben ser 1..N sin huecos: {versiones}")
    return encontradas


def version_actual(conexion: sqlite3.Connection) -> int:
    """Version del esquema aplicada en la base (0 si esta vacia)."""
    return conexion.execute("PRAGMA user_version").fetchone()[0]


def migrar(conexion: sqlite3.Connection, carpeta: Path = CARPETA_SQL) -> int:
    """Aplica las migraciones pendientes y devuelve la version final.

    La conexion debe estar en modo autocommit (``isolation_level = None``),
    como la entrega :func:`g2.almacenamiento.base.abrir_escritura`.

    Raises:
        ErrorMigracion: si la base tiene una version mas nueva que el codigo
            (se impide ejecutar codigo viejo sobre una base nueva) o si una
            migracion falla. Ante un fallo se revierte esa migracion.
    """
    migraciones = _listar(carpeta)
    actual = version_actual(conexion)
    ultima = migraciones[-1][0] if migraciones else 0
    if actual > ultima:
        raise ErrorMigracion(
            f"La base esta en la version {actual} y este codigo solo conoce hasta la {ultima}."
        )

    for version, descripcion, ruta in migraciones:
        if version <= actual:
            continue
        sql = ruta.read_text(encoding="utf-8")
        try:
            # executescript no abre transaccion por si mismo: la abrimos aqui
            # para que el DDL y el registro de version sean atomicos.
            conexion.executescript("BEGIN;\n" + sql)
            conexion.execute(
                "INSERT INTO esquema_version (version, descripcion, aplicada_ms) VALUES (?, ?, ?)",
                (version, descripcion, int(time.time() * 1000)),
            )
            conexion.execute(f"PRAGMA user_version = {int(version)}")
            conexion.execute("COMMIT")
        except sqlite3.Error as error:
            if conexion.in_transaction:
                conexion.execute("ROLLBACK")
            raise ErrorMigracion(f"Fallo la migracion {ruta.name}: {error}") from error
    return ultima
