-- =============================================================================
-- 007_eventos_red.sql  --  Eventos del cambio de red (D-040)
-- =============================================================================
-- Ningun evento lleva la contrasena de la red: solo su nombre y el resultado.
-- =============================================================================

INSERT INTO catalogo_evento (codigo, categoria, severidad, descripcion, accion, es_alarma) VALUES
('RED_CAMBIO_SOLICITADO', 'red', 1, 'Se pidio conectar el equipo a otra red (pantalla o plataforma).', NULL, 0),
('RED_CAMBIO_OK',         'red', 1, 'El equipo se conecto a la red nueva.', NULL, 0),
('RED_CAMBIO_FALLIDO',    'red', 2, 'No se pudo conectar a la red nueva; el equipo volvio a la anterior si la tenia.', 'Revisar el nombre y la contrasena de la red y la cobertura.', 0);
