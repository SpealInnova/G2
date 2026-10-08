"""Genera la migracion 003 (cadena de auditoria con huellas SHA-256).

Uso (desde la raiz del proyecto):

    set PYTHONPATH=src
    python tools/generar_cadena.py

Por que se genera: los disparadores de cada tabla auditada llevan la lista de
TODAS las columnas de esa tabla. Escribirla a mano es propenso a errores (una
columna olvidada quedaria fuera de la huella sin que nadie lo note). Este
programa lee las columnas reales de las migraciones 001 y 002 y produce
``003_cadena_auditoria.sql``; ese archivo es el que se aplica y se audita.
Si cambia una tabla auditada en una migracion futura, se regenera.

Diseño (decision D-016): ver MEMORIA_TECNICA.md y el encabezado del SQL generado.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "src" / "g2" / "almacenamiento" / "sql"

# Tablas cuyos registros se encadenan, y si tienen revisiones (columna rev).
# Son los registros de AUDITORIA. Las lecturas no se encadenan una a una (sus
# millones de filas duplicarian el almacenamiento): se sellaran por bloques en
# una etapa posterior, usando esta misma cadena (tabla 'sello_lectura').
AUDITADAS = {
    "arranque": True,
    "comando": True,
    "config_historial": False,
    "calibracion": True,
    "alarma": True,
    "evento": True,
}
GENESIS = "0" * 64
AHORA = "CAST(strftime('%s', 'now') AS INTEGER) * 1000"


def columnas(conexion: sqlite3.Connection, tabla: str) -> list[str]:
    """Nombres de las columnas de una tabla, en el orden del esquema."""
    return [fila[1] for fila in conexion.execute(f"PRAGMA table_info({tabla})")]


def contenido(prefijo: str, cols: list[str]) -> str:
    """Expresion SQL con el contenido canonico de una fila (todas sus columnas)."""
    pares = ",\n            ".join(f"'{c}', {prefijo}{c}" for c in cols)
    return f"json_object(\n            {pares})"


def esquema_en_memoria(migraciones: tuple[str, ...]) -> sqlite3.Connection:
    """Base temporal en memoria con las migraciones indicadas, para leer el
    esquema real (columnas) de las tablas auditadas."""
    memoria = sqlite3.connect(":memory:")
    for nombre in migraciones:
        memoria.executescript((SQL / nombre).read_text(encoding="utf-8"))
    return memoria


def texto_trigger_insert(tabla: str, cols: list[str], con_rev: bool) -> str:
    """Disparador que agrega el eslabon al crear un registro auditado."""
    rev_nueva = "NEW.rev" if con_rev else "1"
    return f"""
-- ---- {tabla} ----
CREATE TRIGGER tr_{tabla}_cadena_insert
AFTER INSERT ON {tabla}
BEGIN
    INSERT INTO auditoria_cadena
        (tabla, registro_id, rev, creado_ms, hash_registro, hash_previo, hash_cadena)
    SELECT '{tabla}', NEW.id, {rev_nueva}, {AHORA}, r.h, p.h,
           sha256(p.h || '|' || '{tabla}' || '|' || NEW.id || '|' || {rev_nueva} || '|' || r.h)
      FROM (SELECT COALESCE((SELECT hash_cadena FROM auditoria_cadena
                              ORDER BY seq DESC LIMIT 1), '{GENESIS}') AS h) AS p,
           (SELECT sha256({contenido("NEW.", cols)}) AS h) AS r;
END;
"""


def texto_trigger_rev(tabla: str, cols: list[str]) -> str:
    """Disparador que agrega el eslabon al cambiar la revision de un registro."""
    return f"""
CREATE TRIGGER tr_{tabla}_cadena_rev
AFTER UPDATE OF rev ON {tabla}
WHEN NEW.rev <> OLD.rev
BEGIN
    INSERT INTO auditoria_cadena
        (tabla, registro_id, rev, creado_ms, hash_registro, hash_previo, hash_cadena)
    SELECT '{tabla}', NEW.id, NEW.rev, {AHORA}, r.h, p.h,
           sha256(p.h || '|' || '{tabla}' || '|' || NEW.id || '|' || NEW.rev || '|' || r.h)
      FROM (SELECT COALESCE((SELECT hash_cadena FROM auditoria_cadena
                              ORDER BY seq DESC LIMIT 1), '{GENESIS}') AS h) AS p,
           (SELECT sha256({contenido("NEW.", cols)}) AS h) AS r;
END;
"""


def texto_vista(memoria: sqlite3.Connection, crear: str = "CREATE VIEW") -> str:
    """Vista con el contenido actual (huella) de cada registro auditado."""
    vistas = []
    for tabla, con_rev in AUDITADAS.items():
        cols = columnas(memoria, tabla)
        rev_vista = "rev" if con_rev else "1"
        vistas.append(
            f"SELECT '{tabla}' AS tabla, id AS registro_id, {rev_vista} AS rev,\n"
            f"       sha256({contenido('', cols)}) AS hash_actual\n"
            f"  FROM {tabla}"
        )
    return f"""
-- Contenido actual de cada registro auditado, con la misma formula de huella que
-- usan los disparadores. La verificacion (g2.almacenamiento.auditoria) la compara
-- con el ultimo eslabon de la cadena de cada registro.
{crear} v_cadena_contenido AS
""" + "\nUNION ALL\n".join(vistas) + ";\n"


def generar() -> str:
    """Texto completo de la migracion 003."""
    memoria = esquema_en_memoria(("001_esquema_inicial.sql", "002_catalogo_inicial.sql"))
    sal = [ENCABEZADO]
    for tabla, con_rev in AUDITADAS.items():
        cols = columnas(memoria, tabla)
        sal.append(texto_trigger_insert(tabla, cols, con_rev))
        if con_rev:
            sal.append(texto_trigger_rev(tabla, cols))
    sal.append(texto_vista(memoria))
    sal.append(PIE)
    return "".join(sal)


ENCABEZADO = f"""-- =============================================================================
-- 003_cadena_auditoria.sql  --  Cadena de auditoria con huellas SHA-256
-- =============================================================================
-- GENERADO por tools/generar_cadena.py. No editar a mano: se regenera.
--
-- Decision D-016 (ver MEMORIA_TECNICA.md). Objetivo: que cualquier alteracion de
-- los registros de auditoria (arranques, comandos, cambios de configuracion,
-- calibraciones, alarmas y eventos) sea detectable.
--
-- Funcionamiento:
--  * Cada vez que se crea o se modifica (nueva revision) un registro auditado,
--    un disparador agrega UN eslabon a la tabla auditoria_cadena, en la misma
--    transaccion que el cambio.
--  * hash_registro = SHA-256 del contenido de la fila (todas sus columnas, en
--    formato JSON).
--  * hash_cadena   = SHA-256 de  hash_previo | tabla | id | rev | hash_registro.
--    hash_previo es el hash_cadena del eslabon anterior (el primero usa
--    {GENESIS[:8]}... = 64 ceros). Alterar o quitar un eslabon rompe todos los siguientes.
--  * auditoria_cadena es de solo-agregar: un disparador rechaza UPDATE y DELETE.
--    Los registros se pueden borrar despues por retencion (con confirmacion de
--    la plataforma); su eslabon permanece como prueba de que existieron.
--  * Cada eslabon se encola para la plataforma (cola_envio), que guarda una
--    copia independiente de la cadena: una alteracion hecha en el equipo se
--    detecta comparando con lo que recibio la plataforma.
--
-- Alcance y limites (honestidad tecnica):
--  * DETECTA alteraciones; no las impide a quien tenga acceso de administrador
--    al archivo. Esa persona podria reconstruir toda la cadena; por eso la copia
--    en la plataforma es la garantia externa.
--  * Una revision antigua de un registro solo se puede verificar en su eslabon
--    (la fila ya tiene el contenido nuevo); el contenido se compara solo para la
--    ultima revision.
--  * Requiere la funcion SQL sha256, que registra g2.almacenamiento.base. Una
--    conexion sin ella no puede escribir en las tablas auditadas (falla, no se
--    salta la cadena).
-- =============================================================================

CREATE TABLE auditoria_cadena (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,
    tabla          TEXT    NOT NULL
                   CHECK (tabla IN ('arranque', 'comando', 'config_historial',
                                    'calibracion', 'alarma', 'evento',
                                    'sello_lectura', 'sello_medicion')),
    registro_id    INTEGER NOT NULL,
    rev            INTEGER NOT NULL CHECK (rev >= 1),
    creado_ms      INTEGER NOT NULL,
    hash_registro  TEXT    NOT NULL CHECK (length(hash_registro) = 64),
    hash_previo    TEXT    NOT NULL CHECK (length(hash_previo) = 64),
    hash_cadena    TEXT    NOT NULL UNIQUE CHECK (length(hash_cadena) = 64),
    UNIQUE (tabla, registro_id, rev)
) STRICT;

-- Solo agregar: ni modificar ni borrar eslabones.
CREATE TRIGGER tr_auditoria_cadena_no_modificar
BEFORE UPDATE ON auditoria_cadena
BEGIN
    SELECT RAISE(ABORT, 'auditoria_cadena es de solo agregar: no se puede modificar');
END;

CREATE TRIGGER tr_auditoria_cadena_no_borrar
BEFORE DELETE ON auditoria_cadena
BEGIN
    SELECT RAISE(ABORT, 'auditoria_cadena es de solo agregar: no se puede borrar');
END;

-- Cada eslabon tambien viaja a la plataforma (copia independiente de la cadena).
CREATE TRIGGER tr_auditoria_cadena_encolar_insert
AFTER INSERT ON auditoria_cadena
BEGIN
    INSERT INTO cola_envio (tabla, registro_id, rev, creado_ms)
    VALUES ('auditoria_cadena', NEW.seq, 1, {AHORA});
END;

-- Estado de la base: ahora incluye la cadena.
DROP VIEW v_estado_db;
CREATE VIEW v_estado_db AS
    SELECT 'lectura' AS tabla, COUNT(*) AS filas FROM lectura
    UNION ALL SELECT 'medicion_periferico', COUNT(*) FROM medicion_periferico
    UNION ALL SELECT 'alarma',              COUNT(*) FROM alarma
    UNION ALL SELECT 'evento',              COUNT(*) FROM evento
    UNION ALL SELECT 'arranque',            COUNT(*) FROM arranque
    UNION ALL SELECT 'comando',             COUNT(*) FROM comando
    UNION ALL SELECT 'calibracion',         COUNT(*) FROM calibracion
    UNION ALL SELECT 'config_historial',    COUNT(*) FROM config_historial
    UNION ALL SELECT 'salud',               COUNT(*) FROM salud
    UNION ALL SELECT 'auditoria_cadena',    COUNT(*) FROM auditoria_cadena
    UNION ALL SELECT 'cola_envio',          COUNT(*) FROM cola_envio;

-- Codigos de auditoria para el catalogo.
INSERT INTO catalogo_evento (codigo, categoria, severidad, descripcion, accion, es_alarma) VALUES
('AUD_VERIFICACION_OK',     'auditoria', 1, 'La verificacion de la cadena de auditoria no encontro diferencias.', NULL, 0),
('ALM_AUDITORIA_ALTERADA',  'alarma',    4, 'La verificacion de la cadena de auditoria encontro registros alterados, eslabones faltantes o cambios sin registrar.', 'Conservar una copia de la base y contactar a soporte; comparar con la copia de la plataforma.', 1);

-- =============================================================================
-- DISPARADORES GENERADOS: un eslabon por cada creacion o revision de un
-- registro auditado.
-- ============================================================================="""

PIE = ""


if __name__ == "__main__":
    destino = SQL / "003_cadena_auditoria.sql"
    destino.write_text(generar(), encoding="utf-8", newline="\n")
    print(f"Generado {destino} ({destino.read_text(encoding='utf-8').count(chr(10))} lineas)")
