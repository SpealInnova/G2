# G2 — Hardware: diagrama, mapa de pines y puntos abiertos

Documento de referencia para el diseño del equipo. Lo **verificado** viene de los
manuales del sensor o de la documentación del fabricante del ADC (se indica la
fuente). Lo marcado **PROPUESTA** o **POR VERIFICAR** no está confirmado.

Plataforma: Raspberry Pi 3 Model B Plus Rev 1.4 (verificado por SSH el 2026-10-08),
Raspberry Pi OS de 64 bits (Debian 13 Trixie, Python 3.13.5, SQLite 3.46.1). Todo el
trabajo sobre el equipo se hace por **SSH** (ver D-024 en `MEMORIA_TECNICA.md`).

## 1. Diagrama de bloques (propuesta)

```
                      ┌────────────────────────────────────────────┐
  Sensor O2 #1 ──────►│ AIN0─AIN1 (diferencial)                    │
  (analógico, mV)     │                                            │
  Sensor O2 #2 ──────►│ AIN2─AIN3 (diferencial)   Waveshare        │
                      │                           High-Precision   │──SPI0──┐
  AIN4..AIN9 libres ─►│ (humedad de línea,        AD HAT ADS1263   │        │
   (ampliación)       │  tensión de 5 V, etc.)    10 canales, 32 bit│        │
                      └────────────────────────────────────────────┘        │
                                                                            ▼
 BME280 (T, HR, hPa) ─┐                                          ┌────────────────────┐
 IMU (acel.+giro) ────┤                                          │   Raspberry Pi 3 B │
 Reloj RTC DS3231 ────┼────────────── I²C (GPIO2/3) ───────────►│                    │
 Humedad de línea ────┤                                          │  g2-core           │
 INA219 (después) ────┘                                          │  g2-uplink         │
                                                                 │  g2-ui             │
 Pantalla Nextion ◄──────────── UART0 (GPIO14/15) ──────────────►│                    │
 Relé 1 (alarma O2)  ◄────────── GPIO ───────────────────────────│                    │
 Relé 2 (falla)      ◄────────── GPIO ───────────────────────────│                    │
 LED de alarma       ◄────────── GPIO ───────────────────────────└────────────────────┘
```

## 2. Sensores de oxígeno (verificado, manual 01120009A del Modus analógico)

El manual del Paracube Micro analógico (01117009A) no está disponible; el 01117707 se
asume equivalente.

| Dato | Valor |
|---|---|
| Alimentación | 5 V ±5 %; ruido y rizado < 0.1 V pico a pico; no opera por debajo de 4.75 V |
| Consumo | 70 mA típico, 100 mA máximo (Modus analógico); el manual del Micro digital indica 110 y 150 mA |
| Pines | P1 +5 V, P2 señal en mV, P3 0 V analógico, P4 tierra |
| Señal | Diferencial P2–P3. **No unir P3 con P4.** Entrada del lector > 1 MΩ |
| Escala | 10 mV por % de O₂ (0–100 % = 0–1 V; sobrerrango −15 %…+200 % = −0.15…+2.0 V) |
| Actualización | cada 200 ms ± 5 ms |
| Cables | cortos y apantallados (el manual del Micro digital exige < 15 cm) |

## 3. Convertidor analógico-digital (fuente: [Waveshare](https://www.waveshare.com/wiki/High-Precision_AD_HAT))

High-Precision AD HAT con ADS1263: 10 canales (5 pares diferenciales), 32 bits, hasta
38.4 kSPS, ADC auxiliar de 24 bits, PGA hasta 32×.

- Interfaz **SPI** (hay que habilitarla). Pines usados (BCM): MOSI 10, MISO 9, SCLK 11,
  **CS 22 (por software)**, **DRDY 17**, **RESET 18**.
- Rango (según el fabricante): 0–5 V en modo de un solo extremo (AVDD a 5 V);
  el modo **diferencial** exige la referencia interna de ±2.5 V.
- En Debian Trixie solo está disponible la biblioteca `lgpio` (no `RPi.GPIO`); se
  usarán `spidev` y `lgpio`/`gpiod`.

**Verificado en la hoja de datos de TI (ADS126x, SBAS661C, mayo de 2021):**

| Dato | Valor | Dónde |
|---|---|---|
| Rango de entrada | ±VREF / ganancia. Con la referencia interna de 2.5 V: ganancia 1 = ±2.5 V, 2 = ±1.25 V, 4 = ±0.625 V | Tabla 9-2 |
| Entrada absoluta con PGA activo | VAVSS + 0.3 V < entrada < VAVDD − 0.3 V (menos la mitad de VIN·(ganancia−1)) | Ecuación 12 |
| Entrada absoluta con PGA en derivación (bypass) | VAVSS − 0.1 V < entrada < VAVDD + 0.1 V | Ecuación 13 |
| Impedancia de entrada diferencial | PGA activo 1 GΩ; PGA en derivación 40 MΩ (el sensor exige > 1 MΩ) | 7.5 |
| Ruido a ganancia 1, 20 SPS, sinc4 | 0.229 µV rms (1.285 µV pico a pico); filtro FIR 0.393 (2.467) | Tabla 8-1 |
| Offset | 350 µV típico / ganancia sin modo chopper; ±0.1 µV / ganancia con modo chopper | 7.5 |
| Error de ganancia | ±50 ppm típico (±300 máximo) | 7.5 |

**Consecuencias para el sensor de oxígeno (10 mV por % de O₂):**
1. **No hace falta ganancia.** El ruido del ADC a ganancia 1 es de ~1.3 µV pico a pico, es decir
   0.00013 % de O₂; el ruido del propio sensor es < 0.2 % (≈ 2 mV). Amplificar no mejora la
   medición y reduce el rango: con ganancia 2 el límite es 1.25 V = 125 % de O₂.
2. **El PGA debe ir en derivación (bypass).** Con el PGA activo las entradas deben quedar por
   encima de 0.3 V, y P3 (0 V analógico) está cerca de 0 V. En derivación se admiten entradas
   hasta 0.1 V por debajo de tierra.
3. **Offset del ADC:** sin modo chopper es del orden de 350 µV (≈ 0.035 % de O₂); se corrige con
   el modo chopper o con la autocalibración de offset del ADC.
4. **Fuentes de ruido reales** (el ruido que importa no es el del ADC): rizado de la fuente de
   5 V del sensor, interferencia de la red de 50/60 Hz y de los relés de AC, cables largos o sin
   apantallar, y las propias actualizaciones cada 200 ms de la salida del sensor.

**Puntos por verificar con el sensor real en el banco:**
1. Tensión de modo común: P3 es una referencia flotante (no se une a tierra en el sensor). El ADC
   necesita un nivel de continua definido en esa entrada; opciones: unir P3 a tierra analógica
   solo en el extremo del ADC, o usar la resistencia de polarización interna del ADS1263
   (sensor bias, 10 MΩ). Conviene pedir al fabricante del sensor (Hummingbird) la forma
   recomendada de conexión con un ADC externo.
2. Filtro: se propone el filtro FIR a 20 SPS por su rechazo de 50 y 60 Hz; falta confirmarlo en
   la sección del filtro digital de la hoja de datos.
3. Fuente de 5 V limpia para los sensores (rizado < 0.1 V), en una rama separada de la
   Raspberry Pi y la pantalla.
4. Muestreo: el sensor actualiza cada 200 ms; se lee cada sensor más rápido y se promedia por
   ventana de 200 ms, conservando mínimo y máximo.

## 4. Mapa de pines (PROPUESTA salvo lo marcado)

| Función | Pin BCM | Estado |
|---|---|---|
| ADC: MOSI / MISO / SCLK | 10 / 9 / 11 | Verificado (Waveshare) |
| ADC: CS / DRDY / RESET | 22 / 17 / 18 | Verificado (Waveshare) |
| I²C (SDA / SCL) | 2 / 3 | Propuesta |
| Nextion (TX / RX) | 14 / 15 (UART0, `/dev/serial0`) | Propuesta |
| Relé 1 (alarma de oxígeno) | 23 | Propuesta |
| Relé 2 (falla del equipo) | 24 | Propuesta |
| LED de alarma | 25 | Propuesta |

Notas:
- En la Raspberry Pi 3 B, el UART principal (PL011) está por omisión conectado al
  Bluetooth. Para usarlo con la pantalla hay que liberar el UART (por ejemplo,
  `dtoverlay=disable-bt`); el UART pequeño no es fiable para la velocidad de la
  Nextion. **POR VERIFICAR** al configurar el sistema.
- Los pines de la cabecera quedan **expuestos** con el HAT instalado (confirmado por
  el usuario). Falta comprobar físicamente que los GPIO 23, 24 y 25 están libres.
- Los relés necesitan una etapa de potencia con aislamiento y diodo de protección, con
  **estado definido al arrancar** (resistencias de polarización): los GPIO quedan sin
  definir mientras la Raspberry Pi arranca.

## 5. Direcciones I²C (PROPUESTA)

| Dispositivo | Dirección | Observación |
|---|---|---|
| Reloj RTC DS3231 | 0x68 | |
| IMU (acelerómetro + giroscopio) | 0x69 | Si el modelo usa 0x68 por omisión, subir su pin AD0 para evitar choque con el RTC |
| BME280 (temperatura, humedad, presión) | 0x76 | |
| Humedad de la línea de aire (SHT4x u otro) | 0x44 | Modelo por definir |
| INA219 (después) | 0x40 | Cuando haya pruebas |

## 6. Periféricos y para qué sirven

- **Temperatura y humedad (BME280 u otro con presión):** va **muy cerca de los
  sensores de oxígeno**, para medir el ambiente de los sensores (y de la
  Raspberry Pi). No está en la línea de gas. Importa porque el manual da un
  coeficiente de temperatura (cero < ±0.5 % de O₂ por 10 °C; span < ±0.5 % de la
  lectura por 10 °C) y una constante térmica de 15 minutos; los cambios bruscos de
  temperatura (por ejemplo, un ventilador) alteran la medición. Ubicarlo cerca de
  los sensores pero lejos de fuentes de calor. La temperatura de la propia
  Raspberry Pi se lee del procesador. La presión (hPa) la da el mismo chip si es un
  BME280 o BMP390; el giroscopio *no* mide presión.
- **IMU (acelerómetro + giroscopio):** vibración e **inclinación**. Importa por dos
  razones del manual del sensor: la vibración y los golpes producen lecturas erróneas
  (Caution 5) y un cambio de orientación de 15° cambia la lectura hasta ±0.5 % de O₂.
- **Humedad de la línea de aire (opcional, sin definir):** el manual exige gas seco, sin condensación y con
  punto de rocío 10 °C por debajo de la temperatura del sensor. Un aviso temprano
  protege la medición. **POR VERIFICAR (seguridad):** el sensor irá en una corriente
  rica en oxígeno; debe ser apto para servicio con oxígeno y estar ubicado en un
  lugar seguro. Esto necesita revisión de un experto antes de elegir el modelo.

## 7. Salidas

- Los **dos relés activan alarmas de corriente alterna (AC)** (confirmado por el
  usuario). Roles propuestos, por confirmar: **relé 1 = alarma de oxígeno** (alto o
  bajo) y **relé 2 = falla del equipo**, energizado en estado normal, de modo que un
  corte de energía, un reinicio o una caída del servicio se vea como falla (práctica
  habitual en equipos de alarma). Costo: una bobina energizada de forma continua
  consume corriente; medirlo.
- **LED de alarma** de estado local.
- No hay zumbador por GPIO: el aviso sonoro es el de la Nextion (D-020). Si `g2-ui`
  falla no suena; un relé puede manejar un zumbador externo o el panel de alarmas del
  hospital.

**Conmutación de corriente alterna: puntos de seguridad (POR VERIFICAR con un
experto; el equipo es para hospitales):**
- Los contactos del relé deben estar dimensionados para la tensión y la corriente de
  la alarma, incluida su naturaleza inductiva (sirenas, bobinas).
- Protección de contactos con red RC o varistor y fusible o interruptor en el
  circuito de la alarma.
- Separación física y eléctrica entre la parte de red (AC) y la electrónica de baja
  tensión: distancias de aislamiento, tierra de protección y, si procede, relés con
  aislamiento reforzado.
- Etapa de potencia de los relés con estado definido al arrancar (resistencias de
  polarización y diodo de protección): los GPIO quedan sin definir mientras la
  Raspberry Pi arranca.
- Revisar si aplica la norma de seguridad eléctrica de equipos médicos (IEC 60601-1);
  no se ha verificado su texto.

## 8. Presupuesto de energía (POR MEDIR)

Sensores de oxígeno: 2 × hasta 150 mA a 5 V (valor conservador). Raspberry Pi 3 B,
pantalla Nextion, HAT, relés, LED y periféricos: por medir en el equipo. Se medirá con
el INA219 cuando se incorpore.
