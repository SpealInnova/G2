"""Pruebas del aviso a systemd (g2.nucleo.notificacion) y del latido por progreso del ciclo."""

from __future__ import annotations

import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from g2.nucleo import notificacion as N


class EnchufeFalso:
    """Sustituye al socket UNIX: recuerda a donde se conecto y que se mando."""

    enviados: list[tuple[str, bytes]] = []

    def __init__(self, *_a, **_k) -> None:
        self.ruta: str | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_e) -> None:
        return None

    def connect(self, ruta: str) -> None:
        self.ruta = ruta

    def sendall(self, datos: bytes) -> None:
        EnchufeFalso.enviados.append((self.ruta, datos))


class PruebasNotificacion(unittest.TestCase):
    def setUp(self) -> None:
        EnchufeFalso.enviados = []
        N._ultimo_latido = N._ultimo_estado = float("-inf")
        self._af = mock.patch.object(socket, "AF_UNIX", 1, create=True)
        self._so = mock.patch.object(socket, "socket", EnchufeFalso)
        self._af.start()
        self._so.start()
        self.addCleanup(self._af.stop)
        self.addCleanup(self._so.stop)

    def con_socket(self, ruta: str = "/run/systemd/notify"):
        return mock.patch.dict(os.environ, {"NOTIFY_SOCKET": ruta})

    def test_sin_notify_socket_no_hace_nada(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(N.listo())
            self.assertFalse(N.latido())
            self.assertFalse(N.deteniendo())
        self.assertEqual(EnchufeFalso.enviados, [])

    def test_listo_latido_estado_y_cierre(self) -> None:
        with self.con_socket():
            self.assertTrue(N.listo("g2-core en marcha"))
            self.assertTrue(N.latido(ahora=100.0))
            self.assertTrue(N.estado("S1 20.9 %", ahora=100.0))
            self.assertTrue(N.deteniendo())
        mensajes = [m for _, m in EnchufeFalso.enviados]
        self.assertEqual(mensajes, [b"READY=1\nSTATUS=g2-core en marcha", b"WATCHDOG=1",
                                    b"STATUS=S1 20.9 %", b"STOPPING=1"])
        self.assertTrue(all(ruta == "/run/systemd/notify" for ruta, _ in EnchufeFalso.enviados))

    def test_el_latido_y_el_estado_se_limitan_en_frecuencia(self) -> None:
        with self.con_socket():
            self.assertTrue(N.latido(ahora=10.0))
            self.assertFalse(N.latido(ahora=10.5))                  # menos de 1 s
            self.assertTrue(N.latido(ahora=11.0))
            self.assertTrue(N.estado("a", ahora=10.0))
            self.assertFalse(N.estado("b", ahora=14.0))             # menos de 5 s
            self.assertTrue(N.estado("c", ahora=15.0))

    def test_socket_abstracto_de_linux(self) -> None:
        with self.con_socket("@/org/freedesktop/systemd1/notify"):
            N.listo()
        self.assertEqual(EnchufeFalso.enviados[0][0], "\0/org/freedesktop/systemd1/notify")

    def test_un_error_de_envio_no_derriba_al_programa(self) -> None:
        class Roto(EnchufeFalso):
            def sendall(self, datos: bytes) -> None:
                raise OSError("sin destino")

        with self.con_socket(), mock.patch.object(socket, "socket", Roto):
            self.assertFalse(N.listo())

    def test_plazo_del_watchdog(self) -> None:
        with mock.patch.dict(os.environ, {"WATCHDOG_USEC": "30000000"}):
            self.assertEqual(N.plazo_watchdog_s(), 30.0)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(N.plazo_watchdog_s())


class PruebasLatidoPorProgreso(unittest.TestCase):
    """El latido solo se da cuando el paso termino bien (watchdog por progreso, D-012)."""

    def preparar(self):
        from g2.almacenamiento.almacen import Almacen
        from g2.nucleo.fuentes import FuenteSimulada
        from g2.nucleo.nucleo import Nucleo
        from g2.tiempo import RelojPrueba
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        a = Almacen.abrir(Path(tmp.name) / "g2.db", RelojPrueba())
        self.addCleanup(a.cerrar)
        a.registrar_sensor(canal="ads1263:0-1", nombre="Sensor 1", modelo="P", mv_por_pct=10.0)
        reloj = [0.0]
        n = Nucleo(a, FuenteSimulada({"ads1263:0-1": 0.209}), mono=lambda: reloj[0])
        n.iniciar()
        return n, reloj

    def test_hay_un_latido_por_cada_paso_completo(self) -> None:
        n, reloj = self.preparar()
        latidos, pasos = [], [0]

        def dormir(s: float) -> None:
            reloj[0] += s
            pasos[0] += 1

        n.ejecutar(lambda: pasos[0] >= 5, periodo_s=0.5, dormir=dormir, al_paso=lambda: latidos.append(1))
        self.assertEqual(len(latidos), 5)

    def test_si_el_paso_falla_no_hay_latido_y_la_excepcion_sale(self) -> None:
        n, reloj = self.preparar()
        latidos = []
        n.fuente = mock.Mock(leer=mock.Mock(side_effect=RuntimeError("ADC atascado")))
        with self.assertRaises(RuntimeError):
            n.ejecutar(lambda: False, dormir=lambda s: None, al_paso=lambda: latidos.append(1))
        self.assertEqual(latidos, [])


if __name__ == "__main__":
    unittest.main()
