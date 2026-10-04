-- =============================================================================
-- 002_catalogo_inicial.sql  --  Codigos iniciales de eventos y alarmas
-- =============================================================================
-- Cada modulo nuevo agrega sus codigos con su propia migracion. Los codigos son
-- estables: una vez publicados no se renombran (la plataforma y los reportes
-- los usan como identificador).
-- Severidad: 0 depuracion, 1 informacion, 2 aviso, 3 error, 4 critico.
-- =============================================================================

INSERT INTO catalogo_evento (codigo, categoria, severidad, descripcion, accion, es_alarma) VALUES
-- Sistema
('SYS_ARRANQUE',            'sistema',  1, 'El equipo arranco.', NULL, 0),
('SYS_APAGADO_LIMPIO',      'sistema',  1, 'El equipo se apago de forma ordenada.', NULL, 0),
('SYS_REINICIO_ANORMAL',    'sistema',  3, 'El arranque anterior no termino con un apagado ordenado (watchdog, corte de energia o bajo voltaje).', 'Revisar la causa registrada en arranque y la alimentacion del equipo.', 0),
('SYS_SALUD_PERIODICA',     'sistema',  0, 'Registro periodico del estado de salud (cada 30 minutos).', NULL, 0),
('SYS_RELOJ_NO_CONFIABLE',  'sistema',  2, 'El reloj del equipo no esta sincronizado; las horas se corregiran al sincronizar.', 'Conectar a internet o revisar el reloj de tiempo real.', 0),
('SYS_RELOJ_SINCRONIZADO',  'sistema',  1, 'El reloj se sincronizo; se corrigieron las horas de los registros pendientes.', NULL, 0),
('SYS_AUTODIAGNOSTICO',     'sistema',  1, 'Resultado del autodiagnostico de arranque.', NULL, 0),
('SYS_MODO_SEGURO',         'sistema',  4, 'El equipo arranco en modo seguro tras reinicios repetidos.', 'Contactar a soporte; revisar el diagnostico remoto.', 0),
-- Base de datos
('DB_DEPURACION',           'base_datos', 1, 'Se ejecuto la depuracion por retencion.', NULL, 0),
('DB_ERROR',                'base_datos', 3, 'Error de la base de datos interna.', 'Revisar el detalle del evento y el diagnostico remoto.', 0),
-- Red y plataforma
('NET_CONECTADA',           'red',      1, 'Conexion a internet establecida.', NULL, 0),
('NET_DESCONECTADA',        'red',      2, 'Se perdio la conexion a internet; el equipo sigue midiendo y almacenando.', 'Revisar la red; los datos se enviaran al reconectar.', 0),
('NET_ENVIO_RECHAZADO',     'red',      3, 'La plataforma rechazo un registro por datos invalidos.', 'Revisar el registro en cola_envio (estado rechazado).', 0),
('NET_COLA_ACUMULADA',      'red',      2, 'La cola de envio supera el umbral de registros pendientes.', 'Revisar la conexion con la plataforma.', 0),
-- Sensores de oxigeno
('SEN_HABILITADO',          'sensor',   1, 'Sensor habilitado.', NULL, 0),
('SEN_DESHABILITADO',       'sensor',   1, 'Sensor deshabilitado por el usuario.', NULL, 0),
('SEN_FALLA',               'sensor',   3, 'El sensor no entrega una señal valida (sin datos o fuera del ADC).', 'Revisar cableado, alimentacion de 5 V y el LED del sensor.', 0),
('SEN_RECUPERADO',          'sensor',   1, 'El sensor volvio a entregar una señal valida.', NULL, 0),
('SEN_SATURADO',            'sensor',   2, 'La señal del sensor esta en el limite de su rango (-15 % o +200 %).', 'Verificar el gas de la muestra y la calibracion.', 0),
('SEN_SPOC_DETECTADO',      'sensor',   1, 'Se detecto un SPOC en curso (la señal oscila entre extremos); las muestras se marcan como en_spoc.', NULL, 0),
-- Calibracion
('CAL_REGISTRADA',          'calibracion', 1, 'Se registro una calibracion.', NULL, 0),
('CAL_FALLIDA',             'calibracion', 3, 'La calibracion no se pudo completar.', 'Repetir con gas estable y flujo constante.', 0),
-- Configuracion y comandos
('CFG_CAMBIO',              'configuracion', 1, 'Se cambio un parametro de configuracion.', NULL, 0),
('CMD_RECHAZADO',           'comando',  2, 'Se rechazo un comando (sin autorizacion, parametros invalidos o condiciones no cumplidas).', NULL, 0),
-- Perifericos
('PER_FALLA',               'periferico', 3, 'Un periferico no responde o entrega valores invalidos.', 'Revisar conexion del periferico.', 0),
('PER_RECUPERADO',          'periferico', 1, 'Un periferico volvio a responder.', NULL, 0),
-- Supervision de servicios (vigilancia de bloqueos)
('SVC_REINICIADO',          'servicio', 2, 'systemd reinicio un servicio de G2 tras una falla.', 'Revisar el detalle del evento y los registros del servicio.', 0),
('SVC_BLOQUEO_DETECTADO',   'servicio', 3, 'Un servicio dejo de reportar avance y fue reiniciado por el watchdog.', 'Revisar el detalle: que operacion se bloqueo.', 0),
('SVC_LIMITE_REINICIOS',    'servicio', 4, 'Un servicio supero el limite de reinicios seguidos; el equipo escala a reinicio o modo seguro.', 'Contactar a soporte; revisar el diagnostico remoto.', 0),
-- Salidas
('OUT_ACTIVADA',            'salida',   1, 'Se activo una salida (rele, electrovalvula, LED, sonido).', NULL, 0),
('OUT_DESACTIVADA',         'salida',   1, 'Se desactivo una salida.', NULL, 0),
-- Alarmas (es_alarma = 1). Las de salud y disco tienen umbrales configurables
-- desde la pantalla y la plataforma, igual que las de oxigeno.
('ALM_O2_ALTO',             'alarma',   3, 'El oxigeno supera el maximo configurado.', 'Revisar el proceso y el sensor.', 1),
('ALM_O2_BAJO',             'alarma',   3, 'El oxigeno esta bajo el minimo configurado.', 'Revisar el proceso y el sensor.', 1),
('ALM_SENSOR_INVALIDO',     'alarma',   3, 'Un sensor entrega lecturas invalidas.', 'Revisar el sensor (ver SEN_FALLA).', 1),
('ALM_SENSORES_DISCREPANTES','alarma',  2, 'La diferencia entre sensores supera el limite configurado.', 'Verificar calibracion de ambos sensores con el mismo gas.', 1),
('ALM_TEMP_ALTA',           'alarma',   2, 'Temperatura fuera del limite configurado.', 'Revisar ventilacion y ubicacion.', 1),
('ALM_HUMEDAD_ALTA',        'alarma',   2, 'Humedad fuera del limite configurado.', 'Revisar la linea de muestra y el sellado.', 1),
('ALM_RPI_TEMP_ALTA',       'alarma',   2, 'La temperatura del procesador de la Raspberry Pi supera el umbral configurado.', 'Revisar ventilacion; el equipo reduce su actividad no esencial.', 1),
('ALM_RPI_RAM_ALTA',        'alarma',   2, 'El uso de memoria RAM supera el umbral configurado.', 'Revisar el diagnostico remoto; posible fuga de memoria.', 1),
('ALM_RPI_BAJO_VOLTAJE',    'alarma',   3, 'La Raspberry Pi detecto voltaje de alimentacion bajo.', 'Revisar la fuente de alimentacion y el cableado.', 1),
('ALM_DISCO_ESPACIO_BAJO',  'alarma',   2, 'El espacio libre de la tarjeta SD esta bajo el umbral de aviso.', 'Programar un respaldo y revisar la conexion con la plataforma.', 1),
('ALM_DISCO_ESPACIO_CRITICO','alarma',  4, 'El espacio libre de la tarjeta SD esta bajo el umbral critico.', 'Hacer el respaldo de inmediato y restablecer la conexion con la plataforma.', 1),
('ALM_VIBRACION',           'alarma',   2, 'Vibracion o golpe sobre el limite configurado; las lecturas pueden ser erroneas.', 'Revisar el montaje del sensor.', 1);
