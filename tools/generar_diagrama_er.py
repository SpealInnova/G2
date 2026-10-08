"""Genera DIAGRAMA_ER.md: el diagrama entidad-relacion de la base de datos, desde el esquema real.

Uso (desde la raiz del proyecto):

    set PYTHONPATH=src
    python tools/generar_diagrama_er.py

El diagrama NO se dibuja a mano: se lee del esquema que dejan las migraciones (tablas,
columnas, claves primarias, unicas y foraneas), asi que no puede quedar desactualizado.
Se vuelve a ejecutar despues de cada migracion nueva.

El resultado usa la sintaxis Mermaid, que GitHub y la vista previa de Markdown de VS Code
(con la extension de Mermaid) dibujan. Hay dos diagramas:
  1. El modelo de datos con sus claves foraneas.
  2. Los mecanismos transversales (cola de envio y cadena de auditoria), cuyas referencias
     son logicas ("tabla" + "registro_id"), no claves foraneas.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from g2.almacenamiento import base

RAIZ = Path(__file__).resolve().parent.parent
SQL = RAIZ / "src" / "g2" / "almacenamiento" / "sql"
SALIDA = RAIZ / "DIAGRAMA_ER.md"

# Tablas que alimentan la cola de envio y la cadena de auditoria (ver 001 y 003).
SINCRONIZABLES = ["lectura", "medicion_periferico", "salud", "config_historial", "alarma",
                  "evento", "comando", "calibracion", "arranque", "auditoria_cadena"]
AUDITADAS = ["arranque", "comando", "config_historial", "calibracion", "alarma", "evento"]


def esquema() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    base.registrar_funciones(con)       # la migracion 004 usa sha256 al re-sellar
    for archivo in sorted(SQL.glob("*.sql")):
        con.executescript(archivo.read_text(encoding="utf-8"))
    return con


def tablas(con: sqlite3.Connection) -> list[str]:
    filas = con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    return [f[0] for f in filas]


def unicas(con: sqlite3.Connection, tabla: str) -> set[str]:
    """Columnas con restriccion UNIQUE de una sola columna."""
    resultado = set()
    # index_list devuelve (seq, nombre, unico, origen, parcial); un indice parcial (con WHERE)
    # no hace unico a todo el campo, asi que no se marca.
    for _seq, nombre, es_unico, _origen, parcial in con.execute(f"PRAGMA index_list({tabla})"):
        if es_unico and not parcial:
            columnas = [c[2] for c in con.execute(f"PRAGMA index_info({nombre})")]
            if len(columnas) == 1:
                resultado.add(columnas[0])
    return resultado


def entidad(con: sqlite3.Connection, tabla: str) -> str:
    foraneas = {f[3] for f in con.execute(f"PRAGMA foreign_key_list({tabla})")}
    unicos = unicas(con, tabla)
    lineas = [f"    {tabla} {{"]
    for _cid, nombre, tipo, no_nulo, _defecto, pk in con.execute(f"PRAGMA table_info({tabla})"):
        claves = [k for k, cond in (("PK", pk), ("FK", nombre in foraneas),
                                    ("UK", nombre in unicos and not pk)) if cond]
        sufijo = (" " + ", ".join(claves)) if claves else ""
        nulo = '' if (no_nulo or pk) else ' "opcional"'
        lineas.append(f"        {(tipo or 'TEXT')} {nombre}{sufijo}{nulo}")
    lineas.append("    }")
    return "\n".join(lineas)


def relaciones(con: sqlite3.Connection) -> list[str]:
    """Una linea por clave foranea: padre (uno) -> hijo (muchos)."""
    lineas = []
    for hijo in tablas(con):
        info = {c[1]: c for c in con.execute(f"PRAGMA table_info({hijo})")}
        for _id, _seq, padre, desde, _a, *_ in con.execute(f"PRAGMA foreign_key_list({hijo})"):
            obligatoria = bool(info[desde][3])
            izquierda = "||" if obligatoria else "|o"
            lineas.append(f'    {padre} {izquierda}--o{{ {hijo} : "{desde}"')
    return lineas


def generar() -> str:
    con = esquema()
    nombres = tablas(con)
    modelo = ["erDiagram"]
    modelo += [entidad(con, t) for t in nombres if t not in ("cola_envio", "auditoria_cadena",
                                                            "esquema_version")]
    modelo += [r for r in relaciones(con)]

    transversal = ["erDiagram"]
    for t in ("cola_envio", "auditoria_cadena"):
        transversal.append(entidad(con, t))
    for t in SINCRONIZABLES:
        transversal.append(f"    {t} {{\n        INTEGER id PK\n    }}")
    for t in SINCRONIZABLES:
        if t != "auditoria_cadena":
            transversal.append(f'    {t} ||..o{{ cola_envio : "tabla + registro_id + rev"')
    transversal.append('    auditoria_cadena ||..o{ cola_envio : "tabla + registro_id + rev"')
    for t in AUDITADAS:
        transversal.append(f'    {t} ||..o{{ auditoria_cadena : "tabla + registro_id + rev"')

    return f"""# G2 — Diagrama entidad-relación de la base de datos

> Generado por `tools/generar_diagrama_er.py` desde el esquema real (migraciones 001 a 004).
> No editar a mano: se regenera después de cada migración. GitHub dibuja los diagramas
> directamente; en VS Code se ven con la extensión *Markdown Preview Mermaid Support*.

**Cómo leerlo:** `PK` clave primaria, `FK` clave foránea, `UK` valor único, *opcional* = acepta
vacío. Las líneas muestran de quién depende cada tabla: un círculo (`o`) en el lado del padre
significa que la referencia es opcional; las patas de gallo (`{{`) marcan el lado "muchos".

## 1. Modelo de datos (claves foráneas)

```mermaid
{chr(10).join(modelo)}
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
{chr(10).join(transversal)}
```
"""


if __name__ == "__main__":
    SALIDA.write_text(generar(), encoding="utf-8", newline="\n")
    print(f"Generado {SALIDA}")
