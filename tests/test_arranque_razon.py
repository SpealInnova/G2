"""Pruebas de la migracion 004: razon del arranque y huellas actualizadas (D-018)."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from g2.almacenamiento import auditoria, base, migraciones
from test_esquema import BasePruebas


class PruebasRazonArranque(BasePruebas):
    def arranque(self, boot_id: str, **extra) -> int:
        datos = dict(boot_id=boot_id, inicio_ms=5000, inicio_confiable=1, version_sw="0.0.1")
        datos.update(extra)
        columnas = ", ".join(datos)
        marcas = ", ".join("?" for _ in datos)
        return self.db.execute(
            f"INSERT INTO arranque ({columnas}) VALUES ({marcas})", tuple(datos.values())
        ).lastrowid

    def test_razon_acepta_codigos_del_catalogo(self) -> None:
        for razon in ("SYS_ARRANQUE", "SVC_REINICIADO", "SVC_BLOQUEO_DETECTADO",
                      "SYS_REINICIO_SOLICITADO", "SYS_ACTUALIZACION"):
            self.arranque(f"x#{razon}", razon=razon)

    def test_razon_rechaza_codigos_inexistentes(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.arranque("x#1", razon="RAZON_INVENTADA")

    def test_varios_inicios_del_nucleo_comparten_el_encendido_del_so(self) -> None:
        self.arranque("so-A#1", so_boot_id="so-A", razon="SYS_ARRANQUE")
        self.arranque("so-A#2", so_boot_id="so-A", razon="SVC_REINICIADO", version_sw="0.0.2")
        filas = self.db.execute(
            "SELECT boot_id, version_sw FROM arranque WHERE so_boot_id = 'so-A' ORDER BY id"
        ).fetchall()
        self.assertEqual([(f["boot_id"], f["version_sw"]) for f in filas],
                         [("so-A#1", "0.0.1"), ("so-A#2", "0.0.2")])

    def test_boot_id_sigue_siendo_unico(self) -> None:
        self.arranque("so-A#1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.arranque("so-A#1")

    def test_las_columnas_nuevas_entran_en_la_huella(self) -> None:
        rid = self.arranque("so-B#1", so_boot_id="so-B", razon="SYS_ARRANQUE")
        self.assertEqual(auditoria.verificar(self.db), [])
        # Alterar la razon saltandose los disparadores debe detectarse.
        for nombre in ("tr_arranque_rev_auto", "tr_arranque_encolar_rev", "tr_arranque_cadena_rev"):
            self.db.execute(f"DROP TRIGGER {nombre}")
        self.db.execute("UPDATE arranque SET razon = 'SYS_ACTUALIZACION' WHERE id = ?", (rid,))
        problemas = auditoria.verificar(self.db)
        self.assertEqual([(p.tipo, p.tabla, p.registro_id) for p in problemas],
                         [("contenido_alterado", "arranque", rid)])

    def test_los_codigos_nuevos_del_catalogo_existen(self) -> None:
        codigos = {f[0] for f in self.db.execute(
            "SELECT codigo FROM catalogo_evento WHERE codigo IN"
            " ('SYS_REINICIO_SOLICITADO', 'SYS_ACTUALIZACION')")}
        self.assertEqual(codigos, {"SYS_REINICIO_SOLICITADO", "SYS_ACTUALIZACION"})


class PruebasMigracion003a004(unittest.TestCase):
    """Una base que ya estaba en la version 3 con datos pasa a la 4 sin romper la cadena."""

    def test_migrar_con_datos_existentes_resella_y_verifica(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hasta3 = Path(tmp) / "hasta3"
            hasta3.mkdir()
            for archivo in base_sql_hasta(3):
                shutil.copy(archivo, hasta3 / archivo.name)

            con = base.abrir_escritura(Path(tmp) / "g2.db")
            try:
                self.assertEqual(migraciones.migrar(con, hasta3), 3)
                con.execute(
                    "INSERT INTO arranque (boot_id, inicio_ms, inicio_confiable, version_sw)"
                    " VALUES ('viejo#1', 1000, 1, '0.0.0')")
                self.assertEqual(auditoria.verificar(con), [])

                self.assertEqual(migraciones.migrar(con), 4)           # carpeta completa

                revs = [f[0] for f in con.execute(
                    "SELECT rev FROM auditoria_cadena WHERE tabla = 'arranque' ORDER BY seq")]
                self.assertEqual(revs, [1, 2])                         # re-sellado
                self.assertEqual(
                    con.execute("SELECT rev FROM arranque").fetchone()[0], 2)
                self.assertEqual(auditoria.verificar(con), [])         # cadena coherente
                pendientes = [f[0] for f in con.execute(
                    "SELECT rev FROM cola_envio WHERE tabla = 'arranque' ORDER BY rev")]
                self.assertEqual(pendientes, [1, 2])
            finally:
                con.close()


def base_sql_hasta(n: int) -> list[Path]:
    return sorted(migraciones.CARPETA_SQL.glob("*.sql"))[:n]


if __name__ == "__main__":
    unittest.main()
