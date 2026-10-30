# Especificación del HMI de G2 (pantalla Nextion NX8048P050_011)

Documento para construir `g2.HMI` en el Nextion Editor. Decisiones de fondo: D-029 en
`MEMORIA_TECNICA.md`. Esta es la **etapa 1**: convenciones, protocolo y la página principal. Las
demás páginas se especifican en las etapas siguientes, cuando la principal ya funcione.

Proyecto: modelo `NX8048P050_011` (5.0", 800×480), dirección 0° horizontal, codificación
`iso-8859-1` (ya configurados).

## 1. Principios

1. **La pantalla solo muestra y avisa de toques.** No decide nada: ni qué página mostrar, ni si un
   valor es válido, ni si una alarma está activa. Todo eso lo decide la Raspberry Pi (`g2-ui`).
2. **Toda navegación pasa por la Pi.** Un botón de navegación no ejecuta `page ...`: avisa a la Pi
   y la Pi ordena el cambio de página. Así la Pi puede pedir el PIN antes de abrir una página
   protegida y puede forzar una página (por ejemplo, la de alarmas).
3. **Los nombres no se cambian ni se reutilizan.** La Pi escribe en los componentes por su nombre
   (`principal.o2_1.txt="20.9"`). Si hace falta cambiar un nombre, se cambia aquí y en el código
   a la vez.
4. **El protocolo no depende de los números que asigna el editor.** Los eventos de toque llevan
   códigos propios de esta especificación (tabla 2), no el `id` del componente. Así, borrar o
   reordenar objetos no rompe nada. (En el equipo anterior eso rompió el protocolo sin avisar.)

## 2. Protocolo pantalla → Pi

Todo evento tiene el formato de un evento de toque estándar de Nextion, para usar un solo
analizador: `65 PP CC 00 FF FF FF` (bytes en hexadecimal), donde `PP` es el **código de página** y
`CC` el **código del control**.

| PP | Página | | CC | Significado |
|---|---|---|---|---|
| 00 | principal | | 01 a 7F | botones de cada página (ver su tabla) |
| 01 | alarmas | | FE | la página terminó de cargarse (la Pi envía todos sus datos) |
| 02 | config | | | |
| 03 | red | | | |
| 04 | calibracion | | | |
| 05 | sistema | | | |
| 06 | teclado | | | |
| 07 | reportes | | | |
| 08 | confirmar | | | |
| 09 | texto | | | |
| 0A | grafica | | | |

- **Cómo se escribe en el editor:** en el evento *Touch Release* de cada botón, **la primera línea**
  es `printh 65 PP CC 00 FF FF FF` con los códigos de la tabla de esa página (por ejemplo
  `printh 65 00 01 00 FF FF FF`). La casilla *Send Component ID* se deja **sin marcar**.
- **Página cargada:** en el evento *Postinitialize* de cada página va
  `printh 65 PP FE 00 FF FF FF`. Es lo que permite a la Pi rellenar la página aunque la pantalla se
  haya reiniciado sola.
- **Pantalla encendida:** al encender, Nextion envía `88 FF FF FF` por sí misma; la Pi lo toma como
  "pantalla reiniciada" y la resincroniza completa.
- **Versión del protocolo:** el componente `proto` (variable numérica global de la página
  `principal`) vale `1`. La Pi lo lee al arrancar (`get principal.proto.val`) y avisa si no coincide.
  Sube de número cuando cambie esta especificación de forma incompatible.

## 3. Pi → pantalla

La Pi escribe con comandos de Nextion terminados en `FF FF FF`. Textos con comillas, en
`iso-8859-1`; colores en RGB565 (decimal); páginas por nombre. Ejemplos:

```
principal.o2_1.txt="20.9"
principal.est_1.txt="NORMAL"
principal.est_1.bco=1128
principal.est_1.pco=65535
page alarmas
```

## 4. Convenciones del editor

- **Nombres** de páginas y componentes: minúsculas, sin tildes ni espacios, en español
  (`principal`, `o2_1`, `b_alarmas`). Se asigna en *objname* (para una página, con doble clic en el
  panel *Page*).
- **Orden de las páginas en el editor:** las páginas nuevas se agregan **al final**, en el orden en que
  se construyen, y no se reordenan. El número interno de cada página no importa: la Pi las llama por
  su **nombre** y los eventos usan los códigos `PP` fijos de la sección 2.
- **No borrar objetos que ya estén en uso:** si sobra uno, se vuelve invisible (`vis=0`) o se deja.
- **Variables globales** (`vscope = global`) solo para el protocolo; el resto es local.
- **Sin lógica en la pantalla** más allá de: enviar el evento de toque, enviar el evento de página
  cargada y reproducir el pitido de pulsación (sección 6).

### Fuentes (Tools → Font Generator, codificación `iso-8859-1`, caracteres 32 a 255)

| Número | Uso | Tipo y tamaño (alto aproximado en píxeles) |
|---|---|---|
| 0 | textos pequeños (indicadores de la barra) | Arial, 24 |
| 1 | títulos y avisos | Arial negrita, 32 |
| 2 | estado del sensor | Arial negrita, 40 |
| 3 | valor de oxígeno | Arial negrita, 100 (solo necesita 0 a 9, punto, guion y espacio) |
| 4 | botones | Arial negrita, 24 |

El orden de creación fija el número: crear en este orden, de 0 a 4. Los anchos de las cajas de
la sección 5 están calculados para estas fuentes; con el botón **Debug** compruebe que el texto
más largo de cada caja cabe (`100.0` en `o2_*`, `CALIBRANDO` en `est_*`, `COLA 1250` en
`cola_s`, `Calibrar` en `b_calib`). Si no cabe, acorte el texto, no agrande la fuente.

### Colores (RGB565 decimal)

| Nombre          | Valor  | Uso                                  |
|---              |---     |---                                   |
| fondo           | 63423  | fondo de la página                   |
| tarjeta         | 65535  | tarjetas y avisos                    |
| texto           | 6438   | texto principal                      |
| texto_suave     | 25423  | títulos de tarjeta                   |
| barra           | 6504   | barra superior                       |
| normal          | 1128   | estado normal (verde)                |
| alarma          | 51427  | alarma alta o baja (rojo)            |
| aviso           | 62880  | advertencia y botón de acuse (ámbar) |
| calibrando      | 726    | calibración en curso (azul)          |
| inactivo        | 27568  | sin señal o deshabilitado (gris)     |
| boton           | 59197  | botón en reposo                      |
| boton_pulsado   | 48730  | botón pulsado                        |
| blanco          | 65535  | texto sobre barra y estados          |
| sensor1         | 6969   | línea y valor del sensor 1 en la gráfica (azul) |
| sensor2         | 58306  | línea y valor del sensor 2 en la gráfica (naranja) |

El estado nunca se indica **solo con color**: siempre va escrito (NORMAL, ALTA, BAJA...).

## 5. Página 0: `principal` (800×480)

### Fondo (imagen)

El fondo (barra superior, tarjetas, franja de avisos y siluetas de los botones) es una imagen
**sin texto**: `nextion/fondos/principal.png` (800×480). Se generó con IA y se ajustó a la cuadrícula
con `tools/ajustar_fondo_nextion.py` (original en `nextion/fondos/origen_principal_chatgpt.png`).

1. En el panel **Picture** → **Add**, agregar `principal.png`. Debe ser **la primera imagen**
   del proyecto (id 0).
2. Poner el fondo como un componente **Picture** de pantalla completa: `objname` = `fondo`,
   `pic` = 0, `x` = 0, `y` = 0, `w` = 800, `h` = 480. Es **el primer componente** que se crea
   (queda al fondo de las capas; todo lo demás va encima). La página no necesita `sta` ni `pic`.
3. El nombre de la página es `principal`, en minúscula (los nombres distinguen mayúsculas: la Pi
   enviará `page principal`).

El logotipo de SPEAL (`nextion/imagenes/logo.png`, 110×44 px) ya viene **dibujado en el fondo**,
en x=16, y=6; por eso el título empieza en x=138. No se agrega como componente.

Con el fondo puesto, **no se crean** componentes para la barra ni para las tarjetas. Los textos que
van sobre la barra o sobre las tarjetas llevan `sta` = **crop image** y `picc` = 0 (`sta` y `picc` son atributos del propio Text): así muestran el
fondo detrás de las letras. Los textos que **cambian de color** según el estado (`est_*` y `aviso`)
llevan `sta` = solid color, porque la Pi les cambia `bco`.

### Componentes

Tipo *Text* salvo donde se indica. `xcen`/`ycen` = 1 (centrado) salvo que se indique otra cosa
(`xcen`: 0 izquierda, 1 centro, 2 derecha). Posiciones y tamaños en píxeles.

| Nombre | Tipo | x | y | w | h | Fuente | Texto inicial | pco | sta / bco | Notas |
|---|---|---|---|---|---|---|---|---|---|---|
| `titulo` | Text | 138 | 8 | 215 | 40 | 1 | Analizador G2 | blanco | crop image | `xcen`=0 |
| `hora` | Text | 360 | 8 | 110 | 40 | 1 | 00:00 | blanco | crop image | |
| `red_s` | Text | 480 | 8 | 140 | 40 | 0 | SIN RED | blanco | crop image | estado de la red |
| `cola_s` | Text | 630 | 8 | 154 | 40 | 0 | COLA 0 | blanco | crop image | registros pendientes de envío |
| `tit_1` | Text | 32 | 84 | 200 | 36 | 1 | SENSOR 1 | texto_suave | crop image | `xcen`=0 |
| `o2_1` | Text | 32 | 124 | 260 | 130 | 3 | --.- | texto | crop image | `xcen`=2 (derecha) |
| `uni_1` | Text | 296 | 196 | 84 | 40 | 1 | %O2 | texto_suave | crop image | `xcen`=0 |
| `est_1` | Text | 32 | 268 | 344 | 68 | 2 | SIN SEÑAL | texto_suave | solid, bco = tarjeta | la Pi cambia texto y colores |
| `tit_2` | Text | 424 | 84 | 200 | 36 | 1 | SENSOR 2 | texto_suave | crop image | `xcen`=0 |
| `o2_2` | Text | 424 | 124 | 260 | 130 | 3 | --.- | texto | crop image | `xcen`=2 |
| `uni_2` | Text | 688 | 196 | 84 | 40 | 1 | %O2 | texto_suave | crop image | `xcen`=0 |
| `est_2` | Text | 424 | 268 | 344 | 68 | 2 | SIN SEÑAL | texto_suave | solid, bco = tarjeta | |
| `aviso` | Text | 20 | 368 | 760 | 40 | 1 | Sin alarmas | texto | solid, bco = tarjeta | línea de alarmas y mensajes |
| `b_alarmas` | Button | 26 | 427 | 108 | 42 | 4 | Alarmas | texto | solid, bco = boton | `bco2` = boton_pulsado |
| `b_config` | Button | 159 | 427 | 108 | 42 | 4 | Config | texto | solid, bco = boton | `bco2` = boton_pulsado |
| `b_red` | Button | 284 | 427 | 108 | 42 | 4 | Red | texto | solid, bco = boton | `bco2` = boton_pulsado |
| `b_calib` | Button | 411 | 427 | 108 | 42 | 4 | Calibrar | texto | solid, bco = boton | `bco2` = boton_pulsado |
| `b_sistema` | Button | 538 | 427 | 108 | 42 | 4 | Sistema | texto | solid, bco = boton | `bco2` = boton_pulsado |
| `b_acuse` | Button | 665 | 427 | 108 | 42 | 4 | ACUSAR | texto | solid, bco = aviso | `bco2` = boton_pulsado |
| `proto` | Variable (número) | | | | | | | | | `vscope`=global, `val`=1 |

Los botones quedan 2 px dentro de las siluetas de la imagen, para que el borde de la imagen
enmarque cada botón. Los tres colores de `bco` de la imagen real son: fondo 63391, tarjeta
65535 y botón 57085; si al compilar se nota la diferencia con la paleta de la sección 4, para
los botones use 57085 en vez de `boton`.

### Eventos

Cada uno de los 6 botones lleva **dos** eventos: al **pulsar** suena el pitido (así se oye al
instante) y al **soltar** avisa a la Pi.

| Evento (en los 6 botones) | Código |
|---|---|
| Touch Press | `play 1,0,0` |

Y al soltar:

| Evento | Código a enviar (`printh ...`) |
|---|---|
| `b_alarmas`           Touch Release     | `printh 65 00 01 00 FF FF FF` |
| `b_config`            Touch Release     | `printh 65 00 02 00 FF FF FF` |
| `b_red`               Touch Release     | `printh 65 00 03 00 FF FF FF` |
| `b_calib`             Touch Release     | `printh 65 00 04 00 FF FF FF` |
| `b_sistema`           Touch Release     | `printh 65 00 05 00 FF FF FF` |
| `b_acuse`             Touch Release     | `printh 65 00 06 00 FF FF FF` |
| Página `principal`,   Postinitialize    | `printh 65 00 FE 00 FF FF FF` |

Ningún otro evento lleva código: los demás componentes son solo de lectura y no suenan.

### Largo máximo de los textos (`txt_maxl`)

El atributo `txt_maxl` (por defecto 10) es el máximo de letras que acepta el componente: lo que la
Pi escriba de más se **corta sin avisar**. Valores: `aviso` 60, `est_1` y `est_2` 12, `red_s` 12,
`cola_s` 14; `hora`, `o2_1`, `o2_2` y los demás, 10. La Pi no debe escribir textos más largos.

### Qué escribirá la Pi

| Componente | Valores |
|---|---|
| `o2_1`, `o2_2` | `20.9`, `100.0`, o `--.-` si no hay dato |
| `est_1`, `est_2` | NORMAL (bco normal), ALTA y BAJA (bco alarma), CALIBRANDO (bco calibrando), SIN SEÑAL y APAGADO (bco inactivo); `pco` siempre blanco |
| `aviso` | "Sin alarmas" (bco tarjeta, pco texto) o el resumen de las alarmas activas, p. ej. `S1 BAJO 18.5 %  S2 ALTO 93.2 %` (bco alarma, pco blanco); máximo 60 letras |
| `red_s` | `WIFI OK`, `CABLE OK`, `SIN RED` |
| `cola_s` | `COLA 0`, `COLA 1250`... |
| `hora` | `HH:MM` |

### Alarma de un sensor (D-032)

Cada sensor se avisa por separado. Para el sensor N, la Pi escribe:

| Situación | `est_N` | `o2_N` |
|---|---|---|
| Alarma nueva (sin acusar) | texto `ALTA` o `BAJA`; **parpadea** a 1 Hz alternando `bco` = alarma (51427) y `pco` = blanco con los colores **invertidos** (`bco` = blanco y `pco` = alarma), así el texto se lee en las dos fases | `pco` = alarma (51427) |
| Alarma acusada | `bco` = alarma **fijo** | `pco` = alarma |
| Sin alarma | texto de su estado normal | `pco` = texto (6438) |

El parpadeo lo hace la Pi (no la pantalla), así se detiene si `g2-ui` se detiene y el recuadro queda
en el último color. El sonido de alarma es otro audio del proyecto (id 1 en adelante), por el canal 0.

## 6. Sonido de pulsación (pitido)

La pantalla tiene altavoz pero **no zumbador**, así que el comando `beep` no suena: el pitido es un
archivo de audio corto que se reproduce con `play`. El archivo (`nextion/sonidos/pulsacion.wav`:
tono de 2 kHz, 70 ms, mono, 16 bits, 16 kHz) se genera con `tools/generar_sonido_pulsacion.py`.

1. En el panel **Audio** del editor → **Add**, agregar `pulsacion.wav`. Debe ser **el primer audio**
   del proyecto (id 0). Los sonidos de alarma se agregarán después (id 1 en adelante).
2. En el evento **Touch Press** de cada botón de navegación (y de Acusar), poner `play 1,0,0`
   (canal 1, audio 0, sin repetir). El **canal 0 queda reservado para las alarmas**, así el pitido
   de un toque no corta una alarma que esté sonando.
3. Volumen: en la pestaña **Program.s** (se ejecuta al encender la pantalla) fijar `volume=50`
   (0 a 100; la variable se llama `volume`, no `vol`: con `vol` el editor da *Invalid Variables*).
   Es persistente: la pantalla la recuerda y la usa como volumen al encender. Si el editor no
   admite la asignación en Program.s, ponerla en el *Postinitialize* de `principal`.
   **No suba de 60.** Con `volume=70` la pantalla **se reinicia sola al sonar el audio** (probado el 2026-10-21: con 70
   se reinicia; con 50 y 60, no): el altavoz consume más de lo que aguanta la fuente de la pantalla. Aun así, la Pi
   **fija el volumen al arrancar y cada vez que la pantalla enciende** (clave `pantalla.volumen`, 50 por omisión), así que
   un volumen alto en el `.HMI` solo dura hasta que la interfaz arranca.
4. Regla para las páginas siguientes: **todo botón que el usuario pulse lleva `play 1,0,0` en su
   Touch Press**; los componentes que solo muestran no.

### Sonido de alarma

Es otro audio del proyecto: `nextion/sonidos/alarma.wav` (tono doble alterno de 880 y 660 Hz, 0.68 s,
generado por `tools/generar_sonido_alarma.py`). Se agrega en el panel **Audio** como **el segundo**
(id 1). Ningún componente lo reproduce por sí solo: **lo ordena la Pi** con `play 0,1,0` (canal 0,
audio 1, una vez) y lo **repite cada pocos segundos** mientras haya una alarma sin acusar (D-032). Así,
si `g2-ui` falla, el sonido se detiene solo y no queda sonando sin control. Tras **Acusar** se silencia
por `alarma.acuse_silencio_s` (120 s, D-031).

### Sonido «Calibrando»

Voz grabada por el usuario que dice «Calibrando» (`nextion/sonidos/calibrando.wav`, 0,61 s, mono, 16 bits, 16 kHz; se obtiene de la
grabación original con `tools/convertir_sonido_voz.py`). Se agrega en el panel **Audio** como **el tercero** (id 2), después de
`pulsacion` (0) y `alarma` (1). Lo ordena la Pi con `play 0,2,0` y lo repite cada pocos segundos mientras dure una calibración (con las
alarmas suspendidas el canal 0 queda libre). Su pico es 0,85 y su energía (RMS 0,12) es una cuarta parte de la del tono de alarma (0,52),
que a volumen 50 no reinicia la pantalla.

El pitido lo reproduce la propia pantalla, sin ir y volver a la Pi, para que suene al instante
aunque la Pi esté ocupada (decisión de D-029). Si `g2-ui` falla, los toques siguen sonando, pero
no navegan. Si el editor rechaza el `.wav` o el canal 1 no existe en este modelo, se ajusta al
probar (otro formato de audio o el canal 0).

## 7. Página `teclado` (PP = 06)

Teclado numérico para escribir el PIN y los valores. **La pantalla no guarda lo tecleado**: cada tecla
avisa a la Pi, que lleva el valor, lo valida y reescribe el campo `valor` (para un PIN escribe un
asterisco por dígito). Así el PIN nunca se queda en la pantalla.

**Fondo:** `nextion/fondos/interna.png` (barra con el logotipo y un panel blanco), generado por
`tools/generar_fondo_interno.py`. En el panel **Picture** → **Add**, agréguelo como **segunda imagen**
(id 1). Se usa también en las demás páginas interiores. Componente `fondo`: *Picture* de pantalla completa
(`pic` = 1, x 0, y 0, w 800, h 480), el primero que se crea en la página.

Todos los *Text* de la tabla llevan `sta` = solid color salvo `titulo` (crop image, `picc` = 1).

| Nombre | Tipo | x | y | w | h | Fuente | Texto inicial | pco | bco | `txt_maxl` / notas |
|---|---|---|---|---|---|---|---|---|---|---|
| `titulo` | Text | 138 | 8 | 500 | 40 | 1 | Teclado | blanco | crop image (`picc` 1) | 30; `xcen`=0 |
| `t_titulo` | Text | 32 | 84 | 368 | 40 | 1 | Valor | texto_suave | tarjeta | 40; `xcen`=0; qué se está tecleando |
| `valor` | Text | 32 | 128 | 368 | 72 | 2 | (vacío) | texto | fondo (63423) | 12; centrado; campo de lo tecleado |
| `msg` | Text | 32 | 208 | 368 | 72 | 0 | (vacío) | texto_suave | tarjeta | 80; `xcen`=0, `ycen`=0, `isbr`=True (salto de línea); ayuda y errores |
| `b_borrar` | Button | 32 | 292 | 176 | 56 | 4 | Borrar | texto | boton | `bco2` = boton_pulsado |
| `b_limpiar` | Button | 224 | 292 | 176 | 56 | 4 | Limpiar | texto | boton | |
| `b_cancelar` | Button | 32 | 364 | 176 | 72 | 4 | Cancelar | texto | boton | |
| `b_aceptar` | Button | 224 | 364 | 176 | 72 | 4 | Aceptar | blanco | normal (1128) | `bco2` = 870 (verde oscuro); `pco2` blanco |
| `k_7`, `k_8`, `k_9` | Button | 436, 548, 660 | 84 | 100 | 76 | 2 | 7, 8, 9 | texto | boton | `bco2` = boton_pulsado |
| `k_4`, `k_5`, `k_6` | Button | 436, 548, 660 | 168 | 100 | 76 | 2 | 4, 5, 6 | texto | boton | |
| `k_1`, `k_2`, `k_3` | Button | 436, 548, 660 | 252 | 100 | 76 | 2 | 1, 2, 3 | texto | boton | |
| `k_punto`, `k_0`, `k_signo` | Button | 436, 548, 660 | 336 | 100 | 76 | 2 | `.`, 0, ± | texto | boton | el signo `±` es el carácter 0xB1 (existe en iso-8859-1) |

Los botones llevan `style` = flat, `sta` = solid color y `pco2` = `pco`. Los que no figuran con `bco2`
propio usan boton_pulsado (48730).

### Eventos (`printh 65 06 CC 00 FF FF FF` al soltar)

Todos los botones llevan además `play 1,0,0` en *Touch Press*.

| CC | Botón | | CC | Botón |
|---|---|---|---|---|
| 10 a 19 | `k_0` a `k_9` (10 + dígito) | | 1C | `b_borrar` |
| 1A | `k_punto` | | 1D | `b_limpiar` |
| 1B | `k_signo` | | 1E | `b_cancelar` |
| FE | página cargada (*Postinitialize*) | | 1F | `b_aceptar` |

### Qué hace la Pi

1. Antes de abrir la página, la Pi guarda **qué se va a teclear** (PIN o una clave de configuración) y
   **desde qué página** (para volver), y envía `page teclado`.
2. Al llegar `65 06 FE`, escribe `titulo`, `t_titulo`, `valor` y `msg` (por ejemplo, el rango válido).
3. Cada tecla: la Pi actualiza el valor y reescribe `valor`. Ignora lo que no corresponda (el punto en
   un valor entero, `±` si no admite negativos, más de 12 caracteres).
4. **Aceptar:** la Pi valida con el catálogo de configuración (rango y relaciones, p. ej. bajo < alto).
   Si es válido lo aplica con origen `pantalla`, y vuelve a la página de origen. Si no, escribe el
   motivo en `msg` con `pco` = alarma (51427) y deja la página abierta.
5. **Cancelar:** vuelve sin cambiar nada.
6. **PIN (confirmado, D-038):** `valor` muestra un asterisco por dígito (de 4 a 8). El PIN **vale 5 minutos** una vez
   aceptado; **3 intentos fallidos** bloquean el teclado **60 s** (mientras tanto las teclas no hacen nada y `msg`
   cuenta los segundos). Los tres valores son claves del catálogo (`pantalla.pin_vigencia_s`, `pantalla.pin_intentos`
   y `pantalla.pin_bloqueo_s`) que **no se pueden cambiar desde la propia pantalla**. La Pi verifica el PIN contra
   su huella y solo avisa al núcleo el resultado (aceptado, fallido o bloqueado) para dejarlo como evento de seguridad.
7. **Título de la barra:** la Pi escribe `titulo` según el modo: `Ingrese el PIN` o `Ajustar alarma`. `t_titulo` dice
   `PIN` o el ajuste (por ejemplo `Oxígeno bajo (%)`), y `msg` la ayuda (`Actual: 20.0 %. Entre 0 y 100 % O2`) o el
   error en rojo (`PIN incorrecto. Intentos restantes: 2`, `Debe ser menor que el máximo (92 %)`...).

## 8. Página `alarmas` (PP = 01)

Muestra y ajusta los umbrales de alarma y lista las alarmas recientes. Todo cambio pide el PIN (la Pi
abre el teclado, sección 7). **Fondo:** el mismo `interna.png` (`fondo`, `pic` = 1).

| Nombre | Tipo | x | y | w | h | Fuente | Texto inicial | pco | bco | `txt_maxl` / notas |
|---|---|---|---|---|---|---|---|---|---|---|
| `titulo` | Text | 138 | 8 | 500 | 40 | 1 | Alarmas | blanco | crop image (`picc` 1) | 30; `xcen`=0 |
| `h_aj` | Text | 32 | 84 | 368 | 28 | 0 | AJUSTES | texto_suave | tarjeta | 20; `xcen`=0 |
| `l_bajo` | Text | 32 | 116 | 190 | 44 | 0 | Oxígeno bajo | texto | tarjeta | 20; `xcen`=0 |
| `l_alto` | Text | 32 | 168 | 190 | 44 | 0 | Oxígeno alto | texto | tarjeta | 20; `xcen`=0 |
| `l_retardo` | Text | 32 | 220 | 190 | 44 | 0 | Retardo | texto | tarjeta | 20; `xcen`=0 |
| `l_histeresis` | Text | 32 | 272 | 190 | 44 | 0 | Histéresis | texto | tarjeta | 20; `xcen`=0 |
| `l_acuse` | Text | 32 | 324 | 190 | 44 | 0 | Tiempo acuse | texto | tarjeta | 20; `xcen`=0 |
| `v_bajo` | Button | 228 | 116 | 172 | 44 | 4 | 20.0 % | texto | boton | `bco2` = boton_pulsado; `txt_maxl` 12 |
| `v_alto` | Button | 228 | 168 | 172 | 44 | 4 | 92.0 % | texto | boton | |
| `v_retardo` | Button | 228 | 220 | 172 | 44 | 4 | 10 s | texto | boton | |
| `v_histeresis` | Button | 228 | 272 | 172 | 44 | 4 | 0.5 % | texto | boton | |
| `v_acuse` | Button | 228 | 324 | 172 | 44 | 4 | 120 s | texto | boton | |
| `b_volver` | Button | 32 | 392 | 368 | 56 | 4 | Volver | texto | boton | |
| `h_hist` | Text | 432 | 84 | 336 | 28 | 0 | HISTORIAL RECIENTE | texto_suave | tarjeta | 24; `xcen`=0 |
| `h1` a `h6` | Text | 432 | 116 + 50·n (n = 0 a 5) | 336 | 44 | 0 | (vacío) | texto | tarjeta | 40; `xcen`=0 |

Las cinco filas de ajuste corresponden, en orden, a las claves `alarma.o2_bajo_pct`,
`alarma.o2_alto_pct`, `alarma.o2_retardo_s`, `alarma.o2_histeresis_pct` y `alarma.acuse_silencio_s`
(D-027, D-031). Los valores llevan su unidad escrita en el texto del botón.

### Eventos (`printh 65 01 CC 00 FF FF FF` al soltar; además `play 1,0,0` en *Touch Press*)

| CC  | Botón           |     | CC  | Botón        |
|---  |---              |---  |---  |---           |
| 01  | `v_bajo`        |     | 05  | `v_acuse`    |
| 02  | `v_alto`        |     | 06  | `b_volver`   |
| 03  | `v_retardo`     |     | FE  | página cargada (*Postinitialize*) |
| 04  | `v_histeresis`  |     |     |              |

### Qué escribe la Pi

- `v_bajo`, `v_alto`, `v_retardo`, `v_histeresis`, `v_acuse`: el valor vigente con su unidad
  (`20.0 %`, `92.0 %`, `10 s`, `0.5 %`, `120 s`). Al volver del teclado los refresca.
- `h1` a `h6`: las 6 alarmas más recientes de los dos sensores, la más nueva arriba, con el formato
  `DD/MM HH:MM S1 BAJO` (sensor 1 o 2; BAJO o ALTO). Las **activas** con `pco` = alarma (51427) y las
  ya cerradas con `pco` = texto_suave (25423). Si hay menos de 6, el resto queda vacío.
- `b_volver`: la Pi ordena `page principal`.

## 9. Página `confirmar` (PP = 08)

Pregunta de **Sí / No** compartida por todas las acciones delicadas (apagar un sensor, reiniciar, calibrar). La Pi
escribe la pregunta y el detalle; la pantalla solo avisa qué botón se tocó.

**Fondo:** `interna.png` (`fondo`, `pic` = 1). Los botones llevan `style` = flat, `sta` = solid color y `pco2` = `pco`.

| Nombre | Tipo | x | y | w | h | Fuente | Texto inicial | pco | bco | `txt_maxl` / notas |
|---|---|---|---|---|---|---|---|---|---|---|
| `titulo` | Text | 138 | 8 | 500 | 40 | 1 | Confirmar | blanco | crop image (`picc` 1) | 30; centrado |
| `t_pregunta` | Text | 32 | 90 | 736 | 130 | 1 | (vacío) | texto | tarjeta | 80; centrado, `isbr`=True |
| `t_detalle` | Text | 32 | 230 | 736 | 110 | 0 | (vacío) | texto_suave | tarjeta | 160; centrado, `isbr`=True |
| `b_no` | Button | 32 | 364 | 352 | 72 | 4 | No, cancelar | texto | boton | `bco2` = boton_pulsado |
| `b_si` | Button | 416 | 364 | 352 | 72 | 4 | Sí, continuar | texto | aviso (62880) | `bco2` = boton_pulsado |

**Eventos** (`printh 65 08 CC 00 FF FF FF` al soltar; además `play 1,0,0` en *Touch Press*): `b_si` = `01`, `b_no` = `02`,
página cargada (*Postinitialize*) = `FE`.

## 10. Página `sistema` (PP = 05)

Muestra cómo está el equipo y ofrece las acciones de mantenimiento. **Todas las acciones piden el PIN** y las que
interrumpen el servicio piden además confirmación. **Fondo:** `interna.png` (`fondo`, `pic` = 1).

| Nombre | Tipo | x | y | w | h | Fuente | Texto inicial | pco | bco | `txt_maxl` / notas |
|---|---|---|---|---|---|---|---|---|---|---|
| `titulo` | Text | 138 | 8 | 500 | 40 | 1 | Sistema | blanco | crop image (`picc` 1) | 30; centrado |
| `i1` a `i8` | Text | 32 | 84 + 44·n (n = 0 a 7) | 400 | 40 | 0 | (vacío) | texto | tarjeta | 40; `xcen`=0; una línea de información cada una |
| `b_reportes` | Button | 448 | 84 | 320 | 56 | 4 | Reportes USB | texto | boton | `bco2` = boton_pulsado |
| `b_servicios` | Button | 448 | 152 | 320 | 56 | 4 | Reiniciar servicios | texto | boton | |
| `b_reiniciar` | Button | 448 | 220 | 320 | 56 | 4 | Reiniciar equipo | texto | boton | |
| `b_auditoria` | Button | 448 | 288 | 320 | 56 | 4 | Verificar auditoría | texto | boton | |
| `res` | Text | 448 | 348 | 320 | 36 | 0 | (vacío) | texto_suave | tarjeta | 40; centrado; resultado de la última acción |
| `b_volver` | Button | 448 | 396 | 320 | 56 | 4 | Volver | texto | boton | |

**Eventos** (`printh 65 05 CC 00 FF FF FF` al soltar; además `play 1,0,0` en *Touch Press*): `b_reportes` = `01`,
`b_servicios` = `02`, `b_reiniciar` = `03`, `b_auditoria` = `04`, `b_volver` = `05`, página cargada = `FE`.

**Qué escribe la Pi** en `i1` a `i8` (una línea cada una, máximo unas 30 letras para que quepan):

| Línea | Ejemplo |
|---|---|
| `i1` | `Software 0.1.0-dev` |
| `i2` | `Pantalla: protocolo 1` |
| `i3` | `Encendido hace 3 d 4 h` |
| `i4` | `CPU 46 °C   RAM 38 %` (en rojo si pasa el umbral) |
| `i5` | `Disco libre 21.4 GB (72 %)` (en rojo si está bajo el umbral) |
| `i6` | `Base 0.9 MB   Cola 1840` |
| `i7` | `Núcleo OK · Pantalla OK` |
| `i8` | `PIN: de fábrica` (o `de la plataforma`, o `SIN PIN`) |

## 11. Página `config` (PP = 02)

Ajustes generales del equipo. Cada cambio pide el PIN (la Pi abre el teclado, sección 7). Apagar un sensor pide además
confirmación y **nunca se permite apagar el último sensor que queda**. **Fondo:** `interna.png` (`fondo`, `pic` = 1).

| Nombre | Tipo | x | y | w | h | Fuente | Texto inicial | pco | bco | `txt_maxl` / notas |
|---|---|---|---|---|---|---|---|---|---|---|
| `titulo` | Text | 138 | 8 | 500 | 40 | 1 | Configuración | blanco | crop image (`picc` 1) | 30; centrado |
| `h_aj` | Text | 32 | 84 | 368 | 28 | 0 | AJUSTES | texto_suave | tarjeta | 20; `xcen`=0 |
| `l_guardado` | Text | 32 | 116 | 190 | 44 | 0 | Guardado datos | texto | tarjeta | 20; `xcen`=0 |
| `l_pantalla` | Text | 32 | 168 | 190 | 44 | 0 | Pantalla | texto | tarjeta | 20; `xcen`=0 |
| `l_discrepancia` | Text | 32 | 220 | 190 | 44 | 0 | Dif. sensores | texto | tarjeta | 20; `xcen`=0 |
| `l_sensor1` | Text | 32 | 272 | 190 | 44 | 0 | Sensor 1 | texto | tarjeta | 20; `xcen`=0 |
| `l_sensor2` | Text | 32 | 324 | 190 | 44 | 0 | Sensor 2 | texto | tarjeta | 20; `xcen`=0 |
| `v_guardado` | Button | 228 | 116 | 172 | 44 | 4 | 15 s | texto | boton | `bco2` = boton_pulsado; `txt_maxl` 12 |
| `v_pantalla` | Button | 228 | 168 | 172 | 44 | 4 | 1 s | texto | boton | |
| `v_discrepancia` | Button | 228 | 220 | 172 | 44 | 4 | 0.5 % | texto | boton | |
| `v_sensor1` | Button | 228 | 272 | 172 | 44 | 4 | ACTIVO | texto | boton | la Pi escribe `ACTIVO` o `APAGADO` |
| `v_sensor2` | Button | 228 | 324 | 172 | 44 | 4 | ACTIVO | texto | boton | |
| `b_volver` | Button | 32 | 392 | 368 | 56 | 4 | Volver | texto | boton | |

| `h_eq` | Text | 432 | 84 | 336 | 28 | 0 | EQUIPO | texto_suave | tarjeta | 20; `xcen`=0 |
| `e1` a `e4` | Text | 432 | 116 + 50·n (n = 0 a 3) | 336 | 44 | 0 | (vacío) | texto | tarjeta | 40; `xcen`=0; solo lectura |

**Eventos** (`printh 65 02 CC 00 FF FF FF` al soltar; además `play 1,0,0` en *Touch Press*): `v_guardado` = `01`,
`v_pantalla` = `02`, `v_discrepancia` = `03`, `v_sensor1` = `04`, `v_sensor2` = `05`, `b_volver` = `06`, página
cargada = `FE`.

**Qué escribe la Pi:** `v_guardado` y `v_pantalla` con su unidad (`15 s`, `1 s`); `v_discrepancia` (`0.5 %`);
`v_sensor1` y `v_sensor2` (`ACTIVO` o `APAGADO`, este último con `pco` = alarma); `e1` a `e4`: `Nombre: ...`,
`ID: ...`, `S1: modelo, serie` y `S2: modelo, serie` (`(sin definir)` si faltan).

**Navegación desde `principal`:** `b_config` abre `config` y `b_sistema` abre `sistema` (la Pi lo ordena, como en
`alarmas`). `reportes` se abre desde `sistema` y `red` y `calibracion` quedan para las etapas siguientes.

## 12. Página `red` (PP = 03)

Estado de la conexión y cambio de red. **Conectar a otra red** pide el PIN, luego el nombre y la contraseña con el
teclado de texto (sección 13) y una confirmación. Se puede **tocar una de las redes cercanas** para saltarse el nombre.
**Fondo:** `interna.png` (`fondo`, `pic` = 1). Botones con `style` = flat, `sta` = solid color y `pco2` = `pco`.

| Nombre | Tipo | x | y | w | h | Fuente | Texto inicial | pco | bco | `txt_maxl` / notas |
|---|---|---|---|---|---|---|---|---|---|---|
| `titulo` | Text | 138 | 8 | 500 | 40 | 1 | Red | blanco | crop image (`picc` 1) | 30; centrado |
| `i1` a `i5` | Text | 32 | 84 + 44·n (n = 0 a 4) | 400 | 40 | 0 | (vacío) | texto | tarjeta | 40; `xcen`=0 |
| `h_redes` | Text | 448 | 84 | 320 | 28 | 0 | REDES CERCANAS | texto_suave | tarjeta | 20; `xcen`=0 |
| `res` | Text | 32 | 308 | 400 | 36 | 0 | (vacío) | texto_suave | tarjeta | 60; `xcen`=0; progreso o resultado de un cambio |
| `b_conectar` | Button | 32 | 348 | 400 | 48 | 4 | Conectar a otra red | texto | boton | `bco2` = boton_pulsado |
| `b_volver` | Button | 32 | 404 | 400 | 48 | 4 | Volver | texto | boton | |
| `n1` a `n4` | Button | 448 | 116 + 50·n (n = 0 a 3) | 320 | 44 | 0 | (vacío) | texto | boton | `bco2` = boton_pulsado; `txt_maxl` 30 |
| `b_buscar` | Button | 448 | 320 | 320 | 56 | 4 | Buscar redes | texto | boton | |

**Eventos** (`printh 65 03 CC 00 FF FF FF` al soltar; además `play 1,0,0` en *Touch Press*): `b_conectar` = `01`,
`b_buscar` = `02`, `n1` = `03`, `n2` = `04`, `n3` = `05`, `n4` = `06`, `b_volver` = `07`, página cargada = `FE`.

**Qué escribe la Pi:**

| Componente | Ejemplo |
|---|---|
| `i1` | `Conexión: WiFi «RedEjemplo»`, `Conexión: Cable (Ethernet)` o `Conexión: SIN RED` (en rojo) |
| `i2` | `IP: 192.168.10.20` |
| `i3` | `Señal: 99 %` |
| `i4` | `Internet: SÍ` o `Internet: NO` (en rojo) |
| `i5` | `ZeroTier: 10.99.99.10` o `ZeroTier: no conectado` |
| `n1` a `n4` | `RedEjemplo  99%` (las 4 redes de mejor señal; vacío si hay menos) |
| `res` | `Conectando a «Hospital»...`, `Conectado a «Hospital»`, `Contraseña incorrecta` (en rojo)... |

**Cambiar de red de forma segura:** el equipo prueba la red nueva **sin borrar la actual**. Si la nueva falla
(contraseña incorrecta, no se encuentra o no tiene internet y la anterior sí), la descarta y **vuelve a la red anterior**.
Durante el cambio el equipo puede quedar sin red hasta un minuto; la medición, las alarmas y la pantalla siguen funcionando.
En un equipo nuevo, sin red anterior, una red que conecta pero no sale a internet **se acepta y se avisa**.

## 13. Página `texto` (PP = 09)

Teclado completo para escribir el nombre y la contraseña de una red: letras minúsculas y mayúsculas, números y los
32 símbolos. Son **40 teclas de caracteres** que cambian de etiqueta según la **capa** (`abc`, `ABC` y `#+=`): la Pi
reescribe el `txt` de las 40 teclas al cambiar de capa y traduce cada toque al carácter de la capa vigente. Por eso las
teclas **no llevan el carácter en el evento, sino su posición** (`t_00` a `t_39`). **Fondo:** `interna.png`
(`fondo`, `pic` = 1). Todos los botones: `style` = flat, `sta` = solid color y `pco2` = `pco`.

| Nombre | Tipo | x | y | w | h | Fuente | Texto inicial | pco | bco | `txt_maxl` / notas |
|---|---|---|---|---|---|---|---|---|---|---|
| `titulo` | Text | 138 | 8 | 500 | 40 | 1 | Nombre de la red | blanco | crop image (`picc` 1) | 40; centrado; la Pi lo cambia |
| `valor` | Text | 32 | 80 | 540 | 52 | 2 | (vacío) | texto | fondo (63423) | 30; `xcen`=0; muestra lo escrito; la contraseña **se ve** salvo que se pulse `Ocultar` |
| `b_ver` | Button | 580 | 80 | 90 | 52 | 4 | Ocultar | texto | boton | 10; la Pi escribe `Ocultar`/`Ver` (vacío si es el nombre) |
| `b_borrar` | Button | 678 | 80 | 90 | 52 | 4 | Borrar | texto | boton | |
| `msg` | Text | 32 | 136 | 736 | 28 | 0 | (vacío) | texto_suave | tarjeta | 80; `xcen`=0; ayuda y errores |
| `t_00` a `t_09` | Button | 32 + 74·col (col = 0 a 9) | 168 | 68 | 52 | 4 | 1 2 3 4 5 6 7 8 9 0 | texto | boton | 4; fila 1 |
| `t_10` a `t_19` | Button | 32 + 74·col | 226 | 68 | 52 | 4 | q w e r t y u i o p | texto | boton | fila 2 |
| `t_20` a `t_29` | Button | 32 + 74·col | 284 | 68 | 52 | 4 | a s d f g h j k l ñ | texto | boton | fila 3 |
| `t_30` a `t_39` | Button | 32 + 74·col | 342 | 68 | 52 | 4 | z x c v b n m . - _ | texto | boton | fila 4 |
| `b_mayus` | Button | 32 | 402 | 100 | 52 | 4 | ABC | texto | boton | la Pi escribe `ABC`/`abc` |
| `b_simbolos` | Button | 138 | 402 | 100 | 52 | 4 | #+= | texto | boton | la Pi escribe `#+=`/`abc` |
| `b_espacio` | Button | 244 | 402 | 214 | 52 | 4 | espacio | texto | boton | |
| `b_limpiar` | Button | 464 | 402 | 90 | 52 | 4 | Limpiar | texto | boton | |
| `b_cancelar` | Button | 560 | 402 | 100 | 52 | 4 | Cancelar | texto | boton | |
| `b_aceptar` | Button | 666 | 402 | 102 | 52 | 4 | Aceptar | blanco | normal (1128) | `bco2` = 870 (verde oscuro); `pco2` blanco |

Las 40 teclas se hacen **copiando una y cambiando `objname`, `txt`, `x` e `y`**. Los textos iniciales son solo para que
se vea bien en el editor: la Pi los reescribe al cargar la página.

**Eventos** (`printh 65 09 CC 00 FF FF FF` al soltar):

**Sonido en TODAS las teclas (obligatorio):** *cada* componente táctil de esta página —las 40 teclas `t_00` a `t_39` y
los botones `b_mayus`, `b_simbolos`, `b_espacio`, `b_borrar`, `b_limpiar`, `b_ver`, `b_cancelar` y `b_aceptar`— lleva
`play 1,0,0` en **Touch Press**. Es la pantalla la que suena, en el instante del toque y sin esperar a la Pi, para que quien
escribe sepa que el toque se registró aunque la letra tarde en aparecer (a 9600 baudios puede tardar). Como las teclas se
hacen copiando una, **ponga el `play 1,0,0` en la primera `t_00` antes de copiarla**: así las 39 restantes lo heredan.
Después de copiar, revise una por una pulsándolas en *Debug*; una sola tecla muda es un error de la página.

| Teclas | Código `CC` (hexadecimal) |
|---|---|
| `t_00` a `t_09` (fila 1) | `00` a `09` |
| `t_10` a `t_19` (fila 2) | `0A` a `13` |
| `t_20` a `t_29` (fila 3) | `14` a `1D` |
| `t_30` a `t_39` (fila 4) | `1E` a `27` |
| `b_mayus`, `b_simbolos`, `b_espacio` | `30`, `31`, `32` |
| `b_borrar`, `b_limpiar`, `b_ver` | `33`, `34`, `35` |
| `b_cancelar`, `b_aceptar` | `36`, `37` |
| página cargada (*Postinitialize*) | `FE` |

**Qué hace la Pi:** el nombre admite hasta 32 caracteres y la contraseña hasta 63 (8 a 63 para una red con clave; vacía
significa red abierta si la red no se vio en la búsqueda). La contraseña **se ve mientras se escribe**, para poder
comprobar que está bien escrita; `Ocultar` la cambia a asteriscos (y `Ver` la muestra de nuevo). Las comillas dobles y la barra invertida se **escapan** al escribirlas en el `txt` (`\"` y `\\`).
**Por comprobar con la pantalla real:** abra la capa `#+=` y verifique que se ven las teclas `"` y `\`; si salen mal,
avíseme y las cambio por otra etiqueta.

**Velocidad del puerto serie (recomendado):** esta página repinta 40 teclas al cambiar de capa, y a 9600 baudios tarda
más de un segundo. En *Program.s* agregue `bauds=115200` junto a `volume=50`. La interfaz **detecta sola** la velocidad (prueba
115200 y después 9600), así que no hay que cambiar nada más ni queda incomunicada la pantalla.

## 15. Página `grafica` (PP = 0A)

Gráfica en tiempo de las dos señales de oxígeno. **La Pi la abre sola** cuando la pantalla `principal` lleva 10 s sin tocarse
(clave `pantalla.grafica_espera_s`; 0 la desactiva) y **un toque en cualquier parte la cierra**. Si salta una alarma sin acusar o el
núcleo deja de responder, la Pi vuelve a `principal` sola para que se vea el aviso. **Fondo:** `interna.png` (`fondo`, `pic` = 1).
Los textos llevan `sta` = solid color y `bco` = tarjeta (65535), salvo `titulo` (crop image, `picc` = 1).

| Nombre | Tipo | x | y | w | h | Fuente | Texto inicial | pco | `txt_maxl` / notas |
|---|---|---|---|---|---|---|---|---|---|
| `titulo` | Text | 138 | 8 | 500 | 40 | 1 | Oxígeno en el tiempo | blanco | 30; centrado |
| `s0` | **Waveform** | 72 | 84 | 700 | 290 | | | | ver abajo |
| `y_max` | Text | 8 | 84 | 58 | 28 | 0 | 24 | texto_suave | 10; `xcen`=2 (derecha); marca de arriba del eje |
| `y_med` | Text | 8 | 215 | 58 | 28 | 0 | 21 | texto_suave | 10; `xcen`=2; marca del medio |
| `y_min` | Text | 8 | 346 | 58 | 28 | 0 | 18 | texto_suave | 10; `xcen`=2; marca de abajo |
| `x_ini` | Text | 72 | 376 | 160 | 24 | 0 | -12 min | texto_suave | 10; `xcen`=0; lo que cubre la gráfica (la Pi lo escribe) |
| `x_fin` | Text | 612 | 376 | 160 | 24 | 0 | ahora | texto_suave | 10; `xcen`=2; fijo |
| `v1` | Text | 72 | 404 | 330 | 36 | 1 | S1  20.9 %  NORMAL | sensor1 (6969) | 30; `xcen`=0; la Pi cambia texto y color |
| `v2` | Text | 420 | 404 | 330 | 36 | 1 | S2  20.9 %  NORMAL | sensor2 (58306) | 30; `xcen`=0 |
| `msg` | Text | 72 | 442 | 700 | 22 | 0 | Toque la pantalla para volver | texto_suave | 40; centrado; fijo |
| `salir` | **Hotspot** | 0 | 0 | 800 | 480 | | | | **el último que se crea** (queda encima de todo); un toque en cualquier parte |

**Componente `s0` (Waveform):**

| Atributo | Valor |
|---|---|
| `ch` (canales) | **4** |
| `bco` | tarjeta (65535) |
| `gdc` (color de la rejilla) | 59197 |
| `gdw` (ancho de la celda) | 100 |
| `gdh` (alto de la celda) | 145 (así hay 3 líneas horizontales, alineadas con `y_max`, `y_med` e `y_min`) |
| `pco0` (canal 0, sensor 1) | 6969 (azul) |
| `pco1` (canal 1, sensor 2) | 58306 (naranja) |
| `pco2` (canal 2, límite bajo de alarma) | 51427 (rojo) |
| `pco3` (canal 3, límite alto de alarma) | 51427 (rojo) |
| `dis` (escala) | 100 |
| `dir` (dirección) | de izquierda a derecha (**por comprobar** con la pantalla real: una historia corta debe quedar pegada a la izquierda y, al llenarse la gráfica, desplazarse hacia la izquierda; si sale al revés, cambie `dir`) |

El tamaño importa: **700 píxeles de ancho = 700 puntos por canal**, y la Pi manda **una muestra por segundo** (la gráfica cubre unos 12 minutos).
Los valores de cada punto van de 0 a 255: el **0 es «sin dato»** (la línea baja al borde inferior) y la Pi ajusta sola el eje vertical
(`y_max`, `y_med` e `y_min` dicen su escala). Los dos canales de límite solo se dibujan si el límite cae dentro del eje.

**Eventos** (no lleva ningún `printh` en los textos ni en `s0`; solo el hotspot):

| Componente | Evento | Código |
|---|---|---|
| `salir` | *Touch Press* | `play 1,0,0` |
| `salir` | *Touch Release* | `printh 65 0A 01 00 FF FF FF` |
| Página `grafica` | *Postinitialize* | `printh 65 0A FE 00 FF FF FF` |

**Qué hace la Pi:** (1) al arrancar y cada vez que la pantalla enciende le ordena `sendxy=1`, para que la pantalla avise de **cualquier**
toque (no solo de los botones) y así saber que alguien la está usando; no hay que poner nada en el `.HMI`. (2) Toma una muestra por segundo
**siempre**, con la gráfica abierta o no, así al abrirla ya hay historia. (3) Al cargarse la página la dibuja entera con `addt` (una orden
`addt s0.id,CANAL,N` y, cuando la pantalla responde `FE FF FF FF`, los N bytes; la pantalla confirma con `FD FF FF FF`); mientras tanto no
manda otras órdenes. Si la pantalla no responde al `addt`, usa `add` punto por punto (más lento: unos 20 s a 9600 baudios, 1,7 s a 115200).
(4) Con la gráfica abierta agrega un punto por canal cada segundo (`add s0.id,CANAL,VALOR`) y la redibuja entera solo si cambia el eje.
(5) Si el `.tft` no trae esta página, la pantalla responde «página inexistente»: la Pi lo registra una vez y no vuelve a intentarlo
hasta que la pantalla se reinicie.

**Se recomienda 115200 baudios** (`bauds=115200` en *Program.s*): dibujar la gráfica entera con `addt` son unos 2,1 KB (1,4 KB sin los límites): ~2 s a
9600 y 0,2 s a 115200.

## 16. Página `reportes` (PP = 07)

Exporta las lecturas a una **memoria USB** como un **PDF protegido con contraseña**. Se abre desde `sistema` (botón
*Reportes USB*). **Fondo:** `interna.png` (`fondo`, `pic` = 1). Botones con `style` = flat, `sta` = solid color y
`pco2` = `pco`; los textos con `sta` = solid color y `bco` = tarjeta, salvo `titulo` (crop image, `picc` = 1).

| Nombre | Tipo | x | y | w | h | Fuente | Texto inicial | pco | bco | `txt_maxl` / notas |
|---|---|---|---|---|---|---|---|---|---|---|
| `titulo` | Text | 138 | 8 | 500 | 40 | 1 | Reportes | blanco | crop image (`picc` 1) | 30; centrado |
| `i2` | Text | 32 | 148 | 736 | 36 | 0 | (vacío) | texto | tarjeta | 60; `xcen`=0; días y registros del rango, o por qué no sirve (rojo) |
| `i1` | Text | 32 | 188 | 736 | 36 | 0 | (vacío) | texto | tarjeta | 60; `xcen`=0; estado de la memoria USB (rojo si falta o se llama distinto) 
| `prog` | Text | 32 | 332 | 736 | 28 | 0 | (vacío) | texto_suave | tarjeta | 60; `xcen`=0; lo que está haciendo (`Dibujando páginas... 40 %`) |
| `res` | Text | 32 | 364 | 736 | 36 | 0 | (vacío) | texto_suave | tarjeta | 70; `xcen`=0; resultado (rojo si falló) |
| `v_desde` | Button | 32 | 84 | 360 | 56 | 4 | Desde: 27/10/2026 | texto | boton | 24; `bco2` = boton_pulsado; se toca para cambiar la fecha |
| `v_hasta` | Button | 408 | 84 | 360 | 56 | 4 | Hasta: 27/10/2026 | texto | boton | 24; `bco2` = boton_pulsado ||
| `b_hoy` | Button | 32 | 236 | 360 | 56 | 4 | Imprimir hoy | texto | boton | `bco2` = boton_pulsado; el reporte del día de hoy, de una vez |
| `b_generar` | Button | 408 | 236 | 360 | 56 | 4 | Generar reporte | texto | boton | 20; la Pi lo cambia a `Generando...` mientras corre |
| `barra` | Progress bar | 32 | 304 | 736 | 24 | | | pco = normal (1128) | bco = boton | `val` = 0; la Pi escribe `val` de 0 a 100 |
| `b_volver` | Button | 32 | 404 | 736 | 56 | 4 | Volver | texto | boton | `bco2` = boton_pulsado |

**Eventos** (`printh 65 07 CC 00 FF FF FF` al soltar; además `play 1,0,0` en *Touch Press*): `v_desde` = `01`,
`v_hasta` = `02`, `b_hoy` = `03`, `b_generar` = `04`, `b_volver` = `05`, página cargada = `FE`.

**Cómo se usa (todo lo decide la Pi):**

1. Al abrir la página el rango es **el día de hoy**. Tocar `v_desde` o `v_hasta` abre el **teclado numérico** (sección 7) para
   escribir la fecha con 8 dígitos (`DDMMAAAA`; la Pi muestra las barras: `27/10/2026`). Las fechas son **días completos**
   (de las 00:00 del primer día a las 24:00 del último, en la hora de Colombia, `America/Bogota`): no se escriben horas.
2. **Máximo 7 días** por reporte (un reporte más largo tardaría demasiado y exigiría mucho a la Raspberry Pi). No hay fechas futuras.
3. `i2` dice cuántos registros trae el rango (`3 día(s) · 17280 registros por sensor`); si no sirve, lo dice en rojo.
4. **La memoria USB debe llamarse igual que el equipo** (el nombre que se ve en `config`, por ejemplo `ANZD-600226001`).
   Es un seguro más: un reporte no se copia a una memoria cualquiera. `i1` lo dice. **Ojo:** una memoria **FAT/FAT32 no admite
   más de 11 letras** en su nombre: con un nombre de 14 hay que **formatearla como exFAT o NTFS** y ponerle ese nombre.
5. `b_generar` (o `b_hoy`, que genera el de hoy sin tocar fechas) **pide el PIN** y arranca. El reporte lo hace el núcleo en un
   proceso aparte, con prioridad baja: **la medición y las alarmas no se enteran**. Mientras corre, **la pantalla queda
   bloqueada** (ver abajo): `b_generar` dice `Generando...`, los botones se ven apagados y `barra` y `prog` muestran el avance.
6. Al terminar, `res` dice cuántas filas y páginas tiene y los primeros 12 caracteres de su **huella SHA-256**. La huella
   completa queda en el archivo `.sha256` junto al PDF y en el registro de eventos del equipo (`REPORTE_GENERADO`).

**Bloqueo de la pantalla (D-045).** Desde que se acepta el PIN hasta que el reporte termina (o falla) la pantalla **no atiende
ningún toque**, para que nada lo interrumpa: no se puede salir de la página, cambiar las fechas ni pedir otro reporte, y **no hay
botón Cancelar**. La Pi lo hace de dos maneras: descarta los toques y le ordena a la pantalla `tsw 255,0` (deshabilita el toque de
todos los componentes de la página; lo repite cada vez que la página carga y lo devuelve con `tsw 255,1` al terminar). Mientras tanto
pone `b_generar`, `b_hoy`, `b_volver`, `v_desde` y `v_hasta` en `pco` = inactivo, y `res` = `No toque la pantalla ni retire la memoria USB`
(`pco` = aviso). **No hace falta ningún componente nuevo ni cambiar nada en el `.HMI`.** Si el núcleo deja de responder o se corta la
luz, la pantalla se libera sola (el bloqueo no es un estado guardado). Un reporte de una semana tarda ~30 s; el tope es de 15 min.
El sonido y los relevos de alarma siguen funcionando; solo el acuse con la pantalla espera a que termine.

**El PDF:** se abre con una **contraseña que es el nombre del equipo** (cifrado AES-256); se puede ver, imprimir y **copiar su texto** (para pasar los datos a una hoja de cálculo), no editar. Una fila por intervalo de guardado, con el número de registro de cada sensor en la base de datos, la fecha y la hora,
y la lectura de los dos sensores. **Las filas con alerta de oxígeno (BAJO o ALTO) van en rojo y negrita**, con el umbral que
tenía la alarma al dispararse; la discrepancia entre sensores no se marca. Lleva una primera hoja de resumen con el logo de SPEAL, pequeño, arriba a la derecha (el nombre del equipo queda a su izquierda) (rango, estadísticas
de cada sensor, intervalo de guardado, alertas, estado de la cadena de auditoría; no muestra la versión del software ni el modelo o la serie de los sensores) y, al final, las alarmas de oxígeno del rango y el estado de los sensores (cuándo se apagaron, encendieron o quedaron sin señal; explica las celdas con «—»).
El nombre del archivo no lleva el nombre del equipo (es la contraseña): `G2_reporte_2026-10-21_a_2026-10-27_20261027-1015.pdf`.

**Qué escribe la Pi:**

| Componente | Ejemplo |
|---|---|
| `v_desde`, `v_hasta` | `Desde: 21/10/2026`, `Hasta: 27/10/2026` |
| `i2` | `7 día(s) · 40320 registros por sensor`, `Máximo 7 días por reporte` (rojo), `Sin registros en esas fechas` (rojo) |
| `i1` | `Memoria USB «ANZD-600226001» lista`, `Inserte la memoria USB llamada «ANZD-600226001»` (rojo) |
| `b_generar` | `Generar reporte` o `Generando...` |
| `barra` (`val`) y `prog` | `40` y `Dibujando páginas... 40 %` (solo mientras corre) |
| `res` | `No toque la pantalla ni retire la memoria USB` (aviso, mientras corre), `Listo: 40320 filas, 730 págs. Huella b3ae8fcc33fe`, `Reporte cancelado`, `La memoria USB se llama «X»; debe llamarse «...»` (rojo) |

Un reporte de una semana con un guardado cada 15 s son unas 40 000 filas (~730 páginas) y tarda unos 30 s en la Raspberry Pi.

**Teclado de fechas:** reutiliza la página `teclado` (sección 7): la Pi escribe `teclado.titulo.txt` = `Fecha del reporte` y
`teclado.t_titulo.txt` = `Desde (día/mes/año)` o `Hasta (día/mes/año)`. No hace falta cambiar nada en el `.HMI` (la tecla del
punto no hace nada en este modo).

## 17. Página `calibracion` (PP = 04)

Calibración de **un punto de un sensor con gas patrón** (D-048, D-049): el punto **bajo** (0,0 % de nitrógeno, o el aire a 20,9 %) corrige el
cero y el punto **alto** (98,0 %, 99,8 % u otro valor que se teclea) corrige la ganancia (la pendiente). Se abre desde `principal`
(botón `b_calib`, que ya existe). **Fondo:** `interna.png` (`fondo`, `pic` = 1). Botones con `style` = flat, `sta` = solid color y
`pco2` = `pco`; los textos con `sta` = solid color y `bco` = tarjeta, salvo `titulo` (crop image, `picc` = 1).
**Esta versión reemplaza a la primera de la sección (que solo calibraba el cero en aire con un botón por sensor).**

| Nombre | Tipo | x | y | w | h | Fuente | Texto inicial | pco | bco | `txt_maxl` / notas |
|---|---|---|---|---|---|---|---|---|---|---|
| `titulo` | Text | 138 | 8 | 500 | 40 | 1 | Calibración | blanco | crop image (`picc` 1) | 30; centrado |
| `v_s1` | Button | 32 | 84 | 360 | 56 | 4 | Sensor 1  20.9 % | texto | boton | 24; `bco2` = boton_pulsado; elige el Sensor 1 (la Pi pinta `bco` del elegido) |
| `v_s2` | Button | 408 | 84 | 360 | 56 | 4 | Sensor 2  20.9 % | texto | boton | 24; `bco2` = boton_pulsado; elige el Sensor 2 |
| `b_bajo` | Button | 32 | 148 | 176 | 56 | 4 | Bajo 0.0 % | texto | boton | `bco2` = boton_pulsado; el gas pasa a 0,0 % |
| `b_aire` | Button | 216 | 148 | 176 | 56 | 4 | Aire 20.9 % | texto | boton | `bco2` = boton_pulsado; el gas pasa a 20,9 % |
| `v_gas` | Button | 408 | 148 | 360 | 56 | 4 | Gas: 0.0 % | texto | boton | 24; `bco2` = boton_pulsado; abre el teclado numérico para escribir otro valor |
| `i1` | Text | 32 | 212 | 736 | 36 | 0 | (vacío) | texto | tarjeta | 60; `xcen`=0; qué se va a calibrar (sensor, gas y punto), o qué sensor se calibra |
| `i2` | Text | 32 | 252 | 736 | 36 | 0 | (vacío) | texto | tarjeta | 60; `xcen`=0; la calibración vigente del sensor elegido, o la variación de la señal |
| `i3` | Text | 32 | 292 | 736 | 36 | 0 | (vacío) | texto | tarjeta | 60; `xcen`=0; indicación, o el tiempo transcurrido |
| `barra` | Progress bar | 32 | 334 | 736 | 24 | | | pco = normal (1128) | bco = boton | `val` = 0; la Pi escribe `val` de 0 a 100 (tiempo usado del máximo) |
| `res` | Text | 32 | 362 | 736 | 36 | 0 | (vacío) | texto_suave | tarjeta | **80**; `xcen`=0; resultado (rojo si falló) |
| `b_iniciar` | Button | 32 | 404 | 360 | 56 | 4 | Calibrar este punto | texto | boton | 24; `bco2` = boton_pulsado; la Pi lo cambia a `Calibrando...` mientras corre |
| `b_volver` | Button | 408 | 404 | 360 | 56 | 4 | Volver | texto | boton | `bco2` = boton_pulsado |

**Eventos** (`printh 65 04 CC 00 FF FF FF` al soltar; además `play 1,0,0` en *Touch Press*): `v_s1` = `01`, `v_s2` = `02`, `b_bajo` = `03`,
`b_aire` = `04`, `v_gas` = `05`, `b_iniciar` = `06`, `b_volver` = `07`, página cargada = `FE`.

**Cómo se usa (todo lo decide la Pi):**

1. Se conecta al sensor el **gas patrón** (o se deja al aire). Se elige el sensor (`v_s1` o `v_s2`) y el gas: `b_bajo` (0,0 %), `b_aire`
   (20,9 %) o `v_gas`, que abre el **teclado numérico** (sección 7) para escribir la concentración (de 0 a 100 %, con punto decimal: `99.8`).
   Elegir no pide PIN ni cambia nada. `i1` dice a qué punto corresponde: **menos de 50 % es el punto bajo (corrige el cero); 50 % o más es el
   punto alto (corrige la ganancia)**.
2. `b_iniciar` pide el **PIN** y una **confirmación** (página `confirmar`: `¿Calibrar el Sensor 2 con gas de 99.8 %?`) y ordena la calibración
   al núcleo. Solo **un sensor a la vez**, y solo si **el otro sigue encendido** (queda vigilando); si no, la Pi lo dice en `res` y no pide el PIN.
3. **Cada punto se calibra por separado** y en cualquier orden. La calibración vigente del sensor se compone con el último punto bajo y el
   último punto alto medidos: con los dos, el equipo corrige cero y ganancia; con solo el bajo, el cero (ganancia 1); con solo el alto, la
   ganancia (cero 0). `i2` muestra lo vigente (`Vigente: gan. 1.005  cero -0.20 %  bajo 0  alto 98`; `--` es un punto sin medir). Volver a medir un
   punto reemplaza al anterior de su lado.
4. El núcleo mide: espera una señal **estable** (variación de 0,3 % o menos durante 30 s) y promedia esos 30 s. Tarda desde ~30 s hasta **5 minutos**.
5. La calibración **falla y no se aplica nada** si la ganancia queda fuera de **0,90 a 1,10**, si el cero pasa de **±3 %**, si los dos puntos
   distan menos de **50 puntos**, o si la señal no se estabiliza. Casi siempre es que el sensor no tenía el gas indicado. Queda registrada como fallida.
6. **Mientras dura**, las alarmas y las lecturas guardadas de **ese sensor** se suspenden (el otro sigue vigilado, con sus alarmas, relevos y
   sonido), la principal muestra `CALIBRANDO` (azul) en su recuadro y suena la voz **«Calibrando»** cada pocos segundos (sección 6). Una
   alarma del otro sensor tiene prioridad en el sonido.
7. **Bloqueo de la pantalla (igual que en reportes, D-045):** desde que se confirma hasta que termina la pantalla **no atiende ningún toque**
   (`tsw 255,0`, que la Pi repite en cada carga de página y devuelve con `tsw 255,1` al terminar) y no hay botón Cancelar. Si el núcleo
   deja de responder o se corta la luz, se libera sola. El tope de 5 minutos hace que nunca sea indefinido.

**Qué escribe la Pi:**

| Componente | Ejemplo |
|---|---|
| `v_s1`, `v_s2` | `Sensor 1  20.9 %`, `Sensor 2  APAGADO`, `Sensor 2  SIN SENSOR`; `bco` = boton_pulsado el elegido; en `pco` = inactivo mientras calibra |
| `b_bajo`, `b_aire` | `bco` = boton_pulsado si su valor es el gas elegido |
| `v_gas` | `Gas: 98.0 %`, `Gas: 99.95 %` |
| `i1`, `i2`, `i3` (en reposo) | `Sensor 1 con gas de 98.0 %: punto alto (corrige la ganancia)`; `Vigente: de fábrica (sin calibrar)`; `Ponga el gas y toque Calibrar. Tarda de 1 a 5 min.` |
| `i1`, `i2`, `i3` (calibrando) | `Calibrando Sensor 1 con gas de 98.0 %`; `Variación 1.80 % (debe bajar de 0.30 %)` o `Esperando una señal estable...`; `Tiempo 45 s de 300 s como máximo` |
| `barra` (`val`) | `15` (solo mientras calibra) |
| `b_iniciar` | `Calibrar este punto` o `Calibrando...` |
| `res` | `No toque la pantalla ni mueva el sensor` (aviso, mientras calibra); al terminar: `Sensor 1: Punto alto 98 % listo: gan. 1.005, cero +0.00 %`, o en rojo `Sensor 1: Mide 90.1 % con gas de 0 %. Cero -90.1 % pasa de ±3: ¿gas correcto?`; `El Sensor 2 no está activo`, `Encienda el otro sensor: debe seguir vigilando` (rojo) |

**Teclado del gas:** reutiliza la página `teclado` (sección 7): la Pi escribe `teclado.titulo.txt` = `Gas patrón` y `teclado.t_titulo.txt` =
`Concentración de O2 (%)`; la tecla del punto sí funciona en este modo. No hace falta cambiar nada en el `.HMI`. **Confirmar:** reutiliza la
página `confirmar` (sección 9). El recuadro de estado de la principal ya trae el color `calibrando` (726) y el texto `CALIBRANDO` (secciones 4 y 5).

## 18. Cómo probar lo construido

1. En el editor, botón **Debug**: simula la pantalla sin dispositivo para revisar el diseño.
2. Guardar y **Compile**: genera el `.tft` (ruta en *File → Open build folder*).
3. Cargar el `.tft` a la pantalla: la primera vez, con tarjeta microSD o con un adaptador USB-TTL;
   después, desde la Raspberry Pi por el puerto serie (herramienta `g2ctl pantalla-cargar`, por
   construir).
4. Conectar la pantalla a la Pi y correr `tools/banco/sonda_nextion.py` (debe responder el modelo).
5. Probar los eventos con el emulador y con la pantalla real.

## 19. Páginas que faltan (etapas siguientes)

Ninguna por ahora. Queda para más adelante el método SPOC guiado del fabricante (D-039), que usa el botón físico del sensor y solo se registra.
