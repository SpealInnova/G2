-- =============================================================================
-- 012_pantalla_inestable.sql  --  Reinicios de la pantalla Nextion (D-050)
-- =============================================================================
-- La pantalla Nextion tiene su propia fuente y puede reiniciarse sola (cortes o caidas de voltaje en su alimentacion). g2-ui se entera
-- cuando la pantalla avisa que acaba de encender y se lo dice al nucleo, que lo deja como evento (los seguidos se agrupan en uno con
-- `repeticiones`) y abre una alarma del sistema si son 5 o mas en 10 minutos. La alarma no suena ni mueve relevos.
-- =============================================================================

INSERT INTO catalogo_evento (codigo, categoria, severidad, descripcion, accion, es_alarma) VALUES
('PANT_REINICIADA',        'pantalla', 2, 'La pantalla Nextion se reinicio sola con el equipo en marcha.', 'Si se repite, revisar la alimentacion de la pantalla (fuente, cable y tierra comun).', 0),
('ALM_PANTALLA_INESTABLE', 'alarma',   3, 'La pantalla Nextion se reinicio 5 veces o mas en 10 minutos.', 'Revisar la fuente de alimentacion de la pantalla (su voltaje al arrancar), el cable y la tierra comun con la Raspberry Pi.', 1);
