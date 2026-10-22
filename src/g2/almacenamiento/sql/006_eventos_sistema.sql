-- =============================================================================
-- 006_eventos_sistema.sql  --  Eventos de mantenimiento y de verificacion de la auditoria (D-039)
-- =============================================================================
-- Cada modulo nuevo agrega sus codigos con su propia migracion (ver 002 y 005).
-- =============================================================================

INSERT INTO catalogo_evento (codigo, categoria, severidad, descripcion, accion, es_alarma) VALUES
('SYS_REINICIO_PEDIDO',      'sistema',   2, 'Se pidio reiniciar los servicios o el equipo desde la pantalla o la plataforma.', 'Verificar que el reinicio fue autorizado.', 0),
('SEG_AUDITORIA_VERIFICADA', 'seguridad', 1, 'Se verifico la cadena de auditoria y esta integra.', NULL, 0),
('SEG_AUDITORIA_ALTERADA',   'seguridad', 4, 'La verificacion de la cadena de auditoria encontro diferencias: los datos pudieron alterarse.', 'No confiar en los registros afectados; hacer una copia de la base y contactar a soporte.', 0);
