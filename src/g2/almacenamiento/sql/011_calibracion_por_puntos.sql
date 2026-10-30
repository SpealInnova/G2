-- =============================================================================
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

ALTER TABLE calibracion ADD COLUMN ganancia     REAL CHECK (ganancia IS NULL OR ganancia > 0);
ALTER TABLE calibracion ADD COLUMN bajo_ref_pct REAL;
ALTER TABLE calibracion ADD COLUMN bajo_mv      REAL;
ALTER TABLE calibracion ADD COLUMN alto_ref_pct REAL;
ALTER TABLE calibracion ADD COLUMN alto_mv      REAL;

-- Verificacion: si el CHECK no quedo ampliado, esta insercion viola su restriccion y la migracion entera se revierte.
CREATE TEMP TABLE _verificacion_011 (ok INTEGER NOT NULL CHECK (ok = 1));
INSERT INTO _verificacion_011 SELECT instr(sql, '''puntos''') > 0 FROM sqlite_master WHERE type = 'table' AND name = 'calibracion';
DROP TABLE _verificacion_011;

-- Disparadores de la cadena de `calibracion`, con las columnas nuevas.
DROP TRIGGER tr_calibracion_cadena_insert;
DROP TRIGGER tr_calibracion_cadena_rev;

-- ---- calibracion ----
CREATE TRIGGER tr_calibracion_cadena_insert
AFTER INSERT ON calibracion
BEGIN
    INSERT INTO auditoria_cadena
        (tabla, registro_id, rev, creado_ms, hash_registro, hash_previo, hash_cadena)
    SELECT 'calibracion', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000, r.h, p.h,
           sha256(p.h || '|' || 'calibracion' || '|' || NEW.id || '|' || NEW.rev || '|' || r.h)
      FROM (SELECT COALESCE((SELECT hash_cadena FROM auditoria_cadena
                              ORDER BY seq DESC LIMIT 1), '0000000000000000000000000000000000000000000000000000000000000000') AS h) AS p,
           (SELECT sha256(json_object(
            'id', NEW.id,
            'ts_ms', NEW.ts_ms,
            'ts_confiable', NEW.ts_confiable,
            'arranque_id', NEW.arranque_id,
            'mono_ms', NEW.mono_ms,
            'sensor_id', NEW.sensor_id,
            'tipo', NEW.tipo,
            'gas_pct', NEW.gas_pct,
            'gas_certificado', NEW.gas_certificado,
            'mv_antes', NEW.mv_antes,
            'mv_despues', NEW.mv_despues,
            'offset_pct', NEW.offset_pct,
            'presion_hpa', NEW.presion_hpa,
            'temperatura_c', NEW.temperatura_c,
            'origen', NEW.origen,
            'actor', NEW.actor,
            'comando_id', NEW.comando_id,
            'resultado', NEW.resultado,
            'vigente', NEW.vigente,
            'notas', NEW.notas,
            'rev', NEW.rev,
            'ganancia', NEW.ganancia,
            'bajo_ref_pct', NEW.bajo_ref_pct,
            'bajo_mv', NEW.bajo_mv,
            'alto_ref_pct', NEW.alto_ref_pct,
            'alto_mv', NEW.alto_mv)) AS h) AS r;
END;

CREATE TRIGGER tr_calibracion_cadena_rev
AFTER UPDATE OF rev ON calibracion
WHEN NEW.rev <> OLD.rev
BEGIN
    INSERT INTO auditoria_cadena
        (tabla, registro_id, rev, creado_ms, hash_registro, hash_previo, hash_cadena)
    SELECT 'calibracion', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000, r.h, p.h,
           sha256(p.h || '|' || 'calibracion' || '|' || NEW.id || '|' || NEW.rev || '|' || r.h)
      FROM (SELECT COALESCE((SELECT hash_cadena FROM auditoria_cadena
                              ORDER BY seq DESC LIMIT 1), '0000000000000000000000000000000000000000000000000000000000000000') AS h) AS p,
           (SELECT sha256(json_object(
            'id', NEW.id,
            'ts_ms', NEW.ts_ms,
            'ts_confiable', NEW.ts_confiable,
            'arranque_id', NEW.arranque_id,
            'mono_ms', NEW.mono_ms,
            'sensor_id', NEW.sensor_id,
            'tipo', NEW.tipo,
            'gas_pct', NEW.gas_pct,
            'gas_certificado', NEW.gas_certificado,
            'mv_antes', NEW.mv_antes,
            'mv_despues', NEW.mv_despues,
            'offset_pct', NEW.offset_pct,
            'presion_hpa', NEW.presion_hpa,
            'temperatura_c', NEW.temperatura_c,
            'origen', NEW.origen,
            'actor', NEW.actor,
            'comando_id', NEW.comando_id,
            'resultado', NEW.resultado,
            'vigente', NEW.vigente,
            'notas', NEW.notas,
            'rev', NEW.rev,
            'ganancia', NEW.ganancia,
            'bajo_ref_pct', NEW.bajo_ref_pct,
            'bajo_mv', NEW.bajo_mv,
            'alto_ref_pct', NEW.alto_ref_pct,
            'alto_mv', NEW.alto_mv)) AS h) AS r;
END;

DROP VIEW v_cadena_contenido;
-- Contenido actual de cada registro auditado, con la misma formula de huella que
-- usan los disparadores. La verificacion (g2.almacenamiento.auditoria) la compara
-- con el ultimo eslabon de la cadena de cada registro.
CREATE VIEW v_cadena_contenido AS
SELECT 'arranque' AS tabla, id AS registro_id, rev AS rev,
       sha256(json_object(
            'id', id,
            'boot_id', boot_id,
            'inicio_ms', inicio_ms,
            'inicio_confiable', inicio_confiable,
            'sincronizado_utc_ms', sincronizado_utc_ms,
            'sincronizado_mono_ms', sincronizado_mono_ms,
            'causa', causa,
            'version_sw', version_sw,
            'version_config', version_config,
            'uptime_previo_s', uptime_previo_s,
            'throttled', throttled,
            'rev', rev,
            'razon', razon,
            'so_boot_id', so_boot_id)) AS hash_actual
  FROM arranque
UNION ALL
SELECT 'comando' AS tabla, id AS registro_id, rev AS rev,
       sha256(json_object(
            'id', id,
            'uuid', uuid,
            'ts_ms', ts_ms,
            'ts_confiable', ts_confiable,
            'arranque_id', arranque_id,
            'mono_ms', mono_ms,
            'origen', origen,
            'actor', actor,
            'tipo', tipo,
            'parametros_json', parametros_json,
            'estado', estado,
            'fin_ms', fin_ms,
            'resultado_json', resultado_json,
            'rev', rev)) AS hash_actual
  FROM comando
UNION ALL
SELECT 'config_historial' AS tabla, id AS registro_id, 1 AS rev,
       sha256(json_object(
            'id', id,
            'ts_ms', ts_ms,
            'ts_confiable', ts_confiable,
            'arranque_id', arranque_id,
            'mono_ms', mono_ms,
            'clave', clave,
            'valor_anterior', valor_anterior,
            'valor_nuevo', valor_nuevo,
            'version', version,
            'origen', origen,
            'actor', actor,
            'comando_id', comando_id)) AS hash_actual
  FROM config_historial
UNION ALL
SELECT 'calibracion' AS tabla, id AS registro_id, rev AS rev,
       sha256(json_object(
            'id', id,
            'ts_ms', ts_ms,
            'ts_confiable', ts_confiable,
            'arranque_id', arranque_id,
            'mono_ms', mono_ms,
            'sensor_id', sensor_id,
            'tipo', tipo,
            'gas_pct', gas_pct,
            'gas_certificado', gas_certificado,
            'mv_antes', mv_antes,
            'mv_despues', mv_despues,
            'offset_pct', offset_pct,
            'presion_hpa', presion_hpa,
            'temperatura_c', temperatura_c,
            'origen', origen,
            'actor', actor,
            'comando_id', comando_id,
            'resultado', resultado,
            'vigente', vigente,
            'notas', notas,
            'rev', rev,
            'ganancia', ganancia,
            'bajo_ref_pct', bajo_ref_pct,
            'bajo_mv', bajo_mv,
            'alto_ref_pct', alto_ref_pct,
            'alto_mv', alto_mv)) AS hash_actual
  FROM calibracion
UNION ALL
SELECT 'alarma' AS tabla, id AS registro_id, rev AS rev,
       sha256(json_object(
            'id', id,
            'codigo', codigo,
            'severidad', severidad,
            'sensor_id', sensor_id,
            'periferico_id', periferico_id,
            'inicio_ms', inicio_ms,
            'inicio_confiable', inicio_confiable,
            'arranque_id', arranque_id,
            'mono_ms', mono_ms,
            'fin_ms', fin_ms,
            'fin_confiable', fin_confiable,
            'umbral', umbral,
            'valor_disparo', valor_disparo,
            'valor_pico', valor_pico,
            'estado', estado,
            'acuse_ms', acuse_ms,
            'acuse_actor', acuse_actor,
            'mensaje', mensaje,
            'actualizado_ms', actualizado_ms,
            'rev', rev)) AS hash_actual
  FROM alarma
UNION ALL
SELECT 'evento' AS tabla, id AS registro_id, rev AS rev,
       sha256(json_object(
            'id', id,
            'ts_ms', ts_ms,
            'ts_confiable', ts_confiable,
            'arranque_id', arranque_id,
            'mono_ms', mono_ms,
            'codigo', codigo,
            'severidad', severidad,
            'origen', origen,
            'sensor_id', sensor_id,
            'periferico_id', periferico_id,
            'mensaje', mensaje,
            'datos_json', datos_json,
            'repeticiones', repeticiones,
            'ultimo_ms', ultimo_ms,
            'rev', rev)) AS hash_actual
  FROM evento;

-- Las calibraciones de cero en aire anteriores (D-048, tipo 'offset_cero', correctas y con su tension medida) pasan a ser el PUNTO BAJO de
-- la calibracion por puntos (gas de 20,9 %): asi la correccion vigente sigue igual (ganancia 1, mismo cero) y, al medir despues un punto
-- alto, se compone con ese punto en lugar de empezar de cero. Las demas filas solo ganan las columnas vacias.
-- Re-sellado de las filas anteriores a esta migracion: cada una recibe una nueva revision (y con ella un eslabon nuevo en la cadena
-- y una entrada en la cola de envio).
UPDATE calibracion
   SET bajo_ref_pct = CASE WHEN tipo = 'offset_cero' AND resultado = 'ok' AND gas_pct < 50 AND mv_antes IS NOT NULL THEN gas_pct END,
       bajo_mv      = CASE WHEN tipo = 'offset_cero' AND resultado = 'ok' AND gas_pct < 50 AND mv_antes IS NOT NULL THEN mv_antes END,
       rev = rev + 1;
