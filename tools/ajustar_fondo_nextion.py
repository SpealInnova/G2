"""Ajusta el fondo de la pagina principal de la Nextion a la cuadricula de la especificacion.

La imagen generada por la IA tiene la proporcion correcta (5:3) pero sus zonas (barra, tarjetas,
franja de avisos y botones) quedan comprimidas en vertical respecto de lo pedido. Este programa la
estira POR BANDAS horizontales para que cada zona caiga exactamente donde dice
nextion/ESPECIFICACION_HMI.md, y deja el resultado en 800x480 (tamano nativo de la pantalla).

Ademas coloca el logotipo de SPEAL (nextion/imagenes/logo.png) en la barra superior. La pantalla
no maneja transparencia, por eso el logo se compone aqui sobre el color real de la barra y queda
integrado en el fondo, sin un componente aparte.

Uso:  python tools/ajustar_fondo_nextion.py
Entrada: nextion/fondos/origen_principal_chatgpt.png y nextion/imagenes/logo.png
Salida:  nextion/fondos/principal.png

Las coordenadas de ORIGEN se midieron sobre la imagen original (1619x971); las de DESTINO son las
de la especificacion (pantalla de 800x480).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "nextion" / "fondos" / "origen_principal_chatgpt.png"
LOGO = RAIZ / "nextion" / "imagenes" / "logo.png"
SALIDA = RAIZ / "nextion" / "fondos" / "principal.png"
LOGO_TAMANO = (110, 44)       # la barra mide 56 px de alto: 6 px de margen arriba y abajo
LOGO_POSICION = (16, 6)       # el titulo empieza despues (x=138, ver la especificacion)
ANCHO, ALTO = 800, 480

# (y_origen, y_destino): cada par fija un borde; entre dos pares consecutivos se estira la banda.
PUNTOS = [
    (0.0, 0),        # arriba
    (93.5, 56),      # fin de la barra superior
    (131.0, 72),     # borde superior de las tarjetas
    (591.0, 352),    # borde inferior de las tarjetas
    (617.0, 364),    # borde superior de la franja de avisos
    (697.0, 412),    # borde inferior de la franja de avisos
    (827.0, 424),    # borde superior de los botones
    (905.0, 472),    # borde inferior de los botones
    (971.0, 480),    # abajo
]


# Marca de agua de la molecula de oxigeno (en la imagen original queda entre la franja de avisos
# y los botones, un hueco que al ajustarse mide solo 12 px y la dejaria aplastada): se borra.
MARCA_DE_AGUA = (700, 700, 925, 822)      # x0, y0, x1, y1 sobre la imagen original
PUNTO_DE_COLOR_DE_FONDO = (600, 760)      # un punto vacio del fondo, de donde tomar el color


def main() -> None:
    origen = Image.open(ENTRADA).convert("RGB")
    ancho, alto = origen.size
    assert alto == 971, f"se esperaba una imagen de 971 px de alto, trae {alto}"
    ImageDraw.Draw(origen).rectangle(MARCA_DE_AGUA, fill=origen.getpixel(PUNTO_DE_COLOR_DE_FONDO))
    resultado = Image.new("RGB", (ANCHO, ALTO))
    for (o0, d0), (o1, d1) in zip(PUNTOS, PUNTOS[1:]):
        banda = origen.resize((ANCHO, d1 - d0), Image.LANCZOS, box=(0, o0, ancho, o1))
        resultado.paste(banda, (0, d0))
    # Logotipo: se compone con su canal alfa sobre la barra (la pantalla no tiene transparencia).
    logo = Image.open(LOGO).convert("RGBA").resize(LOGO_TAMANO, Image.LANCZOS)
    resultado.paste(logo, LOGO_POSICION, mask=logo.getchannel("A"))
    resultado.save(SALIDA, optimize=True)
    print(f"{SALIDA.relative_to(RAIZ)}: {resultado.size[0]}x{resultado.size[1]}")


if __name__ == "__main__":
    main()
