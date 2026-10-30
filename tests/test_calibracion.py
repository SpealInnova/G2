"""Pruebas de la calibracion por puntos (D-048, D-049): la recta, la maquina de estados y su integracion con el nucleo."""

from __future__ import annotations

import math
import unittest

from g2.nucleo import calibracion as cal
from g2.nucleo import senal
from g2.nucleo.calibracion import Punto, Puntos
from test_nucleo_ciclo import C1, C2, BaseCiclo, volts


def o2(recta: cal.Recta, mv: float, mv_por_pct: float = 10.0) -> float:
    return senal.tension_a_pct(mv / 1000.0, mv_por_pct, recta.cero_pct, recta.ganancia)


class PruebasRecta(unittest.TestCase):
    def test_solo_el_punto_bajo_corrige_el_cero_y_deja_la_ganancia_en_uno(self) -> None:
        r = cal.calcular(10.0, Punto(0.0, 2.0), Puntos())                   # con nitrogeno el sensor marca 0,2 %
        self.assertIsNone(r.error)
        self.assertEqual(r.ganancia, 1.0)
        self.assertAlmostEqual(r.cero_pct, -0.2)
        self.assertAlmostEqual(o2(r, 2.0), 0.0)

    def test_el_aire_cuenta_como_punto_bajo(self) -> None:
        r = cal.calcular(10.0, Punto(20.9, 214.0), Puntos())
        self.assertEqual((r.ganancia, round(r.cero_pct, 6)), (1.0, -0.5))
        self.assertIsNotNone(r.puntos.bajo)
        self.assertIsNone(r.puntos.alto)

    def test_solo_el_punto_alto_corrige_la_ganancia_por_el_origen(self) -> None:
        r = cal.calcular(10.0, Punto(98.0, 975.0), Puntos())
        self.assertIsNone(r.error)
        self.assertEqual(r.cero_pct, 0.0)
        self.assertAlmostEqual(r.ganancia, 98.0 / 97.5)
        self.assertAlmostEqual(o2(r, 975.0), 98.0)

    def test_con_los_dos_puntos_la_recta_pasa_por_ambos(self) -> None:
        previos = Puntos(bajo=Punto(0.0, 3.0))
        r = cal.calcular(10.0, Punto(99.8, 985.0), previos)
        self.assertIsNone(r.error)
        self.assertAlmostEqual(o2(r, 3.0), 0.0)
        self.assertAlmostEqual(o2(r, 985.0), 99.8)
        self.assertEqual((r.puntos.bajo, r.puntos.alto), (Punto(0.0, 3.0), Punto(99.8, 985.0)))

    def test_el_orden_de_los_puntos_da_la_misma_recta(self) -> None:
        a = cal.calcular(10.0, Punto(98.0, 970.0), Puntos(bajo=Punto(0.0, 3.0)))
        b = cal.calcular(10.0, Punto(0.0, 3.0), Puntos(alto=Punto(98.0, 970.0)))
        self.assertAlmostEqual(a.ganancia, b.ganancia)
        self.assertAlmostEqual(a.cero_pct, b.cero_pct)

    def test_medir_otra_vez_un_punto_reemplaza_solo_su_casilla(self) -> None:
        previos = Puntos(bajo=Punto(0.0, 3.0), alto=Punto(98.0, 970.0))
        r = cal.calcular(10.0, Punto(99.8, 985.0), previos)                 # un gas alto distinto
        self.assertEqual((r.puntos.bajo, r.puntos.alto), (Punto(0.0, 3.0), Punto(99.8, 985.0)))

    def test_puntos_demasiado_cercanos_se_rechazan(self) -> None:
        r = cal.calcular(10.0, Punto(60.0, 600.0), Puntos(bajo=Punto(20.9, 209.0)))
        self.assertIn("distan menos de 50", r.error)

    def test_ganancia_fuera_de_0_90_a_1_10_se_rechaza(self) -> None:
        r = cal.calcular(10.0, Punto(98.0, 800.0), Puntos())                # el sensor solo da 80 %: ganancia 1,225
        self.assertIn("ganancia", r.error)
        r = cal.calcular(10.0, Punto(98.0, 1100.0), Puntos())               # 110 %: ganancia 0,89
        self.assertIn("ganancia", r.error)
        self.assertIsNone(cal.calcular(10.0, Punto(98.0, 980.0 / 1.1), Puntos()).error)      # justo 1,10

    def test_cero_pasado_de_3_se_rechaza(self) -> None:
        self.assertIsNone(cal.calcular(10.0, Punto(0.0, 30.0), Puntos()).error)             # -3,0 exacto
        self.assertIn("cero", cal.calcular(10.0, Punto(0.0, 30.5), Puntos()).error)

    def test_una_senal_alta_menor_que_la_baja_se_rechaza(self) -> None:
        r = cal.calcular(10.0, Punto(98.0, 5.0), Puntos(bajo=Punto(0.0, 900.0)))
        self.assertIn("no es mayor", r.error)

    def test_los_mensajes_breves_caben_en_la_linea_de_la_pantalla(self) -> None:
        """``Sensor 1: `` + el mensaje debe caber en los 80 caracteres de ``calibracion.res``."""
        casos = [(Punto(0.0, 900.0), Puntos()), (Punto(98.0, 800.0), Puntos()), (Punto(98.0, 5.0), Puntos(bajo=Punto(0.0, 900.0))),
                 (Punto(60.0, 600.0), Puntos(bajo=Punto(20.9, 209.0))), (Punto(98.0, 0.0), Puntos())]
        for punto, previos in casos:
            c = cal.CalibracionPunto(sensor_id=1, nombre="Sensor 1", mv_por_pct=10.0, referencia_pct=punto.referencia_pct,
                                     previos=previos, ahora_s=0.0, comando_id=None, actor="t", origen="local")
            r = c._concluir(punto.mv, 30.0)
            self.assertFalse(r.ok)
            self.assertTrue(r.breve)
            self.assertLessEqual(len("Sensor 1: " + r.breve), 80, r.breve)
        r = cal.CalibracionPunto(sensor_id=1, nombre="Sensor 1", mv_por_pct=10.0, referencia_pct=99.8, previos=Puntos(),
                                 ahora_s=0.0, comando_id=None, actor="t", origen="local")._concluir(985.0, 30.0)
        self.assertTrue(r.ok)
        self.assertLessEqual(len("Sensor 1: " + r.breve), 80)

    def test_casilla_por_la_referencia(self) -> None:
        self.assertEqual([cal.casilla(x) for x in (0.0, 20.9, 49.9, 50.0, 98.0, 99.8)],
                         ["bajo", "bajo", "bajo", "alto", "alto", "alto"])


class PruebasMaquina(unittest.TestCase):
    def nueva(self, referencia=20.9, previos=None) -> cal.CalibracionPunto:
        return cal.CalibracionPunto(sensor_id=1, nombre="Sensor 1", mv_por_pct=10.0, referencia_pct=referencia,
                                    previos=previos or Puntos(), ahora_s=0.0, comando_id=7, actor="pantalla", origen="pantalla")

    def correr(self, c, mv, desde=0.0, hasta=60.0, paso=0.5):
        t, resultado = desde, None
        while t < hasta and resultado is None:
            t += paso
            resultado = c.agregar(t, mv(t) if callable(mv) else mv)
        return resultado, t

    def test_aire_estable_da_el_cero_con_el_promedio_de_30_s(self) -> None:
        resultado, t = self.correr(self.nueva(), 214.0)
        self.assertTrue(resultado.ok)
        self.assertEqual((resultado.casilla, resultado.referencia_pct), ("bajo", 20.9))
        self.assertAlmostEqual(resultado.offset_pct, -0.5, places=6)
        self.assertEqual(resultado.ganancia, 1.0)
        self.assertAlmostEqual(resultado.mv_prom, 214.0)
        self.assertGreaterEqual(t, cal.VENTANA_S - cal.TOLERANCIA_VENTANA_S)
        self.assertLess(t, cal.VENTANA_S + 2)

    def test_punto_alto_con_la_referencia_tecleada(self) -> None:
        resultado, _ = self.correr(self.nueva(99.8, Puntos(bajo=Punto(0.0, 3.0))), 985.0)
        self.assertTrue(resultado.ok)
        self.assertEqual(resultado.casilla, "alto")
        self.assertIn("Punto alto 99.8 %", resultado.motivo)
        self.assertAlmostEqual(o2(resultado.recta, 985.0), 99.8)

    def test_el_mensaje_avisa_que_falta_el_otro_punto(self) -> None:
        r, _ = self.correr(self.nueva(0.0), 2.0)
        self.assertIn("falta el punto alto", r.motivo)
        r, _ = self.correr(self.nueva(98.0), 975.0)
        self.assertIn("falta el punto bajo", r.motivo)
        r, _ = self.correr(self.nueva(98.0, Puntos(bajo=Punto(0.0, 2.0))), 975.0)
        self.assertNotIn("falta", r.motivo)

    def test_mientras_el_sensor_se_asienta_espera_y_mide_ya_estable(self) -> None:
        # baja de 90 % a 0 % con una constante de 8 s: la ventana de 30 s solo es estable cuando ya llego
        resultado, t = self.correr(self.nueva(0.0), lambda t: 2.0 + 898.0 * math.exp(-t / 8.0), hasta=240.0)
        self.assertTrue(resultado.ok)
        self.assertGreater(t, 60.0)
        self.assertLess(abs(resultado.offset_pct), 0.5)

    def test_una_muestra_sin_senal_vacia_la_ventana(self) -> None:
        c = self.nueva()
        self.correr(c, 209.0, hasta=25.0)
        self.assertIsNone(c.agregar(25.5, None))
        self.assertIsNone(c.variacion_pct)
        resultado, t = self.correr(c, 209.0, desde=25.5, hasta=100.0)
        self.assertTrue(resultado.ok)
        self.assertGreaterEqual(t - 25.5, cal.VENTANA_S - cal.TOLERANCIA_VENTANA_S)

    def test_con_el_sensor_en_la_linea_falla_y_dice_que_gas_mide(self) -> None:
        resultado, _ = self.correr(self.nueva(0.0), 900.0)                  # se creyo que estaba con nitrogeno: sigue en 90 %
        self.assertFalse(resultado.ok)
        self.assertIn("mide 90.0 % con gas de 0 %", resultado.motivo)
        self.assertIsNotNone(resultado.recta)                               # se entrega para dejarla en el registro

    def test_si_nunca_se_estabiliza_falla_a_los_5_minutos(self) -> None:
        resultado, t = self.correr(self.nueva(), lambda t: 209.0 + (5.0 if int(t) % 2 else -5.0), hasta=400.0)
        self.assertFalse(resultado.ok)
        self.assertIsNone(resultado.offset_pct)
        self.assertAlmostEqual(t, cal.TOPE_S, delta=0.6)
        self.assertIn("no se estabilizó", resultado.motivo)

    def test_el_estado_para_la_pantalla(self) -> None:
        c = self.nueva(98.0)
        self.correr(c, 975.0, hasta=10.0)
        e = c.estado(10.0, 97.5)
        self.assertEqual((e["en_curso"], e["sensor_id"], e["referencia_pct"], e["casilla"], e["texto_o2"]),
                         (True, 1, 98.0, "alto", "97.5"))


class BaseCalibracion(BaseCiclo):
    def setUp(self) -> None:
        super().setUp()
        self.n.iniciar()
        self.contador = 0

    def orden(self, tipo, **datos) -> int:
        self.contador += 1
        self.n.procesar_orden({"uuid": f"u{self.contador}", "tipo": tipo, "origen": "pantalla", "actor": "pantalla", **datos})
        return self.a.db.execute("SELECT id FROM comando WHERE uuid = ?", (f"u{self.contador}",)).fetchone()["id"]

    def comando(self, comando_id) -> dict:
        return dict(self.a.db.execute("SELECT * FROM comando WHERE id = ?", (comando_id,)).fetchone())

    def calibraciones(self, sensor_id=1) -> list:
        return self.a.db.execute("SELECT * FROM calibracion WHERE sensor_id = ? ORDER BY id", (sensor_id,)).fetchall()

    def estado(self, sensor_id=1) -> dict:
        return next(s for s in self.n.estado_pantalla()["sensores"] if s["id"] == sensor_id)

    def calibrar(self, sensor_id: int, referencia: float, pct_medido: float, segundos: float = 40) -> int:
        self.fuente.tensiones[C1 if sensor_id == 1 else C2] = volts(pct_medido)
        cid = self.orden("calibrar_punto", sensor_id=sensor_id, referencia_pct=referencia)
        self.correr(self.n, segundos)
        return cid


class PruebasNucleoCalibrando(BaseCalibracion):
    def test_punto_bajo_con_nitrogeno_deja_el_cero_y_lo_aplica(self) -> None:
        cid = self.calibrar(1, 0.0, 0.2)
        self.assertEqual(self.comando(cid)["estado"], "ok")
        self.assertIn("CAL_INICIADA", self.codigos_de_eventos())
        self.assertIn("CAL_REGISTRADA", self.codigos_de_eventos())
        fila = self.calibraciones()[-1]
        self.assertEqual((fila["tipo"], fila["resultado"], fila["vigente"], fila["origen"], fila["actor"]),
                         ("puntos", "ok", 1, "pantalla", "pantalla"))
        self.assertAlmostEqual(fila["offset_pct"], -0.2, places=6)
        self.assertEqual(fila["ganancia"], 1.0)
        self.assertEqual((fila["gas_pct"], fila["comando_id"]), (0.0, cid))
        self.assertAlmostEqual(fila["mv_antes"], 2.0)
        self.assertEqual((fila["bajo_ref_pct"], fila["alto_ref_pct"], fila["alto_mv"]), (0.0, None, None))
        self.correr(self.n, 2)
        self.assertAlmostEqual(self.n._valores[1], 0.0, places=6)           # ya lee 0,0 con el cero nuevo

    def test_punto_alto_despues_del_bajo_deja_la_ganancia_y_conserva_el_bajo(self) -> None:
        self.calibrar(1, 0.0, 0.2)
        self.calibrar(1, 98.0, 97.5)
        filas = self.calibraciones()
        self.assertEqual([f["vigente"] for f in filas], [0, 1])
        fila = filas[-1]
        self.assertAlmostEqual(fila["ganancia"], 98.0 / 97.3, places=6)
        self.assertAlmostEqual(fila["offset_pct"], -fila["ganancia"] * 0.2, places=6)
        self.assertEqual((fila["bajo_ref_pct"], fila["alto_ref_pct"]), (0.0, 98.0))
        self.assertAlmostEqual(fila["bajo_mv"], 2.0)
        self.assertAlmostEqual(fila["alto_mv"], 975.0)
        self.correr(self.n, 2)
        self.assertAlmostEqual(self.n._valores[1], 98.0, places=6)          # en el alto
        self.fuente.tensiones[C1] = volts(0.2)
        self.correr(self.n, 2)
        self.assertAlmostEqual(self.n._valores[1], 0.0, places=6)           # y en el bajo

    def test_un_segundo_gas_alto_reemplaza_al_anterior_y_el_bajo_se_conserva(self) -> None:
        self.calibrar(1, 0.0, 0.2)
        self.calibrar(1, 98.0, 97.5)
        self.calibrar(1, 99.8, 99.1)
        fila = self.calibraciones()[-1]
        self.assertEqual((fila["bajo_ref_pct"], fila["alto_ref_pct"]), (0.0, 99.8))
        self.assertEqual([f["vigente"] for f in self.calibraciones()], [0, 0, 1])

    def test_el_punto_alto_solo_corrige_la_ganancia_por_el_origen(self) -> None:
        self.calibrar(1, 98.0, 97.5)
        fila = self.calibraciones()[-1]
        self.assertEqual(fila["offset_pct"], 0.0)
        self.assertAlmostEqual(fila["ganancia"], 98.0 / 97.5, places=6)
        self.assertEqual((fila["bajo_ref_pct"], fila["alto_ref_pct"]), (None, 98.0))

    def test_las_lecturas_del_tramo_quedan_marcadas_y_las_nuevas_apuntan_a_la_calibracion(self) -> None:
        self.correr(self.n, 20)
        self.calibrar(1, 20.9, 21.4)
        self.correr(self.n, 20)
        filas = self.lecturas(1)
        marcadas = [f for f in filas if f["calidad"] & senal.CALIDAD_EN_SPOC]
        self.assertTrue(marcadas)
        self.assertTrue(all(f["n_muestras"] == 0 for f in marcadas))        # esas muestras no son medicion
        self.assertEqual(filas[-1]["calibracion_id"], self.calibraciones()[-1]["id"])
        self.assertEqual(filas[-1]["calidad"], 0)
        self.assertTrue(all(not f["calidad"] & senal.CALIDAD_EN_SPOC for f in self.lecturas(2)))

    def test_un_sensor_con_otro_gas_falla_y_la_calibracion_no_cambia(self) -> None:
        self.calibrar(1, 0.0, 0.2)
        cid = self.calibrar(1, 0.0, 90.0)                                   # se dijo nitrogeno pero sigue en la linea
        fila = self.calibraciones()[-1]
        self.assertEqual((fila["resultado"], fila["vigente"]), ("fallo", 0))
        self.assertEqual(self.comando(cid)["estado"], "error")
        self.assertIn("CAL_FALLIDA", self.codigos_de_eventos())
        self.assertAlmostEqual(self.n.sensores[0].offset_pct, -0.2, places=6)       # sigue la anterior
        self.assertEqual(self.a.calibracion_vigente_fila(1)["id"], self.calibraciones()[0]["id"])

    def test_el_sensor_calibrado_muestra_calibrando_y_el_otro_sigue_vigilado(self) -> None:
        self.fuente.tensiones[C2] = volts(95.0)                             # el otro esta en alarma ALTA
        self.correr(self.n, 20)
        self.assertEqual(self.estado(2)["estado"], "ALTA")
        self.orden("calibrar_punto", sensor_id=1, referencia_pct=98.0)
        self.correr(self.n, 5)
        e = self.n.estado_pantalla()
        self.assertEqual(self.estado(1)["estado"], "CALIBRANDO")
        self.assertEqual(self.estado(2)["estado"], "ALTA")
        self.assertTrue(e["rele_alto"])
        self.assertTrue(e["calibracion"]["en_curso"])
        self.assertEqual(e["calibracion"]["referencia_pct"], 98.0)
        self.assertIn("Calibrando Sensor 1", e["aviso"])
        self.assertIn("S2 ALTO", e["aviso"])

    def test_las_alarmas_del_sensor_calibrado_se_suspenden_y_vuelven_al_terminar(self) -> None:
        self.fuente.tensiones[C1] = volts(95.0)
        self.correr(self.n, 20)
        self.assertEqual(self.estado(1)["estado"], "ALTA")
        self.orden("calibrar_punto", sensor_id=1, referencia_pct=98.0)
        self.correr(self.n, 5)
        abiertas = self.a.db.execute("SELECT COUNT(*) FROM alarma WHERE sensor_id = 1 AND estado <> 'cerrada'").fetchone()[0]
        self.assertEqual(abiertas, 0)
        self.n.procesar_orden({"uuid": "c", "tipo": "calibrar_cancelar", "origen": "pantalla"})
        self.correr(self.n, 20)
        self.assertEqual(self.estado(1)["estado"], "ALTA")

    def test_cancelar_no_cambia_nada_y_lo_deja_registrado(self) -> None:
        self.fuente.tensiones[C1] = volts(21.4)
        cid = self.orden("calibrar_punto", sensor_id=1, referencia_pct=20.9)
        self.correr(self.n, 10)
        otro = self.orden("calibrar_cancelar")
        self.assertIsNone(self.n.calibracion)
        self.assertEqual(self.comando(otro)["estado"], "ok")
        self.assertEqual(self.comando(cid)["estado"], "error")
        self.assertEqual(self.calibraciones(), [])
        self.assertIn("CAL_CANCELADA", self.codigos_de_eventos())
        self.assertFalse(self.n.estado_pantalla()["calibracion"]["en_curso"])

    def test_cancelar_sin_calibracion_se_rechaza(self) -> None:
        self.assertEqual(self.comando(self.orden("calibrar_cancelar"))["estado"], "rechazado")

    def test_el_cierre_del_nucleo_cancela_la_que_estaba_en_curso(self) -> None:
        cid = self.orden("calibrar_punto", sensor_id=1, referencia_pct=0.0)
        self.correr(self.n, 5)
        self.n.cerrar()
        self.assertEqual(self.comando(cid)["estado"], "error")
        self.assertIn("CAL_CANCELADA", self.codigos_de_eventos())

    def test_la_calibracion_vigente_se_recupera_al_reiniciar_el_nucleo(self) -> None:
        self.calibrar(1, 0.0, 0.2)
        self.calibrar(1, 98.0, 97.5)
        nuevo = self.nuevo_nucleo()
        nuevo.iniciar()
        self.assertAlmostEqual(nuevo.sensores[0].ganancia, 98.0 / 97.3, places=6)
        self.assertAlmostEqual(nuevo.sensores[0].offset_pct, -0.2 * 98.0 / 97.3, places=6)


class PruebasRechazos(BaseCalibracion):
    def rechazo(self, **datos) -> str:
        datos.setdefault("referencia_pct", 98.0)
        return self.comando(self.orden("calibrar_punto", **datos))["resultado_json"]

    def test_sensor_inexistente_o_invalido(self) -> None:
        for datos in ({"sensor_id": 99}, {"sensor_id": "1"}, {}):
            self.assertIn("sensor invalido", self.rechazo(**datos))
        self.assertIsNone(self.n.calibracion)

    def test_la_concentracion_del_gas_debe_ser_un_numero_de_0_a_100(self) -> None:
        for valor in (-1, 100.5, "98", None, True, [98]):
            self.assertIn("entre 0 y 100", self.rechazo(sensor_id=1, referencia_pct=valor))
        self.assertIn("entre 0 y 100", self.comando(self.orden("calibrar_punto", sensor_id=1))["resultado_json"])   # sin el dato
        self.assertIsNone(self.n.calibracion)
        for valor in (0, 0.0, 20.9, 99.8, 100):                                                                      # y los extremos sirven
            self.n.calibracion = None
            self.assertEqual(self.comando(self.orden("calibrar_punto", sensor_id=1, referencia_pct=valor))["estado"], "recibido")
            self.n._cancelar_calibracion("prueba")

    def test_un_sensor_apagado_no_se_calibra(self) -> None:
        self.orden("sensor_habilitar", sensor_id=1, habilitado=False)
        self.assertIn("sensor invalido", self.rechazo(sensor_id=1))

    def test_no_se_calibra_si_no_queda_otro_sensor_vigilando(self) -> None:
        self.orden("sensor_habilitar", sensor_id=2, habilitado=False)
        self.assertIn("encienda el otro sensor", self.rechazo(sensor_id=1))
        self.assertIsNone(self.n.calibracion)

    def test_no_se_puede_empezar_otra_mientras_hay_una(self) -> None:
        self.orden("calibrar_punto", sensor_id=1, referencia_pct=0.0)
        self.assertIn("ya hay una calibracion en curso", self.rechazo(sensor_id=2))
        self.assertEqual(self.n.calibracion.sensor_id, 1)

    def test_no_se_calibra_mientras_se_genera_un_reporte(self) -> None:
        class ReporteEnCurso:
            def estado(self):
                return {"en_curso": True}
        self.n.reportes = ReporteEnCurso()
        self.assertIn("se esta generando un reporte", self.rechazo(sensor_id=1))

    def test_no_se_apaga_el_sensor_que_se_calibra(self) -> None:
        self.orden("calibrar_punto", sensor_id=1, referencia_pct=0.0)
        cid = self.orden("sensor_habilitar", sensor_id=1, habilitado=False)
        self.assertEqual(self.comando(cid)["estado"], "rechazado")
        self.assertIn("se esta calibrando", self.comando(cid)["resultado_json"])
        self.assertEqual(self.estado(1)["estado"], "CALIBRANDO")


class PruebasMigracion010a011(unittest.TestCase):
    """Una base en la version 10 con una calibracion de cero pasa a la 11 sin perderla ni romper la cadena de auditoria."""

    def test_migrar_con_una_calibracion_anterior(self) -> None:
        import shutil
        import tempfile
        from pathlib import Path

        from g2.almacenamiento import auditoria, base, migraciones
        with tempfile.TemporaryDirectory() as tmp:
            hasta10 = Path(tmp) / "hasta10"
            hasta10.mkdir()
            for archivo in sorted(migraciones.CARPETA_SQL.glob("*.sql"))[:10]:
                shutil.copy(archivo, hasta10 / archivo.name)
            con = base.abrir_escritura(Path(tmp) / "g2.db")
            try:
                self.assertEqual(migraciones.migrar(con, hasta10), 10)
                con.execute("INSERT INTO arranque (boot_id, inicio_ms, inicio_confiable, version_sw) VALUES ('x#1', 1000, 1, '0')")
                con.execute("INSERT INTO sensor (canal, nombre, modelo, mv_por_pct) VALUES ('ads1263:0-1', 'S1', 'P', 10.0)")
                con.execute("INSERT INTO calibracion (ts_ms, ts_confiable, arranque_id, mono_ms, sensor_id, tipo, gas_pct, mv_antes,"
                            " offset_pct, origen, resultado, vigente) VALUES (2000, 1, 1, 5, 1, 'offset_cero', 20.9, 214.0, -0.5,"
                            " 'pantalla', 'ok', 1)")
                con.execute("INSERT INTO calibracion (ts_ms, ts_confiable, arranque_id, mono_ms, sensor_id, tipo, gas_pct, mv_antes,"
                            " offset_pct, origen, resultado, vigente) VALUES (2100, 1, 1, 6, 1, 'offset_cero', 20.9, 979.0, -77.0,"
                            " 'pantalla', 'fallo', 0)")
                self.assertEqual(auditoria.verificar(con), [])
                with self.assertRaises(Exception):                                  # antes de la 011 no existe el tipo nuevo
                    con.execute("INSERT INTO calibracion (ts_ms, ts_confiable, arranque_id, mono_ms, sensor_id, tipo, origen,"
                                " resultado) VALUES (3000, 1, 1, 6, 1, 'puntos', 'local', 'ok')")

                self.assertEqual(migraciones.migrar(con), 11)

                filas = [tuple(f) for f in con.execute(
                    "SELECT tipo, offset_pct, ganancia, bajo_ref_pct, bajo_mv, alto_mv, rev, vigente FROM calibracion ORDER BY id")]
                # la correcta pasa a ser el punto bajo (20,9 % a 214 mV); el fallo solo se re-sella; las dos quedan conservadas
                self.assertEqual(filas, [("offset_cero", -0.5, None, 20.9, 214.0, None, 2, 1),
                                         ("offset_cero", -77.0, None, None, None, None, 2, 0)])
                self.assertEqual(auditoria.verificar(con), [])                                       # cadena coherente
                self.assertEqual([f[0] for f in con.execute("SELECT rev FROM auditoria_cadena WHERE tabla = 'calibracion' ORDER BY seq")],
                                 [1, 1, 2, 2])
                con.execute("INSERT INTO calibracion (ts_ms, ts_confiable, arranque_id, mono_ms, sensor_id, tipo, gas_pct, offset_pct,"
                            " ganancia, bajo_ref_pct, bajo_mv, origen, resultado, vigente) VALUES (3000, 1, 1, 6, 1, 'puntos', 0, -0.2,"
                            " 1.0, 0, 2.0, 'local', 'ok', 1)")                                     # el tipo nuevo ya vale, en la misma conexion
                self.assertEqual(auditoria.verificar(con), [])
                self.assertEqual(con.execute("SELECT COUNT(*) FROM calibracion WHERE vigente = 1").fetchone()[0], 1)
                with self.assertRaises(Exception):                                                    # y la ganancia no puede ser <= 0
                    con.execute("UPDATE calibracion SET ganancia = 0 WHERE id = 3")
                self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            finally:
                con.close()

    def test_una_base_nueva_trae_todo_desde_el_principio(self) -> None:
        import tempfile
        from pathlib import Path

        from g2.almacenamiento.almacen import Almacen
        with tempfile.TemporaryDirectory() as tmp:
            a = Almacen.abrir(Path(tmp) / "g2.db")
            try:
                columnas = {f[1] for f in a.db.execute("PRAGMA table_info(calibracion)")}
                self.assertTrue({"ganancia", "bajo_ref_pct", "bajo_mv", "alto_ref_pct", "alto_mv"} <= columnas)
            finally:
                a.cerrar()


class PruebasCtl(unittest.TestCase):
    def ejecutar(self, *argumentos):
        import contextlib
        import io
        import json
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock

        from g2 import ctl
        with tempfile.TemporaryDirectory() as tmp:
            salida = io.StringIO()
            with mock.patch.dict(os.environ, {"G2_RUN": tmp}), contextlib.redirect_stdout(salida):
                codigo = ctl.main(list(argumentos))
            ordenes = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(Path(tmp, "ordenes").glob("*.json"))] \
                if Path(tmp, "ordenes").is_dir() else []
        return codigo, salida.getvalue(), ordenes

    def test_calibrar_punto_deja_la_orden_para_el_nucleo(self) -> None:
        codigo, salida, ordenes = self.ejecutar("calibrar-punto", "2", "99.8")
        self.assertEqual(codigo, 0)
        (orden,) = ordenes
        self.assertEqual((orden["tipo"], orden["sensor_id"], orden["referencia_pct"], orden["origen"], orden["actor"]),
                         ("calibrar_punto", 2, 99.8, "local", "g2ctl"))

    def test_calibrar_cancelar(self) -> None:
        codigo, _, ordenes = self.ejecutar("calibrar-cancelar")
        self.assertEqual((codigo, [o["tipo"] for o in ordenes]), (0, ["calibrar_cancelar"]))


if __name__ == "__main__":
    unittest.main()
