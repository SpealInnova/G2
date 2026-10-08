# G2 — Bitácora

Registro cronológico de lo que se hace en el proyecto. Las razones de cada
decisión están en `MEMORIA_TECNICA.md`.

## 2026-10-03

- Se creó la carpeta `documentacion/` con los manuales del sensor:
  - `01117001A_1P1 Digital.pdf`: Paracube Micro, variantes digitales.
  - `Manual-Paracube-Modus_1.pdf`: Paracube Modus, variantes digitales
    (01120001A).
  - `Manual-Paracube-Modus_2.pdf`: Paracube Modus, variantes analógicas
    (01120009A).
- Se leyó el manual del Micro digital: la salida es UART TTL (19200 baudios,
  8N1, ASCII), una lectura cada 200 ms.
- Se comparó el Micro con el Modus: sin diferencias de desempeño. Cambian el
  consumo (Micro 110/150 mA, Modus 70/100 mA), el tiempo de primera lectura
  (Micro < 4 s, Modus < 8 s) y la norma de prueba citada.
- Se identificó que el sensor disponible `01117707500032` es **analógico**
  (10 mV/%O₂, conector KK), no digital. Ver D-003.
- Se leyó la calibración del manual analógico (SPOC por botón, 20.9 % de O₂).
- Decisiones tomadas: SQLite (D-001), Python (D-002), sensor analógico
  (D-003), repositorio en GitHub (D-004), bitácora y memoria con justificación
  y código comentado para auditoría (D-005).
- Se anotó el requisito de la lista de funciones y objetivos del nuevo
  analizador en `Mejoras.txt` (lista del usuario).
- Hallazgo: la carpeta G2 está dentro del repositorio git del directorio de
  usuario. No se ha ejecutado ninguna operación git. Ver D-004.
- Repositorio: se ejecutó `git init -b main` dentro de G2 (repositorio propio,
  separado del del directorio de usuario) y se agregó el remoto `origin` =
  `https://github.com/SpealInnova/G2.git`. El remoto ya tiene una rama `main`
  con un commit inicial (`README.md`), que se traerá al hacer el primer
  commit. No se ha hecho commit ni push.
- Se creó `.gitignore`: excluye los manuales del fabricante (PDF y zip,
  marcados como documento confidencial), secretos, entorno virtual de Python y
  archivos de base de datos.
- Se encontraron en `documentacion/` dos archivos nuevos
  (`Manual-Paracube-Sprint_00502001A_0.pdf` y `hummingbird.zip`), aún sin
  revisar.
- Decisiones confirmadas por el usuario sobre la base de datos: se guarda todo
  (opción B: lecturas, alarmas, eventos, arranques, comandos, calibraciones,
  configuración y salud), con la cola de envío por referencia, y retención
  por defecto, borrando solo con confirmación explícita de la plataforma.
  Hardware: Raspberry Pi 3 B, Raspberry Pi OS 64 bits (Trixie). Ver D-006 a
  D-010.
- Se escribió el esquema inicial de SQLite (`001_esquema_inicial.sql`, 15
  tablas, 4 vistas, 39 disparadores), el catálogo inicial de eventos y
  alarmas (`002_catalogo_inicial.sql`), el aplicador de migraciones
  (`migraciones.py`) y la apertura de conexiones (`base.py`).
- Se escribieron 32 pruebas (`tests/test_esquema.py`); todas pasan con Python
  3.10 y SQLite 3.39 en el equipo de desarrollo (Windows). Aún no se han
  ejecutado en la Raspberry Pi.
- No se hizo commit ni push.
- Política de salud definida por el usuario: guardar cada 30 minutos y ante
  datos alarmantes (temperatura, RAM, corriente, tensión); uso de RAM y de
  disco visibles en la plataforma. Registrada como D-011. Pendiente confirmar
  la columna `motivo` en `salud` (cambio de esquema).
- Confirmado por el usuario: arquitectura de 3 servicios (D-009) con
  vigilancia de bloqueos (D-012); columna `motivo` en `salud`; alertas de
  espacio en disco (D-013); requisito de trazabilidad y auditoría (D-014).
- Cambios en el esquema (aún sin publicar, por eso se editó la migración
  001 y no se creó una nueva): columna `salud.motivo` (código del
  catálogo) y vista `v_lectura_trazabilidad`. En el catálogo se
  reemplazaron `SYS_BAJO_VOLTAJE`, `SYS_TEMP_ALTA`, `DB_ESPACIO_BAJO` y
  `DB_ESPACIO_CRITICO` por alarmas (`ALM_RPI_TEMP_ALTA`,
  `ALM_RPI_RAM_ALTA`, `ALM_RPI_BAJO_VOLTAJE`, `ALM_DISCO_ESPACIO_BAJO`,
  `ALM_DISCO_ESPACIO_CRITICO`) y se agregaron `SYS_SALUD_PERIODICA` y los
  códigos `SVC_*` de supervisión de servicios. 39 pruebas, todas pasan.
- Decisiones del usuario: sin respaldos automáticos que liberen espacio;
  alerta temprana de llenado de disco (D-013); respaldos recurrentes en
  un repositorio independiente de la Raspberry Pi y de la nube (D-015);
  cadena de auditoría con huellas SHA-256 (D-016).
- Se implementó la cadena: migración `003_cadena_auditoria.sql` (generada
  por `tools/generar_cadena.py`), función `sha256` en `base.py`, verificador
  `auditoria.py` y `tests/test_cadena_auditoria.py`. La migración 001 se
  editó (aún sin publicar) para que `cola_envio` acepte `auditoria_cadena`.
  55 pruebas, todas pasan (Python 3.10, SQLite 3.39, Windows).
- Pendiente: no se ha hecho commit ni push; el usuario pidió esperar a
  cerrar todas las confirmaciones.
- Confirmaciones del usuario: umbrales de disco por defecto (aviso 20 % o
  2 GB, crítico 10 % o 1 GB); mínimo de operación (dejar de guardar
  lecturas sin borrar nada); respaldos generados por la plataforma en un
  Drive de la empresa (configuración posterior); el primer commit incluye
  todo, también `CONTEXTO.md` y `Mejoras.txt` (origen del proyecto).

## 2026-10-04

- Se subió el primer commit a `SpealInnova/G2` (`d991cfa`). El usuario
  `williamrubio1` quedó como colaborador del repositorio, que es público.
- Búsqueda de analizadores de oxígeno de referencia (AMI, Oxysystems,
  OxyPro, S4 Aurora, plantas PSA con monitoreo remoto). Hallazgo: el OxyPro
  de PSC usa el mismo sensor Paracube Micro.
- Decisión del usuario: esta versión es para hospitales (D-017).
- Se analizó la recuperación escalonada sin reiniciar la Raspberry Pi
  (D-018) y la viabilidad de alertas por correo o WhatsApp y de reinicio
  remoto (D-019). Pendiente confirmar el cambio de esquema de `arranque`.
- El usuario propuso resolver el registro de reinicios de servicio con una
  columna de razón en vez de reconstruir `arranque`; se acepta (D-018).
- Requisito de audio por el puerto de la Raspberry Pi (D-020).
- Se revisó la plataforma `iot-elsalvador` para las alertas por correo
  (D-021): ya tiene alertas pero no correo; el despliegue es automático con
  cada push a `main`; se anotaron observaciones de seguridad.
- Audio: se cancela el audio por la Raspberry Pi; se conserva el de la
  Nextion comandado desde la Raspberry Pi (D-020).
- Alertas por correo: confirmadas por el usuario y construidas en la rama
  local `feature/alertas-correo` de la plataforma, sin commit ni push
  (D-021). 18 pruebas pasan; falta probar con MySQL y SMTP reales.
- Se reemplazó el token real de `.env.example` por un marcador y se
  documentó el plan de seguridad por etapas (D-022).
- Hardware definido por el usuario: ADC Waveshare ADS1263 (10 canales, 32 bits),
  2 sensores analógicos, 2 relés y 1 LED de alarma, periféricos de temperatura,
  humedad, vibración, presión y humedad de línea (D-023). Se creó `HARDWARE.md`.
- Requisito de trabajar todo por SSH hacia la Raspberry Pi (D-024).
- Respuestas del usuario: relés para alarmas AC, sensor de temperatura y humedad
  junto a los sensores de oxígeno, pines de la cabecera expuestos (D-023).
- Se aplicó la migración 004 (`arranque.razon` y `arranque.so_boot_id`, D-018) y se
  refactorizó el generador de la cadena. 62 pruebas, todas pasan.

## 2026-10-05

- Se leyó la hoja de datos del ADS126x (TI). Conclusión: ganancia 1 con PGA en
  derivación; no hace falta amplificar. Registrado en D-025 y `HARDWARE.md` §3.

## 2026-10-08

- Acceso SSH a la Raspberry Pi de G2: se instaló una llave propia de este PC
  (detalles de acceso en las notas locales, no publicadas) (D-026).
- Reconocimiento de solo lectura: Pi 3 Model B Plus, Trixie con escritorio, Python
  3.13.5, SQLite 3.46.1; SPI, I²C y UART sin habilitar.
- Se cargó el código en `~/g2/dev` y las 62 pruebas pasan en la Pi.
- Aprovisionamiento de la Pi con `scripts/aprovisionar_pi.sh`: SPI, I²C y UART
  habilitados, consola serie y Bluetooth desactivados, `sqlite3` y `tmux`
  instalados; reinicio verificado. Contraseña y escritorio sin cambios, por decisión
  del usuario.
- Sonda `tools/banco/sonda_ads1263.py`: ADS1263 detectado por SPI (ID 0x23).
- Decisión del usuario: se conservan `avahi-daemon`, `rpcbind` y `nfs-blkmap`
  (se mantienen abiertos varios canales de comunicación con la Pi).
- Controlador del ADS1263 (`src/g2/hardware/`), emulador y herramienta de banco
  (`tools/banco/medir_adc.py`). 82 pruebas. Primera lectura real: el flujo funciona;
  falta la medición con el voltaje de referencia (D-025).
- Primer intento de medición con voltaje de muestra (usuario: 2.5 V en IN0): las lecturas
  fueron ruidosas e inestables (IN0 contra AINCOM ≈ 1.87 V con desviación de 118 mV; IN1
  contra AINCOM ≈ 1.93 V con 118 mV; IN0 contra IN1 ≈ 8.8 mV con 9.5 mV). Es el
  comportamiento de entradas sin referencia a tierra: la fuente no queda referida a GND.
  Medición no válida; se pidió revisar la conexión del negativo y usar ≤ 2.4 V.
- Segundo intento de medición. Con una referencia de 5 V de diagnóstico (preset
  `diagnostico_5v`, aproximada) se vio: IN0 contra COM ≈ 2.503 V (dispersión ≈ 4 mV);
  IN1 contra COM saturado en ≥ 5 V; IN0 contra IN1 ≈ −2.51 V. Conclusión: IN0 recibe
  los 2.5 V, pero IN1 está conectada a una tensión ≥ 5 V (probablemente al riel de 5 V),
  por lo que la medición diferencial IN0–IN1 se satura. Con la referencia interna, 2.5 V
  está justo en el límite del rango (±2.5 V) y también satura. Se agregó la opción
  `referencia="avdd"` al controlador (85 pruebas).
- Conexión corregida por el usuario (IN1 a GND, IN0 a ~1.6 V). Primera medición
  válida: ver D-025. El PGA activo da 15 mV de error con una entrada cerca de 0 V;
  con el PGA en derivación todas las configuraciones coinciden (1658.8 a
  1658.9 mV). Piso de ruido del ADC ≈ 6 µV; el ruido observado es de la fuente.
