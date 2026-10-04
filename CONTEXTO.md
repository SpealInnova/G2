# G2 — Contexto de la nueva versión de analizadores de oxígeno

Este archivo resume lo aprendido con el equipo **ANZD-600226001** (proyecto
"Refact Analizador") para usarlo como base de **G2**, la nueva versión.
Está pensado para retomar el trabajo sin repetir el diagnóstico. Las
credenciales (token de la plataforma, contraseñas de MySQL) **no** están aquí:
se encuentran en el código del equipo actual, en `Main.py`, `truncate.py` y
`config_red.py`, y deben moverse a configuración protegida en G2.

---

## 1. Qué es el equipo

- **Analizador de oxígeno dúplex** (2 sensores de O₂), instalado en campo
  (Oxioriente, Colombia). Identificador: `ANZD-600226001`.
- **Hardware:** Raspberry Pi (Debian/Raspberry Pi OS, `hostname` =
  `ANZD-600226001`), pantalla **Nextion NX8048P050_011R** (serie Intelligent,
  5", 800×480, con altavoz sin buzzer), 2 sensores **Hummingbird Paracube
  Modus** (oxígeno paramagnético, digital, UART 19200 baud, ASCII), sensor de
  temperatura/humedad **DHT22** (GPIO4, pin 7), barómetro **BMP085** (I²C,
  falla de forma persistente), adaptadores **USB-serie PL2303** para los
  sensores, relé/electroválvula, LED, buzzer, salidas GPIO por sensor.
- **Conectividad:** Ethernet con IP fija (tabla `config_red` de la base de
  datos local) y WiFi gestionada por el sistema operativo (no por el código).
  Acceso remoto por SSH a través de **ZeroTier** (red `speal`).

## 2. Arquitectura actual del firmware (y sus problemas)

Tres procesos independientes que comparten recursos sin coordinación real:

| Proceso | Servicio | Qué hace |
|---|---|---|
| `Main.py` | `SpealA.service` | Lectura de sensores (hilo), pantalla (`work()`, bucle de ~2 s nominal), base de datos local (`conn_mysql()`, cada 15 s), alarmas, envío a la plataforma, estado de la Raspberry (hilo cada 60 s) |
| `Serialnextion.py` | `SpealB.service` | Escucha los eventos de la pantalla y lanza scripts auxiliares con `os.system` |
| `Calib_sensor_dig.py`, `Alarmas_Analizadores.py`, `truncate.py`, `config_red.py`, `log_alarmas.py`, `stop.py` | lanzados por `SpealB` | Scripts efímeros, uno por pantalla o acción |

**Problemas de arquitectura detectados (base del rediseño):**
- Varios procesos abren el mismo puerto serie o los mismos puertos de sensor
  (errores "multiple access", procesos colgados, cruces de puertos).
- Comunicación entre procesos mediante archivos de bandera en `/tmp` y
  archivos de texto (`max.txt`, `min.txt`, `Alarmas.txt`, `ip.txt`).
- Un mismo hilo mezcla refresco de pantalla, lectura de DHT22/BMP y envío HTTP
  a la plataforma; el ciclo puede durar desde 2 s hasta más de 200 s.
- El DHT22 se lee desde dos hilos sin bloqueo (protocolo de un solo cable,
  sensible a tiempos): sin `Lock`, las lecturas se corrompen.
- Errores silenciados: `obtener_dht22()` traga los `RuntimeError` sin registrar
  nada, así que un DHT22 desconectado no aparecía en ningún log.
- `work()` usa `global` implícito y variables sin validar (ej. `O2_sensor_1`
  puede ser número en todos los caminos, sin `None`).
- Concatenación de SQL con strings (riesgo de inyección y de errores de
  formato) en `conn_mysql()`.
- `requests.post(..., verify=False)` deshabilita la validación TLS.
- Sin reintento ni cola local: si falla la red, la muestra se descarta
  en silencio (solo un `print`).
- Sin pruebas automatizadas; cada cambio se verificó manualmente en campo.
- Muchos respaldos `.bak_*` dispersos en la carpeta del código, sin control de
  versiones.

## 3. Sensores de oxígeno (Paracube Modus, manual 01120001A)

**Comunicación:** UART 19200 baud, línea ASCII cada ~200 ms con el valor
(`"20.9"`, 0.1% de resolución). Comandos terminan en `\r`.

**Identidad de fábrica:** comando `!` devuelve `!XXXXXYYYZZZZZZZ`. Los sensores
de este equipo: `01121703250064` (Sensor 1) y `01121703250065` (Sensor 2).
La identidad permite saber qué sensor es, sin depender del puerto USB.

**Comandos útiles (Tabla 6 del manual):**
- `!` identidad · `!F` firmware · `!P` compensación de presión (1 = activa)
- `!D` datos de calibración: 4 líneas (punto vigente y respaldo de fábrica)
- `!Ln.n` calibración baja con gas n% · `!Hn.n` calibración alta
- `!Sn.n` SPOC (un punto, desplaza el cero) · `!R` restaura calibración de fábrica
- Caution 7 del manual: **no mezclar SPOC y calibración de dos puntos**;
  si se mezclan, `!R` antes de la calibración de dos puntos.

**Banderas de estado** (Tabla 4 y 5): posición fija en la línea de salida:
pos. 6 = **B** (comando incorrecto / solicitud de calibración inválida),
pos. 7 = **C** (puntos de calibración a menos de 20% de separación, o
compensación de presión cambiada sin recalibrar), pos. 8 = **E** (fuera de
especificación, señal inestable, posible contaminación del puerto).
Sin número: **S** = calibrando (≤4 s), **X** = falla grave.

**Rango de operación:** 0–100% O₂, con sobrerrango de −15% a +200% (§3.1).
Los valores −15.0 y 200.0 son **topes de saturación**, no corrupción de datos.

**Especificación (§3.1):** error intrínseco, linealidad, repetibilidad y ruido
de ±0.2% O₂ cada uno; deriva de cero <±0.4% en 24 h, <±0.2% por semana
adicional y <±0.2% por mes.

**Tiempo de respuesta (§3.1):** a 250 mL/min, 18 s (16–21%) y 20 s (aire→100%);
a 500 mL/min, 11 s y 13 s. Lo que determina el tiempo es el **flujo** y el
tamaño del salto, no si el valor está cerca de un límite.

**Requisitos de calibración (§5.1, §5.2):** gas certificado a 0.1% de exactitud,
flujo constante por la entrada (≥250 mL/min), 30 s de espera entre
concentraciones. Dos puntos con ≥20% de separación (no necesariamente
nitrógeno: aire 20.9% y un gas alto sirven).

**Interpretación de `!D` (inferencia, NO documentada por el fabricante):**
la segunda columna parece ser la señal interna cruda; la primera, el gas del
punto; columnas 3 y 4, temperatura (K) y presión (kPa) del momento. Con esta
interpretación, en calibraciones buenas la pendiente quedó en 89–91% de la de
fábrica. Conviene confirmar con Hummingbird antes de basar decisiones en ello.

**Presión barométrica del propio sensor:** el sensor tiene medidor de presión
interno (aparece en `!D`, §5.3) pero no lo expone en la salida normal.

**Lecciones de calibración del equipo (lo que sí pasó):**
- Un punto alto grabado con gas de 99.8 cuando el gas real era 99.0 deja la
  escala 0.8 alta. **Registrar siempre la concentración del certificado.**
- Un punto alto grabado con el sensor en aire (≈21%) produce lecturas de ≈97
  en aire después. Verificar la señal antes de grabar (estabilidad ≤0.1 en 30 s).
- `RESET` (`!R`) restaura fábrica y borra el punto alto bueno. No usar sin
  necesidad.
- Ambos sensores pueden quedar **cruzados** si se intercambian cables: el
  mapeo por puerto USB (udev) cambia; el mapeo por identidad (`!`) no.
- Sensor 2 presentó lectura ~0.5 mayor que Sensor 1 en el mismo aire tras
  recalibrar; dentro de tolerancia combinada (~0.4) pero detectable.

## 4. Pantalla Nextion (`.HMI` y protocolo)

**Protocolo:** la pantalla envía `0x65 <página> <id> <evento> FF FF FF` al
tocar (evento `01` = presionar, `00` = soltar). "Send Component ID" manda ese
mensaje automáticamente y depende del id del objeto: **eliminar un objeto
renumera los ids y rompe el protocolo sin aviso** (pasó con `CMP`).
**Mejor práctica adoptada:** `printh 65 <pág> <id> 00 FF FF FF` como primera
línea del evento Touch Release, con "Send Component ID" desmarcado.

**Respuestas de la pantalla:** `get <obj>.<atributo>` devuelve `0x70` + texto +
`FF FF FF` (texto) o `0x71`-`q` + 4 bytes (número, little-endian). `\x1a` =
variable/objeto inválido. `print <var>` envía texto plano **sin marcador**.

**Atributos:** `sta` (1 = color sólido, 3 = transparente; **solo lectura en el
editor si aparece en negro**, no se puede asignar en ejecución), `pco`/`bco`
(color de texto y de fondo, asignables), `vis <id>,<0/1>` (oculta/muestra
por **id**, no por nombre), `pic`/`pic2` (imagen normal/presionada).

**Colores (RGB565):** 0 negro · 65535 blanco · 65504 amarillo · 2016 verde ·
63488 rojo · 1055 azul-verdoso (usado como "procesando").

**Páginas y ids relevantes:**
- Página **Principal**: `OXI1_t`=20, `OXI2_t`=21 (lecturas de texto), `n2`=22,
  `b0`=9. Ids de avisos de alarma: 29 (baja S2), 30 (baja S1), 31 (alta S2),
  32 (alta S1), con imágenes 99/100 (baja) y ids de imagen de alta (p2/p3).
  Preinitialize: `vis 9,0`, `vis 27,0`, `vis 28,0`, `vis 29,0`, `vis 32,0`,
  `vis 31,0`, `vis 22,0` (ver ids en cada página antes de ocultar).
- Página **Alarmas** (id 8): `b0`=3 (máximo), `b1`=4 (mínimo), `c0`/`c1`
  (círculos de estado), `t0` (campo de entrada), `OXI1_t`=22, `OXI2_t`=26,
  `n22`=9, `n2`=29. Preinitialize oculta ids 9, 27, 28, 29, 32.
- Página **Calibración** (id 14): `t1`=28 (Sensor 1), `t2`=29 (Sensor 2),
  `H`=3, `L`=4, `S`=23 (`0x17`), `RESET`=18 (`0x12`), `ERROR` (texto de
  aviso, `txt_maxl` debe ser ≥16).

**Timers:** `tm0` (Alarmas) repone el color de `c0`/`c1` con `n22`; `tm_blink`
(Principal, 500 ms) parpadea los avisos con `sys0=sys0^1`. Un timer mal
configurado puede pisar colores o dejar `\x1a` en bucle (ruido constante
conocido, no causado por el código Python).

**Gráfica de tendencia:** `tm0` toma `OXI1_t`/`OXI2_t` con
`covx ..., 0, 0` (solo parte entera) y los suma con `add 1,<canal>,<valor>`.

**Limitaciones:** no hay `.HMI` fuente versionado (solo el `.tft` compilado y
el archivo del editor, que dependen de la máquina donde se edita). El
`.HMI` del equipo actual está en `back_up/230926/proyecto_local/nextion/`
(puede faltar `INGEMEDI.HMI` si estaba abierto al copiarlo).

## 5. Alarmas

**Configuración:** máximo y mínimo de oxígeno en `max.txt` y `min.txt`
(texto con un decimal, ej. `20.0`), escritos por la pantalla de Alarmas
(`Alarmas_Analizadores.py`) o por SSH. Son los **únicos** umbrales usados por
este equipo (`ALARM_TYPE=1`, `TYPE_EQUIPO=1`, `TYPE_ANALIZADOR=2`). Los
valores de `Alarmas.txt` pertenecen a otra variante de equipo.

**Lógica (dúplex, `Main.py`):**
- Alta por sensor: `s1_high_active = pureza_s1 > maximo` (igual para S2).
- Baja por sensor: `s1_low_active = pureza_s1 < minimo` (igual para S2).
- **LED general, electroválvula y buzzer** (si `flagk()=="1"`): se activan con
  **cualquiera** de las cuatro condiciones. El LED general se enciende con
  todas las alarmas.
- Salidas por sensor (`ALARMA_SENSOR_1/2`): cada una según su propio sensor.
- Avisos en pantalla (`va_bajaS1/2`, `va_altaS1/2` → `tm_blink`): mismas
  condiciones que los pines correspondientes.

**Umbrales de prueba que causaron alarma real (no olvidar):** `20.0/18.0`,
`99.5/100.0`, `67.0/20.0`. Después de cualquier prueba, restaurar umbrales
reales y confirmar con `cat max.txt min.txt`.

**Pantalla de Alarmas (confirmación verde/rojo):** `Alarmas_Analizadores.py`
pinta `c0`/`c1` azul (1055) al recibir el toque, lee el valor que manda
`print t0.txt` con `valor_tras_evento()` (extrae solo el número con regex, pues
llega duplicado y mezclado con ruido `\x1a`), y pinta verde (2016) si es válido
o rojo (63488) si no. El botón de la Nextion ya no tiene `delay` ni `covx`:
solo verifica `t0.txt != ""`.

## 6. Base de datos y reportes

**Base de datos local** (MySQL, `analitech`, tabla `muestras`):
- Se guarda cada **15 s** (`conn_mysql()`), con `connection_timeout=5`.
- Columnas usadas: `oxigeno`, `oxigeno2`, `temperatura`, `pbarometrica`,
  `updated_at` (en realidad contiene `ban`, el flag de alarma: `"0"` = alarma,
  `"1"` = sin alarma), `created_at`.
- `truncate.py` vacía `muestras` y `ALARMAS` al generar el reporte USB.
- **No guardar filas de arranque:** `primera_lectura_o2_lista` evita guardar
  hasta tener lectura real de ambos sensores (`O2_sensor_1/2` arrancan en 0.0).

**Reporte PDF (USB):** `truncate.py` genera el PDF con `fpdf`. Pinta en rojo
cada fila cuyo flag (quinta columna) es `'0'`, en blanco en cualquier otro
caso (incluido `None`). Filas sin alarma pero con oxígeno 0 pueden aparecer
blancas si se guardaron antes de tener lectura real (caso ya corregido).

**Plataforma (sp-peek.com):** Node/Express + MySQL (proyecto aparte:
`Analizador de Oxígeno\var\iot-elsalvador`, `DOCUMENTACION_TECNICA.md`).
- Endpoint: `POST https://sp-peek.com/api/v1/data`, cabecera
  `Authorization: Bearer <token>`. El token debe coincidir con el `.env` del
  servidor y el equipo debe estar registrado en `equipos_config` (sin
  autoregistro).
- Cuerpo: `{ equipo_id, timestamp (ISO 8601), datos: [{tipo_dato, valor}] }`.
- `tipo_dato` de proceso: `oxigeno`, `oxigeno2`, `temperatura`,
  `presion_barometrica`. De salud (cada 60 s): `temp_raspberry`,
  `memoria_uso_pct`, `cpu_uso_pct`, `throttled_flag` (texto hex), `temp_dht22`,
  `humedad_dht22`, `estado_sensor_o2_1`, `estado_sensor_o2_2` (texto: `OK`,
  `B`, `C`, `E`, `S`, `X`, combinaciones). Evento: `encendido` (al arrancar).
  Alarmas y calibración: `alarma`, `calibracion_*` (ya sin uso desde el firmware).
- **Problema actual:** el envío de lecturas de proceso se hace desde el bucle
  de pantalla (`work()`), no desde el hilo de 15 s, así que su cadencia es
  irregular. Pendiente de corregir en el firmware (mover `enviar_datos_iot()`
  al hilo de `conn_mysql()`).
- `muestras_30s`: downsample en la plataforma.

## 7. Hardware y problemas físicos observados

- **BMP085** (presión): falla en cada ciclo (`Input/output error`); la presión
  que usa el equipo es la de **internet** (`api.open-meteo.com`, coordenadas
  fijas en el código), que sobrescribe la medición local. Sin internet, la
  presión queda desactualizada. Reemplazar por sensor digital moderno
  (BMP390 o BME280) con detección al arrancar.
- **DHT22** (temperatura/humedad): en la última prueba **no detectado**
  ("DHT sensor not found, check wiring"), también en prueba aislada sin
  competencia de hilos. Por eso `temperatura` se guardó como `0.0` (el BMP
  tampoco). Causa probable: conector o cable suelto tras el traslado.
- **USB-serie PL2303:** `dmesg` mostró timeouts del controlador
  (`dwc_otg_hcd_urb_dequeue`) y desconexiones de dispositivo. Un proceso
  colgado de una prueba anterior bloqueó un puerto (ya resuelto).
- **Sensores O₂:** las lecturas anómalas (−15 y 200) eran saturación, no
  corrupción. Ver §3.
- **Traslado del equipo:** perdió su red WiFi de oficina (la red se guarda en
  el sistema operativo, no en el código). Para reconectarlo hay que tener
  acceso local (pantalla y teclado) o una red cableada.
- **Cruce de sensores:** se detectó tras mover cables; los sensores aparecían
  intercambiados en los puertos USB.

## 8. Respaldo y documentación del equipo actual

- `Refact Analizador\back_up\230926\`: `proyecto_local/` (código local, sin
  `INGEMEDI.HMI`) y `backup_230926.tar.gz` (copia tomada de la Raspberry el
  25/09, anterior a varios cambios; ver el histórico).
- `Refact Analizador\HISTORICO_CAMBIOS.md`: registro de cambios, con razones y
  archivos (secciones 1–18), y pendientes.
- `Refact Analizador\Reporte_Cambios_Tecnicos_ANZD-600226001.docx`: informe
  técnico para la mesa técnica (actualizado hasta la recalibración del 25/09;
  faltan los cambios posteriores).
- `Refact Analizador\documentacion\Modus\Manual-Paracube-Modus_1.pdf`: manual
  del sensor.
- `documentacion_tecnica\protocolo_caracterizacion_metrologica_O2.md`: protocolo
  de caracterización del sensor.

## 9. Reglas de trabajo aprendidas (aplicar en G2)

- **Confirmar el texto exacto antes de parchear.** Los reemplazos se hacen con
  `assert count == 1`, con respaldo previo del archivo y `ast.parse` después.
  Las líneas cambian con cada edición; buscar por contenido, no por número.
- **Diagnosticar y calcular antes de implementar.** El usuario pide revisar
  los riesgos primero; varias propuestas se descartaron tras revisar el código
  (ej. `O2_sensor_1 = None` habría roto el hilo principal).
- **No asumir el estado del equipo:** el código local puede estar desactualizado
  respecto al equipo. Verificar siempre en el equipo (`cat`, `grep`, `journalctl`).
- **Confirmar la configuración real** antes de dar un dato por cierto (umbrales,
  identidad de sensores, banderas).
- **No deshacer ni reiniciar servicios sin decirlo.** Detener `SpealA` libera
  los puertos, pero también detiene las lecturas que alguien esté usando.
- **Respuestas cortas y simples** (preferencia explícita del usuario).
- **Notar el error propio** y corregirlo sin rodeos (varias veces hubo que
  rectificar: fechas, interpretación de `!D`, el significado de `sta`, el
  sentido de la alarma de rango).

## 10. Mejoras propuestas para G2 (lista acordada hasta ahora)

1. Sensores con identidad desde el diseño (sin adaptadores USB-serie)
2. Un solo proceso dueño de los puertos de los sensores
3. Calibración guiada con estabilidad automática y verificación del gas
4. Calibración semiautomática con electroválvulas
5. Protocolo pantalla–firmware versionado, con `.HMI` en git
6. Lecturas inválidas marcadas como tal, no recortadas a 0–99.9
7. Alarma de sensores discrepantes (diferencia >0.5)
8. Emuladores de sensor y de pantalla para pruebas
9. Diagnóstico remoto desde la plataforma (paquete de diagnóstico)
10. Sensores ambientales robustos (I²C, detección al arrancar, fallas reportadas)
11. Secretos y configuración fuera del código
12. Caudalímetro en la muestra, con bloqueo de calibración sin flujo
13. Detección de humedad y líquido en la línea de muestra
14. Monitoreo de alimentación por rama (INA219/INA226)
15. Tercer sensor de O₂ de otra tecnología, con votación 2 de 3
16. Temperatura cerca de cada celda y de la fuente
17. Acelerómetro y contacto de puerta
18. Reloj de tiempo real con batería propia
19. Respaldo de energía (UPS pequeño o supercapacitor)
20. Procesos desacoplados con cola o socket local, sin archivos de bandera
21. Watchdog de hardware
22. Concurrencia con bloqueos desde el diseño
23. Transporte MQTT y certificado TLS válido (sin `verify=False`)
24. Cola local persistente para reenvío sin pérdida
25. Versionado y actualización remota (OTA) con rollback
26. Gestión centralizada de flota
27. Pruebas automatizadas y de integración
28. Consultas parametrizadas y política de retención de datos
29. Calibración registrada con auditoría (quién, cuándo, gas, puntos, certificado)
30. Configuración de red desde la pantalla (WiFi y Ethernet)
31. Mensajes de error visibles en pantalla, no solo en logs
32. Modo de alimentación/potencia (ahorro de energía en reposo)

*Las mejoras que el usuario quiere implementar en G2 aún no se han anotado
aquí; agregarlas a esta lista.*

## 11. Pendientes del equipo actual (ANZD-600226001)

- Verificar el arranque con la bandera nueva (`primera_lectura_o2_lista`):
  sin filas `0.0000` tras reinicio.
- Reparar el DHT22 (conector/cable) y confirmar lectura.
- Reemplazar el BMP085 o aceptar presión de internet como provisional.
- Aplicar el envío web en el hilo de 15 s (pendiente de la sección 7.1 del
  histórico).
- Recalibración: verificación con gas de 99.0% y de 21% certificado.
- Restaurar `max.txt`/`min.txt` a los valores reales de operación.
- Regenerar el `.docx` del reporte con los cambios desde el 25/09.
- Rehacer el respaldo `230926` tras la verificación final.
- Medir la compensación de presión (`!P`) de ambos sensores.
- Sensor 2 con lectura ~0.5 mayor que Sensor 1 en aire: confirmar si hay que
  ajustarla.
