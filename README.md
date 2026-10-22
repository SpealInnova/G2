# G2

Nueva versión del analizador de oxígeno de SPEAL: sensor **analógico**, Raspberry Pi, pantalla
Nextion y plataforma web **sp-peek.com**. Primera versión para **hospitales**.

> Este proyecto se documenta para poder escribir después el manual técnico del equipo: cada
> decisión tiene su justificación en la [memoria técnica](MEMORIA_TECNICA.md) y el trabajo se
> registra día a día en la [bitácora](BITACORA.md).

## Estado

| Parte | Estado |
|---|---|
| Base de datos interna (SQLite): esquema, auditoría con huellas SHA-256, cola de envío, catálogo de configuración y capa de datos | **Hecho** y probado |
| Convertidor analógico-digital ADS1263 (controlador, emulador y herramientas de banco) | **Hecho**; validado con una fuente de prueba |
| Raspberry Pi preparada (SPI, I²C, UART) y herramienta `g2ctl` | **Hecho** |
| Núcleo `g2-core` (lectura, promedio, alarmas, almacenamiento) | Hecho como servicio de systemd con watchdog y probado con el ADC real; faltan los relevos por GPIO y la salud de la Pi |
| Interfaz `g2-ui` de la pantalla | Hechas del lado de la Pi: principal, alarmas, config, sistema, confirmar, red y teclado de texto (PIN, acuse, reinicios, cambio de red con reversión); faltan reportes y calibración |
| Servicio de envío a la plataforma | Por construir (diseño en la memoria técnica) |
| Pantalla Nextion | Páginas principal, teclado y alarmas listas (v0.2.0); faltan configuración, red, calibración, sistema y reportes |
| Alertas por correo en la plataforma | Construidas en una rama de la plataforma, sin publicar |

## Para empezar

```
set PYTHONPATH=src
python -m unittest discover -s tests
```

Requiere Python 3.10 o superior. Las pruebas no necesitan hardware: el ADC y la pantalla tienen
emuladores.

## Qué hay en el repositorio

| Carpeta o archivo | Contenido |
|---|---|
| `src/g2/almacenamiento/` | Base de datos: migraciones SQL, capa de datos, cadena de auditoría |
| `src/g2/configuracion/` | Catálogo de claves de configuración con sus valores por defecto |
| `src/g2/hardware/` | Controlador del ADS1263, su emulador y el puerto SPI de la Raspberry Pi |
| `src/g2/ctl.py` | Herramienta `g2ctl` para operar el equipo por SSH |
| `tools/` | Generadores (cadena de auditoría, diagrama) y herramientas de banco del ADC |
| `scripts/aprovisionar_pi.sh` | Prepara el sistema de la Raspberry Pi (repetible) |
| `tests/` | Pruebas automáticas |

## Documentación

- [Memoria técnica](MEMORIA_TECNICA.md): decisiones D-001 en adelante, con su justificación y lo pendiente.
- [Bitácora](BITACORA.md): registro cronológico del trabajo.
- [Hardware](HARDWARE.md): diagrama de bloques, pines y direcciones I²C.
- [Diagrama entidad-relación](DIAGRAMA_ER.md) de la base de datos.
- [Contexto](CONTEXTO.md): lo aprendido del equipo anterior y la lista de mejoras.

## Novedades

Esta sección se genera con `python tools/actualizar_novedades.py` a partir de los cambios
publicados (no se edita a mano).

<!-- NOVEDADES:INICIO -->

### 2026-10-22

- **Pantalla Nextion v0.3.0 y servicios g2-ui y g2-core: PIN, red, sistema y configuración**
  - Interfaz g2-ui (src/g2/pantalla): la pantalla es "tonta" y la Pi manda; páginas principal, alarmas, teclado (PIN y valores), confirmar, sistema, configuración, red y teclado de texto completo con capas abc, ABC y símbolos. La con…
  - PIN de acceso (D-038): se guarda solo su huella PBKDF2, vale 5 minutos y se bloquea 60 s tras 3 fallos; todas las acciones de cambio lo piden. El valor de fábrica no está en el repositorio.
  - Servicios systemd con vigilancia por progreso (g2-core y g2-ui), regla polkit para reiniciar servicios y gestionar la red sin sudo, e instalador scripts/instalar_servicios.sh; comunicación por archivos en /run/g2 con permisos 060…
  - Salud de la Raspberry Pi (CPU, memoria, disco, base y cola) con alarmas del sistema, y verificación de la cadena de auditoría desde la pantalla; migraciones 005 a 007.
  - Cambio de red desde la pantalla (D-040) con reversión automática si la red nueva falla, apoyo a la primera instalación sin red, y la contraseña sin rastro en base, eventos, auditoría ni registros. Transporte seguro desde la plata…

### 2026-10-21

- **Núcleo g2-core, primera versión: lectura, alarmas por sensor y almacenamiento** (`73bb374`)
  - Paquete src/g2/nucleo y arranque con python3 -m g2.nucleo: convierte la tensión de cada sensor a % de oxígeno (10 mV por %, con la corrección de la calibración vigente) y guarda un registro por sensor cada 15 s con promedio, míni…
  - Motor de alarmas por sensor (D-032): oxígeno bajo, oxígeno alto y sensor sin señal, más la discrepancia entre sensores como alarma del sistema; con retardo, histéresis, acuse que silencia el sonido 2 minutos y relevos de oxígeno…
  - Lectura del ADS1263 que no se detiene ante errores y reconfigura el chip si se reinicia; salidas de los relevos solo emuladas, pendientes de la decisión de D-033; cierre ordenado que guarda el intervalo en curso.
  - Probado con el ADC real en la Raspberry Pi y un divisor de voltaje: 1.030 V en el multímetro y 1029.99 mV en el núcleo; 73 pruebas nuevas, 209 en total, también en la Pi.
  - Acceso remoto con ZeroTier instalado desde el repositorio oficial y la memoria técnica con D-034 (núcleo) y D-035 (acceso remoto); README actualizado.

### 2026-10-20

- **Pantalla Nextion v0.2.0: páginas teclado y alarmas; decisiones de alarmas y relevos** (`76c5972`)
  - Pantalla v0.2.0: se suman la página del teclado numérico (PIN y valores) y la página de alarmas (umbrales, retardo, histéresis, tiempo de acuse e historial reciente), con fondo para páginas interiores y sonido de alarma.
  - Alarmas por sensor (D-032): aviso visual en el recuadro de cada sensor, parpadeo hasta acusar y sonido repetido por la Pi; Acusar acusa ambos sensores y silencia el sonido 2 minutos (D-031, nueva clave alarma.acuse_silencio_s).
  - Relevos de alarma (D-033): placa de 3 relevos, uno para oxígeno bajo y otro para oxígeno alto, energizados en normal; análisis del riesgo del estado de los pines en el reinicio y opciones A, B y C pendientes de decisión y de medi…
  - Herramientas: tools/banco/pantalla.py (envía órdenes a la pantalla y decodifica los toques, con pruebas), generadores del fondo interior y del sonido de alarma.
  - Especificación del HMI ampliada (teclado, alarmas, sonido de alarma, largo de textos) y manifiesto de versiones con las huellas SHA-256.

### 2026-10-16

- **Pantalla Nextion v0.1.0: página principal terminada y herramienta de versiones** (`59a7025`)
  - Página principal de la pantalla (versión 0.1.0): fondo con el logotipo de SPEAL, tarjetas de los dos sensores, línea de avisos y 6 botones con pitido de pulsación; protocolo de eventos versión 1.
  - tools/publicar_pantalla.py: copia el .tft compilado a nextion/build/ con su versión y registra las huellas SHA-256 en nextion/MANIFIESTO.md; una versión publicada no se puede sobrescribir.
  - Especificación del HMI: estado inicial de los textos de estado y largo máximo de los textos (txt_maxl).
  - Programas de la pantalla (.HMI y .tft) con Git LFS; etiqueta pantalla-v0.1.0.
- **Pantalla Nextion: primer proyecto del editor (.HMI) y su compilado (.tft) con Git LFS** (`2216bd2`)
  - Proyecto g2.HMI del Nextion Editor y su compilado g2.tft, versionados con Git LFS (primera subida): página principal en construcción, con fondo, fuentes y sonido de pulsación de la especificación.
- **Pantalla Nextion: especificación del HMI, fondo, fuentes y sonido; novedades en el README** (`61d6cf8`)
  - Especificación del HMI (nextion/ESPECIFICACION_HMI.md): convenciones, protocolo con códigos propios de evento, página principal, pitido de pulsación y reglas del editor.
  - Fondo de la pantalla con el logotipo de SPEAL, ajustado a la cuadrícula de 800×480 (tools/ajustar_fondo_nextion.py), fuentes de la pantalla y sonido de pulsación (tools/generar_sonido_pulsacion.py).
  - Botón Acusar (D-031): silencia solo el sonido de la pantalla, los relevos no se desactivan y el sonido vuelve a los 2 minutos; nueva clave de configuración alarma.acuse_silencio_s (24 claves).
  - Programas de la pantalla con Git LFS (.HMI y .tft): el proyecto del editor se sube solo en hitos.
  - README como página principal con novedades por fecha generadas desde el historial (tools/actualizar_novedades.py) y sonda de la pantalla (tools/banco/sonda_nextion.py).

### 2026-10-09

- **Pruebas A/B del ruido y validacion del ADC con multimetro** (`3bf1ce8`)
  - tools/banco/comparar_capturas.py: compara capturas del ADC lado a lado (promedio, desviacion, ruido por banda y desviacion de Allan) para pruebas A/B.
  - Memoria tecnica (D-025): el ruido de la fuente de prueba venia del riel de 3.3 V de la Pi; con una pila el ruido sobre 0.1 Hz queda al nivel del piso del ADC (< 7 uV rms) y no cambia con la carga de la Pi. Comparacion simultanea…
  - Bitacora actualizada (cambio de IP de la Pi por DHCP verificado por la huella de la llave).

### 2026-10-08

- **Base de datos de G2: catalogo de configuracion, capa de datos, g2ctl y diagrama ER** (`ea26773`)
  - Catalogo de 23 claves de configuracion (src/g2/configuracion): tipo, valor por defecto, limites, unidad y quien puede cambiarlas; reglas entre claves (umbral de oxigeno bajo menor que el alto, umbrales de disco). Valores por defe…
  - Capa de datos Almacen (src/g2/almacenamiento/almacen.py): unica via de escritura del nucleo, con transacciones, datos de tiempo automaticos, configuracion con historial, sensores, calibracion, lecturas, salud, eventos agrupados,…
  - Herramienta g2ctl (python3 -m g2.ctl): crear y consultar la base, verificar la cadena de auditoria, ver y cambiar configuracion, dar de alta sensores.
  - DIAGRAMA_ER.md y tools/generar_diagrama_er.py: diagrama entidad-relacion generado desde el esquema real (Mermaid).
  - 47 pruebas nuevas (132 en total), verificadas tambien en la Raspberry Pi.
- **Valores por defecto, WiFi sin ahorro de energia y analisis de ruido del ADC** (`32fb587`)
  - D-027: valores por defecto de la configuracion definidos por el usuario (pantalla 1 s, alarma de oxigeno bajo 20 % y alto 92 %, configurables por Nextion y plataforma, temperatura de la Pi 60 C, RAM 85 %).
  - scripts/aprovisionar_pi.sh: desactiva el ahorro de energia del WiFi (NetworkManager y de inmediato con iw) e instala iw; la causa probable de cortes de SSH de la sesion.
  - tools/banco/ver_adc.py: muestra voltios con 6 decimales, sin notacion cientifica (--detalle agrega ruido y % de O2 equivalente).
  - tools/banco/capturar_adc.py y analizar_ruido.py: captura de series y analisis de espectro, desviacion de Allan y ruido restante segun el corte de un filtro.
  - Memoria tecnica: comparacion con el multimetro (1.660 V), resultado del analisis de ruido y metodo para fijar la frecuencia de corte del filtro.
- **Controlador del ADS1263, aprovisionamiento de la Pi y primeras mediciones** (`9a894fa`)
  - Controlador del ADC ADS1263 (src/g2/hardware): reinicio, identificacion, configuracion verificada, lectura diferencial con suma de control, deteccion de reinicio del chip y tiempos maximos; emulador con inyeccion de fallas y puer…
  - Migracion 004: columnas razon y so_boot_id en arranque (cada inicio de g2-core deja su fila) y huellas de la cadena de auditoria actualizadas; el generador de la cadena se divide en funciones reutilizables (la migracion 003 no ca…
  - scripts/aprovisionar_pi.sh: habilita SPI e I2C, libera el UART para la Nextion, apaga el Bluetooth e instala sqlite3 y tmux (repetible, con respaldo de la configuracion de arranque).
  - Herramientas de banco (tools/banco): sonda del ADS1263, medicion y comparacion de configuraciones, y monitor en vivo.
  - HARDWARE.md (diagrama, pines, direcciones I2C) y decisiones D-018 a D-026 en MEMORIA_TECNICA.md; BITACORA.md actualizada.

### 2026-10-04

- **Base de G2: contexto, decisiones, esquema SQLite con cadena de auditoria** (`d991cfa`)
  - CONTEXTO.md y Mejoras.txt: origen del proyecto (lo aprendido del equipo ANZD-600226001 y la lista de funciones deseadas).
  - MEMORIA_TECNICA.md y BITACORA.md: decisiones D-001 a D-016 con su justificacion, y registro cronologico del trabajo.
  - Base de datos interna (SQLite): migraciones 001 a 003 (esquema, catalogo de eventos y alarmas, cadena de auditoria SHA-256), cola de envio por referencia con borrado solo tras confirmacion de la plataforma, y vista de trazabilida…
  - Modulos de almacenamiento (base, migraciones, auditoria) y 55 pruebas.
  - tools/generar_cadena.py: genera la migracion 003.

### 2026-10-03

- **Initial commit** (`81e0d27`)

<!-- NOVEDADES:FIN -->
