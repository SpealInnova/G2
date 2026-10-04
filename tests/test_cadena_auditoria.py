"""Pruebas de la cadena de auditoria con huellas SHA-256 (decision D-016).

Verifican que cada registro auditado deja un eslabon, que la cadena es de solo
agregar y que ``verificar`` detecta cada tipo de alteracion. Para simular una
alteracion hace falta saltarse los disparadores de proteccion; las pruebas lo
hacen eliminandolos de la base temporal, que es lo que haria quien manipulara
el archivo con acceso total.
"""

from __future__ import annotations

import sqlite3
import unittest

from g2.almacenamiento import auditoria, base
from test_esquema import BasePruebas

CEROS = "0" * 64


class PruebasCadena(BasePruebas):
    # -- ayudas ---------------------------------------------------------------
    def evento(self, **cambios) -> int:
        datos = dict(ts_ms=7000, ts_confiable=1, arranque_id=1, mono_ms=6000,
                     codigo="NET_DESCONECTADA", severidad=2, origen="uplink.red")
        datos.update(cambios)
        columnas = ", ".join(datos)
        marcas = ", ".join("?" for _ in datos)
        return self.db.execute(
            f"INSERT INTO evento ({columnas}) VALUES ({marcas})", tuple(datos.values())
        ).lastrowid

    def eslabones(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM auditoria_cadena ORDER BY seq").fetchall()

    def quitar_disparadores(self, *nombres: str) -> None:
        """Simula a quien manipula el archivo saltandose las protecciones."""
        for nombre in nombres:
            self.db.execute(f"DROP TRIGGER {nombre}")

    # -- construccion de la cadena ---------------------------------------------
    def test_el_primer_eslabon_parte_de_ceros(self) -> None:
        primero = self.eslabones()[0]  # el arranque que crea setUp
        self.assertEqual(primero["tabla"], "arranque")
        self.assertEqual(primero["hash_previo"], CEROS)

    def test_cada_registro_auditado_deja_un_eslabon_enlazado(self) -> None:
        self.evento()
        self.alarma()
        enlaces = self.eslabones()
        self.assertEqual([e["tabla"] for e in enlaces], ["arranque", "evento", "alarma"])
        for anterior, actual in zip(enlaces, enlaces[1:]):
            self.assertEqual(actual["hash_previo"], anterior["hash_cadena"])

    def test_modificar_un_registro_agrega_un_eslabon_de_la_nueva_revision(self) -> None:
        rid = self.alarma()
        self.db.execute("UPDATE alarma SET valor_pico = 23.5 WHERE id = ?", (rid,))
        revs = [e["rev"] for e in self.eslabones() if e["tabla"] == "alarma"]
        self.assertEqual(revs, [1, 2])

    def test_lecturas_y_salud_no_se_encadenan_una_a_una(self) -> None:
        self.lectura()
        self.assertEqual([e["tabla"] for e in self.eslabones()], ["arranque"])

    def test_los_eslabones_viajan_a_la_plataforma(self) -> None:
        self.evento()
        pendientes = self.db.execute(
            "SELECT COUNT(*) FROM cola_envio WHERE tabla = 'auditoria_cadena'"
            " AND estado = 'pendiente'"
        ).fetchone()[0]
        self.assertEqual(pendientes, len(self.eslabones()))

    # -- cadena de solo agregar --------------------------------------------------
    def test_no_se_puede_modificar_un_eslabon(self) -> None:
        with self.assertRaises(sqlite3.DatabaseError):
            self.db.execute("UPDATE auditoria_cadena SET hash_registro = ? WHERE seq = 1",
                            ("a" * 64,))

    def test_no_se_puede_borrar_un_eslabon(self) -> None:
        with self.assertRaises(sqlite3.DatabaseError):
            self.db.execute("DELETE FROM auditoria_cadena WHERE seq = 1")

    def test_sin_la_funcion_sha256_no_se_puede_escribir_en_tablas_auditadas(self) -> None:
        externa = sqlite3.connect(str(self.ruta), isolation_level=None)
        try:
            externa.execute("PRAGMA foreign_keys = ON")
            with self.assertRaises(sqlite3.OperationalError):
                externa.execute(
                    "INSERT INTO evento (ts_ms, ts_confiable, arranque_id, mono_ms, codigo,"
                    " severidad, origen) VALUES (1, 1, 1, 1, 'SYS_ARRANQUE', 1, 'externa')"
                )
        finally:
            externa.close()
        # La escritura rechazada no dejo nada.
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM evento").fetchone()[0], 0)

    # -- verificacion ------------------------------------------------------------
    def test_una_base_integra_no_tiene_problemas(self) -> None:
        rid = self.alarma()
        self.db.execute("UPDATE alarma SET valor_pico = 23.5 WHERE id = ?", (rid,))
        self.evento()
        self.db.execute(
            "INSERT INTO config_historial (ts_ms, ts_confiable, arranque_id, mono_ms, clave,"
            " valor_nuevo, version, origen) VALUES (1, 1, 1, 1, 'intervalo_s', '15', 1, 'pantalla')"
        )
        self.assertEqual(auditoria.verificar(self.db), [])

    def test_la_verificacion_funciona_con_conexion_de_solo_lectura(self) -> None:
        self.evento()
        lectura = base.abrir_lectura(self.ruta)
        try:
            self.assertEqual(auditoria.verificar(lectura), [])
        finally:
            lectura.close()

    def test_detecta_contenido_alterado(self) -> None:
        rid = self.alarma()
        self.quitar_disparadores("tr_alarma_rev_auto", "tr_alarma_encolar_rev",
                                 "tr_alarma_cadena_rev")
        self.db.execute("UPDATE alarma SET valor_disparo = 99.9 WHERE id = ?", (rid,))
        problemas = auditoria.verificar(self.db)
        self.assertEqual([(p.tipo, p.tabla, p.registro_id) for p in problemas],
                         [("contenido_alterado", "alarma", rid)])

    def test_detecta_cambio_sin_registrar(self) -> None:
        rid = self.alarma()
        self.quitar_disparadores("tr_alarma_rev_auto", "tr_alarma_encolar_rev",
                                 "tr_alarma_cadena_rev")
        self.db.execute("UPDATE alarma SET valor_pico = 30.0, rev = 2 WHERE id = ?", (rid,))
        tipos = [p.tipo for p in auditoria.verificar(self.db)]
        self.assertEqual(tipos, ["cambio_sin_registrar"])

    def test_detecta_registro_sin_eslabon(self) -> None:
        self.quitar_disparadores("tr_evento_cadena_insert")
        self.evento()
        tipos = [p.tipo for p in auditoria.verificar(self.db)]
        self.assertEqual(tipos, ["sin_eslabon"])

    def test_detecta_eslabon_modificado(self) -> None:
        self.evento()
        self.quitar_disparadores("tr_auditoria_cadena_no_modificar")
        self.db.execute("UPDATE auditoria_cadena SET hash_registro = ? WHERE seq = 2",
                        ("b" * 64,))
        problemas = auditoria.verificar(self.db)
        rotos = [p.seq for p in problemas if p.tipo == "eslabon_roto"]
        self.assertEqual(rotos, [2])  # se informa donde se rompio, sin cascada

    def test_detecta_eslabon_borrado(self) -> None:
        self.evento()
        self.evento(ts_ms=8000)
        self.quitar_disparadores("tr_auditoria_cadena_no_borrar")
        self.db.execute("DELETE FROM auditoria_cadena WHERE seq = 2")
        problemas = auditoria.verificar(self.db)
        self.assertTrue(any(p.tipo == "eslabon_roto" for p in problemas))

    def test_borrar_por_retencion_deja_el_eslabon_y_no_es_problema(self) -> None:
        rid = self.evento()
        self.confirmar("evento", rid)
        self.db.execute("DELETE FROM evento WHERE id = ?", (rid,))
        self.assertEqual(auditoria.verificar(self.db), [])
        self.assertIn("evento", [e["tabla"] for e in self.eslabones()])


if __name__ == "__main__":
    unittest.main()
