"""Pruebas del esquema de la base de datos interna (decisiones D-007 a D-010).

Cada prueba verifica una regla que el esquema debe hacer cumplir por si mismo,
sin depender de que el codigo de la aplicacion se comporte bien. Ejecutar con:

    set PYTHONPATH=src            (Windows)   /   export PYTHONPATH=src  (Linux)
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from g2.almacenamiento import base, migraciones


class BasePruebas(unittest.TestCase):
    """Crea una base temporal con todas las migraciones y datos minimos."""

    def setUp(self) -> None:
        self._carpeta = tempfile.TemporaryDirectory()
        self.ruta = Path(self._carpeta.name) / "g2.db"
        self.db = base.abrir_escritura(self.ruta)
        migraciones.migrar(self.db)
        # Datos minimos de los que dependen casi todas las tablas.
        self.db.execute(
            "INSERT INTO arranque (id, boot_id, inicio_ms, inicio_confiable, version_sw)"
            " VALUES (1, 'boot-1', 1000, 1, '0.0.0')"
        )
        self.db.execute(
            "INSERT INTO sensor (id, canal, nombre, modelo, mv_por_pct)"
            " VALUES (1, 'ads1115:0x48:diff0-1', 'Sensor 1', 'Paracube Micro 01117707', 10.0)"
        )

    def tearDown(self) -> None:
        self.db.close()
        self._carpeta.cleanup()

    # -- ayudas ---------------------------------------------------------------
    def lectura(self, **cambios) -> int:
        """Inserta una lectura valida (con los cambios indicados) y devuelve su id."""
        datos = dict(
            ts_ms=2000, ts_confiable=1, arranque_id=1, mono_ms=1000, sensor_id=1,
            periodo_ms=15000, n_muestras=75, o2_prom=20.9, o2_min=20.8, o2_max=21.0,
            mv_prom=209.0, calidad=0,
        )
        datos.update(cambios)
        columnas = ", ".join(datos)
        marcas = ", ".join("?" for _ in datos)
        cursor = self.db.execute(
            f"INSERT INTO lectura ({columnas}) VALUES ({marcas})", tuple(datos.values())
        )
        return cursor.lastrowid

    def alarma(self, **cambios) -> int:
        datos = dict(
            codigo="ALM_O2_ALTO", severidad=3, sensor_id=1, inicio_ms=3000,
            inicio_confiable=1, arranque_id=1, mono_ms=2000, umbral=22.0,
            valor_disparo=22.5, actualizado_ms=3000,
        )
        datos.update(cambios)
        columnas = ", ".join(datos)
        marcas = ", ".join("?" for _ in datos)
        cursor = self.db.execute(
            f"INSERT INTO alarma ({columnas}) VALUES ({marcas})", tuple(datos.values())
        )
        return cursor.lastrowid

    def cola(self, tabla: str, registro_id: int) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM cola_envio WHERE tabla = ? AND registro_id = ? ORDER BY rev",
            (tabla, registro_id),
        ).fetchall()

    def confirmar(self, tabla: str, registro_id: int) -> None:
        self.db.execute(
            "UPDATE cola_envio SET estado = 'confirmado', confirmado_ms = 9999"
            " WHERE tabla = ? AND registro_id = ?",
            (tabla, registro_id),
        )


class PruebasMigraciones(BasePruebas):
    def test_version_final_y_registro(self) -> None:
        self.assertEqual(migraciones.version_actual(self.db), 4)
        versiones = [f["version"] for f in self.db.execute("SELECT version FROM esquema_version")]
        self.assertEqual(versiones, [1, 2, 3, 4])

    def test_migrar_dos_veces_no_cambia_nada(self) -> None:
        self.assertEqual(migraciones.migrar(self.db), 4)
        cantidad = self.db.execute("SELECT COUNT(*) FROM esquema_version").fetchone()[0]
        self.assertEqual(cantidad, 4)

    def test_rechaza_base_mas_nueva_que_el_codigo(self) -> None:
        self.db.execute("PRAGMA user_version = 99")
        with self.assertRaises(migraciones.ErrorMigracion):
            migraciones.migrar(self.db)

    def test_rechaza_huecos_en_las_versiones(self) -> None:
        with tempfile.TemporaryDirectory() as carpeta:
            (Path(carpeta) / "001_a.sql").write_text("CREATE TABLE a (x INTEGER);")
            (Path(carpeta) / "003_c.sql").write_text("CREATE TABLE c (x INTEGER);")
            con = base.abrir_escritura(Path(carpeta) / "x.db")
            try:
                with self.assertRaises(migraciones.ErrorMigracion):
                    migraciones.migrar(con, Path(carpeta))
            finally:
                con.close()

    def test_migracion_fallida_se_revierte_completa(self) -> None:
        with tempfile.TemporaryDirectory() as carpeta:
            (Path(carpeta) / "001_a.sql").write_text(
                "CREATE TABLE esquema_version (version INTEGER PRIMARY KEY,"
                " descripcion TEXT, aplicada_ms INTEGER);"
                "CREATE TABLE a (x INTEGER);"
                "CREATE TABLE a (x INTEGER);"  # error a proposito: tabla repetida
            )
            con = base.abrir_escritura(Path(carpeta) / "x.db")
            try:
                with self.assertRaises(migraciones.ErrorMigracion):
                    migraciones.migrar(con, Path(carpeta))
                self.assertEqual(migraciones.version_actual(con), 0)
                tablas = con.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
                self.assertEqual(tablas, [])  # ni siquiera la primera tabla quedo
            finally:
                con.close()


class PruebasRestricciones(BasePruebas):
    def test_claves_foraneas_activas(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.lectura(sensor_id=999)

    def test_tipos_estrictos(self) -> None:
        with self.assertRaises(sqlite3.Error):
            self.lectura(periodo_ms="quince")

    def test_lectura_sin_muestras_no_puede_tener_valores(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.lectura(n_muestras=0)  # conserva o2_prom: debe rechazarse

    def test_lectura_sin_muestras_con_nulos_es_valida(self) -> None:
        self.lectura(n_muestras=0, o2_prom=None, o2_min=None, o2_max=None,
                     mv_prom=None, calidad=32)

    def test_lectura_minimo_no_mayor_que_maximo(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.lectura(o2_min=22.0, o2_max=21.0)

    def test_alarma_cerrada_exige_fin(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.alarma(estado="cerrada")

    def test_alarma_rechaza_codigo_que_no_es_de_alarma(self) -> None:
        with self.assertRaises(sqlite3.DatabaseError):
            self.alarma(codigo="NET_CONECTADA")

    def test_alarma_rechaza_codigo_inexistente(self) -> None:
        with self.assertRaises(sqlite3.DatabaseError):
            self.alarma(codigo="ALM_NO_EXISTE")

    def test_json_invalido_rechazado(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO evento (ts_ms, ts_confiable, arranque_id, mono_ms, codigo,"
                " severidad, origen, datos_json) VALUES (1, 1, 1, 1, 'SYS_ARRANQUE', 1,"
                " 'prueba', '{no es json')"
            )

    def test_uuid_de_comando_unico(self) -> None:
        sql = (
            "INSERT INTO comando (uuid, ts_ms, ts_confiable, arranque_id, mono_ms, origen, tipo)"
            " VALUES ('u-1', 1, 1, 1, 1, 'plataforma', 'deshabilitar_sensor')"
        )
        self.db.execute(sql)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(sql)

    def test_consulta_parametrizada_no_ejecuta_texto_como_sql(self) -> None:
        malicioso = "x'; DROP TABLE lectura; --"
        self.db.execute("SELECT * FROM sensor WHERE nombre = ?", (malicioso,)).fetchall()
        self.db.execute("SELECT COUNT(*) FROM lectura").fetchone()  # la tabla sigue


class PruebasCalibracion(BasePruebas):
    def calibracion(self, **cambios) -> int:
        datos = dict(
            ts_ms=4000, ts_confiable=1, arranque_id=1, mono_ms=3000, sensor_id=1,
            tipo="offset_cero", gas_pct=20.9, origen="pantalla", resultado="ok", vigente=1,
        )
        datos.update(cambios)
        columnas = ", ".join(datos)
        marcas = ", ".join("?" for _ in datos)
        return self.db.execute(
            f"INSERT INTO calibracion ({columnas}) VALUES ({marcas})", tuple(datos.values())
        ).lastrowid

    def test_una_sola_calibracion_vigente_por_sensor(self) -> None:
        primera = self.calibracion()
        segunda = self.calibracion(ts_ms=5000)
        vigentes = self.db.execute(
            "SELECT id FROM calibracion WHERE sensor_id = 1 AND vigente = 1"
        ).fetchall()
        self.assertEqual([v["id"] for v in vigentes], [segunda])
        # La anterior cambio, asi que su nueva revision tambien se encola.
        self.assertEqual([c["rev"] for c in self.cola("calibracion", primera)], [1, 2])

    def test_calibracion_fallida_no_puede_ser_vigente(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.calibracion(resultado="fallo", vigente=1)


class PruebasSincronizacionYBorrado(BasePruebas):
    def test_insertar_encola_automaticamente(self) -> None:
        rid = self.lectura()
        entradas = self.cola("lectura", rid)
        self.assertEqual(len(entradas), 1)
        self.assertEqual(entradas[0]["estado"], "pendiente")
        self.assertEqual(entradas[0]["rev"], 1)

    def test_no_se_puede_borrar_lo_pendiente(self) -> None:
        rid = self.lectura()
        with self.assertRaises(sqlite3.DatabaseError):
            self.db.execute("DELETE FROM lectura WHERE id = ?", (rid,))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM lectura").fetchone()[0], 1)

    def test_enviado_sin_confirmacion_tampoco_se_borra(self) -> None:
        rid = self.lectura()
        self.db.execute(
            "UPDATE cola_envio SET estado = 'enviado', enviado_ms = 5 WHERE registro_id = ?",
            (rid,),
        )
        with self.assertRaises(sqlite3.DatabaseError):
            self.db.execute("DELETE FROM lectura WHERE id = ?", (rid,))

    def test_rechazado_no_se_borra(self) -> None:
        rid = self.lectura()
        self.db.execute(
            "UPDATE cola_envio SET estado = 'rechazado' WHERE registro_id = ?", (rid,)
        )
        with self.assertRaises(sqlite3.DatabaseError):
            self.db.execute("DELETE FROM lectura WHERE id = ?", (rid,))

    def test_confirmado_se_borra_y_limpia_la_cola(self) -> None:
        rid = self.lectura()
        self.confirmar("lectura", rid)
        self.db.execute("DELETE FROM lectura WHERE id = ?", (rid,))
        self.assertEqual(self.cola("lectura", rid), [])

    def test_sin_entrada_en_cola_no_se_borra(self) -> None:
        # Si alguien borrara la entrada de cola a mano, el registro queda protegido.
        rid = self.lectura()
        self.db.execute("DELETE FROM cola_envio WHERE registro_id = ?", (rid,))
        with self.assertRaises(sqlite3.DatabaseError):
            self.db.execute("DELETE FROM lectura WHERE id = ?", (rid,))

    def test_vista_depurable_solo_incluye_confirmados(self) -> None:
        a, b = self.lectura(ts_ms=1), self.lectura(ts_ms=2)
        self.confirmar("lectura", a)
        ids = [f["registro_id"] for f in self.db.execute(
            "SELECT registro_id FROM v_depurable WHERE tabla = 'lectura'")]
        self.assertEqual(ids, [a])
        self.assertNotIn(b, ids)

    def test_depuracion_masiva_solo_desde_la_vista(self) -> None:
        a, b = self.lectura(ts_ms=1), self.lectura(ts_ms=2)
        self.confirmar("lectura", a)
        self.db.execute(
            "DELETE FROM lectura WHERE id IN"
            " (SELECT registro_id FROM v_depurable WHERE tabla = 'lectura')"
        )
        restantes = [f["id"] for f in self.db.execute("SELECT id FROM lectura")]
        self.assertEqual(restantes, [b])

    def test_modificar_alarma_sube_rev_y_encola_la_revision(self) -> None:
        rid = self.alarma()
        self.db.execute(
            "UPDATE alarma SET estado = 'cerrada', fin_ms = 4000, fin_confiable = 1,"
            " actualizado_ms = 4000 WHERE id = ?", (rid,)
        )
        self.assertEqual(self.db.execute("SELECT rev FROM alarma WHERE id = ?", (rid,)
                                         ).fetchone()[0], 2)
        self.assertEqual([c["rev"] for c in self.cola("alarma", rid)], [1, 2])

    def test_alarma_no_se_borra_hasta_confirmar_todas_las_revisiones(self) -> None:
        rid = self.alarma()
        self.db.execute("UPDATE alarma SET valor_pico = 23.0 WHERE id = ?", (rid,))
        # Solo la revision 1 confirmada: la 2 sigue pendiente.
        self.db.execute(
            "UPDATE cola_envio SET estado = 'confirmado', confirmado_ms = 1"
            " WHERE tabla = 'alarma' AND registro_id = ? AND rev = 1", (rid,)
        )
        with self.assertRaises(sqlite3.DatabaseError):
            self.db.execute("DELETE FROM alarma WHERE id = ?", (rid,))
        self.confirmar("alarma", rid)
        self.db.execute("DELETE FROM alarma WHERE id = ?", (rid,))

    def test_confirmado_exige_fecha_de_confirmacion(self) -> None:
        rid = self.lectura()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "UPDATE cola_envio SET estado = 'confirmado' WHERE registro_id = ?", (rid,)
            )


class PruebasSaludYTrazabilidad(BasePruebas):
    def salud(self, **cambios) -> int:
        datos = dict(ts_ms=5000, ts_confiable=1, arranque_id=1, mono_ms=4000, cpu_temp_c=55.0)
        datos.update(cambios)
        columnas = ", ".join(datos)
        marcas = ", ".join("?" for _ in datos)
        return self.db.execute(
            f"INSERT INTO salud ({columnas}) VALUES ({marcas})", tuple(datos.values())
        ).lastrowid

    def test_salud_por_defecto_es_periodica(self) -> None:
        rid = self.salud()
        motivo = self.db.execute("SELECT motivo FROM salud WHERE id = ?", (rid,)).fetchone()[0]
        self.assertEqual(motivo, "SYS_SALUD_PERIODICA")

    def test_salud_por_alarma_usa_el_codigo_de_la_alarma(self) -> None:
        self.salud(motivo="ALM_RPI_BAJO_VOLTAJE")

    def test_salud_rechaza_motivo_inexistente(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.salud(motivo="MOTIVO_INVENTADO")

    def test_alarmas_de_salud_y_disco_son_validas(self) -> None:
        for codigo in ("ALM_RPI_TEMP_ALTA", "ALM_RPI_RAM_ALTA", "ALM_RPI_BAJO_VOLTAJE",
                       "ALM_DISCO_ESPACIO_BAJO", "ALM_DISCO_ESPACIO_CRITICO"):
            self.alarma(codigo=codigo, sensor_id=None)

    def test_trazabilidad_une_sensor_calibracion_arranque_y_envio(self) -> None:
        cal = self.db.execute(
            "INSERT INTO calibracion (ts_ms, ts_confiable, arranque_id, mono_ms, sensor_id,"
            " tipo, gas_pct, gas_certificado, origen, actor, resultado, vigente)"
            " VALUES (4000, 1, 1, 3000, 1, 'offset_cero', 20.9, 'CERT-123', 'pantalla',"
            " 'tecnico', 'ok', 1)"
        ).lastrowid
        self.db.execute("UPDATE sensor SET serie_etiqueta = '01117707500032' WHERE id = 1")
        rid = self.lectura(calibracion_id=cal)
        self.confirmar("lectura", rid)
        fila = self.db.execute(
            "SELECT * FROM v_lectura_trazabilidad WHERE lectura_id = ?", (rid,)
        ).fetchone()
        self.assertEqual(fila["serie_etiqueta"], "01117707500032")
        self.assertEqual(fila["gas_certificado"], "CERT-123")
        self.assertEqual(fila["version_sw"], "0.0.0")
        self.assertEqual(fila["envio_estado"], "confirmado")
        self.assertEqual(fila["ts_corregido_ms"], fila["ts_ms"])  # reloj confiable

    def test_trazabilidad_corrige_la_hora_si_el_reloj_no_era_confiable(self) -> None:
        # Arranque sin hora real: la lectura se tomo 1000 ms (monotonico) despues
        # del arranque; el reloj se sincronizo en mono 5000 con UTC = 1_700_000_000_000.
        self.db.execute(
            "UPDATE arranque SET sincronizado_utc_ms = 1700000000000,"
            " sincronizado_mono_ms = 5000 WHERE id = 1"
        )
        rid = self.lectura(ts_ms=42, ts_confiable=0, mono_ms=1000)
        corregido = self.db.execute(
            "SELECT ts_corregido_ms FROM v_lectura_trazabilidad WHERE lectura_id = ?", (rid,)
        ).fetchone()[0]
        self.assertEqual(corregido, 1700000000000 + (1000 - 5000))

    def test_trazabilidad_sin_sincronizar_no_inventa_la_hora(self) -> None:
        rid = self.lectura(ts_confiable=0)
        corregido = self.db.execute(
            "SELECT ts_corregido_ms FROM v_lectura_trazabilidad WHERE lectura_id = ?", (rid,)
        ).fetchone()[0]
        self.assertIsNone(corregido)


class PruebasConexiones(BasePruebas):
    def test_conexion_de_lectura_no_puede_escribir(self) -> None:
        lectura = base.abrir_lectura(self.ruta)
        try:
            self.assertEqual(lectura.execute("SELECT COUNT(*) FROM sensor").fetchone()[0], 1)
            with self.assertRaises(sqlite3.Error):
                lectura.execute("DELETE FROM sensor")
        finally:
            lectura.close()

    def test_modo_wal_y_claves_foraneas_activos(self) -> None:
        self.assertEqual(self.db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(self.db.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_integridad(self) -> None:
        self.assertEqual(self.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main()
