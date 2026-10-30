# Contrato entre el equipo G2 y la plataforma (etapa 1: subida de datos)

Para quien programe el lado de la plataforma (`sp-peek.com`). Lo cumple `g2-uplink` (D-046); el código del equipo está en
`src/g2/uplink/`. **Esta etapa solo sube datos: la plataforma no manda órdenes ni cambia la configuración del equipo** (eso es
la etapa 2, con órdenes firmadas, y no debe abrirse antes: ver el final).

Se puede probar el equipo sin la plataforma real con `python3 -m g2.uplink.simulada` (cumple lo mínimo de este contrato).

## 1. Principios

- **El equipo siempre inicia la conexión** (HTTPS, puerto 443). No se abre ningún puerto en el equipo.
- **Nada se borra del equipo hasta que la plataforma lo confirma, registro por registro** (D-008). Un HTTP 200 no basta: la
  confirmación es el resultado `ok` de cada registro, y solo se dice `ok` cuando **ya está guardado de forma durable**.
- **Idempotente:** el equipo reenvía lo que no se confirmó, y puede reenviar lo ya confirmado si se perdió la respuesta. Dos
  envíos del mismo `(equipo, tabla, id, rev)` deben dejar el mismo resultado y contestar `ok` las dos veces.
- Si la plataforma está caída o lenta, el equipo sigue midiendo y guardando y reintenta con esperas de 5 s hasta 5 min.

## 2. Autenticación y transporte

| | |
|---|---|
| Transporte | **HTTPS con certificado válido**. El equipo verifica el certificado y no sigue redirecciones. |
| Identidad | Cabecera `X-G2-Equipo: <equipo_id>` y el mismo `equipo_id` en el cuerpo. **Deben coincidir**. |
| Secreto | Cabecera `Authorization: Bearer <secreto>`. **Un secreto por equipo** (no el token global): se genera al dar de alta el equipo, se entrega una sola vez y la plataforma solo guarda su **hash** (SHA-256 o mejor) y lo compara en tiempo constante. |
| Alta | El equipo debe estar dado de alta en la plataforma (`equipos_config`). **Sin autoregistro**: un `equipo_id` desconocido es 401. |
| Rechazo | `401` si el secreto o el equipo no valen. El equipo deja de insistir 5 min y avisa con el evento `PLAT_CREDENCIAL_RECHAZADA`. No distinga en la respuesta entre «equipo inexistente» y «secreto malo». |

Recomendado: límite de peticiones por equipo (el uso normal es 1 lote cada 30 s y 1 foto en vivo cada 15 s), registro de
intentos fallidos, y **no escribir el secreto ni la cabecera `Authorization` en ningún registro de peticiones**.

Cuerpos con `Content-Encoding: gzip` cuando pesan 1 KB o más (por ejemplo `express.json()` ya los descomprime). Tamaño: un lote normal
es de hasta 500 registros (unos 200 KB sin comprimir); acepte **al menos 5 MB descomprimidos**. Si no acepta tanto, conteste `413`
y el equipo achica el lote a la mitad.

## 3. `POST /api/g2/v1/lotes` — registros durables

Cabeceras: `Content-Type: application/json`, `X-G2-Equipo`, `X-G2-Lote: <uuid>` (el mismo `lote_id` del cuerpo), `Authorization`.

```json
{
  "equipo_id": "ANZD-600226001",
  "lote_id": "2f6f0c2e-6a52-4a6e-8a1d-0d5b6b0f6a11",
  "registros": [
    {"tabla": "alarma",  "id": 12, "rev": 3, "datos": {"id": 12, "codigo": "ALM_O2_ALTO", "estado": "cerrada", "...": "..."}},
    {"tabla": "lectura", "id": 5301, "rev": 1, "datos": {"id": 5301, "ts_ms": 1793117849607, "sensor_id": 1, "o2_prom": 93.62, "...": "..."}}
  ]
}
```

- `tabla` es una de la sección 5; `id` es la clave del registro en el equipo (`seq` en `auditoria_cadena`); `datos` es la **fila completa**.
- `rev` es la revisión más alta pendiente de ese registro y `datos` trae su contenido **de hoy** (una alarma que se abrió y se cerró
  viaja una vez, ya cerrada, con la `rev` más alta). Las tablas sin columna `rev` (lectura, salud, …) siempre van con `rev: 1`.
  Conserve por `(equipo, tabla, id)` la fila de mayor `rev`; ignore una `rev` menor que la que ya tiene (y conteste `ok`).
- El orden dentro del lote no importa. Con atraso, el equipo envía primero alarmas, eventos y calibraciones, y al final las lecturas.

Respuesta `200`:

```json
{
  "lote_id": "2f6f0c2e-6a52-4a6e-8a1d-0d5b6b0f6a11",
  "resultados": [
    {"tabla": "alarma",  "id": 12,   "rev": 3, "estado": "ok"},
    {"tabla": "lectura", "id": 5301, "rev": 1, "estado": "rechazado", "motivo": "o2_prom fuera de rango"},
    {"tabla": "salud",   "id": 88,   "estado": "reintentar", "motivo": "base de datos ocupada"}
  ]
}
```

| `estado` | Significa | El equipo |
|---|---|---|
| `ok` | Guardado de forma durable (o ya lo tenía). Debe traer `rev` = la guardada. | Lo marca **confirmado** (ya se puede depurar según la retención). Si `rev` es menor que la enviada, no lo da por confirmado y lo reenvía. |
| `rechazado` | El registro es **inválido** y reenviarlo no lo arreglará (con `motivo`). | Lo marca **rechazado**, no lo reintenta, no lo borra, y deja el evento `NET_ENVIO_RECHAZADO` para revisar. |
| `reintentar` | Falla pasajera de ese registro. | Lo deja pendiente y espera 30 s, 60 s, … hasta 10 min. |
| *(no aparece)* | La plataforma no dijo nada de ese registro. | Sigue pendiente. |

- `lote_id` **debe repetirse igual**: si no coincide, el equipo descarta toda la respuesta.
- **No rechace por una falla suya.** Un `rechazado` es definitivo en el equipo: ante un error de su código o de su base use
  `reintentar` o un 5xx, nunca `rechazado`. Un 4xx con el lote entero mal formado (400) no rechaza nada en el equipo: lo trata como error de protocolo y reintenta.
- Códigos HTTP: `200` respuesta por registro; `401/403` credencial; `413` lote demasiado grande (el equipo lo achica);
  `408/429/5xx` reintentar (respete `Retry-After` en segundos); cualquier otro `4xx`, error de protocolo (el equipo reintenta).

## 4. `POST /api/g2/v1/vivo` — foto del valor actual

Para que el panel muestre el oxígeno de ahora sin esperar el intervalo de guardado (hoy 5 min en la Pi; 15 s de fábrica). **No es durable**:
guarde solo la última (o las que quiera para la gráfica en vivo); si se pierde una, la siguiente la reemplaza. Misma autenticación. Cada
`plataforma.intervalo_visualizacion_s` (15 s). Respuesta: cualquier `200`.

```json
{
  "equipo_id": "ANZD-600226001", "ts_ms": 1793294727472, "version_sw": "0.1.0-dev", "nucleo_ok": true,
  "sensores": [{"id": 1, "nombre": "Sensor 1", "estado": "NORMAL", "acusada": false, "o2": 93.62},
               {"id": 2, "nombre": "Sensor 2", "estado": "SIN SEÑAL", "acusada": false, "o2": null}],
  "aviso": "Sin alarmas", "rele_bajo": false, "rele_alto": false, "alertas_salud": [],
  "salud": {"cpu_temp_c": 48.3, "mem_pct": 34.9, "disco_pct": 39.8, "throttled": "0x0", "red_ok": true, "wifi_rssi_dbm": -41, "uptime_s": 9337},
  "red": {"tipo": "wifi", "senal": 79, "internet": true}
}
```

- **`nucleo_ok: false`** quiere decir que el programa de medición del equipo no responde (la red sí): el equipo puede estar sin medir ni alarmar. **Es
  lo más importante que debe alertar la plataforma.** En ese caso solo viene `ts_ms`, `version_sw`, `nucleo_ok` y `edad_estado_s`.
- `estado` del sensor: `NORMAL`, `BAJA` (oxígeno bajo), `ALTA` (oxígeno alto), `SIN SEÑAL` o `APAGADO` (lo apagaron desde la pantalla; `o2` va `null`).
  `acusada`: la alarma está silenciada en la pantalla. `alertas_salud`: códigos de las alarmas de la propia Pi que están activas (temperatura, memoria, disco…).
- No viaja el nombre de la red WiFi ni las direcciones IP.
- Si dejan de llegar fotos (equipo apagado o sin red) la alerta es de la plataforma («equipo sin reportar», D-021).

## 5. Tablas que viajan

Todas las horas son **milisegundos desde 1970 en UTC** según el reloj del equipo (la Pi no tiene reloj propio: `ts_confiable = 0` significa que el reloj aún
no estaba sincronizado cuando se guardó; la hora real se corrige con `arranque.sincronizado_utc_ms`). `*_json` son texto JSON. `sensor_id` y los
`id` son **del equipo** (únicos solo dentro de `equipo_id`; los sensores son 1 y 2).

| Tabla | Clave | `rev` | Columnas de `datos` |
|---|---|---|---|
| `lectura` | `id` | no | id, ts_ms, ts_confiable, arranque_id, mono_ms, sensor_id, periodo_ms, n_muestras, **o2_prom, o2_min, o2_max**, mv_prom, calidad, calibracion_id |
| `alarma` | `id` | sí | id, codigo, severidad, sensor_id, periferico_id, inicio_ms, inicio_confiable, arranque_id, mono_ms, fin_ms, fin_confiable, umbral, valor_disparo, valor_pico, estado, acuse_ms, acuse_actor, mensaje, actualizado_ms, rev |
| `evento` | `id` | sí | id, ts_ms, ts_confiable, arranque_id, mono_ms, codigo, severidad, origen, sensor_id, periferico_id, mensaje, datos_json, repeticiones, ultimo_ms, rev |
| `salud` | `id` | no | id, ts_ms, ts_confiable, arranque_id, mono_ms, motivo, cpu_temp_c, cpu_pct, mem_pct, disco_pct, throttled, tension_5v, corriente_ma, red_ok, wifi_rssi_dbm, db_bytes, uptime_s |
| `calibracion` | `id` | sí | id, ts_ms, ts_confiable, arranque_id, mono_ms, sensor_id, tipo, gas_pct, gas_certificado, mv_antes, mv_despues, offset_pct, presion_hpa, temperatura_c, origen, actor, comando_id, resultado, vigente, notas, rev, **ganancia, bajo_ref_pct, bajo_mv, alto_ref_pct, alto_mv** |
| `config_historial` | `id` | no | id, ts_ms, ts_confiable, arranque_id, mono_ms, clave, valor_anterior, valor_nuevo, version, origen, actor, comando_id |
| `comando` | `id` | sí | id, uuid, ts_ms, ts_confiable, arranque_id, mono_ms, origen, actor, tipo, parametros_json, estado, fin_ms, resultado_json, rev |
| `arranque` | `id` | sí | id, boot_id, inicio_ms, inicio_confiable, sincronizado_utc_ms, sincronizado_mono_ms, causa, version_sw, version_config, uptime_previo_s, throttled, rev, razon, so_boot_id |
| `auditoria_cadena` | **`seq`** | no | seq, tabla, registro_id, rev, creado_ms, hash_registro, hash_previo, hash_cadena |
| `medicion_periferico` | `id` | no | id, ts_ms, ts_confiable, arranque_id, mono_ms, periferico_id, magnitud, periodo_ms, n_muestras, prom, minimo, maximo, calidad |

Notas para el diseño:

- **Mínimo viable:** guardar cada registro tal cual en una tabla `g2_registros(equipo_id, tabla, registro_id, rev, datos_json, recibido_ms)` con clave primaria
  `(equipo_id, tabla, registro_id)` y actualizar solo si `rev` es mayor. Alcanza para confirmar y no perder nada; los tableros se construyen después sobre ella.
- Cada `lectura` es el **promedio, mínimo y máximo de un intervalo** (`periodo_ms`), uno por sensor; no son las muestras de 200 ms. `calidad` es un
  conjunto de bits (1 saturada baja, 2 saturada alta, 4 en calibración, 8 sensor apagado, 16 inestable, 32 sin datos, 64 fuera de rango).
- `auditoria_cadena` permite verificar en la plataforma que no se alteró nada: cada fila encadena la huella del registro con la anterior.
- Las contraseñas **nunca** viajan: las órdenes de red se guardan con `***` y el PIN solo existe como huella en el equipo. Los reportes en PDF no se envían.
- `calibracion.tipo` vale `fabrica`, `offset_cero`, `spoc_boton` o `puntos` (calibración con gas patrón, D-049). En `puntos`: `O₂ = ganancia × (mV / mv_por_pct) + offset_pct`;
  `bajo_*` y `alto_*` son los dos gases patrón (menor y mayor de 50 %) con los que se calculó la recta: `*_ref_pct` es su concentración y `*_mv` la tensión media medida.
  Un fallo (`resultado = 'fallo'`) no se aplica (`vigente = 0`). Las filas anteriores a la migración 011 traen estas columnas en `null` (ganancia 1).
- La lista cerrada de tablas está en `cola_envio` (restricción `CHECK`); una tabla nueva exige acordar este contrato.

## 6. Qué debe verificar la plataforma antes de aceptar un equipo en producción

1. TLS válido en todo el trayecto; ningún `verify=False` en ninguna parte.
2. Secreto individual por equipo, guardado con hash; el token global retirado (D-022, etapa 3).
3. Idempotencia probada: el mismo lote dos veces deja lo mismo y contesta `ok` las dos.
4. `ok` solo después de guardar (transacción confirmada).
5. Límites de tamaño y de frecuencia por equipo; sin secretos en los registros de peticiones.
6. Alertas propias: **`nucleo_ok: false`**, equipo sin reportar, y `PLAT_*`/`NET_*`/`SYS_REINICIO_ANORMAL` entre los eventos.

## 7. Lo que NO está en esta etapa (y por qué)

La plataforma **no envía órdenes** al equipo todavía (cambiar umbrales, la red, reiniciar…). Hoy no existe ese camino en el equipo y no debe abrirse sin:
órdenes firmadas por la plataforma (Ed25519, con identificador del equipo, `uuid`, fecha de emisión y caducidad corta), autorización por usuario y equipo, y que la
plataforma no guarde ni registre secretos (D-042). Se definirá en la etapa 2 como un `GET /api/g2/v1/ordenes` que el equipo consulta.
