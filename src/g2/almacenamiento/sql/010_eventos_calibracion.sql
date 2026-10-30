-- =============================================================================
-- 010_eventos_calibracion.sql  --  Eventos de la calibracion de cero en aire (D-048)
-- =============================================================================
-- CAL_REGISTRADA y CAL_FALLIDA ya existian (002). Se suman el inicio y la cancelacion para que toda la calibracion
-- quede en el registro: quien la pidio, cuando empezo y como termino.
-- =============================================================================

INSERT INTO catalogo_evento (codigo, categoria, severidad, descripcion, accion, es_alarma) VALUES
('CAL_INICIADA',  'calibracion', 1, 'Empezo la calibracion de cero en aire de un sensor; sus alarmas quedan suspendidas mientras dura.', NULL, 0),
('CAL_CANCELADA', 'calibracion', 2, 'Se cancelo la calibracion antes de terminar; no se cambio nada.', 'Repetir la calibracion con el sensor al aire.', 0);
