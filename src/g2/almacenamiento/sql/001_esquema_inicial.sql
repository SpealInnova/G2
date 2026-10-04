-- =============================================================================
-- 001_esquema_inicial.sql  --  Esquema inicial de la base de datos interna de G2
-- =============================================================================
-- Motor: SQLite (decision D-001). Todas las tablas son STRICT: SQLite rechaza
-- valores de un tipo distinto al declarado, en vez de convertirlos en silencio.
--
-- Las decisiones de diseño y su justificacion estan en MEMORIA_TECNICA.md
-- (D-007 a D-010). Resumen de las reglas que este archivo hace cumplir:
--
--  1. TIEMPO. Cada registro lleva la hora UTC en milisegundos (ts_ms) y una
--     marca de si el reloj era confiable (ts_confiable). Ademas guarda el
--     arranque al que pertenece (arranque_id) y el tiempo monotonico desde el
--     arranque (mono_ms). Si el equipo arranco sin hora real, la hora correcta
--     se recupera despues de sincronizar el reloj:
--         ts_corregido = arranque.sincronizado_utc_ms
--                        + (mono_ms - arranque.sincronizado_mono_ms)
--
--  2. SINCRONIZACION SIN PERDIDA. Todo registro que debe llegar a la
--     plataforma se encola AUTOMATICAMENTE en cola_envio (por referencia, no
--     por copia) mediante disparadores, en la misma transaccion que lo creo.
--     Ningun codigo puede olvidarse de encolar.
--
--  3. BORRADO SOLO CON CONFIRMACION. Un registro sincronizable no se puede
--     borrar mientras no tenga al menos una entrada en cola_envio y todas sus
--     entradas esten en estado 'confirmado'. Lo hace cumplir un disparador de
--     la propia base de datos, no el codigo de la aplicacion.
--     'confirmado' significa que la plataforma devolvio la confirmacion
--     explicita de que ese registro (tabla, id, rev) quedo almacenado
--     correctamente; un simple envio exitoso NO basta.
--
--  4. REVISIONES. Las tablas cuyos registros cambian despues de creados
--     (alarma, evento, comando, calibracion, arranque) llevan una columna rev.
--     Cada modificacion aumenta rev y encola la nueva revision.
--
-- Convenciones: nombres en español sin tildes, snake_case; fechas en
-- milisegundos UTC (epoch); booleanos como 0/1.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Control de versiones del esquema
-- -----------------------------------------------------------------------------
CREATE TABLE esquema_version (
    version      INTEGER PRIMARY KEY,
    descripcion  TEXT    NOT NULL,
    aplicada_ms  INTEGER NOT NULL
) STRICT;

-- -----------------------------------------------------------------------------
-- arranque: un registro por cada encendido del equipo (reporte de reinicios).
-- boot_id identifica el arranque; las demas tablas lo referencian por id.
-- -----------------------------------------------------------------------------
CREATE TABLE arranque (
    id                   INTEGER PRIMARY KEY,
    boot_id              TEXT    NOT NULL UNIQUE,
    inicio_ms            INTEGER NOT NULL,
    inicio_confiable     INTEGER NOT NULL CHECK (inicio_confiable IN (0, 1)),
    -- Se completan cuando el reloj se sincroniza (NTP o RTC). Permiten
    -- corregir las horas de los registros hechos antes (ver regla 1).
    sincronizado_utc_ms  INTEGER,
    sincronizado_mono_ms INTEGER,
    causa                TEXT    NOT NULL DEFAULT 'desconocida'
                         CHECK (causa IN ('limpio', 'watchdog', 'corte_energia',
                                          'bajo_voltaje', 'desconocida')),
    version_sw           TEXT    NOT NULL,
    version_config       INTEGER,
    uptime_previo_s      INTEGER,
    throttled            TEXT,          -- salida de vcgencmd get_throttled
    rev                  INTEGER NOT NULL DEFAULT 1 CHECK (rev >= 1),
    CHECK ((sincronizado_utc_ms IS NULL) = (sincronizado_mono_ms IS NULL))
) STRICT;

-- -----------------------------------------------------------------------------
-- catalogo_evento: todos los codigos de eventos y alarmas que el equipo puede
-- generar, con su descripcion y la accion recomendada. Agregar un codigo nuevo
-- es un INSERT, no un cambio de esquema. Base de los mensajes en pantalla y
-- del manual tecnico.
-- -----------------------------------------------------------------------------
CREATE TABLE catalogo_evento (
    codigo       TEXT    PRIMARY KEY,
    categoria    TEXT    NOT NULL,
    severidad    INTEGER NOT NULL CHECK (severidad BETWEEN 0 AND 4),
    descripcion  TEXT    NOT NULL,
    accion       TEXT,
    es_alarma    INTEGER NOT NULL DEFAULT 0 CHECK (es_alarma IN (0, 1))
) STRICT;
-- Severidad: 0 depuracion, 1 informacion, 2 aviso, 3 error, 4 critico.

-- -----------------------------------------------------------------------------
-- comando: cada orden recibida por pantalla, plataforma o localmente.
-- uuid unico evita ejecutar dos veces la misma orden (idempotencia).
-- -----------------------------------------------------------------------------
CREATE TABLE comando (
    id               INTEGER PRIMARY KEY,
    uuid             TEXT    NOT NULL UNIQUE,
    ts_ms            INTEGER NOT NULL,
    ts_confiable     INTEGER NOT NULL CHECK (ts_confiable IN (0, 1)),
    arranque_id      INTEGER NOT NULL REFERENCES arranque (id),
    mono_ms          INTEGER NOT NULL CHECK (mono_ms >= 0),
    origen           TEXT    NOT NULL CHECK (origen IN ('pantalla', 'plataforma', 'local')),
    actor            TEXT,
    tipo             TEXT    NOT NULL,
    parametros_json  TEXT    CHECK (parametros_json IS NULL OR json_valid(parametros_json)),
    estado           TEXT    NOT NULL DEFAULT 'recibido'
                     CHECK (estado IN ('recibido', 'ejecutando', 'ok', 'error', 'rechazado')),
    fin_ms           INTEGER,
    resultado_json   TEXT    CHECK (resultado_json IS NULL OR json_valid(resultado_json)),
    rev              INTEGER NOT NULL DEFAULT 1 CHECK (rev >= 1)
) STRICT;

-- -----------------------------------------------------------------------------
-- config: valor vigente de cada parametro configurable (desde pantalla o
-- plataforma). config_historial guarda cada cambio (auditoria).
-- La regla de conflicto entre pantalla y plataforma es: gana el cambio mas
-- reciente; version aumenta con cada cambio de la clave.
-- -----------------------------------------------------------------------------
CREATE TABLE config (
    clave          TEXT    PRIMARY KEY,
    valor          TEXT    NOT NULL,
    tipo           TEXT    NOT NULL
                   CHECK (tipo IN ('entero', 'real', 'texto', 'booleano', 'json')),
    version        INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    origen         TEXT    NOT NULL
                   CHECK (origen IN ('defecto', 'pantalla', 'plataforma', 'local')),
    actor          TEXT,
    actualizado_ms INTEGER NOT NULL
) STRICT;

CREATE TABLE config_historial (
    id              INTEGER PRIMARY KEY,
    ts_ms           INTEGER NOT NULL,
    ts_confiable    INTEGER NOT NULL CHECK (ts_confiable IN (0, 1)),
    arranque_id     INTEGER NOT NULL REFERENCES arranque (id),
    mono_ms         INTEGER NOT NULL CHECK (mono_ms >= 0),
    clave           TEXT    NOT NULL,
    valor_anterior  TEXT,
    valor_nuevo     TEXT    NOT NULL,
    version         INTEGER NOT NULL,
    origen          TEXT    NOT NULL
                    CHECK (origen IN ('defecto', 'pantalla', 'plataforma', 'local')),
    actor           TEXT,
    comando_id      INTEGER REFERENCES comando (id)
) STRICT;

-- -----------------------------------------------------------------------------
-- sensor: sensores de oxigeno instalados. El sensor analogico (D-003) no se
-- identifica por si mismo, por eso se registra aqui el canal del ADC y la serie
-- de la etiqueta.
-- -----------------------------------------------------------------------------
CREATE TABLE sensor (
    id               INTEGER PRIMARY KEY,
    canal            TEXT    NOT NULL UNIQUE,   -- p. ej. 'ads1115:0x48:diff0-1'
    nombre           TEXT    NOT NULL,
    modelo           TEXT    NOT NULL,
    variante         TEXT,
    serie_etiqueta   TEXT,
    mv_por_pct       REAL    NOT NULL CHECK (mv_por_pct > 0),   -- 10.0 en 01117707
    mv_aire_objetivo REAL,                      -- mV esperados en aire tras un SPOC
    rango_min_pct    REAL    NOT NULL DEFAULT -15.0,
    rango_max_pct    REAL    NOT NULL DEFAULT 200.0,
    habilitado       INTEGER NOT NULL DEFAULT 1 CHECK (habilitado IN (0, 1)),
    instalado_ms     INTEGER,
    notas            TEXT,
    CHECK (rango_min_pct < rango_max_pct)
) STRICT;

-- -----------------------------------------------------------------------------
-- calibracion: cada correccion registrada de un sensor (auditoria: quien,
-- cuando, con que gas y con que certificado).
--   tipo 'fabrica'    : valores de fabrica registrados al instalar.
--   tipo 'offset_cero': correccion de cero en el equipo (manual, seccion 5.2).
--   tipo 'spoc_boton' : SPOC hecho con el boton fisico del sensor; el equipo
--                       solo lo registra (no conoce el offset interno).
-- Solo una calibracion vigente por sensor (indice unico parcial).
-- -----------------------------------------------------------------------------
CREATE TABLE calibracion (
    id               INTEGER PRIMARY KEY,
    ts_ms            INTEGER NOT NULL,
    ts_confiable     INTEGER NOT NULL CHECK (ts_confiable IN (0, 1)),
    arranque_id      INTEGER NOT NULL REFERENCES arranque (id),
    mono_ms          INTEGER NOT NULL CHECK (mono_ms >= 0),
    sensor_id        INTEGER NOT NULL REFERENCES sensor (id),
    tipo             TEXT    NOT NULL CHECK (tipo IN ('fabrica', 'offset_cero', 'spoc_boton')),
    gas_pct          REAL,                      -- concentracion real del gas aplicado
    gas_certificado  TEXT,                      -- certificado o lote del gas
    mv_antes         REAL,
    mv_despues       REAL,
    offset_pct       REAL,                      -- correccion en % de O2 (si aplica)
    presion_hpa      REAL,
    temperatura_c    REAL,
    origen           TEXT    NOT NULL CHECK (origen IN ('pantalla', 'plataforma', 'local')),
    actor            TEXT,
    comando_id       INTEGER REFERENCES comando (id),
    resultado        TEXT    NOT NULL CHECK (resultado IN ('ok', 'fallo')),
    vigente          INTEGER NOT NULL DEFAULT 0 CHECK (vigente IN (0, 1)),
    notas            TEXT,
    rev              INTEGER NOT NULL DEFAULT 1 CHECK (rev >= 1),
    CHECK (NOT (resultado = 'fallo' AND vigente = 1))
) STRICT;

CREATE UNIQUE INDEX ux_calibracion_vigente
    ON calibracion (sensor_id) WHERE vigente = 1;

-- -----------------------------------------------------------------------------
-- lectura: datos de oxigeno por sensor, agregados por intervalo de
-- almacenamiento (decision D-007): promedio, minimo y maximo de las muestras
-- del intervalo. ts_ms es el instante en que termina el intervalo.
--
-- calidad es una mascara de bits (0 = lectura valida):
--     1 saturada_baja   2 saturada_alta   4 en_spoc (calibrando)
--     8 deshabilitado  16 inestable      32 sin_datos   64 fuera_de_rango
-- Si no hubo muestras (n_muestras = 0) los valores de O2 y mV son NULL; asi un
-- hueco queda registrado como hueco y no como un cero falso.
-- -----------------------------------------------------------------------------
CREATE TABLE lectura (
    id             INTEGER PRIMARY KEY,
    ts_ms          INTEGER NOT NULL,
    ts_confiable   INTEGER NOT NULL CHECK (ts_confiable IN (0, 1)),
    arranque_id    INTEGER NOT NULL REFERENCES arranque (id),
    mono_ms        INTEGER NOT NULL CHECK (mono_ms >= 0),
    sensor_id      INTEGER NOT NULL REFERENCES sensor (id),
    periodo_ms     INTEGER NOT NULL CHECK (periodo_ms > 0),
    n_muestras     INTEGER NOT NULL CHECK (n_muestras >= 0),
    o2_prom        REAL,
    o2_min         REAL,
    o2_max         REAL,
    mv_prom        REAL,
    calidad        INTEGER NOT NULL DEFAULT 0 CHECK (calidad >= 0),
    calibracion_id INTEGER REFERENCES calibracion (id),
    CHECK (n_muestras > 0 OR (o2_prom IS NULL AND o2_min IS NULL
                              AND o2_max IS NULL AND mv_prom IS NULL)),
    CHECK (o2_min IS NULL OR o2_max IS NULL OR o2_min <= o2_max)
) STRICT;

CREATE INDEX ix_lectura_sensor_ts ON lectura (sensor_id, ts_ms);
CREATE INDEX ix_lectura_ts        ON lectura (ts_ms);

-- -----------------------------------------------------------------------------
-- periferico / medicion_periferico: temperatura, humedad, presion, vibracion
-- y cualquier sensor futuro. Una medicion por magnitud e intervalo, de modo que
-- un periferico nuevo no exige cambiar el esquema.
-- magnitud: p. ej. 'temperatura_c', 'humedad_pct', 'presion_hpa',
--           'vibracion_g_rms', 'vibracion_g_pico'.
-- calidad usa la misma mascara de bits que lectura.
-- -----------------------------------------------------------------------------
CREATE TABLE periferico (
    id          INTEGER PRIMARY KEY,
    tipo        TEXT    NOT NULL,
    nombre      TEXT    NOT NULL UNIQUE,
    bus         TEXT,                           -- 'i2c', 'gpio', ...
    direccion   TEXT,                           -- p. ej. '0x76'
    habilitado  INTEGER NOT NULL DEFAULT 1 CHECK (habilitado IN (0, 1)),
    notas       TEXT
) STRICT;

CREATE TABLE medicion_periferico (
    id            INTEGER PRIMARY KEY,
    ts_ms         INTEGER NOT NULL,
    ts_confiable  INTEGER NOT NULL CHECK (ts_confiable IN (0, 1)),
    arranque_id   INTEGER NOT NULL REFERENCES arranque (id),
    mono_ms       INTEGER NOT NULL CHECK (mono_ms >= 0),
    periferico_id INTEGER NOT NULL REFERENCES periferico (id),
    magnitud      TEXT    NOT NULL,
    periodo_ms    INTEGER NOT NULL CHECK (periodo_ms > 0),
    n_muestras    INTEGER NOT NULL CHECK (n_muestras >= 0),
    prom          REAL,
    minimo        REAL,
    maximo        REAL,
    calidad       INTEGER NOT NULL DEFAULT 0 CHECK (calidad >= 0),
    CHECK (n_muestras > 0 OR (prom IS NULL AND minimo IS NULL AND maximo IS NULL))
) STRICT;

CREATE INDEX ix_medicion_per_ts ON medicion_periferico (periferico_id, magnitud, ts_ms);

-- -----------------------------------------------------------------------------
-- alarma: un registro por episodio (inicio, fin, acuse), no por muestra.
-- El codigo debe existir en catalogo_evento con es_alarma = 1.
-- -----------------------------------------------------------------------------
CREATE TABLE alarma (
    id               INTEGER PRIMARY KEY,
    codigo           TEXT    NOT NULL REFERENCES catalogo_evento (codigo),
    severidad        INTEGER NOT NULL CHECK (severidad BETWEEN 0 AND 4),
    sensor_id        INTEGER REFERENCES sensor (id),
    periferico_id    INTEGER REFERENCES periferico (id),
    inicio_ms        INTEGER NOT NULL,
    inicio_confiable INTEGER NOT NULL CHECK (inicio_confiable IN (0, 1)),
    arranque_id      INTEGER NOT NULL REFERENCES arranque (id),
    mono_ms          INTEGER NOT NULL CHECK (mono_ms >= 0),   -- instante del inicio
    fin_ms           INTEGER,
    fin_confiable    INTEGER CHECK (fin_confiable IN (0, 1)),
    umbral           REAL,
    valor_disparo    REAL,
    valor_pico       REAL,
    estado           TEXT    NOT NULL DEFAULT 'activa'
                     CHECK (estado IN ('activa', 'acusada', 'cerrada')),
    acuse_ms         INTEGER,
    acuse_actor      TEXT,
    mensaje          TEXT,
    actualizado_ms   INTEGER NOT NULL,
    rev              INTEGER NOT NULL DEFAULT 1 CHECK (rev >= 1),
    CHECK (estado <> 'cerrada' OR fin_ms IS NOT NULL),
    CHECK (estado <> 'acusada' OR acuse_ms IS NOT NULL),
    CHECK ((fin_ms IS NULL) = (fin_confiable IS NULL))
) STRICT;

CREATE INDEX ix_alarma_estado ON alarma (estado);
CREATE INDEX ix_alarma_inicio ON alarma (inicio_ms);

-- -----------------------------------------------------------------------------
-- evento: todo hecho relevante que no es una lectura ni una alarma (arranques,
-- red, sensores, periféricos, configuracion, calibracion, salidas, energia).
-- Los eventos identicos y consecutivos se agrupan en un solo registro con
-- repeticiones y ultimo_ms, para que una falla constante no llene la base.
-- -----------------------------------------------------------------------------
CREATE TABLE evento (
    id             INTEGER PRIMARY KEY,
    ts_ms          INTEGER NOT NULL,
    ts_confiable   INTEGER NOT NULL CHECK (ts_confiable IN (0, 1)),
    arranque_id    INTEGER NOT NULL REFERENCES arranque (id),
    mono_ms        INTEGER NOT NULL CHECK (mono_ms >= 0),
    codigo         TEXT    NOT NULL REFERENCES catalogo_evento (codigo),
    severidad      INTEGER NOT NULL CHECK (severidad BETWEEN 0 AND 4),
    origen         TEXT    NOT NULL,            -- servicio.modulo que lo genero
    sensor_id      INTEGER REFERENCES sensor (id),
    periferico_id  INTEGER REFERENCES periferico (id),
    mensaje        TEXT,
    datos_json     TEXT    CHECK (datos_json IS NULL OR json_valid(datos_json)),
    repeticiones   INTEGER NOT NULL DEFAULT 1 CHECK (repeticiones >= 1),
    ultimo_ms      INTEGER,
    rev            INTEGER NOT NULL DEFAULT 1 CHECK (rev >= 1)
) STRICT;

CREATE INDEX ix_evento_ts     ON evento (ts_ms);
CREATE INDEX ix_evento_codigo ON evento (codigo, ts_ms);

-- -----------------------------------------------------------------------------
-- salud: estado de la Raspberry Pi (temperatura, carga, memoria, disco,
-- energia, red). Politica (D-011): se guarda cada 30 minutos (motivo
-- 'SYS_SALUD_PERIODICA') y, ademas, de forma asincrona cuando ocurre una
-- alarma de salud (temperatura alta, RAM alta, bajo voltaje, espacio de disco);
-- en ese caso motivo es el codigo de esa alarma (ver catalogo_evento), de modo
-- que cada fila explica por que se guardo.
-- tension_5v y corriente_ma quedan NULL hasta incorporar el medidor INA219
-- (decision pendiente); mientras tanto el bajo voltaje se toma del indicador
-- `throttled` de la propia Raspberry Pi.
-- -----------------------------------------------------------------------------
CREATE TABLE salud (
    id              INTEGER PRIMARY KEY,
    ts_ms           INTEGER NOT NULL,
    ts_confiable    INTEGER NOT NULL CHECK (ts_confiable IN (0, 1)),
    arranque_id     INTEGER NOT NULL REFERENCES arranque (id),
    mono_ms         INTEGER NOT NULL CHECK (mono_ms >= 0),
    motivo          TEXT    NOT NULL DEFAULT 'SYS_SALUD_PERIODICA'
                    REFERENCES catalogo_evento (codigo),
    cpu_temp_c      REAL,
    cpu_pct         REAL,
    mem_pct         REAL,
    disco_pct       REAL,
    throttled       TEXT,
    tension_5v      REAL,
    corriente_ma    REAL,
    red_ok          INTEGER CHECK (red_ok IN (0, 1)),
    wifi_rssi_dbm   INTEGER,
    db_bytes        INTEGER,
    uptime_s        INTEGER
) STRICT;

CREATE INDEX ix_salud_ts ON salud (ts_ms);

-- -----------------------------------------------------------------------------
-- cola_envio: lista de lo que falta por confirmar con la plataforma (outbox).
-- Guarda solo una REFERENCIA (tabla, registro_id, rev) (decision D-008); el
-- mensaje se arma desde la fila al enviar.
--
-- Estados:
--   pendiente : aun no enviado (o hay que reintentar).
--   enviado   : enviado, esperando la confirmacion de la plataforma.
--   confirmado: la plataforma confirmo explicitamente que lo almaceno bien.
--               Es el UNICO estado que permite borrar el registro (regla 3).
--   rechazado : la plataforma lo rechazo (datos invalidos). No se borra; exige
--               atencion y genera un evento NET_ENVIO_RECHAZADO.
-- Regla para el modulo de envio: al confirmar la revision mas reciente de un
-- registro, se pueden marcar como confirmadas las revisiones anteriores.
-- -----------------------------------------------------------------------------
CREATE TABLE cola_envio (
    id                 INTEGER PRIMARY KEY,
    tabla              TEXT    NOT NULL
                       CHECK (tabla IN ('lectura', 'medicion_periferico', 'salud',
                                        'config_historial', 'alarma', 'evento',
                                        'comando', 'calibracion', 'arranque',
                                        'auditoria_cadena')),
    registro_id        INTEGER NOT NULL,
    rev                INTEGER NOT NULL DEFAULT 1 CHECK (rev >= 1),
    creado_ms          INTEGER NOT NULL,
    estado             TEXT    NOT NULL DEFAULT 'pendiente'
                       CHECK (estado IN ('pendiente', 'enviado', 'confirmado', 'rechazado')),
    intentos           INTEGER NOT NULL DEFAULT 0 CHECK (intentos >= 0),
    proximo_intento_ms INTEGER,
    enviado_ms         INTEGER,
    confirmado_ms      INTEGER,
    ultimo_error       TEXT,
    UNIQUE (tabla, registro_id, rev),
    CHECK (estado <> 'confirmado' OR confirmado_ms IS NOT NULL)
) STRICT;

CREATE INDEX ix_cola_estado ON cola_envio (estado, proximo_intento_ms);
CREATE INDEX ix_cola_ref    ON cola_envio (tabla, registro_id);

-- -----------------------------------------------------------------------------
-- Vistas de consulta
-- -----------------------------------------------------------------------------

-- Registros que se pueden borrar: tienen cola y todas sus entradas estan
-- confirmadas. La depuracion por retencion debe seleccionar SOLO desde aqui;
-- si intentara borrar otro registro, el disparador de proteccion abortaria la
-- sentencia completa.
CREATE VIEW v_depurable AS
    SELECT tabla, registro_id
      FROM cola_envio
     GROUP BY tabla, registro_id
    HAVING SUM(estado <> 'confirmado') = 0;

CREATE VIEW v_alarmas_activas AS
    SELECT * FROM alarma WHERE estado <> 'cerrada';

CREATE VIEW v_cola_resumen AS
    SELECT tabla, estado, COUNT(*) AS cantidad, MIN(creado_ms) AS mas_antiguo_ms
      FROM cola_envio
     GROUP BY tabla, estado;

-- Trazabilidad de cada lectura (auditoria): de que sensor (serie de la
-- etiqueta) salio, con que calibracion vigente (gas y certificado), en que
-- arranque (version de software y de configuracion), a que hora real (corregida
-- si el reloj no era confiable) y en que estado esta su entrega a la plataforma.
-- ts_corregido_ms es NULL solo si el reloj aun no se ha sincronizado.
CREATE VIEW v_lectura_trazabilidad AS
SELECT l.id AS lectura_id,
       l.ts_ms,
       l.ts_confiable,
       CASE WHEN l.ts_confiable = 1 THEN l.ts_ms
            WHEN a.sincronizado_utc_ms IS NOT NULL
                 THEN a.sincronizado_utc_ms + (l.mono_ms - a.sincronizado_mono_ms)
       END AS ts_corregido_ms,
       l.sensor_id, s.nombre AS sensor, s.modelo, s.variante, s.serie_etiqueta,
       l.periodo_ms, l.n_muestras, l.o2_prom, l.o2_min, l.o2_max, l.mv_prom, l.calidad,
       l.calibracion_id, c.tipo AS calibracion_tipo, c.ts_ms AS calibracion_ms,
       c.gas_pct, c.gas_certificado, c.actor AS calibracion_actor,
       a.boot_id, a.version_sw, a.version_config, a.causa AS causa_arranque,
       q.estado AS envio_estado, q.enviado_ms, q.confirmado_ms
  FROM lectura l
  JOIN sensor   s ON s.id = l.sensor_id
  JOIN arranque a ON a.id = l.arranque_id
  LEFT JOIN calibracion c ON c.id = l.calibracion_id
  LEFT JOIN cola_envio  q ON q.tabla = 'lectura' AND q.registro_id = l.id AND q.rev = 1;

-- Cantidad de registros por tabla (estado de la base interna). COUNT(*) recorre
-- la tabla: consultar bajo demanda o con poca frecuencia, no en cada ciclo.
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
    UNION ALL SELECT 'cola_envio',          COUNT(*) FROM cola_envio;

-- -----------------------------------------------------------------------------
-- Disparadores especificos (no repetitivos)
-- -----------------------------------------------------------------------------

-- Una alarma solo puede usar codigos del catalogo marcados como alarma.
CREATE TRIGGER tr_alarma_codigo_valido
BEFORE INSERT ON alarma
WHEN NOT EXISTS (SELECT 1 FROM catalogo_evento
                  WHERE codigo = NEW.codigo AND es_alarma = 1)
BEGIN
    SELECT RAISE(ABORT, 'alarma: el codigo no existe en catalogo_evento como alarma');
END;

-- Al registrar una calibracion vigente, la anterior deja de serlo. Se hace en
-- la misma transaccion para respetar el indice unico ux_calibracion_vigente.
CREATE TRIGGER tr_calibracion_unica_vigente
BEFORE INSERT ON calibracion
WHEN NEW.vigente = 1
BEGIN
    UPDATE calibracion SET vigente = 0
     WHERE sensor_id = NEW.sensor_id AND vigente = 1;
END;

-- =============================================================================
-- DISPARADORES GENERADOS (sincronizacion y proteccion de borrado)
-- Se repiten con la misma plantilla para cada tabla sincronizable.
-- =============================================================================

-- Tablas inmutables despues de creadas: solo se encolan al insertar.

-- ---- lectura ----
CREATE TRIGGER tr_lectura_encolar_insert
AFTER INSERT ON lectura
BEGIN
    INSERT INTO cola_envio (tabla, registro_id, rev, creado_ms)
    VALUES ('lectura', NEW.id, 1, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

CREATE TRIGGER tr_lectura_proteger_borrado
BEFORE DELETE ON lectura
WHEN NOT EXISTS (SELECT 1 FROM cola_envio
                  WHERE tabla = 'lectura' AND registro_id = OLD.id)
  OR EXISTS (SELECT 1 FROM cola_envio
              WHERE tabla = 'lectura' AND registro_id = OLD.id
                AND estado <> 'confirmado')
BEGIN
    SELECT RAISE(ABORT, 'lectura: no se puede borrar un registro sin confirmacion de la plataforma');
END;

CREATE TRIGGER tr_lectura_limpiar_cola
AFTER DELETE ON lectura
BEGIN
    DELETE FROM cola_envio WHERE tabla = 'lectura' AND registro_id = OLD.id;
END;

-- ---- medicion_periferico ----
CREATE TRIGGER tr_medicion_periferico_encolar_insert
AFTER INSERT ON medicion_periferico
BEGIN
    INSERT INTO cola_envio (tabla, registro_id, rev, creado_ms)
    VALUES ('medicion_periferico', NEW.id, 1, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

CREATE TRIGGER tr_medicion_periferico_proteger_borrado
BEFORE DELETE ON medicion_periferico
WHEN NOT EXISTS (SELECT 1 FROM cola_envio
                  WHERE tabla = 'medicion_periferico' AND registro_id = OLD.id)
  OR EXISTS (SELECT 1 FROM cola_envio
              WHERE tabla = 'medicion_periferico' AND registro_id = OLD.id
                AND estado <> 'confirmado')
BEGIN
    SELECT RAISE(ABORT, 'medicion_periferico: no se puede borrar un registro sin confirmacion de la plataforma');
END;

CREATE TRIGGER tr_medicion_periferico_limpiar_cola
AFTER DELETE ON medicion_periferico
BEGIN
    DELETE FROM cola_envio WHERE tabla = 'medicion_periferico' AND registro_id = OLD.id;
END;

-- ---- salud ----
CREATE TRIGGER tr_salud_encolar_insert
AFTER INSERT ON salud
BEGIN
    INSERT INTO cola_envio (tabla, registro_id, rev, creado_ms)
    VALUES ('salud', NEW.id, 1, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

CREATE TRIGGER tr_salud_proteger_borrado
BEFORE DELETE ON salud
WHEN NOT EXISTS (SELECT 1 FROM cola_envio
                  WHERE tabla = 'salud' AND registro_id = OLD.id)
  OR EXISTS (SELECT 1 FROM cola_envio
              WHERE tabla = 'salud' AND registro_id = OLD.id
                AND estado <> 'confirmado')
BEGIN
    SELECT RAISE(ABORT, 'salud: no se puede borrar un registro sin confirmacion de la plataforma');
END;

CREATE TRIGGER tr_salud_limpiar_cola
AFTER DELETE ON salud
BEGIN
    DELETE FROM cola_envio WHERE tabla = 'salud' AND registro_id = OLD.id;
END;

-- ---- config_historial ----
CREATE TRIGGER tr_config_historial_encolar_insert
AFTER INSERT ON config_historial
BEGIN
    INSERT INTO cola_envio (tabla, registro_id, rev, creado_ms)
    VALUES ('config_historial', NEW.id, 1, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

CREATE TRIGGER tr_config_historial_proteger_borrado
BEFORE DELETE ON config_historial
WHEN NOT EXISTS (SELECT 1 FROM cola_envio
                  WHERE tabla = 'config_historial' AND registro_id = OLD.id)
  OR EXISTS (SELECT 1 FROM cola_envio
              WHERE tabla = 'config_historial' AND registro_id = OLD.id
                AND estado <> 'confirmado')
BEGIN
    SELECT RAISE(ABORT, 'config_historial: no se puede borrar un registro sin confirmacion de la plataforma');
END;

CREATE TRIGGER tr_config_historial_limpiar_cola
AFTER DELETE ON config_historial
BEGIN
    DELETE FROM cola_envio WHERE tabla = 'config_historial' AND registro_id = OLD.id;
END;

-- Tablas con revisiones: ademas encolan cada modificacion.

-- ---- alarma ----
CREATE TRIGGER tr_alarma_encolar_insert
AFTER INSERT ON alarma
BEGIN
    INSERT INTO cola_envio (tabla, registro_id, rev, creado_ms)
    VALUES ('alarma', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

CREATE TRIGGER tr_alarma_proteger_borrado
BEFORE DELETE ON alarma
WHEN NOT EXISTS (SELECT 1 FROM cola_envio
                  WHERE tabla = 'alarma' AND registro_id = OLD.id)
  OR EXISTS (SELECT 1 FROM cola_envio
              WHERE tabla = 'alarma' AND registro_id = OLD.id
                AND estado <> 'confirmado')
BEGIN
    SELECT RAISE(ABORT, 'alarma: no se puede borrar un registro sin confirmacion de la plataforma');
END;

CREATE TRIGGER tr_alarma_limpiar_cola
AFTER DELETE ON alarma
BEGIN
    DELETE FROM cola_envio WHERE tabla = 'alarma' AND registro_id = OLD.id;
END;

-- Toda modificacion aumenta rev (si el codigo no lo hizo) y encola la revision.
CREATE TRIGGER tr_alarma_rev_auto
AFTER UPDATE ON alarma
WHEN NEW.rev = OLD.rev
BEGIN
    UPDATE alarma SET rev = OLD.rev + 1 WHERE id = NEW.id;
END;

CREATE TRIGGER tr_alarma_encolar_rev
AFTER UPDATE OF rev ON alarma
WHEN NEW.rev <> OLD.rev
BEGIN
    INSERT INTO cola_envio (tabla, registro_id, rev, creado_ms)
    VALUES ('alarma', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

-- ---- evento ----
CREATE TRIGGER tr_evento_encolar_insert
AFTER INSERT ON evento
BEGIN
    INSERT INTO cola_envio (tabla, registro_id, rev, creado_ms)
    VALUES ('evento', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

CREATE TRIGGER tr_evento_proteger_borrado
BEFORE DELETE ON evento
WHEN NOT EXISTS (SELECT 1 FROM cola_envio
                  WHERE tabla = 'evento' AND registro_id = OLD.id)
  OR EXISTS (SELECT 1 FROM cola_envio
              WHERE tabla = 'evento' AND registro_id = OLD.id
                AND estado <> 'confirmado')
BEGIN
    SELECT RAISE(ABORT, 'evento: no se puede borrar un registro sin confirmacion de la plataforma');
END;

CREATE TRIGGER tr_evento_limpiar_cola
AFTER DELETE ON evento
BEGIN
    DELETE FROM cola_envio WHERE tabla = 'evento' AND registro_id = OLD.id;
END;

-- Toda modificacion aumenta rev (si el codigo no lo hizo) y encola la revision.
CREATE TRIGGER tr_evento_rev_auto
AFTER UPDATE ON evento
WHEN NEW.rev = OLD.rev
BEGIN
    UPDATE evento SET rev = OLD.rev + 1 WHERE id = NEW.id;
END;

CREATE TRIGGER tr_evento_encolar_rev
AFTER UPDATE OF rev ON evento
WHEN NEW.rev <> OLD.rev
BEGIN
    INSERT INTO cola_envio (tabla, registro_id, rev, creado_ms)
    VALUES ('evento', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

-- ---- comando ----
CREATE TRIGGER tr_comando_encolar_insert
AFTER INSERT ON comando
BEGIN
    INSERT INTO cola_envio (tabla, registro_id, rev, creado_ms)
    VALUES ('comando', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

CREATE TRIGGER tr_comando_proteger_borrado
BEFORE DELETE ON comando
WHEN NOT EXISTS (SELECT 1 FROM cola_envio
                  WHERE tabla = 'comando' AND registro_id = OLD.id)
  OR EXISTS (SELECT 1 FROM cola_envio
              WHERE tabla = 'comando' AND registro_id = OLD.id
                AND estado <> 'confirmado')
BEGIN
    SELECT RAISE(ABORT, 'comando: no se puede borrar un registro sin confirmacion de la plataforma');
END;

CREATE TRIGGER tr_comando_limpiar_cola
AFTER DELETE ON comando
BEGIN
    DELETE FROM cola_envio WHERE tabla = 'comando' AND registro_id = OLD.id;
END;

-- Toda modificacion aumenta rev (si el codigo no lo hizo) y encola la revision.
CREATE TRIGGER tr_comando_rev_auto
AFTER UPDATE ON comando
WHEN NEW.rev = OLD.rev
BEGIN
    UPDATE comando SET rev = OLD.rev + 1 WHERE id = NEW.id;
END;

CREATE TRIGGER tr_comando_encolar_rev
AFTER UPDATE OF rev ON comando
WHEN NEW.rev <> OLD.rev
BEGIN
    INSERT INTO cola_envio (tabla, registro_id, rev, creado_ms)
    VALUES ('comando', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

-- ---- calibracion ----
CREATE TRIGGER tr_calibracion_encolar_insert
AFTER INSERT ON calibracion
BEGIN
    INSERT INTO cola_envio (tabla, registro_id, rev, creado_ms)
    VALUES ('calibracion', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

CREATE TRIGGER tr_calibracion_proteger_borrado
BEFORE DELETE ON calibracion
WHEN NOT EXISTS (SELECT 1 FROM cola_envio
                  WHERE tabla = 'calibracion' AND registro_id = OLD.id)
  OR EXISTS (SELECT 1 FROM cola_envio
              WHERE tabla = 'calibracion' AND registro_id = OLD.id
                AND estado <> 'confirmado')
BEGIN
    SELECT RAISE(ABORT, 'calibracion: no se puede borrar un registro sin confirmacion de la plataforma');
END;

CREATE TRIGGER tr_calibracion_limpiar_cola
AFTER DELETE ON calibracion
BEGIN
    DELETE FROM cola_envio WHERE tabla = 'calibracion' AND registro_id = OLD.id;
END;

-- Toda modificacion aumenta rev (si el codigo no lo hizo) y encola la revision.
CREATE TRIGGER tr_calibracion_rev_auto
AFTER UPDATE ON calibracion
WHEN NEW.rev = OLD.rev
BEGIN
    UPDATE calibracion SET rev = OLD.rev + 1 WHERE id = NEW.id;
END;

CREATE TRIGGER tr_calibracion_encolar_rev
AFTER UPDATE OF rev ON calibracion
WHEN NEW.rev <> OLD.rev
BEGIN
    INSERT INTO cola_envio (tabla, registro_id, rev, creado_ms)
    VALUES ('calibracion', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

-- ---- arranque ----
CREATE TRIGGER tr_arranque_encolar_insert
AFTER INSERT ON arranque
BEGIN
    INSERT INTO cola_envio (tabla, registro_id, rev, creado_ms)
    VALUES ('arranque', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;

CREATE TRIGGER tr_arranque_proteger_borrado
BEFORE DELETE ON arranque
WHEN NOT EXISTS (SELECT 1 FROM cola_envio
                  WHERE tabla = 'arranque' AND registro_id = OLD.id)
  OR EXISTS (SELECT 1 FROM cola_envio
              WHERE tabla = 'arranque' AND registro_id = OLD.id
                AND estado <> 'confirmado')
BEGIN
    SELECT RAISE(ABORT, 'arranque: no se puede borrar un registro sin confirmacion de la plataforma');
END;

CREATE TRIGGER tr_arranque_limpiar_cola
AFTER DELETE ON arranque
BEGIN
    DELETE FROM cola_envio WHERE tabla = 'arranque' AND registro_id = OLD.id;
END;

-- Toda modificacion aumenta rev (si el codigo no lo hizo) y encola la revision.
CREATE TRIGGER tr_arranque_rev_auto
AFTER UPDATE ON arranque
WHEN NEW.rev = OLD.rev
BEGIN
    UPDATE arranque SET rev = OLD.rev + 1 WHERE id = NEW.id;
END;

CREATE TRIGGER tr_arranque_encolar_rev
AFTER UPDATE OF rev ON arranque
WHEN NEW.rev <> OLD.rev
BEGIN
    INSERT INTO cola_envio (tabla, registro_id, rev, creado_ms)
    VALUES ('arranque', NEW.id, NEW.rev, CAST(strftime('%s', 'now') AS INTEGER) * 1000);
END;
