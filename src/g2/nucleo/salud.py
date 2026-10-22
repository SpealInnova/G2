"""Salud de la Raspberry Pi: medicion, registro periodico y alarmas (D-011, D-013, D-039).

Cada ``MUESTREO_S`` segundos se mide la temperatura del procesador, la memoria RAM, el disco, el voltaje de
alimentacion (``throttled`` de la Pi), el enlace de red y el tiempo encendido. Con eso:

  * se **registra** una fila de ``salud`` cada ``salud.intervalo_min`` minutos (30 por omision) y, ademas, cada vez
    que una causa abre una alarma, con la causa como motivo (D-011: "cada media hora o cada vez que se genere un
    dato alarmante");
  * se **alarma** (``ALM_RPI_TEMP_ALTA``, ``ALM_RPI_RAM_ALTA``, ``ALM_DISCO_ESPACIO_BAJO``,
    ``ALM_DISCO_ESPACIO_CRITICO``, ``ALM_RPI_BAJO_VOLTAJE``) con los umbrales de la configuracion, un retardo
    de ``RETARDO_S`` y un margen de histeresis para no oscilar en el limite;
  * se entrega la ultima medicion para la pagina ``sistema`` de la pantalla.

Estas alarmas son DEL SISTEMA: aparecen en el aviso de la pantalla pero no suenan ni activan relevos (D-033: los
relevos son solo de oxigeno). La medicion esta separada en ``MedidorLinux`` para poder probar todo sin una Pi.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Protocol

from g2.almacenamiento.almacen import Almacen
from g2.nucleo.alarmas import ACTIVA, Condicion

MUESTREO_S = 10.0
RETARDO_S = 30.0
BIT_BAJO_VOLTAJE_AHORA = 0x1                     # ``vcgencmd get_throttled``: bit 0, voltaje bajo detectado AHORA
MARGEN_TEMP_C = 5.0                              # histeresis: la alarma cierra 5 °C / 5 % por debajo del umbral
MARGEN_RAM_PCT = 5.0
MARGEN_DISCO_PCT, MARGEN_DISCO_GB = 2.0, 0.5

ALM_TEMP, ALM_RAM = "ALM_RPI_TEMP_ALTA", "ALM_RPI_RAM_ALTA"
ALM_DISCO_BAJO, ALM_DISCO_CRITICO = "ALM_DISCO_ESPACIO_BAJO", "ALM_DISCO_ESPACIO_CRITICO"
ALM_VOLTAJE = "ALM_RPI_BAJO_VOLTAJE"
CODIGOS = (ALM_TEMP, ALM_RAM, ALM_DISCO_BAJO, ALM_DISCO_CRITICO, ALM_VOLTAJE)
ETIQUETAS = {ALM_TEMP: "PI TEMP ALTA", ALM_RAM: "PI RAM ALTA", ALM_DISCO_BAJO: "DISCO BAJO",
             ALM_DISCO_CRITICO: "DISCO CRÍTICO", ALM_VOLTAJE: "PI BAJO VOLTAJE"}


@dataclass(frozen=True)
class Medicion:
    """Una lectura de la salud. Lo que no se pudo medir queda en ``None`` (nunca un cero inventado)."""

    cpu_temp_c: float | None = None
    cpu_pct: float | None = None
    mem_pct: float | None = None
    disco_pct: float | None = None               # espacio USADO, en %
    disco_libre_gb: float | None = None
    throttled: str | None = None                 # p. ej. "0x0" o "0x50005"
    red_ok: bool | None = None
    wifi_rssi_dbm: int | None = None
    uptime_s: float | None = None
    db_bytes: int | None = None

    @property
    def disco_libre_pct(self) -> float | None:
        return None if self.disco_pct is None else 100.0 - self.disco_pct

    def para_la_base(self) -> dict:
        """Campos de ``Almacen.registrar_salud`` (sin los que no se midieron)."""
        campos = {"cpu_temp_c": self.cpu_temp_c, "cpu_pct": self.cpu_pct, "mem_pct": self.mem_pct,
                  "disco_pct": self.disco_pct, "throttled": self.throttled,
                  "red_ok": None if self.red_ok is None else int(self.red_ok),
                  "wifi_rssi_dbm": self.wifi_rssi_dbm, "db_bytes": self.db_bytes,
                  "uptime_s": None if self.uptime_s is None else int(self.uptime_s)}
        return {k: v for k, v in campos.items() if v is not None}

    def como_diccionario(self) -> dict:
        """Para publicarla a la interfaz (JSON)."""
        return {f.name: getattr(self, f.name) for f in fields(self)}


class Medidor(Protocol):
    def medir(self) -> Medicion: ...


class MedidorLinux:
    """Mide la Raspberry Pi leyendo ``/proc``, ``/sys`` y ``vcgencmd``. Cada medida falla por separado: si una no
    esta disponible (por ejemplo en un PC) queda en ``None`` y las demas siguen."""

    def __init__(self, ruta_datos: Path = Path("/"), ruta_bd: Path | None = None) -> None:
        self.ruta_datos, self.ruta_bd = Path(ruta_datos), (Path(ruta_bd) if ruta_bd else None)
        self._cpu_previo: tuple[int, int] | None = None

    def medir(self) -> Medicion:
        disco = self._disco()
        return Medicion(cpu_temp_c=self._temperatura(), cpu_pct=self._cpu(), mem_pct=self._memoria(),
                        disco_pct=disco[0], disco_libre_gb=disco[1], throttled=self._throttled(),
                        red_ok=self._red(), wifi_rssi_dbm=self._wifi(), uptime_s=self._uptime(),
                        db_bytes=self._bd())

    @staticmethod
    def _leer(ruta: str) -> str | None:
        try:
            return Path(ruta).read_text()
        except OSError:
            return None

    def _temperatura(self) -> float | None:
        texto = self._leer("/sys/class/thermal/thermal_zone0/temp")
        try:
            return round(int(texto) / 1000.0, 1) if texto else None
        except ValueError:
            return None

    def _memoria(self) -> float | None:
        texto = self._leer("/proc/meminfo")
        if not texto:
            return None
        datos = {}
        for linea in texto.splitlines():
            clave, _, resto = linea.partition(":")
            if clave in ("MemTotal", "MemAvailable"):
                datos[clave] = int(resto.split()[0])
        if "MemTotal" in datos and "MemAvailable" in datos and datos["MemTotal"] > 0:
            return round(100.0 * (1 - datos["MemAvailable"] / datos["MemTotal"]), 1)
        return None

    def _cpu(self) -> float | None:
        """Uso del procesador entre dos mediciones seguidas (la primera vez no hay con que comparar)."""
        texto = self._leer("/proc/stat")
        try:
            valores = [int(x) for x in texto.splitlines()[0].split()[1:]]
        except (AttributeError, ValueError, IndexError):
            return None
        total, inactivo = sum(valores), valores[3] + (valores[4] if len(valores) > 4 else 0)
        previo, self._cpu_previo = self._cpu_previo, (total, inactivo)
        if previo is None or total <= previo[0]:
            return None
        return round(100.0 * (1 - (inactivo - previo[1]) / (total - previo[0])), 1)

    def _disco(self) -> tuple[float | None, float | None]:
        try:
            uso = shutil.disk_usage(self.ruta_datos)
        except OSError:
            return None, None
        return round(100.0 * uso.used / uso.total, 1), round(uso.free / 1024 ** 3, 2)

    @staticmethod
    def _throttled() -> str | None:
        try:
            salida = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True,
                                    timeout=2, check=False).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
        return salida.split("=", 1)[1] if salida.startswith("throttled=") else None

    def _red(self) -> bool | None:
        encontrado = False
        for interfaz in ("eth0", "wlan0"):
            texto = self._leer(f"/sys/class/net/{interfaz}/operstate")
            if texto is not None:
                encontrado = True
                if texto.strip() == "up":
                    return True
        return False if encontrado else None

    def _wifi(self) -> int | None:
        texto = self._leer("/proc/net/wireless")
        if not texto:
            return None
        for linea in texto.splitlines()[2:]:
            columnas = linea.replace(":", " ").split()
            if len(columnas) >= 4 and columnas[0] == "wlan0":
                try:
                    return int(float(columnas[3]))
                except ValueError:
                    return None
        return None

    def _uptime(self) -> float | None:
        texto = self._leer("/proc/uptime")
        try:
            return float(texto.split()[0]) if texto else None
        except (ValueError, IndexError):
            return None

    def _bd(self) -> int | None:
        if self.ruta_bd is None:
            return None
        try:
            return self.ruta_bd.stat().st_size
        except OSError:
            return None


class ObservadorSalud:
    """Mide cada ``MUESTREO_S``, registra la salud y mantiene las alarmas del sistema."""

    def __init__(self, almacen: Almacen, medidor: Medidor) -> None:
        self.a, self.medidor = almacen, medidor
        self.ultima = Medicion()
        self._conds = {codigo: Condicion(codigo, None) for codigo in CODIGOS}
        self._t_muestra = self._t_registro = None  # type: float | None

    def recuperar(self) -> int:
        """Tras un reinicio, retoma las alarmas de salud que seguian abiertas en la base."""
        n = 0
        for cond in self._conds.values():
            alarma_id = self.a.alarma_activa(cond.codigo, None)
            if alarma_id is not None:
                cond.estado, cond.alarma_id = ACTIVA, alarma_id
                n += 1
        return n

    def etiquetas_activas(self) -> list[str]:
        return [ETIQUETAS[c.codigo] for c in self._conds.values() if c.estado == ACTIVA]

    def codigos_activos(self) -> list[str]:
        return [c.codigo for c in self._conds.values() if c.estado == ACTIVA]

    def paso(self, ahora: float) -> list[str]:
        """Llamar en cada vuelta del ciclo: solo trabaja cuando toca. Devuelve los cambios de alarmas."""
        if self._t_muestra is not None and ahora - self._t_muestra < MUESTREO_S:
            return []
        self._t_muestra = ahora
        self.ultima = medicion = self.medidor.medir()
        cambios = self._evaluar(medicion, ahora)
        if self._t_registro is None:                        # una fila al arrancar, para tener el punto de partida
            self._t_registro = ahora
            self._registrar("SYS_SALUD_PERIODICA", medicion)
        elif ahora - self._t_registro >= float(self.a.config_tipada("salud.intervalo_min")) * 60:
            self._t_registro = ahora
            self._registrar("SYS_SALUD_PERIODICA", medicion)
        return cambios

    def _registrar(self, motivo: str, medicion: Medicion) -> None:
        self.a.registrar_salud(motivo=motivo, **medicion.para_la_base())

    def _evaluar(self, m: Medicion, ahora: float) -> list[str]:
        leer = self.a.config_tipada
        cambios: list[str] = []
        t_aviso, ram_aviso = float(leer("salud.temp_cpu_aviso_c")), float(leer("salud.ram_aviso_pct"))
        libre_pct, libre_gb = m.disco_libre_pct, m.disco_libre_gb
        aviso_pct, aviso_gb = float(leer("salud.disco_aviso_libre_pct")), float(leer("salud.disco_aviso_libre_gb"))
        crit_pct, crit_gb = float(leer("salud.disco_critico_libre_pct")), float(leer("salud.disco_critico_libre_gb"))

        def bajo(umbral_pct, umbral_gb, margen_pct=0.0, margen_gb=0.0) -> bool:
            return ((libre_pct is not None and libre_pct < umbral_pct + margen_pct)
                    or (libre_gb is not None and libre_gb < umbral_gb + margen_gb))

        if m.cpu_temp_c is not None:
            self._avanzar(ALM_TEMP, m.cpu_temp_c > t_aviso, m.cpu_temp_c <= t_aviso - MARGEN_TEMP_C, ahora,
                          m.cpu_temp_c, t_aviso,
                          f"Temperatura de la Raspberry Pi alta: {m.cpu_temp_c:.1f} °C (umbral {t_aviso:g} °C)", m, cambios)
        if m.mem_pct is not None:
            self._avanzar(ALM_RAM, m.mem_pct > ram_aviso, m.mem_pct <= ram_aviso - MARGEN_RAM_PCT, ahora,
                          m.mem_pct, ram_aviso,
                          f"Memoria RAM alta: {m.mem_pct:.1f} % (umbral {ram_aviso:g} %)", m, cambios)
        if libre_pct is not None or libre_gb is not None:
            texto = (f"{libre_gb:.1f} GB libres ({libre_pct:.0f} %)" if libre_gb is not None and libre_pct is not None
                     else "poco espacio libre")
            self._avanzar(ALM_DISCO_BAJO, bajo(aviso_pct, aviso_gb),
                          not bajo(aviso_pct, aviso_gb, MARGEN_DISCO_PCT, MARGEN_DISCO_GB), ahora,
                          libre_pct, aviso_pct, f"Poco espacio en la tarjeta: {texto}", m, cambios)
            self._avanzar(ALM_DISCO_CRITICO, bajo(crit_pct, crit_gb),
                          not bajo(crit_pct, crit_gb, MARGEN_DISCO_PCT, MARGEN_DISCO_GB), ahora,
                          libre_pct, crit_pct, f"Espacio en la tarjeta CRÍTICO: {texto}", m, cambios)
        if m.throttled is not None:
            try:
                bajo_voltaje = bool(int(m.throttled, 16) & BIT_BAJO_VOLTAJE_AHORA)
            except ValueError:
                bajo_voltaje = False
            self._avanzar(ALM_VOLTAJE, bajo_voltaje, not bajo_voltaje, ahora, None, None,
                          f"La Raspberry Pi detecta voltaje de alimentacion bajo (estado {m.throttled})", m, cambios)
        return cambios

    def _avanzar(self, codigo: str, entra: bool, sale: bool, ahora: float, valor, umbral, mensaje: str,
                 medicion: Medicion, cambios: list[str]) -> None:
        cond = self._conds[codigo]
        accion = cond.actualizar(entra, sale, RETARDO_S, ahora)
        if accion == "activar":
            cond.alarma_id = self.a.abrir_alarma(codigo, umbral=umbral, valor=valor, mensaje=mensaje)
            self._registrar(codigo, medicion)               # D-011: una fila de salud con la causa
            cambios.append(f"abre {codigo}: {mensaje}")
        elif accion == "cerrar":
            if cond.alarma_id is not None:
                self.a.cerrar_alarma(cond.alarma_id)
            cambios.append(f"cierra {codigo}")
            cond.reiniciar()
