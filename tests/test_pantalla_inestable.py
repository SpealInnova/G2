"""Pruebas de la vigia de comunicacion y de los reinicios de la pantalla Nextion (D-050): lo que hace g2-ui y lo que hace el nucleo."""

from __future__ import annotations

import unittest

from g2.nucleo.salud import (ALM_PANTALLA, MUESTREO_S, REINICIOS_PANTALLA, RETARDO_S, VENTANA_PANTALLA_S)
from g2.nucleo.nucleo import Nucleo
from g2.nucleo.fuentes import FuenteSimulada
from g2.pantalla import protocolo as P
from test_nucleo_salud import BaseSalud, MedidorFalso
from test_pantalla_interfaz import BaseEtapa1, estado
import test_pantalla_interfaz as tui
from test_nucleo_ciclo import C1, C2, BaseCiclo, volts


class PruebasVigia(BaseEtapa1):
    """g2-ui le da a la pantalla una señal de vida cada segundo; la vigia del .HMI avisa sola si deja de llegarle."""

    def test_manda_la_señal_cada_segundo_y_el_fin_del_arranque_una_sola_vez(self) -> None:
        self.arrancar_en_principal()
        self.avanzar(5.0)
        vivos = [o for o in self.enlace.vigia if o == P.ORDEN_VIGIA_VIVO]
        self.assertGreaterEqual(len(vivos), 4)
        self.assertLessEqual(len(vivos), 6)
        self.assertEqual(self.enlace.vigia.count(P.ORDEN_VIGIA_FIN_ARRANQUE), 1)

    def test_no_manda_nada_hasta_que_la_pantalla_carga_su_pagina(self) -> None:
        self.ultimo = estado()
        self.ui.iniciar()
        self.avanzar(3.0)
        self.assertEqual(self.enlace.vigia, [])
        self.cargar("principal")
        self.avanzar(1.5)
        self.assertIn(P.ORDEN_VIGIA_VIVO, self.enlace.vigia)

    def test_la_señal_no_se_cuela_entre_las_ordenes_normales(self) -> None:
        self.arrancar_en_principal()
        self.avanzar(3.0)
        self.assertFalse([o for o in self.enlace.enviadas if o.startswith("principal.va_")])

    def test_si_la_pantalla_se_reinicia_vuelve_a_decir_que_el_arranque_termino(self) -> None:
        self.arrancar_en_principal()
        self.avanzar(2.0)
        self.enlace.vigia.clear()
        self.enlace.encendida()
        self.ui.paso()
        self.cargar("principal")
        self.avanzar(1.5)
        self.assertEqual(self.enlace.vigia.count(P.ORDEN_VIGIA_FIN_ARRANQUE), 1)

    def test_si_la_vigia_perdio_la_señal_la_pi_repinta_todo_y_contesta_en_seguida(self) -> None:
        self.arrancar_en_principal()
        self.avanzar(2.0)
        self.enlace.enviadas.clear()
        self.enlace.vigia.clear()
        self.enlace.vigia_perdida("principal")
        self.ui.paso()
        self.avanzar(0.6)
        self.assertTrue(self.enlace.ordenes_con("principal.o2_1.txt"))          # volvio a pintar lo que la vigia piso
        self.assertTrue(self.enlace.ordenes_con("principal.aviso.txt"))
        self.assertIn(P.ORDEN_VIGIA_VIVO, self.enlace.vigia)

    def test_si_el_tft_no_trae_la_vigia_se_deja_de_mandar_con_un_solo_error(self) -> None:
        self.arrancar_en_principal()
        with self.assertLogs("g2.pantalla", level="ERROR") as registro:
            for _ in range(5):
                self.avanzar(1.1)
                self.enlace.inyectar(bytes([0x1A]))                              # "variable o atributo invalido"
                self.ui.paso()
        self.assertEqual(len([r for r in registro.records if "no tiene las variables de la vigia" in r.getMessage()]), 1)
        cantidad = len(self.enlace.vigia)
        self.avanzar(5.0)
        self.assertEqual(len(self.enlace.vigia), cantidad)

    def test_un_rechazo_de_otra_orden_no_apaga_la_vigia(self) -> None:
        self.arrancar_en_principal()
        self.avanzar(1.1)
        self.tocar("principal", "b_alarmas")                                     # la ultima orden ya no es de la vigia
        for _ in range(4):
            self.enlace.inyectar(bytes([0x1A]))
            self.ui.paso()
        self.assertTrue(self.ui._vigia_activa)

    def test_un_tft_nuevo_reactiva_la_vigia(self) -> None:
        self.arrancar_en_principal()
        self.ui._vigia_activa = False
        self.enlace.encendida()                                                  # la pantalla se reinicio: puede traer un .tft nuevo
        self.ui.paso()
        self.assertTrue(self.ui._vigia_activa)

    def test_con_un_protocolo_incompatible_no_manda_la_señal(self) -> None:
        self.arrancar_en_principal()
        self.ui.protocolo_compatible = False
        self.enlace.vigia.clear()
        self.avanzar(3.0)
        self.assertEqual(self.enlace.vigia, [])


class PruebasAvisoDeReinicios(BaseEtapa1):
    """Cada reinicio de la pantalla (con g2-ui en marcha) se le avisa al nucleo, con los de los ultimos 10 minutos."""

    def reinicios(self) -> list[dict]:
        return [o for o in self.nucleo.recoger_ordenes() if o["tipo"] == "pantalla_reiniciada"]

    def test_arrancar_g2_ui_no_cuenta_como_reinicio_de_la_pantalla(self) -> None:
        self.arrancar_en_principal()
        self.avanzar(3.0)
        self.assertEqual(self.reinicios(), [])

    def test_cada_reinicio_avisa_y_cuenta_los_de_los_ultimos_diez_minutos(self) -> None:
        self.arrancar_en_principal()
        cuentas = []
        for _ in range(3):
            self.enlace.encendida()
            self.ui.paso()
            self.avanzar(1.0)
            cuentas += [o["reinicios_10min"] for o in self.reinicios()]
        self.assertEqual(cuentas, [1, 2, 3])

    def test_la_orden_lleva_a_g2_ui_como_actor(self) -> None:
        self.arrancar_en_principal()
        self.enlace.encendida()
        self.ui.paso()
        (orden,) = self.reinicios()
        self.assertEqual((orden["actor"], orden["origen"]), ("g2-ui", "pantalla"))

    def test_pasados_los_diez_minutos_la_cuenta_vuelve_a_uno(self) -> None:
        self.arrancar_en_principal()
        self.enlace.encendida()
        self.ui.paso()
        self.reinicios()
        self.avanzar(601.0)
        self.enlace.encendida()
        self.ui.paso()
        (orden,) = self.reinicios()
        self.assertEqual(orden["reinicios_10min"], 1)


class PruebasNucleoConReinicios(BaseCiclo):
    def setUp(self) -> None:
        super().setUp()
        self.n = Nucleo(self.a, self.fuente, self.salidas, mono=lambda: self.t[0], version_sw="test", medidor=MedidorFalso())
        self.n.iniciar()

    def reinicio(self, cuantos: int = 1) -> None:
        for i in range(cuantos):
            self.n.procesar_orden({"uuid": f"p{self.t[0]}-{i}", "tipo": "pantalla_reiniciada", "origen": "pantalla",
                                   "actor": "g2-ui", "reinicios_10min": i + 1})

    def eventos(self, codigo: str) -> list:
        return self.a.db.execute("SELECT * FROM evento WHERE codigo = ?", (codigo,)).fetchall()

    def comandos_de_pantalla(self) -> int:
        return self.a.db.execute("SELECT COUNT(*) FROM comando WHERE tipo = 'pantalla_reiniciada'").fetchone()[0]

    def test_un_reinicio_deja_un_evento_y_no_un_comando(self) -> None:
        self.reinicio()
        (e,) = self.eventos("PANT_REINICIADA")
        self.assertEqual((e["origen"], e["repeticiones"]), ("g2-ui", 1))
        self.assertEqual(self.comandos_de_pantalla(), 0)

    def test_una_rafaga_queda_agrupada_en_un_solo_evento(self) -> None:
        self.reinicio(13)
        (e,) = self.eventos("PANT_REINICIADA")
        self.assertEqual(e["repeticiones"], 13)

    def test_con_5_reinicios_en_10_minutos_se_abre_la_alarma_del_sistema_tras_el_retardo(self) -> None:
        self.reinicio(REINICIOS_PANTALLA)
        self.correr(self.n, RETARDO_S + 2 * MUESTREO_S)
        alarma = self.a.alarma_activa(ALM_PANTALLA)
        self.assertIsNotNone(alarma)
        self.assertIn("PANTALLA INESTABLE", " ".join(self.n.salud.etiquetas_activas()))
        self.assertIn(ALM_PANTALLA, self.n.estado_pantalla()["alertas_salud"])
        self.assertIn("PANTALLA INESTABLE", self.n.estado_pantalla()["aviso"])

    def test_con_menos_de_5_no_hay_alarma(self) -> None:
        self.reinicio(REINICIOS_PANTALLA - 1)
        self.correr(self.n, 120)
        self.assertIsNone(self.a.alarma_activa(ALM_PANTALLA))

    def test_la_alarma_se_cierra_cuando_pasan_10_minutos_sin_reinicios(self) -> None:
        self.reinicio(REINICIOS_PANTALLA)
        self.correr(self.n, 60)
        self.assertIsNotNone(self.a.alarma_activa(ALM_PANTALLA))
        self.correr(self.n, VENTANA_PANTALLA_S + 2 * MUESTREO_S)
        self.assertIsNone(self.a.alarma_activa(ALM_PANTALLA))

    def test_la_alarma_no_suena_ni_mueve_los_relevos(self) -> None:
        self.reinicio(REINICIOS_PANTALLA)
        self.correr(self.n, 60)
        e = self.n.estado_pantalla()
        self.assertFalse(e["sonar"])
        self.assertEqual((e["rele_bajo"], e["rele_alto"]), (False, False))

    def test_un_dato_raro_en_la_orden_no_la_rompe(self) -> None:
        for valor in (None, "x", -3, True, 2.5):
            self.n.procesar_orden({"uuid": f"r{valor}", "tipo": "pantalla_reiniciada", "reinicios_10min": valor})
        self.assertTrue(self.eventos("PANT_REINICIADA"))

    def test_sin_observador_de_salud_el_evento_se_registra_igual(self) -> None:
        n = Nucleo(self.a, self.fuente, self.salidas, mono=lambda: self.t[0], version_sw="test")
        n.iniciar()
        n.procesar_orden({"uuid": "sin", "tipo": "pantalla_reiniciada", "reinicios_10min": 1})
        self.assertTrue(self.eventos("PANT_REINICIADA"))


if __name__ == "__main__":
    unittest.main()
