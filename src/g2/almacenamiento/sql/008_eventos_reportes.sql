-- =============================================================================
-- 008_eventos_reportes.sql  --  Eventos de la exportacion de reportes a USB (D-044)
-- =============================================================================
-- Ningun evento lleva la contrasena del PDF (es el nombre del equipo): solo el rango, el archivo y su huella SHA-256.
-- =============================================================================

INSERT INTO catalogo_evento (codigo, categoria, severidad, descripcion, accion, es_alarma) VALUES
('REPORTE_GENERADO',  'reporte', 1, 'Se genero un reporte en PDF cifrado y se copio a la memoria USB; el evento guarda su huella SHA-256.', NULL, 0),
('REPORTE_FALLIDO',   'reporte', 2, 'No se pudo generar o copiar el reporte (memoria USB ausente o con otro nombre, rango muy grande, error al copiar).', 'Revisar el mensaje: la memoria USB debe llamarse igual que el equipo.', 0),
('REPORTE_CANCELADO', 'reporte', 1, 'El reporte se cancelo antes de terminar; no se dejo ningun archivo en la memoria USB.', NULL, 0);
