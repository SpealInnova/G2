"""Pruebas de la generacion de las novedades del README (tools/actualizar_novedades.py)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import actualizar_novedades as N                                      # noqa: E402

CAMPO, REG = N.SEP_CAMPO, N.SEP_REG

SALIDA_GIT = (
    f"2026-10-09{CAMPO}3bf1ce8{CAMPO}Pruebas A/B del ruido{CAMPO}"
    "Parrafo suelto que no es una vineta.\n\n"
    "- Primera vineta que se\n  continua en otra linea.\n"
    "- Segunda vineta.\n\nCo-Authored-By: Alguien <a@b.c>\n" + REG + "\n"
    f"2026-10-09{CAMPO}ea26773{CAMPO}Base de datos{CAMPO}- Catalogo de claves.\n" + REG + "\n"
    f"2026-10-04{CAMPO}d991cfa{CAMPO}Primer commit{CAMPO}" + REG
)


class PruebasNovedades(unittest.TestCase):
    def test_parsea_los_commits_de_git_log(self) -> None:
        commits = N.parsear(SALIDA_GIT)
        self.assertEqual([c.hash for c in commits], ["3bf1ce8", "ea26773", "d991cfa"])
        self.assertEqual(commits[0].titulo, "Pruebas A/B del ruido")

    def test_vinetas_juntan_continuaciones_e_ignoran_parrafos_y_coautoria(self) -> None:
        cuerpo = N.parsear(SALIDA_GIT)[0].cuerpo
        self.assertEqual(N.vinetas(cuerpo), ["Primera vineta que se continua en otra linea.",
                                             "Segunda vineta."])

    def test_vinetas_largas_se_acortan(self) -> None:
        largo = "- " + "palabra " * 80
        self.assertLessEqual(len(N.vinetas(largo)[0]), N.MAX_LARGO)
        self.assertTrue(N.vinetas(largo)[0].endswith("…"))

    def test_agrupa_por_fecha_con_la_mas_reciente_primero(self) -> None:
        texto = N.formatear(N.parsear(SALIDA_GIT))
        self.assertLess(texto.index("### 2026-10-09"), texto.index("### 2026-10-04"))
        self.assertEqual(texto.count("### 2026-10-09"), 1)             # dos commits, un solo dia
        self.assertIn("- **Pruebas A/B del ruido** (`3bf1ce8`)", texto)
        self.assertIn("  - Segunda vineta.", texto)
        self.assertNotIn("Co-Authored-By", texto)
        self.assertNotIn("Parrafo suelto", texto)

    def test_commit_pendiente_sin_hash(self) -> None:
        pendiente = Path(__file__).with_name("_mensaje_tmp.txt")
        pendiente.write_text("Titulo nuevo\n\n- Cambio uno\n\nCo-Authored-By: x\n", encoding="utf-8")
        try:
            c = N.desde_mensaje(pendiente, "2026-10-10")
        finally:
            pendiente.unlink()
        texto = N.formatear([c])
        self.assertIn("- **Titulo nuevo**\n", texto)                   # sin hash entre parentesis
        self.assertIn("  - Cambio uno", texto)

    def test_sin_cambios(self) -> None:
        self.assertIn("Aún no hay cambios", N.formatear([]))

    def test_reemplaza_solo_el_bloque_y_es_idempotente(self) -> None:
        readme = f"# Titulo\n\ntexto\n\n{N.INICIO}\nviejo\n{N.FIN}\n\npie\n"
        uno = N.reemplazar_bloque(readme, "NUEVO")
        self.assertIn("# Titulo", uno)
        self.assertIn("pie", uno)
        self.assertNotIn("viejo", uno)
        self.assertEqual(N.reemplazar_bloque(uno, "NUEVO"), uno)

    def test_sin_marcas_falla_en_vez_de_borrar_el_readme(self) -> None:
        with self.assertRaises(ValueError):
            N.reemplazar_bloque("# Titulo sin marcas", "x")
        with self.assertRaises(ValueError):
            N.reemplazar_bloque(f"{N.INICIO} {N.INICIO} {N.FIN}", "x")


if __name__ == "__main__":
    unittest.main()
