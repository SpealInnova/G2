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
- Valores por defecto de la configuración definidos por el usuario (D-027).
- Comparación con el multímetro (1.660 V): diferencia de −0.04 a −1.34 mV con el PGA
  en derivación (D-025). Limitada por la tolerancia de la referencia interna y del
  multímetro.
- Ahorro de energía del WiFi desactivado en la Pi (D-026) y agregado al script de
  aprovisionamiento.
- Herramientas `capturar_adc.py` y `analizar_ruido.py`; el ruido de la fuente de prueba
  es lento (< 0.5 Hz) y no se puede filtrar sin quitar señal. Método para fijar el
  corte del filtro registrado en D-025.
- Se construyó la base de datos (D-028): catálogo de 23 claves de configuración, capa de
  datos `Almacen`, relojes y herramienta `g2ctl`. 132 pruebas (PC y Pi). Base real creada en
  la Pi (`~/g2/datos/g2.db`, esquema 4) con la configuración por defecto y los dos sensores
  dados de alta; la cadena de auditoría verifica OK. Pendiente de subir a GitHub.
- Diagrama entidad-relación de la base de datos: `DIAGRAMA_ER.md`, generado desde el esquema real
  con `tools/generar_diagrama_er.py` (sintaxis Mermaid validada con el analizador de Mermaid).
  Dos diagramas: el modelo con sus claves foráneas y los mecanismos transversales (cola de
  envío y cadena de auditoría). Se regenera después de cada migración.
- Prueba A/B del ruido de la fuente de prueba (divisor desde el pin de 3.3 V de la Pi): el
  ruido es 73 veces el piso del ADC y sube con la carga de la Pi; se agregó
  `tools/banco/comparar_capturas.py`. Detalle en D-025.

## 2026-10-09

- La Pi dejó de responder en su dirección y, tras desenchufarla y volver a enchufarla,
  reapareció con otra IP asignada por DHCP. SSH avisó que la llave del servidor había
  cambiado para esa IP; se comprobó que la huella era idéntica a la de la Pi de G2, así que
  era el mismo equipo (la llave guardada para esa IP era de otro equipo). El ahorro de
  energía del WiFi siguió desactivado tras el reinicio. Se recomienda reservar la IP en el
  router o usar el nombre `raspberry.local` (avahi).
- Prueba A/B con pila de 10 V y divisor de 4 resistencias (≈ 1.99 V): el ruido sobre 0.1 Hz
  queda al nivel del piso del ADC y no cambia con la carga de la Pi; el ruido de la prueba
  anterior venía del riel de 3.3 V. Detalle en D-025.
- Multímetro 1.988 V frente al ADC (1990.2 mV y luego 1985.8 mV): no fueron simultáneas y la
  fuente derivó 4.4 mV; no se puede calcular el error absoluto. Se pidió medir al mismo
  tiempo y conocer las resistencias (carga del divisor). Detalle en D-025.
- Comparación simultánea con el multímetro (1.987 V): el ADC lee 1985.24 mV (−0.09 %), igual
  diferencia proporcional que con la fuente de 1.660 V (−0.08 %). Compatible con el error de
  ganancia de la referencia interna o con la tolerancia del multímetro (D-025).
- Se ordenó la lista de pendientes de la memoria técnica (se quitaron los ya resueltos) y se
  agregó la sección "Tareas pendientes de hardware y operación".
- Propuesta de trabajo con la pantalla Nextion (D-029), con preguntas abiertas.
- Respuestas del usuario sobre la Nextion (D-029): construirá el `.HMI` con ayuda; PIN por
  defecto y asignable desde la plataforma; se conservan los reportes a USB; solo español.
- README como página principal con novedades por fecha, generadas desde `git log` (D-030).
- Modelo de la pantalla en el editor de Nextion: NX8048P050_011 (por confirmar con la etiqueta o
  con `tools/banco/sonda_nextion.py`; sin respuesta porque aún no está conectada) (D-029).
- Ajustes de pantalla en el editor de Nextion: horizontal 0° y codificación iso-8859-1; reglas
  de texto derivadas (D-029).
- Proyecto `nextion/g2.HMI` creado por el usuario en el repositorio. Se escribió la etapa 1 de la
  especificación del HMI (convenciones, protocolo con códigos propios y página principal) en
  `nextion/ESPECIFICACION_HMI.md` (D-029).
- Fondo de la pantalla: imagen de IA ajustada a la cuadrícula con `tools/ajustar_fondo_nextion.py`
  (`nextion/fondos/principal.png`); especificación del HMI actualizada y con anchos corregidos.
- Logo de SPEAL integrado en la barra del fondo (110x44 px, compuesto sobre el color de la barra porque la
  pantalla no maneja transparencia); el titulo y los indicadores de la barra se desplazaron. Fuentes
  generadas en nextion/fonts (arial24, arial32n, arial40n, arial100n, arial24n).
- Botón Acusar (D-031): silencia solo el sonido de la pantalla, los relevos no se desactivan, el
  sonido vuelve a los 2 minutos si la alarma persiste. Nueva clave `alarma.acuse_silencio_s` (120 s).
- Pitido de pulsación de botones: sonido `nextion/sonidos/pulsacion.wav` (generado con
  `tools/generar_sonido_pulsacion.py`) y su uso en la especificación del HMI (canal 1 para toques).
- Corrección: la variable de volumen de la Nextion es `volume` (no `vol`); verificado en el juego
  de instrucciones oficial y corregida en la especificación del HMI.
- Git LFS activado para `*.HMI` y `*.tft` (versionado de los programas de la pantalla, D-029).
- Herramienta tools/publicar_pantalla.py (hito de la pantalla): copia el .tft a nextion/build/ con su
  version y registra las huellas SHA-256 en nextion/MANIFIESTO.md; una version publicada es inmutable.
  Especificacion: largo maximo de los textos (txt_maxl) y estado inicial de est_*. 146 pruebas pasan.
- Alarmas por sensor (D-032): cada sensor con su alarma, aviso visual (recuadro rojo, parpadea hasta
  acusar) y sonido; Acusar acusa todas; los relevos no dependen del acuse.
- Decisiones del usuario (D-032): Acusar acusa ambos sensores y el sonido; un relevo por sensor
  (relevo 1 = sensor 1, relevo 2 = sensor 2); la falla del equipo ya no tiene relevo.
- Relevos (D-033): placa RPi Relay Board de 3 relevos, uno por alarma (oxígeno bajo y alto, de
  cualquier sensor), energizados en normal; riesgo del estado por omisión de los pines y capas de
  defensa por verificar en la placa real. Sustituye "un relevo por sensor" de D-032.
- Especificación del HMI: páginas teclado (PP 06) y alarmas (PP 01), fondo de páginas interiores
  (`tools/generar_fondo_interno.py`) y sonido de alarma (`tools/generar_sonido_alarma.py`).
- Diagnóstico (D-033): reinicio de la Pi sin disparar alarmas; opciones A (estricta), B (sin hardware)
  y C (relevo 3 "fuera de servicio" con retardo de ~2 min); pendiente de decisión y de medir la placa.
- Herramienta de banco tools/banco/pantalla.py: envia ordenes a la Nextion (p. ej. page teclado) y muestra los
  toques decodificados con los codigos de la especificacion; 8 pruebas del decodificador.
- g2-core primera versión (D-034): `src/g2/nucleo/` (señal, motor de alarmas por sensor, fuentes, salidas
  emuladas y ciclo), `python3 -m g2.nucleo`. 73 pruebas nuevas (209 en total, también en la Pi). Corrida
  de 24 s con el ADC real en una base de prueba aparte; las alarmas se abrieron como se esperaba.
- Divisor de voltaje en las entradas AIN0-AIN1 y AIN2-AIN3 (el usuario las nombra IN1-IN2 e IN3-IN4): g2-core lee
  ambos sensores en 103.0 % (~1.03 V) con el ADC real; se abre la alarma alta de los dos y solo el relevo alto.
- Navegación de la pantalla verificada por el usuario (principal y alarmas con `page`). Multímetro 1.030 V = ADC
  1029.99 mV. ZeroTier instalado en la Pi desde el repositorio oficial con la llave verificada y unido a la red
  privada del usuario, pendiente de autorizar el nodo (D-035). SSH por contraseña se conserva como canal de soporte.
- ZeroTier verificado: el nodo quedó autorizado (IP asignada) y el acceso por SSH funciona con la misma huella.
- Pantalla conectada a la Pi: NX8048P050_011R, firmware 293, 9600 baudios; la sonda ahora tolera el byte nulo
  suelto de su respuesta. Cambio de página, lectura de `proto` y escritura de textos verificados con la pantalla real.
- g2-core como servicio de systemd con watchdog por progreso (D-036): probado congelando el proceso a propósito.
- g2-ui primera etapa y comunicación por archivos en /run/g2 (D-037): página principal, alarmas (lectura), Acusar,
  parpadeo y sonido; 272 pruebas, también en la Pi; ambos servicios instalados y habilitados en la Pi.
- Fotos de la pantalla real (usuario): la principal muestra los datos en vivo y la de alarmas los ajustes y el
  historial; toques de Alarmas, Volver y Acusar verificados en el registro de g2-ui. Detectado: la pantalla trae
  navegación temporal y carga cada página dos veces (con 3 avisos de atributo inválido); hay que quitarla del HMI.
- Corregido el exceso de revisiones del valor extremo de las alarmas (191 en una sola); ahora se escribe solo si
  cambia 0.5 % y al cerrar o apagar. 276 pruebas, también en la Pi.
- PIN de la pantalla (D-038): migración 005 (tabla `pin_acceso`, no sincronizada), módulo `g2.seguridad.pin`, comandos
  `g2ctl pin-fijar` y `pin-estado`, teclado con PIN en `g2-ui` y órdenes `pin_resultado` y `config_fijar` en el núcleo.
  Reglas confirmadas por el usuario: vigencia 5 min, 3 fallos y bloqueo de 60 s. PIN de fábrica aprovisionado en la Pi
  por SSH (no está en el repositorio). 317 pruebas, también en la Pi.
- Decisiones sobre las páginas restantes (WiFi escribiendo nombre y contraseña, calibración con ambos métodos, CSV con
  huellas SHA-256, PIN en todo lo delicado) y plan por etapas (D-039). Etapa 1 del lado de la Pi: salud de la Pi,
  órdenes sensor_habilitar, sistema_accion y auditoria_resultado, páginas confirmar, sistema y config, regla de polkit.
- Prueba real de reiniciar servicios por la vía de la pantalla: reveló que el comando moría con el núcleo; corregido
  con --no-block y el núcleo al final. El usuario probó el PIN en la pantalla real (fallo, acierto y cambios de ajustes).
  374 pruebas, también en la Pi.
- Configuración de la red (D-040): gestor con reversión automática sobre NetworkManager, servicio de red en un hilo,
  órdenes red_configurar y red_buscar, la contraseña nunca se registra, páginas `red` y `texto` (teclado completo por capas)
  en la interfaz y su especificación del HMI, polkit ampliado y detección automática de la velocidad del puerto serie.
  461 pruebas, también en la Pi. Comprobados en la Pi: estado, búsqueda y permisos de NetworkManager.
- Hallazgo grave (D-041): la pantalla se reiniciaba cada 3 s al sonar la alarma con `volume=70` (el altavoz consume más de lo
  que aguanta su fuente). Aislado con la herramienta de banco (70 reinicia; 10 a 60 no). La Pi ahora fija el volumen (50) al
  arrancar y en cada encendido de la pantalla, y una protección baja el volumen o calla el sonido si reinicia. 473 pruebas.
- D-042: la contraseña de la red ahora se ve al escribirla (botón Ocultar/Ver); especificación: `play 1,0,0` obligatorio en las 40 teclas
  y en todos los botones de `texto`; documentados los requisitos para que la clave viaje segura desde la plataforma (TLS verificado,
  órdenes firmadas con caducidad, autorización, sin rastro en la plataforma y cifrado de extremo a extremo). 473 pruebas.
- D-043: gráfica en tiempo de las dos señales (Waveform de 4 canales): se abre sola tras 10 s sin tocar `principal` y un toque la cierra;
  vuelve a `principal` si salta una alarma sin acusar. Toda la lógica está en la Pi (historial, eje automático, `addt`/`add`, `sendxy=1`).
  Especificación de la página en la sección 15 del HMI. 523 pruebas. Falta construir la página y probarla en la pantalla real.
- D-044: reportes en PDF cifrado (contraseña = nombre del equipo) a memoria USB (debe llamarse como el equipo): filtro por días completos (máx. 7),
  botón «imprimir hoy», filas con alerta de oxígeno en rojo y negrita con el umbral de ese momento, respeta el intervalo de guardado, resumen
  con estado de la cadena de auditoría y huella SHA-256 en archivo y evento. Corre en un proceso aparte (la medición no se entera). Página
  `reportes` (sección 16 del HMI). 618 pruebas. Hallazgo: la tarjeta SD salía como memoria USB (corregido). Falta construir la página, instalar con
  sudo (polkit y librerías) y probar con una USB exFAT real.
- Sonido «Calibrando» (voz del usuario): convertido a WAV mono 16 bits 16 kHz (0,61 s, pico 0,85) con la nueva herramienta tools/convertir_sonido_voz.py;
  será el audio id 2 de la pantalla (play 0,2,0). Especificado en la sección 6 del HMI; falta agregarlo al .HMI cuando se construya la calibración.
- D-045: la pantalla queda bloqueada mientras se genera un reporte (se descartan los toques en la Pi y se ordena `tsw 255,0` a la pantalla, repetido
  en cada carga de página); se quitó el botón Cancelar; se libera sola si el núcleo no responde. Misma técnica para la calibración. 627 pruebas.
  Falta comprobar en la pantalla real que `tsw 255,0` desactiva el toque.
- USB real (NTFS): lsblk con PATH primero daba lista plana y no reconocía ninguna USB (corregido: NAME primero, 632 pruebas). El reporte llega hasta cifrar y falla
  al copiar con «Read-only file system»: la unidad g2-core y la regla de polkit instaladas son anteriores a los cambios; falta correr instalar_servicios.sh con sudo.
- Reporte: zona horaria de Colombia (America/Bogota, por defecto y fijada en la Pi); se quitó la zona del encabezado y la sección «Cambios de configuración»
  del final. 631 pruebas.
- Reporte PDF: sin «Software» ni modelo/serie de sensores, texto copiable (permite copiar e imprimir, no editar) y logo de SPEAL pequeño en la primera
  página. Hecho en cuatro pasos comprobados uno a uno; 633 pruebas; probado con datos reales en la Pi.
- Reporte PDF: el logo es el mismo de la pantalla Nextion (nextion/imagenes/logo.png, óvalo amarillo), no SPEAL_Air.
- Reporte PDF: el logo pasa al extremo derecho de la cabecera de la primera página y el nombre del equipo se corre a su izquierda.
- Umbrales de alarma restaurados en la Pi a los de fábrica (20 %, 92 %, 10 s, acuse 120 s; estaban 15 %, 95 %, 15 s, 500 s). Con el oxígeno real en ~93,7 % la
  alarma de ALTO ahora se activa. Hallazgo: `muestreo.intervalo_guardado_s` sigue en 300 s (fijado desde la pantalla el 27/10), no se tocó.
- Velocidad de la pantalla: sigue a 9600 baudios; falta `bauds=115200` en el HMI (la detección automática cubre ambos casos).
- Reporte PDF: el anexo suma la sección «Estado de los sensores» (apagado, encendido, sin señal) y la primera página un renglón de resumen; sin migración. 636 pruebas;
  comprobado con los datos reales del 27/10 en la Pi.
- g2-uplink (D-046), etapa 1: servicio que envía a la plataforma por HTTPS (lotes durables con confirmación por registro + foto en vivo cada 15 s), con esperas
  crecientes, secreto por equipo en un archivo 0600 y apagado por omisión (`plataforma.activa = 0`; falta `equipo.id` y el secreto). Solo lee la base: pide a g2-core
  anotar los resultados con la orden `cola_resultado` (no es un comando). Migración 009 (eventos PLAT_*), `g2ctl plataforma-credencial` y `plataforma-estado`,
  `systemd/g2-uplink.service`, regla de polkit e instalador actualizados. Contrato para la plataforma en CONTRATO_PLATAFORMA.md y plataforma simulada para probar.
  704 pruebas (también en la Pi). Con una copia de la base real: 20.927 pendientes enviados y confirmados en 46 s. Hallazgo: auditoria_cadena se identifica por `seq`.
  Falta: que la plataforma implemente el contrato, instalar con sudo y activar. No se tocó el repositorio de la plataforma.
- g2-uplink vigila a g2-core (D-047): si el núcleo no responde 120 s seguidos pide a systemd reiniciarlo (máx. 3 por hora, 300 s entre intentos) y, al arrancar, el núcleo
  registra la razón `SVC_BLOQUEO_DETECTADO` con un evento. Funciona aunque el envío esté desactivado. 749 pruebas (también en la Pi); en la Pi se probó el reinicio sin sudo
  y el registro. No se probó con un núcleo congelado real (el watchdog de systemd actúa antes).
- Cola de envío: se descartaron los 21.028 registros pendientes (todos de prueba) con la orden nueva `g2ctl cola-descartar --motivo ... [--confirmar]`. No borra nada (D-010):
  las entradas pasan a `rechazado` con el motivo, los registros siguen en el equipo y no se depuran; deja un evento `NET_ENVIO_RECHAZADO`. Antes se sacó una copia de la base
  (`/home/pi/g2/respaldos/g2_antes_de_descartar_cola_20261029_163042.db`). Cadena de auditoría OK. Desde ahora la plataforma solo recibirá lo que el equipo registre después.
- Calibración de cero en aire (D-048): `calibrar_aire` (un sensor a la vez, con el otro vigilando) mide una ventana estable de 30 s (variación ≤ 0,3 %), guarda el cero
  vigente si la corrección no pasa de ±3 % y, si no, deja un fallo sin aplicarlo; tope de 5 min. El sensor calibrado sale de la vigilancia y sus muestras quedan marcadas
  (`en_spoc`). Migración 010 (`CAL_INICIADA`, `CAL_CANCELADA`), página `calibracion` en g2-ui (PIN, confirmación, bloqueo total como reportes, voz «Calibrando»),
  sección 17 de la especificación del HMI y `g2ctl calibrar-aire / calibrar-cancelar`. 797 pruebas (también en la Pi), desplegado. Falta construir la página en el `.HMI` y probar con
  un sensor y una pantalla reales.
- Calibración por puntos con gas patrón (D-049), a pedido del usuario (D-048 solo calibraba el cero en aire): punto bajo (0,0 % o aire) y punto alto (98,0 %, 99,8 % u otro valor tecleado), cada
  uno por separado; la recta `ganancia × mV/10 + cero` se compone con el último punto de cada lado. Límites: ganancia 0,90 a 1,10, cero ±3 %, puntos a 50 puntos o más, estable 0,3 % en 30 s,
  tope 5 min. Migración 011 (ganancia y puntos en `calibracion`, tipo `puntos`, huella de auditoría ampliada; probada con una copia de la base real en la Pi), orden `calibrar_punto`,
  `g2ctl calibrar-punto`, página `calibracion` rehecha (sección 17 del HMI), reporte PDF y contrato con la plataforma actualizados. 828 pruebas. **Sin desplegar** en la Pi mientras el usuario
  prueba la pantalla con la configuración anterior. Aparte: reintento al reemplazar el archivo de estado en Windows y una prueba de reportes que dependía de la fecha.
- D-049 desplegada en la Pi (copia previa de la base, esquema 11, auditoría correcta). Causa de que `v_gas` no abriera el teclado: la Pi aún traía la tabla de controles de la página
  `calibracion` de D-048 (solo `01` a `03`) y el `.HMI` nuevo envía `01` a `07`. La migración 011 conserva como punto bajo las calibraciones de cero en aire ya hechas (S1 +0,04 %, S2 +0,10 %).
