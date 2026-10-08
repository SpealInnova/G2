"""Genera la migracion 004 (razon del arranque y huellas actualizadas).

Uso (desde la raiz del proyecto):

    set PYTHONPATH=src
    python tools/generar_migracion_004.py

La migracion 004 agrega dos columnas a ``arranque`` (decision D-018) y, como
``arranque`` es una tabla auditada, vuelve a crear sus disparadores de la cadena
de auditoria y la vista ``v_cadena_contenido`` para que las columnas nuevas
entren en la huella. Esas piezas llevan la lista de columnas y por eso se
generan (misma razon que ``generar_cadena.py``); la migracion 003 ya esta
publicada y no se toca.
"""

from __future__ import annotations

from generar_cadena import (
    AUDITADAS, SQL, columnas, esquema_en_memoria,
    texto_trigger_insert, texto_trigger_rev, texto_vista,
)

# Cambios de columnas. Se usan tanto en el SQL generado como en la base temporal
# que sirve para leer las columnas resultantes.
ALTERS = """ALTER TABLE arranque ADD COLUMN razon TEXT REFERENCES catalogo_evento (codigo);
ALTER TABLE arranque ADD COLUMN so_boot_id TEXT;
"""

ENCABEZADO = f"""-- =============================================================================
-- 004_razon_arranque.sql  --  Razon y encendido del sistema operativo en `arranque`
-- =============================================================================
-- GENERADO por tools/generar_migracion_004.py. No editar a mano: se regenera.
--
-- Decision D-018. Hasta ahora `arranque` registraba un encendido de la Raspberry
-- Pi. Desde esta migracion registra CADA INICIO DE g2-core, de modo que un
-- reinicio de servicio (falla, watchdog, actualizacion o peticion remota) deja su
-- propia fila con su version de software y no se pierde la trazabilidad de que
-- version produjo cada lectura.
--
--  * razon      : codigo de catalogo_evento que explica por que arranco el nucleo
--                 (SYS_ARRANQUE, SVC_REINICIADO, SVC_BLOQUEO_DETECTADO,
--                 SYS_REINICIO_SOLICITADO, SYS_ACTUALIZACION...). NULL en filas
--                 anteriores a esta migracion.
--  * so_boot_id : identificador del encendido del sistema operativo; varias filas
--                 de `arranque` pueden compartirlo.
--  * boot_id    : sigue siendo unico y pasa a identificar cada inicio del nucleo
--                 (por ejemplo '<so_boot_id>#<n>'). No cambia su restriccion.
--  * `causa` conserva sus cinco valores (nivel del sistema); el detalle de un
--    reinicio de servicio lo da `razon`.
--
-- Cadena de auditoria: las columnas nuevas entran en la huella. Los disparadores
-- de `arranque` y la vista v_cadena_contenido se vuelven a crear, y al final las
-- filas de `arranque` que ya existian se re-sellan con una nueva revision (un
-- eslabon nuevo por fila), para que la verificacion siga siendo coherente. En una
-- base vacia ese paso no hace nada.
-- =============================================================================

{ALTERS}
INSERT INTO catalogo_evento (codigo, categoria, severidad, descripcion, accion, es_alarma) VALUES
('SYS_REINICIO_SOLICITADO', 'sistema', 1, 'Un usuario pidio el reinicio (desde la pantalla o la plataforma); ver el registro de comando.', NULL, 0),
('SYS_ACTUALIZACION',       'sistema', 1, 'Reinicio por actualizacion de software.', NULL, 0);

-- Disparadores de la cadena de `arranque`, con las columnas nuevas.
DROP TRIGGER tr_arranque_cadena_insert;
DROP TRIGGER tr_arranque_cadena_rev;
"""

PIE = """
-- Re-sellado de las filas anteriores a esta migracion: cada una recibe una nueva
-- revision (y con ella un eslabon nuevo en la cadena y una entrada en la cola de
-- envio).
UPDATE arranque SET rev = rev + 1;
"""


def generar() -> str:
    memoria = esquema_en_memoria((
        "001_esquema_inicial.sql", "002_catalogo_inicial.sql", "003_cadena_auditoria.sql"))
    memoria.executescript(ALTERS)

    sal = [ENCABEZADO]
    cols = columnas(memoria, "arranque")
    sal.append(texto_trigger_insert("arranque", cols, AUDITADAS["arranque"]))
    sal.append(texto_trigger_rev("arranque", cols))
    sal.append("\nDROP VIEW v_cadena_contenido;")
    sal.append(texto_vista(memoria))
    sal.append(PIE)
    return "".join(sal)


if __name__ == "__main__":
    destino = SQL / "004_razon_arranque.sql"
    destino.write_text(generar(), encoding="utf-8", newline="\n")
    print(f"Generado {destino} ({destino.read_text(encoding='utf-8').count(chr(10))} lineas)")
