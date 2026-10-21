"""Pruebas de la conversion a % de O2 y del agregado por intervalo (g2.nucleo.senal)."""

from __future__ import annotations

import unittest

from g2.nucleo import senal


class PruebasConversion(unittest.TestCase):
    def test_diez_milivoltios_por_cada_uno_por_ciento(self) -> None:
        self.assertAlmostEqual(senal.tension_a_pct(0.209, 10.0), 20.9)
        self.assertAlmostEqual(senal.tension_a_pct(1.0, 10.0), 100.0)
        self.assertAlmostEqual(senal.tension_a_pct(0.0, 10.0), 0.0)

    def test_el_offset_de_la_calibracion_se_suma(self) -> None:
        self.assertAlmostEqual(senal.tension_a_pct(0.2080, 10.0, offset_pct=0.1), 20.9)
        self.assertAlmostEqual(senal.tension_a_pct(0.2100, 10.0, offset_pct=-0.1), 20.9)

    def test_sensibilidad_invalida(self) -> None:
        with self.assertRaises(ValueError):
            senal.tension_a_pct(0.2, 0.0)

    def test_marcas_de_saturacion(self) -> None:
        self.assertEqual(senal.calidad_de_muestra(20.9), 0)
        self.assertEqual(senal.calidad_de_muestra(-15.1), senal.CALIDAD_SATURADA_BAJA)
        self.assertEqual(senal.calidad_de_muestra(200.1), senal.CALIDAD_SATURADA_ALTA)
        self.assertEqual(senal.calidad_de_muestra(-15.0), 0)           # el limite mismo es valido


class PruebasAcumulador(unittest.TestCase):
    def test_promedio_minimo_y_maximo(self) -> None:
        acum = senal.Acumulador()
        for o2 in (20.0, 21.0, 22.0):
            acum.agregar(o2, o2 * 10)
        r = acum.cerrar()
        self.assertEqual(r.n_muestras, 3)
        self.assertAlmostEqual(r.o2_prom, 21.0)
        self.assertEqual((r.o2_min, r.o2_max), (20.0, 22.0))
        self.assertAlmostEqual(r.mv_prom, 210.0)
        self.assertEqual(r.calidad, 0)

    def test_un_intervalo_sin_datos_es_un_hueco_no_un_cero(self) -> None:
        acum = senal.Acumulador()
        acum.agregar_sin_dato()
        r = acum.cerrar()
        self.assertEqual(r.n_muestras, 0)
        self.assertIsNone(r.o2_prom)
        self.assertIsNone(r.mv_prom)
        self.assertEqual(r.calidad, senal.CALIDAD_SIN_DATOS)

    def test_intervalo_con_huecos_se_marca_inestable(self) -> None:
        acum = senal.Acumulador()
        acum.agregar(20.0, 200.0)
        acum.agregar_sin_dato()
        r = acum.cerrar()
        self.assertEqual(r.n_muestras, 1)
        self.assertTrue(r.calidad & senal.CALIDAD_INESTABLE)

    def test_las_marcas_de_saturacion_se_acumulan(self) -> None:
        acum = senal.Acumulador()
        acum.agregar(201.0, 2010.0)
        acum.agregar(20.0, 200.0)
        self.assertTrue(acum.cerrar().calidad & senal.CALIDAD_SATURADA_ALTA)

    def test_cerrar_deja_el_acumulador_limpio_para_el_siguiente_intervalo(self) -> None:
        acum = senal.Acumulador()
        acum.agregar(30.0, 300.0)
        acum.cerrar()
        self.assertEqual(acum.n_intentos, 0)
        acum.agregar(10.0, 100.0)
        r = acum.cerrar()
        self.assertEqual((r.n_muestras, r.o2_prom), (1, 10.0))


if __name__ == "__main__":
    unittest.main()
