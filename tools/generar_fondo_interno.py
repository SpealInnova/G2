"""Genera el fondo de las paginas interiores de la pantalla (nextion/fondos/interna.png).

Toma la barra superior con el logotipo del fondo de la pagina principal (nextion/fondos/principal.png,
las 56 primeras filas) y debajo deja el color de fondo con un unico panel blanco de esquinas
redondeadas (x 16-784, y 72-464), igual de sobrio que las tarjetas de la pagina principal. Sin texto:
los textos y los botones los pone la pantalla encima (ver nextion/ESPECIFICACION_HMI.md).

Uso:  python tools/generar_fondo_interno.py        (despues de tools/ajustar_fondo_nextion.py)
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "nextion" / "fondos" / "principal.png"
SALIDA = RAIZ / "nextion" / "fondos" / "interna.png"
ANCHO, ALTO, ALTO_BARRA = 800, 480, 56
PANEL = (16, 72, 784, 464)          # x0, y0, x1, y1 del panel blanco
RADIO = 12
AMPLIACION = 4                      # se dibuja ampliado y se reduce, para bordes sin dientes de sierra
BLANCO = (255, 255, 255)


def main() -> None:
    principal = Image.open(ENTRADA).convert("RGB")
    assert principal.size == (ANCHO, ALTO), "ejecute antes tools/ajustar_fondo_nextion.py"
    # Colores tomados de la propia pagina principal para que ambas se vean iguales:
    # el fondo en un punto vacio entre la barra y las tarjetas y el borde en el lateral de una tarjeta.
    fondo = principal.getpixel((8, 200))
    borde = min((principal.getpixel((x, 200)) for x in range(14, 20)), key=sum)

    grande = Image.new("RGB", (ANCHO * AMPLIACION, ALTO * AMPLIACION), fondo)
    x0, y0, x1, y1 = (v * AMPLIACION for v in PANEL)
    ImageDraw.Draw(grande).rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=RADIO * AMPLIACION,
                                             fill=BLANCO, outline=borde, width=AMPLIACION)
    imagen = grande.resize((ANCHO, ALTO), Image.LANCZOS)
    imagen.paste(principal.crop((0, 0, ANCHO, ALTO_BARRA)), (0, 0))      # barra con el logotipo
    imagen.save(SALIDA, optimize=True)
    print(f"{SALIDA.name}: {imagen.size[0]}x{imagen.size[1]} (fondo {fondo}, borde {borde})")


if __name__ == "__main__":
    main()
