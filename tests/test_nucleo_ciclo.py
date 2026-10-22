"""Pruebas del ciclo completo del nucleo (g2.nucleo.nucleo): lectura, conversion, almacenamiento por
intervalo, alarmas con relevos y sonido, arranque y cierre ordenado. Fuente de tensiones simulada y
reloj controlado; base real temporal."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from g2.almacenamiento import auditoria
from g2.almacenamiento.almacen import Almacen
from g2.nucleo.fuentes import FuenteAds1263, FuenteSimulada, analizar_canal
from g2.nucleo.nucleo import Nucleo
from g2.nucleo.salidas import SalidasEmuladas
from g2.tiempo import RelojPrueba

C1, C2 = "ads1263:0-1", "ads1263:2-3"


def volts(pct: float | None) -> float | None:
    """Tension que entrega un Paracube (10 mV por %) para un % de O2."""
    return None if pct is None else pct * 0.010


class BaseCiclo(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ruta = Path(self._tmp.name) / "g2.db"
        self.reloj = RelojPrueba()
        self.t = [0.0]
        self.fuente = FuenteSimulada({C1: volts(20.9), C2: volts(20.9)})
        self.salidas = SalidasEmuladas()
        self.a = Almacen.abrir(self.ruta, self.reloj)
        self.s1 = self.a.registrar_sensor(canal=C1, nombre="Sensor 1", modelo="Paracube Micro", mv_por_pct=10.0)
        self.s2 = self.a.registrar_sensor(canal=C2, nombre="Sensor 2", modelo="Paracube Micro", mv_por_pct=10.0)
        self.n = self.nuevo_nucleo()

    def tearDown(self) -> None:
        self.a.cerrar()
        self._tmp.cleanup()

    def nuevo_nucleo(self) -> Nucleo:
        return Nucleo(self.a, self.fuente, self.salidas, mono=lambda: self.t[0], version_sw="test")

    def correr(self, nucleo: Nucleo, segundos: float, paso_s: float = 0.5) -> None:
        fin = self.t[0] + segundos
        while self.t[0] < fin - 1e-9:
            self.t[0] += paso_s
            self.reloj.avanzar(int(paso_s * 1000))
            nucleo.paso()

    def lecturas(self, sensor_id: int):
        return self.a.db.execute("SELECT * FROM lectura WHERE sensor_id = ? ORDER BY id", (sensor_id,)).fetchall()

    def codigos_de_eventos(self) -> list[str]:
        return [f["codigo"] for f in self.a.db.execute("SELECT codigo FROM evento")]


class PruebasLecturas(BaseCiclo):
    def test_guarda_un_registro_por_sensor_cada_intervalo(self) -> None:
        self.n.iniciar()
        self.correr(self.n, 14.5)
        self.assertEqual(len(self.lecturas(self.s1)), 0)             # el intervalo (15 s) aun no termina
        self.correr(self.n, 0.5)
        for sensor in (self.s1, self.s2):
            filas = self.lecturas(sensor)
            self.assertEqual(len(filas), 1)
            f = filas[0]
            self.assertAlmostEqual(f["o2_prom"], 20.9)
            self.assertAlmostEqual(f["mv_prom"], 209.0)
            self.assertEqual((f["calidad"], f["periodo_ms"]), (0, 15000))
            self.assertEqual(f["n_muestras"], 30)

    def test_aplica_el_offset_de_la_calibracion_vigente(self) -> None:
        self.a.registrar_arranque(version_sw="t", so_boot_id="x")       # la calibracion necesita arranque
        self.a.registrar_calibracion(sensor_id=self.s1, tipo="offset_cero", origen="local", resultado="ok",
                                     offset_pct=0.1, vigente=True)
        self.n.iniciar()
        self.correr(self.n, 15)
        self.assertAlmostEqual(self.lecturas(self.s1)[0]["o2_prom"], 21.0)
        self.assertAlmostEqual(self.lecturas(self.s2)[0]["o2_prom"], 20.9)

    def test_el_registro_lleva_minimo_y_maximo(self) -> None:
        self.n.iniciar()
        self.fuente.tensiones[C1] = volts(20.0)
        self.correr(self.n, 7)
        self.fuente.tensiones[C1] = volts(22.0)
        self.correr(self.n, 8)
        f = self.lecturas(self.s1)[0]
        self.assertEqual((f["o2_min"], f["o2_max"]), (20.0, 22.0))
        self.assertTrue(20.0 < f["o2_prom"] < 22.0)

    def test_sin_señal_se_guarda_como_hueco_con_marca(self) -> None:
        self.fuente.tensiones[C2] = None
        self.n.iniciar()
        self.correr(self.n, 15)
        f = self.lecturas(self.s2)[0]
        self.assertEqual((f["n_muestras"], f["o2_prom"], f["calidad"]), (0, None, 32))
        self.assertEqual(self.n.estado_pantalla()["sensores"][1]["texto_o2"], "--.-")

    def test_cerrar_guarda_el_intervalo_en_curso(self) -> None:
        self.n.iniciar()
        self.correr(self.n, 6)
        self.n.cerrar()
        f = self.lecturas(self.s1)[0]
        self.assertEqual((f["n_muestras"], f["periodo_ms"]), (12, 6000))

    def test_la_cadena_de_auditoria_queda_integra(self) -> None:
        self.n.iniciar()
        self.fuente.tensiones[C1] = volts(15.0)
        self.correr(self.n, 40)
        self.assertEqual(auditoria.verificar(self.a.db), [])


class PruebasAlarmasEnElCiclo(BaseCiclo):
    def test_alarma_baja_activa_el_relevo_y_el_sonido_y_acusar_solo_silencia(self) -> None:
        self.n.iniciar()
        self.fuente.tensiones[C1] = volts(15.0)
        self.correr(self.n, 9.5)
        self.assertFalse(self.salidas.bajo)                         # aun en el retardo de 10 s
        self.correr(self.n, 1)
        estado = self.n.estado_pantalla()
        self.assertTrue(self.salidas.bajo and not self.salidas.alto)
        s1, s2 = estado["sensores"]
        self.assertEqual((s1["estado"], s1["acusada"], s1["texto_o2"]), ("BAJA", False, "15.0"))
        self.assertEqual(s2["estado"], "NORMAL")
        self.assertTrue(estado["sonar"] and estado["parpadeo"] and estado["rele_bajo"])
        self.assertTrue(estado["aviso"].startswith("S1 BAJO 15.0 %"))
        self.assertEqual(self.n.acusar("pantalla"), 2)              # la baja y la discrepancia entre sensores
        estado = self.n.estado_pantalla()
        self.assertFalse(estado["sonar"] or estado["parpadeo"])
        self.assertTrue(self.salidas.bajo)                          # el relevo sigue (D-031)
        self.assertEqual(estado["sensores"][0]["acusada"], True)

    def test_el_sonido_vuelve_a_los_dos_minutos(self) -> None:
        self.n.iniciar()
        self.fuente.tensiones[C1] = volts(15.0)
        self.correr(self.n, 11)
        self.n.acusar("pantalla")
        self.correr(self.n, 119)
        self.assertFalse(self.n.estado_pantalla()["sonar"])
        self.correr(self.n, 2)
        self.assertTrue(self.n.estado_pantalla()["sonar"])

    def test_cambiar_el_umbral_en_la_configuracion_rige_sin_reiniciar(self) -> None:
        self.n.iniciar()
        self.fuente.tensiones[C1] = volts(21.5)
        self.correr(self.n, 12)
        self.assertFalse(self.salidas.bajo)
        self.a.config_fijar("alarma.o2_bajo_pct", 22.0, origen="pantalla", actor="t")
        self.correr(self.n, 12)                                     # lo lee en el siguiente segundo
        self.assertTrue(self.salidas.bajo)

    def test_las_dos_alarmas_usan_cada_una_su_relevo(self) -> None:
        self.n.iniciar()
        self.fuente.tensiones[C1] = volts(15.0)
        self.fuente.tensiones[C2] = volts(95.0)
        self.correr(self.n, 11)
        self.assertTrue(self.salidas.bajo and self.salidas.alto)

    def test_sensor_deshabilitado_se_muestra_apagado_y_no_se_lee(self) -> None:
        self.a.registrar_arranque(version_sw="t", so_boot_id="x")
        self.a.fijar_sensor_habilitado(self.s2, False, origen="local")
        self.fuente.tensiones[C2] = volts(5.0)                      # si se leyera, abriria alarma
        self.n.iniciar()
        self.correr(self.n, 20)
        s1, s2 = self.n.estado_pantalla()["sensores"]
        self.assertEqual((s1["estado"], s2["estado"]), ("NORMAL", "APAGADO"))
        self.assertFalse(self.salidas.bajo)
        self.assertEqual(self.lecturas(self.s2), [])


class PruebasArranqueYCierre(BaseCiclo):
    def test_un_cierre_ordenado_se_reconoce_en_el_arranque_siguiente(self) -> None:
        self.assertTrue(self.n.iniciar())                           # primera vez: se considera ordenado
        self.n.cerrar()
        otro = self.nuevo_nucleo()
        self.assertTrue(otro.iniciar())
        razones = [f["razon"] for f in self.a.db.execute("SELECT razon FROM arranque ORDER BY id")]
        self.assertEqual(razones, ["SYS_ARRANQUE", "SYS_ARRANQUE"])
        self.assertNotIn("SYS_REINICIO_ANORMAL", self.codigos_de_eventos())

    def test_sin_cierre_ordenado_el_arranque_siguiente_lo_registra(self) -> None:
        self.n.iniciar()
        self.correr(self.n, 3)                                      # y el programa "se cae": sin cerrar()
        otro = self.nuevo_nucleo()
        self.assertFalse(otro.iniciar())
        razones = [f["razon"] for f in self.a.db.execute("SELECT razon FROM arranque ORDER BY id")]
        self.assertEqual(razones[-1], "SYS_REINICIO_ANORMAL")
        self.assertIn("SYS_REINICIO_ANORMAL", self.codigos_de_eventos())

    def test_las_alarmas_abiertas_se_retoman_al_reiniciar_sin_duplicarse(self) -> None:
        self.n.iniciar()
        self.fuente.tensiones[C1] = volts(15.0)
        self.correr(self.n, 11)
        abiertas = self.a.db.execute("SELECT COUNT(*) FROM alarma WHERE estado <> 'cerrada'").fetchone()[0]
        otro = self.nuevo_nucleo()
        otro.iniciar()
        self.correr(otro, 11)
        self.assertEqual(self.a.db.execute("SELECT COUNT(*) FROM alarma").fetchone()[0], abiertas)
        self.assertTrue(self.salidas.bajo)

    def test_ejecutar_repite_los_pasos_y_publica_el_estado(self) -> None:
        self.n.iniciar()
        publicados, pasos = [], [0]

        def detener() -> bool:
            return pasos[0] >= 6

        def dormir(s: float) -> None:
            self.t[0] += s
            pasos[0] += 1

        self.n.ejecutar(detener, periodo_s=0.5, dormir=dormir, al_publicar=publicados.append)
        self.assertEqual(pasos[0], 6)
        self.assertGreaterEqual(len(publicados), 3)                  # 1 s de intervalo de pantalla: 3 s simulados
        self.assertEqual(publicados[0]["aviso"], "Sin alarmas")


class PruebasOrdenesDeLaInterfaz(BaseCiclo):
    def alarma_baja_abierta(self) -> None:
        self.n.iniciar()
        self.fuente.tensiones[C1] = volts(15.0)
        self.correr(self.n, 11)

    def comandos(self):
        return self.a.db.execute("SELECT uuid, origen, tipo, estado, actor, resultado_json FROM comando "
                                 "ORDER BY id").fetchall()

    def test_acusar_se_registra_como_comando_y_silencia_el_sonido(self) -> None:
        self.alarma_baja_abierta()
        self.assertTrue(self.n.estado_pantalla()["sonar"])
        self.n.procesar_orden({"uuid": "u-1", "tipo": "acusar", "origen": "pantalla", "actor": "pantalla"})
        self.assertFalse(self.n.estado_pantalla()["sonar"])
        self.assertTrue(self.salidas.bajo)                                 # el relevo sigue (D-031)
        (c,) = self.comandos()
        self.assertEqual((c["uuid"], c["origen"], c["tipo"], c["estado"], c["actor"]),
                         ("u-1", "pantalla", "acusar", "ok", "pantalla"))
        self.assertIn('"acusadas": 2', c["resultado_json"])                # la baja y la discrepancia

    def test_la_misma_orden_dos_veces_se_ejecuta_una_sola(self) -> None:
        self.alarma_baja_abierta()
        orden = {"uuid": "u-2", "tipo": "acusar", "origen": "pantalla"}
        self.n.procesar_orden(orden)
        self.t[0] += 130                                                   # vuelve el sonido
        self.n.motor.evaluar({self.s1: 15.0, self.s2: 20.9}, self.n.umbrales, self.t[0])
        self.assertTrue(self.n.estado_pantalla()["sonar"])
        self.n.procesar_orden(orden)                                       # reenvio: no hace nada
        self.assertTrue(self.n.estado_pantalla()["sonar"])
        self.assertEqual(len(self.comandos()), 1)

    def test_una_orden_desconocida_se_rechaza_y_queda_registrada(self) -> None:
        self.n.iniciar()
        self.n.procesar_orden({"uuid": "u-3", "tipo": "apagar_todo", "origen": "pantalla"})
        (c,) = self.comandos()
        self.assertEqual((c["tipo"], c["estado"]), ("apagar_todo", "rechazado"))

    def test_ordenes_mal_formadas_o_con_origen_raro_no_rompen_nada(self) -> None:
        self.n.iniciar()
        self.n.procesar_orden({"tipo": "acusar"})                          # sin uuid
        self.n.procesar_orden("basura")                                    # ni siquiera es un diccionario
        self.n.procesar_orden({"uuid": "u-4", "tipo": "acusar", "origen": "internet"})
        (c,) = self.comandos()
        self.assertEqual(c["origen"], "local")                             # un origen no valido pasa a "local"

    def test_ejecutar_recibe_ordenes_y_publica_el_estado_de_inmediato(self) -> None:
        self.alarma_baja_abierta()
        publicados, pendientes, pasos = [], [[{"uuid": "u-5", "tipo": "acusar", "origen": "pantalla"}]], [0]

        def ordenes():
            return pendientes.pop(0) if pendientes else []

        def dormir(s: float) -> None:
            self.t[0] += s
            pasos[0] += 1

        # intervalo de pantalla 1 s: la publicacion normal solo ocurriria una vez por segundo
        self.n.ejecutar(lambda: pasos[0] >= 1, periodo_s=0.5, dormir=dormir,
                        al_publicar=publicados.append, ordenes=ordenes)
        self.assertEqual(len(publicados), 1)
        self.assertFalse(publicados[0]["sonar"])                           # ya con el acuse aplicado
        self.assertTrue(publicados[0]["sensores"][0]["acusada"])


class FuenteAdcDePrueba:
    """Doble del ADC: entrega lecturas o lanza errores segun se le pida."""

    def __init__(self) -> None:
        self.respuestas: list = []
        self.iniciado = 0

    def leer_diferencial(self, positiva, negativa, tiempo_max_s=1.0):
        from g2.hardware import ads1263 as A
        valor = self.respuestas.pop(0)
        if isinstance(valor, Exception):
            raise valor
        return A.Lectura(tension_v=valor, codigo=0, status=0, canal=(positiva, negativa), pga_activo=False)

    def iniciar(self) -> None:
        self.iniciado += 1


class PruebasFuenteAds1263(unittest.TestCase):
    def test_analiza_el_nombre_del_canal(self) -> None:
        self.assertEqual(analizar_canal("ads1263:0-1"), (0, 1))
        self.assertEqual(analizar_canal("ads1263:2-3"), (2, 3))
        for malo in ("0-1", "ads1115:0-1", "ads1263:a-b", "ads1263:01"):
            with self.assertRaises(ValueError):
                analizar_canal(malo)

    def test_un_error_del_adc_es_sin_señal_y_no_detiene_el_programa(self) -> None:
        from g2.hardware import ads1263 as A
        adc = FuenteAdcDePrueba()
        adc.respuestas = [0.2, A.ErrorTiempoAgotado("sin dato"), 0.21]
        fuente = FuenteAds1263(adc)
        self.assertEqual(fuente.leer(C1), 0.2)
        self.assertIsNone(fuente.leer(C1))
        self.assertIn("ErrorTiempoAgotado", fuente.ultimo_error)
        self.assertEqual(fuente.leer(C1), 0.21)
        self.assertIsNone(fuente.ultimo_error)

    def test_si_el_chip_se_reinicio_se_reconfigura(self) -> None:
        from g2.hardware import ads1263 as A
        adc = FuenteAdcDePrueba()
        adc.respuestas = [A.ErrorChipReiniciado("reinicio")]
        FuenteAds1263(adc).leer(C1)
        self.assertEqual(adc.iniciado, 1)

    def test_varios_errores_seguidos_reconfiguran_pero_no_mas_de_una_vez_cada_5_s(self) -> None:
        from g2.hardware import ads1263 as A
        reloj = [100.0]
        adc = FuenteAdcDePrueba()
        adc.respuestas = [A.ErrorChecksum("x")] * 8
        fuente = FuenteAds1263(adc, ahora=lambda: reloj[0])
        for _ in range(3):
            fuente.leer(C1)
        self.assertEqual(adc.iniciado, 1)                           # al tercer error seguido
        for _ in range(3):
            fuente.leer(C1)
        self.assertEqual(adc.iniciado, 1)                           # sigue fallando, pero espera
        reloj[0] += 6
        fuente.leer(C1)
        self.assertEqual(adc.iniciado, 2)


if __name__ == "__main__":
    unittest.main()
