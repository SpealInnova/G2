"""La memoria USB del reporte (D-044): encontrarla, comprobar su nombre, copiar el archivo y desmontarla.

Seguridad: el reporte SOLO se copia a una memoria USB cuyo nombre (etiqueta del volumen) sea igual al nombre del equipo.
Asi un reporte no se lleva por error a una memoria cualquiera. Ojo: una memoria FAT/FAT32 admite como mucho 11 letras en
su nombre; un nombre como ``ANZD-600226001`` (14) pide formatearla como exFAT o NTFS.

Todo lo que habla con el sistema (``lsblk``, ``udisksctl``) pasa por ``ejecutar``, para poder probarlo sin hardware.
Montar y desmontar usa ``udisks2`` (permiso de polkit en ``systemd/50-g2.rules``); si el volumen ya estaba montado, se usa
donde esta y NO se desmonta.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

Ejecutor = Callable[[list[str]], "subprocess.CompletedProcess[str]"]
HOLGURA_ESPACIO = 1.1                               # espacio libre necesario, como multiplo del tamano del archivo


class ErrorUsb(Exception):
    """Algo fallo con la memoria USB; el mensaje es corto y se puede mostrar en la pantalla."""


@dataclass(frozen=True)
class Particion:
    ruta: str                                       # /dev/sda1
    etiqueta: str
    fstype: str
    montaje: str | None = None


def correr(comando: list[str]) -> "subprocess.CompletedProcess[str]":
    try:
        return subprocess.run(comando, capture_output=True, text=True, timeout=45, check=False)
    except FileNotFoundError:
        raise ErrorUsb(f"Falta el programa {comando[0]} en el equipo") from None
    except subprocess.TimeoutExpired:
        raise ErrorUsb("La memoria USB no responde") from None


# NAME va primero a proposito: asi lsblk entrega el ARBOL (disco -> particiones). Con otra columna primera entrega una lista
# plana y las particiones pierden el transporte ``usb`` de su disco (comprobado en la Pi con una memoria NTFS).
COLUMNAS_LSBLK = "NAME,PATH,LABEL,FSTYPE,MOUNTPOINT,RM,HOTPLUG,TRAN,TYPE,SIZE"
SISTEMA = ("/", "/boot", "/home", "/var", "/usr", "/etc")        # nunca se escribe donde vive el sistema


def _es_del_sistema(montaje: str | None) -> bool:
    return bool(montaje) and (montaje in SISTEMA or montaje.startswith(("/boot/", "/var/", "/usr/", "/etc/")))  # type: ignore[union-attr]


def explorar(ejecutar: Ejecutor = correr) -> tuple[list[Particion], int]:
    """``(volumenes, sin_formato)``: los volumenes con sistema de archivos de los dispositivos USB y cuantas particiones (o
    discos con medio) USB hay SIN sistema de archivos reconocible (sin formatear, danados o con un formato que Linux no abre).
    Solo cuenta el transporte ``usb``: la tarjeta SD de la Raspberry Pi (``mmc``) tambien se declara «extraible» y NO es una
    memoria de reportes (comprobado en la Pi)."""
    salida = ejecutar(["lsblk", "-J", "-o", COLUMNAS_LSBLK])
    if salida.returncode != 0:
        raise ErrorUsb("No se pudo buscar la memoria USB")
    try:
        arbol = json.loads(salida.stdout)["blockdevices"]
    except (ValueError, KeyError, TypeError):
        raise ErrorUsb("No se pudo leer la lista de memorias USB") from None
    encontrados: list[Particion] = []
    sin_formato = 0

    def recorrer(nodo: dict, extraible: bool) -> None:
        nonlocal sin_formato
        extraible = extraible or nodo.get("tran") == "usb"
        hijos = nodo.get("children") or []
        if extraible and nodo.get("type") in ("part", "disk") and not _es_del_sistema(nodo.get("mountpoint")):
            if nodo.get("fstype"):
                encontrados.append(Particion(nodo["path"], nodo.get("label") or "", nodo["fstype"], nodo.get("mountpoint")))
            elif not hijos and (nodo["type"] == "part" or str(nodo.get("size") or "0").strip() not in ("0", "0B")):
                sin_formato += 1                         # un lector de tarjetas vacio (disco de 0 B) no cuenta
        for hijo in hijos:
            recorrer(hijo, extraible)

    for nodo in arbol:
        recorrer(nodo, False)
    return encontrados, sin_formato


def listar(ejecutar: Ejecutor = correr) -> list[Particion]:
    """Los volumenes con sistema de archivos de los dispositivos USB (ver ``explorar``)."""
    return explorar(ejecutar)[0]


def _igual(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def buscar(nombre: str, ejecutar: Ejecutor = correr) -> Particion:
    """La memoria USB que se llama como el equipo.

    Raises:
        ErrorUsb: si no hay ninguna, o ninguna tiene ese nombre.
    """
    candidatas, sin_formato = explorar(ejecutar)
    if not candidatas:
        if sin_formato:
            raise ErrorUsb("La USB no tiene un formato legible (use exFAT o NTFS)")
        raise ErrorUsb(f"Inserte la memoria USB llamada «{nombre}»")
    for particion in candidatas:
        if _igual(particion.etiqueta, nombre):
            return particion
    vistas = ", ".join(f"«{p.etiqueta or 'sin nombre'}»" for p in candidatas)
    solo_fat = len(nombre) > 11 and all(p.fstype in ("vfat", "fat", "msdos") for p in candidatas)
    ayuda = ". En FAT no caben más de 11 letras: formatee en exFAT" if solo_fat else ""
    raise ErrorUsb(f"La memoria USB se llama {vistas}; debe llamarse «{nombre}»{ayuda}")


def montar(particion: Particion, ejecutar: Ejecutor = correr) -> tuple[Path, bool]:
    """``(carpeta, la_montamos_nosotros)``: donde esta montada la memoria. Si ya lo estaba, se usa tal cual."""
    if particion.montaje:
        return Path(particion.montaje), False
    salida = ejecutar(["udisksctl", "mount", "-b", particion.ruta, "--no-user-interaction"])
    if salida.returncode != 0:
        raise ErrorUsb("No se pudo abrir la memoria USB")
    encontrado = re.search(r" at (.+?)\.?\s*$", salida.stdout.strip())
    if not encontrado:
        raise ErrorUsb("No se supo dónde quedó la memoria USB")
    return Path(encontrado.group(1)), True


def desmontar(particion: Particion, montamos: bool, ejecutar: Ejecutor = correr) -> bool:
    """Desmonta la memoria si la montamos nosotros. Devuelve False si no se pudo (el archivo ya esta copiado y verificado)."""
    if hasattr(os, "sync"):
        os.sync()
    if not montamos:
        return True
    return ejecutar(["udisksctl", "unmount", "-b", particion.ruta, "--no-user-interaction"]).returncode == 0


def sha256(ruta: Path) -> str:
    resumen = hashlib.sha256()
    with open(ruta, "rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


def nombre_libre(carpeta: Path, nombre: str) -> str:
    """``nombre`` si no existe en la carpeta; si existe, ``nombre_2``, ``nombre_3``... (nunca se sobrescribe)."""
    base, punto, extension = nombre.rpartition(".")
    candidato, n = nombre, 1
    while (carpeta / candidato).exists() or (carpeta / f"{candidato}.sha256").exists():
        n += 1
        candidato = f"{base}_{n}{punto}{extension}"
    return candidato


def copiar(origen: Path, carpeta: Path, nombre: str) -> tuple[Path, str]:
    """Copia ``origen`` a ``carpeta/nombre`` (y deja a su lado ``nombre.sha256``), la verifica leyendola de vuelta y devuelve
    ``(ruta_final, sha256)``. Se escribe con un nombre temporal y se renombra al final: si algo falla a medias NO queda un
    archivo incompleto con el nombre del reporte.

    Raises:
        ErrorUsb: sin espacio, sin permiso de escritura o si la copia no coincide con el original.
    """
    tamano = origen.stat().st_size
    parcial: Path | None = None
    try:
        if shutil.disk_usage(carpeta).free < tamano * HOLGURA_ESPACIO + 4096:
            raise ErrorUsb("No hay espacio suficiente en la memoria USB")
        nombre = nombre_libre(carpeta, nombre)
        final, parcial = carpeta / nombre, carpeta / f".{nombre}.parte"
        huella = sha256(origen)
        with open(origen, "rb") as entrada, open(parcial, "wb") as salida:
            shutil.copyfileobj(entrada, salida, 1024 * 1024)
            salida.flush()
            os.fsync(salida.fileno())
        if sha256(parcial) != huella:
            parcial.unlink(missing_ok=True)
            raise ErrorUsb("La copia no coincide con el original: se descarta")
        os.replace(parcial, final)
        archivo_huella = carpeta / f"{nombre}.sha256"
        with open(archivo_huella, "w", encoding="utf-8", newline="\n") as salida:
            salida.write(f"{huella} *{nombre}\n")
            salida.flush()
            os.fsync(salida.fileno())
    except OSError as error:
        if parcial is not None:
            try:
                parcial.unlink(missing_ok=True)
            except OSError:
                pass
        raise ErrorUsb(f"No se pudo escribir en la memoria USB ({error.strerror or error})") from None
    return final, huella
