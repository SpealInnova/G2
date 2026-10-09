# G2 — Memoria técnica (decisiones y justificación)

Cada decisión de diseño se registra aquí con su razón, para poder redactar
después el manual técnico del dispositivo. El cronograma de lo que se hizo y
cuándo está en `BITACORA.md`. El contexto heredado del equipo anterior
(ANZD-600226001) está en `CONTEXTO.md`.

Formato de cada decisión: contexto, decisión, justificación, alternativas
descartadas, consecuencias, fuente.

---

## D-001 — Base de datos interna: SQLite

- **Fecha:** 2026-10-03
- **Contexto:** el equipo anterior usa MySQL local (`analitech.muestras`), con
  concatenación de SQL y un servicio aparte en la Raspberry Pi.
- **Decisión:** SQLite, con consultas parametrizadas y política de retención.
- **Justificación:** no necesita servidor aparte (un proceso menos que puede
  caerse), consume menos energía y memoria, y un solo archivo facilita el
  respaldo y el diagnóstico remoto. Objetivo del proyecto: mínimo consumo y
  mínima probabilidad de falla.
- **Alternativas descartadas:** MySQL/MariaDB local (más consumo y más puntos
  de falla).
- **Consecuencias:** hay que definir con cuidado quién escribe (un solo
  proceso dueño de la base) y el modo de journal (WAL) para soportar cortes de
  energía. El esquema se acordará antes de implementarlo.

## D-002 — Lenguaje: Python

- **Fecha:** 2026-10-03
- **Decisión:** Python.
- **Justificación:** es el lenguaje de confianza y dominio del responsable, lo
  que facilita el mantenimiento y la auditoría. El equipo anterior ya está en
  Python.
- **Alternativas descartadas:** Go o Rust (binario único y menor consumo, pero
  fuera del dominio del equipo).
- **Consecuencias:** se exige disciplina para compensar lo que el lenguaje no
  impone: tipado con anotaciones, un solo dueño por recurso, manejo explícito
  de errores y pruebas automatizadas.

## D-003 — Sensor de esta versión: analógico (Hummingbird Paracube Micro 01117707)

- **Fecha:** 2026-10-03
- **Contexto:** el sensor disponible es `01117707500032`. Según el formato
  `XXXXXYYYZZZZZZZ` (manual 01117001A, pág. 28): producto 01117, variante 707,
  serie 500032. La tabla 6 del manual (pág. 30) indica para la variante 707:
  salida analógica 10 mV/%O₂, conector KK, compensación de presión ambiente.
- **Decisión:** G2 se diseña para sensores de salida analógica.
- **Hechos técnicos (fuente: manual Modus analógico 01120009A, págs. 16-25;
  el manual del Micro analógico 01117009A no está disponible, se asume
  equivalente y debe confirmarse):**
  - Pines: P1 +5 V, P2 señal mV, P3 0 V analógico, P4 GND. La señal es
    diferencial P2–P3; no unir P3 con P4. Entrada del lector > 1 MΩ.
  - 10 mV por cada 1 % de O₂ (aire 20.9 % ≈ 209–210 mV). Rango 0–100 %, con
    sobrerrango de −15 % a +200 %.
  - Se actualiza cada 200 ms ± 5 ms.
  - Consumo a 5 V: 70 mA típico y 100 mA máximo según manual del Modus; el
    manual del Micro digital indica 110 mA y 150 mA.
  - No tiene UART: no hay identidad por comando, ni calibración por comando,
    ni banderas B/C/E/S/X. El estado se ve en el LED de la placa.
- **Consecuencias para el diseño:**
  1. Se necesita un ADC externo de entrada diferencial (por ejemplo ADS1115,
     16 bits). La resolución del ADC no mejora la exactitud: el ruido es
     < 0.2 % pico a pico y el error intrínseco < ±0.2 %.
  2. **La calibración es solo de un punto (SPOC) con aire a 20.9 %.** Se hace
     con un botón físico de la placa superior del sensor; no se puede
     disparar por software. Durante un SPOC (≈ 55 s o más) la salida oscila
     entre los extremos del rango a 1 Hz y esas muestras no son medición.
  3. La calibración "desde pantalla y plataforma" se implementa como
     **corrección de cero en el equipo** (manual, sección 5.2): se mide aire
     conocido, se guarda la diferencia y se resta de las lecturas siguientes,
     registrada con auditoría. El span queda como lo dejó la fábrica.
  4. La identidad del sensor no se puede leer; se asigna por canal del ADC y
     se registra el número de serie de la etiqueta en la configuración.
  5. Hay que detectar y marcar como inválidas las muestras tomadas durante un
     SPOC (oscilación a 1 Hz entre extremos).
  6. La compensación de presión viene configurada de fábrica y no es
     intercambiable entre variantes (Caution 6, manual 01120009A).

## D-004 — Control de versiones: GitHub

- **Fecha:** 2026-10-03
- **Decisión:** el código se versiona en `https://github.com/SpealInnova/G2.git`.
- **Realizado (2026-10-03):** la carpeta G2 estaba dentro del repositorio git
  del directorio de usuario (`C:\Users\anapa`, sin remoto). Se creó un
  repositorio propio en G2 (`git init -b main`) y se conectó el remoto
  `origin`, para no mezclar historiales ni subir otros proyectos. El remoto ya
  tiene un commit inicial (`README.md`). Aún no hay commit ni push.
- **Justificación de `.gitignore`:** los manuales del fabricante están
  marcados como documento confidencial y con derechos reservados, por eso no
  se suben (PDF y zip de `documentacion/`).

## D-005 — Documentación y estándar de código

- **Fecha:** 2026-10-03
- **Decisión:**
  - Se mantiene bitácora (`BITACORA.md`) y memoria técnica (este archivo) con
    la justificación de cada implementación, como base del manual técnico.
  - El código se comenta de forma que sea fácil de auditar: cada módulo
    explica su propósito y sus responsabilidades, cada función explica qué
    hace, qué recibe, qué devuelve y qué errores puede producir, y las
    decisiones no evidentes se justifican junto a la línea (con referencia a
    la decisión D-xxx).
- **Pendiente de confirmar:** idioma de los comentarios y de los nombres.
  Propuesta: comentarios y documentación en español, nombres de código en
  español o inglés de forma consistente.

## D-006 — Plataforma de hardware y sistema operativo

- **Fecha:** 2026-10-03
- **Decisión:** Raspberry Pi 3 B con Raspberry Pi OS de 64 bits, basado en
  Debian Trixie. (Verificado el 2026-10-08: el equipo de desarrollo es una
  Raspberry Pi 3 Model B Plus Rev 1.4; ver D-026.)
- **Implicaciones para el diseño:**
  - 1 GB de RAM compartida: se limita la memoria por servicio y se evitan
    bibliotecas pesadas.
  - Sin reloj de tiempo real propio: se necesita RTC externo (ver
    `Mejoras.txt` y D-pendiente de reloj).
  - WiFi integrado de 2.4 GHz; red gestionada con NetworkManager (`nmcli`).
  - Python de Trixie en entorno virtual (el sistema protege los paquetes del
    sistema), y `libgpiod` en lugar de `RPi.GPIO`.
  - Perro guardián de hardware del propio SoC disponible para systemd.
  - Consumo en reposo mayor que el de modelos Zero; el ahorro se logra
    apagando lo no usado y con muestreo por eventos. Se medirá con INA219.

---

## D-007 — Qué se guarda en la base y con qué granularidad

- **Fecha:** 2026-10-03
- **Decisión:** la base interna guarda todo lo que el equipo mide o hace, no
  solo lecturas: lecturas de oxígeno, mediciones de periféricos, alarmas,
  eventos, arranques (reporte de reinicios), comandos, calibraciones, cambios
  de configuración y estado de salud, cada uno con sus metadatos. Las
  lecturas y mediciones se guardan **agregadas por intervalo** (promedio,
  mínimo, máximo, número de muestras y calidad), no muestra por muestra.
- **Justificación:**
  - Los reinicios, errores de periféricos y la auditoría de calibración y
    configuración son requisitos explícitos; deben poder enviarse a la
    plataforma por la misma cola y consultarse con SQL.
  - El sensor entrega 5 muestras por segundo. Guardar el agregado reduce el
    ruido, el espacio y las escrituras en la tarjeta SD (menos consumo y
    desgaste), y conserva mínimo y máximo, que es lo útil para alarmas.
  - Cada lectura anota la calibración vigente y una máscara de calidad
    (válida, saturada, en SPOC, deshabilitado, inestable, sin datos, fuera de
    rango). Un hueco se guarda como hueco (valores NULL), no como cero.
- **Alternativa descartada:** guardar solo lecturas y alarmas, con eventos en
  un archivo de registro. Se descartó porque impediría el reporte de
  reinicios, el diagnóstico remoto y la auditoría por consulta.
- **Implementación:** `src/g2/almacenamiento/sql/001_esquema_inicial.sql`.

## D-008 — Sincronización sin pérdida: cola por referencia con disparadores

- **Fecha:** 2026-10-03
- **Decisión:** la cola de envío (`cola_envio`) guarda solo una referencia
  `(tabla, registro_id, rev)`; el mensaje se arma desde la fila al enviar. El
  encolado lo hacen disparadores de la base, en la misma transacción que crea
  o modifica el registro. Las tablas que cambian tras crearse (alarma, evento,
  comando, calibración, arranque) llevan `rev`; cada modificación sube `rev` y
  encola la nueva revisión.
- **Justificación:** no duplica datos (menos espacio y escrituras) y ningún
  código puede olvidarse de encolar o encolar sin guardar. La plataforma
  recibe `(equipo, tabla, id, rev)` y descarta duplicados, así un reenvío
  tras un corte no genera registros repetidos.
- **Estados de la cola:** pendiente, enviado, confirmado, rechazado.
- **Requisito para la plataforma:** "confirmado" solo se marca cuando la
  plataforma devuelve una confirmación explícita, por registro, de que quedó
  almacenado correctamente. Un envío con respuesta HTTP exitosa no basta. El
  formato exacto se define con la plataforma (proyecto `iot-elsalvador`).
- **Pruebas:** `tests/test_esquema.py` (clase `PruebasSincronizacionYBorrado`).

## D-009 — Arquitectura de software y bajo consumo (aprobada 2026-10-03)

- **Fecha:** 2026-10-03
- **Decisión (con la condición de vigilarlos, ver D-012):** tres servicios de systemd, cada uno dueño exclusivo de su
  recurso, comunicados por un socket local (sin broker MQTT):
  - `g2-core`: ADC y periféricos, agregación, alarmas, salidas, configuración
    y **único escritor** de SQLite; alimenta el watchdog.
  - `g2-uplink`: envío a sp-peek.com, cola, comandos remotos, red.
  - `g2-ui`: pantalla Nextion y sonido; solo muestra y captura.
  Los dos últimos abren la base en solo lectura (`abrir_lectura`).
- **Justificación:** si la red o la pantalla fallan, la medición y las
  alarmas siguen; una sola escritora evita bloqueos; pocos procesos reducen
  RAM y consumo en una Raspberry Pi 3 B de 1 GB.
- **Medidas de bajo consumo y calor:** sin sondeo continuo (eventos y
  temporizadores), interrupciones con `libgpiod`, escritura por lotes en
  SQLite, envío por lotes con esperas crecientes sin red, pantalla atenuada
  tras inactividad, sonido por el altavoz de la Nextion (audio de la Pi
  apagado), HDMI y Bluetooth apagados, límites de CPU y memoria por servicio,
  reducción de actividad no esencial si sube la temperatura, medición del
  consumo real con INA219, reguladores conmutados en la alimentación.

## D-010 — Retención y borrado

- **Fecha:** 2026-10-03
- **Decisión:** retención por defecto: lecturas y eventos 1 año, salud 14
  días, alarmas, calibraciones y arranques sin límite. **Un registro solo se
  borra si la plataforma confirmó explícitamente que lo almacenó
  correctamente.** Esta regla la hace cumplir el propio esquema (disparador de
  protección por tabla y vista `v_depurable`), no solo el código.
- **Consecuencia abierta:** con la regla absoluta, si el disco se llena
  durante una desconexión larga no se puede liberar espacio borrando.
  Política por definir (ver pendientes).

## D-011 — Estado de salud del equipo: periódico y por alarmas

- **Fecha:** 2026-10-03
- **Decisión (definida por el usuario):**
  - El estado de salud de la Raspberry Pi se **registra cada 30 minutos** y se
    **transmite a la plataforma**, incluidos el uso de RAM y de almacenamiento
    (tarjeta SD).
  - Las alertas de salud son **asíncronas**: se guardan en el momento en que
    ocurren, igual que las alarmas de oxígeno alto y bajo, con umbrales
    configurables desde la pantalla Nextion y desde la plataforma.
  - Para no sumar periféricos por ahora, solo se registra lo que la propia
    Raspberry Pi reporta: temperatura, RAM, disco y **bajo voltaje**
    (indicador `throttled`). El medidor de corriente y tensión (INA219) y sus
    alertas de pico de corriente se agregarán más adelante, cuando haya
    pruebas de funcionamiento.
- **Implementación en el esquema:** `salud` tiene la columna `motivo`, que
  es un código de `catalogo_evento`: `SYS_SALUD_PERIODICA` (cada 30 min) o el
  código de la alarma que la disparó (`ALM_RPI_TEMP_ALTA`, `ALM_RPI_RAM_ALTA`,
  `ALM_RPI_BAJO_VOLTAJE`, `ALM_DISCO_ESPACIO_BAJO`, `ALM_DISCO_ESPACIO_CRITICO`).
  Las alarmas se guardan como episodios en `alarma`. Las columnas
  `tension_5v` y `corriente_ma` quedan vacías hasta tener el INA219.
- **Justificación:** menos escrituras (menos consumo y desgaste de la SD) sin
  perder los momentos que importan para el diagnóstico; el mismo mecanismo de
  umbrales y alarmas para oxígeno y salud simplifica el diseño y la auditoría.
- **Pendientes:** valores por defecto de los umbrales, tiempo mínimo entre
  alarmas repetidas de la misma causa, y nuevos tipos de dato en la plataforma
  (uso de disco, tamaño de la base) en el proyecto `iot-elsalvador`.

## D-012 — Supervisión de servicios (evitar bloqueos y congelamientos)

- **Fecha:** 2026-10-03
- **Requisito (del usuario):** los servicios no deben quedar colgados ni
  congelar lecturas o transmisiones, como ocurrió con el equipo anterior; hay
  que vigilarlos para reducir la probabilidad de fallos.
- **Diseño acordado (se implementa y se prueba por etapas):**
  - systemd reinicia cada servicio si falla (`Restart`), con límite de
    reinicios en una ventana; al superarlo escala a reinicio de la Raspberry o
    modo seguro y registra `SVC_LIMITE_REINICIOS`.
  - Watchdog por avance, no por simple "estoy vivo": cada servicio avisa a
    systemd (`WatchdogSec` con `sd_notify`) solo cuando completa trabajo real
    (una lectura, un ciclo de envío, un refresco de pantalla). Un hilo
    bloqueado deja de avisar y el servicio se reinicia (`SVC_BLOQUEO_DETECTADO`).
  - Ninguna operación de entrada/salida sin tiempo máximo: lectura del ADC y
    de periféricos, puerto serie de la pantalla, peticiones HTTP, DNS, base
    de datos (`busy_timeout`). Es la causa más probable de los congelamientos
    anteriores (ciclos de 2 s a más de 200 s y puertos bloqueados).
  - Perro guardián de hardware de la Raspberry Pi 3 B (gestionado por
    systemd) para reiniciar el equipo si el propio sistema se cuelga.
  - Límites de memoria, CPU y tareas por servicio; `g2-core` protegido frente
    al OOM; parada rápida y completa de los procesos hijos para no dejar
    puertos tomados.
  - Vigilancia cruzada: `g2-core` emite un latido; `g2-ui` muestra "núcleo
    caído" y `g2-uplink` lo informa a la plataforma, que alerta si deja de
    llegar. Sin `g2-core`, los comandos de pantalla y plataforma se rechazan
    con aviso, no se acumulan en silencio.
  - Servicios del sistema operativo innecesarios deshabilitados; registros en
    memoria o con límite de tamaño.
  - Cada reinicio queda en `evento` (códigos `SVC_*`) y en `arranque`.
- **Pruebas previstas:** inyección de fallas (congelar un proceso con
  `SIGSTOP`, desconectar el sensor o la pantalla, cortar la red, llenar el
  disco, cortar la energía en bucle) y una prueba larga de varios días.

## D-013 — Espacio en disco: alerta temprana, sin borrar ni respaldar para liberar

- **Fecha:** 2026-10-03
- **Decisión (del usuario):** por ahora el equipo **no hace respaldos
  automáticos para liberar espacio**. Se configura una **alerta de llenado
  con antelación**: debe dispararse mientras aún quede memoria suficiente para
  que el funcionamiento de la Raspberry Pi no se altere, de modo que se pueda
  hacer soporte o respaldo manual a tiempo.
- **Justificación:** no se borra ningún dato ni se altera la trazabilidad
  (factor importante); se mantiene la regla D-010 sin excepciones.
- **Implementación:** alarmas `ALM_DISCO_ESPACIO_BAJO` (aviso) y
  `ALM_DISCO_ESPACIO_CRITICO`, con umbrales configurables desde la pantalla y
  la plataforma, visibles en ambas. **Valores por defecto confirmados por el
  usuario** (a medir en el equipo): aviso cuando el espacio libre baje de
  20 % o 2 GB (lo que ocurra primero) y crítico de 10 % o 1 GB. Las alarmas de
  disco guardan además un registro en `salud` con ese motivo (D-011).
- **Estimación (por medir en el equipo):** con 2 sensores guardando cada 15 s
  se generan del orden de 4 millones de filas al año, cerca de 1 GB si ninguna
  se hubiera confirmado. Con una tarjeta de 16 GB el almacenamiento de
  lecturas dura años; el riesgo real viene de registros del sistema, archivos
  temporales y cortes muy largos, por eso se limitan los registros (D-012).
- **Mínimo de operación (aprobado por el usuario):** si, pese a las alertas,
  el espacio libre llega a un mínimo de operación, el equipo deja de guardar
  lecturas para no detener el sistema operativo. Sigue midiendo, evaluando
  alarmas, activando salidas y mostrando datos en pantalla; mantiene la
  alarma crítica activa y registra el momento en que dejó de guardar y el
  momento en que reanudó. No borra nada. **Pendiente:** el valor numérico del
  mínimo (a definir al medir el equipo; configurable).

## D-014 — Trazabilidad y auditoría de los datos

- **Fecha:** 2026-10-03
- **Requisito (del usuario):** todo el diseño debe permitir la trazabilidad
  de los datos y ser fácilmente auditable.
- **Cómo lo cumple el diseño:**
  - Cada lectura registra el sensor (serie de la etiqueta), la calibración
    vigente (gas, certificado, quién y cuándo), el arranque (versión de
    software y de configuración), la calidad del dato y la hora, con una
    marca de si el reloj era confiable y los datos para corregirla.
  - Cada cambio de configuración, comando, calibración, alarma y reinicio
    queda registrado con origen y actor.
  - La entrega a la plataforma queda registrada por registro (enviado,
    confirmado, rechazado) y no se borra nada sin confirmación (D-008, D-010).
  - La vista `v_lectura_trazabilidad` reúne todo lo anterior por lectura.
  - La cadena de huellas de D-016 hace detectable cualquier alteración de los
    registros de auditoría.
  - El código se comenta para auditoría (D-005) y cada decisión tiene su
    justificación en este documento.

## D-015 — Respaldos en un repositorio independiente

- **Fecha:** 2026-10-03
- **Decisión (del usuario):** los respaldos se guardan en **un repositorio
  aparte**, distinto de la memoria de la Raspberry Pi y de la base de datos web,
  de forma que no se altere ninguno de los dos orígenes, no se modifiquen los
  registros y se conserven **copias recurrentes** de los datos.
- **Justificación:** cumple la trazabilidad (los registros originales no se
  tocan) y da una tercera copia independiente.
- **Confirmado por el usuario (2026-10-03):** la copia la genera **la
  plataforma** (no consume energía ni espacio del equipo; el equipo solo
  conserva lo no confirmado hasta que la plataforma lo reciba) y el destino
  es **un Drive de la empresa**. La configuración se hará más adelante.
- **Pendiente de definir al configurarlo:** proveedor y cuenta del Drive,
  carpeta, forma de autenticación de la plataforma, frecuencia, qué
  incluye, cifrado, cuánto tiempo se conservan las copias, y cómo se
  verifica y se registra cada copia (fecha, rango, huella, destino).
- **Límite a tener presente:** una copia hecha desde la plataforma no incluye
  lo que el equipo aún no ha podido enviar durante una desconexión; para eso
  existe la alerta de D-013.

## D-016 — Cadena de auditoría con huellas SHA-256

- **Fecha:** 2026-10-03
- **Decisión (del usuario):** encadenar los registros de auditoría con una
  huella criptográfica para detectar alteraciones.
- **Diseño:** migración `003_cadena_auditoria.sql` (generada por
  `tools/generar_cadena.py`). Cada creación o nueva revisión de un registro de
  `arranque`, `comando`, `config_historial`, `calibracion`, `alarma` o `evento`
  agrega un eslabón a `auditoria_cadena`, en la misma transacción, mediante
  disparadores. `hash_registro` es el SHA-256 de todas las columnas de la fila;
  `hash_cadena` es el SHA-256 de `hash_previo | tabla | id | rev |
  hash_registro`. La tabla es de solo agregar (UPDATE y DELETE se rechazan).
  Los eslabones se envían a la plataforma, que guarda una copia independiente.
- **Verificación:** `g2.almacenamiento.auditoria.verificar`, que se puede
  ejecutar con una conexión de solo lectura. Detecta eslabones modificados o
  borrados, contenido alterado, cambios sin registrar y registros sin
  eslabón. Alarma prevista: `ALM_AUDITORIA_ALTERADA`.
- **Justificación:** más garantía de integridad para auditoría; el costo es el
  cálculo de una huella por cada registro de auditoría, que son pocos, y unos
  150 bytes por eslabón.
- **Decisión de diseño:** las lecturas **no** se encadenan una a una (sus
  millones de filas duplicarían el almacenamiento). Se sellarán por bloques
  (por ejemplo, una hora) con una huella del bloque agregada a esta misma
  cadena (tablas `sello_lectura` y `sello_medicion`, ya admitidas). Falta
  implementarlo con el servicio `g2-core`.
- **Límites (honestidad técnica):** detecta alteraciones, no las impide a quien
  tenga acceso de administrador al archivo; la garantía externa es la copia en
  la plataforma. Una revisión antigua solo se verifica en su eslabón. Las
  conexiones deben registrar la función `sha256`; sin ella no pueden escribir
  en las tablas auditadas (falla, no se salta la cadena).
- **Pruebas:** `tests/test_cadena_auditoria.py`.

---

## D-017 — Uso previsto: hospitales (versión industrial después)

- **Fecha:** 2026-10-04
- **Decisión (del usuario):** esta versión de G2 es para **hospitales**; la
  versión industrial se hará más adelante.
- **Consecuencias:** la trazabilidad, la auditoría, la confiabilidad y el
  registro de fallas dejan de ser deseables y pasan a ser requisitos. Hay que
  confirmar con un experto en regulación qué normas aplican (por ejemplo las
  ISO 80601-2-55, ISO 80601-2-69 e ISO 7396-1 aparecen en la bibliografía de
  analizadores de oxígeno) y qué registro sanitario exige cada país. Aún no se
  ha verificado el texto de ninguna norma.
- **Regla de diseño:** las notificaciones remotas (correo, WhatsApp) son un
  aviso secundario; el aviso primario de una alarma es siempre local (pantalla,
  sonido, salidas) y no depende de la red.

## D-018 — Recuperación escalonada: reiniciar sin apagar la Raspberry Pi

- **Fecha:** 2026-10-04
- **Decisión (propuesta, falta confirmar el cambio de esquema):** ante una falla
  se prueba la medida más pequeña que sirva, y solo se reinicia la Raspberry Pi
  cuando las anteriores no bastan:
  1. Dentro del proceso: reintentar y reabrir el dispositivo (puerto serie,
     bus I²C) sin reiniciar nada.
  2. Reiniciar **un servicio** (`g2-core`, `g2-uplink` o `g2-ui`): lo hace
     systemd ante una falla o un watchdog vencido, o un comando remoto.
     Tarda segundos y la Raspberry Pi sigue encendida.
  3. Reiniciar **todos los servicios de G2**.
  4. Reiniciar la Raspberry Pi: solo si se supera el límite de reinicios de
     servicio, si falla un bus o dispositivo que un reinicio de servicio no
     libera, o si el sistema operativo se cuelga (perro guardián de hardware).
  5. Modo seguro tras reinicios repetidos.
- **Registro de cada reinicio:** antes de reiniciar se registra el motivo y
  quién lo pidió; al arrancar se registra qué ocurrió. Un reinicio de servicio
  no apaga el equipo y queda en `evento` (`SVC_REINICIADO`,
  `SVC_BLOQUEO_DETECTADO`) y en `arranque`. Para saber si el servicio anterior
  terminó de forma limpia, `g2-core` deja una marca de apagado limpio en la
  base antes de salir; si al iniciar no está, el cierre anterior fue anormal.
  Un corte de energía no se puede evitar por software, solo inferir después
  (falta de marca de apagado limpio e indicador `throttled`).
- **Cambio de esquema (propuesta del usuario, más simple que la mía; falta
  aplicarla):** en lugar de reconstruir `arranque`, se agrega **una razón**.
  Nueva migración 004 (la 001 ya está publicada) con `ALTER TABLE ... ADD
  COLUMN`, que no obliga a reconstruir nada:
  - `razon`: código del catálogo (reinicio de servicio, reinicio remoto,
    actualización, falla de servicio, encendido normal...), nullable.
  - `so_boot_id`: identificador del encendido del sistema operativo,
    nullable.
  - `boot_id` pasa a identificar **cada inicio de `g2-core`** (por ejemplo,
    `<encendido>#<n>`), así que la restricción de unicidad actual sigue siendo
    válida. Así cada reinicio de servicio deja su fila, con su versión de
    software, y no se pierde la trazabilidad de qué versión produjo cada
    lectura.
  - `causa` conserva sus cinco valores (nivel del sistema); el detalle de un
    reinicio de servicio lo da `razon`. Es un compromiso aceptable.
  - Hay que regenerar los disparadores de la cadena de auditoría de
    `arranque` y la vista `v_cadena_contenido` para que las columnas nuevas
    entren en la huella (`tools/generar_cadena.py` debe leer todas las
    migraciones anteriores, no solo 001 y 002). Las huellas de filas
    existentes cambiarían; no hay equipos instalados todavía, así que es el
    momento barato para cerrar las columnas de las tablas auditadas.

- **Aplicado (2026-10-04):** migración `004_razon_arranque.sql`, generada por
  `tools/generar_migracion_004.py`. Agrega `arranque.razon` y `arranque.so_boot_id`,
  dos códigos nuevos de catálogo (`SYS_REINICIO_SOLICITADO`, `SYS_ACTUALIZACION`),
  vuelve a crear los disparadores de la cadena de `arranque` y la vista
  `v_cadena_contenido` (las columnas nuevas entran en la huella) y re-sella las filas
  de `arranque` anteriores con una revisión nueva. La 003 no se tocó (se comprobó que
  regenerarla produce el mismo archivo). `tools/generar_cadena.py` se dividió en
  funciones reutilizables. 62 pruebas pasan, incluida una migración de una base en
  versión 3 con datos a la 4.

## D-019 — Alertas por correo o WhatsApp y reinicio remoto (viabilidad)

- **Fecha:** 2026-10-04
- **Decisión (del usuario):** le gustan estas dos mejoras; se pidió evaluar
  si son implementables en software.
- **Conclusión:** ambas son implementables. La parte de software es pequeña o
  mediana; lo que más pesa son trámites con terceros y la seguridad.
- **Alertas (se generan en la plataforma, no en el equipo):** el equipo solo
  envía sus alarmas; la plataforma decide a quién avisar. Así las credenciales
  de correo y de WhatsApp quedan en un solo lugar y no en cada equipo.
  - Correo: SMTP o un servicio de envío transaccional; hay que configurar
    SPF y DKIM del dominio para que no caiga en spam.
  - WhatsApp: la API oficial (WhatsApp Business Platform) exige cuenta de
    empresa verificada, plantillas de mensaje aprobadas por Meta para avisos
    iniciados por la empresa, consentimiento de cada destinatario y costo por
    mensaje (verificar la tarifa vigente). No usar bibliotecas no oficiales:
    violan los términos de uso y pueden bloquear el número.
  - Reglas necesarias: contactos por rol y horario, escalamiento si nadie
    acusa, acuse de recibo, límite de frecuencia para no repetir el mismo aviso
    en cada muestra, estado de entrega y registro de cada aviso en la
    auditoría. También alerta de **equipo sin reportar** (la plataforma detecta
    la falta de latidos), porque un equipo sin red no puede avisar por sí mismo.
  - Para alarmas críticas se recomienda un canal adicional con confirmación
    (SMS o llamada), ya que WhatsApp no garantiza entrega inmediata.
- **Reinicio remoto:** comandos `reiniciar_servicio` y `reiniciar_equipo`.
  - El equipo consulta o mantiene la conexión hacia la plataforma (no se abren
    puertos de entrada). Hay que elegir entre consulta periódica y conexión
    permanente (compromiso entre latencia y consumo).
  - Comandos firmados por la plataforma y verificados por el equipo, con rol
    autorizado, confirmación, límite de frecuencia y registro en `comando` y en
    la cadena de auditoría.
  - El reinicio se ejecuta con un permiso restringido (solo `systemctl restart`
    de las unidades de G2 y el reinicio del equipo), con tiempo máximo y sin
    usar `os.system`.
  - Reglas de seguridad clínica: bloquear o exigir confirmación adicional si
    hay una calibración en curso o una alarma activa, mostrar en la pantalla
    quién lo pidió y alertar si el equipo no regresa en un tiempo razonable.
  - `g2-uplink` puede reiniciar `g2-core` aunque este esté colgado, y el perro
    guardián de hardware cubre el caso de que `g2-uplink` también falle.
- **Pendiente:** elegir proveedor de correo y de mensajería, iniciar el trámite
  de WhatsApp Business, y definir el protocolo de comandos con la plataforma.

---

## D-020 — Audio: se conserva el de la Nextion, comandado desde la Raspberry Pi

- **Fecha:** 2026-10-04
- **Decisión (del usuario):** el audio sigue siendo el de la pantalla Nextion,
  comandado desde la Raspberry Pi. **Se cancela** el uso del puerto de audio de
  la Raspberry Pi propuesto antes; se mantiene lo supuesto en D-009 (tres
  servicios, audio de la Raspberry Pi apagado).
- **Consecuencia a vigilar:** el puerto serie de la Nextion lo posee `g2-ui`,
  así que el aviso sonoro de una alarma depende de que `g2-ui` esté en marcha.
  `g2-core` pide el sonido a `g2-ui`; mientras `g2-ui` falle, el zumbador por
  GPIO que maneja `g2-core` sigue como respaldo del aviso sonoro (D-012 vigila
  a `g2-ui`).

## D-021 — Alertas por correo electrónico (en la plataforma)

- **Fecha:** 2026-10-04
- **Decisiones del usuario (confirmadas):**
  - Los destinatarios (uno o varios) los agrega el usuario admin de la
    plataforma `iot-elsalvador`.
  - El registro de correos es visible desde la plataforma.
  - Columna `sin_reporte_min` en `equipos_config` (alerta de equipo sin
    reportar).
  - **Un solo aviso por alerta, con la hora de inicio**, para no generar
    sobrealerta de eventos fáciles de resolver: sin recordatorios y sin correo
    de cierre.
  - Código y dependencia `nodemailer`.
  - Remitente: `innova@speal-intl.com` (cuenta del administrador de los
    dispositivos; el dominio usa Google Workspace).
- **Construido (2026-10-04), en la rama local `feature/alertas-correo` del
  repositorio de la plataforma, sin commit ni push:**
  - `notificaciones/`: lógica pura (`logica.js`), acceso a MySQL
    (`repositorio.js`), SMTP (`smtp.js`) y el notificador (`index.js`).
  - Ganchos en `server.js`: las dos alertas de `verificarAlertas` y la
    recepción de datos (para vigilar el silencio de un equipo). El correo no
    bloquea la recepción de datos.
  - API solo para admin: destinatarios, estado y prueba de correo, registro de
    correos y minutos de silencio por equipo.
  - Pestaña **Correos** en el panel admin, con el texto escapado antes de
    mostrarlo.
  - `migration_alertas_correo.sql`, `schema_mysql.sql`,
    `DOCUMENTACION_TECNICA.md` y `.env.example` (sin secretos).
  - 18 pruebas con `node --test` sobre la lógica, con repositorio y SMTP
    simulados.
- **Decisiones de detalle tomadas al construir (el usuario puede cambiarlas):**
  - Ventana de supresión de 60 min (`MAIL_VENTANA_SUPRESION_MIN`): no se repite
    el aviso del mismo tipo, equipo y destinatario. Evita avisos duplicados por
    una alerta que oscila o por un reinicio del servidor (cada despliegue lo
    reinicia). Una alerta nueva del mismo tipo dentro de la ventana queda
    registrada como "omitida".
  - Se descartaron del diseño la severidad mínima y el aviso de cierre del
    destinatario, por la regla de un solo aviso.
  - Tras un reinicio del servidor, el silencio de un equipo se cuenta desde el
    arranque.
  - La hora de inicio se escribe en `America/Bogotá` (`MAIL_TZ`).
  - Reintentos de envío: esperas de 1, 5, 15 y 60 min, hasta 5 intentos.
- **Lo que NO se ha verificado:** las consultas SQL de `repositorio.js` no se
  han ejecutado contra MySQL (no hay MySQL local); no se ha enviado ningún
  correo real; la interfaz no se ha abierto en un navegador. Falta probarlo en
  un entorno con base de datos y la cuenta de correo.
- **Pasos del usuario para activarlo:** crear una contraseña de aplicación de
  `innova@speal-intl.com` (requiere verificación en dos pasos) y escribirla en
  el `.env` del servidor como `SMTP_PASS` (nunca en el repositorio ni en un
  mensaje); luego, desde la pestaña **Correos**, agregar destinatarios y usar
  "Enviar prueba".
- **Despliegue:** `deploy.yml` publica en producción con cada push a `main`.
  Nada se sube sin una orden explícita; lo recomendable es abrir una solicitud
  de cambios (pull request) desde la rama y fusionarla cuando se decida.

## D-022 — Seguridad de la plataforma (propuesta, falta confirmar)

- **Fecha:** 2026-10-04
- **Voluntad del usuario:** sacar los tokens del código y de `.env.example`
  (guardarlos en la base de datos), cambiar periódicamente las contraseñas,
  y que las contraseñas no queden expuestas.
- **Hallazgos (código revisado):**
  - `.env.example` contenía un token real; ya se reemplazó por un marcador.
    Sigue estando (a) en el historial de git del repositorio, (b) como valor
    por omisión en `server.js` y (c) en `DOCUMENTACION_TECNICA.md`. Como estuvo
    publicado en el repositorio, debe considerarse comprometido y rotarse.
  - Las contraseñas **ya están en la base de datos**, pero **en texto plano**, y
    el sistema las usa como credencial en **cada petición** (cabeceras
    `x-admin-token`, `x-user-token` y la URL de `/api/stream`). Arreglarlo
    exige cambiar el inicio de sesión, no solo la forma de guardarlas.
  - Existe un administrador por defecto con contraseña `123456789`, creado en
    cada arranque con `INSERT IGNORE`.
- **Plan propuesto, por etapas (cada una con confirmación):**
  1. Contraseñas con hash y sal (`scrypt`, incluido en Node; sin dependencia
     nueva), inicio de sesión que entrega un token de sesión aleatorio con
     vencimiento, y el panel y las rutas pasan a usar ese token en lugar de
     la contraseña. Eliminar el administrador por defecto: el primero se crea
     por una variable de entorno o un script único, con cambio obligatorio.
  2. Vencimiento periódico de contraseñas (por ejemplo 90 días, configurable),
     cambio obligatorio al iniciar sesión y reglas mínimas de complejidad.
  3. Tokens de dispositivos guardados con hash (SHA-256) en la base de datos y
     mostrados una sola vez al crearlos; todos los equipos con token
     individual; retirar el token global de respaldo y rotarlo.
- **Cambios de esquema necesarios:** `usuarios` (hash, fecha del último cambio,
  cambio obligatorio), una tabla de sesiones y `equipos_config` (hash del
  token).
- **Riesgo a coordinar:** los equipos instalados usan hoy el token global o
  uno individual; rotar o retirar el global antes de actualizar sus tokens deja
  esos equipos sin transmitir. Va después de migrar cada equipo y con una
  ventana acordada.

---

## D-023 — ADC, periféricos y salidas

- **Fecha:** 2026-10-04
- **Decisiones (del usuario):**
  - ADC: Waveshare **High-Precision AD HAT con ADS1263**, 10 canales, 32 bits. Los
    sensores de oxígeno se conectan a sus entradas analógicas (pares
    diferenciales), no a un puerto de la Raspberry Pi.
  - Se esperan **2 sensores de oxígeno analógicos**.
  - Salidas: **dos relés y un LED de alarma**.
  - Periféricos deseados: temperatura y humedad, un sensor de movimiento para
    vibración (y, si se puede, inclinación), presión barométrica y un sensor de
    humedad en la línea de aire.
- **Aclaración técnica:** el giroscopio no mide presión (hPa); los hPa los da un
  barómetro. Se propone BME280 (temperatura, humedad y presión) más un IMU
  (acelerómetro + giroscopio) para vibración e inclinación.
- **Documento de referencia:** `HARDWARE.md` (diagrama, mapa de pines, direcciones
  I²C, puntos por verificar). El mapa de pines es propuesta, excepto los pines del
  ADC, que vienen de la documentación del fabricante.
- **Impactos en el diseño:**
  - El ADC va por SPI con CS por software (GPIO 22), DRDY (17) y RESET (18); el
    controlador usa `spidev` y `lgpio`/`gpiod`, no `RPi.GPIO`.
  - Lectura diferencial P2–P3 por sensor; falta verificar en el banco el límite
    de tensión de entrada con el sobrerrango negativo.
  - Fuente de 5 V limpia para los sensores (rizado < 0.1 V) y cables cortos.
  - Sin zumbador por GPIO: el aviso sonoro es el de la Nextion (D-020); el relé de
    alarma puede manejar un zumbador externo.
- **Respuestas del usuario (2026-10-04):**
  - Los relés **activan alarmas de corriente alterna (AC)**; la función de cada
    relé sigue sin confirmar (se propone relé 1 = alarma de oxígeno y relé 2 =
    falla del equipo, energizado en normal). Conmutar AC en un equipo hospitalario
    exige dimensionar los contactos, proteger y aislar; ver `HARDWARE.md` §7.
  - Un sensor de **temperatura y humedad va muy cerca de los sensores de oxígeno**,
    para medir el ambiente de los sensores y de la Raspberry Pi; no está en la
    línea de gas. El sensor de humedad de la línea de aire sigue sin definir.
  - Los pines de la cabecera quedan **expuestos** con el HAT.
  - Las referencias de los periféricos las dará el usuario más adelante.

## D-024 — Desarrollo y operación remotos por SSH

- **Fecha:** 2026-10-04
- **Requisito (del usuario):** todo el trabajo sobre el equipo se hace por **SSH**
  hacia la Raspberry Pi; el diseño debe tenerlo en cuenta.
- **Consecuencias de diseño:**
  - **Sin interfaz gráfica:** todo se opera por línea de comandos. Se agregará una
    herramienta `g2ctl` con salida legible y en JSON: estado de los servicios,
    lectura en vivo, autodiagnóstico, configuración, calibración y paquete de
    diagnóstico. Los registros se consultan con `journalctl`.
  - **Emuladores:** la mayor parte del desarrollo y de las pruebas se hace en el PC
    con emuladores de ADC, de I²C y de pantalla; en la Raspberry Pi, por SSH, solo
    se prueba lo que necesita el hardware (pruebas marcadas aparte).
  - **Instalación repetible:** un script de aprovisionamiento idempotente configura
    el sistema (SPI, I²C, UART, usuarios, permisos, servicios). Los cambios de
    arranque (por ejemplo `config.txt`) exigen reinicio; el script lo avisa. Sirve
    también como documentación para el manual.
  - **Despliegue con vuelta atrás:** cada versión en su propia carpeta y un enlace
    `actual`; si la nueva falla tras reiniciar los servicios, se vuelve a la anterior.
  - **No perder el acceso:** cualquier cambio de red (WiFi, Ethernet, ZeroTier,
    cortafuegos) se aplica con reversión automática si no se confirma en un tiempo
    corto; el acceso por ZeroTier no depende de lo que haga G2. Las sesiones largas
    van dentro de `tmux`.
  - **Seguridad del acceso:** SSH solo con llaves; los servicios corren con un
    usuario propio sin shell y con permisos mínimos sobre SPI, I²C y GPIO; la
    única elevación permitida es reiniciar las unidades de G2 (D-019).

---

## D-025 — Configuración del ADS1263 y plan de puesta en marcha

- **Fecha:** 2026-10-05
- **Contexto:** el usuario preguntó si conviene usar la ganancia (PGA) del ADS1263 para
  amplificar la señal del sensor (0 a 1 V) y reducir ruido, con 2 sensores.
- **Fuente:** hoja de datos de TI, ADS126x (SBAS661C), leída el 2026-10-05; datos en
  `HARDWARE.md` §3.
- **Decisión de diseño (propuesta; se confirma con medidas en el banco):**
  - Ganancia 1 y **PGA en derivación (bypass)**; referencia interna de 2.5 V
    (rango ±2.5 V, que cubre −0.15 a +2.0 V del sensor).
  - **Razón:** el ruido del ADC a ganancia 1 (~1.3 µV pico a pico, 20 SPS) es unas
    1500 veces menor que el ruido del sensor (< 0.2 % de O₂ ≈ 2 mV); amplificar no
    mejora la medición y recorta el rango. Con el PGA activo las entradas deben estar
    por encima de 0.3 V y P3 queda cerca de 0 V.
  - Dos sensores en entradas diferenciales: sensor 1 en AIN0–AIN1 y sensor 2 en
    AIN2–AIN3, leídos de forma secuencial con conversiones de ciclo único.
  - Filtro FIR a 20 SPS (rechazo de 50 y 60 Hz, por confirmar) y modo chopper o
    autocalibración de offset (el offset sin chopper es ~350 µV ≈ 0.035 % de O₂).
  - La reducción de ruido real se logra con una fuente de 5 V limpia para los
    sensores, cables cortos y apantallados, separación de los relés de AC y promedio
    por ventana de 200 ms.
- **Plan de puesta en marcha (por SSH):**
  1. Banco con un voltaje conocido (por ejemplo una pila medida con multímetro) para
     validar el ADC; después con el sensor de oxígeno.
  2. Controlador del ADS1263 en Python (`spidev` y `lgpio`; CS en GPIO 22, DRDY en 17,
     RESET en 18) con un emulador de la misma interfaz para las pruebas en el PC.
  3. Herramienta de banco que lee los canales y calcula promedio, desviación y valores
     pico a pico con distintas configuraciones, para decidir con datos y registrarlo
     aquí.
  4. Integración en `g2-core`.
- **Implementado (2026-10-08):**
  - `src/g2/hardware/ads1263.py`: controlador del ADC1 (reinicio, identificación,
    configuración con verificación por lectura de vuelta, conversión continua, lectura
    diferencial por RDATA1, suma de control, detección de reinicio del chip y tiempos
    máximos en toda espera). Cada constante cita la tabla o sección de la hoja de datos.
  - `src/g2/hardware/ads1263_emulado.py`: emulador del chip con reloj simulado e
    inyección de fallas (sin datos, suma de control mala, reinicio).
  - `src/g2/hardware/puerto_spi_pi.py`: puerto real (`spidev` y `lgpio`; CS en GPIO 22,
    RESET en 18).
  - `tools/banco/medir_adc.py`: herramienta de banco con configuraciones predefinidas
    (`--comparar`), comparación con una referencia de multímetro y salida en JSON.
  - 20 pruebas nuevas del controlador contra el emulador (82 en total). Límite de
    estas pruebas: el emulador refleja la lectura que se hizo de la hoja de datos; la
    validación real es la medición en el banco.
- **Primera lectura con el chip real (2026-10-08):** el flujo completo funciona (reinicio,
  configuración, conversión, suma de control correcta): ~18 lecturas por segundo con FIR
  a 20 SPS, desviación ≈ 6 µV con lo que hubiera conectado (no era una medición válida: aún
  no había voltaje de referencia conectado). Hallazgo: con el PGA en derivación el bit
  "salida alta del PGA" del byte de estado aparece activo; los monitores del PGA no
  aplican en derivación, por eso el controlador los ignora en ese caso.
- **Primera medición válida con voltaje de muestra (2026-10-08):** IN0 a ~1.6 V (fuente
  del usuario, valor de multímetro aún sin informar), IN1 a GND. Resultados con
  `medir_adc.py --par 0-1 --muestras 100 --comparar`:
  - **El ADC no es el límite:** IN1 contra COM (ambas a tierra) dio 0.37 mV de promedio,
    5.7 µV de desviación y 25 µV pico a pico con FIR a 20 SPS (≈ 0.0025 % de O₂ a
    10 mV por %). Es el piso de ruido de la cadena.
  - **El PGA activo falla en esta conexión, como se predijo:** con el PGA activo y una
    entrada cerca de 0 V la lectura quedó 15 mV por debajo (1643.7 mV frente a
    1658.8 mV; ≈ 1.5 % de O₂ en el sensor) y el chip marcó la alarma "salida baja del
    PGA". Con ganancia 2 y PGA activo la lectura fue 1093.6 mV (esperado 1658.8 mV).
    Confirma la decisión de ganancia 1 con el PGA en derivación.
  - **Todas las configuraciones con el PGA en derivación coinciden** en 1658.8 a
    1658.9 mV (diferencia de 0.1 mV ≈ 0.01 % de O₂).
  - **El ruido observado lo domina la fuente:** la dispersión varió de 143 a 844 µV entre
    corridas hechas con la misma configuración, muy por encima del piso del ADC (6 µV), por
    lo que no se puede elegir filtro con esta fuente. Hace falta una fuente más limpia
    (pila) o el sensor real.
  - **Decisión provisional:** configuración "recomendada" (ganancia 1, PGA en derivación,
    FIR a 20 SPS, sin chopper). Con dos sensores en lectura alternada, cada uno se muestrea
    unas 10 veces por segundo (cada cambio de entrada reinicia la conversión de 50 ms), más
    que las 5 actualizaciones por segundo del sensor.
  - **Pendiente:** valor del multímetro para medir el error absoluto de la cadena; repetir
    con una pila; repetir con el sensor de oxígeno.
- **Comparación con el multímetro (2026-10-08):** referencia 1.660 V (valor del usuario).
  Con el PGA en derivación, todas las configuraciones dieron entre 1658.66 y 1659.96 mV:
  diferencia de −0.04 a −1.34 mV (−0.003 a −0.08 %; −0.004 a −0.13 % de O₂ a 10 mV por %).
  Con el PGA activo: −14.7 mV (ganancia 1) y −565 mV (ganancia 2). **Alcance de la
  validación:** la coincidencia es buena, pero no certifica una exactitud absoluta mejor que
  ~0.1 %: la referencia interna del ADC tiene ±0.1 % típico (±0.2 % máximo, o ±1.7 / ±3.3 mV
  a 1.66 V) y el multímetro tiene su propia tolerancia. Para certificarla se necesita una
  referencia de tensión calibrada.
- **Análisis de ruido (2026-10-08, fuente del usuario, 90 s a 100 SPS):** herramientas
  `tools/banco/capturar_adc.py` (en la Pi) y `tools/banco/analizar_ruido.py` (en el PC;
  espectro de Welch, desviación de Allan y ruido restante según el corte de un filtro de
  primer orden). Resultado: ruido total ≈ 340 µV rms (≈ 0.034 % de O₂), **concentrado por
  debajo de 0.5 Hz** (170 µV rms por debajo de 0.1 Hz, 190 µV entre 0.1 y 0.5 Hz) y con
  picos en 0.05, 0.63, 4 y 8 Hz; la desviación de Allan **no baja** al promediar (130 a 270 µV
  de 0.05 s a 40 s). Es ruido lento de la fuente (probablemente un divisor del riel de 5 V
  de la Pi), no ruido blanco del ADC (piso de ~6 µV). Consecuencias: (1) un filtro no lo
  quita sin quitar también la señal útil (el ancho de banda de la respuesta del sensor es
  ≈ 0.35 / 11 s ≈ 0.03 Hz): un corte de 0.2 Hz solo baja el ruido a 236 µV y exigiría unos
  800 µF con 1 kΩ; (2) el filtrado, si hace falta, va en digital; (3) el análisis debe
  repetirse con el sensor de oxígeno real, cuyo ruido es otro.
- **Prueba A/B: ¿el ruido lo mete la fuente? (2026-10-08).** La fuente de prueba es un divisor
  de dos resistencias iguales alimentado desde el pin de 3.3 V de la Raspberry Pi (≈ 1.66 V).
  Se capturaron 45 s a 100 SPS en tres condiciones (`tools/banco/comparar_capturas.py`):

  | | Divisor en reposo | Divisor con la Pi a plena carga | Piso del ADC (entradas a tierra) |
  |---|---|---|---|
  | Desviación | 470 µV | 650 µV | 6.4 µV |
  | Pico a pico | 2751 µV | 2660 µV | 51 µV |
  | Promedio | 1.659017 V | 1.658664 V | 0.000373 V |
  | Ruido < 1 Hz (rms) | 183 y 242 µV | 265 y 331 µV | 0.3 y 1.2 µV |
  | Allan a 1 s / 10 s | 252 / 158 µV | 322 / 293 µV | 1.1 / 0.2 µV |

  Conclusión: **la fuente domina el ruido** (73 veces el piso del ADC) y **depende de la carga
  de la Pi**: con los 4 núcleos al máximo el ruido por debajo de 1 Hz sube ~40 % y el promedio
  baja 0.35 mV, lo que apunta al riel de 3.3 V (el ADC usa su referencia interna de 2.5 V, con
  rechazo de alimentación de 80 a 90 dB, así que no explica ese corrimiento). Promediar más no
  ayuda (Allan sin descenso), por ser ruido lento. Limitación: la carga también calentó la placa
  (60 °C, límite suave de temperatura activo) y parte de la deriva puede ser térmica de las
  resistencias. Para confirmarlo del todo: repetir con una pila o una referencia de tensión
  dedicada en lugar del pin de 3.3 V.
- **Prueba A/B con una pila como fuente (2026-10-09).** Se repitió la prueba con el divisor
  (4 resistencias iguales) alimentado por una pila de 10 V, a ≈ 1.99 V, en reposo y con la Pi a
  plena carga (45 s a 100 SPS cada una):

  | | Divisor desde 3.3 V de la Pi | Divisor con pila |
  |---|---|---|
  | Desviación en reposo / con carga | 470 / 650 µV | **92 / 86 µV** |
  | Ruido < 0.1 Hz (rms) | 183 y 265 µV | **7.0 y 7.0 µV** |
  | Ruido 0.1–1 Hz (rms) | 242 y 331 µV | **2.4 y 3.1 µV** |
  | Ruido 1–10 Hz (rms) | 161 y 180 µV | **2.8 y 6.8 µV** |
  | Pico a pico | 2751 / 2660 µV | 370 / 398 µV |

  Conclusión: **el ruido venía del riel de 3.3 V de la Pi.** Con la pila, el ruido por encima de
  0.1 Hz es del orden del piso del ADC (0.3 a 5 µV rms por banda) y **no cambia con la carga de la
  Pi**: la cadena de medición (ADC, su alimentación, el cableado) es insensible a lo que haga el
  procesador. Lo que queda en la desviación (≈ 90 µV) es una **deriva lenta** (≈ −300 µV en 45 s, de
  la pila al descargarse y de la temperatura de las resistencias), no ruido: explica el pico a pico
  de ~370 µV y el valor de Allan a 10 s (≈ 48 µV). Con esta fuente el ruido total es de ~0.009 % de
  O₂ (a 10 mV por %), muy por debajo de la especificación del sensor (< 0.2 %). Pendiente: el valor
  del multímetro para esta fuente (error absoluto).
- **Comparación con el multímetro, fuente de pila (2026-10-09):** el usuario midió 1.988 V entre IN0
  e IN1. El ADC leyó 1990.2 y 1989.8 mV en las capturas anteriores y **1985.8 mV (tres mediciones de
  200 muestras, desviación 5 a 6 µV, el piso del ADC) minutos después**: la fuente derivó unos 4.4 mV
  (pila al descargarse y temperatura de las resistencias). Como las lecturas no fueron simultáneas,
  1.988 V queda entre las dos del ADC y no se puede calcular el error absoluto: lo único que se
  concluye es que ADC y multímetro coinciden dentro de la deriva de la fuente (≈ ±2 mV, ±0.1 %).
  Además, **tanto el ADC (40 MΩ) como el multímetro (≈ 10 MΩ) cargan el divisor**: con
  resistencias de 100 kΩ el efecto sería de ~0.2 % y ~0.8 %; hay que conocer los valores. Para
  validar la exactitud absoluta: leer el multímetro y el ADC al mismo tiempo, con una fuente de baja
  impedancia (resistencias de 10 kΩ o menos, o una pila directa).
- **Comparación simultánea con el multímetro (2026-10-09, 15:30 a 15:31):** multímetro 1.987 V (en
  paralelo, resolución de 1 mV) frente a **1985.24 mV del ADC** (400 muestras en 20 s): el ADC lee
  **1.76 mV (−0.09 %) menos**. El resultado repite el de la fuente de 1.660 V (−0.08 %): una
  diferencia **proporcional y del mismo signo en dos fuentes y dos niveles**, compatible con un
  error de ganancia (la referencia interna del ADC tiene ±0.1 % típico y ±0.2 % máximo; o la
  calibración del propio multímetro, cuya tolerancia típica es mayor, ≈ ±0.5 %). La carga del
  divisor no lo explica (el multímetro, de menor impedancia, leería por debajo, no por encima).
  Con el multímetro conectado el ruido subió de 5 a 109 µV (la medición del multímetro inyecta
  ruido). **Efecto en el sensor:** un error de −0.09 % de la lectura equivale a 0.02 % de O₂ en
  aire y 0.09 % de O₂ al 100 %, dentro de la especificación del sensor (±0.2 %), pero el error
  máximo de la referencia (±0.2 %) sumaría 0.2 % de O₂ al 100 %. Se puede corregir con una
  referencia de tensión calibrada (la exactitud absoluta del ADC no se puede certificar con este
  multímetro); queda como mejora opcional.
- **Método para fijar la frecuencia de corte:** capturar una serie larga (≥ 90 s) con el
  sensor real, calcular el espectro y la desviación de Allan, estimar el ancho de banda de la
  señal (≈ 0.35 / tiempo de respuesta) y elegir un corte ≥ 3 veces mayor con un retardo
  aceptable; se verifica con la tabla "corte frente a ruido restante" de `analizar_ruido.py`.
- **Siguiente:** con el voltaje de muestra (pila medida con multímetro) conectado a
  AIN0 (+) y AIN1 (−, y a GND), correr `medir_adc.py --comparar --referencia-v <valor>`
  y registrar aquí el resultado para fijar la configuración.
- **Pendiente:** acceso SSH a la Raspberry Pi, confirmar que el HAT está instalado y SPI
  habilitado, y consultar a Hummingbird la conexión recomendada de P3 con un ADC externo.

---

## D-026 — Raspberry Pi de desarrollo: estado inicial, acceso y primera carga

- **Fecha:** 2026-10-08
- **Equipo:** Raspberry Pi de desarrollo en la red local, dedicada a G2 (versión
  completamente nueva; sin firmware del analizador anterior), con el HAT ADS1263
  instalado.
- **Acceso:** por SSH con una llave propia de este PC, instalada el 2026-10-08. Los
  datos de acceso y el procedimiento para revocarla están en las notas locales (no
  publicadas). La seguridad de la cuenta de usuario (contraseña y acceso por
  contraseña) se endurecerá más adelante, por decisión del usuario.
- **Estado inicial verificado (solo lectura):**
  - Modelo **Raspberry Pi 3 Model B Plus Rev 1.4** (no 3 B), aarch64, 905 MB de RAM.
  - Debian 13 (Trixie) con **escritorio** (`graphical.target`, `lightdm`), Python 3.13.5,
    SQLite 3.46.1, pip 25.1.1; 15 GB de tarjeta, 7.9 GB libres.
  - Ya instalados: `git`, `python3-venv`, `python3-spidev`, `python3-lgpio`, `i2c-tools`.
    Faltan: `sqlite3` (cliente), `tmux`.
  - **SPI, I²C (GPIO 2 y 3) y UART no están habilitados** (no existen `/dev/spidev*`,
    `/dev/i2c-1` ni `/dev/serial*`); la consola serie sí está habilitada, lo que choca
    con la pantalla Nextion. El `i2c-2` que aparece es el del puerto HDMI.
  - Sin reloj de tiempo real (`/dev/rtc*`); la hora está sincronizada por NTP
    (America/Bogota) gracias a Internet.
  - Servicios en marcha innecesarios para un equipo sin pantalla de escritorio:
    `lightdm`, `bluetooth`, `avahi-daemon`, `rpcbind`, `nfs-blkmap`, `udisks2`,
    `accounts-daemon`. ZeroTier no está activo.
  - Sin subtensión (`throttled=0x0`), 46 °C. `sudo` pide contraseña.
  - Tiene Internet (GitHub responde 200).
- **Primera carga (2026-10-08):** código copiado a `~/g2/dev` (src, tests, tools) y
  **las 62 pruebas pasan en la Pi** (Python 3.13.5, SQLite 3.46.1), además de en el PC
  (Python 3.10, SQLite 3.39). Es la primera verificación en el hardware real.
- **Preparación propuesta (cambia el sistema; pendiente de confirmar, requiere
  reinicio):** cambiar la contraseña de `pi`; pasar a modo sin escritorio y apagar
  `lightdm`; habilitar SPI e I²C; liberar el UART principal para la Nextion
  (`enable_uart=1`, `dtoverlay=disable-bt`, sin consola serie); deshabilitar `bluetooth`,
  `avahi-daemon`, `rpcbind` y `nfs-blkmap`; instalar `sqlite3` y `tmux`. Todo debe quedar
  en un script de aprovisionamiento repetible dentro del repositorio.

- **Aprovisionamiento aplicado (2026-10-08), con aprobación del usuario:** script
  `scripts/aprovisionar_pi.sh` (repetible; con `--verificar` solo informa). Habilitó SPI e
  I²C, activó el UART por hardware, quitó la consola serie, desactivó el Bluetooth
  (`dtoverlay=disable-bt` y servicio) e instaló `sqlite3` y `tmux`. Guarda copias
  `config.txt.g2-original` y `cmdline.txt.g2-original` para volver atrás. Se reinició la
  Pi y se verificó: existen `/dev/spidev0.0`, `/dev/i2c-1` y `/dev/serial0 → ttyAMA0` (el
  UART principal PL011), el Bluetooth no existe y no hay consola serie.
- **No se tocó, por decisión del usuario:** la contraseña de `pi` (se cambiará más
  adelante, y después se desactivará el acceso por contraseña) y el escritorio `lightdm`
  (se conserva por si hace falta conectarse directamente; se apagará cuando el equipo
  esté estable). Quedan sin decidir `avahi-daemon`, `rpcbind` y `nfs-blkmap`.
- **ADS1263 detectado:** `tools/banco/sonda_ads1263.py` reinicia el chip y lee tres
  registros: ID = 0x23 (dispositivo 1 = ADS1263), POWER = 0x11 e INTERFACE = 0x05, los
  valores de fábrica. Confirma que el HAT está bien conectado y que CS (GPIO 22), RESET
  (GPIO 18) y SPI0 funcionan. El bus I²C 1 está vacío (aún no hay periféricos).

- **Incidente de conexión SSH (2026-10-08):** durante unos minutos las conexiones desde el
  PC expiraron antes de autenticar (el servidor las registró como "Connection reset
  [preauth]"); el kernel no registró errores y la Pi estaba sana (carga 0, sin subtensión).
  Causa probable (no demostrada): el ahorro de energía del WiFi, activo por omisión, con la
  Pi solo por WiFi. **Por decisión del usuario se desactivó** (archivo
  `/etc/NetworkManager/conf.d/10-g2-wifi-sin-ahorro.conf` e inmediato con `iw`), y quedó en
  `scripts/aprovisionar_pi.sh`. También se vio que una de las consultas se había ejecutado
  dentro de la propia Pi; los comandos de consulta se ejecutan desde el PC.

---

## D-027 — Valores por defecto de la configuración

- **Fecha:** 2026-10-08
- **Definidos por el usuario:**
  - Intervalo de pantalla: **1 s**.
  - Alarma de oxígeno **bajo: 20 %** (alarma cuando O₂ < 20 %) y de oxígeno **alto: 92 %**
    (alarma cuando O₂ > 92 %). **Ambos umbrales deben poder configurarse desde la pantalla
    Nextion y desde la plataforma** (misma regla de conflicto que el resto de la
    configuración: gana el cambio más reciente, y cada cambio queda auditado en
    `config_historial`).
  - Temperatura de la Pi (aviso): **60 °C**.
  - Uso de RAM (aviso): **85 %**.
- **Aceptados de la propuesta:** intervalo de guardado 15 s; escala del sensor 10 mV por %
  de O₂; retardo antes de alarmar 10 s; histéresis 0.5 % de O₂; alarma por sensores
  discrepantes con diferencia mayor que 0.5 %; salud periódica cada 30 min; disco: aviso al
  bajar de 20 % o 2 GB libres y crítico al bajar de 10 % o 1 GB.
- **Claves definidas (2026-10-08):** ver D-028 (`src/g2/configuracion/catalogo.py`).
- **Pendiente:** la regla de qué hacen las alarmas con los dos sensores (alarma por
  sensor o por el peor de los dos); el usuario está revisando la lógica de alarmas.

---

## D-028 — Capa de datos, catálogo de configuración y base real en la Pi

- **Fecha:** 2026-10-08
- **Qué se construyó:**
  - `src/g2/configuracion/catalogo.py`: **única fuente de verdad** de la configuración: 23
    claves con tipo, valor por defecto (D-027), límites, unidad, descripción y quién puede
    cambiarlas (`pantalla`, `plataforma`, `local`). Reglas entre claves: `alarma.o2_bajo_pct` <
    `alarma.o2_alto_pct` y los umbrales críticos de disco por debajo de los de aviso. Los
    umbrales de oxígeno se pueden cambiar desde pantalla y plataforma; la identidad del equipo
    (`equipo.id`, `equipo.nombre`) y la marca interna `sistema.apagado_limpio` solo localmente.
  - `src/g2/almacenamiento/almacen.py` (clase `Almacen`): **la única vía de escritura del
    núcleo.** Cada operación es una transacción (`BEGIN IMMEDIATE`); los registros llevan solos
    los datos de tiempo (hora UTC, reloj confiable, arranque, tiempo monotónico); consultas con
    parámetros; la cola de envío y la cadena de auditoría las hacen los disparadores.
    Operaciones: apertura con migraciones y siembra de configuración, arranque y apagado limpio,
    configuración con validación e historial, sensores y calibración, lecturas con la
    calibración vigente, salud, eventos con agrupación de repetidos (`evento.agrupar_s`), ciclo
    de vida de alarmas (abrir sin duplicar, pico, acuse, cierre), comandos idempotentes por
    `uuid` y resumen del estado de la base.
  - `src/g2/tiempo.py`: relojes (`RelojSistema` consulta a systemd si la hora está sincronizada;
    `RelojPrueba` para las pruebas).
  - `src/g2/ctl.py` (`python3 -m g2.ctl`): herramienta por SSH con `bd-crear`, `bd-estado`,
    `bd-verificar`, `config-listar`, `config-fijar`, `sensores-listar`, `sensor-agregar` y
    `sensor-serie`. La ruta de la base sale de `--bd`, de `G2_BD` o de `~/g2/datos/g2.db`.
- **Decisiones de diseño:**
  - Escribir una clave con el mismo valor no deja nada en el historial (evita ruido y
    revisiones inútiles en la cadena de auditoría); lo mismo con `actualizar_pico`.
  - El estado interno (`sistema.apagado_limpio`) se guarda sin historial: no es un cambio de
    configuración.
  - El habilitado de cada sensor vive en la tabla `sensor` (no en `config`), para que haya una
    sola fuente de verdad; cambiarlo deja un evento (`SEN_HABILITADO` / `SEN_DESHABILITADO`).
  - Las herramientas que no son el núcleo reutilizan el último arranque o crean uno
    (`g2ctl <versión>`), ya que todo registro exige un arranque. Cuando exista `g2-core`, los
    cambios irán por su socket local (D-009).
- **Pruebas:** 47 nuevas (catálogo y capa de datos), 132 en total; pasan en el PC y en la Pi.
  Incluyen una prueba de que la cadena de auditoría queda coherente tras un uso completo.
- **Base real creada en la Pi (2026-10-08):** `~/g2/datos/g2.db` (esquema versión 4, 216 KiB, modo
  WAL), con las 23 claves sembradas en sus valores por defecto, **Sensor 1** (`ads1263:0-1`) y
  **Sensor 2** (`ads1263:2-3`) dados de alta (Paracube Micro 01117707, 10 mV por %; serie
  pendiente: `sensor-serie`). La cadena de auditoría verifica OK. Es la base de desarrollo; la
  definitiva irá en `/var/lib/g2` con un usuario de servicio y permisos restringidos (el archivo
  actual es legible por todos los usuarios de la Pi).
- **Pendiente:** la lógica de alarmas (en revisión por el usuario), `g2-core`, y el catálogo de
  claves de la plataforma y la pantalla (URL, sincronización) cuando se diseñe `g2-uplink`.

---

## Decisiones pendientes

- Probar las alertas por correo con MySQL y la cuenta real, y decidir cuándo
  fusionar la rama `feature/alertas-correo` (D-021).
- Seguridad de la plataforma: confirmar el plan por etapas y las columnas y
  tablas nuevas (D-022).
- Proveedor de correo y de mensajería, trámite de WhatsApp Business y
  protocolo de comandos remotos con la plataforma (D-019).
- Confirmar con un experto en regulación las normas y el registro
  sanitario aplicables a la versión hospitalaria (D-017).
- Configuración del Drive de la empresa para los respaldos: proveedor,
  cuenta, carpeta, autenticación, frecuencia, cifrado y retención (D-015).
- Valor numérico del mínimo de operación del disco (D-013).
- Sellado por bloques de las lecturas dentro de la cadena de auditoría
  (D-016).
- Confirmación por registro con la plataforma, incluida la copia de la
  cadena (D-008, D-016).
- Valores por defecto de los umbrales de temperatura y RAM, y tiempo mínimo
  entre alarmas repetidas (D-011). Los de disco ya están definidos (D-013).
- Incorporar el medidor INA219 (corriente y tensión), cuando haya pruebas
  (D-011).
- Reloj de tiempo real y política de marcas de tiempo sin hora confiable
  (el esquema ya guarda lo necesario para corregir las horas).
- Modelo de configuración: claves y valores por defecto (la tabla `config` ya
  existe; falta definir el catálogo de claves).
- Comandos remotos autenticados, con confirmación y auditoría.
- Lógica de alarmas local (histéresis, tiempo mínimo, acuse, estado seguro de
  salidas).
- Protocolo con la pantalla Nextion, versionado.
- Gestión de WiFi (NetworkManager).
- Sistema de archivos de solo lectura y partición de datos.
- Actualización remota firmada con vuelta atrás.
- Confirmar las funciones de los relés, definir los dimensionamientos para AC y
  elegir los modelos de los periféricos (D-023, `HARDWARE.md`); verificar en el
  banco la lectura diferencial del sensor con el ADS1263.
