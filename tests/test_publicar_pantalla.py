"""Pruebas de la preparacion de hitos de la pantalla (tools/publicar_pantalla.py)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import publicar_pantalla as P                                            # noqa: E402


class PruebasPublicar(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "g2.HMI").write_bytes(b"proyecto")
        (self.dir / "g2.tft").write_bytes(b"compilado")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def publicar(self, version="0.1.0", nota="Principal") -> str:
        return P.publicar(version, nota, self.dir, hoy=date(2026, 10, 16))

    def test_copia_el_tft_y_escribe_manifiesto_y_version(self) -> None:
        self.publicar()
        self.assertEqual((self.dir / "build" / "g2_v0.1.0.tft").read_bytes(), b"compilado")
        self.assertEqual((self.dir / "VERSION").read_text(), "0.1.0\n")
        manifiesto = (self.dir / "MANIFIESTO.md").read_text(encoding="utf-8")
        self.assertIn(P.sha256(self.dir / "g2.tft"), manifiesto)
        self.assertIn("| 0.1.0 | 2026-10-16 |", manifiesto)

    def test_repetir_con_los_mismos_archivos_no_cambia_nada(self) -> None:
        self.publicar()
        antes = (self.dir / "MANIFIESTO.md").read_text(encoding="utf-8")
        self.assertIn("sin cambios", self.publicar())
        self.assertEqual((self.dir / "MANIFIESTO.md").read_text(encoding="utf-8"), antes)

    def test_una_version_publicada_no_se_sobrescribe(self) -> None:
        self.publicar()
        (self.dir / "g2.tft").write_bytes(b"compilado distinto")
        with self.assertRaises(P.ErrorPublicacion):
            self.publicar()
        self.assertEqual((self.dir / "build" / "g2_v0.1.0.tft").read_bytes(), b"compilado")

    def test_versiones_nuevas_se_agregan_al_manifiesto(self) -> None:
        self.publicar()
        (self.dir / "g2.tft").write_bytes(b"otro")
        self.publicar("0.2.0", "Teclado")
        filas = [l for l in (self.dir / "MANIFIESTO.md").read_text(encoding="utf-8").splitlines()
                 if l.startswith("| 0.")]
        self.assertEqual(len(filas), 2)

    def test_version_invalida_o_archivo_faltante(self) -> None:
        with self.assertRaises(P.ErrorPublicacion):
            self.publicar("v1")
        (self.dir / "g2.tft").unlink()
        with self.assertRaises(P.ErrorPublicacion):
            self.publicar()

    def test_tft_mas_viejo_que_el_hmi_se_rechaza(self) -> None:
        viejo = (self.dir / "g2.HMI").stat().st_mtime - 3600
        os.utime(self.dir / "g2.tft", (viejo, viejo))
        with self.assertRaises(P.ErrorPublicacion):
            self.publicar()


if __name__ == "__main__":
    unittest.main()
