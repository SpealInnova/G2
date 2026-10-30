"""El ciclo de g2-uplink (D-046): cada vuelta decide si toca enviar la foto en vivo, un lote de la cola, o esperar.

Dos envios distintos, porque sirven para cosas distintas:
  * **Lotes** (durables): lo que hay en ``cola_envio``, registro por registro, con confirmacion explicita de la plataforma
    (D-008). Nada se borra del equipo hasta que se confirma. Se reintenta con esperas crecientes.
  * **En vivo** (``plataforma.intervalo_visualizacion_s``): el valor de oxigeno de ahora, para que el panel web no espere los
    5 minutos del intervalo de guardado. No se guarda ni se reintenta: si se pierde, la siguiente lo reemplaza.

Quien escribe la base es g2-core: este servicio solo la lee y, al terminar un envio, le pide a g2-core que lo anote con la
orden ``cola_resultado`` (que no es un comando: ver ``Nucleo._registrar_envio``). Si g2-core no responde no se envian lotes
(no habria quien anotara el resultado y se reenviaria lo mismo una y otra vez), pero la foto en vivo sigue y dice
``nucleo_ok: false``, que es justo lo que la plataforma necesita saber.

Ademas vigila a g2-core (``SupervisorNucleo``, D-012): si no responde durante 2 minutos le pide a systemd reiniciarlo, con
limites. Eso no depende de la plataforma: corre aunque el envio este desactivado.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Callable

from g2 import __version__, ipc
from g2.almacenamiento.almacen import Almacen
from g2.uplink import credencial, mensajes
from g2.uplink.cliente import (ClientePlataforma, CredencialRechazada, ErrorEnvio, LoteDemasiadoGrande)
from g2.uplink.supervisor import SupervisorNucleo

REGISTRO = logging.getLogger("g2.uplink")
NOMBRE_ESTADO = "uplink.json"
LIMITE_ESTADO_S = 30.0               # el estado del nucleo mas viejo que esto no sirve: el nucleo no responde
PERIODO_CONFIG_S = 10.0              # cada cuanto se vuelve a leer la configuracion y el secreto
EN_VUELO_S = 30.0                    # lo ya enviado se aparta este tiempo, mientras el nucleo lo anota
ESPERA_MIN_S, ESPERA_MAX_S = 5.0, 300.0      # espera entre intentos fallidos: 5, 10, 20... hasta 5 minutos
ESPERA_CREDENCIAL_S = 300.0          # con la credencial rechazada no se insiste antes de esto
REAVISO_ENLACE_S = 600.0             # mientras el enlace esta mal, se vuelve a avisar al nucleo cada 10 min
PUBLICAR_CADA_S = 2.0
CONTAR_CADA_S = 15.0
LOTE_MIN = 10
CLAVES = {"activa": "plataforma.activa", "url": "plataforma.url", "intervalo_s": "plataforma.intervalo_envio_s",
          "lote_max": "plataforma.lote_max", "vivo_s": "plataforma.intervalo_visualizacion_s", "equipo_id": "equipo.id"}
SALUD_EN_VIVO = ("cpu_temp_c", "mem_pct", "disco_pct", "throttled", "red_ok", "wifi_rssi_dbm", "uptime_s")


def instantanea(estado: dict | None, nucleo_ok: bool, edad_s: float, version_sw: str, ahora_ms: int) -> dict:
    """La foto en vivo. Sin el estado del nucleo solo dice que el nucleo no responde; no lleva la red ni su direccion."""
    foto: dict = {"ts_ms": ahora_ms, "version_sw": version_sw, "nucleo_ok": nucleo_ok}
    if not nucleo_ok or estado is None:
        foto["edad_estado_s"] = None if edad_s == float("inf") else round(edad_s, 1)
        return foto
    foto["sensores"] = [{"id": s.get("id"), "nombre": s.get("nombre"), "estado": s.get("estado"),
                         "acusada": bool(s.get("acusada")),
                         "o2": round(s["o2"], 2) if isinstance(s.get("o2"), (int, float)) else None}
                        for s in estado.get("sensores", [])]
    foto.update(aviso=estado.get("aviso"), rele_bajo=bool(estado.get("rele_bajo")),
                rele_alto=bool(estado.get("rele_alto")),
                alertas_salud=[str(c) for c in estado.get("alertas_salud") or []])
    salud = estado.get("salud") or {}
    foto["salud"] = {k: salud[k] for k in SALUD_EN_VIVO if k in salud}
    red = (estado.get("red") or {}).get("red") or {}
    foto["red"] = {k: red[k] for k in ("tipo", "senal", "internet") if k in red}
    return foto


class ServicioUplink:
    def __init__(self, abrir_almacen: Callable[[], Almacen], nucleo: ipc.ClienteNucleo, carpeta_estado: Path | None, *,
                 leer_secreto: Callable[[], str] = credencial.leer,
                 fabrica: Callable[..., ClientePlataforma] = ClientePlataforma,
                 reloj: Callable[[], float] = time.time, mono: Callable[[], float] = time.monotonic,
                 version_sw: str = __version__, supervisor: SupervisorNucleo | None = None) -> None:
        self._abrir, self.nucleo, self.carpeta_estado = abrir_almacen, nucleo, carpeta_estado
        self.supervisor = supervisor                              # None: no vigila al nucleo (las pruebas)
        self._leer_secreto, self._fabrica = leer_secreto, fabrica
        self._reloj, self._mono, self.version_sw = reloj, mono, version_sw
        self._almacen: Almacen | None = None
        self._cfg: dict | None = None
        self._secreto: str | None = None
        self._problema: tuple[str, str] | None = None            # (estado, detalle) si falta algo para enviar
        self._cfg_en = float("-inf")
        self._cliente: ClientePlataforma | None = None
        self._cliente_clave: tuple | None = None
        self._enlace: str | None = None                          # ok | sin_enlace | credencial (None: aun no se sabe)
        self._detalle: str | None = None
        self._enlace_avisado: str | None = None
        self._aviso_en = float("-inf")
        self._fallos = 0
        self._no_antes = 0.0
        self._prox_lote = 0.0
        self._prox_vivo = 0.0
        self._lote_efectivo: int | None = None
        self._en_vuelo: dict[int, float] = {}
        self.confirmados = self.rechazados = 0
        self._ultimo_ok_s: float | None = None
        self._pendientes: int | None = None
        self._contado_en = float("-inf")
        self._publicado_en = float("-inf")
        self._ultimo_estado = ""

    # ------------------------------------------------------------------------------------------------- un paso
    def paso(self) -> None:
        ahora = self._mono()
        estado, edad = self.nucleo.leer_estado()
        nucleo_ok = estado is not None and edad <= LIMITE_ESTADO_S
        if self.supervisor is not None:                         # vigilar al nucleo no depende de la plataforma
            self.supervisor.vigilar(nucleo_ok, ahora)
        self._leer_configuracion(ahora)
        if self._cfg is None or self._problema is not None:
            self._publicar(ahora)
            return
        if self._preparar_cliente() and ahora >= self._no_antes:    # primero: un secreto corregido corta la espera
            try:
                if ahora >= self._prox_vivo:
                    self._prox_vivo = ahora + self._cfg["vivo_s"]
                    self._cliente.enviar_vivo(instantanea(estado, nucleo_ok, edad, self.version_sw, self._ms()))
                    self._exito()
                if nucleo_ok and ahora >= self._prox_lote:
                    self._enviar_lote(ahora)
            except CredencialRechazada as error:
                self._fallo("credencial", str(error), ahora, ESPERA_CREDENCIAL_S)
            except ErrorEnvio as error:
                self._fallo("sin_enlace", str(error), ahora, None, error.espera_s)
        self._avisar_enlace(ahora)
        self._publicar(ahora)

    def _ms(self) -> int:
        return int(self._reloj() * 1000)

    # ------------------------------------------------------------------------------------------------- configuracion
    def _leer_configuracion(self, ahora: float) -> None:
        if ahora - self._cfg_en < PERIODO_CONFIG_S and self._cfg is not None:
            return
        self._cfg_en = ahora
        try:
            if self._almacen is None:
                self._almacen = self._abrir()
            cfg = {k: self._almacen.config_tipada(clave) for k, clave in CLAVES.items()}
        except (sqlite3.Error, OSError) as error:
            REGISTRO.warning("no se pudo leer la base: %s", error)
            self._cerrar_base()
            return
        cfg["equipo_id"] = str(cfg["equipo_id"]).strip()
        if self._cfg is not None and cfg["lote_max"] != self._cfg["lote_max"]:
            self._lote_efectivo = None                          # alguien cambio el tamano: se vuelve a probar con el nuevo
        self._cfg = cfg
        self._problema, self._secreto = None, None
        if not cfg["activa"]:
            self._problema = ("desactivada", "plataforma.activa esta apagada")
        elif not cfg["equipo_id"]:
            self._problema = ("sin_equipo_id", "falta equipo.id (el identificador del equipo ante la plataforma)")
        else:
            try:
                self._secreto = self._leer_secreto()
            except credencial.ErrorCredencial as error:
                self._problema = ("sin_credencial", str(error))

    def _cerrar_base(self) -> None:
        if self._almacen is not None:
            try:
                self._almacen.cerrar()
            except sqlite3.Error:
                pass
        self._almacen = None

    def _preparar_cliente(self) -> bool:
        """Deja listo el cliente para la configuracion y el secreto de ahora. Si cambian (alguien corrigio la credencial o la
        direccion) se empieza de cero, sin esperar el castigo de los fallos anteriores."""
        clave = (self._cfg["url"], self._cfg["equipo_id"], self._secreto)
        if clave != self._cliente_clave:
            try:
                self._cliente = self._fabrica(self._cfg["url"], self._cfg["equipo_id"], self._secreto,
                                              version_sw=self.version_sw)
            except ValueError as error:
                self._cliente, self._cliente_clave = None, None
                self._problema = ("url_invalida", str(error))
                return False
            self._cliente_clave = clave
            self._fallos, self._no_antes, self._prox_lote, self._prox_vivo = 0, 0.0, 0.0, 0.0
        return True

    # ------------------------------------------------------------------------------------------------- lotes
    def _enviar_lote(self, ahora: float) -> None:
        cfg = self._cfg
        limite = min(self._lote_efectivo or cfg["lote_max"], cfg["lote_max"])
        self._en_vuelo = {i: hasta for i, hasta in self._en_vuelo.items() if hasta > ahora}
        entradas = mensajes.pendientes(self._almacen.db, self._ms(), limite, self._en_vuelo)
        if not entradas:
            self._prox_lote = ahora + cfg["intervalo_s"]
            return
        lote = mensajes.armar(self._almacen.db, entradas)
        confirmados: list[int] = []
        rechazados: dict[int, str] = dict(lote.faltantes)
        fallidos: dict[int, str] = {}
        if lote.registros:
            try:
                resultados = self._cliente.enviar_lote(lote.registros)
            except LoteDemasiadoGrande:
                # Se queda con el tamano menor (no vuelve a crecer solo: volveria a fallar en cada ciclo) hasta que
                # alguien cambie plataforma.lote_max o se reinicie el servicio.
                self._lote_efectivo = max(LOTE_MIN, limite // 2)
                self._prox_lote = ahora + 1.0
                REGISTRO.warning("la plataforma no acepta %d registros por lote: se baja a %d", limite, self._lote_efectivo)
                return
            for registro in lote.registros:
                ids = lote.entradas[(registro["tabla"], registro["id"])]
                resultado = resultados.get((registro["tabla"], registro["id"]))
                if resultado is None:
                    continue                                    # la plataforma no dijo nada de este: sigue pendiente
                estado, motivo, rev = resultado
                if estado == "ok" and rev is not None and rev < registro["rev"]:
                    fallidos.update({i: "la plataforma confirmo una revision anterior" for i in ids})
                elif estado == "ok":
                    confirmados += ids
                elif estado == "rechazado":
                    rechazados.update({i: motivo or "rechazado por la plataforma" for i in ids})
                else:
                    fallidos.update({i: motivo or "la plataforma pidio reintentar" for i in ids})
            self._exito()
        self.confirmados += len(confirmados)
        self.rechazados += len(rechazados)
        self._anotar(confirmados, rechazados, fallidos, ahora)
        # con atraso se sigue enseguida; al estar al dia, se espera el intervalo
        self._prox_lote = ahora + (1.0 if len(entradas) >= limite else cfg["intervalo_s"])

    def _anotar(self, confirmados: list[int], rechazados: dict[int, str], fallidos: dict[int, str], ahora: float) -> None:
        """Le pide a g2-core que anote el resultado (y el estado del enlace). Lo enviado se aparta un rato para no volver
        a elegirlo antes de que el nucleo lo anote."""
        for i in (*confirmados, *rechazados, *fallidos):
            self._en_vuelo[i] = ahora + EN_VUELO_S
        self._ordenar(confirmados=confirmados, rechazados=rechazados, fallidos=fallidos)

    # ------------------------------------------------------------------------------------------------- el enlace
    def _exito(self) -> None:
        self._fallos, self._no_antes = 0, 0.0
        self._enlace, self._detalle = "ok", None
        self._ultimo_ok_s = self._reloj()

    def _fallo(self, enlace: str, detalle: str, ahora: float, espera_s: float | None = None,
               pedida_s: float | None = None) -> None:
        self._fallos += 1
        espera = espera_s if espera_s is not None else min(ESPERA_MAX_S, ESPERA_MIN_S * 2 ** (self._fallos - 1))
        self._no_antes = ahora + max(espera, pedida_s or 0.0)
        self._enlace, self._detalle = enlace, detalle
        if self._fallos == 1:                                   # solo el primero de una racha: despues seria ruido
            REGISTRO.warning("enlace con la plataforma: %s (%s); se reintenta en %.0f s", enlace, detalle,
                             self._no_antes - ahora)

    def _avisar_enlace(self, ahora: float) -> None:
        """Avisa al nucleo cuando el enlace cambia (y cada tanto mientras este mal, por si el nucleo se reinicio)."""
        if self._enlace is None:
            return
        if self._enlace != self._enlace_avisado or (self._enlace != "ok" and ahora - self._aviso_en >= REAVISO_ENLACE_S):
            self._ordenar()

    def _ordenar(self, **resultado) -> None:
        try:
            self.nucleo.enviar_orden("cola_resultado", origen="local", enlace=self._enlace, detalle=self._detalle,
                                     **resultado)
            self._enlace_avisado, self._aviso_en = self._enlace, self._mono()
        except OSError as error:
            REGISTRO.warning("no se pudo avisar al nucleo: %s", error)

    # ------------------------------------------------------------------------------------------------- su estado
    def estado(self) -> str:
        if self._cfg is None:
            return "base_ilegible"
        if self._problema is not None:
            return self._problema[0]
        return {"ok": "ok", "sin_enlace": "sin_enlace", "credencial": "credencial_rechazada"}.get(self._enlace, "iniciando")

    def _publicar(self, ahora: float) -> None:
        """Deja ``/run/g2/uplink.json`` (para ``g2ctl plataforma-estado`` y, mas adelante, la pantalla)."""
        estado = self.estado()
        if estado != self._ultimo_estado:
            REGISTRO.info("g2-uplink: %s%s", estado, f" ({self._detalle or self._problema[1]})"
                          if (self._detalle or self._problema) else "")
            self._ultimo_estado = estado
        if self.carpeta_estado is None or ahora - self._publicado_en < PUBLICAR_CADA_S:
            return
        self._publicado_en = ahora
        if self._almacen is not None and ahora - self._contado_en >= CONTAR_CADA_S:
            self._contado_en = ahora
            try:
                self._pendientes = self._almacen.db.execute(
                    "SELECT COUNT(*) FROM cola_envio WHERE estado = 'pendiente'").fetchone()[0]
            except sqlite3.Error:
                self._pendientes = None
        detalle = self._detalle or (self._problema[1] if self._problema else None)
        documento = {"estado": estado, "detalle": detalle, "ultimo_ok_s": self._ultimo_ok_s, "pendientes": self._pendientes,
                     "confirmados": self.confirmados, "rechazados": self.rechazados, "version_sw": self.version_sw,
                     "publicado_s": self._reloj()}
        if self.supervisor is not None:
            documento["nucleo"] = self.supervisor.estado()
        try:
            ipc._escribir_atomico(self.carpeta_estado / NOMBRE_ESTADO,
                                  json.dumps(documento, ensure_ascii=False).encode("utf-8"))
        except OSError as error:
            REGISTRO.warning("no se pudo publicar el estado: %s", error)

    def cerrar(self) -> None:
        self._cerrar_base()
