"""Capa de acceso a datos de G2: la unica via por la que el nucleo escribe en la base.

Que garantiza esta capa (D-007 a D-016, ver MEMORIA_TECNICA.md):
  * Cada escritura es una transaccion (BEGIN IMMEDIATE ... COMMIT): o se guarda completa o
    no se guarda nada.
  * Cada registro lleva los datos de tiempo del esquema (hora UTC, si el reloj era
    confiable, arranque y tiempo monotonico) sin que quien llama tenga que pensarlo.
  * La configuracion se valida con ``configuracion.catalogo`` y cada cambio deja su
    historial con origen y autor.
  * No hay consultas con texto concatenado: todo va con parametros.
  * El encolado hacia la plataforma y la cadena de auditoria las hacen los disparadores
    de la base; esta capa no las toca.

Regla de propiedad (D-009): solo ``g2-core`` debe escribir. Las herramientas de
provisionamiento (``g2.ctl``) la usan de forma directa mientras el nucleo no existe.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from g2.almacenamiento import base, migraciones
from g2.configuracion import catalogo
from g2.configuracion.catalogo import ErrorConfig
from g2.tiempo import RelojSistema


class ErrorAlmacen(Exception):
    """Operacion de datos invalida (por ejemplo, escribir sin haber registrado el arranque)."""


@dataclass(frozen=True)
class ResultadoConfig:
    clave: str
    valor: str
    version: int
    cambiado: bool


def leer_so_boot_id() -> str:
    """Identificador del encendido del sistema operativo (Linux); si no existe, uno nuevo."""
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return str(uuid.uuid4())


class Almacen:
    """Escritura y lectura de los datos de G2 sobre una base SQLite ya migrada."""

    def __init__(self, conexion: sqlite3.Connection, reloj=None) -> None:
        self.db = conexion
        self.reloj = reloj or RelojSistema()
        self._arranque_id: int | None = None

    # ------------------------------------------------------------------ creacion y apertura
    @classmethod
    def abrir(cls, ruta: str | Path, reloj=None) -> "Almacen":
        """Abre la base (la crea si no existe), aplica las migraciones y siembra los valores
        por defecto de las claves de configuracion que falten.

        Raises:
            migraciones.ErrorMigracion: si el esquema no se puede actualizar.
        """
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        conexion = base.abrir_escritura(ruta)
        migraciones.migrar(conexion)
        almacen = cls(conexion, reloj)
        almacen._sembrar_configuracion()
        return almacen

    def cerrar(self) -> None:
        self.db.close()

    def _sembrar_configuracion(self) -> None:
        """Inserta las claves del catalogo que aun no estan (origen 'defecto')."""
        ahora = self.reloj.ahora_ms()
        with self._transaccion():
            for clave in catalogo.CLAVES.values():
                self.db.execute(
                    "INSERT OR IGNORE INTO config (clave, valor, tipo, version, origen, actualizado_ms)"
                    " VALUES (?, ?, ?, 1, 'defecto', ?)",
                    (clave.nombre, clave.defecto, clave.tipo, ahora))

    # ------------------------------------------------------------------ transacciones
    @contextmanager
    def _transaccion(self) -> Iterator[None]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    def _tiempo(self) -> dict:
        """Datos de tiempo que llevan los registros. Exige el arranque ya registrado."""
        if self._arranque_id is None:
            raise ErrorAlmacen("falta registrar el arranque antes de escribir datos")
        return {"ts_ms": self.reloj.ahora_ms(), "ts_confiable": int(self.reloj.confiable()),
                "arranque_id": self._arranque_id, "mono_ms": self.reloj.mono_ms()}

    def _insertar(self, tabla: str, datos: dict) -> int:
        """INSERT parametrizado; ``tabla`` y las columnas salen del codigo, nunca de entrada."""
        columnas = ", ".join(datos)
        marcas = ", ".join("?" for _ in datos)
        cursor = self.db.execute(f"INSERT INTO {tabla} ({columnas}) VALUES ({marcas})",
                                 tuple(datos.values()))
        return cursor.lastrowid

    # ------------------------------------------------------------------ arranque
    @property
    def arranque_id(self) -> int | None:
        return self._arranque_id

    def registrar_arranque(self, *, version_sw: str, razon: str = "SYS_ARRANQUE",
                           causa: str = "desconocida", so_boot_id: str | None = None,
                           uptime_previo_s: int | None = None,
                           throttled: str | None = None) -> int:
        """Registra el inicio del nucleo (D-018) y lo deja como el arranque en curso.

        ``boot_id`` es ``<so_boot_id>#<n>``: varios inicios del nucleo dentro del mismo
        encendido de la Raspberry Pi comparten ``so_boot_id``.
        """
        so_boot_id = so_boot_id or leer_so_boot_id()
        ahora, mono = self.reloj.ahora_ms(), self.reloj.mono_ms()
        confiable = int(self.reloj.confiable())
        with self._transaccion():
            n = self.db.execute("SELECT COUNT(*) FROM arranque WHERE so_boot_id = ?",
                                (so_boot_id,)).fetchone()[0]
            version_config = self.db.execute(
                "SELECT COALESCE(MAX(version), 0) FROM config").fetchone()[0]
            self._arranque_id = self._insertar("arranque", {
                "boot_id": f"{so_boot_id}#{n + 1}", "so_boot_id": so_boot_id,
                "inicio_ms": ahora, "inicio_confiable": confiable,
                # Si el reloj ya es confiable, ese instante es la referencia de correccion.
                "sincronizado_utc_ms": ahora if confiable else None,
                "sincronizado_mono_ms": mono if confiable else None,
                "causa": causa, "razon": razon, "version_sw": version_sw,
                "version_config": version_config, "uptime_previo_s": uptime_previo_s,
                "throttled": throttled})
        return self._arranque_id

    def usar_ultimo_arranque(self) -> int:
        """Para herramientas que no son el nucleo: reutiliza el arranque mas reciente."""
        fila = self.db.execute("SELECT id FROM arranque ORDER BY id DESC LIMIT 1").fetchone()
        if fila is None:
            raise ErrorAlmacen("no hay ningun arranque registrado; inicie g2-core o use "
                               "registrar_arranque")
        self._arranque_id = fila["id"]
        return self._arranque_id

    def marcar_reloj_sincronizado(self) -> bool:
        """Cuando el reloj pasa a ser confiable, guarda la referencia que permite corregir las
        horas de los registros hechos antes (esquema, regla 1). Devuelve si hubo cambio."""
        if self._arranque_id is None:
            raise ErrorAlmacen("falta registrar el arranque")
        with self._transaccion():
            fila = self.db.execute("SELECT sincronizado_utc_ms FROM arranque WHERE id = ?",
                                   (self._arranque_id,)).fetchone()
            if fila["sincronizado_utc_ms"] is not None:
                return False
            self.db.execute(
                "UPDATE arranque SET sincronizado_utc_ms = ?, sincronizado_mono_ms = ? WHERE id = ?",
                (self.reloj.ahora_ms(), self.reloj.mono_ms(), self._arranque_id))
        return True

    # ------------------------------------------------------------------ apagado limpio
    def iniciar_sesion(self) -> bool:
        """Lee si el cierre anterior fue ordenado y marca que ahora se esta ejecutando.

        Returns:
            True si la vez anterior termino con ``cerrar_limpio`` (o es la primera vez).
        """
        anterior = self.config_obtener("sistema.apagado_limpio") == "1"
        self._config_interno("sistema.apagado_limpio", "0")
        return anterior

    def cerrar_limpio(self) -> None:
        self._config_interno("sistema.apagado_limpio", "1")

    def _config_interno(self, clave: str, valor: str) -> None:
        """Estado interno: se guarda sin historial (no es un cambio de configuracion)."""
        with self._transaccion():
            self.db.execute("UPDATE config SET valor = ?, origen = 'local', actualizado_ms = ? "
                            "WHERE clave = ?", (valor, self.reloj.ahora_ms(), clave))

    # ------------------------------------------------------------------ configuracion
    def config_obtener(self, clave: str) -> str:
        """Valor vigente (texto). Si la clave no esta sembrada, usa el valor por defecto."""
        catalogo.obtener(clave)
        fila = self.db.execute("SELECT valor FROM config WHERE clave = ?", (clave,)).fetchone()
        return fila["valor"] if fila else catalogo.CLAVES[clave].defecto

    def config_tipada(self, clave: str):
        """Valor vigente convertido a su tipo (int, float, bool o str)."""
        tipo = catalogo.obtener(clave).tipo
        valor = self.config_obtener(clave)
        return {"entero": int, "real": float, "booleano": lambda v: v == "1"}.get(tipo, str)(valor)

    def config_listar(self) -> list[dict]:
        filas = self.db.execute("SELECT * FROM config ORDER BY clave").fetchall()
        return [dict(f) | {"defecto": catalogo.CLAVES[f["clave"]].defecto
                           if f["clave"] in catalogo.CLAVES else None} for f in filas]

    def config_fijar(self, clave: str, valor: object, *, origen: str, actor: str | None = None,
                     comando_id: int | None = None) -> ResultadoConfig:
        """Cambia una clave con validacion, permiso de origen e historial (una transaccion).

        Si el valor nuevo es igual al vigente no se escribe nada (sin ruido en el historial).

        Raises:
            ErrorConfig: clave desconocida, valor invalido, relacion entre claves incumplida
                u ``origen`` sin permiso para esa clave.
        """
        definicion = catalogo.obtener(clave)
        if origen not in definicion.editable_por:
            raise ErrorConfig(f"{clave}: no se puede cambiar desde {origen!r} "
                              f"(solo {sorted(definicion.editable_por)})")
        nuevo = catalogo.normalizar(definicion, valor)
        catalogo.validar_relaciones(clave, nuevo, self.config_obtener)

        with self._transaccion():
            fila = self.db.execute("SELECT valor, version FROM config WHERE clave = ?",
                                   (clave,)).fetchone()
            if fila is not None and fila["valor"] == nuevo:
                return ResultadoConfig(clave, nuevo, fila["version"], False)
            version = (fila["version"] + 1) if fila else 1
            tiempo = self._tiempo()
            if fila is None:
                self.db.execute(
                    "INSERT INTO config (clave, valor, tipo, version, origen, actor, actualizado_ms)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (clave, nuevo, definicion.tipo, version, origen, actor, tiempo["ts_ms"]))
            else:
                self.db.execute(
                    "UPDATE config SET valor = ?, version = ?, origen = ?, actor = ?, "
                    "actualizado_ms = ? WHERE clave = ?",
                    (nuevo, version, origen, actor, tiempo["ts_ms"], clave))
            self._insertar("config_historial", {
                **tiempo, "clave": clave, "valor_anterior": fila["valor"] if fila else None,
                "valor_nuevo": nuevo, "version": version, "origen": origen, "actor": actor,
                "comando_id": comando_id})
        return ResultadoConfig(clave, nuevo, version, True)

    # ------------------------------------------------------------------ sensores y calibracion
    def registrar_sensor(self, *, canal: str, nombre: str, modelo: str, mv_por_pct: float,
                         variante: str | None = None, serie_etiqueta: str | None = None,
                         mv_aire_objetivo: float | None = None, notas: str | None = None) -> int:
        """Da de alta un sensor de oxigeno (D-003). ``canal`` identifica su entrada del ADC,
        por ejemplo ``ads1263:0-1``."""
        with self._transaccion():
            return self._insertar("sensor", {
                "canal": canal, "nombre": nombre, "modelo": modelo, "variante": variante,
                "serie_etiqueta": serie_etiqueta, "mv_por_pct": mv_por_pct,
                "mv_aire_objetivo": mv_aire_objetivo, "instalado_ms": self.reloj.ahora_ms(),
                "notas": notas})

    def listar_sensores(self) -> list[dict]:
        return [dict(f) for f in self.db.execute("SELECT * FROM sensor ORDER BY id")]

    def fijar_sensor_habilitado(self, sensor_id: int, habilitado: bool, *, origen: str,
                                actor: str | None = None) -> bool:
        """Habilita o deshabilita un sensor y deja un evento. Devuelve si hubo cambio."""
        with self._transaccion():
            fila = self.db.execute("SELECT habilitado FROM sensor WHERE id = ?",
                                   (sensor_id,)).fetchone()
            if fila is None:
                raise ErrorAlmacen(f"sensor {sensor_id} inexistente")
            if bool(fila["habilitado"]) == habilitado:
                return False
            self.db.execute("UPDATE sensor SET habilitado = ? WHERE id = ?",
                            (int(habilitado), sensor_id))
            self._evento_sin_tx(
                "SEN_HABILITADO" if habilitado else "SEN_DESHABILITADO", f"{origen}:{actor or '-'}",
                sensor_id=sensor_id, mensaje=f"cambio pedido desde {origen}")
        return True

    def fijar_serie_sensor(self, sensor_id: int, serie_etiqueta: str) -> None:
        """Anota la serie de la etiqueta de un sensor (el analogico no se identifica solo)."""
        with self._transaccion():
            cursor = self.db.execute("UPDATE sensor SET serie_etiqueta = ? WHERE id = ?",
                                     (serie_etiqueta.strip(), sensor_id))
            if cursor.rowcount == 0:
                raise ErrorAlmacen(f"sensor {sensor_id} inexistente")

    def calibracion_vigente(self, sensor_id: int) -> int | None:
        fila = self.db.execute("SELECT id FROM calibracion WHERE sensor_id = ? AND vigente = 1",
                               (sensor_id,)).fetchone()
        return fila["id"] if fila else None

    def registrar_calibracion(self, *, sensor_id: int, tipo: str, origen: str, resultado: str,
                              actor: str | None = None, gas_pct: float | None = None,
                              gas_certificado: str | None = None, mv_antes: float | None = None,
                              mv_despues: float | None = None, offset_pct: float | None = None,
                              presion_hpa: float | None = None, temperatura_c: float | None = None,
                              vigente: bool = False, comando_id: int | None = None,
                              notas: str | None = None) -> int:
        """Registra una calibracion. Si es vigente, reemplaza a la anterior (lo hace la base)."""
        with self._transaccion():
            return self._insertar("calibracion", {
                **self._tiempo(), "sensor_id": sensor_id, "tipo": tipo, "gas_pct": gas_pct,
                "gas_certificado": gas_certificado, "mv_antes": mv_antes, "mv_despues": mv_despues,
                "offset_pct": offset_pct, "presion_hpa": presion_hpa, "temperatura_c": temperatura_c,
                "origen": origen, "actor": actor, "comando_id": comando_id, "resultado": resultado,
                "vigente": int(vigente), "notas": notas})

    # ------------------------------------------------------------------ lecturas y salud
    def insertar_lectura(self, *, sensor_id: int, periodo_ms: int, n_muestras: int,
                         o2_prom: float | None, o2_min: float | None, o2_max: float | None,
                         mv_prom: float | None, calidad: int = 0) -> int:
        """Guarda el agregado de un intervalo, con la calibracion vigente en ese momento."""
        with self._transaccion():
            return self._insertar("lectura", {
                **self._tiempo(), "sensor_id": sensor_id, "periodo_ms": periodo_ms,
                "n_muestras": n_muestras, "o2_prom": o2_prom, "o2_min": o2_min, "o2_max": o2_max,
                "mv_prom": mv_prom, "calidad": calidad,
                "calibracion_id": self.calibracion_vigente(sensor_id)})

    def registrar_salud(self, *, motivo: str = "SYS_SALUD_PERIODICA", **campos) -> int:
        """Estado de la Raspberry Pi. ``campos``: cpu_temp_c, cpu_pct, mem_pct, disco_pct,
        throttled, tension_5v, corriente_ma, red_ok, wifi_rssi_dbm, db_bytes, uptime_s."""
        permitidos = {"cpu_temp_c", "cpu_pct", "mem_pct", "disco_pct", "throttled", "tension_5v",
                      "corriente_ma", "red_ok", "wifi_rssi_dbm", "db_bytes", "uptime_s"}
        desconocidos = set(campos) - permitidos
        if desconocidos:
            raise ErrorAlmacen(f"campos de salud desconocidos: {sorted(desconocidos)}")
        with self._transaccion():
            return self._insertar("salud", {**self._tiempo(), "motivo": motivo, **campos})

    # ------------------------------------------------------------------ eventos
    def _severidad_catalogo(self, codigo: str) -> int:
        fila = self.db.execute("SELECT severidad FROM catalogo_evento WHERE codigo = ?",
                               (codigo,)).fetchone()
        if fila is None:
            raise ErrorAlmacen(f"codigo de evento fuera del catalogo: {codigo!r}")
        return fila["severidad"]

    def registrar_evento(self, codigo: str, origen: str, *, mensaje: str | None = None,
                         datos: dict | None = None, sensor_id: int | None = None,
                         periferico_id: int | None = None, severidad: int | None = None) -> int:
        """Registra un evento. Si el ultimo evento igual (mismo codigo, origen y sensor) es
        reciente (``evento.agrupar_s``), no crea otro: aumenta sus repeticiones."""
        with self._transaccion():
            return self._evento_sin_tx(codigo, origen, mensaje=mensaje, datos=datos,
                                       sensor_id=sensor_id, periferico_id=periferico_id,
                                       severidad=severidad)

    def _evento_sin_tx(self, codigo, origen, *, mensaje=None, datos=None, sensor_id=None,
                       periferico_id=None, severidad=None) -> int:
        sev = severidad if severidad is not None else self._severidad_catalogo(codigo)
        tiempo = self._tiempo()
        ventana_ms = int(self.config_tipada("evento.agrupar_s")) * 1000
        previo = self.db.execute(
            "SELECT id, ts_ms, ultimo_ms FROM evento WHERE codigo = ? AND origen = ? "
            "AND sensor_id IS ? AND periferico_id IS ? ORDER BY id DESC LIMIT 1",
            (codigo, origen, sensor_id, periferico_id)).fetchone()
        if previo and tiempo["ts_ms"] - (previo["ultimo_ms"] or previo["ts_ms"]) <= ventana_ms:
            self.db.execute(
                "UPDATE evento SET repeticiones = repeticiones + 1, ultimo_ms = ? WHERE id = ?",
                (tiempo["ts_ms"], previo["id"]))
            return previo["id"]
        return self._insertar("evento", {
            **tiempo, "codigo": codigo, "severidad": sev, "origen": origen, "sensor_id": sensor_id,
            "periferico_id": periferico_id, "mensaje": mensaje,
            "datos_json": json.dumps(datos, ensure_ascii=False) if datos is not None else None})

    # ------------------------------------------------------------------ alarmas
    def alarma_activa(self, codigo: str, sensor_id: int | None = None) -> int | None:
        """Id de la alarma no cerrada de ese codigo y sensor, si la hay."""
        fila = self.db.execute(
            "SELECT id FROM alarma WHERE codigo = ? AND sensor_id IS ? AND estado <> 'cerrada' "
            "ORDER BY id DESC LIMIT 1", (codigo, sensor_id)).fetchone()
        return fila["id"] if fila else None

    def abrir_alarma(self, codigo: str, *, sensor_id: int | None = None,
                     periferico_id: int | None = None, umbral: float | None = None,
                     valor: float | None = None, mensaje: str | None = None,
                     severidad: int | None = None) -> int:
        """Abre una alarma. Si ya hay una abierta igual, devuelve la existente (no duplica)."""
        with self._transaccion():
            existente = self.alarma_activa(codigo, sensor_id)
            if existente is not None:
                return existente
            tiempo = self._tiempo()
            return self._insertar("alarma", {
                "codigo": codigo,
                "severidad": severidad if severidad is not None else self._severidad_catalogo(codigo),
                "sensor_id": sensor_id, "periferico_id": periferico_id,
                "inicio_ms": tiempo["ts_ms"], "inicio_confiable": tiempo["ts_confiable"],
                "arranque_id": tiempo["arranque_id"], "mono_ms": tiempo["mono_ms"],
                "umbral": umbral, "valor_disparo": valor, "valor_pico": valor, "mensaje": mensaje,
                "actualizado_ms": tiempo["ts_ms"]})

    def actualizar_pico(self, alarma_id: int, valor_pico: float) -> bool:
        """Actualiza el valor extremo de una alarma abierta. Solo escribe si cambio (cada
        escritura genera una revision y un eslabon de auditoria)."""
        with self._transaccion():
            fila = self.db.execute("SELECT valor_pico, estado FROM alarma WHERE id = ?",
                                   (alarma_id,)).fetchone()
            if fila is None or fila["estado"] == "cerrada" or fila["valor_pico"] == valor_pico:
                return False
            self.db.execute("UPDATE alarma SET valor_pico = ?, actualizado_ms = ? WHERE id = ?",
                            (valor_pico, self.reloj.ahora_ms(), alarma_id))
        return True

    def acusar_alarma(self, alarma_id: int, actor: str) -> bool:
        """Registra el acuse de recibo. Devuelve False si ya estaba acusada o cerrada."""
        with self._transaccion():
            fila = self.db.execute("SELECT estado FROM alarma WHERE id = ?", (alarma_id,)).fetchone()
            if fila is None:
                raise ErrorAlmacen(f"alarma {alarma_id} inexistente")
            if fila["estado"] != "activa":
                return False
            ahora = self.reloj.ahora_ms()
            self.db.execute("UPDATE alarma SET estado = 'acusada', acuse_ms = ?, acuse_actor = ?, "
                            "actualizado_ms = ? WHERE id = ?", (ahora, actor, ahora, alarma_id))
        return True

    def cerrar_alarma(self, alarma_id: int) -> bool:
        """Cierra la alarma (la condicion termino). Devuelve False si ya estaba cerrada."""
        with self._transaccion():
            fila = self.db.execute("SELECT estado FROM alarma WHERE id = ?", (alarma_id,)).fetchone()
            if fila is None:
                raise ErrorAlmacen(f"alarma {alarma_id} inexistente")
            if fila["estado"] == "cerrada":
                return False
            ahora = self.reloj.ahora_ms()
            self.db.execute(
                "UPDATE alarma SET estado = 'cerrada', fin_ms = ?, fin_confiable = ?, "
                "actualizado_ms = ? WHERE id = ?",
                (ahora, int(self.reloj.confiable()), ahora, alarma_id))
        return True

    # ------------------------------------------------------------------ comandos
    def registrar_comando(self, *, uuid_comando: str, origen: str, tipo: str,
                          parametros: dict | None = None, actor: str | None = None) -> tuple[int, bool]:
        """Registra un comando recibido. Es idempotente: si el ``uuid`` ya existe devuelve el
        existente y ``False`` (no se ejecuta dos veces). Devuelve ``(id, es_nuevo)``."""
        with self._transaccion():
            previo = self.db.execute("SELECT id FROM comando WHERE uuid = ?",
                                     (uuid_comando,)).fetchone()
            if previo:
                return previo["id"], False
            return self._insertar("comando", {
                **self._tiempo(), "uuid": uuid_comando, "origen": origen, "actor": actor,
                "tipo": tipo, "estado": "recibido",
                "parametros_json": json.dumps(parametros, ensure_ascii=False)
                if parametros is not None else None}), True

    def finalizar_comando(self, comando_id: int, estado: str, resultado: dict | None = None) -> None:
        if estado not in ("ok", "error", "rechazado"):
            raise ErrorAlmacen(f"estado final de comando no valido: {estado!r}")
        with self._transaccion():
            self.db.execute(
                "UPDATE comando SET estado = ?, fin_ms = ?, resultado_json = ? WHERE id = ?",
                (estado, self.reloj.ahora_ms(),
                 json.dumps(resultado, ensure_ascii=False) if resultado is not None else None,
                 comando_id))

    # ------------------------------------------------------------------ estado de la base
    def estado(self) -> dict:
        """Resumen del estado de la base interna (D-014, requisito de la lista inicial):
        version del esquema, filas por tabla, tamano, cola de envio y alarmas abiertas."""
        filas = {f["tabla"]: f["filas"] for f in self.db.execute("SELECT * FROM v_estado_db")}
        cola = [dict(f) for f in self.db.execute("SELECT * FROM v_cola_resumen")]
        paginas = self.db.execute("PRAGMA page_count").fetchone()[0]
        tam_pagina = self.db.execute("PRAGMA page_size").fetchone()[0]
        return {
            "version_esquema": migraciones.version_actual(self.db),
            "filas": filas,
            "bytes": paginas * tam_pagina,
            "cola_envio": cola,
            "pendientes_envio": sum(c["cantidad"] for c in cola if c["estado"] != "confirmado"),
            "alarmas_abiertas": self.db.execute(
                "SELECT COUNT(*) FROM v_alarmas_activas").fetchone()[0],
            "ultimo_arranque": (dict(f) if (f := self.db.execute(
                "SELECT id, boot_id, razon, version_sw, inicio_ms FROM arranque "
                "ORDER BY id DESC LIMIT 1").fetchone()) else None),
        }
