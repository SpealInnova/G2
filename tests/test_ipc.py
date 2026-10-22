"""Pruebas de la comunicacion por archivos entre g2-core y g2-ui (g2.ipc)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from g2 import ipc


class PruebasIpc(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "run"                     # no existe todavia
        self.t = [1000.0]
        self.nucleo = ipc.PublicadorEstado(self.dir, reloj=lambda: self.t[0])
        self.ui = ipc.ClienteNucleo(self.dir, reloj=lambda: self.t[0])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_el_estado_publicado_se_lee_con_su_edad(self) -> None:
        self.nucleo.publicar({"aviso": "Sin alarmas", "sensores": []})
        self.t[0] += 2.5
        estado, edad = self.ui.leer_estado()
        self.assertEqual(estado["aviso"], "Sin alarmas")
        self.assertAlmostEqual(edad, 2.5)
        self.assertEqual(estado["secuencia"], 1)

    def test_sin_archivo_o_ilegible_es_sin_estado(self) -> None:
        estado, edad = self.ui.leer_estado()
        self.assertIsNone(estado)
        self.assertEqual(edad, float("inf"))
        (self.dir / ipc.NOMBRE_ESTADO).write_text("{no es json", encoding="utf-8")
        self.assertEqual(self.ui.leer_estado(), (None, float("inf")))

    def test_publicar_no_deja_archivos_temporales(self) -> None:
        for _ in range(3):
            self.nucleo.publicar({"x": 1})
        nombres = sorted(p.name for p in self.dir.iterdir())
        self.assertEqual(nombres, sorted([ipc.CARPETA_ORDENES, ipc.NOMBRE_ESTADO]))

    def test_texto_con_acentos_viaja_bien(self) -> None:
        self.nucleo.publicar({"aviso": "S1 SIN SEÑAL"})
        self.assertEqual(self.ui.leer_estado()[0]["aviso"], "S1 SIN SEÑAL")

    def test_las_ordenes_se_recogen_en_orden_y_se_borran(self) -> None:
        a = self.ui.enviar_orden("acusar", actor="pantalla")
        self.t[0] += 0.01
        b = self.ui.enviar_orden("otra")
        ordenes = self.nucleo.recoger_ordenes()
        self.assertEqual([o["uuid"] for o in ordenes], [a, b])
        self.assertEqual([o["tipo"] for o in ordenes], ["acusar", "otra"])
        self.assertEqual(ordenes[0]["origen"], "pantalla")
        self.assertEqual(self.nucleo.recoger_ordenes(), [])             # ya se habian borrado

    def test_una_orden_ilegible_se_descarta_y_no_bloquea_a_las_demas(self) -> None:
        (self.dir / ipc.CARPETA_ORDENES / "0000-malo.json").write_text("{basura", encoding="utf-8")
        bueno = self.ui.enviar_orden("acusar")
        ordenes = self.nucleo.recoger_ordenes()
        self.assertEqual([o["uuid"] for o in ordenes], [bueno])
        self.assertEqual(list((self.dir / ipc.CARPETA_ORDENES).iterdir()), [])

    def test_cada_orden_tiene_un_uuid_distinto(self) -> None:
        ids = {self.ui.enviar_orden("acusar") for _ in range(5)}
        self.assertEqual(len(ids), 5)

    def test_carpeta_por_defecto_sale_de_g2_run(self) -> None:
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"G2_RUN": "/run/g2"}):
            self.assertEqual(ipc.carpeta_por_defecto(), Path("/run/g2"))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(ipc.carpeta_por_defecto())


if __name__ == "__main__":
    unittest.main()
