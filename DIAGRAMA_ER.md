# G2 — Diagrama entidad-relación de la base de datos

> Generado por `tools/generar_diagrama_er.py` desde el esquema real (migraciones 001 a 004).
> No editar a mano: se regenera después de cada migración. GitHub dibuja los diagramas
> directamente; en VS Code se ven con la extensión *Markdown Preview Mermaid Support*.

**Cómo leerlo:** `PK` clave primaria, `FK` clave foránea, `UK` valor único, *opcional* = acepta
vacío. Las líneas muestran de quién depende cada tabla: un círculo (`o`) en el lado del padre
significa que la referencia es opcional; las patas de gallo (`{`) marcan el lado "muchos".

## 1. Modelo de datos (claves foráneas)

```mermaid
erDiagram
    alarma {
        INTEGER id PK
        TEXT codigo FK
        INTEGER severidad
        INTEGER sensor_id FK "opcional"
        INTEGER periferico_id FK "opcional"
        INTEGER inicio_ms
        INTEGER inicio_confiable
        INTEGER arranque_id FK
        INTEGER mono_ms
        INTEGER fin_ms "opcional"
        INTEGER fin_confiable "opcional"
        REAL umbral "opcional"
        REAL valor_disparo "opcional"
        REAL valor_pico "opcional"
        TEXT estado
        INTEGER acuse_ms "opcional"
        TEXT acuse_actor "opcional"
        TEXT mensaje "opcional"
        INTEGER actualizado_ms
        INTEGER rev
    }
    arranque {
        INTEGER id PK
        TEXT boot_id UK
        INTEGER inicio_ms
        INTEGER inicio_confiable
        INTEGER sincronizado_utc_ms "opcional"
        INTEGER sincronizado_mono_ms "opcional"
        TEXT causa
        TEXT version_sw
        INTEGER version_config "opcional"
        INTEGER uptime_previo_s "opcional"
        TEXT throttled "opcional"
        INTEGER rev
        TEXT razon FK "opcional"
        TEXT so_boot_id "opcional"
    }
    calibracion {
        INTEGER id PK
        INTEGER ts_ms
        INTEGER ts_confiable
        INTEGER arranque_id FK
        INTEGER mono_ms
        INTEGER sensor_id FK
        TEXT tipo
        REAL gas_pct "opcional"
        TEXT gas_certificado "opcional"
        REAL mv_antes "opcional"
        REAL mv_despues "opcional"
        REAL offset_pct "opcional"
        REAL presion_hpa "opcional"
        REAL temperatura_c "opcional"
        TEXT origen
        TEXT actor "opcional"
        INTEGER comando_id FK "opcional"
        TEXT resultado
        INTEGER vigente
        TEXT notas "opcional"
        INTEGER rev
    }
    catalogo_evento {
        TEXT codigo PK
        TEXT categoria
        INTEGER severidad
        TEXT descripcion
        TEXT accion "opcional"
        INTEGER es_alarma
    }
    comando {
        INTEGER id PK
        TEXT uuid UK
        INTEGER ts_ms
        INTEGER ts_confiable
        INTEGER arranque_id FK
        INTEGER mono_ms
        TEXT origen
        TEXT actor "opcional"
        TEXT tipo
        TEXT parametros_json "opcional"
        TEXT estado
        INTEGER fin_ms "opcional"
        TEXT resultado_json "opcional"
        INTEGER rev
    }
    config {
        TEXT clave PK
        TEXT valor
        TEXT tipo
        INTEGER version
        TEXT origen
        TEXT actor "opcional"
        INTEGER actualizado_ms
    }
    config_historial {
        INTEGER id PK
        INTEGER ts_ms
        INTEGER ts_confiable
        INTEGER arranque_id FK
        INTEGER mono_ms
        TEXT clave
        TEXT valor_anterior "opcional"
        TEXT valor_nuevo
        INTEGER version
        TEXT origen
        TEXT actor "opcional"
        INTEGER comando_id FK "opcional"
    }
    evento {
        INTEGER id PK
        INTEGER ts_ms
        INTEGER ts_confiable
        INTEGER arranque_id FK
        INTEGER mono_ms
        TEXT codigo FK
        INTEGER severidad
        TEXT origen
        INTEGER sensor_id FK "opcional"
        INTEGER periferico_id FK "opcional"
        TEXT mensaje "opcional"
        TEXT datos_json "opcional"
        INTEGER repeticiones
        INTEGER ultimo_ms "opcional"
        INTEGER rev
    }
    lectura {
        INTEGER id PK
        INTEGER ts_ms
        INTEGER ts_confiable
        INTEGER arranque_id FK
        INTEGER mono_ms
        INTEGER sensor_id FK
        INTEGER periodo_ms
        INTEGER n_muestras
        REAL o2_prom "opcional"
        REAL o2_min "opcional"
        REAL o2_max "opcional"
        REAL mv_prom "opcional"
        INTEGER calidad
        INTEGER calibracion_id FK "opcional"
    }
    medicion_periferico {
        INTEGER id PK
        INTEGER ts_ms
        INTEGER ts_confiable
        INTEGER arranque_id FK
        INTEGER mono_ms
        INTEGER periferico_id FK
        TEXT magnitud
        INTEGER periodo_ms
        INTEGER n_muestras
        REAL prom "opcional"
        REAL minimo "opcional"
        REAL maximo "opcional"
        INTEGER calidad
    }
    periferico {
        INTEGER id PK
        TEXT tipo
        TEXT nombre UK
        TEXT bus "opcional"
        TEXT direccion "opcional"
        INTEGER habilitado
        TEXT notas "opcional"
    }
    salud {
        INTEGER id PK
        INTEGER ts_ms
        INTEGER ts_confiable
        INTEGER arranque_id FK
        INTEGER mono_ms
        TEXT motivo FK
        REAL cpu_temp_c "opcional"
        REAL cpu_pct "opcional"
        REAL mem_pct "opcional"
        REAL disco_pct "opcional"
        TEXT throttled "opcional"
        REAL tension_5v "opcional"
        REAL corriente_ma "opcional"
        INTEGER red_ok "opcional"
        INTEGER wifi_rssi_dbm "opcional"
        INTEGER db_bytes "opcional"
        INTEGER uptime_s "opcional"
    }
    sensor {
        INTEGER id PK
        TEXT canal UK
        TEXT nombre
        TEXT modelo
        TEXT variante "opcional"
        TEXT serie_etiqueta "opcional"
        REAL mv_por_pct
        REAL mv_aire_objetivo "opcional"
        REAL rango_min_pct
        REAL rango_max_pct
        INTEGER habilitado
        INTEGER instalado_ms "opcional"
        TEXT notas "opcional"
    }
    arranque ||--o{ alarma : "arranque_id"
    periferico |o--o{ alarma : "periferico_id"
    sensor |o--o{ alarma : "sensor_id"
    catalogo_evento ||--o{ alarma : "codigo"
    catalogo_evento |o--o{ arranque : "razon"
    comando |o--o{ calibracion : "comando_id"
    sensor ||--o{ calibracion : "sensor_id"
    arranque ||--o{ calibracion : "arranque_id"
    arranque ||--o{ comando : "arranque_id"
    comando |o--o{ config_historial : "comando_id"
    arranque ||--o{ config_historial : "arranque_id"
    periferico |o--o{ evento : "periferico_id"
    sensor |o--o{ evento : "sensor_id"
    catalogo_evento ||--o{ evento : "codigo"
    arranque ||--o{ evento : "arranque_id"
    calibracion |o--o{ lectura : "calibracion_id"
    sensor ||--o{ lectura : "sensor_id"
    arranque ||--o{ lectura : "arranque_id"
    periferico ||--o{ medicion_periferico : "periferico_id"
    arranque ||--o{ medicion_periferico : "arranque_id"
    catalogo_evento ||--o{ salud : "motivo"
    arranque ||--o{ salud : "arranque_id"
```

Notas:
- `arranque` es la raíz de la trazabilidad: casi todo registro apunta al arranque del núcleo
  que lo generó (`arranque_id`), con la versión de software y de configuración de ese momento.
- `lectura` guarda un agregado por intervalo (promedio, mínimo, máximo) y la calibración
  vigente al medir (`calibracion_id`).
- `alarma` y `evento` usan códigos de `catalogo_evento`; `salud.motivo` también.
- `config` guarda el valor vigente de cada clave; `config_historial` cada cambio, con su origen
  y, si vino de la plataforma o la pantalla, el `comando` que lo pidió.
- `esquema_version` (control de migraciones) no se dibuja: no se relaciona con nada.

## 2. Mecanismos transversales (referencias lógicas, no claves foráneas)

`cola_envio` y `auditoria_cadena` apuntan a otras tablas por el par `tabla` + `registro_id`
(y `rev`), no por una clave foránea, porque cada una sirve a varias tablas. Las líneas
punteadas lo indican. Los disparadores de la base mantienen ambos mecanismos (ver
`001_esquema_inicial.sql` y `003_cadena_auditoria.sql`):

- **cola_envio:** todo registro sincronizable se encola solo, y no se puede borrar hasta que
  la plataforma confirme que lo almacenó (D-008, D-010).
- **auditoria_cadena:** cada creación o revisión de un registro auditado agrega un eslabón con
  la huella SHA-256 encadenada con la del eslabón anterior (D-016).

```mermaid
erDiagram
    cola_envio {
        INTEGER id PK
        TEXT tabla
        INTEGER registro_id
        INTEGER rev
        INTEGER creado_ms
        TEXT estado
        INTEGER intentos
        INTEGER proximo_intento_ms "opcional"
        INTEGER enviado_ms "opcional"
        INTEGER confirmado_ms "opcional"
        TEXT ultimo_error "opcional"
    }
    auditoria_cadena {
        INTEGER seq PK
        TEXT tabla
        INTEGER registro_id
        INTEGER rev
        INTEGER creado_ms
        TEXT hash_registro
        TEXT hash_previo
        TEXT hash_cadena UK
    }
    lectura {
        INTEGER id PK
    }
    medicion_periferico {
        INTEGER id PK
    }
    salud {
        INTEGER id PK
    }
    config_historial {
        INTEGER id PK
    }
    alarma {
        INTEGER id PK
    }
    evento {
        INTEGER id PK
    }
    comando {
        INTEGER id PK
    }
    calibracion {
        INTEGER id PK
    }
    arranque {
        INTEGER id PK
    }
    auditoria_cadena {
        INTEGER id PK
    }
    lectura ||..o{ cola_envio : "tabla + registro_id + rev"
    medicion_periferico ||..o{ cola_envio : "tabla + registro_id + rev"
    salud ||..o{ cola_envio : "tabla + registro_id + rev"
    config_historial ||..o{ cola_envio : "tabla + registro_id + rev"
    alarma ||..o{ cola_envio : "tabla + registro_id + rev"
    evento ||..o{ cola_envio : "tabla + registro_id + rev"
    comando ||..o{ cola_envio : "tabla + registro_id + rev"
    calibracion ||..o{ cola_envio : "tabla + registro_id + rev"
    arranque ||..o{ cola_envio : "tabla + registro_id + rev"
    auditoria_cadena ||..o{ cola_envio : "tabla + registro_id + rev"
    arranque ||..o{ auditoria_cadena : "tabla + registro_id + rev"
    comando ||..o{ auditoria_cadena : "tabla + registro_id + rev"
    config_historial ||..o{ auditoria_cadena : "tabla + registro_id + rev"
    calibracion ||..o{ auditoria_cadena : "tabla + registro_id + rev"
    alarma ||..o{ auditoria_cadena : "tabla + registro_id + rev"
    evento ||..o{ auditoria_cadena : "tabla + registro_id + rev"
```
