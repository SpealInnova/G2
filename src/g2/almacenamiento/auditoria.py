"""Verificacion de la cadena de auditoria (decision D-016, migracion 003).

La cadena la construyen los disparadores de la base de datos; este modulo solo
la **verifica**. Se puede ejecutar con una conexion de solo lectura, por ejemplo
desde ``g2-uplink`` de forma periodica o a peticion desde la plataforma.

Que detecta:
  * ``eslabon_roto``: un eslabon no coincide con su propia huella, o su
    ``hash_previo`` no es el ``hash_cadena`` del eslabon anterior (se modifico o
    se quito un eslabon).
  * ``contenido_alterado``: el contenido actual de un registro no coincide con
    la huella guardada para su ultima revision (se cambio sin pasar por los
    disparadores).
  * ``cambio_sin_registrar``: el registro esta en una revision mas nueva que la
    del ultimo eslabon (se cambio sin dejar eslabon).
  * ``sin_eslabon``: existe un registro auditado que nunca tuvo eslabon.

Que NO detecta: la alteracion de registros que ya fueron borrados por retencion
(su eslabon permanece, pero ya no hay contenido que comparar) ni una
reconstruccion completa de la cadena por quien tenga acceso de administrador;
para eso sirve la copia que guarda la plataforma.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

# Huella inicial: "hash_previo" del primer eslabon.
GENESIS = "0" * 64


@dataclass(frozen=True)
class Problema:
    """Una inconsistencia encontrada por :func:`verificar`."""

    tipo: str            # eslabon_roto | contenido_alterado | cambio_sin_registrar | sin_eslabon
    seq: int | None      # numero de eslabon involucrado, si aplica
    tabla: str | None
    registro_id: int | None
    detalle: str


def _huella_eslabon(previo: str, tabla: str, registro_id: int, rev: int, hash_registro: str) -> str:
    """Recalcula ``hash_cadena``. Debe coincidir exactamente con el SQL de la
    migracion 003: ``previo | tabla | id | rev | hash_registro``."""
    texto = f"{previo}|{tabla}|{registro_id}|{rev}|{hash_registro}"
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def verificar(conexion: sqlite3.Connection) -> list[Problema]:
    """Verifica toda la cadena y devuelve la lista de problemas (vacia si esta bien).

    Recorre todos los eslabones en orden: en un equipo con muchos registros
    conviene ejecutarlo de forma ocasional, no en cada ciclo.

    La conexion debe tener registrada la funcion ``sha256`` (las que entrega
    :mod:`g2.almacenamiento.base` ya la tienen).

    Raises:
        sqlite3.Error: si la base no se puede leer.
    """
    problemas: list[Problema] = []

    # 1) Los eslabones: cada uno coincide con su huella y enlaza con el anterior.
    esperado_previo = GENESIS
    seq_previa = 0
    for fila in conexion.execute("SELECT * FROM auditoria_cadena ORDER BY seq"):
        if fila["seq"] != seq_previa + 1:
            problemas.append(Problema(
                "eslabon_roto", fila["seq"], fila["tabla"], fila["registro_id"],
                f"faltan eslabones entre {seq_previa} y {fila['seq']}"))
        if fila["hash_previo"] != esperado_previo:
            problemas.append(Problema(
                "eslabon_roto", fila["seq"], fila["tabla"], fila["registro_id"],
                "hash_previo no coincide con el eslabon anterior"))
        calculado = _huella_eslabon(fila["hash_previo"], fila["tabla"], fila["registro_id"],
                                    fila["rev"], fila["hash_registro"])
        if fila["hash_cadena"] != calculado:
            problemas.append(Problema(
                "eslabon_roto", fila["seq"], fila["tabla"], fila["registro_id"],
                "hash_cadena no coincide con el contenido del eslabon"))
        # Se continua con el hash que figura en el eslabon para no repetir el
        # mismo problema en cascada: asi solo se informa donde se rompio.
        esperado_previo = fila["hash_cadena"]
        seq_previa = fila["seq"]

    # 2) El contenido actual de cada registro frente a su ultimo eslabon.
    consulta = """
        SELECT u.tabla, u.registro_id, u.rev AS rev_actual, u.hash_actual,
               e.seq, e.rev AS rev_eslabon, e.hash_registro
          FROM v_cadena_contenido u
          LEFT JOIN auditoria_cadena e
                 ON e.tabla = u.tabla AND e.registro_id = u.registro_id
                AND e.rev = (SELECT MAX(rev) FROM auditoria_cadena
                              WHERE tabla = u.tabla AND registro_id = u.registro_id)
         WHERE e.seq IS NULL OR e.rev <> u.rev OR e.hash_registro <> u.hash_actual
    """
    for fila in conexion.execute(consulta):
        if fila["seq"] is None:
            problemas.append(Problema(
                "sin_eslabon", None, fila["tabla"], fila["registro_id"],
                "el registro no tiene ningun eslabon en la cadena"))
        elif fila["rev_eslabon"] != fila["rev_actual"]:
            problemas.append(Problema(
                "cambio_sin_registrar", fila["seq"], fila["tabla"], fila["registro_id"],
                f"el registro esta en la revision {fila['rev_actual']} y el ultimo "
                f"eslabon es de la {fila['rev_eslabon']}"))
        else:
            problemas.append(Problema(
                "contenido_alterado", fila["seq"], fila["tabla"], fila["registro_id"],
                "el contenido actual no coincide con la huella registrada"))
    return problemas
