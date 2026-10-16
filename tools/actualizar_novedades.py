"""Actualiza la seccion "Novedades" del README con los cambios publicados, por fecha.

Uso (desde la raiz del proyecto, antes de hacer el commit):

    python tools/actualizar_novedades.py                       # con los commits ya hechos
    python tools/actualizar_novedades.py --mensaje mensaje.txt # y ademas el commit que se va a hacer

Lee ``git log`` (fecha, titulo y viñetas del mensaje de cada commit), los agrupa por dia y
reemplaza lo que hay entre las marcas ``<!-- NOVEDADES:INICIO -->`` y ``<!-- NOVEDADES:FIN -->``
del README. El resto del README no se toca.

Con ``--mensaje`` se incluye el commit que aun no existe (su texto sale del archivo con el
mensaje, que es el mismo que se le pasa a ``git commit -F``), para que el README ya lo traiga y
quede en el mismo commit. La fecha es la de hoy.

El README es publico: lo unico que se publica es lo que ya dicen los mensajes de los commits,
que no deben llevar direcciones, contrasenas ni datos de acceso.
"""

from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
README = RAIZ / "README.md"
INICIO = "<!-- NOVEDADES:INICIO -->"
FIN = "<!-- NOVEDADES:FIN -->"
SEP_CAMPO, SEP_REG = "\x1f", "\x1e"
MAX_VINETAS = 5
MAX_LARGO = 230


@dataclass(frozen=True)
class Commit:
    fecha: str          # AAAA-MM-DD
    hash: str           # abreviado; vacio si aun no existe
    titulo: str
    cuerpo: str


def leer_commits(cantidad: int) -> list[Commit]:
    salida = subprocess.run(
        ["git", "-C", str(RAIZ), "log", f"-n{cantidad}", "--date=short",
         f"--pretty=format:%ad{SEP_CAMPO}%h{SEP_CAMPO}%s{SEP_CAMPO}%b{SEP_REG}"],
        capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return parsear(salida)


def parsear(texto: str) -> list[Commit]:
    commits = []
    for registro in texto.split(SEP_REG):
        registro = registro.strip("\n")
        if not registro.strip():
            continue
        fecha, hash_, titulo, cuerpo = (registro.split(SEP_CAMPO, 3) + ["", "", "", ""])[:4]
        commits.append(Commit(fecha.strip(), hash_.strip(), titulo.strip(), cuerpo))
    return commits


def desde_mensaje(ruta: Path, hoy: str) -> Commit:
    """El commit pendiente, a partir del archivo con su mensaje."""
    texto = ruta.read_text(encoding="utf-8").strip("\n")
    titulo, _, cuerpo = texto.partition("\n")
    return Commit(hoy, "", titulo.strip(), cuerpo)


def vinetas(cuerpo: str) -> list[str]:
    """Las viñetas ("- ...") del cuerpo, juntando las lineas de continuacion.

    Se ignora la linea de coautoria y todo lo que no sea una viñeta (los parrafos sueltos).
    """
    resultado: list[str] = []
    actual: str | None = None
    for linea in cuerpo.splitlines():
        if linea.startswith("Co-Authored-By") or not linea.strip():
            if actual is not None:
                resultado.append(actual)
                actual = None
            continue
        if linea.startswith("- "):
            if actual is not None:
                resultado.append(actual)
            actual = linea[2:].strip()
        elif linea.startswith("  ") and actual is not None:
            actual += " " + linea.strip()
        else:
            if actual is not None:
                resultado.append(actual)
                actual = None
    if actual is not None:
        resultado.append(actual)
    return [v if len(v) <= MAX_LARGO else v[:MAX_LARGO - 1].rstrip() + "…" for v in resultado]


def formatear(commits: list[Commit]) -> str:
    """Markdown agrupado por fecha (la mas reciente primero)."""
    if not commits:
        return "_Aún no hay cambios publicados._"
    dias: dict[str, list[Commit]] = {}
    for c in commits:
        dias.setdefault(c.fecha, []).append(c)
    bloques = []
    for fecha in sorted(dias, reverse=True):
        lineas = [f"### {fecha}", ""]
        for c in dias[fecha]:
            referencia = f" (`{c.hash}`)" if c.hash else ""
            lineas.append(f"- **{c.titulo}**{referencia}")
            for v in vinetas(c.cuerpo)[:MAX_VINETAS]:
                lineas.append(f"  - {v}")
        bloques.append("\n".join(lineas))
    return "\n\n".join(bloques)


def reemplazar_bloque(readme: str, contenido: str) -> str:
    """Pone ``contenido`` entre las marcas del README. Falla si faltan las marcas."""
    if readme.count(INICIO) != 1 or readme.count(FIN) != 1:
        raise ValueError(f"El README debe tener exactamente una marca {INICIO} y una {FIN}")
    antes, resto = readme.split(INICIO)
    _, despues = resto.split(FIN)
    return f"{antes}{INICIO}\n\n{contenido}\n\n{FIN}{despues}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Actualiza las novedades del README")
    ap.add_argument("--mensaje", type=Path, help="archivo con el mensaje del commit pendiente")
    ap.add_argument("--cantidad", type=int, default=15, help="cuantos commits mostrar")
    args = ap.parse_args()

    commits = leer_commits(args.cantidad)
    if args.mensaje:
        hoy = datetime.date.today().isoformat()
        commits = [desde_mensaje(args.mensaje, hoy)] + commits[: args.cantidad - 1]
    texto = README.read_text(encoding="utf-8")
    nuevo = reemplazar_bloque(texto, formatear(commits))
    README.write_text(nuevo, encoding="utf-8", newline="\n")
    print(f"README actualizado con {len(commits)} cambio(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
