"""Pruebas de la salud de la Pi (g2.nucleo.salud) y de las ordenes de sistema del nucleo (D-039)."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from g2.almacenamiento.almacen import Almacen
from g2.nucleo.fuentes import FuenteSimulada
from g2.nucleo.nucleo import Nucleo
from g2.nucleo.salud import (ALM_DISCO_BAJO, ALM_DISCO_CRITICO, ALM_RAM, ALM_TEMP, ALM_VOLTAJE, MUESTREO_S,
                             RETARDO_S, Medicion, MedidorLinux, ObservadorSalud)
from g2.tiempo import RelojPrueba

C1, C2 = "ads1263:0-1", "ads1263:2-3"
NORMAL = Medicion(cpu_temp_c=45.0, cpu_pct=10.0, mem_pct=40.0, disco_pct=30.0, disco_libre_gb=20.0,
                  throttled="0x0", red_ok=True, wifi_rssi_dbm=-55, uptime_s=1000.0, db_bytes=500_000)


class MedidorFalso:
    def __init__(self, medicion: Medicion = NORMAL) -> None:
        self.medicion = medicion
        self.llamadas = 0

    def medir(self) -> Medicion:
        self.llamadas += 1
        return self.medicion


class BaseSalud(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.a = Almacen.abrir(Path(self._tmp.name) / "g2.db", RelojPrueba())
        self.a.registrar_arranque(version_sw="test", so_boot_id="so-1")
        self.medidor = MedidorFalso()
        self.obs = ObservadorSalud(self.a, self.medidor)

    def tearDown(self) -> None:
        self.a.cerrar()
        self._tmp.cleanup()

    def correr(self, desde: float, hasta: float, paso: float = MUESTREO_S) -> None:
        t = desde
        while t <= hasta:
            self.obs.paso(t)
            t += paso

    def alarma(self, codigo: str):
        return self.a.db.execute("SELECT * FROM alarma WHERE codigo = ? ORDER BY id DESC LIMIT 1",
                                 (codigo,)).fetchone()

    def filas_de_salud(self):
        return self.a.db.execute("SELECT * FROM salud ORDER BY id").fetchall()


class PruebasRegistro(BaseSalud):
    def test_registra_una_fila_al_arrancar_y_otra_cada_30_minutos(self) -> None:
        self.correr(0, 1790)
        self.assertEqual(len(self.filas_de_salud()), 1)
        self.correr(1800, 1800)
        self.assertEqual(len(self.filas_de_salud()), 2)
        self.correr(1810, 3590)
        self.assertEqual(len(self.filas_de_salud()), 2)
        self.correr(3600, 3600)
        self.assertEqual(len(self.filas_de_salud()), 3)

    def test_la_fila_lleva_las_mediciones_y_nunca_ceros_inventados(self) -> None:
        self.medidor.medicion = Medicion(cpu_temp_c=47.5, mem_pct=40.0, red_ok=False)    # lo demas no se pudo medir
        self.correr(0, 0)
        (f,) = self.filas_de_salud()
        self.assertEqual((f["cpu_temp_c"], f["mem_pct"], f["red_ok"], f["motivo"]), (47.5, 40.0, 0, "SYS_SALUD_PERIODICA"))
        self.assertIsNone(f["cpu_pct"])
        self.assertIsNone(f["wifi_rssi_dbm"])

    def test_no_mide_mas_de_una_vez_cada_10_segundos(self) -> None:
        for t in (0, 1, 2, 5, 9.9):
            self.obs.paso(t)
        self.assertEqual(self.medidor.llamadas, 1)
        self.obs.paso(10)
        self.assertEqual(self.medidor.llamadas, 2)

    def test_el_intervalo_sale_de_la_configuracion(self) -> None:
        self.a.config_fijar("salud.intervalo_min", 1, origen="local")
        self.correr(0, 70)
        self.assertEqual(len(self.filas_de_salud()), 2)


class PruebasAlarmasDeSalud(BaseSalud):
    def con(self, **cambios) -> None:
        self.medidor.medicion = replace(NORMAL, **cambios)

    def test_temperatura_alta_espera_el_retardo_y_cierra_con_histeresis(self) -> None:
        self.con(cpu_temp_c=63.0)                                          # el umbral es 60
        self.correr(0, RETARDO_S - 10)
        self.assertIsNone(self.alarma(ALM_TEMP))
        self.correr(RETARDO_S, RETARDO_S)
        fila = self.alarma(ALM_TEMP)
        self.assertEqual((fila["estado"], fila["umbral"], fila["valor_disparo"]), ("activa", 60.0, 63.0))
        self.assertIsNone(fila["sensor_id"])
        self.con(cpu_temp_c=57.0)                                          # bajo el umbral pero no 5 grados
        self.correr(40, 50)
        self.assertEqual(self.alarma(ALM_TEMP)["estado"], "activa")
        self.con(cpu_temp_c=55.0)
        self.correr(60, 60)
        self.assertEqual(self.alarma(ALM_TEMP)["estado"], "cerrada")

    def test_una_alarma_deja_una_fila_de_salud_con_la_causa(self) -> None:
        self.con(cpu_temp_c=70.0)
        self.correr(0, 40)
        motivos = [f["motivo"] for f in self.filas_de_salud()]
        self.assertEqual(motivos, ["SYS_SALUD_PERIODICA", ALM_TEMP])

    def test_ram_alta(self) -> None:
        self.con(mem_pct=90.0)                                              # el umbral es 85
        self.correr(0, 40)
        self.assertEqual(self.alarma(ALM_RAM)["estado"], "activa")

    def test_disco_bajo_y_critico_son_alarmas_distintas(self) -> None:
        self.con(disco_pct=85.0, disco_libre_gb=5.0)                        # 15 % libre: bajo el aviso (20 %), no el critico (10 %)
        self.correr(0, 40)
        self.assertEqual(self.alarma(ALM_DISCO_BAJO)["estado"], "activa")
        self.assertIsNone(self.alarma(ALM_DISCO_CRITICO))
        self.con(disco_pct=95.0, disco_libre_gb=0.5)
        self.correr(50, 90)
        self.assertEqual(self.alarma(ALM_DISCO_CRITICO)["estado"], "activa")

    def test_poco_espacio_en_gb_alarma_aunque_el_porcentaje_sea_alto(self) -> None:
        self.con(disco_pct=50.0, disco_libre_gb=1.5)                        # 50 % libre, pero menos de 2 GB
        self.correr(0, 40)
        self.assertEqual(self.alarma(ALM_DISCO_BAJO)["estado"], "activa")

    def test_bajo_voltaje_detectado_ahora(self) -> None:
        self.con(throttled="0x50005")                                       # bit 0: voltaje bajo ahora
        self.correr(0, 40)
        self.assertEqual(self.alarma(ALM_VOLTAJE)["estado"], "activa")

    def test_un_bajo_voltaje_pasado_no_alarma(self) -> None:
        self.con(throttled="0x50000")                                       # solo ocurrio antes (bits 16 y 18)
        self.correr(0, 60)
        self.assertIsNone(self.alarma(ALM_VOLTAJE))

    def test_lo_que_no_se_pudo_medir_no_alarma(self) -> None:
        self.medidor.medicion = Medicion()
        self.correr(0, 100)
        self.assertEqual(self.a.db.execute("SELECT COUNT(*) FROM alarma").fetchone()[0], 0)

    def test_tras_un_reinicio_se_retoman_las_alarmas_abiertas_sin_duplicar(self) -> None:
        self.con(cpu_temp_c=70.0)
        self.correr(0, 40)
        otro = ObservadorSalud(self.a, self.medidor)
        self.assertEqual(otro.recuperar(), 1)
        for t in range(0, 100, 10):
            otro.paso(float(t))
        self.assertEqual(self.a.db.execute("SELECT COUNT(*) FROM alarma WHERE codigo = ?", (ALM_TEMP,)).fetchone()[0], 1)
        self.assertEqual(otro.etiquetas_activas(), ["PI TEMP ALTA"])


class PruebasMedidorLinux(unittest.TestCase):
    def test_medir_nunca_falla_aunque_falte_algo(self) -> None:
        m = MedidorLinux().medir()                                          # en un PC faltan /sys y vcgencmd
        self.assertIsInstance(m, Medicion)
        if m.cpu_temp_c is not None:
            self.assertTrue(0 < m.cpu_temp_c < 110)
        if m.mem_pct is not None:
            self.assertTrue(0 <= m.mem_pct <= 100)
        if m.disco_pct is not None:
            self.assertTrue(0 <= m.disco_pct <= 100)

    def test_la_base_no_recibe_campos_sin_medir(self) -> None:
        self.assertEqual(Medicion(cpu_temp_c=40.0).para_la_base(), {"cpu_temp_c": 40.0})
        self.assertEqual(Medicion(red_ok=False, uptime_s=12.7).para_la_base(), {"red_ok": 0, "uptime_s": 12})


class PruebasNucleoConSalud(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.a = Almacen.abrir(Path(self._tmp.name) / "g2.db", RelojPrueba())
        self.s1 = self.a.registrar_sensor(canal=C1, nombre="Sensor 1", modelo="P", mv_por_pct=10.0)
        self.s2 = self.a.registrar_sensor(canal=C2, nombre="Sensor 2", modelo="P", mv_por_pct=10.0)
        self.t = [0.0]
        self.fuente = FuenteSimulada({C1: 0.209, C2: 0.209})
        self.medidor = MedidorFalso()
        self.lanzados: list[list[str]] = []
        self.n = Nucleo(self.a, self.fuente, mono=lambda: self.t[0], medidor=self.medidor,
                        ejecutor=self.lanzados.append)
        self.n.iniciar()

    def tearDown(self) -> None:
        self.a.cerrar()
        self._tmp.cleanup()

    def correr(self, segundos: float) -> None:
        fin = self.t[0] + segundos
        while self.t[0] < fin - 1e-9:
            self.t[0] += 0.5
            self.n.paso()

    def orden(self, uuid: str, tipo: str, **datos) -> None:
        self.n.procesar_orden({"uuid": uuid, "tipo": tipo, "origen": "pantalla", "actor": "pantalla", **datos})

    def comandos(self):
        return self.a.db.execute("SELECT tipo, estado, resultado_json FROM comando ORDER BY id").fetchall()

    def eventos(self, codigo: str):
        return self.a.db.execute("SELECT * FROM evento WHERE codigo = ?", (codigo,)).fetchall()

    # ---- salud en el estado publicado ----
    def test_el_estado_publicado_lleva_la_salud_y_la_version(self) -> None:
        self.correr(11)
        estado = self.n.estado_pantalla()
        self.assertEqual(estado["salud"]["cpu_temp_c"], 45.0)
        self.assertEqual(estado["version_sw"], "0.1.0-dev")
        self.assertEqual(estado["alertas_salud"], [])
        json.dumps(estado)                                                    # se puede publicar como JSON

    def test_las_alarmas_de_la_pi_salen_en_el_aviso_pero_no_suenan_ni_mueven_relevos(self) -> None:
        self.medidor.medicion = replace(NORMAL, cpu_temp_c=70.0)
        self.correr(45)
        estado = self.n.estado_pantalla()
        self.assertEqual(estado["aviso"], "PI TEMP ALTA")
        self.assertEqual(estado["alertas_salud"], [ALM_TEMP])
        self.assertFalse(estado["sonar"] or estado["rele_bajo"] or estado["rele_alto"])

    def test_el_aviso_junta_las_alarmas_de_oxigeno_y_las_de_la_pi(self) -> None:
        self.medidor.medicion = replace(NORMAL, cpu_temp_c=70.0)
        self.fuente.tensiones[C1] = 0.15
        self.correr(45)
        aviso = self.n.estado_pantalla()["aviso"]
        self.assertTrue(aviso.startswith("S1 BAJO"))
        self.assertTrue(aviso.endswith("PI TEMP ALTA"))
        self.assertLessEqual(len(aviso), 60)

    def test_sin_medidor_no_hay_salud(self) -> None:
        n = Nucleo(self.a, self.fuente, mono=lambda: self.t[0])
        n.iniciar()
        self.assertIsNone(n.estado_pantalla()["salud"])

    # ---- habilitar sensores ----
    def test_apagar_un_sensor_lo_deja_apagado_y_se_registra(self) -> None:
        self.correr(7)
        self.orden("h1", "sensor_habilitar", sensor_id=self.s2, habilitado=False)
        s1, s2 = self.n.estado_pantalla()["sensores"]
        self.assertEqual((s1["estado"], s2["estado"]), ("NORMAL", "APAGADO"))
        self.assertEqual(len(self.eventos("SEN_DESHABILITADO")), 1)
        self.assertEqual(self.comandos()[-1]["estado"], "ok")
        lecturas = self.a.db.execute("SELECT sensor_id FROM lectura").fetchall()
        self.assertEqual({f["sensor_id"] for f in lecturas}, {self.s1, self.s2})      # las muestras del apagado se guardaron

    def test_nunca_se_apaga_el_ultimo_sensor(self) -> None:
        self.orden("h1", "sensor_habilitar", sensor_id=self.s2, habilitado=False)
        self.orden("h2", "sensor_habilitar", sensor_id=self.s1, habilitado=False)
        self.assertEqual([c["estado"] for c in self.comandos()], ["ok", "rechazado"])
        self.assertIn("al menos un sensor", self.comandos()[1]["resultado_json"])
        self.assertEqual(self.n.estado_pantalla()["sensores"][0]["estado"], "NORMAL")

    def test_volver_a_encender_un_sensor(self) -> None:
        self.orden("h1", "sensor_habilitar", sensor_id=self.s2, habilitado=False)
        self.orden("h2", "sensor_habilitar", sensor_id=self.s2, habilitado=True)
        self.correr(2)
        self.assertEqual(self.n.estado_pantalla()["sensores"][1]["estado"], "NORMAL")

    def test_ordenes_de_sensor_invalidas_se_rechazan(self) -> None:
        self.orden("h1", "sensor_habilitar", sensor_id=99, habilitado=False)
        self.orden("h2", "sensor_habilitar", sensor_id=self.s2, habilitado="no")
        self.orden("h3", "sensor_habilitar", sensor_id="2", habilitado=False)
        self.assertEqual([c["estado"] for c in self.comandos()], ["rechazado"] * 3)

    def test_apagar_un_sensor_en_alarma_cierra_su_alarma(self) -> None:
        self.fuente.tensiones[C2] = 0.15
        self.correr(12)
        self.assertTrue(self.n.estado_pantalla()["rele_bajo"])
        self.orden("h1", "sensor_habilitar", sensor_id=self.s2, habilitado=False)
        self.correr(1)
        self.assertFalse(self.n.estado_pantalla()["rele_bajo"])

    # ---- acciones del sistema ----
    def test_reiniciar_servicios_registra_el_evento_y_lanza_el_comando(self) -> None:
        self.orden("a1", "sistema_accion", accion="reiniciar_servicios")
        self.assertEqual(self.lanzados, [["systemctl", "--no-block", "restart", "g2-ui.service", "g2-core.service"]])
        self.assertEqual(self.lanzados[0][-1], "g2-core.service")           # el nucleo va ultimo: ver ACCIONES_DEL_SISTEMA
        self.assertEqual(len(self.eventos("SYS_REINICIO_PEDIDO")), 1)
        self.assertEqual(self.comandos()[-1]["estado"], "ok")

    def test_reiniciar_el_equipo(self) -> None:
        self.orden("a1", "sistema_accion", accion="reiniciar_equipo")
        self.assertEqual(self.lanzados, [["systemctl", "reboot"]])

    def test_una_accion_desconocida_no_se_ejecuta_y_nada_de_la_orden_se_toma_como_comando(self) -> None:
        self.orden("a1", "sistema_accion", accion="rm -rf /")
        self.orden("a2", "sistema_accion", accion="apagar_equipo", comando=["shutdown", "-h", "now"])
        self.orden("a3", "sistema_accion")
        self.assertEqual(self.lanzados, [])
        self.assertEqual([c["estado"] for c in self.comandos()], ["rechazado"] * 3)

    def test_la_misma_orden_de_reinicio_no_se_ejecuta_dos_veces(self) -> None:
        self.orden("a1", "sistema_accion", accion="reiniciar_servicios")
        self.orden("a1", "sistema_accion", accion="reiniciar_servicios")
        self.assertEqual(len(self.lanzados), 1)

    # ---- resultado de la auditoria ----
    def test_el_resultado_de_la_verificacion_queda_como_evento(self) -> None:
        self.orden("v1", "auditoria_resultado", correcta=True)
        self.orden("v2", "auditoria_resultado", correcta=False, diferencias=3)
        self.assertEqual(len(self.eventos("SEG_AUDITORIA_VERIFICADA")), 1)
        (alterada,) = self.eventos("SEG_AUDITORIA_ALTERADA")
        self.assertEqual(json.loads(alterada["datos_json"]), {"diferencias": 3})
        self.assertEqual(alterada["severidad"], 4)

    def test_un_resultado_de_auditoria_invalido_se_rechaza(self) -> None:
        self.orden("v1", "auditoria_resultado", correcta="si")
        self.assertEqual(self.comandos()[-1]["estado"], "rechazado")


if __name__ == "__main__":
    unittest.main()
