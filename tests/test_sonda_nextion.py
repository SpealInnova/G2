"""Pruebas del interprete de la sonda de la pantalla (tools/banco/sonda_nextion.py) con la respuesta
REAL que dio la NX8048P050_011R el 2026-10-21."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "banco"))
import sonda_nextion as S                                                # noqa: E402

RESPUESTA_REAL = b"c\x00omok 1,1281-0,NX8048P050_011R,293,10501,AEB234012ED59D5B,128974848-0\xff\xff\xff"


class PruebasSonda(unittest.TestCase):
    def test_reconoce_la_respuesta_real_con_un_byte_nulo_suelto(self) -> None:
        linea = S.interpretar(RESPUESTA_REAL)
        self.assertIsNotNone(linea)
        partes = linea.split(",")
        self.assertEqual(partes[2], "NX8048P050_011R")                  # modelo
        self.assertEqual(partes[3], "293")                              # firmware
        self.assertEqual(partes[5], "AEB234012ED59D5B")                 # numero de serie
        self.assertEqual(int(partes[6].split("-")[0]), 128974848)       # flash

    def test_respuesta_limpia(self) -> None:
        self.assertTrue(S.interpretar(b"comok 1,x,MODELO,1,2,3,4" + S.FIN).startswith("comok"))

    def test_sin_respuesta_o_con_otra_cosa(self) -> None:
        self.assertIsNone(S.interpretar(b""))
        self.assertIsNone(S.interpretar(b"\x1a" + S.FIN))


if __name__ == "__main__":
    unittest.main()
