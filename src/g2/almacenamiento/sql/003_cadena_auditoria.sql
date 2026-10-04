-- =============================================================================
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
--    00000000... = 64 ceros). Alterar o quitar un eslabon rompe todos los siguientes.
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
    VALUES ('auditoria_cadena', NEW.seq, 1, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
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
-- =============================================================================
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
            'rev', NEW.rev)) AS h) AS r;
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
            'rev', NEW.rev)) AS h) AS r;
END;

-- ---- comando ----
CREATE TRIGGER tr_comando_cadena_insert
AFTER INSERT ON comando
BEGIN
    INSERT INTO auditoria_cadena
        (tabla, registro_id, rev, creado_ms, hash_registro, hash_previo, hash_cadena)
    SELECT 'comando', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000, r.h, p.h,
           sha256(p.h || '|' || 'comando' || '|' || NEW.id || '|' || NEW.rev || '|' || r.h)
      FROM (SELECT COALESCE((SELECT hash_cadena FROM auditoria_cadena
                              ORDER BY seq DESC LIMIT 1), '0000000000000000000000000000000000000000000000000000000000000000') AS h) AS p,
           (SELECT sha256(json_object(
            'id', NEW.id,
            'uuid', NEW.uuid,
            'ts_ms', NEW.ts_ms,
            'ts_confiable', NEW.ts_confiable,
            'arranque_id', NEW.arranque_id,
            'mono_ms', NEW.mono_ms,
            'origen', NEW.origen,
            'actor', NEW.actor,
            'tipo', NEW.tipo,
            'parametros_json', NEW.parametros_json,
            'estado', NEW.estado,
            'fin_ms', NEW.fin_ms,
            'resultado_json', NEW.resultado_json,
            'rev', NEW.rev)) AS h) AS r;
END;

CREATE TRIGGER tr_comando_cadena_rev
AFTER UPDATE OF rev ON comando
WHEN NEW.rev <> OLD.rev
BEGIN
    INSERT INTO auditoria_cadena
        (tabla, registro_id, rev, creado_ms, hash_registro, hash_previo, hash_cadena)
    SELECT 'comando', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000, r.h, p.h,
           sha256(p.h || '|' || 'comando' || '|' || NEW.id || '|' || NEW.rev || '|' || r.h)
      FROM (SELECT COALESCE((SELECT hash_cadena FROM auditoria_cadena
                              ORDER BY seq DESC LIMIT 1), '0000000000000000000000000000000000000000000000000000000000000000') AS h) AS p,
           (SELECT sha256(json_object(
            'id', NEW.id,
            'uuid', NEW.uuid,
            'ts_ms', NEW.ts_ms,
            'ts_confiable', NEW.ts_confiable,
            'arranque_id', NEW.arranque_id,
            'mono_ms', NEW.mono_ms,
            'origen', NEW.origen,
            'actor', NEW.actor,
            'tipo', NEW.tipo,
            'parametros_json', NEW.parametros_json,
            'estado', NEW.estado,
            'fin_ms', NEW.fin_ms,
            'resultado_json', NEW.resultado_json,
            'rev', NEW.rev)) AS h) AS r;
END;

-- ---- config_historial ----
CREATE TRIGGER tr_config_historial_cadena_insert
AFTER INSERT ON config_historial
BEGIN
    INSERT INTO auditoria_cadena
        (tabla, registro_id, rev, creado_ms, hash_registro, hash_previo, hash_cadena)
    SELECT 'config_historial', NEW.id, 1, CAST(strftime('%s', 'now') AS INTEGER) * 1000, r.h, p.h,
           sha256(p.h || '|' || 'config_historial' || '|' || NEW.id || '|' || 1 || '|' || r.h)
      FROM (SELECT COALESCE((SELECT hash_cadena FROM auditoria_cadena
                              ORDER BY seq DESC LIMIT 1), '0000000000000000000000000000000000000000000000000000000000000000') AS h) AS p,
           (SELECT sha256(json_object(
            'id', NEW.id,
            'ts_ms', NEW.ts_ms,
            'ts_confiable', NEW.ts_confiable,
            'arranque_id', NEW.arranque_id,
            'mono_ms', NEW.mono_ms,
            'clave', NEW.clave,
            'valor_anterior', NEW.valor_anterior,
            'valor_nuevo', NEW.valor_nuevo,
            'version', NEW.version,
            'origen', NEW.origen,
            'actor', NEW.actor,
            'comando_id', NEW.comando_id)) AS h) AS r;
END;

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
            'rev', NEW.rev)) AS h) AS r;
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
            'rev', NEW.rev)) AS h) AS r;
END;

-- ---- alarma ----
CREATE TRIGGER tr_alarma_cadena_insert
AFTER INSERT ON alarma
BEGIN
    INSERT INTO auditoria_cadena
        (tabla, registro_id, rev, creado_ms, hash_registro, hash_previo, hash_cadena)
    SELECT 'alarma', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000, r.h, p.h,
           sha256(p.h || '|' || 'alarma' || '|' || NEW.id || '|' || NEW.rev || '|' || r.h)
      FROM (SELECT COALESCE((SELECT hash_cadena FROM auditoria_cadena
                              ORDER BY seq DESC LIMIT 1), '0000000000000000000000000000000000000000000000000000000000000000') AS h) AS p,
           (SELECT sha256(json_object(
            'id', NEW.id,
            'codigo', NEW.codigo,
            'severidad', NEW.severidad,
            'sensor_id', NEW.sensor_id,
            'periferico_id', NEW.periferico_id,
            'inicio_ms', NEW.inicio_ms,
            'inicio_confiable', NEW.inicio_confiable,
            'arranque_id', NEW.arranque_id,
            'mono_ms', NEW.mono_ms,
            'fin_ms', NEW.fin_ms,
            'fin_confiable', NEW.fin_confiable,
            'umbral', NEW.umbral,
            'valor_disparo', NEW.valor_disparo,
            'valor_pico', NEW.valor_pico,
            'estado', NEW.estado,
            'acuse_ms', NEW.acuse_ms,
            'acuse_actor', NEW.acuse_actor,
            'mensaje', NEW.mensaje,
            'actualizado_ms', NEW.actualizado_ms,
            'rev', NEW.rev)) AS h) AS r;
END;

CREATE TRIGGER tr_alarma_cadena_rev
AFTER UPDATE OF rev ON alarma
WHEN NEW.rev <> OLD.rev
BEGIN
    INSERT INTO auditoria_cadena
        (tabla, registro_id, rev, creado_ms, hash_registro, hash_previo, hash_cadena)
    SELECT 'alarma', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000, r.h, p.h,
           sha256(p.h || '|' || 'alarma' || '|' || NEW.id || '|' || NEW.rev || '|' || r.h)
      FROM (SELECT COALESCE((SELECT hash_cadena FROM auditoria_cadena
                              ORDER BY seq DESC LIMIT 1), '0000000000000000000000000000000000000000000000000000000000000000') AS h) AS p,
           (SELECT sha256(json_object(
            'id', NEW.id,
            'codigo', NEW.codigo,
            'severidad', NEW.severidad,
            'sensor_id', NEW.sensor_id,
            'periferico_id', NEW.periferico_id,
            'inicio_ms', NEW.inicio_ms,
            'inicio_confiable', NEW.inicio_confiable,
            'arranque_id', NEW.arranque_id,
            'mono_ms', NEW.mono_ms,
            'fin_ms', NEW.fin_ms,
            'fin_confiable', NEW.fin_confiable,
            'umbral', NEW.umbral,
            'valor_disparo', NEW.valor_disparo,
            'valor_pico', NEW.valor_pico,
            'estado', NEW.estado,
            'acuse_ms', NEW.acuse_ms,
            'acuse_actor', NEW.acuse_actor,
            'mensaje', NEW.mensaje,
            'actualizado_ms', NEW.actualizado_ms,
            'rev', NEW.rev)) AS h) AS r;
END;

-- ---- evento ----
CREATE TRIGGER tr_evento_cadena_insert
AFTER INSERT ON evento
BEGIN
    INSERT INTO auditoria_cadena
        (tabla, registro_id, rev, creado_ms, hash_registro, hash_previo, hash_cadena)
    SELECT 'evento', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000, r.h, p.h,
           sha256(p.h || '|' || 'evento' || '|' || NEW.id || '|' || NEW.rev || '|' || r.h)
      FROM (SELECT COALESCE((SELECT hash_cadena FROM auditoria_cadena
                              ORDER BY seq DESC LIMIT 1), '0000000000000000000000000000000000000000000000000000000000000000') AS h) AS p,
           (SELECT sha256(json_object(
            'id', NEW.id,
            'ts_ms', NEW.ts_ms,
            'ts_confiable', NEW.ts_confiable,
            'arranque_id', NEW.arranque_id,
            'mono_ms', NEW.mono_ms,
            'codigo', NEW.codigo,
            'severidad', NEW.severidad,
            'origen', NEW.origen,
            'sensor_id', NEW.sensor_id,
            'periferico_id', NEW.periferico_id,
            'mensaje', NEW.mensaje,
            'datos_json', NEW.datos_json,
            'repeticiones', NEW.repeticiones,
            'ultimo_ms', NEW.ultimo_ms,
            'rev', NEW.rev)) AS h) AS r;
END;

CREATE TRIGGER tr_evento_cadena_rev
AFTER UPDATE OF rev ON evento
WHEN NEW.rev <> OLD.rev
BEGIN
    INSERT INTO auditoria_cadena
        (tabla, registro_id, rev, creado_ms, hash_registro, hash_previo, hash_cadena)
    SELECT 'evento', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000, r.h, p.h,
           sha256(p.h || '|' || 'evento' || '|' || NEW.id || '|' || NEW.rev || '|' || r.h)
      FROM (SELECT COALESCE((SELECT hash_cadena FROM auditoria_cadena
                              ORDER BY seq DESC LIMIT 1), '0000000000000000000000000000000000000000000000000000000000000000') AS h) AS p,
           (SELECT sha256(json_object(
            'id', NEW.id,
            'ts_ms', NEW.ts_ms,
            'ts_confiable', NEW.ts_confiable,
            'arranque_id', NEW.arranque_id,
            'mono_ms', NEW.mono_ms,
            'codigo', NEW.codigo,
            'severidad', NEW.severidad,
            'origen', NEW.origen,
            'sensor_id', NEW.sensor_id,
            'periferico_id', NEW.periferico_id,
            'mensaje', NEW.mensaje,
            'datos_json', NEW.datos_json,
            'repeticiones', NEW.repeticiones,
            'ultimo_ms', NEW.ultimo_ms,
            'rev', NEW.rev)) AS h) AS r;
END;

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
            'rev', rev)) AS hash_actual
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
