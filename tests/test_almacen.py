"""Pruebas de la capa de acceso a datos (Almacen) contra una base real en un archivo temporal."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from g2.almacenamiento import auditoria, base
from g2.almacenamiento.almacen import Almacen, ErrorAlmacen
from g2.configuracion import catalogo
from g2.configuracion.catalogo import ErrorConfig
from g2.tiempo import RelojPrueba


class BaseAlmacen(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ruta = Path(self._tmp.name) / "datos" / "g2.db"        # la carpeta no existe aun
        self.reloj = RelojPrueba()
        self.a = Almacen.abrir(self.ruta, self.reloj)

    def tearDown(self) -> None:
        self.a.cerrar()
        self._tmp.cleanup()

    def arrancar(self, **extra) -> int:
        return self.a.registrar_arranque(version_sw="0.1.0-test", so_boot_id="so-1", **extra)

    def sensor(self, canal: str = "ads1263:0-1") -> int:
        return self.a.registrar_sensor(canal=canal, nombre="Sensor 1",
                                       modelo="Paracube Micro 01117707", mv_por_pct=10.0)

    def contar(self, tabla: str) -> int:
        return self.a.db.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]


class PruebasCreacion(BaseAlmacen):
    def test_crea_la_carpeta_el_esquema_y_siembra_la_configuracion(self) -> None:
        self.assertTrue(self.ruta.exists())
        self.assertEqual(self.contar("config"), len(catalogo.CLAVES))
        self.assertEqual(self.a.config_obtener("alarma.o2_alto_pct"), "92.0")
        self.assertEqual(self.a.config_tipada("muestreo.intervalo_pantalla_s"), 1)
        self.assertIs(self.a.config_tipada("sistema.apagado_limpio"), True)

    def test_abrir_otra_vez_no_duplica_ni_pisa_cambios(self) -> None:
        self.arrancar()
        self.a.config_fijar("alarma.o2_alto_pct", 95, origen="pantalla", actor="t")
        self.a.cerrar()
        self.a = Almacen.abrir(self.ruta, self.reloj)
        self.assertEqual(self.contar("config"), len(catalogo.CLAVES))
        self.assertEqual(self.a.config_obtener("alarma.o2_alto_pct"), "95.0")

    def test_sin_arranque_no_se_puede_escribir_datos(self) -> None:
        with self.assertRaises(ErrorAlmacen):
            self.a.registrar_salud(cpu_temp_c=45.0)


class PruebasArranque(BaseAlmacen):
    def test_cada_inicio_del_nucleo_deja_su_fila_con_numero_dentro_del_encendido(self) -> None:
        self.arrancar()
        self.a.registrar_arranque(version_sw="0.1.1", razon="SVC_REINICIADO", so_boot_id="so-1")
        self.a.registrar_arranque(version_sw="0.1.1", so_boot_id="so-2")
        ids = [f["boot_id"] for f in self.a.db.execute("SELECT boot_id FROM arranque ORDER BY id")]
        self.assertEqual(ids, ["so-1#1", "so-1#2", "so-2#1"])
        razon = self.a.db.execute("SELECT razon FROM arranque WHERE boot_id = 'so-1#2'").fetchone()[0]
        self.assertEqual(razon, "SVC_REINICIADO")

    def test_reloj_confiable_guarda_la_referencia_de_correccion(self) -> None:
        self.arrancar()
        f = self.a.db.execute("SELECT * FROM arranque").fetchone()
        self.assertEqual(f["inicio_confiable"], 1)
        self.assertEqual(f["sincronizado_utc_ms"], f["inicio_ms"])

    def test_reloj_no_confiable_se_sincroniza_despues(self) -> None:
        self.reloj.fijar_confiable(False)
        self.arrancar()
        f = self.a.db.execute("SELECT * FROM arranque").fetchone()
        self.assertEqual((f["inicio_confiable"], f["sincronizado_utc_ms"]), (0, None))
        self.reloj.avanzar(5000)
        self.reloj.fijar_confiable(True)
        self.assertTrue(self.a.marcar_reloj_sincronizado())
        self.assertFalse(self.a.marcar_reloj_sincronizado())              # ya estaba
        f = self.a.db.execute("SELECT * FROM arranque").fetchone()
        self.assertIsNotNone(f["sincronizado_utc_ms"])
        self.assertEqual(f["rev"], 2)                                      # quedo como revision nueva

    def test_marca_de_apagado_limpio(self) -> None:
        self.arrancar()
        self.assertTrue(self.a.iniciar_sesion())            # primera vez: se considera limpio
        self.assertFalse(self.a.iniciar_sesion())           # no hubo cerrar_limpio: cierre anormal
        self.a.cerrar_limpio()
        self.assertTrue(self.a.iniciar_sesion())

    def test_usar_ultimo_arranque(self) -> None:
        with self.assertRaises(ErrorAlmacen):
            self.a.usar_ultimo_arranque()
        esperado = self.arrancar()
        self.a._arranque_id = None
        self.assertEqual(self.a.usar_ultimo_arranque(), esperado)


class PruebasConfiguracionAlmacen(BaseAlmacen):
    def setUp(self) -> None:
        super().setUp()
        self.arrancar()

    def test_cambio_deja_historial_con_origen_y_autor(self) -> None:
        r = self.a.config_fijar("alarma.o2_bajo_pct", "18", origen="plataforma", actor="admin")
        self.assertEqual((r.valor, r.version, r.cambiado), ("18.0", 2, True))
        h = self.a.db.execute("SELECT * FROM config_historial").fetchone()
        self.assertEqual((h["clave"], h["valor_anterior"], h["valor_nuevo"], h["origen"], h["actor"]),
                         ("alarma.o2_bajo_pct", "20.0", "18.0", "plataforma", "admin"))
        self.assertEqual(self.a.config_listar()[0]["origen"] in ("plataforma", "defecto"), True)

    def test_mismo_valor_no_escribe_nada(self) -> None:
        antes = self.contar("config_historial")
        r = self.a.config_fijar("alarma.o2_bajo_pct", "20", origen="pantalla")
        self.assertFalse(r.cambiado)
        self.assertEqual((self.contar("config_historial"), r.version), (antes, 1))

    def test_valor_invalido_no_cambia_nada(self) -> None:
        with self.assertRaises(ErrorConfig):
            self.a.config_fijar("alarma.o2_bajo_pct", "150", origen="pantalla")
        self.assertEqual(self.a.config_obtener("alarma.o2_bajo_pct"), "20.0")
        self.assertEqual(self.contar("config_historial"), 0)

    def test_relacion_bajo_menor_que_alto(self) -> None:
        with self.assertRaises(ErrorConfig):
            self.a.config_fijar("alarma.o2_bajo_pct", 95, origen="pantalla")     # alto = 92
        with self.assertRaises(ErrorConfig):
            self.a.config_fijar("alarma.o2_alto_pct", 15, origen="plataforma")   # bajo = 20
        self.a.config_fijar("alarma.o2_alto_pct", 96, origen="plataforma")
        self.a.config_fijar("alarma.o2_bajo_pct", 95, origen="pantalla")         # ahora si cabe

    def test_origen_sin_permiso(self) -> None:
        with self.assertRaises(ErrorConfig):
            self.a.config_fijar("equipo.id", "ANZD-1", origen="plataforma")
        self.a.config_fijar("equipo.id", "G2-0001", origen="local", actor="tecnico")
        self.assertEqual(self.a.config_obtener("equipo.id"), "G2-0001")

    def test_clave_desconocida(self) -> None:
        with self.assertRaises(ErrorConfig):
            self.a.config_fijar("inventada", 1, origen="local")


class PruebasLecturasYSalud(BaseAlmacen):
    def setUp(self) -> None:
        super().setUp()
        self.arrancar()
        self.s = self.sensor()

    def test_lectura_toma_la_calibracion_vigente(self) -> None:
        sin = self.a.insertar_lectura(sensor_id=self.s, periodo_ms=15000, n_muestras=150,
                                      o2_prom=20.9, o2_min=20.8, o2_max=21.0, mv_prom=209.0)
        cal = self.a.registrar_calibracion(sensor_id=self.s, tipo="offset_cero", origen="pantalla",
                                           resultado="ok", vigente=True, gas_pct=20.9, actor="t")
        con = self.a.insertar_lectura(sensor_id=self.s, periodo_ms=15000, n_muestras=150,
                                      o2_prom=20.9, o2_min=20.8, o2_max=21.0, mv_prom=209.0)
        filas = {f["id"]: f["calibracion_id"] for f in self.a.db.execute("SELECT id, calibracion_id FROM lectura")}
        self.assertEqual((filas[sin], filas[con]), (None, cal))

    def test_lectura_sin_muestras_guarda_el_hueco_como_nulos(self) -> None:
        self.a.insertar_lectura(sensor_id=self.s, periodo_ms=15000, n_muestras=0, o2_prom=None,
                                o2_min=None, o2_max=None, mv_prom=None, calidad=32)

    def test_lectura_se_encola_para_la_plataforma(self) -> None:
        rid = self.a.insertar_lectura(sensor_id=self.s, periodo_ms=15000, n_muestras=5,
                                      o2_prom=1.0, o2_min=1.0, o2_max=1.0, mv_prom=10.0)
        q = self.a.db.execute("SELECT estado FROM cola_envio WHERE tabla = 'lectura' AND registro_id = ?",
                              (rid,)).fetchone()
        self.assertEqual(q["estado"], "pendiente")

    def test_el_tiempo_viene_del_reloj_y_marca_la_confiabilidad(self) -> None:
        self.reloj.fijar_confiable(False)
        rid = self.a.insertar_lectura(sensor_id=self.s, periodo_ms=15000, n_muestras=5,
                                      o2_prom=1.0, o2_min=1.0, o2_max=1.0, mv_prom=10.0)
        f = self.a.db.execute("SELECT * FROM lectura WHERE id = ?", (rid,)).fetchone()
        self.assertEqual((f["ts_ms"], f["ts_confiable"], f["mono_ms"]),
                         (self.reloj.ahora_ms(), 0, self.reloj.mono_ms()))

    def test_salud_periodica_y_por_alarma(self) -> None:
        self.a.registrar_salud(cpu_temp_c=48.0, mem_pct=40.0, disco_pct=42.0)
        self.a.registrar_salud(motivo="ALM_RPI_TEMP_ALTA", cpu_temp_c=61.0)
        motivos = [f[0] for f in self.a.db.execute("SELECT motivo FROM salud ORDER BY id")]
        self.assertEqual(motivos, ["SYS_SALUD_PERIODICA", "ALM_RPI_TEMP_ALTA"])
        with self.assertRaises(ErrorAlmacen):
            self.a.registrar_salud(campo_inventado=1)

    def test_sensor_duplicado_se_rechaza(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.sensor()

    def test_serie_del_sensor(self) -> None:
        self.a.fijar_serie_sensor(self.s, " 01117707500032 ")
        self.assertEqual(self.a.listar_sensores()[0]["serie_etiqueta"], "01117707500032")
        with self.assertRaises(ErrorAlmacen):
            self.a.fijar_serie_sensor(999, "x")

    def test_habilitar_y_deshabilitar_un_sensor_deja_evento(self) -> None:
        self.assertTrue(self.a.fijar_sensor_habilitado(self.s, False, origen="pantalla", actor="t"))
        self.assertFalse(self.a.fijar_sensor_habilitado(self.s, False, origen="pantalla"))
        self.assertTrue(self.a.fijar_sensor_habilitado(self.s, True, origen="plataforma"))
        codigos = [f[0] for f in self.a.db.execute("SELECT codigo FROM evento ORDER BY id")]
        self.assertEqual(codigos, ["SEN_DESHABILITADO", "SEN_HABILITADO"])
        with self.assertRaises(ErrorAlmacen):
            self.a.fijar_sensor_habilitado(999, True, origen="pantalla")


class PruebasEventos(BaseAlmacen):
    def setUp(self) -> None:
        super().setUp()
        self.arrancar()

    def test_eventos_iguales_cercanos_se_agrupan(self) -> None:
        a = self.a.registrar_evento("NET_DESCONECTADA", "uplink.red")
        self.reloj.avanzar(10_000)
        b = self.a.registrar_evento("NET_DESCONECTADA", "uplink.red")
        self.reloj.avanzar(10_000)
        c = self.a.registrar_evento("NET_DESCONECTADA", "uplink.red")
        self.assertEqual((a, b, c), (a, a, a))
        f = self.a.db.execute("SELECT repeticiones, ultimo_ms, rev FROM evento").fetchone()
        self.assertEqual(f["repeticiones"], 3)
        self.assertEqual(f["ultimo_ms"], self.reloj.ahora_ms())
        self.assertGreaterEqual(f["rev"], 2)

    def test_pasada_la_ventana_se_crea_otro(self) -> None:
        a = self.a.registrar_evento("NET_DESCONECTADA", "uplink.red")
        self.reloj.avanzar(61_000)
        self.assertNotEqual(self.a.registrar_evento("NET_DESCONECTADA", "uplink.red"), a)

    def test_distinto_sensor_u_origen_no_se_agrupa(self) -> None:
        s = self.sensor()
        a = self.a.registrar_evento("SEN_FALLA", "core.adc", sensor_id=s)
        self.assertNotEqual(self.a.registrar_evento("SEN_FALLA", "core.adc"), a)
        self.assertNotEqual(self.a.registrar_evento("SEN_FALLA", "otro", sensor_id=s), a)

    def test_codigo_fuera_del_catalogo(self) -> None:
        with self.assertRaises(ErrorAlmacen):
            self.a.registrar_evento("NO_EXISTE", "x")

    def test_datos_se_guardan_como_json(self) -> None:
        self.a.registrar_evento("SYS_AUTODIAGNOSTICO", "core", datos={"adc": "ok", "n": 2})
        crudo = self.a.db.execute("SELECT datos_json FROM evento").fetchone()[0]
        self.assertEqual(json.loads(crudo), {"adc": "ok", "n": 2})


class PruebasAlarmas(BaseAlmacen):
    def setUp(self) -> None:
        super().setUp()
        self.arrancar()
        self.s = self.sensor()

    def test_ciclo_de_vida_completo(self) -> None:
        aid = self.a.abrir_alarma("ALM_O2_ALTO", sensor_id=self.s, umbral=92.0, valor=92.4)
        self.assertEqual(self.a.alarma_activa("ALM_O2_ALTO", self.s), aid)
        self.assertTrue(self.a.actualizar_pico(aid, 93.1))
        self.assertTrue(self.a.acusar_alarma(aid, "enfermera"))
        self.assertFalse(self.a.acusar_alarma(aid, "otra"))             # ya acusada
        self.reloj.avanzar(60_000)
        self.assertTrue(self.a.cerrar_alarma(aid))
        self.assertFalse(self.a.cerrar_alarma(aid))
        f = self.a.db.execute("SELECT * FROM alarma WHERE id = ?", (aid,)).fetchone()
        self.assertEqual((f["estado"], f["valor_pico"], f["acuse_actor"]), ("cerrada", 93.1, "enfermera"))
        self.assertEqual(f["fin_ms"], self.reloj.ahora_ms())
        self.assertIsNone(self.a.alarma_activa("ALM_O2_ALTO", self.s))

    def test_no_duplica_una_alarma_abierta(self) -> None:
        a = self.a.abrir_alarma("ALM_O2_BAJO", sensor_id=self.s, valor=19.0)
        self.assertEqual(self.a.abrir_alarma("ALM_O2_BAJO", sensor_id=self.s, valor=18.0), a)
        self.assertEqual(self.contar("alarma"), 1)

    def test_alarmas_de_sensores_distintos_son_independientes(self) -> None:
        s2 = self.sensor("ads1263:2-3")
        a = self.a.abrir_alarma("ALM_O2_BAJO", sensor_id=self.s, valor=19.0)
        b = self.a.abrir_alarma("ALM_O2_BAJO", sensor_id=s2, valor=19.0)
        self.assertNotEqual(a, b)

    def test_actualizar_pico_igual_no_genera_revision(self) -> None:
        aid = self.a.abrir_alarma("ALM_O2_ALTO", sensor_id=self.s, valor=93.0)
        rev = self.a.db.execute("SELECT rev FROM alarma WHERE id = ?", (aid,)).fetchone()[0]
        self.assertFalse(self.a.actualizar_pico(aid, 93.0))
        self.assertEqual(self.a.db.execute("SELECT rev FROM alarma WHERE id = ?", (aid,)).fetchone()[0], rev)

    def test_codigo_que_no_es_alarma(self) -> None:
        with self.assertRaises(sqlite3.DatabaseError):
            self.a.abrir_alarma("NET_CONECTADA")

    def test_alarma_inexistente(self) -> None:
        with self.assertRaises(ErrorAlmacen):
            self.a.acusar_alarma(999, "x")


class PruebasComandos(BaseAlmacen):
    def setUp(self) -> None:
        super().setUp()
        self.arrancar()

    def test_comando_es_idempotente_por_uuid(self) -> None:
        cid, nuevo = self.a.registrar_comando(uuid_comando="u-1", origen="plataforma",
                                              tipo="deshabilitar_sensor", parametros={"sensor": 1})
        self.assertTrue(nuevo)
        self.assertEqual(self.a.registrar_comando(uuid_comando="u-1", origen="plataforma",
                                                  tipo="deshabilitar_sensor"), (cid, False))
        self.a.finalizar_comando(cid, "ok", {"detalle": "listo"})
        f = self.a.db.execute("SELECT estado, resultado_json FROM comando").fetchone()
        self.assertEqual((f["estado"], json.loads(f["resultado_json"])), ("ok", {"detalle": "listo"}))
        with self.assertRaises(ErrorAlmacen):
            self.a.finalizar_comando(cid, "recibido")


class PruebasEstadoYAuditoria(BaseAlmacen):
    def test_estado_resume_la_base(self) -> None:
        self.arrancar()
        s = self.sensor()
        self.a.insertar_lectura(sensor_id=s, periodo_ms=15000, n_muestras=1, o2_prom=1.0,
                                o2_min=1.0, o2_max=1.0, mv_prom=10.0)
        self.a.abrir_alarma("ALM_O2_BAJO", sensor_id=s, valor=19.0)
        e = self.a.estado()
        self.assertEqual(e["version_esquema"], 4)
        self.assertEqual((e["filas"]["lectura"], e["filas"]["arranque"]), (1, 1))
        self.assertEqual(e["alarmas_abiertas"], 1)
        self.assertGreater(e["pendientes_envio"], 0)
        self.assertEqual(e["ultimo_arranque"]["boot_id"], "so-1#1")
        self.assertGreater(e["bytes"], 0)

    def test_la_cadena_de_auditoria_queda_coherente_tras_un_uso_completo(self) -> None:
        self.arrancar()
        s = self.sensor()
        self.a.config_fijar("alarma.o2_alto_pct", 95, origen="plataforma", actor="admin")
        aid = self.a.abrir_alarma("ALM_O2_ALTO", sensor_id=s, valor=96.0)
        self.a.acusar_alarma(aid, "x")
        self.a.cerrar_alarma(aid)
        self.a.registrar_evento("NET_DESCONECTADA", "uplink.red")
        self.a.registrar_evento("NET_DESCONECTADA", "uplink.red")
        self.a.registrar_calibracion(sensor_id=s, tipo="offset_cero", origen="pantalla",
                                     resultado="ok", vigente=True)
        self.a.registrar_comando(uuid_comando="u", origen="local", tipo="x")
        self.assertEqual(auditoria.verificar(self.a.db), [])
        lectura = base.abrir_lectura(self.ruta)
        try:
            self.assertEqual(auditoria.verificar(lectura), [])
        finally:
            lectura.close()

    def test_una_escritura_que_falla_no_deja_nada_a_medias(self) -> None:
        self.arrancar()
        antes = self.contar("config_historial")
        with self.assertRaises(sqlite3.DatabaseError):
            with self.a._transaccion():
                self.a._insertar("config_historial", {
                    **self.a._tiempo(), "clave": "x", "valor_nuevo": "1", "version": 1,
                    "origen": "origen_invalido"})
        self.assertEqual(self.contar("config_historial"), antes)
        self.assertFalse(self.a.db.in_transaction)


if __name__ == "__main__":
    unittest.main()
