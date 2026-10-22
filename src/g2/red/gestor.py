"""Gestor de red de G2: ver el estado, buscar redes WiFi y CAMBIAR de red con reversion automatica (D-040).

Usa NetworkManager por medio de ``nmcli`` (en Raspberry Pi OS Trixie es el gestor de red). Todo lo que habla con el
sistema entra por dos puntos inyectables (``ejecutor`` para ``nmcli`` y ``sonda`` para comprobar internet), asi
se prueba sin hardware y sin tocar la red de nadie.

El cambio de red es lo delicado: un equipo que queda sin red por una contrasena mal escrita se vuelve inalcanzable.
Por eso ``configurar`` NUNCA borra la red que ya funciona hasta comprobar la nueva:

  1. anota la red activa y si tenia internet;
  2. crea un perfil NUEVO (no toca el anterior) y lo activa;
  3. comprueba que la red nueva llega a internet por SU interfaz (no por otra, como el cable);
  4. si todo va bien, se queda con la nueva (con prioridad sobre las anteriores, que siguen guardadas como respaldo);
  5. si falla, borra el perfil nuevo y VUELVE a la red anterior, y dice por que fallo.

Regla para el primer uso: si antes no habia internet (equipo nuevo, sin credenciales), una red que conecta pero no
tiene salida a internet se ACEPTA (avisando), porque es mejor que ninguna; si antes SI habia internet, la red nueva
debe tenerlo tambien o se revierte.

La contrasena viaja como argumento de ``nmcli`` unos milisegundos: solo la ve quien ya tenga acceso a esta Pi. Nunca se
registra, ni en el log ni en la base (ver ``redactar`` y el nucleo).
"""

from __future__ import annotations

import hashlib
import logging
import re
import socket
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable

REGISTRO = logging.getLogger("g2.red")

PREFIJO_PERFIL = "g2-wifi-"
PRIORIDAD_NUEVA = 10                      # mayor que la de los perfiles anteriores (0 por omision)
MAX_PERFILES_PROPIOS = 4                  # perfiles que crea G2: al pasar de aqui se borran los mas viejos
ESPERA_ACTIVAR_S = 40                     # cuanto se espera a que la red nueva conecte
ANFITRIONES_INTERNET = (("1.1.1.1", 443), ("8.8.8.8", 53))
SECRETOS = ("contrasena", "password", "psk", "clave")

Ejecutor = Callable[..., "tuple[int, str, str]"]


class ErrorRed(Exception):
    """Datos de red invalidos (nombre o contrasena)."""


def redactar(datos: dict) -> dict:
    """Copia de ``datos`` con los campos secretos sustituidos por ``***``: es lo que se puede guardar o mostrar."""
    return {k: ("***" if k in SECRETOS and v not in (None, "") else v) for k, v in datos.items()}


def ejecutar_nmcli(argumentos: list[str], tiempo_max_s: float = 30.0) -> tuple[int, str, str]:
    """Corre ``nmcli`` con tiempo maximo. Devuelve ``(codigo, salida, error)``; 124 si se agoto el tiempo y 127 si
    no existe ``nmcli`` (un PC de desarrollo)."""
    try:
        r = subprocess.run(["nmcli", *argumentos], capture_output=True, text=True, timeout=tiempo_max_s, check=False)
    except subprocess.TimeoutExpired:
        return 124, "", "tiempo agotado"
    except OSError:
        return 127, "", "nmcli no esta disponible"
    return r.returncode, r.stdout, r.stderr.strip()


def verificar_internet(interfaz: str | None = None, tiempo_max_s: float = 4.0) -> bool:
    """True si se logra abrir una conexion a internet (por IP, sin depender del DNS). Con ``interfaz`` el intento
    va POR ESA interfaz: es la unica forma de saber si el WiFi nuevo sale a internet cuando tambien hay un cable."""
    for anfitrion, puerto in ANFITRIONES_INTERNET:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(tiempo_max_s)
                if interfaz and hasattr(socket, "SO_BINDTODEVICE"):
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interfaz.encode())
                s.connect((anfitrion, puerto))
            return True
        except OSError:
            continue
    return False


# ------------------------------------------------------------------ resultados
@dataclass(frozen=True)
class RedVisible:
    ssid: str
    senal: int                            # 0 a 100
    seguridad: str                        # texto de nmcli: "WPA2", "WPA2 WPA3", "" si es abierta


@dataclass(frozen=True)
class EstadoRed:
    """Foto de la red: lo que se muestra en la pagina ``red``."""

    tipo: str | None = None               # "wifi", "ethernet" o None si no hay conexion
    ssid: str | None = None
    ip: str | None = None
    senal: int | None = None
    internet: bool | None = None
    zerotier_ip: str | None = None
    interfaz_wifi: str | None = None

    def como_diccionario(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass(frozen=True)
class ResultadoRed:
    ok: bool
    mensaje: str                          # en espanol, listo para la pantalla
    revertida: bool = False               # True si se volvio a la red anterior
    sin_internet: bool = False            # conecto, pero la red no sale a internet
    motivo: str = ""                      # codigo corto del fallo: contrasena, no_encontrada, tiempo, sin_internet...


def _partir(linea: str) -> list[str]:
    """Parte una linea de ``nmcli -t`` por los ``:`` que no estan escapados con ``\\``."""
    return [c.replace("\\:", ":").replace("\\\\", "\\") for c in re.split(r"(?<!\\):", linea)]


def validar_credenciales(ssid: str, contrasena: str) -> None:
    """Un nombre de red tiene de 1 a 32 bytes; una contrasena WPA, de 8 a 63 caracteres (o 64 hexadecimales); vacia
    significa red abierta. Sin caracteres de control."""
    if not ssid or len(ssid.encode("utf-8")) > 32:
        raise ErrorRed("El nombre de la red debe tener entre 1 y 32 caracteres")
    if any(ord(c) < 32 or ord(c) == 127 for c in ssid + contrasena):
        raise ErrorRed("El nombre o la contraseña tienen caracteres no válidos")
    if contrasena and not (8 <= len(contrasena) <= 63 or re.fullmatch(r"[0-9a-fA-F]{64}", contrasena)):
        raise ErrorRed("La contraseña debe tener entre 8 y 63 caracteres")


def nombre_de_perfil(ssid: str) -> str:
    """Nombre del perfil de NetworkManager de una red: fijo por red (sirve para actualizar su contrasena)."""
    return PREFIJO_PERFIL + hashlib.sha1(ssid.encode("utf-8")).hexdigest()[:8]


def explicar_fallo(texto: str) -> tuple[str, str]:
    """``(motivo, mensaje)`` a partir de lo que dijo nmcli."""
    t = texto.lower()
    if "secrets were required" in t or "802-1x" in t or "authentication" in t or "wrong" in t or "psk" in t:
        return "contrasena", "Contraseña incorrecta"
    if "no network with ssid" in t or "not found" in t or "ssid" in t:
        return "no_encontrada", "No se encontró la red (revise el nombre y la cobertura)"
    if "timeout" in t or "tiempo" in t or "timed out" in t:
        return "tiempo", "La red tardó demasiado en responder"
    return "otro", "No se pudo conectar a la red"


# ------------------------------------------------------------------ el gestor
class GestorRed:
    def __init__(self, ejecutor: Ejecutor = ejecutar_nmcli,
                 sonda: Callable[[str | None], bool] = verificar_internet,
                 dormir: Callable[[float], None] = time.sleep) -> None:
        self._nmcli, self._sonda, self._dormir = ejecutor, sonda, dormir

    # ---- consulta --------------------------------------------------------------------------------
    def _salida(self, argumentos: list[str], tiempo_max_s: float = 15.0) -> str:
        codigo, salida, _ = self._nmcli(argumentos, tiempo_max_s=tiempo_max_s)
        return salida if codigo == 0 else ""

    def dispositivos(self) -> list[dict]:
        filas = []
        for linea in self._salida(["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"]).splitlines():
            c = _partir(linea)
            if len(c) >= 4:
                filas.append({"dispositivo": c[0], "tipo": c[1], "estado": c[2], "conexion": c[3]})
        return filas

    def interfaz_wifi(self) -> str | None:
        for d in self.dispositivos():
            if d["tipo"] == "wifi":
                return d["dispositivo"]
        return None

    def _ip(self, dispositivo: str) -> str | None:
        salida = self._salida(["-t", "-g", "IP4.ADDRESS", "device", "show", dispositivo]).strip().splitlines()
        return salida[0].split("/")[0] if salida and salida[0] else None

    def estado(self, comprobar_internet: bool = True) -> EstadoRed:
        activo, zt = None, None
        for d in self.dispositivos():
            conectado = d["estado"].startswith("connected")
            if d["tipo"] in ("wifi", "ethernet") and conectado and activo is None:
                activo = d
            elif d["tipo"] == "tun" and d["dispositivo"].startswith("zt") and conectado:
                zt = self._ip(d["dispositivo"])
        wifi = self.interfaz_wifi()
        if activo is None:
            return EstadoRed(zerotier_ip=zt, interfaz_wifi=wifi)
        ssid = senal = None
        if activo["tipo"] == "wifi":
            for linea in self._salida(["-t", "-f", "ACTIVE,SSID,SIGNAL", "device", "wifi", "list",
                                       "--rescan", "no"]).splitlines():
                c = _partir(linea)
                if len(c) >= 3 and c[0] == "yes":
                    ssid, senal = c[1], int(c[2]) if c[2].isdigit() else None
                    break
        return EstadoRed(tipo="wifi" if activo["tipo"] == "wifi" else "ethernet", ssid=ssid,
                         ip=self._ip(activo["dispositivo"]), senal=senal, zerotier_ip=zt, interfaz_wifi=wifi,
                         internet=self._sonda(activo["dispositivo"]) if comprobar_internet else None)

    def escanear(self, buscar_de_nuevo: bool = True) -> list[RedVisible]:
        """Redes WiFi a la vista, sin repetir nombres (queda la de mejor senal) y de mas a menos senal."""
        salida = self._salida(["-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan",
                               "yes" if buscar_de_nuevo else "no"], tiempo_max_s=25.0)
        mejores: dict[str, RedVisible] = {}
        for linea in salida.splitlines():
            c = _partir(linea)
            if len(c) < 3 or not c[0] or not c[1].isdigit():
                continue
            red = RedVisible(c[0], int(c[1]), c[2].strip())
            if c[0] not in mejores or red.senal > mejores[c[0]].senal:
                mejores[c[0]] = red
        return sorted(mejores.values(), key=lambda r: -r.senal)

    def _perfil_wifi_activo(self) -> str | None:
        for linea in self._salida(["-t", "-f", "NAME,TYPE", "connection", "show", "--active"]).splitlines():
            c = _partir(linea)
            if len(c) >= 2 and c[1] == "802-11-wireless":
                return c[0]
        return None

    def _perfiles_propios(self) -> list[str]:
        nombres = []
        for linea in self._salida(["-t", "-f", "NAME", "connection", "show"]).splitlines():
            nombre = _partir(linea)[0]
            if nombre.startswith(PREFIJO_PERFIL):
                nombres.append(nombre)
        return nombres

    # ---- cambio de red ---------------------------------------------------------------------------
    def configurar(self, ssid: str, contrasena: str = "", oculta: bool = False) -> ResultadoRed:
        """Conecta a una red nueva con reversion automatica (ver el docstring del modulo). BLOQUEA hasta 1 o 2
        minutos: debe correr fuera del ciclo del nucleo (un hilo aparte)."""
        try:
            validar_credenciales(ssid, contrasena)
        except ErrorRed as error:
            return ResultadoRed(False, str(error), motivo="datos")
        wifi = self.interfaz_wifi()
        if wifi is None:
            return ResultadoRed(False, "Este equipo no tiene WiFi", motivo="sin_wifi")

        anterior = self._perfil_wifi_activo()
        tenia_internet = self._sonda(None)
        REGISTRO.info("cambio de red a %r (anterior: %s, con internet: %s)", ssid, anterior, tenia_internet)

        perfil = nombre_de_perfil(ssid)
        self._nmcli(["connection", "delete", perfil], tiempo_max_s=15)       # si existia, se reemplaza
        argumentos = ["connection", "add", "type", "wifi", "ifname", wifi, "con-name", perfil, "ssid", ssid,
                      "connection.autoconnect", "yes", "connection.autoconnect-priority", str(PRIORIDAD_NUEVA)]
        if oculta:
            argumentos += ["wifi.hidden", "yes"]
        if contrasena:
            argumentos += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", contrasena]
        codigo, _, error = self._nmcli(argumentos, tiempo_max_s=20)
        if codigo != 0:
            REGISTRO.warning("no se pudo crear el perfil de red: %s", error.replace(contrasena, "***") if contrasena else error)
            return ResultadoRed(False, "No se pudo guardar la red", motivo="perfil")

        codigo, _, error = self._nmcli(["--wait", str(ESPERA_ACTIVAR_S), "connection", "up", perfil, "ifname", wifi],
                                       tiempo_max_s=ESPERA_ACTIVAR_S + 15)
        if codigo != 0:
            motivo, mensaje = explicar_fallo(error)
            REGISTRO.warning("la red %r no conecto (%s)", ssid, motivo)
            return self._revertir(perfil, anterior, wifi, motivo, mensaje)

        hay_internet = self._sonda(wifi)
        if not hay_internet and tenia_internet:
            REGISTRO.warning("la red %r conecto pero no sale a internet: se revierte", ssid)
            return self._revertir(perfil, anterior, wifi, "sin_internet",
                                  "La red conectó pero no tiene salida a internet")
        self._podar_perfiles(conservar=perfil)
        if not hay_internet:
            return ResultadoRed(True, f"Conectado a «{ssid}», pero sin salida a internet", sin_internet=True)
        return ResultadoRed(True, f"Conectado a «{ssid}»")

    def _revertir(self, perfil: str, anterior: str | None, wifi: str, motivo: str, mensaje: str) -> ResultadoRed:
        """Borra el perfil que fallo y vuelve a la red de antes."""
        self._nmcli(["connection", "delete", perfil], tiempo_max_s=15)
        if anterior and self._perfil_wifi_activo() != anterior:
            codigo, _, _ = self._nmcli(["--wait", str(ESPERA_ACTIVAR_S), "connection", "up", anterior, "ifname", wifi],
                                       tiempo_max_s=ESPERA_ACTIVAR_S + 15)
            if codigo != 0:                                                # NetworkManager lo reintenta solo (autoconnect)
                REGISTRO.error("no se pudo reactivar la red anterior %r de inmediato", anterior)
        return ResultadoRed(False, mensaje, revertida=anterior is not None, motivo=motivo,
                            sin_internet=motivo == "sin_internet")

    def _podar_perfiles(self, conservar: str) -> None:
        """Deja a lo sumo ``MAX_PERFILES_PROPIOS`` perfiles creados por G2 (la lista sale en orden de creacion)."""
        propios = [p for p in self._perfiles_propios()]
        sobrantes = [p for p in propios if p != conservar][: max(0, len(propios) - MAX_PERFILES_PROPIOS)]
        for p in sobrantes:
            self._nmcli(["connection", "delete", p], tiempo_max_s=15)
