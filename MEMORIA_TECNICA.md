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

## D-029 — Pantalla Nextion: forma de trabajo (PROPUESTA, preguntas abiertas)

- **Fecha:** 2026-10-09
- **Equipo:** Nextion NX8048P050-011R (serie Intelligent, 5", 800×480, táctil resistiva, con
  altavoz) conectada al UART principal de la Pi (`/dev/serial0`), que ya está liberado (D-026).
  Audio: el de la Nextion, comandado desde la Pi (D-020).
- **Principio:** la pantalla es una **vista y un teclado**; no decide nada. Toda la lógica vive en
  el firmware (D-024). El servicio **`g2-ui`** es el único dueño del puerto serie (D-009).
- **Flujo de datos:**
  - `g2-core` publica su estado en vivo (lecturas de cada segundo, alarmas, calibración en curso)
    por su socket local; `g2-ui` lo toma y actualiza solo los campos que cambian, cada
    `muestreo.intervalo_pantalla_s` (1 s). Lo histórico y la configuración los lee de la base.
  - Una acción en la pantalla (cambiar un umbral, deshabilitar un sensor) llega a `g2-ui`, que la
    valida y se la pide a `g2-core`; este la aplica con `Almacen.config_fijar(origen="pantalla")` y
    la pantalla muestra lo que `g2-core` confirma, no lo que tecleó el usuario. Si la plataforma
    cambia el mismo valor, gana el más reciente y la pantalla se refresca (D-028).
  - Si la pantalla se reinicia sola, `g2-ui` la vuelve a sincronizar completa. Si `g2-core` cae, la
    pantalla muestra "núcleo caído" y rechaza cambios (D-012).
- **Pantallas previstas (según los requisitos del usuario):** principal (lecturas de los dos
  sensores, estado de alarmas y de red); alarmas (umbrales bajo y alto, acuse, historial);
  configuración (intervalos de guardado y de visualización, habilitar o deshabilitar sensores);
  red (estado de internet, IP asignada por DHCP y conexión a una red WiFi con nombre y contraseña
  tecleados en la pantalla, aplicada por NetworkManager con reversión automática, D-024);
  calibración (guiada: aire a 20.9 %, verificación de estabilidad, gas y certificado, corrección de
  cero registrada con su autor); sistema (estado de la base y de la cola de envío, reinicios,
  salud de la Pi, versión).
- **Protocolo:** el de la propia Nextion, con las lecciones del equipo anterior (`CONTEXTO.md` §4):
  eventos de toque por `printh 65 <página> <id> 00 FF FF FF` como primera línea del evento de
  soltar, con "Send Component ID" desmarcado (borrar un objeto renumera los ids y rompe el
  protocolo sin avisar); lectura de textos con `get` (respuesta `0x70`); tabla de ids versionada
  junto con el `.HMI`. Una versión de protocolo en la pantalla que `g2-ui` comprueba al arrancar.
- **Sonido:** el de navegación (toques) lo reproduce la propia pantalla desde su código, sin ir y
  volver a la Pi; los de alarma los ordena `g2-ui` con prioridad. Si `g2-ui` falla no suena la
  alarma por la pantalla (el relé de alarma sigue funcionando).
- **Cómo se trabaja por SSH:** el diseño gráfico (`.HMI`) se hace en el editor de Nextion, que es
  una aplicación de Windows y no se puede usar por SSH. El `.HMI` y el `.tft` compilado se versionan
  en el repositorio. La carga del `.tft` a la pantalla se hará desde la Pi por el puerto serie
  (`g2ctl pantalla-cargar`, protocolo de carga de Nextion), sin quitar la tarjeta. Para probar sin
  pantalla se escribe un emulador de la Nextion (D-024).
- **Modelo en el editor de Nextion (2026-10-09):** en la serie *Intelligent* del editor, el modelo que
  corresponde a la pantalla del equipo anterior (NX8048P050-011R) es **NX8048P050_011**: 5.0",
  800×480, Flash 128 MB, RAM 524288 B (512 KB) y 200 MHz. Los tres modelos NX8048 (4.3", 5.0" y 7.0")
  comparten resolución de 800×480, pero el `.tft` debe corresponder al modelo exacto de la
  pantalla. El sufijo R o C de la etiqueta indica el tipo de táctil (resistivo o capacitivo) y no
  cambia el modelo del editor. **Por confirmar** con la etiqueta de la pantalla comprada o con
  `tools/banco/sonda_nextion.py`, que le pregunta el modelo por el UART (probada: sin respuesta
  porque aún no está conectada). Límite de diseño a tener en cuenta: 512 KB de RAM para variables.
- **Ajustes de pantalla en el editor (2026-10-09), propuesta:**
  - **Dirección:** 0° horizontal (800×480, apaisada), salvo que la caja del equipo obligue a montar
    la pantalla al revés (entonces 180°; se corrige aquí y no en el código). 90° y 270° dan
    480×800 vertical y no se usarán.
  - **Codificación de caracteres: iso-8859-1 (Latin-1).** Cubre todo el español (á é í ó ú ñ ü ¿ ¡)
    y además ° (grados), µ, ± y ² (se usarán en °C y µV). Cada carácter ocupa un byte, lo que
    simplifica el protocolo y los límites de longitud de los textos (`txt_maxl` cuenta bytes). Se
    descarta UTF-8 por ahora (solo español).
  - **Reglas que se derivan:** (a) las fuentes se generan con el *Font Generator* en la **misma
    codificación** del proyecto, incluyendo los caracteres 32 a 255; (b) `g2-ui` codifica y
    decodifica los textos con `latin-1` (Python `encode("latin-1")`); (c) en pantalla no se usan
    caracteres fuera de Latin-1: se escribe **O2** (no O₂), y las palabras "aprox.", "ohmios" y
    "mayor o igual" en lugar de ≈, Ω y ≥; (d) cambiar la codificación después obliga a rehacer
    las fuentes y revisar todos los textos.
- **Proyecto en el editor (2026-10-09):** el usuario creó `nextion/g2.HMI` dentro del repositorio, con
  el modelo `NX8048P050_011`, codificación `iso-8859-1` y una sola página (`page0`). El archivo pesa
  unos 7 MB y el editor lo tiene bloqueado mientras está abierto, así que **se sube a GitHub solo en
  hitos y con el editor cerrado** (no en cada commit) para no inflar el repositorio. La
  especificación de construcción está en `nextion/ESPECIFICACION_HMI.md` (etapa 1: convenciones,
  protocolo y página principal).
- **Fondo de la pantalla (2026-10-09):** la imagen de fondo de la página principal la generó una IA
  a partir de un prompt con las medidas de la especificación. Salió con la proporción correcta
  pero con las zonas comprimidas en vertical (tarjetas hasta y=291 en vez de 352; botones en
  410–446 en vez de 424–472). En lugar de volver a generarla, `tools/ajustar_fondo_nextion.py`
  la estira por bandas a la cuadrícula y quita la marca de agua, que quedaba aplastada. La
  imagen no lleva texto (el español y los valores los escribe la Pi). Al usar fondo, las
  tarjetas y la barra ya no son componentes; los textos sobre ellas usan `crop image`. De
  paso se corrigieron anchos de la especificación que no cabían (texto de botones, `COLA 1250`,
  estado `DESHABILITADO` → `APAGADO`).
- **Pitido de pulsación (2026-10-16, pedido del usuario):** cada botón emite un pitido al pulsarse. La
  pantalla tiene altavoz sin zumbador (`CONTEXTO.md`), así que `beep` no sirve: se reproduce un
  archivo de audio corto (`nextion/sonidos/pulsacion.wav`, generado por
  `tools/generar_sonido_pulsacion.py`) con `play 1,0,0` en el *Touch Press* de cada botón. Se usa el
  canal 1 para los toques y se reserva el canal 0 para las alarmas. Lo reproduce la propia pantalla
  (no la Pi) para que suene al instante. A confirmar con la pantalla real: formato de audio
  aceptado, existencia del canal 1 y volumen.
- **Versionado de los programas de la pantalla (2026-10-16, aprobado por el usuario):**
  - Lo pequeño va en Git normal y siempre: especificación, fuentes (`nextion/fonts/`), imágenes, sonidos
    y los scripts que los generan.
  - El proyecto `.HMI` (~9 MB y creciendo) y el compilado `.tft` van con **Git LFS** (activado con
    `git lfs install` y `git lfs track "*.HMI" "*.tft"`): el repositorio guarda un puntero y el archivo
    real queda en el almacén LFS de GitHub (1 GB gratis, unas 100 versiones). Se suben solo en hitos
    y con el editor cerrado, porque este bloquea el archivo mientras está abierto.
  - Pendiente (se hace en el primer hito): `nextion/VERSION` y etiquetas `pantalla-vX.Y.Z`; la versión
    escrita en la página Sistema; `nextion/MANIFIESTO.md` con la huella SHA-256 de cada `.tft`
    publicado; y que la Pi registre en la base (cadena de auditoría) la huella del `.tft` que cargó,
    para saber qué programa tenía la pantalla en cada fecha.
  - Quien clone el repositorio necesita Git LFS instalado para descargar el `.HMI` y el `.tft`.
- **Decisiones de protocolo tomadas en la especificación:** (a) toda navegación pasa por la Pi (para
  poder exigir el PIN y forzar páginas); (b) los eventos de toque llevan **códigos propios**
  (`printh 65 <página> <control> 00 FF FF FF`) y no el `id` del editor, de modo que borrar o reordenar
  objetos no rompe el protocolo; (c) el evento `FE` de "página cargada" permite a la Pi rellenar la
  página aunque la pantalla se haya reiniciado; (d) la versión del protocolo vive en la variable
  `principal.proto`.
- **Respuestas del usuario (2026-10-09):**
  1. **El usuario construirá el `.HMI`** en el editor de Nextion, con ayuda: se le entrega una
     especificación (páginas, componentes con nombres e ids, eventos) y revisión por pantalla.
  2. **Habrá un PIN para proteger los cambios** (umbrales, calibración, conexión de red): uno **por
     defecto** y otro **que se puede asignar desde la plataforma**. Interpretación a confirmar: el
     PIN por defecto sirve mientras no se asigne uno desde la plataforma; al asignarlo, el de
     fábrica deja de valer. Diseño propuesto: el PIN se guarda con hash y sal (nunca en claro), se
     compara en `g2-core` (la pantalla solo envía lo tecleado), con límite de intentos y bloqueo
     temporal, cada intento fallido y cada cambio de PIN queda como evento, y la pantalla no
     muestra nunca el PIN vigente. Un PIN por defecto conocido es débil: debe cambiarse al
     instalar el equipo (se avisa en pantalla mientras siga activo).
  3. **Se conserva la exportación de reportes de lecturas a una memoria USB** (la hacía el equipo
     anterior). Pendiente definir: formato (PDF y/o CSV), rango de fechas, contenido (lecturas,
     alarmas, eventos, calibraciones) y trazabilidad del propio reporte (huella SHA-256 del
     archivo y estado de la cadena de auditoría al generarlo). El reporte lo genera `g2-core` desde
     la base en solo lectura y se copia a la memoria USB montada por `udisks2` (ya instalado).
  4. **Solo español**, por ahora.

---

## D-030 — Novedades por fecha en la página principal del repositorio

- **Fecha:** 2026-10-09
- **Pedido del usuario:** llevar los cambios con fechas en la página principal del repositorio, como
  otra forma de que el equipo de trabajo esté enterado.
- **Implementación:** `README.md` es la página principal de GitHub (resumen, estado de cada parte,
  cómo empezar, estructura y enlaces a la documentación). Su sección **Novedades** se genera con
  `tools/actualizar_novedades.py` a partir de `git log` (fecha, título y viñetas del mensaje de cada
  commit, agrupados por día), entre las marcas `NOVEDADES:INICIO` y `NOVEDADES:FIN`; el resto del
  README no se toca y el programa falla en vez de borrar si faltan las marcas. Con `--mensaje` se
  incluye el commit que se está por hacer, para que el README quede en el mismo commit.
- **Procedimiento antes de cada commit:** escribir el mensaje con un título claro y viñetas ("- ...");
  ejecutar `python tools/actualizar_novedades.py --mensaje <archivo del mensaje>`; hacer el commit con
  ese mismo archivo. El estado (tabla "Estado" del README) se edita a mano cuando una parte cambia.
- **Cuidado:** el README es público; solo sale lo que dicen los mensajes de los commits, que no
  deben llevar direcciones, contraseñas ni datos de acceso. Los mensajes se escriben con tildes.
- **Pruebas:** `tests/test_novedades.py`.

---

## D-031 — Función del botón "Acusar"

- **Fecha:** 2026-10-16
- **Decisión del usuario:** acusar una alarma **silencia solo el sonido de la pantalla** y **nunca
  desactiva los relevos** de las alarmas de corriente alterna: esos siguen activados mientras la
  alarma esté activa. Pasados **2 minutos** desde el acuse, si la alarma persiste, el sonido de la
  pantalla vuelve a sonar.
- **Implementación prevista:**
  - La clave de configuración `alarma.acuse_silencio_s` (por defecto 120 s, entre 10 y 3600) fija ese
    tiempo; se creó en `catalogo.py` y se prueba en `tests/test_configuracion.py`.
  - La pantalla solo envía el evento de toque (`65 00 06 00 FF FF FF`); `g2-core` registra el acuse
    (ya existe `Almacen.acusar` en el ciclo de vida de la alarma, con quién y cuándo) y calcula el
    silencio; `g2-ui` ordena a la Nextion el sonido.
  - El acuse **no cierra** la alarma: se cierra cuando el valor vuelve a la normalidad (con la
    histéresis). Un acuse repetido reinicia los 2 minutos.
  - Los relevos dependen únicamente del estado de la alarma, nunca del acuse; esto debe cubrirse con
    una prueba cuando se construya el motor de alarmas.
- **Por qué:** una alarma silenciada por error no debe dejar al personal sin ningún aviso físico, y el
  sonido que vuelve a sonar evita que una alarma acusada y olvidada pase inadvertida.

---

## D-032 — Alarmas por sensor: aviso visual y sonoro

- **Fecha:** 2026-10-19
- **Decisión del usuario:** cada sensor tiene **su propia alarma**; no se agrupan en "el peor de los
  dos". Cada alarma se avisa de forma visual (un letrero o el indicador del sensor iluminado) y con
  sonido.
- **Cómo queda (propuesta que sigue esa decisión; el usuario puede ajustarla):**
  - **Independencia.** Cada sensor evalúa sus umbrales (`alarma.o2_bajo_pct`, `alarma.o2_alto_pct`) con
    su retardo y su histéresis, y abre y cierra su propia alarma en la base de datos (ya guarda
    `sensor_id` en cada alarma). Que un sensor esté en alarma no afecta al otro.
  - **Aviso visual por sensor (pantalla principal).** El recuadro de estado del sensor (`est_1`,
    `est_2`) cambia a rojo con el texto ALTA o BAJA y el valor de oxígeno (`o2_1`, `o2_2`) pasa a rojo.
    Mientras la alarma no se ha acusado, el recuadro **parpadea** (1 Hz); al acusar, queda **fijo en
    rojo** hasta que la alarma se cierra. Así se distingue "nueva" de "ya vista" sin depender solo del
    sonido.
  - **Letrero.** La línea `aviso` resume las alarmas activas, por ejemplo `S1 BAJO 18.5 %` o
    `S1 BAJO 18.5 %  S2 ALTO 93.2 %` (máximo 60 letras por `txt_maxl`).
  - **Sonido.** Un solo sonido de alarma para cualquier sensor, por el canal 0 de la pantalla. La Pi lo
    repite cada pocos segundos en vez de dejarlo en bucle en la pantalla: si `g2-ui` falla, el sonido
    se detiene solo y no queda sonando sin control.
  - **Acusar (D-031).** Confirmado por el usuario: un solo botón acusa **ambos sensores** y el sonido
    de la alarma a la vez: silencia el sonido por 2 minutos y deja los recuadros fijos. Una alarma **nueva** (por ejemplo, del otro sensor)
    vuelve a sonar al instante aunque la otra ya estuviera acusada.
  - **Relevos.** El aviso visual y sonoro es por sensor, pero los **relevos de las alarmas de corriente
    alterna son uno por tipo de alarma** (oxígeno bajo y oxígeno alto), no uno por sensor: ver D-033.
  - **Otras alarmas.** La discrepancia entre los dos sensores (`alarma.discrepancia_pct`) y la falla de
    un sensor (sin señal) son alarmas aparte, propias del sistema y no de un sensor.
- **Por qué:** con dos sensores que pueden estar en tuberías o puntos distintos, "el peor de los dos"
  esconde cuál está mal y en qué sentido; la alarma por sensor dice exactamente dónde está el problema.
- **Por probar:** el parpadeo y el sonido repetido con la pantalla real, y que la repetición de
  órdenes desde la Pi no sature el puerto serie.

---

## D-033 — Relevos de alarma: uno por alarma, energizados en normal

- **Fecha:** 2026-10-19
- **Decisiones del usuario:**
  - Se usará la placa de expansión **RPi Relay Board** (Waveshare) de **3 relevos**, con **un relevo
    dedicado a cada alarma**: **relevo 1 = oxígeno bajo** (se activa cuando **cualquiera** de los dos
    sensores está en nivel bajo) y **relevo 2 = oxígeno alto** (cuando cualquiera está en nivel alto).
    Esto reemplaza la idea de "un relevo por sensor" de la primera versión de D-032.
  - Los relevos trabajan **energizados en normal** (a prueba de fallas): la bobina está activa mientras
    todo va bien y se suelta en alarma, de modo que un corte de energía de la placa también avisa.
    El usuario no ve por ahora cómo prevenir un corte de energía con el modo "energizado solo en
    alarma"; una batería recargable queda como plan futuro.
  - El relevo 3 queda **libre**. Propuesta (por confirmar): "equipo sin vigilancia", que se suelta
    cuando `g2-core` no está funcionando (la falla del equipo que ya no tenía relevo).
  - Hay **tres fuentes separadas**: la Raspberry Pi, la pantalla Nextion y los periféricos (entre
    ellos la placa de relevos).
  - Los relevos no dependen del acuse (D-031).
- **Datos de la placa (wiki de Waveshare):** canales CH1, CH2 y CH3 en los pines BCM **26, 20 y 21**
  (físicos 37, 38 y 40); el control es de **nivel bajo** (el relevo se cierra con el pin en bajo); hay
  que dejar puesto el puente `Relay_JMP` para que la Pi los controle; la wiki no publica las
  características de los contactos, el aislamiento ni la protección de las bobinas (a revisar con la
  hoja de datos y el experto; las tiendas indican 5 A).
- **Consecuencia crítica ("energizado en normal" con control de nivel bajo):** el relevo está
  energizado cuando el pin está en **bajo**, y es justo el estado por omisión de los pines 26, 20 y 21
  de la Raspberry Pi (resistencia hacia abajo). Por lo tanto, **mientras la Pi arranca, o si el
  programa se cae y suelta los pines, los relevos podrían quedar energizados, es decir, "todo
  normal", sin que nadie vigile**. Es el sentido peligroso del fallo. Defensas propuestas, en capas
  (todas por verificar en la placa real con un multímetro, apagando y reiniciando la Pi y matando el
  programa):
  1. `gpio=26,20,21=op,dh` en `/boot/firmware/config.txt`: el firmware pone los pines en alto desde
     el arranque (relevos soltados = alarma hasta que `g2-core` tome el control).
  2. `ExecStopPost` del servicio `g2-core` (systemd): al detenerse o caerse el programa, vuelve a
     poner los tres pines en alto.
  3. El watchdog de hardware reinicia la Pi si se cuelga; al reiniciar, vuelve a regir la capa 1.
  4. Si la placa lo permite, resistencias de 10 kΩ de cada entrada a 3.3 V, para que un pin suelto
     o la Pi apagada quede en alto.
  Con esto, los estados sin vigilancia (arranque, caída del programa, cuelgue, Pi apagada) **disparan**
  las alarmas externas; hay que aceptar y avisar que cada reinicio las dispara unos segundos.
- **Diagnóstico: que un reinicio de la Pi no dispare las alarmas (2026-10-19, pedido del usuario;
  pendiente de decisión).** La placa se activa mediante optoacopladores PC817 y sus relés tienen
  contactos NC y NA. Es posible, con un costo:
  - **Opción B (sin hardware nuevo):** si no se agregan las resistencias hacia 3.3 V ni `gpio=…=dh`
    (capas 1 y 4 de arriba), el estado por omisión de los pines 26, 20 y 21 (hacia abajo = nivel bajo
    = LED del optoacoplador encendido) deja los relevos **energizados = normal** durante el
    reinicio. Se verifica mirando los LED CH1 a CH3 de la placa durante un reinicio. Costo: durante
    el reinicio, el cuelgue o la caída del programa **nadie vigila y no se nota**; un cuelgue
    repetido (el watchdog reinicia la Pi cada 15 s) no avisaría nunca. Con solo contactos NC/NA no
    se puede distinguir "reiniciando" de "normal": se necesita memoria en el tiempo.
  - **Opción C (recomendada para evaluar):** como la B, más el **relevo 3 = "equipo fuera de
    servicio" con retardo de unos 2 minutos**: la Pi emite un latido (un pulso por segundo) a un
    temporizador reiniciable externo; si falta más de ~120 s (más que un reinicio normal, ~60 s), el
    relevo 3 se suelta y avisa. Un reinicio normal no dispara nada; un cuelgue repetido o una Pi
    apagada, sí. Implementación: microcontrolador pequeño que mide el latido (preferido: ajustable y
    fiable, pero agrega firmware que certificar) o un temporizador reiniciable discreto (un 555 con
    condensador grande es poco fiable para 2 min). Las tres salidas NC en paralelo dan un "alarma
    general" si el hospital lo pide. El aviso de la plataforma (correo si el equipo deja de reportar)
    cubre además la caída remota.
  - **Opción A (la estricta, capas 1 a 4 de arriba):** cada reinicio y cada caída disparan las
    alarmas externas unos segundos. La más segura, pero con alarmas en cada reinicio planeado.
  - Siempre que se acepte una ventana sin vigilancia, debe acotarse (el retardo), documentarse y
    revisarse con un experto en equipos médicos.
- **Cableado de las alarmas externas:** con relevos energizados en normal, el aparato de alarma va
  conectado al contacto **normalmente cerrado (NC)**: queda cerrado cuando la bobina se suelta (alarma
  o falta de energía). Dimensionar los contactos para la corriente alterna real y revisar con un
  experto antes de conectar (equipo hospitalario, `HARDWARE.md` §7).
- **Fuentes separadas:** la tierra (GND) de las señales de control debe ser común entre la Pi y la
  placa. Si cae la fuente de la placa, los relevos se sueltan (alarma: lo deseado). Si cae la fuente
  de la pantalla, las alarmas de AC siguen, pero la pantalla se apaga: la Pi detecta que no responde
  y lo registra y avisa por la plataforma. Si cae la de la Pi, depende de la capa 4 (por verificar).
- **Pendientes de esta decisión:** confirmar el uso del relevo 3; medir el comportamiento real de la
  placa en arranque y caída; elegir la fuente de 3.3 V de la placa; batería o respaldo de energía.

---

## D-034 — g2-core, primera versión: lectura, alarmas por sensor y almacenamiento

- **Fecha:** 2026-10-21
- **Qué es:** el paquete `src/g2/nucleo/` y su arranque `python3 -m g2.nucleo`. Primera parte del
  servicio `g2-core` (D-005, único escritor de la base). Aún **no** es un servicio de systemd.
- **Módulos:**
  - `senal.py`: `O2 [%] = tensión [mV] / mv_por_pct + offset_pct` (10 mV por % en el Paracube; el
    offset sale de la calibración vigente) y el agregado por intervalo (promedio, mínimo y máximo;
    un hueco queda como hueco, con la marca `sin_datos`; un intervalo con intentos fallidos lleva la
    marca `inestable`).
  - `alarmas.py`: motor de alarmas. Por sensor: oxígeno bajo, oxígeno alto y sensor inválido; del
    sistema: sensores discrepantes. Retardo (`alarma.o2_retardo_s`) e histéresis
    (`alarma.o2_histeresis_pct`) como en D-027; acuse y sonido como en D-031 y D-032; relevos como en
    D-033 (el de bajo con cualquier sensor en bajo, el de alto con cualquiera en alto, sin depender
    del acuse). Todo cambio queda en la tabla `alarma` por medio del `Almacen` (revisiones y cadena de
    auditoría). Al arrancar **retoma** las alarmas que quedaron abiertas, sin duplicarlas y cerrando las
    que ya no corresponden.
  - `fuentes.py`: la fuente de tensiones. `FuenteAds1263` lee los canales `ads1263:N-M` del ADC real;
    ante un error del ADC devuelve "sin señal" (no detiene el programa) y reconfigura el chip si se
    reinició o falla 3 veces seguidas (máximo un intento cada 5 s). `FuenteSimulada` para pruebas.
  - `salidas.py`: interfaz de los relevos y una versión emulada. **La versión de GPIO no se escribe
    todavía**: depende de la decisión de D-033 (estado de los pines al arrancar y al caerse el
    programa).
  - `nucleo.py`: el ciclo (cada 0.5 s): leer, convertir, evaluar, fijar los relevos y, cada
    `muestreo.intervalo_guardado_s` (15 s), guardar un registro por sensor. Entrega
    `estado_pantalla()` (valor, estado, acusada, aviso, sonido, parpadeo y relevos) que usará `g2-ui`.
    El arranque deja la razón `SYS_ARRANQUE` o `SYS_REINICIO_ANORMAL` (si el cierre anterior no fue
    ordenado) y el cierre guarda el intervalo en curso y marca el apagado limpio.
- **Decisiones de diseño tomadas aquí (a confirmar por el usuario):**
  1. La **histéresis de la discrepancia** entre sensores es la mitad de su límite: se abre si la
     diferencia supera `alarma.discrepancia_pct` y se cierra cuando baja de la mitad.
  2. El **sensor inválido** usa el mismo retardo que las alarmas de oxígeno.
  3. **Acusar** acusa todas las alarmas activas, también las del sistema (discrepancia y sensor
     inválido); estas suenan como las demás, pero no activan relevos.
  4. Las lecturas se toman **dos veces por segundo** (parámetro del ciclo, no es clave de
     configuración todavía).
- **Aviso:** el valor por omisión de `alarma.discrepancia_pct` (0.5 %) es muy estrecho para dos sensores
  reales con calibraciones distintas: probablemente la alarma de discrepancia se abrirá a menudo.
  Revisarlo con las mediciones del sensor real.
- **Probado:** 73 pruebas nuevas (209 en total, también en la Raspberry Pi con Python 3.13) y una
  corrida de 24 s con el ADC real y una base de prueba aparte: 31 muestras por sensor cada 15 s,
  alarmas abiertas tras el retardo de 10 s, cierre ordenado. Con las entradas como estaban en ese
  momento (IN0–IN1 ≈ 1.03 V y IN2–IN3 ≈ 9 mV) se abrieron las alarmas de oxígeno alto, de oxígeno bajo y
  de discrepancia, como corresponde.
- **Comparación con el multímetro (2026-10-21):** con el divisor en AIN2–AIN3 el usuario midió **1.030 V** y el
  núcleo guardó **1029.99 mV** (promedio de 31 muestras, sensor 2) y 1030.0 mV (11 muestras): coinciden. El
  usuario nombra las entradas desde 1 (IN1–IN2 = AIN0–AIN1, IN3–IN4 = AIN2–AIN3).
- **Observado:** la **primera muestra** tras arrancar el ADC puede ser transitoria (el sensor 2 marcó
  56.6 % en la primera muestra y luego 0.9 %). Se evaluará descartar las primeras lecturas tras el
  arranque o tras reiniciar el chip.
- **Corrección (2026-10-21, con la prueba real en la Pi):** el valor extremo de una alarma (`valor_pico`) se
  reescribía en la base cada vez que el mínimo o el máximo se movía una milésima: con los sensores casi en cero
  una sola alarma llegó a **191 revisiones**, cada una con su eslabón de auditoría y su entrada en la cola de envío
  (la cola pasó de 1808 registros, 724 de alarmas), con desgaste innecesario de la tarjeta SD. Ahora el extremo
  se lleva al día en memoria y solo se escribe cuando se mueve al menos **0.5 %** (`PICO_MIN_CAMBIO`), y **siempre**
  al cerrar la alarma, al deshabilitar su sensor y al apagar el núcleo (el registro final queda exacto). Medido
  después: en 90 s la cola solo creció con las lecturas (12 registros) y las alarmas abiertas no sumaron
  revisiones. 4 pruebas nuevas.
- **Observación:** mientras no exista `g2-uplink`, la cola de envío solo crece (unos 8 registros por minuto con las
  lecturas, más las alarmas y la auditoría) y por D-014 nada se borra sin confirmación de la plataforma: la base
  crece sin límite hasta que exista el envío. Con 1 h de pruebas pesa unos 700 KB.
- **Pendiente:** servicio de systemd con watchdog por progreso (D-012); relevos por GPIO (D-033);
  `g2-ui` (protocolo de la Nextion y emulador); `g2-uplink` y la cola de envío; registro de salud de
  la Pi; flujos de calibración; que `g2ctl` pida los cambios al núcleo en vez de escribir.

---

## D-035 — Acceso remoto a la Raspberry Pi con ZeroTier

- **Fecha:** 2026-10-21
- **Pedido del usuario:** una IP fija para llegar a la Pi desde fuera de la red local y, más adelante,
  ofrecer soporte técnico. El usuario creó una red privada de ZeroTier y pidió unir la Pi a ella.
- **Qué se hizo:** `zerotier-one` 1.16.2 instalado **desde el repositorio oficial de apt para Debian 13**
  (no con `curl | bash`), con la llave de firma de ZeroTier, Inc. (huella
  `74A5E9C458E1A431F1DA57A71657198823E52A61`) descargada de dos orígenes distintos (el repositorio oficial
  en GitHub y su servidor de descargas) cuyos archivos resultaron idénticos. El servicio queda activo y
  habilitado al arrancar (usa unos 13 MB de memoria). La Pi se unió a la red; al ser **privada**, queda
  pendiente que el usuario autorice el nodo en ZeroTier Central y le asigne una IP administrada.
- **Decisión del usuario sobre SSH:** **conservar el acceso por contraseña** como canal adicional de
  soporte (no desactivarlo), y cambiar la contraseña de fábrica de `pi` al terminar el proyecto. El ID de
  la red y el del nodo se guardan solo en la nota local (el repositorio es público).
- **Riesgos y mitigaciones recomendadas:** mientras la contraseña sea la de fábrica, cualquier miembro
  autorizado de la red podría entrar; por eso solo se autoriza a mano y, hasta el cambio, es una red de
  confianza reducida. Opciones para después: contraseña larga; permitir la contraseña solo desde la
  interfaz de ZeroTier (`Match Address` en `sshd_config`) y exigir llave desde las demás; cortafuegos
  limitando SSH a la red local y a ZeroTier; `fail2ban`. Un acceso remoto a un equipo hospitalario debe
  revisarse con el responsable de seguridad antes de la instalación en campo.
- **Pendiente:** autorizar el nodo y fijar su IP; comprobar el acceso por SSH desde la IP de ZeroTier;
  elegir una de las opciones de refuerzo de arriba.

---

## D-036 — g2-core como servicio de systemd con watchdog por progreso

- **Fecha:** 2026-10-21
- **Qué se hizo:** `systemd/g2-core.service` y `scripts/instalar_servicios.sh` (repetible; `--iniciar`, `--quitar`).
  El servicio es `Type=notify`: avisa "listo" al terminar de arrancar (`src/g2/nucleo/notificacion.py`, sin
  dependencias) y da un **latido solo después de cada paso completo** del ciclo (lectura, alarmas y base).
  Con `WatchdogSec=30`, si el ciclo se atasca (ADC o base de datos), el latido se detiene y systemd lo reinicia
  (watchdog por progreso, D-012).
- **Decisiones de la unidad:** `Restart=always` **sin límite** de reinicios (una vigilancia detenida es peor que
  un reinicio repetido; la escalada a reiniciar la Pi o al modo seguro de D-012 queda pendiente porque depende
  de D-033); `RestartPreventExitStatus=2` (el código 2 es "sin sensores habilitados", un error de configuración);
  no depende de la red; endurecimiento mínimo (`NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict` con
  escritura solo en la carpeta de datos y en `/run/g2`). La validación con `systemd-analyze verify` detectó que
  `StartLimitIntervalSec` va en `[Unit]` y no en `[Service]`.
- **Probado en la Pi (2026-10-21):** el servicio arranca y queda habilitado al encender; con el proceso **congelado
  a propósito** (`SIGSTOP`) systemd lo detectó a los 30 s (`Watchdog timeout`), lo cerró (`ABRT`) y lo reinició
  en unos 4 s; el arranque nuevo quedó con la razón `SYS_REINICIO_ANORMAL`, se retomaron las 2 alarmas abiertas
  sin duplicarlas y la cadena de auditoría siguió íntegra; un reinicio ordenado (`systemctl restart`) queda como
  `SYS_ARRANQUE`. Consumo: unos 24 MB de memoria.
- **Ojo:** mientras corre, el servicio ocupa el ADC; para usar las herramientas de banco hay que detenerlo
  (`sudo systemctl stop g2-core`) y volver a iniciarlo. La base de producción (`~/g2/datos/g2.db`) ya contiene
  datos de estas pruebas (alarmas con el divisor de voltaje); antes de instalar el equipo en campo se recrea.

---

## D-037 — g2-ui: interfaz de la pantalla y su comunicación con el núcleo

- **Fecha:** 2026-10-21
- **Qué es:** el paquete `src/g2/pantalla/` y su arranque `python3 -m g2.pantalla`, servicio `g2-ui`
  (`systemd/g2-ui.service`, también `Type=notify` con watchdog por progreso). Primera etapa: página principal
  completa, navegación a la página de alarmas (solo lectura), Acusar, parpadeo y sonido de alarma.
  **Falta** el teclado numérico con el PIN para editar los ajustes y las páginas config, red, calibración,
  sistema y reportes.
- **Módulos:** `protocolo.py` (códigos de página y control, eventos, órdenes y colores: **única fuente**, usada
  también por la herramienta de banco `tools/banco/pantalla.py`), `vistas.py` (del estado del núcleo a lo que
  muestra cada página, funciones puras), `enlace.py` (puerto serie real y una pantalla emulada para pruebas),
  `datos.py` (lecturas de la base en **solo lectura** y estado de la red) e `interfaz.py` (navegación, pintado
  solo de lo que cambia, parpadeo, sonido y acuse).
- **Comunicación con el núcleo (`src/g2/ipc.py`): archivos en `/run/g2`** (memoria, sin desgastar la SD):
  el núcleo publica `estado.json` cada segundo (de forma atómica) y la interfaz deja las órdenes como archivos en
  `ordenes/`. **Por qué archivos y no un socket:** son fáciles de inspeccionar, se prueban igual en un PC y en la
  Pi, no abren puertos y los protegen los permisos del usuario. La interfaz **nunca escribe en la base** (D-005):
  el núcleo recoge cada orden, la **registra en la tabla `comando`** con su `uuid` (idempotente: reenviarla no la
  ejecuta dos veces) y la ejecuta.
- **Comportamientos acordados en D-031 y D-032, ya implementados:** el recuadro del sensor parpadea a 1 Hz
  (invirtiendo los colores para que el texto se lea en las dos fases) mientras la alarma no se acusa y queda fijo
  en rojo al acusar; la Pi repite el sonido de alarma cada 3 s mientras el núcleo lo pide (si la interfaz se
  detiene, el sonido se detiene solo); Acusar acusa los dos sensores y los relevos no cambian.
- **Si el núcleo se cuelga:** si `estado.json` tiene más de 5 s, la interfaz **no muestra valores viejos como
  actuales**: los recuadros pasan a `SIN SEÑAL`, los valores a `--.-`, el aviso dice `Núcleo sin respuesta` y el
  sonido se detiene; cuando el núcleo vuelve, la pantalla se recupera sola.
- **Probado:** 63 pruebas nuevas con la pantalla emulada (272 en total, también en la Pi) y una prueba de punta a
  punta en la Pi: la pantalla real respondió la versión del protocolo (1), la interfaz cargó la página principal
  y un acuse enviado por la vía de las órdenes se ejecutó en menos de 2.5 s y quedó registrado en `comando`.
- **Detalles del enlace real:** la pantalla es la **NX8048P050_011R**, firmware 293, 123 MB de flash, a 9600 baudios
  (TX de la pantalla en el pin 10 de la Pi y RX en el pin 8). Una orden de cambio de página responde con el
  evento de página cargada. A 9600 baudios un repintado completo de la principal tarda cerca de un segundo; se
  evalúa subir la velocidad (`bauds` en Program.s y en el servicio).
- **Para oír el sonido de alarma** hay que agregar `nextion/sonidos/alarma.wav` al `.HMI` como **segundo audio**
  (id 1); sin él la orden `play 0,1,0` no suena.
- **Pendiente:** el teclado y el PIN (reglas por confirmar: vigencia, intentos y bloqueo), las demás páginas, la
  confirmación con la pantalla real de los toques y del parpadeo, y el estado de la red que hoy solo mira el enlace
  (no comprueba internet) y la cola de envío, que se llenará cuando exista `g2-uplink`.

---

## D-038 — PIN de la pantalla y cambio de ajustes con teclado

- **Fecha:** 2026-10-21
- **Decisiones del usuario:** hay un PIN **de fábrica** (el usuario eligió el valor; **no está en el repositorio**) y otro
  que asigna la plataforma, que reemplaza al de fábrica cuando existe; el PIN **vale 5 minutos** una vez aceptado;
  **3 intentos fallidos** bloquean el teclado **60 s**.
- **Qué protege:** los cambios de ajustes hechos desde la pantalla táctil (hoy los cinco de la página de alarmas;
  después calibración y red). Ver datos, navegar y **Acusar** no piden PIN.
- **Dónde se guarda:** tabla `pin_acceso` (migración **005**, esquema 5) con la **huella** PBKDF2-HMAC-SHA256 (100 000
  iteraciones, sal propia de 16 bytes), nunca el PIN. La tabla **no entra a la cola de envío ni a la cadena de
  auditoría a propósito**: la huella de un PIN de 4 dígitos se recupera probando los 10 000 valores, así que no debe salir
  del equipo. Por eso tampoco se usa la tabla `config` (su historial se sincroniza) y el valor **no puede ir en el código ni
  en el repositorio público**: se aprovisiona en cada equipo por SSH con
  `python3 -m g2.ctl pin-fijar --tipo fabrica --desde-stdin` (el PIN no se pasa como argumento: quedaría en el historial
  del shell y en la lista de procesos). Los cambios de PIN quedan como evento `SEG_PIN_CAMBIADO` **sin el valor**.
- **Quién verifica:** la interfaz (`g2-ui`) compara lo tecleado con la huella leída de la base en solo lectura, de modo
  que el PIN **nunca viaja** (ni por los archivos de `/run/g2` ni por el registro). Al núcleo solo le avisa el **resultado**
  (`pin_resultado`: aceptado, fallido o bloqueado), que el núcleo registra como eventos de seguridad
  (`SEG_PIN_ACEPTADO`, `SEG_PIN_FALLIDO`, `SEG_PIN_BLOQUEADO`) y como comandos auditables.
- **Cómo se cambia un ajuste:** toque en el ajuste → teclado (pide el PIN si no hay uno vigente) → valor → la interfaz lo
  valida con las **mismas reglas del catálogo** que el núcleo (rango y relaciones como mínimo < máximo), con mensajes
  claros → orden `config_fijar` al núcleo → el núcleo la **registra en `comando`**, la valida otra vez, la aplica con
  origen `pantalla` y su historial (queda ligada a su orden) y rige en el siguiente ciclo, sin reiniciar. Si el núcleo la
  rechaza, el motivo queda en el comando y el valor vigente no cambia.
- **Falla cerrada:** si no hay ningún PIN configurado, la pantalla **no permite cambios** y lo dice. Las claves del propio
  PIN (`pantalla.pin_vigencia_s`, `pantalla.pin_intentos`, `pantalla.pin_bloqueo_s`) solo las cambian la plataforma o
  `g2ctl`, **nunca la pantalla** (comprobado con una prueba).
- **Límites conocidos:** (1) los contadores de intentos y el bloqueo viven en memoria: si `g2-ui` se reinicia, se reinician;
  (2) quien pueda **leer la base** podría recuperar un PIN corto de su huella, y quien tenga acceso al sistema
  puede además escribir órdenes: el PIN protege contra una persona frente a la pantalla, no contra un acceso al sistema,
  que se protege con SSH, ZeroTier y los permisos (D-035); (3) la plataforma aún no puede asignar su PIN y la pantalla
  aún no avisa que el de fábrica sigue activo.
- **Probado:** 41 pruebas nuevas (317 en total, también en la Raspberry Pi): formato y verificación del PIN, que el PIN no aparece
  en ningún byte de los archivos de la base ni en la cola, el recorrido completo en la interfaz con la pantalla emulada
  (PIN correcto, incorrecto, bloqueo y su fin, vigencia de 5 minutos, vencimiento mientras se teclea, valores fuera de rango,
  mínimo mayor que el máximo, claves enteras, cancelar y sin PIN configurado) y las órdenes del núcleo.
- **Pendiente:** comando de la plataforma para asignar el PIN; aviso en pantalla de "PIN de fábrica activo"; mostrar en la página
  de Sistema el estado del PIN; persistir el bloqueo si se decide que debe sobrevivir a un reinicio de la interfaz.

---

## D-039 — Páginas de sistema y configuración, salud de la Pi y plan de las demás páginas

- **Fecha:** 2026-10-21
- **Decisiones del usuario sobre las páginas que faltaban:** (1) **WiFi:** debe poder conectarse a **cualquier red
  escribiendo su nombre y contraseña** en la pantalla, con letras mayúsculas y minúsculas, números y caracteres
  especiales → hace falta una página nueva de **teclado alfanumérico** (`texto`, código `09`); (2) **calibración:**
  **ambos métodos**, la guía del SPOC del fabricante y el ajuste de cero por software, y los dos quedan registrados;
  (3) **reportes a USB:** CSV con un archivo de huellas SHA-256; (4) **PIN en todo lo delicado:** la exportación a USB y
  las acciones de Sistema.
- **Plan por etapas** (cada una con su especificación del HMI, para que el usuario construya en el editor mientras se
  implementa el lado de la Pi): **1** `confirmar`, `sistema` y `config` (hecha del lado de la Pi); **2** `reportes`;
  **3** `calibracion`; **4** `texto` y `red`.
- **Etapa 1 — páginas** (especificación en las secciones 9 a 11 de `nextion/ESPECIFICACION_HMI.md`):
  - `confirmar` (PP `08`): pregunta de Sí / No compartida por todas las acciones que interrumpen el servicio.
  - `sistema` (PP `05`): 8 líneas de información (software, protocolo de la pantalla, tiempo encendido, CPU y RAM,
    disco, base y cola, estado de los servicios, qué PIN rige; en rojo si hay alarma) y las acciones **reiniciar servicios**,
    **reiniciar el equipo** y **verificar la auditoría**; todas piden PIN y las dos primeras además confirmación.
  - `config` (PP `02`): intervalo de guardado, intervalo de la pantalla, diferencia máxima entre sensores y encender o
    apagar cada sensor (con PIN; apagar pide confirmación y **nunca se permite apagar el último sensor**).
- **Salud de la Raspberry Pi (`src/g2/nucleo/salud.py`, pendiente desde D-011 y D-013):** cada 10 s se miden la
  temperatura del procesador, uso del procesador, RAM, disco, voltaje (`throttled`), enlace de red, señal WiFi, tamaño
  de la base y tiempo encendido. Se **registra una fila de `salud` al arrancar y cada 30 minutos** y, además, cada vez que
  una causa abre una alarma (con la causa como motivo). Alarmas con retardo de 30 s e histéresis (5 °C, 5 %, 2 % y
  0.5 GB): `ALM_RPI_TEMP_ALTA`, `ALM_RPI_RAM_ALTA`, `ALM_DISCO_ESPACIO_BAJO`, `ALM_DISCO_ESPACIO_CRITICO` (aviso si
  queda menos del 20 % o 2 GB; crítico menos del 10 % o 1 GB) y `ALM_RPI_BAJO_VOLTAJE`. Son alarmas **del sistema**:
  salen en el aviso de la pantalla pero **no suenan ni activan relevos** (D-033). Lo que no se pudo medir queda
  nulo, nunca un cero inventado. Probado con datos reales de la Pi (46 °C, 36 % de RAM, 7.8 GB libres, `0x0`).
- **Órdenes nuevas del núcleo** (siempre registradas en `comando`, idempotentes por `uuid`): `sensor_habilitar`,
  `sistema_accion` y `auditoria_resultado`; migración **006** con los eventos `SYS_REINICIO_PEDIDO`,
  `SEG_AUDITORIA_VERIFICADA` y `SEG_AUDITORIA_ALTERADA`. Las acciones del sistema salen de una **lista cerrada**
  (reiniciar servicios y reiniciar equipo): nada de lo que llegue en una orden se ejecuta como comando.
- **Cómo reinicia el núcleo sin `sudo`:** los servicios corren con `NoNewPrivileges`, que bloquea `sudo`, y es una
  protección que se quiere conservar. En su lugar, la regla de polkit `systemd/50-g2.rules` (la instala
  `scripts/instalar_servicios.sh`) permite al usuario `pi` **solo** reiniciar `g2-core.service` y `g2-ui.service` y reiniciar
  el equipo (no apagarlo ni tocar otras unidades).
- **Defecto encontrado y corregido en la prueba real:** el comando `systemctl` lo lanza el propio núcleo y vive en su
  grupo de procesos, así que cuando systemd reinicia al núcleo **mata también al comando antes de que alcance a reiniciar
  la interfaz**. Ahora se encolan ambos con `--no-block` y el núcleo va **último**; comprobado: cambian los dos PID.
- **Verificar la auditoría:** la hace la interfaz **en segundo plano** (puede tardar y crece con la base) con su
  conexión de solo lectura y avisa el resultado al núcleo, que lo deja como evento (`SEG_AUDITORIA_VERIFICADA` o
  `SEG_AUDITORIA_ALTERADA`, severidad 4). Si no se puede verificar, **nunca se dice que está bien**.
- **Verificado por el usuario en la pantalla real (2026-10-21):** el PIN de la pantalla funciona: un intento fallido, el
  PIN aceptado y varios ajustes cambiados desde el teclado quedaron aplicados y registrados con origen `pantalla`
  (D-038). Los umbrales de alarma quedaron con valores de prueba (mínimo 15 %, máximo 95 %, retardo 15 s, acuse 180 s);
  **restaurar los valores de fábrica (20 %, 92 %, 10 s, 120 s) antes de usar el equipo.**
- **Probado:** 374 pruebas (también en la Pi): 57 nuevas de interfaz (sistema, config, confirmar, PIN reutilizado) y 30 de
  salud y órdenes del núcleo.
- **Pendiente:** el usuario construye `confirmar`, `sistema` y `config` en el `.HMI`; después las etapas 2, 3 y 4. La
  página de sistema muestra el botón de reportes, que por ahora dice "próxima etapa".

---

## D-040 — Configuración de la red desde la pantalla y la plataforma

- **Fecha:** 2026-10-21
- **Requisito del usuario:** (1) poder configurar la red **también desde la plataforma**, estando el equipo conectado por
  Ethernet o por una red temporal: se ingresan las credenciales, se acepta, el equipo cambia a la red nueva, queda sin red
  un momento y se reconecta; (2) se necesita el **teclado completo en la pantalla** porque, en una **primera instalación,
  el equipo no tiene credenciales** y necesita una primera configuración de red.
- **Prioridad:** la red pasó a ser la etapa siguiente (antes de reportes y calibración), por ser lo primero que necesita un
  equipo nuevo en campo.
- **Cambio de red con reversión automática (`src/g2/red/gestor.py`):** usa NetworkManager por medio de `nmcli`. Un equipo
  que queda sin red por una contraseña mal escrita es inalcanzable, así que **nunca se borra la red que funciona antes de
  comprobar la nueva**: se anota la red activa y si tenía internet, se crea un perfil **nuevo** y se activa, se comprueba que
  la red nueva llega a internet **por su propia interfaz** (con `SO_BINDTODEVICE`: si hay un cable, este no debe tapar el
  fallo del WiFi), y si todo va bien se queda con la nueva (prioridad 10 sobre las anteriores, que siguen guardadas como
  respaldo; se conservan a lo sumo 4 perfiles creados por G2). Si falla (contraseña incorrecta, red no encontrada, tiempo
  agotado o sin internet cuando antes sí había) **borra el perfil nuevo, vuelve a la red anterior y dice por qué falló**.
  **Primer uso:** si antes no había internet (equipo nuevo), una red que conecta pero no sale a internet **se acepta y se
  avisa**, porque es mejor que ninguna.
- **Qué redes admite:** WPA/WPA2 personal (contraseña de 8 a 63 caracteres o 64 hexadecimales), redes **abiertas** (contraseña
  vacía) y redes **ocultas**. **No** admite todavía redes empresariales (802.1X) ni portales cautivos (que piden aceptar una
  página).
- **El núcleo no se bloquea:** el cambio puede tardar uno o dos minutos, así que lo ejecuta un **hilo propio**
  (`src/g2/nucleo/servicio_red.py`) que también mide la red cada 10 s y busca redes cada 30 s; el ciclo del núcleo sigue
  midiendo, alarmando y dando su latido. El hilo **nunca escribe en la base**: deja el resultado y el núcleo lo registra
  (comando `ok` o `error` y los eventos `RED_CAMBIO_SOLICITADO`, `RED_CAMBIO_OK`, `RED_CAMBIO_FALLIDO`; migración 007).
  Órdenes nuevas: `red_configurar` y `red_buscar`; solo se hace un cambio a la vez.
- **La contraseña no deja rastro (comprobado con pruebas):** se **redacta** (`***`) antes de guardar el comando, que se sincroniza
  con la plataforma y entra a la cadena de auditoría; los eventos solo llevan el nombre de la red; el archivo de la orden va en
  `/run/g2` (memoria) con permisos **0600** y el núcleo lo **borra al recogerlo**; nunca sale en el registro de actividad ni
  en una orden a la pantalla mientras está oculta; no aparece en ningún byte de los archivos de la base. La guarda NetworkManager
  en su perfil (solo root puede leerlo). Límite conocido: viaja como argumento de `nmcli` unos milisegundos, visible solo
  para quien ya tenga acceso a la Pi.
- **Desde la pantalla (primera instalación):** si no hay red, la barra principal dice **"Sin red: toque Red para conectarse"**. La
  página `red` muestra la conexión (tipo, nombre, IP, señal, internet y ZeroTier), las 4 redes cercanas de mejor señal y el
  resultado; **tocar una red cercana** salta el nombre y, si es abierta, también la contraseña. **Conectar a otra red**:
  PIN → nombre → contraseña → confirmación → orden. La página `texto` es un **teclado completo**: 40 teclas de caracteres que
  cambian por **capas** (`abc`, `ABC` y `#+=`, con los 32 símbolos ASCII, la `ñ` y los números), espacio, borrar, limpiar y **Ocultar /
  Ver** (la contraseña **se ve** al escribirla; ver D-042). Nombre hasta 32 caracteres y contraseña hasta 63. La pantalla sigue "tonta": la
  Pi reescribe las etiquetas y traduce cada toque, por eso el evento lleva la **posición** de la tecla y no el carácter.
- **Desde la plataforma:** se usa **la misma orden** `red_configurar` (con origen `plataforma`) cuando exista `g2-uplink`; el
  resultado queda en `comando` y se enviará al volver la conexión por la cola de envío. **Pendiente:** el transporte seguro de esa
  orden (TLS y órdenes firmadas, plan de seguridad D-022): una contraseña de red no puede viajar sin eso; y qué hace la plataforma
  si el equipo no confirma tras el cambio (la reversión local protege al equipo).
- **Permisos:** la regla de polkit `systemd/50-g2.rules` se amplió con las acciones de NetworkManager necesarias (buscar redes y
  crear, modificar y activar perfiles; no apagar el WiFi). **Comprobado en la Pi** desde un proceso sin sesión (el caso del
  servicio): escaneó las redes y creó y borró un perfil de prueba sin activarlo.
- **Velocidad del puerto serie:** `g2-ui` ahora **detecta sola** la velocidad (prueba 115200 y luego 9600), porque el teclado de texto
  repinta 40 teclas al cambiar de capa y a 9600 baudios tarda más de un segundo; se recomienda `bauds=115200` en *Program.s* del
  `.HMI`. Una pantalla a cualquiera de las dos velocidades funciona.
- **Probado:** 461 pruebas (también en la Pi): 27 del gestor con un `nmcli` falso (cambio correcto, contraseña incorrecta, red
  inexistente, sin internet con y sin internet previo, primer uso, cable y WiFi, red abierta y oculta, poda de perfiles, que la contraseña no
  salga en el registro), 20 del servicio y las órdenes (con que no haya rastro de la contraseña en la base) y 60 de la interfaz
  (escribir a mano, elegir de la lista, redes abiertas, ver y ocultar, límites de largo, cancelar, progreso y resultado).
- **Pendiente:** (1) el usuario construye las páginas `red` y `texto` (especificación, secciones 12 y 13); (2) **la prueba real de
  la reversión en la Pi** (apaga la red de 20 a 60 s: con un cable Ethernet conectado no hay interrupción); (3) comprobar en la
  pantalla las teclas `"` y `\`, que se escapan en el `txt`; (4) la parte de la plataforma; (5) redes empresariales y portales cautivos.

---

## D-041 — La pantalla se reinicia al sonar con volumen alto

- **Fecha:** 2026-10-21
- **Qué se vio:** con una alarma sonando (la Pi ordena `play 0,1,0` cada 3 s), el registro de `g2-ui` mostraba que **la pantalla
  se encendía sola cada 3 segundos** (20 veces en 6 minutos): se reiniciaba cada vez que sonaba. Era grave: en una alarma real
  la pantalla habría quedado ilegible justo cuando más se necesita.
- **Cómo se aisló:** (1) al silenciar el sonido (un acuse) los reinicios se detuvieron; (2) con `g2-ui` detenido y la herramienta de
  banco, `play 1,0,0` (pitido corto) no reiniciaba, pero `play 0,0,0`, `play 0,1,0` y `play 1,1,0` sí (la pantalla emite su secuencia de
  arranque `00 00 00` y `88`); (3) con `volume=10`, `20`, `40`, `50` y `60` el sonido de alarma **no** reinicia (tres pasadas cada uno),
  y con **70** sí. **Causa:** el volumen de **70** que se recomendó en la especificación (`volume=70` en *Program.s*) hace que el
  altavoz consuma más de lo que aguanta la fuente de la pantalla, que se reinicia por caída de tensión. Hay que revisar la fuente de
  la pantalla (corriente disponible) antes de instalar el equipo.
- **Corrección de raíz:** el volumen lo **fija la Pi**, no el `.HMI`: `g2-ui` envía `volume=N` al arrancar y **cada vez que la pantalla
  enciende** (el `.HMI` vuelve a poner el suyo en cada arranque y la Pi lo corrige antes de que suene), con N de la clave
  `pantalla.volumen` (**50** por omisión; solo la plataforma o `g2ctl` la cambian). La especificación pasa a `volume=50` y avisa que
  no se suba de 60.
- **Protección:** si la pantalla se reinicia dentro de los 4 s siguientes a un sonido, la interfaz **baja el volumen 20 puntos** (mínimo 10)
  y lo registra como error; si ocurre 3 veces en un minuto, **desactiva el sonido de alarma 10 minutos**. La alarma visual (el recuadro
  rojo y el aviso) y los **relevos no dependen del sonido** y siguen igual.
- **Comprobado en la pantalla real:** con el sonido sonando cada 3 s, 0 reinicios en 40 s; y tras un **arranque en frío** (`rest`),
  donde el `.HMI` vuelve a poner su volumen, 0 reinicios en 30 s con la alarma sonando. 12 pruebas nuevas de la interfaz (473 en total,
  también en la Pi).
- **Pendiente:** cambiar `volume=70` por `volume=50` en *Program.s* del `.HMI`; medir la corriente real que entrega la fuente de la pantalla
  con el altavoz sonando; decidir si el volumen se puede ajustar desde la página de configuración.

---

## D-042 — Contraseña visible, sonido en cada tecla y transporte seguro de la contraseña

- **Fecha:** 2026-10-22
- **Contraseña visible (corrige D-040):** la contraseña de la red **se ve mientras se escribe**; `Ocultar` la cambia a asteriscos y `Ver`
  la vuelve a mostrar. **Por qué:** una clave de hasta 63 caracteres con mayúsculas, números y símbolos se equivoca con facilidad y,
  tecleada mal, el equipo prueba la red, falla y vuelve a la anterior: se pierden uno o dos minutos y, en un equipo nuevo sin red, no
  hay forma de saber qué falló. El riesgo de que alguien la vea por encima del hombro es menor que ese y se controla con `Ocultar`.
  Mientras está oculta, la clave sigue sin enviarse a la pantalla (prueba incluida). El campo `valor` sigue enmascarado en el registro
  de órdenes de la interfaz.
- **Sonido en cada tecla:** la especificación (sección 13) exige `play 1,0,0` en *Touch Press* de **las 40 teclas y de todos los botones**
  de `texto`, y avisa de ponerlo en `t_00` antes de copiarla. **Por qué en la pantalla y no desde la Pi:** suena en el instante del toque,
  sin pasar por el puerto serie, de modo que confirma que **el toque se registró** aunque la letra tarde en aparecer (a 9600 baudios
  repintar el campo puede tardar); si lo ordenara la Pi, un sonido tardío o ausente no distinguiría entre «no se pulsó» y «la Pi
  está ocupada».
- **Qué ya protege a la contraseña dentro del equipo (D-040):** redactada antes de guardar el comando, ausente de eventos, auditoría,
  base y registro; archivo de la orden en memoria (`/run/g2`, 0600) borrado al leerlo; NetworkManager la guarda solo para root.
  **Límites que quedan:** el cable serie pantalla-Pi está dentro de la caja; la clave viaja unos milisegundos como argumento de
  `nmcli`; y si está visible, quien mire la pantalla la ve.
- **Qué falta para que viaje segura desde la plataforma** (la clave sale del navegador de quien administra, pasa por el servidor y llega
  al equipo; hoy **no existe** ese camino y no debe abrirse sin estos puntos). Ordenados por importancia:
  1. **TLS con certificado válido y verificado** en todo el trayecto (navegador-servidor y equipo-servidor); nada de `verify=False`
     (el sistema anterior lo usaba). El equipo **siempre inicia** la conexión (consulta u MQTT): no se abre ningún puerto en la Pi.
  2. **Autenticación individual del equipo**: un secreto por equipo, guardado con hash en la plataforma (D-022, etapa 3), nunca el
     token global.
  3. **Órdenes firmadas por la plataforma** (Ed25519: la plataforma firma, el equipo solo guarda la clave pública, así que robar un
     equipo no permite firmar órdenes). La firma cubre el identificador del equipo, el `uuid` de la orden, la fecha de emisión, una
     **caducidad corta** (p. ej. 10 minutos) y los parámetros. El equipo rechaza lo caducado, lo ajeno, lo repetido (el `uuid` ya es
     idempotente) y lo mal firmado. Sin esto, quien obtenga el canal podría mandar al equipo a una red falsa.
  4. **Autorización en la plataforma**: solo un usuario con el rol adecuado y sobre sus propios equipos puede ordenar un cambio de red;
     queda quién, cuándo y desde dónde (el nombre de la red sí se registra; la clave no).
  5. **La plataforma no debe conservar ni registrar la clave en claro**: sin guardarla en la base (o solo cifrada y borrada al
     confirmar el equipo), sin que aparezca en los registros de peticiones ni en el cuerpo de los errores, nunca en la URL, formulario
     con `autocomplete="off"`, y que el resultado que vuelve al equipo no la repita.
  6. **Cifrado de extremo a extremo del campo de la clave** (recomendado, segunda etapa): el equipo genera un par X25519 al
     aprovisionarse y registra su clave pública; el navegador o la plataforma cifra la clave de la red con ella (cifrado de sobre con
     AES-GCM) y solo el equipo puede descifrarla, de modo que ni un proxy que termine el TLS, ni el servidor, ni sus registros la ven en
     claro. Ya está disponible sin instalar nada: la Pi tiene `cryptography` 43 (X25519, Ed25519, AES-GCM) y Node trae `crypto`.
  7. **Resultado confiable aunque se corte la red**: el cambio deja al equipo sin conexión unos instantes; el resultado se guarda
     en `comando` y se envía por la cola de envío al volver (D-040). La plataforma muestra «pendiente» y un plazo; la reversión local
     protege al equipo si la red nueva falla.
  8. **Reloj**: la caducidad exige hora correcta; la Pi sincroniza por NTP (comprobado), pero un equipo nuevo sin red puede tener la
     hora mal, por eso la comprobación de caducidad se acompaña de un contador creciente por equipo.
- **Recomendación:** etapa A = puntos 1-5 junto con el resto del plan D-022 (el mínimo para abrir el camino); etapa B = punto 6. Hasta
  entonces la red se cambia **solo desde la pantalla**, que es segura.
- **Pendiente:** confirmar la etapa A/B con el usuario; el diseño del mensaje firmado; cómo se aprovisionan las claves en la fábrica.

---

## D-043 — Gráfica en tiempo de las dos señales

- **Fecha:** 2026-10-26
- **Qué se pidió:** una gráfica de amplitud contra tiempo de las dos señales que aparezca sola cuando la pantalla lleva 10 s sin tocarse y
  que un toque sobre ella devuelva a la pantalla principal.
- **Diagnóstico (factible, bajo riesgo):** el componente *Waveform* de Nextion trae 4 canales con valores de 0 a 255 y ancho de 700
  píxeles = 700 puntos por canal. Cálculo del enlace serie (10 bits por byte): un punto nuevo (`add`, 2 canales) son ~28 bytes (29 ms a
  9600 baudios); redibujar todo con puntos sueltos son 19,6 KB (**20 s** a 9600, 1,7 s a 115200, descartado); con carga en bloque
  (`addt`) son 1,4 KB (~1,5 s a 9600, 0,12 s a 115200). Resolución vertical de 256 niveles: con eje fijo de 0 a 100 % cada nivel valdría
  0,39 % y el ruido normal no se vería, así que el eje es **automático**. Ventana: 700 puntos a 1 por segundo = ~12 min.
- **Decisiones del usuario:** (1) la gráfica solo se abre desde `principal`; (2) si salta una alarma con la gráfica abierta, vuelve a `principal`
  (se propuso: solo si está sin acusar); (3) un sensor sin señal deja un hueco; (4) se recomienda 115200 baudios.
- **Cómo funciona (todo en la Pi; la pantalla sigue "tonta"):** `src/g2/pantalla/grafica.py` guarda las últimas 700 muestras de cada sensor,
  calcula el eje (ancho mínimo de 5 % O2, números redondos, holgura de 10 %; se reescala enseguida si un valor se sale y solo se reduce
  pasados 30 s para que la curva no salte) y genera las órdenes: `cle s0.id,255`, `addt s0.id,CANAL,N` (más los N bytes cuando la pantalla
  responde `FE FF FF FF`; ella confirma con `FD FF FF FF`) y `add s0.id,CANAL,VALOR` para cada punto nuevo. Canales: 0 sensor 1, 1 sensor 2,
  2 límite bajo y 3 límite alto de alarma (solo se dibujan si caen dentro del eje). **Sin dato = nivel 0** (la línea baja al borde inferior;
  los valores válidos usan 1 a 255, así que no se confunden): el *Waveform* no sabe dejar un hueco, y esto es lo más parecido.
- **Cuándo se abre y se cierra** (`interfaz.py`): `g2-ui` ordena `sendxy=1` al arrancar y en cada encendido, con lo que la pantalla avisa de
  **cualquier** toque (`67 xx xx yy yy S`), no solo de los botones; sin tocar nada en el `.HMI`. Pasados `pantalla.grafica_espera_s` (10 s, 0 la
  desactiva; clave nueva, editable por plataforma y localmente) sin toques, y solo con `principal` abierta, con el núcleo respondiendo y sin
  alarmas **sin acusar**, ordena `page grafica`. Un toque (el *Hotspot* `salir`, a pantalla completa) ordena `page principal`. Con la gráfica abierta, si
  salta una alarma sin acusar o el núcleo deja de responder, vuelve sola a `principal` **de inmediato** (el aviso rojo no puede quedar tapado; el
  sonido y los relevos nunca dependen de la gráfica). Se toma una muestra por segundo **siempre**, para que al abrirla ya haya historia.
- **Protecciones:** mientras un `addt` recibe sus bytes, ninguna otra orden sale (se guardan y se envían al terminar: mezclarlas corrompería los
  datos); eso puede retrasar hasta ~2 s el regreso por alarma a 9600 baudios. Si la pantalla no responde al `addt` en 4 s, se deja de usar y la
  gráfica se dibuja con `add`. Si el `.tft` no tiene la página `grafica` (responde «página inexistente»), se registra un error **una vez** y la gráfica
  queda desactivada hasta que la pantalla se reinicie; así una pantalla con el `.tft` anterior no sufre.
- **Probado:** 50 pruebas nuevas (523 en total): escala, niveles, límites, eventos del protocolo, la vista y 24 de la interfaz con la pantalla emulada
  (cuándo se abre y cuándo no, cómo se cierra, alarma con la gráfica abierta, dibujo con `addt`, transferencia interrumpida, `add` de respaldo,
  página inexistente). Un defecto encontrado por las pruebas: el seguro contra pedir la página dos veces retrasaba también el regreso por
  alarma; corregido.
- **Pendiente (con la pantalla real):** construir la página `grafica` en el `.HMI` (especificación, sección 15); comprobar que `sendxy=1` informa
  de los toques sobre componentes y zonas vacías, que `addt` funciona en este modelo y la dirección (`dir`) del *Waveform*; poner `bauds=115200`
  en *Program.s*. Una mejora futura: sembrar la gráfica con los promedios de 15 s de la base al arrancar `g2-ui`, para no empezar vacía tras un reinicio.

---

## D-044 — Reportes en PDF cifrado a memoria USB

- **Fecha:** 2026-10-27
- **Qué se pidió:** exportar las lecturas en **PDF** con el número de registro de la base, la fecha y la hora de cada lectura y la lectura
  de los dos sensores; los datos con alerta, **en rojo y negrita** con los parámetros de ese momento; el PDF debe **abrirse con una
  contraseña que es el nombre del dispositivo**.
- **Decisiones del usuario:** (1) la discrepancia entre sensores **no** se marca; (2) filtro por **fechas** (días completos, sin horas) y un
  botón para imprimir **el día de hoy**; (3) **máximo una semana** por reporte, para no exigir demasiado a la Raspberry Pi; (4) la memoria
  USB debe **llamarse igual que el equipo** (un seguro más); (5) se respeta el **intervalo de guardado** que haya en la base en cada
  momento (si se cambió, el reporte lo refleja) y se usa la fecha y hora guardadas con cada dato; (6) el nombre del equipo tiene el formato
  `ANZD-600226001` (ANZ analizador, D duplex, número del código de entrega); mientras no se defina el real se usó uno temporal
  (`ANZD-000000001` en esta Pi); (7) primero los reportes y después la calibración.
- **Hallazgos en los datos reales (antes de diseñar):** la base guarda **una fila por sensor** en cada intervalo y sus horas difieren
  de 1 a 47 ms (solo 304 de 8 704 coinciden exactas), así que el reporte **empareja por cercanía** (menos de la mitad del intervalo de
  la fila), no por igualdad ni por un intervalo fijo de 15 s. `lectura.periodo_ms` es el tiempo real transcurrido (a veces 15,4 s), por
  eso el resumen muestra el intervalo dominante.
- **Medidas en la Raspberry Pi 3 B+:** dibujar con `reportlab` directamente sobre el lienzo (sin armar tablas): 5 760 filas = 105 páginas en 3 s;
  50 000 filas = 910 páginas en 27 s, 49 MB de memoria. Cifrar con `pypdf` AES-256 un PDF de 728 páginas: 3 s. Una semana a 15 s son
  ~40 000 filas (~730 páginas) y tarda ~25 s. Con 6 291 filas reales: 113 páginas en 10,9 s.
- **Cifrado:** `reportlab` solo cifra con RC4 (obsoleto) salvo que tenga `pyaes` (AES en Python puro, lento). Se dibuja con `reportlab` y se cifra
  después con `pypdf` + `cryptography` (ya instalada): **AES-256**. Contraseña para abrir = nombre del equipo; contraseña de propietario
  aleatoria y descartada (se puede ver, imprimir y copiar el texto; no editar: ver «Ajustes 2» abajo). Tras cifrar se comprueba que abre con la contraseña y que **no** abre
  sin ella. El PDF sin cifrar vive solo en una carpeta temporal privada y se borra. **Límite honesto:** el nombre del equipo también se ve en la
  pantalla `config`, así que esto protege contra una apertura casual, no es un secreto fuerte; por eso el nombre del archivo no lo lleva
  (`G2_reporte_AAAA-MM-DD_a_AAAA-MM-DD_AAAAMMDD-HHMM.pdf`). Si el equipo no tiene nombre, **no se genera**.
- **Qué marca como alerta:** una lectura es alerta si **durante su intervalo** hubo una alarma de oxígeno BAJO o ALTO de ese sensor
  (`alarma.inicio_ms` .. `fin_ms`). El umbral que se imprime es `alarma.umbral`, el que tenía al dispararse, no el de hoy (que puede haber
  cambiado). En rojo y negrita: número de registro, fecha, hora, descripción de la alerta y la lectura del sensor en alerta (la del otro, no).
- **Contenido:** hoja de resumen (equipo, ID, rango, intervalo de guardado, estadísticas por sensor, alertas, calibraciones vigentes y
  **estado de la cadena de auditoría** al generarlo: si está alterada lo dice en rojo, pero igual genera el reporte), tabla de lecturas con
  `Página X de Y` (se conoce el total antes de dibujar), y al final las alarmas de oxígeno del rango. Lecturas con calidad
  no normal llevan `*`; las de hora sin sincronizar, `†`; un sensor sin lectura, `—`. Zona horaria: clave `reporte.zona_horaria`
  (**`America/Bogota`**, Colombia, UTC-5 todo el año; ver «Ajustes del 2026-10-27»).
- **Cómo corre (D-005 intacto):** el reporte lo hace un **proceso aparte** (`python3 -m g2.reportes`, prioridad baja `nice 15`) que lanza
  `g2-core` (`nucleo/servicio_reportes.py`): los hilos de Python comparten el GIL y dibujar cientos de páginas le quitaría tiempo a la lectura de
  los sensores y al latido del watchdog. El proceso lee la base en solo lectura y toma de ella el nombre del equipo (la contraseña **nunca** viaja
  por la línea de comandos); informa su avance con líneas JSON. El núcleo es el único que escribe: al terminar registra el evento
  `REPORTE_GENERADO` (con la huella SHA-256 del archivo), `REPORTE_FALLIDO` o `REPORTE_CANCELADO` (migración 008) y cierra el comando. Solo un
  reporte a la vez, máximo 15 min y se mata al cerrar el núcleo. Las órdenes son `reporte_generar` (desde, hasta) y `reporte_cancelar`.
- **Límites:** `MAX_DIAS = 7` y `MAX_FILAS = 60 000` (si el intervalo de guardado se bajara a 1 s, una semana serían 600 000 filas: se rechaza
  antes de armar nada). Fechas futuras, rango invertido y fechas inexistentes se rechazan en la pantalla **y** en el núcleo.
- **Memoria USB:** `reportes/usb.py` (todo lo del sistema pasa por un ejecutor que se sustituye en las pruebas). Solo cuenta el transporte `usb`;
  **hallazgo en la Pi real: la tarjeta SD (`bootfs`, `rootfs`) se declara «extraíble» y salía como memoria USB** (se vio al probar la orden de
  verdad), por eso no se usa `rm` ni `hotplug`, nunca se escribe en un volumen montado en el sistema, y el nombre se compara sin distinguir
  mayúsculas. Se monta con `udisks2` (si ya estaba montada se usa donde está y no se desmonta), se copia con un nombre temporal y se renombra al
  final, se **lee de vuelta y se compara la huella**, nunca sobrescribe (`_2`, `_3`), deja `nombre.pdf.sha256` al lado y se desmonta. Si el nombre
  no coincide se para **antes** de dibujar. **Ojo: una memoria FAT/FAT32 no admite más de 11 letras en su nombre;** `ANZD-600226001` tiene 14, así que
  la memoria hay que formatearla como **exFAT o NTFS** y llamarla igual que el equipo.
- **Pantalla (`reportes`, PP 07, sección 16 de la especificación):** dos campos de fecha (`v_desde`, `v_hasta`) que abren el teclado numérico en modo
  fecha (8 dígitos, la Pi pone las barras; no pide PIN), `b_hoy`, `b_generar` (pide el PIN; pasa a `Cancelar` mientras corre), línea de registros del
  rango, línea de estado de la USB, barra y texto de avance y resultado con los primeros 12 caracteres de la huella. Se comprueba todo lo que la
  pantalla puede comprobar (nombre, rango, USB) **antes** de pedir el PIN.
- **Para que funcione en la Pi (hay que correr con `sudo`):** `scripts/instalar_servicios.sh --iniciar` (instala `python3-reportlab` y `python3-pypdf`,
  la regla de polkit que permite montar y desmontar la USB con udisks2 y la unidad de `g2-core` con `ReadWritePaths` para `/media` y
  `/run/media`). Mientras tanto, en esta Pi, `pypdf` está instalado con `pip --user` para poder probar.
- **Probado:** 89 pruebas nuevas (618 en total): rango y zona horaria, emparejado con intervalos distintos, alertas con el umbral de su momento,
  rojo/negrita fila por fila, PDF que abre solo con el nombre del equipo, USB (nombre, SD, FAT, copia, huella, espacio, sin sobrescribir), trabajo completo,
  cancelación sin dejar nada, cadena alterada, servicio del núcleo y sus órdenes, y la página. En la Pi real: reporte de 6 291 filas (113 páginas)
  en 10,9 s y la orden completa a través de `g2-core` (que encontró el error de la tarjeta SD).
- **Hallazgos con la primera USB real (NTFS, 2026-10-27):** (1) `lsblk -J -o PATH,...` entrega una **lista plana** y la partición pierde el
  transporte `usb` de su disco, así que **ninguna USB se reconocía** (las pruebas usaban un árbol inventado y no lo vieron); ahora se pide `NAME`
  primero (árbol) y hay pruebas con la salida real. (2) Una USB sin formato reconocible ya no dice «Inserte la memoria», dice «La USB no
  tiene un formato legible (use exFAT o NTFS)». (3) El escritorio de la Pi **monta solo** la memoria (`ntfs3`, `/media/pi/<nombre>`): se usa
  donde está y no se desmonta. (4) `g2-core` corre con `ProtectSystem=strict`: **si la unidad instalada no trae `-/media -/run/media` en
  `ReadWritePaths`, la USB se ve de solo lectura** y la copia falla con «Read-only file system» (comprobado: el reporte se dibuja y cifra, y falla
  al copiar). (5) Tampoco estaba instalada la regla de polkit de `udisks2` (`udisksctl mount` por SSH: «Not authorized»). Ambas cosas se
  corrigen reinstalando con `sudo ./scripts/instalar_servicios.sh --iniciar`.
- **Ajustes del 2026-10-27 (a pedido del usuario):** (1) el reporte usa la **zona horaria de Colombia** (`America/Bogota`): es el valor por
  defecto de `reporte.zona_horaria` y el de respaldo en `g2-ui` y en el proceso del reporte; en esta Pi se fijó con `g2ctl config-fijar`
  (antes quedó en `America/El_Salvador`, por eso las horas de las primeras pruebas salían una hora antes). Los días completos del filtro y
  las horas del PDF siguen esa zona. (2) Se **quitó la zona horaria del encabezado** de las páginas (decía `(America/...)` junto a «Generado»).
  (3) Se **quitó del final del reporte la sección «Cambios de configuración en el rango»** (y su consulta a `config_historial`, que ya no se
  usa); el anexo queda solo con las alarmas de oxígeno. El historial de cambios sigue en la base y en la cadena de auditoría. 631 pruebas.
- **Ajustes 2 del 2026-10-29 (a pedido del usuario), hechos y comprobados uno por uno:** (1) se quitó **«Software»** (la versión es información
  interna del equipo); (2) se quitaron las líneas **«Sensor N (modelo, serie)»** del resumen: quedan solo las estadísticas, con la etiqueta
  «Sensor 1» y «Sensor 2»; (3) el PDF ahora **permite copiar el texto** (permisos `EXTRACT` y `EXTRACT_TEXT_AND_GRAPHICS` además de imprimir;
  sigue sin permitir editar; comprobado con MuPDF y pypdf: copiar sí, imprimir sí, editar no; cada fila se extrae completa y en orden, y «—» y
  «†» salen bien); (4) **logo de SPEAL** (`src/g2/reportes/recursos/speal.png`, el **mismo `nextion/imagenes/logo.png` de la pantalla**: el óvalo amarillo) de 22 pt de alto, a la
  derecha de la **cabecera de la primera página** solamente (el nombre del equipo se corre a su izquierda; las demás páginas no cambian); si el archivo faltara, el reporte sale igual sin él. Probado con datos reales en la
  Pi. 633 pruebas. **Contraste con lo dicho antes:** la protección ya no impide copiar; solo impide editar el archivo.
- **Estado de los sensores en el reporte (2026-10-29):** el anexo ahora tiene dos secciones, **«Alarmas de oxígeno»** y **«Estado de los
  sensores»** (título de la página: «Alarmas y estado de los sensores»). La segunda explica las celdas con «—»: cuándo se **apagó** o **encendió**
  un sensor (eventos `SEN_DESHABILITADO` / `SEN_HABILITADO`, que ya guardaba la base) y cuándo estuvo **sin señal** (alarma `ALM_SENSOR_INVALIDO`, con
  su hora de fin o «sigue sin señal»). La base agrupa en un solo evento los que se repiten en menos de `evento.agrupar_s` (60 s); el reporte
  lo dice como «Apagado (2 veces; la última hh:mm:ss)». La primera página suma el renglón «Estado de sensores: N cambios». Consulta nueva
  `consulta.leer_cambios_sensor`; sin migración. Comprobado con los datos reales del 27/10 en la Pi (apagados y encendidos de los dos sensores). 636 pruebas.
- **Umbrales de alarma restaurados (2026-10-29):** en la Pi seguían con valores de prueba (15 %, 95 %, 15 s, acuse 500 s). Se fijaron con
  `g2ctl config-fijar` a los de fábrica (**20 %, 92 %, 10 s, 120 s**, origen `local`, actor `claude-restauracion`; la histéresis ya era 0,5). El
  núcleo los tomó sin reiniciar. Con el oxígeno real alrededor de 93,7 % la alarma de **ALTO** ahora se activa (antes no, con 95 %).
  **Revisar:** `muestreo.intervalo_guardado_s` está en **300 s** en la Pi (fijado desde la pantalla el 27/10; el valor de fábrica es 15 s): no se
  tocó, pero los reportes salen con una fila cada 5 minutos.
- **Velocidad de la pantalla:** la interfaz sigue hablando a **9600 baudios** porque el `.HMI` aún no tiene `bauds=115200` en *Program.s*; no es un fallo
  (la detección automática prueba 115200 y cae a 9600). Pendiente del usuario al construir el HMI; recomendado por la gráfica y el teclado.
- **Pendiente:** construir la página `reportes` en el `.HMI` (sección 16) y probar con una memoria USB exFAT real; instalar con `sudo` (arriba);
  definir el nombre real del equipo; confirmar la zona horaria; probar un reporte de una semana en la Pi real.

---

## D-045 — Pantalla bloqueada mientras se genera un reporte (y mientras se calibre)

- **Fecha:** 2026-10-27
- **Qué se pidió:** que la pantalla quede **inhabilitada** mientras se genera el reporte USB (y, en la calibración, mientras dure) para que
  nada lo interrumpa y se eviten errores de manipulación.
- **Decisión:** mientras el núcleo genera un reporte la pantalla **no atiende ningún toque**: no se puede salir de `reportes`, cambiar las
  fechas, pedir otro reporte ni cancelar. **Se quitó el botón `Cancelar`** de la pantalla (la orden `reporte_cancelar` sigue existiendo en el
  núcleo para uso técnico con `g2ctl`). La duración es corta (una semana ≈ 30 s) y el núcleo corta cualquier reporte a los 15 min.
- **Cómo (dos barreras):** (1) la Pi **descarta** los toques (`_toque`); (2) la Pi le ordena a la pantalla `tsw 255,0` (deshabilita el toque
  de todos los componentes de la página). Una página recién cargada trae los toques habilitados, así que la orden se **repite en cada carga**
  de página y se devuelve (`tsw 255,1`) al terminar. Los botones se ven apagados, `b_generar` dice `Generando...` y `res` dice
  `No toque la pantalla ni retire la memoria USB` (naranja). **No hay componentes nuevos en el `.HMI`.**
- **El bloqueo se deduce del estado del núcleo**, no es un interruptor que alguien pueda dejar puesto: si el núcleo deja de responder, o se
  reinicia `g2-ui`, o se corta la luz, la pantalla **se libera sola**. Cubre también el instante entre aceptar el PIN y que el núcleo marque
  el reporte «en curso» (hasta 6 s). Si `g2-ui` arranca con un reporte en curso, lleva la pantalla a `reportes` y la bloquea.
- **Efectos que hay que conocer:** durante esos ~30 s no se puede acusar una alarma con la pantalla (el sonido y los relevos siguen; el
  acuse se puede hacer al terminar). Un reporte tiene tope de 15 min, por eso el bloqueo nunca es indefinido.
- **Para la calibración:** se usará **el mismo mecanismo** (`_pantalla_bloqueada()`, `tsw 255,0` y descarte de toques) con el aviso
  «Calibrando» en pantalla; allí el bloqueo ya estaba pedido junto con la suspensión de alarmas y relevos (ver pendientes).
- **Probado:** 627 pruebas (6 nuevas): toques ignorados, `tsw` una sola vez y repetido al recargar, liberación al terminar y cuando el núcleo
  no responde, bloqueo antes de que el núcleo responda y reinicio de la interfaz con un reporte en curso. **Falta probarlo en la pantalla
  real** (que `tsw 255,0` apague de verdad el toque en el NX8048P050).

---

## D-046 — g2-uplink: envío de datos a la plataforma (etapa 1)

- **Fecha:** 2026-10-29
- **Decisiones del usuario:** (1) transporte **HTTPS por lotes** (no MQTT); (2) esta entrega es **solo el lado del equipo + el contrato** para la plataforma + una
  plataforma simulada para probar (no se tocó el repositorio de la plataforma); (3) **sin órdenes remotas** todavía (etapa 2).
- **Diagnóstico que lo motivó:** la plataforma actual (`iot-elsalvador`) solo recibe `POST /api/v1/data` con `{tipo_dato, valor}`: no tiene dónde confirmar la cola
  de G2 registro por registro (D-008) ni un canal de órdenes. En la Pi había **20.903 registros pendientes** desde el 21/10 (18.167 lecturas, 1.317 de auditoría,
  852 alarmas…) y no se pueden depurar hasta que se confirmen. `g2-core` es el único escritor (D-005), así que `g2-uplink` no puede marcar la cola por su cuenta.
- **Qué hace (`src/g2/uplink/`, unidad `systemd/g2-uplink.service`):**
  - **Lotes durables:** toma de `cola_envio` los pendientes (hasta `plataforma.lote_max`, 500), arma cada mensaje desde su fila (`mensajes.py`; con atraso salen
    primero alarmas y eventos y al final las lecturas; un registro con varias revisiones viaja **una vez**, con su contenido de hoy y la `rev` más alta), lo
    envía con `POST /api/g2/v1/lotes` y la plataforma contesta **por registro** `ok` / `rechazado` / `reintentar`. Solo `ok` confirma.
  - **En vivo:** cada `plataforma.intervalo_visualizacion_s` (15 s) manda la foto del valor actual (`/api/g2/v1/vivo`; no se guarda ni se reintenta), porque la
    base guarda cada 5 minutos (hoy) y el panel web no debe esperar tanto. Dice `nucleo_ok: false` si `g2-core` no responde (**lo que más importa alertar**) y no lleva
    el nombre de la red WiFi ni las IP.
  - **Quién anota:** al terminar un envío pide a `g2-core` la orden **`cola_resultado`** (confirmados / rechazados / fallidos + estado del enlace). **No es un
    comando**: no se guarda en `comando` (si se guardara, cada envío dejaría un registro que a su vez hay que enviar, sin fin; comprobado que no deja ninguno).
    `Almacen.cola_resultado` solo toca entradas pendientes o enviadas (repetir el aviso no cambia nada): confirmado → depurable; rechazado → queda con su motivo y
    deja **un** evento `NET_ENVIO_RECHAZADO`; fallido → +1 intento y espera 30 s, 60 s… hasta 10 min.
  - **Enlace:** `PLAT_ENLACE_PERDIDO` / `PLAT_ENLACE_RESTABLECIDO` / `PLAT_CREDENCIAL_RECHAZADA` (migración **009**), solo cuando el estado **cambia** (se repite el
    aviso cada 10 min mientras esté mal, por si el núcleo se reinició). Sin red: esperas de 5 s hasta 5 min; credencial rechazada: no insiste 5 min, pero un secreto
    corregido se prueba al instante; `413`: achica el lote a la mitad (mínimo 10) y no vuelve a crecer solo (volvería a fallar en cada ciclo) hasta que alguien
    cambie `plataforma.lote_max`; `Retry-After` se respeta (tope 1 h). **Un registro solo se rechaza si la plataforma lo dice**: un 4xx general se trata como error de
    protocolo y se reintenta.
  - **Si `g2-core` no responde** (estado de más de 30 s) **no se envían lotes** (no habría quién anotara el resultado y se reenviaría lo mismo sin parar); la foto en
    vivo sigue y lo dice.
- **Seguridad (D-042):** solo `https` con el certificado verificado (`http` únicamente hacia `127.0.0.1`, para la plataforma simulada); no se siguen redirecciones (un
  servidor desviado no recibe el secreto); el secreto va solo en `Authorization`, nunca en la URL, el cuerpo, la base ni el repositorio, y el `repr` del cliente y los
  mensajes de error no lo muestran. Se guarda en `~/g2/secretos/plataforma.secreto` (carpeta 0700, archivo 0600; el servicio **se niega a leerlo si otros usuarios
  pueden leerlo**) con `g2ctl plataforma-credencial` (se pide sin mostrarlo, o `--desde-stdin`). Un secreto por equipo (la plataforma guarda su hash).
- **Apagado por omisión:** `plataforma.activa = 0`. No envía nada hasta que, al instalar, se cumplan **tres cosas**: `equipo.id` (el identificador ante la plataforma; hoy
  vacío en la Pi), el secreto guardado y `plataforma.activa = 1`. `g2ctl plataforma-estado` dice cuál falta; el servicio publica su estado en `/run/g2/uplink.json`
  (`desactivada`, `sin_equipo_id`, `sin_credencial`, `url_invalida`, `ok`, `sin_enlace`, `credencial_rechazada`…). Las claves nuevas de configuración (`plataforma.activa`,
  `.url`, `.intervalo_envio_s`, `.lote_max`) solo se pueden cambiar localmente (la URL y el interruptor) o también desde la plataforma (los tiempos).
- **Un defecto que encontraron las pruebas:** `auditoria_cadena` usa `seq` como clave y no `id`; sin corregirlo, sus 1.317 entradas pendientes habrían quedado sin poderse enviar.
- **Contrato para la plataforma:** [CONTRATO_PLATAFORMA.md](CONTRATO_PLATAFORMA.md) (autenticación, los dos endpoints, columnas de cada tabla, qué verificar antes de
  aceptar un equipo en producción). La plataforma simulada (`python3 -m g2.uplink.simulada`) cumple lo mínimo y sirve para probar el equipo sin tocar la real.
- **Probado:** 704 pruebas (68 nuevas, también en la Pi con Python 3.13): mensajes, credencial, cliente (códigos, secreto, redirecciones, compresión, resultados mal
  formados), cola, núcleo, el servicio con cliente falso (esperas, estados, foto en vivo) y de punta a punta con HTTP real contra la plataforma simulada. **Prueba en la Pi con
  una copia de la base real** (nunca con la viva): los 20.927 pendientes se enviaron y confirmaron en **46 s** (42 lotes, 1 MB comprimido; 19.954 registros distintos al
  agrupar revisiones), sin comandos de contabilidad. La cola real quedó intacta (20.922 pendientes) y el proceso real arranca y se detiene bien con la base viva (desactivado).
- **Para ponerlo en marcha (usuario):** (1) `sudo ./scripts/instalar_servicios.sh --iniciar` (instala la unidad y la regla de polkit, crea `~/g2/secretos`); (2) la
  plataforma debe implementar el contrato y dar de alta el equipo; (3) `python3 -m g2.ctl config-fijar equipo.id <id>`, `python3 -m g2.ctl plataforma-credencial`,
  `python3 -m g2.ctl config-fijar plataforma.activa 1`; (4) `python3 -m g2.ctl plataforma-estado`.
- **Descartar la cola (2026-10-29):** `g2ctl cola-descartar` marca como `rechazado` lo pendiente (por omisión sin `--confirmar` solo lo muestra); no borra, porque la base lo
  prohíbe (D-010). Se usó una vez para los 21.028 registros de prueba; el descarte deja un evento y esas dos entradas nuevas sí se enviarán. Los registros descartados
  nunca llegan a la plataforma ni se depuran. Una alarma que siga abierta y se actualice después sí enviará su revisión nueva: la plataforma debe aceptarla aunque no tenga la anterior.
- **Pendiente:** etapa 2 (órdenes firmadas Ed25519, caducidad, `GET /api/g2/v1/ordenes`, cifrado del campo de contraseñas); mostrar el estado del enlace en la pantalla (hoy la principal solo dice `COLA n`); el aviso `NET_COLA_ACUMULADA` cuando la cola crece sin parar; implementar el contrato
  en la plataforma y probarlo con MySQL.

---

## D-047 — g2-uplink vigila a g2-core (vigilancia cruzada, D-012)

- **Fecha:** 2026-10-29
- **Qué se hizo:** `src/g2/uplink/supervisor.py` (`SupervisorNucleo`) y `src/g2/supervision.py`. Si el estado de g2-core falta o tiene más de 30 s durante
  **120 s seguidos** (cuatro veces su watchdog), g2-uplink pide `systemctl restart g2-core.service` (sin sudo: la regla de polkit ya permitía solo `restart`).
  Es la segunda red de seguridad: systemd ya reinicia al núcleo si deja de dar su latido; esto cubre lo que ese watchdog no ve (núcleo "vivo" que no publica su estado).
- **Límites:** al menos 300 s entre intentos y a lo sumo **3 por hora**; agotados, deja de insistir y lo dice (`/run/g2/uplink.json`, `g2ctl plataforma-estado`).
  Cada intento cuenta aunque falle. Razón: reiniciar sin fin no arregla lo que un reinicio no arregla y estorba a quien mide el oxígeno.
- **Independiente de la plataforma:** corre aunque `plataforma.activa` esté apagada. `--sin-vigilar` lo desactiva para pruebas a mano.
- **Registro:** g2-uplink no escribe en la base (D-009); deja la nota `/run/g2/reinicio_nucleo.json` antes de pedir el reinicio y g2-core la lee al arrancar
  (`Nucleo.iniciar(aviso_reinicio)`): el arranque queda con la razón `SVC_BLOQUEO_DETECTADO` y un evento con los segundos sin respuesta. Una nota de más de
  10 minutos o ilegible se ignora; si el reinicio falla, la nota se borra. Sin migración.
- **Probado:** 45 pruebas nuevas (también en la Pi, 749 en total). En la Pi, con la nota puesta a mano y `systemctl restart g2-core` sin sudo: el arranque 43 quedó
  `SVC_BLOQUEO_DETECTADO` con su evento. **No probado:** el ciclo completo con un núcleo congelado de verdad, porque el watchdog de systemd (30 s) lo reinicia
  mucho antes de los 120 s; solo se verá si ese watchdog falla.
- **Pendiente:** la escalada a reiniciar la Raspberry Pi cuando se agoten los reinicios (depende de D-033), y avisar a la plataforma del agotamiento en la foto en vivo.

---

## D-048 — Calibración de cero en aire (desde la pantalla y `g2ctl`)

- **Fecha:** 2026-10-29
- **Estado:** primera etapa, **ampliada por D-049 (2026-10-30)**: el usuario necesita calibrar con gas patrón en un punto bajo (0,0 %) y uno alto
  (98,0 %, 99,8 % u otro), no solo el cero en aire. La orden `calibrar_aire`, la referencia fija de 20,9 % y la página con un botón por sensor de
  esta decisión ya no existen; lo demás (bloqueo de la pantalla, suspensión del sensor, eventos, reglas de rechazo) sigue igual.
- **Contexto:** el Paracube analógico no se calibra por comando (D-001): la corrección es del equipo. El modelo ya era `O₂ = mV / 10 + cero`
  (`senal.tension_a_pct`) y la tabla `calibracion` ya existía (tipo `offset_cero`, vigente única por sensor). No había ninguna calibración
  registrada: se usa la de fábrica. Los dos sensores medían igual en la línea (~90,08 y ~90,09 % de promedio en 24 h).
- **Decisiones del usuario:** (1) **solo cero en aire** (20,9 %) por ahora; el segundo punto con gas de referencia (ganancia) queda para
  después sin romper nada (exigirá migración); (2) **un sensor a la vez**; (3) **bloqueo total** de la pantalla, como en reportes (D-045), sin
  botón Cancelar; (4) límites: estable = variación ≤ **0,3 %** durante **30 s**, cero = promedio de esos 30 s, corrección máxima **±3 %**,
  tope de **5 min**, con PIN y confirmación.
- **Cómo funciona (`src/g2/nucleo/calibracion.py` y `Nucleo`):** el núcleo recibe la orden `calibrar_aire` (`sensor_id`) y, cada medio segundo,
  pasa la tensión del sensor a una máquina de estados pura que desliza una ventana de 30 s hasta que es estable. El cero sale de la **tensión**
  (`20,9 − mV/10`), no de la lectura ya corregida: calibrar dos veces seguidas no acumula. Si pasa de ±3 % (casi siempre: el sensor seguía
  en la línea) o no se estabiliza, **falla y no se aplica**; el fallo queda en `calibracion` (`resultado = 'fallo'`, `vigente = 0`, con lo medido).
  Si sale bien se guarda vigente (`gas_pct` 20,9, `gas_certificado` «aire ambiente», `mv_antes` medido, `comando_id`, `notas`) y rige de
  inmediato. Eventos: `CAL_INICIADA`, `CAL_REGISTRADA`, `CAL_FALLIDA`, `CAL_CANCELADA` (migración 010 agrega los dos que faltaban).
- **Seguridad durante la calibración:** el sensor calibrado **sale de la vigilancia** (sus alarmas se cierran y suspenden; al volver se
  evalúan de nuevo) y sus muestras **no entran al promedio**: el intervalo se corta al empezar y al terminar y el tramo queda como hueco
  con la marca `en_spoc` (`calidad` 4) y `sin_datos` (32). **Se rechaza** si ya hay otra calibración o un reporte, si el sensor está apagado,
  o si **no quedaría otro sensor vigilando** (misma idea que no apagar el último sensor): el otro conserva alarmas, relevos y sonido.
  No se puede apagar el sensor que se calibra. Al cerrar el núcleo con una calibración en curso se cancela y queda registrado.
- **Pantalla:** `principal.b_calib` abre la página `calibracion` (PP 04; especificación en la sección 17 del HMI, **por construir en el `.HMI`**).
  Tocar un sensor pide PIN y confirmación; luego la pantalla se bloquea con el mismo mecanismo que reportes (`tsw 255,0`, toques descartados,
  se libera sola si el núcleo no responde), muestra la variación y el tiempo, y suena la voz «Calibrando» (`play 0,2,0`) cada pocos segundos
  (una alarma del otro sensor tiene prioridad). El recuadro del sensor dice `CALIBRANDO` en azul. `g2ctl calibrar-aire ID` y
  `calibrar-cancelar` dejan la orden para uso técnico (el sensor debe estar al aire).
- **Probado:** 797 pruebas (también en la Pi): la máquina de estados (incluida una bajada de 90 % a 20,9 % con constante de 8 s, que mide ya
  estable), el ciclo completo con base real, rechazos, la página con PIN, bloqueo, sonido y resultado. **No probado todavía** con un sensor
  físico ni con la pantalla real (que `tsw 255,0` apague el toque; que el `.HMI` traiga la página y el audio 2). Se desplegó en la Pi
  (migración 010, servicios activos); no se hizo una calibración real para no dejar un fallo de prueba en la base viva.
- **Pendiente:** construir la página en el `.HMI`; probar con aire real cuánto tarda en estabilizarse el Paracube al sacarlo de ~90 % (el tope
  de 5 min puede quedarse corto); el segundo punto con gas de referencia; el método SPOC guiado (solo se registra); calibrar desde la plataforma
  (orden firmada, etapa 2 de D-046).

---

## D-049 — Calibración por puntos con gas patrón (bajo y alto)

- **Fecha:** 2026-10-30
- **Qué pasó:** D-048 solo calibraba el cero con aire a 20,9 %. El usuario aclaró que el procedimiento real usa **gas patrón**: un punto **bajo** (0,0 %)
  y uno **alto** de valor variable (98,0 %, 99,8 % u otros según el gas disponible). El malentendido fue mío: asumí el aire como referencia y presenté el
  segundo punto como una mejora posterior; el usuario aceptó «solo cero en aire» sobre esa base.
- **Decisiones del usuario:** (1) **cada punto por separado**, en cualquier orden (no una sesión de dos puntos obligatoria); (2) del gas solo se anota
  **el valor en %**; (3) límites: ganancia de **0,90 a 1,10**, puntos separados por **al menos 50 puntos**, estable = variación ≤ 0,3 % durante 30 s,
  tope de 5 min por punto; el cero sigue limitado a **±3 %**.
- **Modelo:** `O₂ = ganancia × (mV / mv_por_pct) + cero` (`senal.tension_a_pct`). Un punto con referencia menor de 50 % es el **bajo** (fija el cero) y de 50 % o
  más el **alto** (fija la ganancia). La calibración vigente se compone con el último punto de cada lado (el otro se conserva de la fila vigente anterior):
  con los dos, `ganancia = (R_alto − R_bajo)/(x_alto − x_bajo)` y `cero = R_bajo − ganancia·x_bajo`; solo el bajo: ganancia 1 y cero `R_bajo − x_bajo` (como D-048); solo
  el alto: cero 0 y ganancia `R_alto/x_alto`. Siempre se parte de la **tensión** medida (`x`), nunca de la lectura ya corregida, así que repetir no acumula. El aire
  (20,9 %) vale como punto bajo. Un fallo no se aplica y queda registrado con lo medido.
- **Datos (migración 011, generada por `tools/generar_migracion_011.py`):** `calibracion` gana `ganancia`, `bajo_ref_pct`, `bajo_mv`, `alto_ref_pct`, `alto_mv` y el tipo
  `puntos`; la fila guarda los dos puntos con los que se calculó la recta y `gas_pct`/`mv_antes` el punto medido en esa acción. Las columnas nuevas entran en la huella de
  auditoría (disparadores y vista regenerados; las calibraciones anteriores se re-sellan). SQLite no deja cambiar un `CHECK` con `ALTER TABLE`: el tipo nuevo se agrega con
  `writable_schema` y `PRAGMA writable_schema = RESET` (necesario para que SQLite relea el esquema antes de agregar las columnas; con ese orden fallaba con «near ','»), y
  una verificación dentro de la migración la aborta si el cambio no se aplicó. Requiere SQLite 3.33 o más (la Pi trae 3.46). Probada con una copia de la base real en la Pi
  (versión 10 → 11, integridad y cadena de auditoría correctas). Contrato con la plataforma actualizado (`CONTRATO_PLATAFORMA.md`): columnas nuevas y valor `puntos`.
- **Órdenes:** `calibrar_punto` (`sensor_id`, `referencia_pct` de 0 a 100) reemplaza a `calibrar_aire`; `calibrar_cancelar` sigue. `g2ctl calibrar-punto ID REF`. Se rechaza igual
  que antes (otra calibración, reporte en curso, sensor apagado, sin otro sensor vigilando) y además si la concentración no es un número entre 0 y 100.
- **Pantalla:** la página `calibracion` se rehízo (sección 17 del HMI): `v_s1`/`v_s2` eligen el sensor, `b_bajo` (0,0 %), `b_aire` (20,9 %) y `v_gas` (teclado numérico, con punto
  decimal) eligen el gas, `i1` dice si es punto bajo o alto, `i2` la calibración vigente, `b_iniciar` pide PIN y confirmación (con el sensor y el gas en la pregunta). Elegir no pide PIN.
  Controles `01` a `07` (`protocolo.CONTROLES[0x04]`). `res` pasa a 80 letras. Los mensajes del núcleo para la pantalla son cortos (`ResultadoCalibracion.breve`) y los detallados
  van al registro. El reporte PDF muestra ganancia, cero y los dos gases de la calibración vigente.
- **Probado:** 828 pruebas (también la migración, con datos). **Desplegado el 2026-10-30** (copia previa de la base en `/home/pi/g2/respaldos/g2_antes_de_011_*.db`, esquema 11, cadena
  de auditoría correcta). El despliegue se retrasó un día porque el usuario probaba la versión anterior; al construir el `.HMI` nuevo y tocar `v_gas` no pasaba nada porque la Pi aún traía la
  tabla de controles vieja (la página 04 solo conocía `01` a `03`: `v_gas` llegaba como `control?05`, y `b_bajo` (`03`) se leía como `b_volver`). **Lección:** un cambio del protocolo
  del `.HMI` exige desplegar la Pi en el mismo momento en que el usuario carga el `.tft` nuevo.
- **Las calibraciones de cero en aire de D-048 se conservan como punto bajo:** la migración copia `gas_pct` y `mv_antes` de las filas `offset_cero` correctas a `bajo_ref_pct` y `bajo_mv`.
  La corrección vigente no cambia (ganancia 1, mismo cero), y al medir después un punto alto se compone con ese punto (aire 20,9 % + 98,0 % distan 77 puntos). Ese día ya había dos
  calibraciones reales en aire vigentes (S1 +0,04 %, S2 +0,10 %: los sensores marcaban 20,86 y 20,80 % en aire) y tres intentos fallidos con el gas de 98 % puesto, hechos con la versión anterior.
- **Otros cambios del día:** `ipc._escribir_atomico` reintenta unos milisegundos si Windows tiene ocupado el archivo (el `PermissionError` esporádico en las pruebas de desarrollo; en
  Linux no cambia nada) y una prueba de reportes usaba el 30/10/2026 como «fecha futura» (ya no lo es).
- **Pendiente:** probar con un sensor real cuánto tarda en estabilizarse con un gas nuevo (el tope de 5 min puede quedarse corto); método SPOC guiado (solo se registra); calibrar
  desde la plataforma (orden firmada, etapa 2 de D-046); decidir si hace falta registrar el certificado del gas (hoy solo el valor).

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
- Incorporar el medidor INA219 (corriente y tensión), cuando haya pruebas
  (D-011).
- Reloj de tiempo real y política de marcas de tiempo sin hora confiable
  (el esquema ya guarda lo necesario para corregir las horas).
- Comandos remotos autenticados, con confirmación y auditoría.
- Lógica de alarmas local (histéresis, tiempo mínimo, acuse, estado seguro de
  salidas).
- Protocolo con la pantalla Nextion, versionado.
- Gestión de WiFi (NetworkManager).
- Sistema de archivos de solo lectura y partición de datos.
- Actualización remota firmada con vuelta atrás.
- Relevos (D-033): ya se decidieron placa de 3 relevos, uno por alarma (bajo y alto) y energizados en
  normal. Falta: confirmar el relevo 3 ("equipo sin vigilancia"), **medir en la placa real** el estado
  de los relevos al arrancar, apagar y matar el programa (las 4 capas de defensa de D-033),
  definir los dimensionamientos para AC con un experto, la fuente de 3.3 V de la placa y el respaldo
  de energía; y elegir los modelos de los demás periféricos (D-023, `HARDWARE.md`).
- Pantalla Nextion: escribir la especificación del `.HMI` (páginas, componentes, ids y eventos),
  el protocolo versionado, el emulador de la pantalla y la carga del `.tft` desde la Pi (D-029).
- PIN de la pantalla: confirmar la interpretación (PIN por defecto y PIN de la plataforma) y
  definir las claves y el comando para asignarlo desde la plataforma (D-029).
- Reportes a memoria USB: formato, contenido, rango de fechas y huella del archivo (D-029).

### Tareas pendientes de hardware y operación

Anotadas el 2026-10-09 a pedido del usuario (sugerencias hechas durante las pruebas del ADC).

- **Lógica de alarmas con dos sensores:** decidir si cada sensor alarma por separado o por el
  peor de los dos (el usuario la está revisando). Bloquea el motor de alarmas de `g2-core`.
- **Consulta a Hummingbird:** forma recomendada de conectar P3 (0 V analógico) a un ADC
  externo, impedancia de salida del sensor y si admite un capacitor en la salida.
- **Medir con el sensor de oxígeno real:** ruido, frecuencia de corte del filtro (método de D-025),
  lectura diferencial P2–P3 y límite de la tensión de entrada con el sobrerrango negativo. El
  sensor 01117707500032 del usuario tiene el LED en rojo fijo (falla): reparar o reemplazar.
- **Referencia de tensión calibrada (mejora opcional):** validar la exactitud absoluta del ADC y
  corregir su error de ganancia (≈ −0.09 % frente al multímetro, D-025).
- **Anotar la serie de la etiqueta de cada sensor** (`g2ctl sensor-serie`) y dar de alta los
  periféricos cuando el usuario entregue las referencias.
- **Base de datos definitiva:** moverla de `~/g2/datos` a `/var/lib/g2`, con usuario de servicio y
  permisos restringidos.
- **Raspberry Pi:** reservar su IP en el router (o usar `raspberry.local`); cambiar la contraseña
  de `pi` al terminar el proyecto (el usuario quiere conservar el acceso por contraseña como canal de
  soporte, ver D-035);
  escritorio (`lightdm`) cuando el equipo
  funcione bien.
