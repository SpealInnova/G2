"""Pruebas del motor de alarmas por sensor (g2.nucleo.alarmas): retardo, histeresis, acuse, sonido,
relevos, sensor invalido, discrepancia y retoma tras un reinicio. Usa una base real temporal."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from g2.almacenamiento.almacen import Almacen
from g2.nucleo.alarmas import (ALM_ALTO, ALM_BAJO, ALM_DISCREPANCIA, ALM_INVALIDO, MotorAlarmas,
                               Umbrales)
from g2.tiempo import RelojPrueba

# 20.0 / 92.0 %, retardo 10 s, histeresis 0.5, acuse 120 s. La discrepancia entre sensores se deja
# muy ancha para que las pruebas de cada alarma no abran tambien la del sistema (cuando un sensor
# marca 15 % y el otro 20.9 % es correcto que ademas se abra "sensores discrepantes").
U = Umbrales(discrepancia_pct=100.0)
UD = Umbrales()                     # con el limite real (0.5 %), para las pruebas de discrepancia


class BaseMotor(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.a = Almacen.abrir(Path(self._tmp.name) / "g2.db", RelojPrueba())
        self.a.registrar_arranque(version_sw="test", so_boot_id="so-1")
        self.s1 = self.a.registrar_sensor(canal="ads1263:0-1", nombre="Sensor 1",
                                          modelo="Paracube Micro", mv_por_pct=10.0)
        self.s2 = self.a.registrar_sensor(canal="ads1263:2-3", nombre="Sensor 2",
                                          modelo="Paracube Micro", mv_por_pct=10.0)
        self.m = MotorAlarmas(self.a, {self.s1: "Sensor 1", self.s2: "Sensor 2"})

    def tearDown(self) -> None:
        self.a.cerrar()
        self._tmp.cleanup()

    def ev(self, v1, v2, t, umbrales: Umbrales = U):
        return self.m.evaluar({self.s1: v1, self.s2: v2}, umbrales, t)

    def alarma(self, codigo, sensor_id):
        return self.a.db.execute("SELECT * FROM alarma WHERE codigo = ? AND sensor_id IS ? "
                                 "ORDER BY id DESC LIMIT 1", (codigo, sensor_id)).fetchone()

    def n_alarmas(self) -> int:
        return self.a.db.execute("SELECT COUNT(*) FROM alarma").fetchone()[0]


class PruebasRetardoEHisteresis(BaseMotor):
    def test_valores_normales_no_abren_alarmas(self) -> None:
        for t in range(0, 60, 1):
            self.ev(20.9, 20.9, t)
        self.assertEqual(self.n_alarmas(), 0)
        self.assertFalse(self.m.rele_bajo() or self.m.rele_alto())
        self.assertEqual(self.m.texto_aviso(), "Sin alarmas")

    def test_la_alarma_baja_espera_el_retardo(self) -> None:
        self.ev(15.0, 20.9, 0)
        self.ev(15.0, 20.9, 9.9)
        self.assertEqual(self.n_alarmas(), 0)
        self.assertFalse(self.m.rele_bajo())
        cambios = self.ev(15.0, 20.9, 10.0)
        self.assertEqual(len(cambios), 1)
        fila = self.alarma(ALM_BAJO, self.s1)
        self.assertEqual((fila["estado"], fila["umbral"], fila["valor_disparo"]), ("activa", 20.0, 15.0))
        self.assertTrue(self.m.rele_bajo())
        self.assertFalse(self.m.rele_alto())

    def test_si_la_condicion_se_pierde_antes_del_retardo_empieza_de_cero(self) -> None:
        self.ev(15.0, 20.9, 0)
        self.ev(25.0, 20.9, 5)                    # se normaliza a los 5 s
        self.ev(15.0, 20.9, 6)                    # vuelve: el conteo empieza en 6
        self.ev(15.0, 20.9, 15)
        self.assertEqual(self.n_alarmas(), 0)
        self.ev(15.0, 20.9, 16)
        self.assertEqual(self.n_alarmas(), 1)

    def test_la_histeresis_mantiene_la_alarma_baja_hasta_superar_minimo_mas_margen(self) -> None:
        self.ev(15.0, 20.9, 0)
        self.ev(15.0, 20.9, 10)
        self.ev(20.2, 20.9, 11)                   # ya supera el minimo (20.0) pero no 20.5
        self.assertEqual(self.alarma(ALM_BAJO, self.s1)["estado"], "activa")
        self.assertTrue(self.m.rele_bajo())
        self.ev(20.5, 20.9, 12)
        fila = self.alarma(ALM_BAJO, self.s1)
        self.assertEqual(fila["estado"], "cerrada")
        self.assertIsNotNone(fila["fin_ms"])
        self.assertFalse(self.m.rele_bajo())

    def test_alarma_alta_con_histeresis_simetrica(self) -> None:
        self.ev(20.9, 95.0, 0)
        self.ev(20.9, 95.0, 10)
        self.assertTrue(self.m.rele_alto())
        self.assertFalse(self.m.rele_bajo())
        self.ev(20.9, 91.8, 11)                   # bajo del maximo (92) pero no de 91.5
        self.assertTrue(self.m.rele_alto())
        self.ev(20.9, 91.5, 12)
        self.assertFalse(self.m.rele_alto())
        self.assertEqual(self.alarma(ALM_ALTO, self.s2)["estado"], "cerrada")

    def test_el_valor_extremo_se_guarda_como_pico(self) -> None:
        for t, v in ((0, 15.0), (10, 15.0), (11, 12.0), (12, 14.0)):
            self.ev(v, 20.9, t)
        self.assertEqual(self.alarma(ALM_BAJO, self.s1)["valor_pico"], 12.0)
        for t, v in ((0, 95.0), (10, 95.0), (11, 99.0), (12, 96.0)):
            self.ev(20.9, v, 20 + t)
        self.assertEqual(self.alarma(ALM_ALTO, self.s2)["valor_pico"], 99.0)

    def test_retardo_cero_activa_de_inmediato(self) -> None:
        self.ev(15.0, 20.9, 0, Umbrales(retardo_s=0))
        self.assertEqual(self.alarma(ALM_BAJO, self.s1)["estado"], "activa")

    def test_valor_justo_en_el_limite_no_dispara(self) -> None:
        for t in range(0, 30):
            self.ev(20.0, 92.0, t)               # ni menor que el minimo ni mayor que el maximo
        self.assertEqual(self.n_alarmas(), 0)


class PruebasPorSensor(BaseMotor):
    def abrir_dos(self) -> None:
        self.ev(15.0, 95.0, 0)
        self.ev(15.0, 95.0, 10)

    def test_cada_sensor_tiene_su_propia_alarma(self) -> None:
        self.ev(15.0, 20.9, 0)
        self.ev(15.0, 20.9, 10)
        self.assertEqual(self.m.estado_sensor(self.s1), ("BAJA", False))
        self.assertEqual(self.m.estado_sensor(self.s2), ("NORMAL", False))
        self.assertEqual(self.m.texto_aviso(), "S1 BAJO 15.0 %")
        self.assertIsNone(self.alarma(ALM_BAJO, self.s2))

    def test_dos_alarmas_a_la_vez_van_a_su_relevo_y_al_letrero(self) -> None:
        self.abrir_dos()
        self.assertEqual(self.m.estado_sensor(self.s1)[0], "BAJA")
        self.assertEqual(self.m.estado_sensor(self.s2)[0], "ALTA")
        self.assertTrue(self.m.rele_bajo() and self.m.rele_alto())
        self.assertEqual(self.m.texto_aviso(), "S1 BAJO 15.0 %  S2 ALTO 95.0 %")

    def test_el_relevo_bajo_sigue_si_cualquiera_de_los_sensores_esta_en_bajo(self) -> None:
        self.ev(15.0, 15.0, 0)
        self.ev(15.0, 15.0, 10)
        self.ev(25.0, 15.0, 11)                   # el sensor 1 se recupera, el 2 sigue
        self.assertTrue(self.m.rele_bajo())
        self.ev(25.0, 25.0, 12)
        self.assertFalse(self.m.rele_bajo())

    def test_un_sensor_deshabilitado_cierra_sus_alarmas(self) -> None:
        self.ev(15.0, 20.9, 0)
        self.ev(15.0, 20.9, 10)
        self.m.evaluar({self.s2: 20.9}, U, 11)    # el sensor 1 ya no se evalua
        self.assertEqual(self.alarma(ALM_BAJO, self.s1)["estado"], "cerrada")
        self.assertFalse(self.m.rele_bajo())

    def test_letrero_no_pasa_de_60_letras(self) -> None:
        ids = [self.s1, self.s2] + [
            self.a.registrar_sensor(canal=f"ads1263:{2 * i}-{2 * i + 1}", nombre=f"Sensor {i + 1}",
                                    modelo="Paracube Micro", mv_por_pct=10.0) for i in range(2, 8)]
        self.m.nombres.update({i: f"Sensor {i}" for i in ids})
        valores = {i: 5.0 for i in ids}
        self.m.evaluar(valores, U, 0)
        self.m.evaluar(valores, U, 10)
        self.assertLessEqual(len(self.m.texto_aviso()), 60)


class PruebasAcuseYSonido(BaseMotor):
    def abrir_bajo_en_s1(self) -> None:
        self.ev(15.0, 20.9, 0)
        self.ev(15.0, 20.9, 10)

    def test_una_alarma_nueva_suena_y_parpadea(self) -> None:
        self.abrir_bajo_en_s1()
        self.assertTrue(self.m.debe_sonar(10))
        self.assertTrue(self.m.hay_sin_acusar())

    def test_acusar_silencia_el_sonido_pero_no_apaga_el_relevo_ni_cierra_la_alarma(self) -> None:
        self.abrir_bajo_en_s1()
        self.assertEqual(self.m.acusar("pantalla", 20, U), 1)
        self.assertFalse(self.m.debe_sonar(21))
        self.assertFalse(self.m.hay_sin_acusar())
        self.assertTrue(self.m.rele_bajo())                      # D-031: los relevos no dependen del acuse
        fila = self.alarma(ALM_BAJO, self.s1)
        self.assertEqual((fila["estado"], fila["acuse_actor"]), ("acusada", "pantalla"))
        self.assertEqual(self.m.estado_sensor(self.s1), ("BAJA", True))

    def test_el_sonido_vuelve_a_los_120_segundos_si_la_alarma_sigue(self) -> None:
        self.abrir_bajo_en_s1()
        self.m.acusar("pantalla", 20, U)
        self.assertFalse(self.m.debe_sonar(139.9))
        self.assertTrue(self.m.debe_sonar(140.0))

    def test_acusar_de_nuevo_reinicia_los_dos_minutos(self) -> None:
        self.abrir_bajo_en_s1()
        self.m.acusar("pantalla", 20, U)
        self.assertEqual(self.m.acusar("pantalla", 100, U), 0)   # nada nuevo que acusar
        self.assertFalse(self.m.debe_sonar(219.0))
        self.assertTrue(self.m.debe_sonar(220.0))

    def test_una_alarma_nueva_del_otro_sensor_suena_al_instante_aunque_haya_silencio(self) -> None:
        self.abrir_bajo_en_s1()
        self.m.acusar("pantalla", 20, U)
        self.ev(15.0, 95.0, 30)
        self.ev(15.0, 95.0, 40)                                  # se abre la alta del sensor 2
        self.assertTrue(self.m.debe_sonar(40))
        self.assertEqual(self.m.estado_sensor(self.s1), ("BAJA", True))
        self.assertEqual(self.m.estado_sensor(self.s2), ("ALTA", False))
        self.assertEqual(self.m.acusar("pantalla", 41, U), 1)    # un solo toque acusa ambos sensores
        self.assertFalse(self.m.debe_sonar(42))

    def test_sin_alarmas_no_suena_ni_acusar_hace_nada(self) -> None:
        self.ev(20.9, 20.9, 0)
        self.assertFalse(self.m.debe_sonar(0))
        self.assertEqual(self.m.acusar("pantalla", 1, U), 0)
        # un acuse sin alarmas no debe dejar silencio guardado para la proxima alarma
        self.ev(15.0, 20.9, 2)
        self.ev(15.0, 20.9, 12)
        self.assertTrue(self.m.debe_sonar(12))

    def test_al_cerrarse_la_alarma_deja_de_sonar(self) -> None:
        self.abrir_bajo_en_s1()
        self.ev(25.0, 20.9, 11)
        self.assertFalse(self.m.debe_sonar(11))


class PruebasSensorInvalidoYDiscrepancia(BaseMotor):
    def test_sin_señal_se_muestra_al_instante_y_alarma_tras_el_retardo(self) -> None:
        self.ev(None, 20.9, 0)
        self.assertEqual(self.m.estado_sensor(self.s1), ("SIN SEÑAL", False))
        self.assertIsNone(self.alarma(ALM_INVALIDO, self.s1))
        self.ev(None, 20.9, 10)
        self.assertEqual(self.alarma(ALM_INVALIDO, self.s1)["estado"], "activa")
        self.assertEqual(self.m.texto_aviso(), "S1 SIN SEÑAL")
        self.assertFalse(self.m.rele_bajo() or self.m.rele_alto())   # los relevos son solo de oxigeno
        codigos = [f["codigo"] for f in self.a.db.execute("SELECT codigo FROM evento")]
        self.assertIn("SEN_FALLA", codigos)

    def test_al_volver_la_señal_se_cierra_y_se_registra_la_recuperacion(self) -> None:
        self.ev(None, 20.9, 0)
        self.ev(None, 20.9, 10)
        self.ev(20.9, 20.9, 11)
        self.assertEqual(self.alarma(ALM_INVALIDO, self.s1)["estado"], "cerrada")
        codigos = [f["codigo"] for f in self.a.db.execute("SELECT codigo FROM evento")]
        self.assertIn("SEN_RECUPERADO", codigos)
        self.assertEqual(self.m.estado_sensor(self.s1), ("NORMAL", False))

    def test_sin_dato_no_se_evaluan_las_alarmas_de_oxigeno(self) -> None:
        self.ev(15.0, 20.9, 0)
        self.ev(None, 20.9, 5)                    # se pierde la señal mientras el retardo corria
        self.ev(15.0, 20.9, 10)                   # el conteo se descarto: no abre todavia
        self.assertIsNone(self.alarma(ALM_BAJO, self.s1))

    def test_discrepancia_entre_sensores_es_una_alarma_del_sistema(self) -> None:
        self.ev(20.9, 22.0, 0, UD)
        self.ev(20.9, 22.0, 10, UD)
        fila = self.alarma(ALM_DISCREPANCIA, None)
        self.assertEqual(fila["estado"], "activa")
        self.assertEqual(self.m.texto_aviso(), "SENSORES DIFIEREN")
        self.assertFalse(self.m.rele_bajo() or self.m.rele_alto())
        self.ev(20.9, 21.0, 11, UD)               # la diferencia baja a 0.1 (< la mitad del limite)
        self.assertEqual(self.alarma(ALM_DISCREPANCIA, None)["estado"], "cerrada")

    def test_con_un_solo_sensor_no_hay_discrepancia(self) -> None:
        for t in range(0, 30):
            self.m.evaluar({self.s1: 20.9}, UD, t)
        self.assertIsNone(self.alarma(ALM_DISCREPANCIA, None))


class PruebasRetomaTrasReinicio(BaseMotor):
    def test_las_alarmas_abiertas_se_retoman_sin_duplicarse(self) -> None:
        self.ev(15.0, 95.0, 0)
        self.ev(15.0, 95.0, 10)
        self.m.acusar("pantalla", 20, U)
        n_antes = self.n_alarmas()
        nuevo = MotorAlarmas(self.a, {self.s1: "Sensor 1", self.s2: "Sensor 2"})
        self.assertEqual(nuevo.recuperar(100.0), 2)
        self.assertTrue(nuevo.rele_bajo() and nuevo.rele_alto())
        self.assertEqual(nuevo.estado_sensor(self.s1), ("BAJA", True))      # se muestra desde el primer instante
        nuevo.evaluar({self.s1: 15.0, self.s2: 95.0}, U, 100.0)
        nuevo.evaluar({self.s1: 15.0, self.s2: 95.0}, U, 110.0)
        self.assertEqual(self.n_alarmas(), n_antes)                          # no abrio otras
        self.assertEqual(nuevo.estado_sensor(self.s1), ("BAJA", True))      # sigue acusada
        self.assertTrue(nuevo.debe_sonar(110.0))                             # el silencio no se conserva

    def test_si_la_condicion_termino_durante_el_reinicio_la_alarma_se_cierra(self) -> None:
        self.ev(15.0, 20.9, 0)
        self.ev(15.0, 20.9, 10)
        nuevo = MotorAlarmas(self.a, {self.s1: "Sensor 1", self.s2: "Sensor 2"})
        nuevo.recuperar(100.0)
        nuevo.evaluar({self.s1: 22.0, self.s2: 20.9}, U, 100.0)
        self.assertEqual(self.alarma(ALM_BAJO, self.s1)["estado"], "cerrada")
        self.assertFalse(nuevo.rele_bajo())


if __name__ == "__main__":
    unittest.main()
