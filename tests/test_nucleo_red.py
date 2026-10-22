"""Pruebas del servicio de red y de las ordenes de red del nucleo (D-040). Nada toca la red real."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import unittest
from pathlib import Path

from g2 import ipc
from g2.almacenamiento.almacen import Almacen
from g2.nucleo.fuentes import FuenteSimulada
from g2.nucleo.nucleo import Nucleo
from g2.nucleo.servicio_red import ServicioRed
from g2.red.gestor import EstadoRed, RedVisible, ResultadoRed
from g2.tiempo import RelojPrueba

CLAVE = "Cl@ve-MUY-secreta/2026"                     # contrasena de prueba


class GestorFalso:
    """Sustituye al gestor real: devuelve lo que se le pida y recuerda con que se le llamo."""

    def __init__(self) -> None:
        self.resultado = ResultadoRed(True, "Conectado a «Hospital»")
        self.llamadas: list[tuple] = []
        self.busquedas = 0
        self.fallar = False

    def configurar(self, ssid, contrasena="", oculta=False):
        self.llamadas.append((ssid, contrasena, oculta))
        if self.fallar:
            raise RuntimeError("fallo inesperado")
        return self.resultado

    def estado(self, comprobar_internet=True):
        return EstadoRed(tipo="wifi", ssid="RedEjemplo", ip="192.168.10.20", senal=99, internet=True,
                         zerotier_ip="10.99.99.10", interfaz_wifi="wlan0")

    def escanear(self, buscar_de_nuevo=True):
        if buscar_de_nuevo:
            self.busquedas += 1
        return [RedVisible("RedEjemplo", 99, "WPA2"), RedVisible("Hospital", 70, "WPA2")]


class PruebasServicioRed(unittest.TestCase):
    def setUp(self) -> None:
        self.t = [0.0]
        self.gestor = GestorFalso()
        self.s = ServicioRed(self.gestor, intervalo_s=10, intervalo_redes_s=30, mono=lambda: self.t[0])

    def test_la_primera_vuelta_publica_el_estado_y_las_redes_cercanas(self) -> None:
        self.s.ciclo()
        e = self.s.estado()
        self.assertEqual((e["red"]["tipo"], e["red"]["ssid"], e["red"]["internet"]), ("wifi", "RedEjemplo", True))
        self.assertEqual([r["ssid"] for r in e["redes"]], ["RedEjemplo", "Hospital"])
        self.assertEqual(e["cambio"], {"en_curso": None, "ultimo": None})

    def test_refresca_cada_10_segundos_no_antes(self) -> None:
        self.s.ciclo()
        self.gestor.estado = lambda comprobar_internet=True: EstadoRed(tipo="ethernet")
        self.t[0] = 5
        self.s.ciclo()
        self.assertEqual(self.s.estado()["red"]["tipo"], "wifi")
        self.t[0] = 10
        self.s.ciclo()
        self.assertEqual(self.s.estado()["red"]["tipo"], "ethernet")

    def test_un_cambio_de_red_se_ejecuta_y_deja_su_resultado_una_sola_vez(self) -> None:
        self.s.ciclo()
        self.assertTrue(self.s.solicitar_cambio("Hospital", CLAVE))
        self.s.ciclo()
        self.assertEqual(self.gestor.llamadas, [("Hospital", CLAVE, False)])
        ssid, resultado = self.s.resultado_pendiente()
        self.assertEqual((ssid, resultado.ok), ("Hospital", True))
        self.assertIsNone(self.s.resultado_pendiente())                      # ya se entrego
        self.assertEqual(self.s.estado()["cambio"]["ultimo"]["mensaje"], "Conectado a «Hospital»")
        self.assertIsNone(self.s.estado()["cambio"]["en_curso"])

    def test_solo_se_hace_un_cambio_a_la_vez(self) -> None:
        self.assertTrue(self.s.solicitar_cambio("A", "12345678"))
        self.assertFalse(self.s.solicitar_cambio("B", "12345678"))
        self.s.ciclo()
        self.assertTrue(self.s.solicitar_cambio("B", "12345678"))             # ya termino el primero

    def test_un_fallo_inesperado_del_gestor_no_tumba_el_servicio(self) -> None:
        self.gestor.fallar = True
        with self.assertLogs("g2.red", level="ERROR"):
            self.s.solicitar_cambio("Hospital", CLAVE)
            self.s.ciclo()
        ssid, resultado = self.s.resultado_pendiente()
        self.assertFalse(resultado.ok)
        self.s.ciclo()                                                       # sigue funcionando

    def test_la_contrasena_no_se_publica_en_el_estado(self) -> None:
        self.s.solicitar_cambio("Hospital", CLAVE)
        self.s.ciclo()
        self.assertNotIn(CLAVE, json.dumps(self.s.estado()))

    def test_buscar_redes_hace_un_escaneo_nuevo(self) -> None:
        self.s.ciclo()
        antes = self.gestor.busquedas
        self.s.solicitar_busqueda()
        self.s.ciclo()
        self.assertEqual(self.gestor.busquedas, antes + 1)

    def test_el_hilo_real_arranca_y_se_detiene(self) -> None:
        self.s.iniciar()
        self.s.detener()
        self.assertIsNotNone(self.s.estado()["red"])


class BaseNucleoRed(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.a = Almacen.abrir(self.dir / "g2.db", RelojPrueba())
        self.a.registrar_sensor(canal="ads1263:0-1", nombre="Sensor 1", modelo="P", mv_por_pct=10.0)
        self.t = [0.0]
        self.gestor = GestorFalso()
        self.red = ServicioRed(self.gestor, mono=lambda: self.t[0])
        self.n = Nucleo(self.a, FuenteSimulada({"ads1263:0-1": 0.209}), mono=lambda: self.t[0], servicio_red=self.red)
        self.n.iniciar()

    def tearDown(self) -> None:
        self.a.cerrar()
        self._tmp.cleanup()

    def orden(self, uuid: str, tipo: str, **datos) -> None:
        self.n.procesar_orden({"uuid": uuid, "tipo": tipo, "origen": "pantalla", "actor": "pantalla", **datos})

    def comandos(self):
        return self.a.db.execute("SELECT tipo, estado, parametros_json, resultado_json FROM comando ORDER BY id").fetchall()

    def eventos(self, codigo: str):
        return self.a.db.execute("SELECT * FROM evento WHERE codigo = ?", (codigo,)).fetchall()

    def terminar_el_cambio(self) -> None:
        self.red.ciclo()                       # el hilo ejecuta el cambio
        self.t[0] += 0.5
        self.n.paso()                          # el nucleo recoge el resultado y lo escribe


class PruebasOrdenesDeRed(BaseNucleoRed):
    def test_cambiar_de_red_registra_el_comando_y_los_eventos(self) -> None:
        self.orden("r1", "red_configurar", ssid="Hospital", contrasena=CLAVE, oculta=False)
        (c,) = self.comandos()
        self.assertEqual(c["estado"], "recibido")                              # sigue en curso
        self.assertEqual(len(self.eventos("RED_CAMBIO_SOLICITADO")), 1)
        self.terminar_el_cambio()
        (c,) = self.comandos()
        self.assertEqual(c["estado"], "ok")
        self.assertIn("Conectado a", c["resultado_json"])
        self.assertEqual(len(self.eventos("RED_CAMBIO_OK")), 1)
        self.assertEqual(self.gestor.llamadas, [("Hospital", CLAVE, False)])

    def test_un_cambio_fallido_queda_como_error_con_su_motivo(self) -> None:
        self.gestor.resultado = ResultadoRed(False, "Contraseña incorrecta", revertida=True, motivo="contrasena")
        self.orden("r1", "red_configurar", ssid="Hospital", contrasena="clavemalaaa")
        self.terminar_el_cambio()
        (c,) = self.comandos()
        self.assertEqual(c["estado"], "error")
        (e,) = self.eventos("RED_CAMBIO_FALLIDO")
        self.assertEqual(json.loads(e["datos_json"])["motivo"], "contrasena")
        self.assertTrue(json.loads(e["datos_json"])["revertida"])
        self.assertEqual(self.eventos("RED_CAMBIO_OK"), [])

    def test_el_estado_publicado_lleva_la_red_y_el_resultado(self) -> None:
        self.orden("r1", "red_configurar", ssid="Hospital", contrasena=CLAVE)
        self.assertEqual(self.n.estado_pantalla()["red"]["cambio"]["en_curso"], "Hospital")
        self.terminar_el_cambio()
        red = self.n.estado_pantalla()["red"]
        self.assertIsNone(red["cambio"]["en_curso"])
        self.assertTrue(red["cambio"]["ultimo"]["ok"])
        self.assertEqual(red["red"]["ssid"], "RedEjemplo")
        json.dumps(self.n.estado_pantalla())                                    # se puede publicar

    # ---- la contrasena no deja rastro ----
    def test_la_contrasena_no_se_guarda_en_el_registro_de_comandos(self) -> None:
        self.orden("r1", "red_configurar", ssid="Hospital", contrasena=CLAVE)
        self.terminar_el_cambio()
        (c,) = self.comandos()
        self.assertNotIn(CLAVE, c["parametros_json"] or "")
        self.assertEqual(json.loads(c["parametros_json"])["contrasena"], "***")
        self.assertEqual(json.loads(c["parametros_json"])["ssid"], "Hospital")

    def test_la_contrasena_no_aparece_en_ningun_byte_de_la_base_ni_en_los_eventos(self) -> None:
        self.orden("r1", "red_configurar", ssid="Hospital", contrasena=CLAVE)
        self.terminar_el_cambio()
        self.a.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for archivo in self.dir.glob("g2.db*"):
            self.assertNotIn(CLAVE.encode(), archivo.read_bytes(), archivo.name)
        textos = [f"{f['mensaje']} {f['datos_json']}" for f in self.a.db.execute("SELECT mensaje, datos_json FROM evento")]
        self.assertNotIn(CLAVE, " ".join(textos))

    def test_la_contrasena_no_sale_en_el_registro_de_actividad(self) -> None:
        with self.assertLogs(level="DEBUG") as registro:
            logging.getLogger("g2.test").debug("inicio")
            self.orden("r1", "red_configurar", ssid="Hospital", contrasena=CLAVE)
            self.terminar_el_cambio()
        self.assertNotIn(CLAVE, "\n".join(registro.output))

    @unittest.skipIf(os.name == "nt", "los permisos POSIX no existen en Windows")
    def test_el_archivo_de_la_orden_solo_lo_lee_su_dueno_y_se_borra_al_recogerla(self) -> None:
        nucleo = ipc.PublicadorEstado(self.dir / "run")
        ui = ipc.ClienteNucleo(self.dir / "run")
        ui.enviar_orden("red_configurar", ssid="Hospital", contrasena=CLAVE)
        (archivo,) = (self.dir / "run" / ipc.CARPETA_ORDENES).glob("*.json")
        self.assertEqual(archivo.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(nucleo.recoger_ordenes()), 1)
        self.assertEqual(list((self.dir / "run" / ipc.CARPETA_ORDENES).iterdir()), [])

    # ---- validaciones ----
    def test_datos_invalidos_se_rechazan_sin_llamar_al_gestor(self) -> None:
        self.orden("r1", "red_configurar", ssid="", contrasena="12345678")
        self.orden("r2", "red_configurar", ssid="Red", contrasena="corta")
        self.orden("r3", "red_configurar", ssid=5, contrasena="12345678")
        self.orden("r4", "red_configurar", ssid="Red", contrasena="12345678", oculta="si")
        self.assertEqual([c["estado"] for c in self.comandos()], ["rechazado"] * 4)
        self.assertEqual(self.gestor.llamadas, [])
        self.assertEqual(self.eventos("RED_CAMBIO_SOLICITADO"), [])

    def test_un_segundo_cambio_mientras_hay_uno_en_curso_se_rechaza(self) -> None:
        self.orden("r1", "red_configurar", ssid="A", contrasena="12345678")
        self.orden("r2", "red_configurar", ssid="B", contrasena="12345678")
        self.assertEqual([c["estado"] for c in self.comandos()], ["recibido", "rechazado"])
        self.assertIn("en curso", self.comandos()[1]["resultado_json"])

    def test_la_misma_orden_no_se_ejecuta_dos_veces(self) -> None:
        self.orden("r1", "red_configurar", ssid="Hospital", contrasena=CLAVE)
        self.terminar_el_cambio()
        self.orden("r1", "red_configurar", ssid="Hospital", contrasena=CLAVE)
        self.red.ciclo()
        self.assertEqual(len(self.gestor.llamadas), 1)

    def test_sin_servicio_de_red_se_rechaza(self) -> None:
        n = Nucleo(self.a, FuenteSimulada({"ads1263:0-1": 0.209}), mono=lambda: self.t[0])
        n.iniciar()
        n.procesar_orden({"uuid": "x", "tipo": "red_configurar", "origen": "pantalla", "ssid": "A", "contrasena": ""})
        self.assertEqual(self.comandos()[-1]["estado"], "rechazado")
        self.assertIsNone(n.estado_pantalla()["red"])

    def test_buscar_redes(self) -> None:
        self.red.ciclo()
        antes = self.gestor.busquedas
        self.orden("b1", "red_buscar")
        self.red.ciclo()
        self.assertEqual(self.gestor.busquedas, antes + 1)
        self.assertEqual(self.comandos()[-1]["estado"], "ok")


if __name__ == "__main__":
    unittest.main()
