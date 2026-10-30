-- =============================================================================
-- 009_eventos_plataforma.sql  --  Eventos del enlace con la plataforma sp-peek.com (g2-uplink, D-046)
-- =============================================================================
-- Ninguno lleva el secreto del equipo ni la URL con datos de acceso: solo el estado del enlace y el motivo.
-- El rechazo de registros concretos usa el evento que ya existia (NET_ENVIO_RECHAZADO).
-- =============================================================================

INSERT INTO catalogo_evento (codigo, categoria, severidad, descripcion, accion, es_alarma) VALUES
('PLAT_ENLACE_PERDIDO',       'red',       2, 'El equipo no logra enviar datos a la plataforma; sigue midiendo y guardando, y reintenta solo.', 'Revisar la red del equipo y que la plataforma responda; los datos se envian al volver el enlace.', 0),
('PLAT_ENLACE_RESTABLECIDO',  'red',       1, 'El equipo volvio a enviar datos a la plataforma.', NULL, 0),
('PLAT_CREDENCIAL_RECHAZADA', 'seguridad', 3, 'La plataforma rechazo el secreto o el identificador del equipo; no se envia nada hasta corregirlo.', 'Revisar equipo.id y el secreto guardado (g2ctl plataforma-credencial) y que el equipo este dado de alta en la plataforma.', 0);
