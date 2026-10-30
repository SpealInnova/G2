"""Que se envia a la plataforma: los registros pendientes de ``cola_envio``, armados desde su fila (D-008).

La cola guarda solo una referencia ``(tabla, registro_id, rev)``; el mensaje se arma aqui, al enviar. Todo es lectura.

  * Con atraso se envia primero lo que mas importa: alarmas y eventos antes que lecturas (que son miles).
  * Si un registro tiene varias revisiones pendientes se envia UNA vez, con su contenido de hoy y la revision mas alta; al
    confirmarlo se confirman todas sus entradas de cola.
  * Un registro que ya no existe no se puede enviar: se avisa para no reintentarlo eternamente.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

# Orden de envio con atraso (el primero sale antes). Es la lista cerrada de tablas que acepta cola_envio.
PRIORIDAD = ("alarma", "evento", "calibracion", "comando", "config_historial", "arranque", "salud",
             "auditoria_cadena", "medicion_periferico", "lectura")
_ORDEN_SQL = "CASE tabla " + " ".join(f"WHEN '{t}' THEN {n}" for n, t in enumerate(PRIORIDAD)) + " END"
HOLGURA_RELOJ_MS = 3_600_000             # un reintento fijado mas alla de esto es de un reloj desajustado: no se espera
CLAVE_PRIMARIA = {"auditoria_cadena": "seq"}      # todas las demas tablas usan ``id``


@dataclass
class Lote:
    registros: list[dict] = field(default_factory=list)                     # lo que viaja
    entradas: dict[tuple[str, int], list[int]] = field(default_factory=dict)   # (tabla, id) -> ids de cola_envio
    faltantes: dict[int, str] = field(default_factory=dict)                 # id de cola -> motivo (la fila ya no existe)

    def vacio(self) -> bool:
        return not self.registros and not self.faltantes


def pendientes(db: sqlite3.Connection, ahora_ms: int, limite: int, excluir=()) -> list[sqlite3.Row]:
    """Entradas de la cola listas para enviar (pendientes y sin espera de reintento), las mas importantes primero.
    ``excluir``: ids que ya se enviaron y esperan a que el nucleo los anote."""
    excluir = set(excluir)
    filas = db.execute(
        f"SELECT id, tabla, registro_id, rev FROM cola_envio WHERE estado = 'pendiente' AND "
        f"(proximo_intento_ms IS NULL OR proximo_intento_ms <= ? OR proximo_intento_ms > ?) "
        f"ORDER BY {_ORDEN_SQL}, id LIMIT ?", (ahora_ms, ahora_ms + HOLGURA_RELOJ_MS, limite + len(excluir)))
    return [f for f in filas if f["id"] not in excluir][:limite]


def armar(db: sqlite3.Connection, entradas: list[sqlite3.Row]) -> Lote:
    """Arma el lote: un registro por cada ``(tabla, id)`` con su fila completa."""
    grupos: dict[tuple[str, int], list[sqlite3.Row]] = {}
    for e in entradas:
        grupos.setdefault((e["tabla"], e["registro_id"]), []).append(e)
    lote = Lote()
    for (tabla, registro_id), lista in grupos.items():
        if tabla not in PRIORIDAD:                                           # no pasa: la tabla lo impide; por si acaso
            lote.faltantes.update({e["id"]: f"tabla desconocida: {tabla}" for e in lista})
            continue
        fila = db.execute(f"SELECT * FROM {tabla} WHERE {CLAVE_PRIMARIA.get(tabla, 'id')} = ?", (registro_id,)).fetchone()
        if fila is None:
            lote.faltantes.update({e["id"]: "el registro ya no existe" for e in lista})
            continue
        lote.registros.append({"tabla": tabla, "id": registro_id, "rev": max(e["rev"] for e in lista),
                               "datos": dict(fila)})
        lote.entradas[(tabla, registro_id)] = [e["id"] for e in lista]
    return lote
