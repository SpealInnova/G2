"""Pruebas de la grafica en tiempo: historial, escala y ordenes (g2.pantalla.grafica), sus eventos de protocolo
y su vista (g2.pantalla.vistas.vista_grafica)."""

from __future__ import annotations

import unittest

from g2.pantalla import grafica as G
from g2.pantalla import protocolo as P
from g2.pantalla import vistas

LIMITES = (20.0, 92.0)


def con_datos(valores, puntos=G.PUNTOS) -> G.HistorialGrafica:
    h = G.HistorialGrafica(puntos)
    for v in valores:
        h.agregar(v)
    h.ajustar_escala(0.0)
    return h


class PruebasEscala(unittest.TestCase):
    def test_sin_datos_no_hay_eje(self) -> None:
        h = G.HistorialGrafica()
        self.assertFalse(h.ajustar_escala(0.0))
        self.assertEqual(h.marcas(), ("", "", ""))
        self.assertEqual(h.nivel(20.9), G.SIN_DATO)

    def test_el_primer_eje_respeta_el_ancho_minimo_y_los_numeros_redondos(self) -> None:
        h = con_datos([(20.9, 20.9)] * 5)
        self.assertEqual((h.bajo, h.alto), (17.0, 24.0))              # ancho minimo de 5 % con holgura, de 1 en 1
        self.assertGreaterEqual(h.alto - h.bajo, G.ANCHO_MINIMO_PCT)

    def test_un_eje_ancho_se_redondea_de_cinco_en_cinco(self) -> None:
        h = con_datos([(21.0, 90.0)])
        self.assertEqual((h.bajo % 5, h.alto % 5), (0.0, 0.0))
        self.assertTrue(h.bajo <= 21.0 and h.alto >= 90.0)

    def test_el_eje_nunca_sale_de_0_a_100(self) -> None:
        h = con_datos([(99.8, 99.9)])
        self.assertLessEqual(h.alto, 100.0)
        self.assertGreaterEqual(h.alto - h.bajo, G.ANCHO_MINIMO_PCT)
        h = con_datos([(0.1, 0.2)])
        self.assertGreaterEqual(h.bajo, 0.0)

    def test_niveles_de_1_a_255_y_cero_para_sin_dato(self) -> None:
        h = con_datos([(18.5, 23.5)])
        self.assertEqual(h.nivel(h.bajo), 1)
        self.assertEqual(h.nivel(h.alto), 255)
        self.assertEqual(h.nivel(None), G.SIN_DATO)
        self.assertEqual(G.SIN_DATO, 0)
        self.assertEqual(h.nivel(h.bajo - 50), 1)                     # lo que se sale se recorta, nunca baja a 0
        self.assertEqual(h.nivel(h.alto + 50), 255)

    def test_un_valor_fuera_del_eje_lo_reescala_enseguida(self) -> None:
        h = con_datos([(20.9, 20.9)])
        antes = (h.bajo, h.alto)
        h.agregar((40.0, 20.9))
        self.assertTrue(h.ajustar_escala(1.0))
        self.assertNotEqual((h.bajo, h.alto), antes)
        self.assertTrue(h.bajo <= 20.9 and h.alto >= 40.0)

    def test_sin_cambios_no_se_reescala(self) -> None:
        h = con_datos([(20.9, 21.0)] * 3)
        h.agregar((21.0, 20.8))
        self.assertFalse(h.ajustar_escala(5.0))

    def test_el_eje_solo_se_reduce_pasado_el_tiempo_de_espera(self) -> None:
        h = G.HistorialGrafica(puntos=10)
        h.agregar((20.9, 60.0))
        h.ajustar_escala(0.0)
        ancho = h.alto - h.bajo
        for _ in range(10):                                            # el 60 sale de la ventana: el eje queda muy ancho
            h.agregar((20.9, 21.0))
        self.assertFalse(h.ajustar_escala(10.0))                       # demasiado pronto
        self.assertEqual(h.alto - h.bajo, ancho)
        self.assertTrue(h.ajustar_escala(G.ESPERA_REESCALA_S + 1.0))
        self.assertLess(h.alto - h.bajo, ancho)

    def test_marcas_del_eje(self) -> None:
        h = con_datos([(20.9, 20.9)])
        self.assertEqual(h.marcas(), ("24", "20.5", "17"))
        self.assertEqual(G.formato_eje(21.5), "21.5")

    def test_formato_de_la_ventana(self) -> None:
        self.assertEqual(G.formato_ventana(700), "-12 min")
        self.assertEqual(G.formato_ventana(60), "-60 s")


class PruebasOrdenes(unittest.TestCase):
    def test_la_ventana_guarda_solo_los_ultimos_700_puntos(self) -> None:
        h = G.HistorialGrafica()
        for i in range(800):
            h.agregar((20.0, 21.0))
        self.assertEqual(h.cantidad(), 700)
        self.assertEqual(h.total, 800)

    def test_un_sensor_sin_dato_baja_al_nivel_cero(self) -> None:
        h = con_datos([(20.9, None), (20.9, None)])
        bloques = dict(h.bloques_completos(LIMITES))
        self.assertEqual(bloques[1], bytes([0, 0]))
        self.assertTrue(all(b > 0 for b in bloques[0]))

    def test_los_limites_de_alarma_solo_se_dibujan_si_caen_en_el_eje(self) -> None:
        h = con_datos([(20.9, 20.9)] * 4)                               # eje 17 a 24: el limite bajo (20) cae, el alto (92) no
        canales = [c for c, _ in h.bloques_completos(LIMITES)]
        self.assertEqual(canales, [0, 1, G.CANAL_BAJO])
        for canal, datos in h.bloques_completos(LIMITES):
            self.assertEqual(len(datos), 4)                            # un byte por punto
        nivel_bajo = dict(h.bloques_completos(LIMITES))[G.CANAL_BAJO]
        self.assertEqual(set(nivel_bajo), {h.nivel(20.0)})

    def test_orden_de_limpiar_y_de_bloque(self) -> None:
        self.assertEqual(G.HistorialGrafica.orden_limpiar(), "cle s0.id,255")
        self.assertEqual(G.HistorialGrafica.orden_bloque(1, 700), "addt s0.id,1,700")

    def test_ordenes_nuevas_son_un_add_por_canal_y_por_muestra(self) -> None:
        h = con_datos([(20.9, 21.5)] * 5)
        o = h.ordenes_nuevas(2, LIMITES)
        self.assertEqual(len(o), 2 * 3)                                  # 2 muestras x (2 sensores + el limite bajo)
        self.assertTrue(all(x.startswith("add s0.id,") for x in o))
        self.assertEqual(o[0], f"add s0.id,0,{h.nivel(20.9)}")
        self.assertEqual(o[1], f"add s0.id,1,{h.nivel(21.5)}")

    def test_ordenes_completas_equivalen_a_los_bloques(self) -> None:
        h = con_datos([(20.9, 21.5), (21.0, 21.4)])
        n_bloques = sum(len(d) for _, d in h.bloques_completos(LIMITES))
        self.assertEqual(len(h.ordenes_completas(LIMITES)), n_bloques)

    def test_pedir_mas_muestras_de_las_que_hay_no_falla(self) -> None:
        h = con_datos([(20.9, 20.9)] * 3)
        self.assertEqual(len(h.ultimas(0, 50)), 3)
        self.assertEqual(h.ultimas(0, 0), [])

    def test_carga_en_bloque_de_700_puntos_cuesta_lo_calculado(self) -> None:
        h = con_datos([(20.9, 21.5)] * 700)
        bytes_totales = sum(len(d) for _, d in h.bloques_completos(LIMITES))
        self.assertEqual(bytes_totales, 700 * 3)                         # 2 sensores + el limite bajo


class PruebasProtocolo(unittest.TestCase):
    def test_toque_en_cualquier_punto(self) -> None:
        e = P.interpretar(bytes([0x67, 0x01, 0x90, 0x00, 0xC8, 0x01]))
        self.assertEqual(e, P.TocarPantalla(400, 200, True))
        self.assertEqual(P.interpretar(bytes([0x67, 0x00, 0x0A, 0x00, 0x14, 0x00])), P.TocarPantalla(10, 20, False))

    def test_respuestas_de_addt(self) -> None:
        self.assertIsInstance(P.interpretar(bytes([0xFE])), P.ListoParaDatos)
        self.assertIsInstance(P.interpretar(bytes([0xFD])), P.DatosRecibidos)

    def test_el_evento_de_pagina_cargada_no_se_confunde_con_el_fe_suelto(self) -> None:
        self.assertEqual(P.interpretar(bytes([0x65, 0x0A, 0xFE, 0x00])), P.PaginaCargada("grafica"))

    def test_toque_de_la_pagina_grafica(self) -> None:
        self.assertEqual(P.interpretar(bytes([0x65, 0x0A, 0x01, 0x00])), P.Toque("grafica", "salir"))

    def test_las_tramas_con_fe_se_separan_bien(self) -> None:
        tramas, resto = P.separar(bytes([0xFE]) + P.FIN + bytes([0xFD]) + P.FIN)
        self.assertEqual([P.interpretar(t) for t in tramas], [P.ListoParaDatos(), P.DatosRecibidos()])
        self.assertEqual(resto, b"")


class PruebasVista(unittest.TestCase):
    def estado(self, e1="NORMAL", e2="NORMAL"):
        return {"sensores": [{"id": 1, "texto_o2": "20.9", "estado": e1}, {"id": 2, "texto_o2": "--.-", "estado": e2}]}

    def test_valores_actuales_con_el_color_de_cada_linea(self) -> None:
        v = vistas.vista_grafica(self.estado(), nucleo_responde=True, marcas=("24", "21", "18"), ventana="-12 min")
        self.assertEqual(v["grafica.v1.txt"], "S1  20.9 %  NORMAL")
        self.assertEqual(v["grafica.v1.pco"], P.COLOR["sensor1"])
        self.assertEqual((v["grafica.y_max.txt"], v["grafica.y_med.txt"], v["grafica.y_min.txt"]), ("24", "21", "18"))
        self.assertEqual(v["grafica.x_ini.txt"], "-12 min")

    def test_en_alarma_rojo_y_sin_senal_gris(self) -> None:
        v = vistas.vista_grafica(self.estado(e1="BAJA", e2="SIN SEÑAL"), nucleo_responde=True,
                                 marcas=("", "", ""), ventana="")
        self.assertEqual(v["grafica.v1.pco"], P.COLOR["alarma"])
        self.assertEqual(v["grafica.v2.pco"], P.COLOR["inactivo"])

    def test_sin_respuesta_del_nucleo_no_muestra_valores(self) -> None:
        v = vistas.vista_grafica(None, nucleo_responde=False, marcas=("", "", ""), ventana="")
        self.assertEqual(v["grafica.v1.txt"], "S1  --.- %  SIN SEÑAL")
        self.assertEqual(v["grafica.v2.pco"], P.COLOR["inactivo"])


if __name__ == "__main__":
    unittest.main()
