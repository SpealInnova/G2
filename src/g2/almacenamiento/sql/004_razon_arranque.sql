-- =============================================================================
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

ALTER TABLE arranque ADD COLUMN razon TEXT REFERENCES catalogo_evento (codigo);
ALTER TABLE arranque ADD COLUMN so_boot_id TEXT;

INSERT INTO catalogo_evento (codigo, categoria, severidad, descripcion, accion, es_alarma) VALUES
('SYS_REINICIO_SOLICITADO', 'sistema', 1, 'Un usuario pidio el reinicio (desde la pantalla o la plataforma); ver el registro de comando.', NULL, 0),
('SYS_ACTUALIZACION',       'sistema', 1, 'Reinicio por actualizacion de software.', NULL, 0);

-- Disparadores de la cadena de `arranque`, con las columnas nuevas.
DROP TRIGGER tr_arranque_cadena_insert;
DROP TRIGGER tr_arranque_cadena_rev;

-- ---- arranque ----
CREATE TRIGGER tr_arranque_cadena_insert
AFTER INSERT ON arranque
BEGIN
    INSERT INTO auditoria_cadena
        (tabla, registro_id, rev, creado_ms, hash_registro, hash_previo, hash_cadena)
    SELECT 'arranque', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000, r.h, p.h,
           sha256(p.h || '|' || 'arranque' || '|' || NEW.id || '|' || NEW.rev || '|' || r.h)
      FROM (SELECT COALESCE((SELECT hash_cadena FROM auditoria_cadena
                              ORDER BY seq DESC LIMIT 1), '0000000000000000000000000000000000000000000000000000000000000000') AS h) AS p,
           (SELECT sha256(json_object(
            'id', NEW.id,
            'boot_id', NEW.boot_id,
            'inicio_ms', NEW.inicio_ms,
            'inicio_confiable', NEW.inicio_confiable,
            'sincronizado_utc_ms', NEW.sincronizado_utc_ms,
            'sincronizado_mono_ms', NEW.sincronizado_mono_ms,
            'causa', NEW.causa,
            'version_sw', NEW.version_sw,
            'version_config', NEW.version_config,
            'uptime_previo_s', NEW.uptime_previo_s,
            'throttled', NEW.throttled,
            'rev', NEW.rev,
            'razon', NEW.razon,
            'so_boot_id', NEW.so_boot_id)) AS h) AS r;
END;

CREATE TRIGGER tr_arranque_cadena_rev
AFTER UPDATE OF rev ON arranque
WHEN NEW.rev <> OLD.rev
BEGIN
    INSERT INTO auditoria_cadena
        (tabla, registro_id, rev, creado_ms, hash_registro, hash_previo, hash_cadena)
    SELECT 'arranque', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000, r.h, p.h,
           sha256(p.h || '|' || 'arranque' || '|' || NEW.id || '|' || NEW.rev || '|' || r.h)
      FROM (SELECT COALESCE((SELECT hash_cadena FROM auditoria_cadena
                              ORDER BY seq DESC LIMIT 1), '0000000000000000000000000000000000000000000000000000000000000000') AS h) AS p,
           (SELECT sha256(json_object(
            'id', NEW.id,
            'boot_id', NEW.boot_id,
            'inicio_ms', NEW.inicio_ms,
            'inicio_confiable', NEW.inicio_confiable,
            'sincronizado_utc_ms', NEW.sincronizado_utc_ms,
            'sincronizado_mono_ms', NEW.sincronizado_mono_ms,
            'causa', NEW.causa,
            'version_sw', NEW.version_sw,
            'version_config', NEW.version_config,
            'uptime_previo_s', NEW.uptime_previo_s,
            'throttled', NEW.throttled,
            'rev', NEW.rev,
            'razon', NEW.razon,
            'so_boot_id', NEW.so_boot_id)) AS h) AS r;
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
            'rev', rev)) AS hash_actual
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

-- Re-sellado de las filas anteriores a esta migracion: cada una recibe una nueva
-- revision (y con ella un eslabon nuevo en la cadena y una entrada en la cola de
-- envio).
UPDATE arranque SET rev = rev + 1;
