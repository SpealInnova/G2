"""Pruebas del catalogo de configuracion (D-027)."""

from __future__ import annotations

import unittest

from g2.configuracion import catalogo
from g2.configuracion.catalogo import ErrorConfig, normalizar, obtener


class PruebasCatalogo(unittest.TestCase):
    def test_el_catalogo_es_coherente(self) -> None:
        self.assertEqual(catalogo.verificar_catalogo(), [])

    def test_valores_por_defecto_definidos_por_el_usuario(self) -> None:
        esperado = {
            "muestreo.intervalo_pantalla_s": "1",
            "alarma.o2_bajo_pct": "20.0",
            "alarma.o2_alto_pct": "92.0",
            "salud.temp_cpu_aviso_c": "60.0",
            "salud.ram_aviso_pct": "85.0",
            "muestreo.intervalo_guardado_s": "15",
            "alarma.o2_retardo_s": "10",
            "alarma.o2_histeresis_pct": "0.5",
            "alarma.discrepancia_pct": "0.5",
            "salud.intervalo_min": "30",
            "salud.disco_aviso_libre_pct": "20.0", "salud.disco_aviso_libre_gb": "2.0",
            "salud.disco_critico_libre_pct": "10.0", "salud.disco_critico_libre_gb": "1.0",
        }
        for clave, defecto in esperado.items():
            self.assertEqual(obtener(clave).defecto, defecto, clave)

    def test_umbrales_de_oxigeno_se_editan_desde_pantalla_y_plataforma(self) -> None:
        for clave in ("alarma.o2_bajo_pct", "alarma.o2_alto_pct"):
            self.assertTrue({"pantalla", "plataforma"} <= obtener(clave).editable_por, clave)

    def test_identidad_y_estado_interno_solo_locales(self) -> None:
        for clave in ("equipo.id", "equipo.nombre", "sistema.apagado_limpio"):
            self.assertEqual(obtener(clave).editable_por, catalogo.SOLO_LOCAL, clave)

    def test_clave_desconocida(self) -> None:
        with self.assertRaises(ErrorConfig):
            obtener("no.existe")


class PruebasNormalizacion(unittest.TestCase):
    def test_enteros(self) -> None:
        c = obtener("muestreo.intervalo_guardado_s")
        self.assertEqual(normalizar(c, " 30 "), "30")
        self.assertEqual(normalizar(c, 30.0), "30")
        for malo in ("abc", "1.5", "", None, "0", "99999"):
            with self.assertRaises(ErrorConfig, msg=repr(malo)):
                normalizar(c, malo)

    def test_reales(self) -> None:
        c = obtener("alarma.o2_bajo_pct")
        self.assertEqual(normalizar(c, "19.5"), "19.5")
        self.assertEqual(normalizar(c, 20), "20.0")
        for malo in ("x", "-1", "101", "nan", "inf"):
            with self.assertRaises(ErrorConfig, msg=malo):
                normalizar(c, malo)

    def test_booleanos(self) -> None:
        c = obtener("sistema.apagado_limpio")
        for verdadero in (1, "1", "true", "SI", "yes", "on"):
            self.assertEqual(normalizar(c, verdadero), "1")
        for falso in (0, "0", "false", "No", "off"):
            self.assertEqual(normalizar(c, falso), "0")
        with self.assertRaises(ErrorConfig):
            normalizar(c, "quizas")

    def test_texto(self) -> None:
        c = obtener("equipo.nombre")
        self.assertEqual(normalizar(c, "  PSA Hospital  "), "PSA Hospital")
        with self.assertRaises(ErrorConfig):
            normalizar(c, "x" * 201)


class PruebasRelaciones(unittest.TestCase):
    def test_bajo_debe_ser_menor_que_alto(self) -> None:
        valores = {"alarma.o2_bajo_pct": "20.0", "alarma.o2_alto_pct": "92.0"}
        catalogo.validar_relaciones("alarma.o2_bajo_pct", "50.0", valores.get)
        with self.assertRaises(ErrorConfig):
            catalogo.validar_relaciones("alarma.o2_bajo_pct", "95.0", valores.get)
        with self.assertRaises(ErrorConfig):
            catalogo.validar_relaciones("alarma.o2_alto_pct", "20.0", valores.get)   # igual: no vale
        catalogo.validar_relaciones("equipo.nombre", "x", valores.get)               # sin relacion


if __name__ == "__main__":
    unittest.main()
