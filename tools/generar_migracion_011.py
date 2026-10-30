"""Genera la migracion 011 (calibracion por puntos: ganancia y los dos puntos de referencia).

Uso (desde la raiz del proyecto):

    set PYTHONPATH=src
    python tools/generar_migracion_011.py

La migracion 011 agrega columnas a ``calibracion`` (decision D-049) y, como ``calibracion`` es una tabla auditada, vuelve a crear
sus disparadores de la cadena de auditoria y la vista ``v_cadena_contenido`` para que las columnas nuevas entren en la huella
(misma razon y mismo metodo que ``generar_migracion_004.py``; las migraciones ya publicadas no se tocan).
"""

from __future__ import annotations

from generar_cadena import (
    AUDITADAS, SQL, columnas, esquema_en_memoria,
    texto_trigger_insert, texto_trigger_rev, texto_vista,
)

ANTERIORES = tuple(sorted(p.name for p in SQL.glob("*.sql") if p.name < "011"))

ALTERS = """ALTER TABLE calibracion ADD COLUMN ganancia     REAL CHECK (ganancia IS NULL OR ganancia > 0);
ALTER TABLE calibracion ADD COLUMN bajo_ref_pct REAL;
ALTER TABLE calibracion ADD COLUMN bajo_mv      REAL;
ALTER TABLE calibracion ADD COLUMN alto_ref_pct REAL;
ALTER TABLE calibracion ADD COLUMN alto_mv      REAL;
"""

ENCABEZADO = f"""-- =============================================================================
-- 011_calibracion_por_puntos.sql  --  Ganancia y puntos de referencia en `calibracion`
-- =============================================================================
-- GENERADO por tools/generar_migracion_011.py. No editar a mano: se regenera.
--
-- Decision D-049. Hasta ahora una calibracion corregia solo el cero (`offset_pct`). Con gas patron en dos puntos (bajo y alto) se
-- corrige tambien la pendiente:  O2 = ganancia * (mV / mv_por_pct) + offset_pct.
--
--  * tipo 'puntos' : calibracion por puntos con gas patron (cada punto se mide por separado). Los tipos anteriores no cambian.
--  * ganancia      : pendiente de la recta (NULL en las filas anteriores = 1).
--  * bajo_ref_pct / bajo_mv : concentracion del gas del punto bajo (menor de 50 %) y la tension media medida con el, en mV.
--  * alto_ref_pct / alto_mv : lo mismo para el punto alto (50 % o mas).
--    La fila vigente guarda los dos puntos con los que se calculo la recta: el que se acaba de medir y el que se conserva de la
--    calibracion anterior. `gas_pct` y `mv_antes` siguen siendo el punto medido en ESTA calibracion.
--
-- SQLite no permite cambiar un CHECK con ALTER TABLE: el tipo nuevo se agrega con el procedimiento documentado de `writable_schema`
-- (el cambio solo AMPLIA los valores permitidos, no toca el contenido) y `writable_schema = RESET` para que SQLite relea el esquema antes
-- de agregar las columnas. Una verificacion aborta la migracion si el cambio no se aplico.
--
-- Cadena de auditoria: las columnas nuevas entran en la huella. Los disparadores de `calibracion` y la vista v_cadena_contenido se
-- vuelven a crear, y las filas que ya existian se re-sellan con una nueva revision (un eslabon nuevo por fila). En una base sin
-- calibraciones ese paso no hace nada.
-- =============================================================================

PRAGMA writable_schema = ON;
UPDATE sqlite_master
   SET sql = replace(sql, 'CHECK (tipo IN (''fabrica'', ''offset_cero'', ''spoc_boton''))',
                          'CHECK (tipo IN (''fabrica'', ''offset_cero'', ''spoc_boton'', ''puntos''))')
 WHERE type = 'table' AND name = 'calibracion';
PRAGMA writable_schema = RESET;      -- apaga el modo y recarga el esquema con el texto nuevo (SQLite 3.33 o mas)

{ALTERS}
-- Verificacion: si el CHECK no quedo ampliado, esta insercion viola su restriccion y la migracion entera se revierte.
CREATE TEMP TABLE _verificacion_011 (ok INTEGER NOT NULL CHECK (ok = 1));
INSERT INTO _verificacion_011 SELECT instr(sql, '''puntos''') > 0 FROM sqlite_master WHERE type = 'table' AND name = 'calibracion';
DROP TABLE _verificacion_011;

-- Disparadores de la cadena de `calibracion`, con las columnas nuevas.
DROP TRIGGER tr_calibracion_cadena_insert;
DROP TRIGGER tr_calibracion_cadena_rev;
"""

PIE = """
-- Las calibraciones de cero en aire anteriores (D-048, tipo 'offset_cero', correctas y con su tension medida) pasan a ser el PUNTO BAJO de
-- la calibracion por puntos (gas de 20,9 %): asi la correccion vigente sigue igual (ganancia 1, mismo cero) y, al medir despues un punto
-- alto, se compone con ese punto en lugar de empezar de cero. Las demas filas solo ganan las columnas vacias.
-- Re-sellado de las filas anteriores a esta migracion: cada una recibe una nueva revision (y con ella un eslabon nuevo en la cadena
-- y una entrada en la cola de envio).
UPDATE calibracion
   SET bajo_ref_pct = CASE WHEN tipo = 'offset_cero' AND resultado = 'ok' AND gas_pct < 50 AND mv_antes IS NOT NULL THEN gas_pct END,
       bajo_mv      = CASE WHEN tipo = 'offset_cero' AND resultado = 'ok' AND gas_pct < 50 AND mv_antes IS NOT NULL THEN mv_antes END,
       rev = rev + 1;
"""


def generar() -> str:
    memoria = esquema_en_memoria(ANTERIORES)
    memoria.executescript(ALTERS)

    sal = [ENCABEZADO]
    cols = columnas(memoria, "calibracion")
    sal.append(texto_trigger_insert("calibracion", cols, AUDITADAS["calibracion"]))
    sal.append(texto_trigger_rev("calibracion", cols))
    sal.append("\nDROP VIEW v_cadena_contenido;")
    sal.append(texto_vista(memoria))
    sal.append(PIE)
    return "".join(sal)


if __name__ == "__main__":
    destino = SQL / "011_calibracion_por_puntos.sql"
    destino.write_text(generar(), encoding="utf-8", newline="\n")
    print(f"Generado {destino} ({destino.read_text(encoding='utf-8').count(chr(10))} lineas)")
