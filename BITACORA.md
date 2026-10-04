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
