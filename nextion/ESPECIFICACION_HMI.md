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
- **Orden de las páginas** (determina su número interno): principal, alarmas, config, red,
  calibracion, sistema, teclado, reportes. Las páginas nuevas se agregan **al final**; no se
  reordenan.
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

| Nombre | Valor | Uso |
|---|---|---|
| fondo | 63423 | fondo de la página |
| tarjeta | 65535 | tarjetas y avisos |
| texto | 6438 | texto principal |
| texto_suave | 25423 | títulos de tarjeta |
| barra | 6504 | barra superior |
| normal | 1128 | estado normal (verde) |
| alarma | 51427 | alarma alta o baja (rojo) |
| aviso | 62880 | advertencia y botón de acuse (ámbar) |
| calibrando | 726 | calibración en curso (azul) |
| inactivo | 27568 | sin señal o deshabilitado (gris) |
| boton | 59197 | botón en reposo |
| boton_pulsado | 48730 | botón pulsado |
| blanco | 65535 | texto sobre barra y estados |

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
| `aviso` | "Sin alarmas" (bco tarjeta, pco texto) o el texto de la alarma activa (bco alarma, pco blanco) |
| `red_s` | `WIFI OK`, `CABLE OK`, `SIN RED` |
| `cola_s` | `COLA 0`, `COLA 1250`... |
| `hora` | `HH:MM` |

## 6. Sonido de pulsación (pitido)

La pantalla tiene altavoz pero **no zumbador**, así que el comando `beep` no suena: el pitido es un
archivo de audio corto que se reproduce con `play`. El archivo (`nextion/sonidos/pulsacion.wav`:
tono de 2 kHz, 70 ms, mono, 16 bits, 16 kHz) se genera con `tools/generar_sonido_pulsacion.py`.

1. En el panel **Audio** del editor → **Add**, agregar `pulsacion.wav`. Debe ser **el primer audio**
   del proyecto (id 0). Los sonidos de alarma se agregarán después (id 1 en adelante).
2. En el evento **Touch Press** de cada botón de navegación (y de Acusar), poner `play 1,0,0`
   (canal 1, audio 0, sin repetir). El **canal 0 queda reservado para las alarmas**, así el pitido
   de un toque no corta una alarma que esté sonando.
3. Volumen: en la pestaña **Program.s** (se ejecuta al encender la pantalla) fijar `volume=70`
   (0 a 100; la variable se llama `volume`, no `vol`: con `vol` el editor da *Invalid Variables*).
   Es persistente: la pantalla la recuerda y la usa como volumen al encender. Si el editor no
   admite la asignación en Program.s, ponerla en el *Postinitialize* de `principal`.
   El valor definitivo se ajusta probando con la pantalla real.
4. Regla para las páginas siguientes: **todo botón que el usuario pulse lleva `play 1,0,0` en su
   Touch Press**; los componentes que solo muestran no.

El pitido lo reproduce la propia pantalla, sin ir y volver a la Pi, para que suene al instante
aunque la Pi esté ocupada (decisión de D-029). Si `g2-ui` falla, los toques siguen sonando, pero
no navegan. Si el editor rechaza el `.wav` o el canal 1 no existe en este modelo, se ajusta al
probar (otro formato de audio o el canal 0).

## 7. Cómo probar lo construido

1. En el editor, botón **Debug**: simula la pantalla sin dispositivo para revisar el diseño.
2. Guardar y **Compile**: genera el `.tft` (ruta en *File → Open build folder*).
3. Cargar el `.tft` a la pantalla: la primera vez, con tarjeta microSD o con un adaptador USB-TTL;
   después, desde la Raspberry Pi por el puerto serie (herramienta `g2ctl pantalla-cargar`, por
   construir).
4. Conectar la pantalla a la Pi y correr `tools/banco/sonda_nextion.py` (debe responder el modelo).
5. Probar los eventos con el emulador y con la pantalla real.

## 8. Páginas que faltan (etapas siguientes)

alarmas (umbrales, acuse, historial), config (intervalos, habilitar sensores), red (estado, IP,
WiFi), calibracion (guiada), sistema (base de datos, reinicios, salud, versión), teclado (numérico,
para el PIN y los valores) y reportes (exportar a memoria USB).
