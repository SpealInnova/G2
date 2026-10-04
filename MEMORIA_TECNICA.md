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
  Debian Trixie.
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

## Decisiones pendientes

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
- Sensores periféricos (temperatura, humedad, presión, vibración): modelos
  concretos y su conexión.
