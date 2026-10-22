-- =============================================================================
-- 005_pin_acceso.sql  --  PIN de acceso de la pantalla (D-038)
-- =============================================================================
-- Protege los cambios hechos desde la pantalla tactil (umbrales, calibracion, red). Hay a lo sumo dos:
--   'fabrica'     el de fabrica, que se aprovisiona al instalar el equipo (NO esta en el repositorio, que es
--                 publico: la huella de un PIN de 4 digitos se recuperaria probando los 10 000 valores);
--   'plataforma'  el que asigna la plataforma; cuando existe, el de fabrica deja de valer.
--
-- Solo se guarda la HUELLA (PBKDF2-HMAC-SHA256 con sal propia), nunca el PIN. Esta tabla NO esta en la cola
-- de envio ni en la cadena de auditoria a proposito: la huella de un PIN corto no debe salir del equipo ni
-- viajar a la plataforma. Los cambios de PIN si quedan como EVENTOS (sin el valor), que si se sincronizan.
-- =============================================================================

CREATE TABLE pin_acceso (
    tipo            TEXT    PRIMARY KEY CHECK (tipo IN ('fabrica', 'plataforma')),
    sal             BLOB    NOT NULL CHECK (length(sal) >= 16),
    huella          BLOB    NOT NULL CHECK (length(huella) = 32),
    iteraciones     INTEGER NOT NULL CHECK (iteraciones >= 10000),
    actualizado_ms  INTEGER NOT NULL,
    actor           TEXT
) STRICT;

INSERT INTO catalogo_evento (codigo, categoria, severidad, descripcion, accion, es_alarma) VALUES
('SEG_PIN_ACEPTADO',   'seguridad', 1, 'Se acepto el PIN en la pantalla.', NULL, 0),
('SEG_PIN_FALLIDO',    'seguridad', 2, 'Se tecleo un PIN incorrecto en la pantalla.', 'Si no fue el personal autorizado, revisar el acceso fisico al equipo.', 0),
('SEG_PIN_BLOQUEADO',  'seguridad', 3, 'La pantalla se bloqueo por intentos fallidos de PIN.', 'Revisar quien tuvo acceso a la pantalla; el bloqueo termina solo.', 0),
('SEG_PIN_CAMBIADO',   'seguridad', 2, 'Se cambio un PIN de acceso (el valor no se registra).', 'Verificar que el cambio fue autorizado.', 0);
