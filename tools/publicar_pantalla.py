"""Prepara un hito de la pantalla Nextion: copia el .tft a nextion/build/ con su version y deja
la huella SHA-256 del .HMI y del .tft en nextion/MANIFIESTO.md.

Para que se sepa siempre QUE programa tenia la pantalla en una fecha: el .tft que se carga en la
pantalla se identifica por su huella, y la Raspberry Pi registra esa huella en la base de datos
(cadena de auditoria) al cargarlo. Una version publicada es INMUTABLE: si ya existe en el manifiesto
con otras huellas, el programa se niega a sobrescribirla y pide subir el numero de version.

Uso (con el Nextion Editor cerrado, tras compilar):
    python tools/publicar_pantalla.py 0.1.0 --nota "Pagina principal"

No hace commit ni push ni etiquetas: solo prepara los archivos.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CARPETA = RAIZ / "nextion"
ENCABEZADO = ("# Manifiesto de versiones de la pantalla Nextion\n\n"
              "Una fila por version publicada. Las huellas son SHA-256 de los archivos guardados con Git LFS.\n"
              "Una version publicada no se modifica: un cambio lleva un numero nuevo.\n\n"
              "| Version | Fecha | Huella SHA-256 del .HMI | Huella SHA-256 del .tft | Bytes del .tft | Nota |\n"
              "|---|---|---|---|---|---|\n")
VERSION_VALIDA = re.compile(r"^\d+\.\d+\.\d+$")


class ErrorPublicacion(Exception):
    """Version invalida, archivo faltante o version ya publicada con otro contenido."""


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def publicar(version: str, nota: str, carpeta: Path = CARPETA, hoy: date | None = None) -> str:
    """Copia el .tft a build/, actualiza VERSION y el manifiesto. Devuelve un resumen."""
    if not VERSION_VALIDA.match(version):
        raise ErrorPublicacion(f"Version invalida '{version}': use el formato 0.1.0")
    hmi, tft = carpeta / "g2.HMI", carpeta / "g2.tft"
    for ruta in (hmi, tft):
        if not ruta.is_file():
            raise ErrorPublicacion(f"Falta {ruta.name}: compile el proyecto en el editor")
    # El .tft sale de compilar el .HMI: si es mas viejo, es de una version anterior del diseno.
    if tft.stat().st_mtime < hmi.stat().st_mtime - 2:
        raise ErrorPublicacion("El g2.tft es mas viejo que el g2.HMI: vuelva a compilar en el editor")

    try:
        h_hmi, h_tft = sha256(hmi), sha256(tft)
    except PermissionError as error:
        raise ErrorPublicacion(f"No se puede leer {Path(error.filename).name}: cierre el Nextion Editor "
                               "(lo mantiene bloqueado mientras esta abierto)") from error
    manifiesto = carpeta / "MANIFIESTO.md"
    texto = manifiesto.read_text(encoding="utf-8") if manifiesto.exists() else ENCABEZADO
    fila_previa = next((l for l in texto.splitlines() if l.startswith(f"| {version} |")), None)
    if fila_previa:
        if h_hmi in fila_previa and h_tft in fila_previa:
            return f"La version {version} ya estaba publicada con estas mismas huellas: sin cambios."
        raise ErrorPublicacion(f"La version {version} ya esta publicada con otras huellas: "
                               "suba el numero de version (una version publicada no se modifica)")

    destino = carpeta / "build" / f"g2_v{version}.tft"
    destino.parent.mkdir(exist_ok=True)
    shutil.copyfile(tft, destino)
    fila = (f"| {version} | {(hoy or date.today()).isoformat()} | `{h_hmi}` | `{h_tft}` | "
            f"{tft.stat().st_size} | {nota.replace('|', '/')} |\n")
    manifiesto.write_text(texto.rstrip("\n") + "\n" + fila, encoding="utf-8", newline="\n")
    (carpeta / "VERSION").write_text(version + "\n", encoding="utf-8", newline="\n")
    return (f"Version {version} preparada: {destino.relative_to(carpeta.parent)}\n"
            f"  .HMI {h_hmi}\n  .tft {h_tft}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("version", help="numero de version, por ejemplo 0.1.0")
    ap.add_argument("--nota", default="", help="que contiene esta version")
    args = ap.parse_args()
    try:
        print(publicar(args.version, args.nota))
    except ErrorPublicacion as error:
        print(f"ERROR: {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
