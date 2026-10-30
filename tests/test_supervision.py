"""Pruebas de la vigilancia de g2-core por g2-uplink (D-012): el supervisor, la nota de reinicio y el arranque del nucleo."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from g2 import supervision
from g2.nucleo.fuentes import FuenteSimulada
from g2.nucleo.nucleo import Nucleo
from g2.uplink import supervisor as sup
from g2.uplink.supervisor import SupervisorNucleo
import test_uplink as tu


class Reiniciador:
    def __init__(self, resultado=(True, "")) -> None:
        self.llamadas, self.resultado = 0, resultado

    def __call__(self):
        self.llamadas += 1
        return self.resultado


class PruebasSupervisor(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.carpeta = Path(self._tmp.name)
        self.reinicio = Reiniciador()
        self.reloj = [1_000_000.0]
        self.s = SupervisorNucleo(self.carpeta, reiniciar=self.reinicio, reloj=lambda: self.reloj[0])

    def vigilar(self, ok: bool, t: float) -> bool:
        self.reloj[0] = 1_000_000.0 + t
        return self.s.vigilar(ok, t)

    def test_un_nucleo_que_responde_no_se_toca(self) -> None:
        for t in range(0, 1000, 10):
            self.assertFalse(self.vigilar(True, t))
        self.assertEqual(self.reinicio.llamadas, 0)

    def test_no_reinicia_antes_de_los_dos_minutos_sin_respuesta(self) -> None:
        self.vigilar(False, 0)
        self.assertFalse(self.vigilar(False, sup.CAIDO_MAX_S - 1))
        self.assertEqual(self.reinicio.llamadas, 0)

    def test_reinicia_al_pasar_el_tiempo_y_deja_la_nota(self) -> None:
        self.vigilar(False, 0)
        self.assertTrue(self.vigilar(False, sup.CAIDO_MAX_S))
        self.assertEqual(self.reinicio.llamadas, 1)
        self.assertIn("reinició el núcleo", supervision.tomar_aviso(self.carpeta, lambda: self.reloj[0]))

    def test_una_respuesta_intermedia_reinicia_la_cuenta(self) -> None:
        self.vigilar(False, 0)
        self.vigilar(True, 100)                                   # volvio un momento
        self.vigilar(False, 110)
        self.assertFalse(self.vigilar(False, 110 + sup.CAIDO_MAX_S - 1))
        self.assertEqual(self.reinicio.llamadas, 0)

    def test_espera_entre_intentos_y_se_rinde_tras_el_maximo(self) -> None:
        self.vigilar(False, 0)
        t = sup.CAIDO_MAX_S
        pedidos = []
        while t < 3000:
            if self.vigilar(False, t):
                pedidos.append(t)
            t += 10
        self.assertEqual(len(pedidos), sup.MAX_POR_HORA)
        for antes, despues in zip(pedidos, pedidos[1:]):
            self.assertGreaterEqual(despues - antes, sup.ENTRE_REINICIOS_S)
        self.assertTrue(self.s.agotado)
        self.assertTrue(self.s.estado()["agotado"])

    def test_pasada_la_hora_vuelve_a_intentar(self) -> None:
        self.vigilar(False, 0)
        for t in range(120, 1500, 10):
            self.vigilar(False, t)
        self.assertTrue(self.s.agotado)
        self.assertTrue(self.vigilar(False, 120 + sup.VENTANA_S + 10))

    def test_si_el_reinicio_falla_lo_dice_y_borra_la_nota(self) -> None:
        self.reinicio.resultado = (False, "Access denied")
        self.vigilar(False, 0)
        self.assertFalse(self.vigilar(False, sup.CAIDO_MAX_S))
        self.assertEqual(self.s.estado()["error"], "Access denied")
        self.assertIsNone(supervision.tomar_aviso(self.carpeta, lambda: self.reloj[0]))
        self.assertEqual(self.s.estado()["reinicios_ultima_hora"], 1)      # el intento cuenta: no se insiste sin freno

    def test_estado_cuenta_el_tiempo_sin_respuesta(self) -> None:
        self.vigilar(False, 0)
        self.vigilar(False, 45)
        self.assertEqual(self.s.estado()["sin_respuesta_s"], 45.0)
        self.vigilar(True, 50)
        self.assertEqual(self.s.estado()["sin_respuesta_s"], 0.0)

    def test_reiniciar_unidad_pide_solo_restart_del_nucleo(self) -> None:
        with mock.patch("subprocess.run") as ejecutar:
            ejecutar.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            self.assertEqual(sup.reiniciar_unidad(), (True, ""))
        self.assertEqual(ejecutar.call_args.args[0], ["systemctl", "restart", "g2-core.service"])
        self.assertIn("timeout", ejecutar.call_args.kwargs)

    def test_reiniciar_unidad_sin_systemctl_no_revienta(self) -> None:
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("systemctl")):
            ok, detalle = sup.reiniciar_unidad()
        self.assertFalse(ok)
        self.assertIn("systemctl", detalle)


class PruebasNota(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.carpeta = Path(self._tmp.name)

    def test_se_lee_una_sola_vez(self) -> None:
        supervision.dejar_aviso(self.carpeta, 130.4, lambda: 100.0)
        self.assertIn("130 s", supervision.tomar_aviso(self.carpeta, lambda: 105.0))
        self.assertIsNone(supervision.tomar_aviso(self.carpeta, lambda: 105.0))

    def test_una_nota_vieja_se_ignora_y_se_borra(self) -> None:
        supervision.dejar_aviso(self.carpeta, 130.0, lambda: 100.0)
        self.assertIsNone(supervision.tomar_aviso(self.carpeta, lambda: 100.0 + supervision.EDAD_MAX_AVISO_S + 1))
        self.assertFalse((self.carpeta / supervision.NOMBRE_AVISO).exists())

    def test_una_nota_ilegible_se_ignora(self) -> None:
        (self.carpeta / supervision.NOMBRE_AVISO).write_text("{no es json", encoding="utf-8")
        self.assertIsNone(supervision.tomar_aviso(self.carpeta))
        (self.carpeta / supervision.NOMBRE_AVISO).write_text(json.dumps({"creado_s": "x"}), encoding="utf-8")
        self.assertIsNone(supervision.tomar_aviso(self.carpeta))

    def test_sin_carpeta_o_sin_nota(self) -> None:
        self.assertIsNone(supervision.tomar_aviso(None))
        self.assertIsNone(supervision.tomar_aviso(self.carpeta))


class PruebasArranqueConNota(tu.BaseConBase):
    def arranque(self, **extra):
        n = Nucleo(self.a, FuenteSimulada({"ads1263:0-1": 0.209}), mono=lambda: 0.0)
        n.iniciar(**extra)
        return self.a.db.execute("SELECT razon FROM arranque ORDER BY id DESC LIMIT 1").fetchone()[0]

    def test_con_la_nota_el_arranque_dice_bloqueo_detectado_y_deja_el_evento(self) -> None:
        razon = self.arranque(aviso_reinicio="g2-uplink reinició el núcleo: no respondió durante 130 s")
        self.assertEqual(razon, "SVC_BLOQUEO_DETECTADO")
        evento = self.a.db.execute("SELECT mensaje, origen FROM evento WHERE codigo = 'SVC_BLOQUEO_DETECTADO'").fetchone()
        self.assertIn("130 s", evento["mensaje"])
        self.assertEqual(evento["origen"], "g2-core")

    def test_sin_la_nota_todo_sigue_igual(self) -> None:
        self.a.config_fijar("sistema.apagado_limpio", "1", origen="local", actor="prueba")
        self.assertEqual(self.arranque(), "SYS_ARRANQUE")
        self.assertIsNone(self.a.db.execute("SELECT 1 FROM evento WHERE codigo = 'SVC_BLOQUEO_DETECTADO'").fetchone())


class PruebasServicioConSupervisor(tu.PruebasServicio):
    def setUp(self) -> None:
        super().setUp()
        self.reinicio = Reiniciador()
        self.supervisor = SupervisorNucleo(self.carpeta, reiniciar=self.reinicio)
        self.s.cerrar()
        self.s = self.servicio(supervisor=self.supervisor)

    def avanzar_y_paso(self, segundos: float) -> None:
        self.reloj.avanzar(int(segundos * 1000))
        self.s.paso()

    def test_vigila_aunque_el_envio_este_desactivado(self) -> None:
        self.nucleo.estado = None                                  # g2-core no publica nada
        self.s.paso()
        self.avanzar_y_paso(sup.CAIDO_MAX_S + 1)
        self.assertEqual(self.s.estado(), "desactivada")
        self.assertEqual(self.reinicio.llamadas, 1)

    def test_un_nucleo_con_estado_viejo_tambien_cuenta_como_caido(self) -> None:
        self.nucleo.edad_s = 31.0
        self.s.paso()
        self.avanzar_y_paso(sup.CAIDO_MAX_S + 1)
        self.assertEqual(self.reinicio.llamadas, 1)

    def test_con_el_nucleo_sano_no_pide_nada(self) -> None:
        self.s.paso()
        self.avanzar_y_paso(600)
        self.assertEqual(self.reinicio.llamadas, 0)

    def test_publica_el_estado_de_la_vigilancia(self) -> None:
        self.s.paso()
        publicado = json.loads((self.carpeta / "uplink.json").read_text(encoding="utf-8"))
        self.assertEqual(publicado["nucleo"]["reinicios_ultima_hora"], 0)
        self.assertFalse(publicado["nucleo"]["agotado"])

    def test_sin_supervisor_no_hay_vigilancia(self) -> None:
        self.s.cerrar()
        self.s = self.servicio()
        self.nucleo.estado = None
        self.s.paso()
        self.avanzar_y_paso(1000)
        publicado = json.loads((self.carpeta / "uplink.json").read_text(encoding="utf-8"))
        self.assertNotIn("nucleo", publicado)


if __name__ == "__main__":
    unittest.main()
