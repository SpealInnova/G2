"""Pruebas del decodificador de la herramienta de banco de la pantalla (tools/banco/pantalla.py)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "banco"))
import pantalla as P                                                     # noqa: E402

FIN = P.FIN


class PruebasDecodificador(unittest.TestCase):
    def test_toque_de_un_boton_conocido(self) -> None:
        self.assertEqual(P.decodificar(bytes([0x65, 0x06, 0x17, 0x00])), "toque: teclado.k_7")
        self.assertEqual(P.decodificar(bytes([0x65, 0x00, 0x06, 0x00])), "toque: principal.b_acuse")
        self.assertEqual(P.decodificar(bytes([0x65, 0x06, 0x1F, 0x00])), "toque: teclado.b_aceptar")

    def test_pagina_cargada_y_pantalla_encendida(self) -> None:
        self.assertEqual(P.decodificar(bytes([0x65, 0x06, 0xFE, 0x00])), "pagina cargada: teclado")
        self.assertIn("encendida", P.decodificar(bytes([0x88])))

    def test_codigos_desconocidos_no_se_ocultan(self) -> None:
        self.assertIn("control?7F", P.decodificar(bytes([0x65, 0x06, 0x7F, 0x00])))
        self.assertIn("pagina?09", P.decodificar(bytes([0x65, 0x09, 0x01, 0x00])))
        self.assertIn("desconocida", P.decodificar(bytes([0x42, 0x01])))

    def test_respuestas_a_get(self) -> None:
        self.assertEqual(P.decodificar(b"\x70" + "Señal".encode("iso-8859-1")), "texto: Señal")
        self.assertEqual(P.decodificar(bytes([0x71, 1, 0, 0, 0])), "numero: 1")
        self.assertEqual(P.decodificar(bytes([0x71, 0xFF, 0xFF, 0xFF, 0xFF])), "numero: -1")

    def test_respuestas_de_error(self) -> None:
        self.assertIn("invalido", P.decodificar(bytes([0x1A])))
        self.assertIn("orden invalida", P.decodificar(bytes([0x00])))
        self.assertIn("correcta", P.decodificar(bytes([0x01])))

    def test_separar_tramas_completas_y_dejar_el_resto(self) -> None:
        datos = bytes([0x65, 0x00, 0x01, 0x00]) + FIN + bytes([0x65, 0x06]) + FIN[:1]
        tramas, resto = P.separar(datos)
        self.assertEqual(tramas, [bytes([0x65, 0x00, 0x01, 0x00])])
        self.assertEqual(resto, bytes([0x65, 0x06]) + FIN[:1])
        tramas, resto = P.separar(resto + FIN[1:])                       # llega el final que faltaba
        self.assertEqual(tramas, [bytes([0x65, 0x06])])
        self.assertEqual(resto, b"")

    def test_codifica_ordenes_en_iso_8859_1(self) -> None:
        self.assertEqual(P.codificar_orden('est_1.txt="SIN SEÑAL"'),
                         b'est_1.txt="SIN SE\xd1AL"' + FIN)

    def test_los_codigos_de_las_teclas_coinciden_con_la_especificacion(self) -> None:
        teclas = P.CONTROLES[0x06]
        self.assertEqual([teclas[0x10 + d] for d in range(10)], [f"k_{d}" for d in range(10)])
        self.assertEqual(teclas[0x1A], "k_punto")
        self.assertEqual(teclas[0x1F], "b_aceptar")


if __name__ == "__main__":
    unittest.main()
