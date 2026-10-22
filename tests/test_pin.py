"""Pruebas del PIN (D-038): el modulo de seguridad, su almacenamiento, g2ctl y las ordenes del nucleo.

Los PIN de estas pruebas son inventados; el PIN de fabrica real NO esta en el repositorio."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from g2 import ctl
from g2.almacenamiento import auditoria
from g2.almacenamiento.almacen import Almacen, ErrorAlmacen
from g2.nucleo.fuentes import FuenteSimulada
from g2.nucleo.nucleo import Nucleo
from g2.seguridad import pin as seguridad_pin
from g2.seguridad.pin import ErrorPin
from g2.tiempo import RelojPrueba

PIN_A, PIN_B = "4821", "90417356"


class PruebasModuloPin(unittest.TestCase):
    def test_formato(self) -> None:
        for bueno in ("1234", "00000", "12345678"):
            self.assertEqual(seguridad_pin.validar_formato(bueno), bueno)
        for malo in ("", "123", "123456789", "12a4", "12 4", "１２３４", "-123", None, 1234):
            with self.assertRaises(ErrorPin):
                seguridad_pin.validar_formato(malo)

    def test_la_huella_verifica_el_pin_correcto_y_solo_ese(self) -> None:
        sal, huella, it = seguridad_pin.nueva_huella(PIN_A, iteraciones=10_000)
        self.assertTrue(seguridad_pin.verificar(PIN_A, sal, huella, it))
        self.assertFalse(seguridad_pin.verificar("4822", sal, huella, it))
        self.assertFalse(seguridad_pin.verificar("", sal, huella, it))
        self.assertFalse(seguridad_pin.verificar("abcd", sal, huella, it))

    def test_la_sal_es_distinta_cada_vez(self) -> None:
        a = seguridad_pin.nueva_huella(PIN_A, iteraciones=10_000)
        b = seguridad_pin.nueva_huella(PIN_A, iteraciones=10_000)
        self.assertNotEqual(a[0], b[0])
        self.assertNotEqual(a[1], b[1])                       # el mismo PIN no da la misma huella en dos equipos
        self.assertEqual(len(a[0]), seguridad_pin.LARGO_SAL)
        self.assertEqual(len(a[1]), 32)

    def test_el_pin_no_esta_en_la_huella_ni_en_la_sal(self) -> None:
        sal, huella, _ = seguridad_pin.nueva_huella(PIN_A, iteraciones=10_000)
        self.assertNotIn(PIN_A.encode(), sal + huella)


class BaseAlmacenPin(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ruta = Path(self._tmp.name) / "g2.db"
        self.reloj = RelojPrueba()
        self.a = Almacen.abrir(self.ruta, self.reloj)
        self.a.registrar_arranque(version_sw="test", so_boot_id="so-1")
        # las pruebas usan pocas iteraciones para ir rapido (el minimo que acepta la base es 10 000)
        patcher = mock.patch.object(seguridad_pin, "ITERACIONES", 10_000)
        patcher.start()
        self.addCleanup(patcher.stop)
        original = seguridad_pin.nueva_huella
        patcher2 = mock.patch.object(seguridad_pin, "nueva_huella",
                                     lambda pin, iteraciones=10_000: original(pin, iteraciones))
        patcher2.start()
        self.addCleanup(patcher2.stop)

    def tearDown(self) -> None:
        self.a.cerrar()
        self._tmp.cleanup()

    def eventos(self, codigo: str):
        return self.a.db.execute("SELECT * FROM evento WHERE codigo = ?", (codigo,)).fetchall()


class PruebasAlmacenPin(BaseAlmacenPin):
    def test_sin_pin_no_hay_ninguno_activo(self) -> None:
        self.assertIsNone(self.a.pin_activo())
        self.assertIsNone(self.a.pin_verificar(PIN_A))
        self.assertEqual(self.a.pin_tipos(), [])

    def test_fijar_y_verificar(self) -> None:
        self.a.pin_fijar("fabrica", PIN_A, origen="local", actor="instalador")
        self.assertEqual(self.a.pin_verificar(PIN_A), "fabrica")
        self.assertIsNone(self.a.pin_verificar("0000"))

    def test_el_de_la_plataforma_reemplaza_al_de_fabrica(self) -> None:
        self.a.pin_fijar("fabrica", PIN_A, origen="local")
        self.a.pin_fijar("plataforma", PIN_B, origen="plataforma", actor="admin")
        self.assertEqual(self.a.pin_activo()["tipo"], "plataforma")
        self.assertEqual(self.a.pin_verificar(PIN_B), "plataforma")
        self.assertIsNone(self.a.pin_verificar(PIN_A))                  # el de fabrica deja de valer
        self.assertEqual(self.a.pin_tipos(), ["fabrica", "plataforma"])

    def test_cambiar_un_pin_lo_reemplaza(self) -> None:
        self.a.pin_fijar("fabrica", PIN_A, origen="local")
        self.a.pin_fijar("fabrica", PIN_B, origen="local")
        self.assertIsNone(self.a.pin_verificar(PIN_A))
        self.assertEqual(self.a.pin_verificar(PIN_B), "fabrica")
        self.assertEqual(self.a.pin_tipos(), ["fabrica"])

    def test_un_formato_invalido_no_escribe_nada(self) -> None:
        for malo in ("12", "abcd", "123456789"):
            with self.assertRaises(ErrorPin):
                self.a.pin_fijar("fabrica", malo, origen="local")
        with self.assertRaises(ErrorAlmacen):
            self.a.pin_fijar("otro", PIN_A, origen="local")
        self.assertEqual(self.a.pin_tipos(), [])
        self.assertEqual(self.eventos("SEG_PIN_CAMBIADO"), [])

    def test_el_cambio_queda_como_evento_sin_el_valor(self) -> None:
        self.a.pin_fijar("fabrica", PIN_A, origen="local", actor="instalador")
        (e,) = self.eventos("SEG_PIN_CAMBIADO")
        self.assertIn("fabrica", e["mensaje"])
        self.assertIn("instalador", e["origen"])
        self.assertNotIn(PIN_A, json.dumps(dict(e)))

    def test_el_pin_no_aparece_en_ninguna_parte_de_la_base(self) -> None:
        self.a.pin_fijar("fabrica", PIN_A, origen="local")
        self.a.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for archivo in Path(self._tmp.name).glob("g2.db*"):
            self.assertNotIn(PIN_A.encode(), archivo.read_bytes(), archivo.name)

    def test_la_tabla_del_pin_no_entra_a_la_cola_de_envio(self) -> None:
        self.a.pin_fijar("fabrica", PIN_A, origen="local")
        self.a.pin_fijar("plataforma", PIN_B, origen="plataforma")
        tablas = {f[0] for f in self.a.db.execute("SELECT DISTINCT tabla FROM cola_envio")}
        self.assertNotIn("pin_acceso", tablas)                           # la huella de un PIN corto no sale del equipo
        self.assertEqual(auditoria.verificar(self.a.db), [])


class PruebasCtlPin(BaseAlmacenPin):
    def ejecutar(self, *argumentos: str, entrada: str = ""):
        salida, error = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(entrada)), redirect_stdout(salida), redirect_stderr(error):
            codigo = ctl.main(["--bd", str(self.ruta), *argumentos])
        return codigo, salida.getvalue(), error.getvalue()

    def test_pin_fijar_desde_stdin_y_pin_estado(self) -> None:
        self.a.cerrar()
        codigo, salida, _ = self.ejecutar("pin-fijar", "--desde-stdin", entrada=PIN_A + "\n")
        self.assertEqual(codigo, 0)
        self.assertNotIn(PIN_A, salida)                                  # nunca se repite el PIN
        codigo, salida, _ = self.ejecutar("pin-estado")
        self.assertIn("PIN de fabrica: si", salida)
        self.assertIn("rige: fabrica", salida)
        self.assertNotIn(PIN_A, salida)
        self.a = Almacen.abrir(self.ruta, self.reloj)
        self.assertEqual(self.a.pin_verificar(PIN_A), "fabrica")

    def test_pin_invalido_no_cambia_nada(self) -> None:
        self.a.cerrar()
        codigo, _, error = self.ejecutar("pin-fijar", "--desde-stdin", entrada="12\n")
        self.assertEqual(codigo, 2)
        self.assertIn("No se cambio el PIN", error)
        _, salida, _ = self.ejecutar("pin-estado")
        self.assertIn("NINGUNO", salida)
        self.a = Almacen.abrir(self.ruta, self.reloj)


class PruebasOrdenesDelNucleo(BaseAlmacenPin):
    def setUp(self) -> None:
        super().setUp()
        self.a.registrar_sensor(canal="ads1263:0-1", nombre="Sensor 1", modelo="P", mv_por_pct=10.0)
        self.t = [0.0]
        self.n = Nucleo(self.a, FuenteSimulada({"ads1263:0-1": 0.209}), mono=lambda: self.t[0])
        self.n.iniciar()

    def comandos(self):
        return self.a.db.execute("SELECT uuid, tipo, estado, resultado_json FROM comando ORDER BY id").fetchall()

    def orden(self, uuid: str, tipo: str, **datos) -> None:
        self.n.procesar_orden({"uuid": uuid, "tipo": tipo, "origen": "pantalla", "actor": "pantalla", **datos})

    def test_los_resultados_del_pin_quedan_como_eventos_de_seguridad(self) -> None:
        self.orden("p1", "pin_resultado", resultado="aceptado")
        self.orden("p2", "pin_resultado", resultado="fallido", intentos=2)
        self.orden("p3", "pin_resultado", resultado="bloqueado", intentos=3)
        self.assertEqual(len(self.eventos("SEG_PIN_ACEPTADO")), 1)
        (fallido,) = self.eventos("SEG_PIN_FALLIDO")
        self.assertEqual(json.loads(fallido["datos_json"]), {"intentos": 2})
        self.assertEqual(len(self.eventos("SEG_PIN_BLOQUEADO")), 1)
        self.assertEqual([c["estado"] for c in self.comandos()], ["ok", "ok", "ok"])

    def test_un_resultado_de_pin_invalido_se_rechaza(self) -> None:
        self.orden("p1", "pin_resultado", resultado="cualquier_cosa")
        self.assertEqual(self.comandos()[0]["estado"], "rechazado")
        self.assertEqual(self.eventos("SEG_PIN_ACEPTADO"), [])

    def test_cambiar_un_ajuste_desde_la_pantalla(self) -> None:
        self.orden("c1", "config_fijar", clave="alarma.o2_bajo_pct", valor="25.0")
        self.assertEqual(self.a.config_obtener("alarma.o2_bajo_pct"), "25.0")
        (c,) = self.comandos()
        self.assertEqual(c["estado"], "ok")
        hist = self.a.db.execute("SELECT origen, actor, comando_id FROM config_historial "
                                 "WHERE clave = 'alarma.o2_bajo_pct' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual((hist["origen"], hist["actor"]), ("pantalla", "pantalla"))
        self.assertIsNotNone(hist["comando_id"])                           # el cambio queda ligado a su orden

    def test_los_umbrales_nuevos_rigen_en_el_siguiente_paso(self) -> None:
        self.orden("c1", "config_fijar", clave="alarma.o2_bajo_pct", valor="22.0")
        self.t[0] += 5
        self.n.paso()
        self.assertEqual(self.n.umbrales.bajo_pct, 22.0)

    def test_un_valor_invalido_se_rechaza_y_no_cambia_nada(self) -> None:
        self.orden("c1", "config_fijar", clave="alarma.o2_bajo_pct", valor="500")
        self.orden("c2", "config_fijar", clave="alarma.o2_bajo_pct", valor="95")        # >= el maximo (92)
        self.orden("c3", "config_fijar", clave="no.existe", valor="1")
        self.assertEqual(self.a.config_obtener("alarma.o2_bajo_pct"), "20.0")
        self.assertEqual([c["estado"] for c in self.comandos()], ["rechazado"] * 3)
        self.assertIn("motivo", self.comandos()[0]["resultado_json"])

    def test_la_pantalla_no_puede_cambiar_los_ajustes_del_propio_pin(self) -> None:
        self.orden("c1", "config_fijar", clave="pantalla.pin_intentos", valor="100")
        self.orden("c2", "config_fijar", clave="pantalla.pin_bloqueo_s", valor="10")
        self.assertEqual(self.a.config_obtener("pantalla.pin_intentos"), "3")
        self.assertEqual([c["estado"] for c in self.comandos()], ["rechazado", "rechazado"])

    def test_la_misma_orden_no_se_ejecuta_dos_veces(self) -> None:
        self.orden("c1", "config_fijar", clave="alarma.o2_bajo_pct", valor="25")
        self.a.config_fijar("alarma.o2_bajo_pct", 30, origen="local")
        self.orden("c1", "config_fijar", clave="alarma.o2_bajo_pct", valor="25")       # reenvio del mismo uuid
        self.assertEqual(self.a.config_obtener("alarma.o2_bajo_pct"), "30.0")


if __name__ == "__main__":
    unittest.main()
