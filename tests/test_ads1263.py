"""Pruebas del controlador del ADS1263 contra su emulador (sin hardware)."""

from __future__ import annotations

import unittest

from g2.hardware import ads1263 as A
from g2.hardware.ads1263_emulado import Ads1263Emulado, RelojFalso


def montar(fuente=None, config: A.ConfigAdc | None = None, **opciones):
    """Controlador + emulador con reloj simulado compartido."""
    reloj = RelojFalso()
    emulado = Ads1263Emulado(reloj, fuente, **opciones)
    adc = A.Ads1263(emulado, config, ahora=reloj.ahora, esperar=reloj.esperar)
    return adc, emulado, reloj


def dos_sensores(p: int, n: int, t: float) -> float:
    """Sensor 1 (AIN0-AIN1) a 20.9 % de O2 = 0.209 V; sensor 2 (AIN2-AIN3) a 100 % = 1.0 V."""
    return {(0, 1): 0.209, (2, 3): 1.0}.get((p, n), 0.0)


class PruebasConversion(unittest.TestCase):
    def test_codigos_conocidos_de_la_tabla_9_19(self) -> None:
        self.assertAlmostEqual(A.codigo_a_tension(0, 1), 0.0)
        self.assertAlmostEqual(A.codigo_a_tension(2 ** 31 - 1, 1), 2.5, places=6)
        self.assertAlmostEqual(A.codigo_a_tension(-2 ** 31, 1), -2.5, places=6)
        self.assertAlmostEqual(A.codigo_a_tension(2 ** 30, 1), 1.25, places=6)
        self.assertAlmostEqual(A.codigo_a_tension(2 ** 30, 2), 0.625, places=6)   # ganancia 2

    def test_suma_de_control_del_ejemplo_de_la_hoja_de_datos(self) -> None:
        self.assertEqual(A.checksum(bytes([0x12, 0x34, 0x56, 0x78])), 0xAF)       # sec. 9.4.7.3.3.1


class PruebasConfiguracion(unittest.TestCase):
    def test_valores_de_registros_por_omision(self) -> None:
        # PGA en derivacion, ganancia 1, FIR, 20 SPS, sin chopper.
        self.assertEqual(A.ConfigAdc().registros(), bytes([0x00, 0x80, 0x84]))

    def test_chopper_y_ganancia_cambian_los_bits_correctos(self) -> None:
        cfg = A.ConfigAdc(ganancia=4, pga_derivacion=False, filtro="sinc4", sps=100, chopper=True)
        mode0, mode1, mode2 = cfg.registros()
        self.assertEqual(mode0, 0x10)             # CHOP = 01
        self.assertEqual(mode1, 0x60)             # sinc4 = 011 en bits 7..5
        self.assertEqual(mode2, (2 << 4) | 7)     # ganancia 4 = 010; 100 SPS = 0111

    def test_fir_solo_admite_velocidades_bajas(self) -> None:
        with self.assertRaises(ValueError):
            A.ConfigAdc(filtro="fir", sps=100).validar()
        with self.assertRaises(ValueError):
            A.ConfigAdc(ganancia=3).validar()

    def test_iniciar_deja_los_registros_como_se_configuraron(self) -> None:
        adc, chip, _ = montar()
        adc.iniciar()
        self.assertEqual([chip.regs[r] for r in (A.REG_MODE0, A.REG_MODE1, A.REG_MODE2)],
                         [0x00, 0x80, 0x84])
        self.assertTrue(chip.corriendo)
        self.assertEqual(chip.regs[A.REG_POWER] & A.POWER_RESET, 0)    # indicador de reinicio borrado

    def test_chip_que_no_es_ads1263_se_rechaza(self) -> None:
        adc, _, _ = montar(id_chip=0x03)          # dispositivo 0 = ADS1262
        with self.assertRaises(A.ErrorChipNoEsperado):
            adc.iniciar()


class PruebasLectura(unittest.TestCase):
    def test_lee_la_tension_del_canal(self) -> None:
        adc, _, _ = montar(dos_sensores)
        adc.iniciar()
        lectura = adc.leer_diferencial(0, 1)
        self.assertAlmostEqual(lectura.tension_v, 0.209, places=6)
        self.assertEqual(lectura.canal, (0, 1))
        self.assertEqual(lectura.alarmas, [])

    def test_cambiar_de_canal_devuelve_el_canal_nuevo_y_no_un_dato_viejo(self) -> None:
        adc, _, _ = montar(dos_sensores)
        adc.iniciar()
        secuencia = [adc.leer_diferencial(*par).tension_v
                     for par in ((0, 1), (2, 3), (0, 1), (2, 3), (2, 3))]
        for obtenido, esperado in zip(secuencia, (0.209, 1.0, 0.209, 1.0, 1.0)):
            self.assertAlmostEqual(obtenido, esperado, places=6)

    def test_tension_negativa(self) -> None:
        adc, _, _ = montar(lambda p, n, t: -0.05)
        adc.iniciar()
        self.assertAlmostEqual(adc.leer_diferencial(0, 1).tension_v, -0.05, places=6)

    def test_se_satura_en_el_rango_con_referencia_de_2v5(self) -> None:
        adc, _, _ = montar(lambda p, n, t: 3.0)
        adc.iniciar()
        self.assertAlmostEqual(adc.leer_diferencial(0, 1).tension_v, 2.5, places=6)

    def test_la_ganancia_cambia_la_escala(self) -> None:
        adc, _, _ = montar(lambda p, n, t: 0.2, A.ConfigAdc(ganancia=2, pga_derivacion=False))
        adc.iniciar()
        self.assertAlmostEqual(adc.leer_diferencial(0, 1).tension_v, 0.2, places=6)

    def test_una_lectura_tarda_lo_que_dura_una_conversion(self) -> None:
        adc, _, reloj = montar(dos_sensores)          # FIR a 20 SPS -> 50 ms
        adc.iniciar()
        adc.leer_diferencial(0, 1)
        antes = reloj.ahora()
        adc.leer_diferencial(2, 3)                    # cambia de canal: conversion nueva
        self.assertTrue(0.045 <= reloj.ahora() - antes <= 0.07, reloj.ahora() - antes)

    def test_el_ruido_del_emulador_se_refleja_en_la_dispersion(self) -> None:
        adc, _, _ = montar(lambda p, n, t: 0.5, ruido_uv=10.0)
        adc.iniciar()
        valores = [adc.leer_diferencial(0, 1).tension_v for _ in range(40)]
        self.assertGreater(max(valores) - min(valores), 1e-6)
        self.assertLess(max(valores) - min(valores), 1e-3)


class PruebasReferencia(unittest.TestCase):
    def test_referencia_avdd_amplia_el_rango_a_5_voltios(self) -> None:
        adc, chip, _ = montar(lambda p, n, t: 3.2, A.ConfigAdc(referencia="avdd"))
        adc.iniciar()
        self.assertEqual(chip.regs[A.REG_REFMUX], 0x24)
        self.assertAlmostEqual(adc.leer_diferencial(0, 10).tension_v, 3.2, places=6)

    def test_con_referencia_avdd_se_satura_en_5_voltios(self) -> None:
        adc, _, _ = montar(lambda p, n, t: 7.0, A.ConfigAdc(referencia="avdd"))
        adc.iniciar()
        self.assertAlmostEqual(adc.leer_diferencial(0, 10).tension_v, 5.0, places=6)

    def test_referencia_interna_por_omision(self) -> None:
        adc, chip, _ = montar()
        adc.iniciar()
        self.assertEqual(chip.regs[A.REG_REFMUX], 0x00)
        with self.assertRaises(ValueError):
            A.ConfigAdc(referencia="otra").validar()


class PruebasAlarmas(unittest.TestCase):
    def test_con_pga_en_derivacion_se_ignoran_las_alarmas_del_pga(self) -> None:
        lectura = A.Lectura(0.1, 0, A.STATUS_PGA_ALTO | A.STATUS_ADC1_NUEVO, (0, 1), pga_activo=False)
        self.assertEqual(lectura.alarmas, [])

    def test_con_pga_activo_se_informan(self) -> None:
        lectura = A.Lectura(0.1, 0, A.STATUS_PGA_ALTO | A.STATUS_REF_BAJA, (0, 1), pga_activo=True)
        self.assertEqual(sorted(lectura.alarmas), ["pga_salida_alta", "referencia_baja"])

    def test_la_referencia_baja_se_informa_siempre(self) -> None:
        lectura = A.Lectura(0.1, 0, A.STATUS_REF_BAJA, (0, 1), pga_activo=False)
        self.assertEqual(lectura.alarmas, ["referencia_baja"])


class PruebasFallas(unittest.TestCase):
    def test_sin_datos_nuevos_vence_el_tiempo_maximo_sin_colgarse(self) -> None:
        adc, chip, reloj = montar(dos_sensores)
        adc.iniciar()
        chip.congelado = True
        antes = reloj.ahora()
        with self.assertRaises(A.ErrorTiempoAgotado):
            adc.leer_diferencial(0, 1, tiempo_max_s=0.5)
        self.assertLess(reloj.ahora() - antes, 0.6)

    def test_suma_de_control_incorrecta(self) -> None:
        adc, chip, _ = montar(dos_sensores)
        adc.iniciar()
        chip.corromper_suma = True
        with self.assertRaises(A.ErrorChecksum):
            adc.leer_diferencial(0, 1)

    def test_reinicio_del_chip_se_detecta_y_se_recupera(self) -> None:
        adc, chip, _ = montar(dos_sensores)
        adc.iniciar()
        adc.leer_diferencial(0, 1)
        chip.simular_reinicio()
        with self.assertRaises(A.ErrorChipReiniciado):
            adc.leer_diferencial(0, 1)
        adc.iniciar()                                  # reconfigura
        self.assertAlmostEqual(adc.leer_diferencial(0, 1).tension_v, 0.209, places=6)


if __name__ == "__main__":
    unittest.main()
