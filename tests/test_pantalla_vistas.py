"""Pruebas de las vistas (g2.pantalla.vistas) y del protocolo (g2.pantalla.protocolo)."""

from __future__ import annotations

import time
import unittest

from g2.pantalla import protocolo as P
from g2.pantalla import vistas as V

C = P.COLOR


def estado(s1=("20.9", "NORMAL", False), s2=("20.9", "NORMAL", False), aviso="Sin alarmas") -> dict:
    return {"sensores": [{"id": 1, "texto_o2": s1[0], "estado": s1[1], "acusada": s1[2]},
                         {"id": 2, "texto_o2": s2[0], "estado": s2[1], "acusada": s2[2]}],
            "aviso": aviso, "sonar": False, "parpadeo": False}


def principal(est, **kw):
    base = dict(nucleo_responde=True, fase_encendida=True, hora="12:34", red="WIFI OK", cola=7)
    base.update(kw)
    return V.vista_principal(est, **base)


class PruebasColores(unittest.TestCase):
    def test_normal_es_verde_con_texto_blanco(self) -> None:
        self.assertEqual(V.colores_estado("NORMAL", False, True), (C["normal"], C["blanco"]))

    def test_alarma_sin_acusar_parpadea_invirtiendo_los_colores(self) -> None:
        self.assertEqual(V.colores_estado("BAJA", False, True), (C["alarma"], C["blanco"]))
        self.assertEqual(V.colores_estado("BAJA", False, False), (C["blanco"], C["alarma"]))
        self.assertEqual(V.colores_estado("ALTA", False, False), (C["blanco"], C["alarma"]))

    def test_alarma_acusada_queda_fija_en_rojo(self) -> None:
        self.assertEqual(V.colores_estado("ALTA", True, True), (C["alarma"], C["blanco"]))
        self.assertEqual(V.colores_estado("ALTA", True, False), (C["alarma"], C["blanco"]))

    def test_sin_señal_y_apagado_son_grises(self) -> None:
        self.assertEqual(V.colores_estado("SIN SEÑAL", False, True), (C["inactivo"], C["blanco"]))
        self.assertEqual(V.colores_estado("APAGADO", False, False), (C["inactivo"], C["blanco"]))


class PruebasVistaPrincipal(unittest.TestCase):
    def test_valores_y_barra(self) -> None:
        v = principal(estado(s2=("15.0", "BAJA", False), aviso="S2 BAJO 15.0 %"))
        self.assertEqual(v["principal.hora.txt"], "12:34")
        self.assertEqual(v["principal.red_s.txt"], "WIFI OK")
        self.assertEqual(v["principal.cola_s.txt"], "COLA 7")
        self.assertEqual((v["principal.o2_1.txt"], v["principal.est_1.txt"]), ("20.9", "NORMAL"))
        self.assertEqual((v["principal.o2_2.txt"], v["principal.est_2.txt"]), ("15.0", "BAJA"))
        self.assertEqual(v["principal.o2_2.pco"], C["alarma"])            # el valor tambien se pone rojo
        self.assertEqual(v["principal.o2_1.pco"], C["texto"])
        self.assertEqual(v["principal.aviso.txt"], "S2 BAJO 15.0 %")
        self.assertEqual((v["principal.aviso.bco"], v["principal.aviso.pco"]), (C["alarma"], C["blanco"]))

    def test_sin_alarmas_el_aviso_es_discreto(self) -> None:
        v = principal(estado())
        self.assertEqual(v["principal.aviso.txt"], "Sin alarmas")
        self.assertEqual((v["principal.aviso.bco"], v["principal.aviso.pco"]), (C["tarjeta"], C["texto"]))

    def test_el_parpadeo_cambia_el_recuadro_pero_no_el_texto(self) -> None:
        e = estado(s1=("15.0", "BAJA", False))
        a, b = principal(e, fase_encendida=True), principal(e, fase_encendida=False)
        self.assertNotEqual(a["principal.est_1.bco"], b["principal.est_1.bco"])
        self.assertEqual(a["principal.est_1.txt"], b["principal.est_1.txt"])
        self.assertEqual(a["principal.est_2.bco"], b["principal.est_2.bco"])     # el sensor 2 no parpadea

    def test_si_el_nucleo_no_responde_no_se_muestran_valores_viejos(self) -> None:
        v = principal(estado(s1=("20.9", "NORMAL", False)), nucleo_responde=False)
        for i in (1, 2):
            self.assertEqual(v[f"principal.o2_{i}.txt"], "--.-")
            self.assertEqual(v[f"principal.est_{i}.txt"], "SIN SEÑAL")
        self.assertEqual(v["principal.aviso.txt"], "Núcleo sin respuesta")
        self.assertEqual(v["principal.aviso.bco"], C["alarma"])

    def test_sin_ningun_estado_tambien_es_sin_nucleo(self) -> None:
        v = principal(None, nucleo_responde=False)
        self.assertEqual(v["principal.aviso.txt"], "Núcleo sin respuesta")

    def test_un_mensaje_temporal_reemplaza_el_aviso_sin_alarma(self) -> None:
        v = principal(estado(), mensaje="Página en construcción")
        self.assertEqual(v["principal.aviso.txt"], "Página en construcción")
        self.assertEqual(v["principal.aviso.bco"], C["tarjeta"])

    def test_el_aviso_no_pasa_de_60_letras(self) -> None:
        v = principal(estado(aviso="X" * 100))
        self.assertEqual(len(v["principal.aviso.txt"]), 60)

    def test_sensor_apagado_se_muestra_gris(self) -> None:
        v = principal(estado(s2=("--.-", "APAGADO", False)))
        self.assertEqual(v["principal.est_2.txt"], "APAGADO")
        self.assertEqual(v["principal.est_2.bco"], C["inactivo"])


class PruebasVistaAlarmas(unittest.TestCase):
    CONFIG = {"alarma.o2_bajo_pct": 20.0, "alarma.o2_alto_pct": 92.0, "alarma.o2_retardo_s": 10.0,
              "alarma.o2_histeresis_pct": 0.5, "alarma.acuse_silencio_s": 120.0}

    def test_los_ajustes_llevan_su_unidad(self) -> None:
        v = V.vista_alarmas(self.CONFIG, [])
        self.assertEqual(v["alarmas.v_bajo.txt"], "20.0 %")
        self.assertEqual(v["alarmas.v_alto.txt"], "92.0 %")
        self.assertEqual(v["alarmas.v_retardo.txt"], "10 s")
        self.assertEqual(v["alarmas.v_histeresis.txt"], "0.5 %")
        self.assertEqual(v["alarmas.v_acuse.txt"], "120 s")

    def test_historial_activas_en_rojo_cerradas_en_gris_y_filas_vacias(self) -> None:
        ms = int(time.mktime((2026, 10, 16, 14, 32, 0, 0, 0, -1)) * 1000)
        hist = [{"codigo": "ALM_O2_BAJO", "sensor_id": 1, "estado": "activa", "inicio_ms": ms},
                {"codigo": "ALM_O2_ALTO", "sensor_id": 2, "estado": "cerrada", "inicio_ms": ms - 60000}]
        v = V.vista_alarmas(self.CONFIG, hist)
        self.assertEqual(v["alarmas.h1.txt"], "16/10 14:32 S1 BAJO")
        self.assertEqual(v["alarmas.h1.pco"], C["alarma"])
        self.assertEqual(v["alarmas.h2.txt"], "16/10 14:31 S2 ALTO")
        self.assertEqual(v["alarmas.h2.pco"], C["texto_suave"])
        for n in range(3, 7):
            self.assertEqual(v[f"alarmas.h{n}.txt"], "")

    def test_alarmas_del_sistema_van_sin_numero_de_sensor(self) -> None:
        ms = int(time.mktime((2026, 10, 16, 9, 5, 0, 0, 0, -1)) * 1000)
        fila = {"codigo": "ALM_SENSORES_DISCREPANTES", "sensor_id": None, "estado": "activa", "inicio_ms": ms}
        self.assertEqual(V.texto_historial(fila), "16/10 09:05 DISCREPANCIA")

    def test_cada_fila_cabe_en_la_caja_de_la_pantalla(self) -> None:
        ms = int(time.mktime((2026, 10, 16, 14, 32, 0, 0, 0, -1)) * 1000)
        for codigo in V.NOMBRES_ALARMA:
            fila = {"codigo": codigo, "sensor_id": 1, "estado": "activa", "inicio_ms": ms}
            self.assertLessEqual(len(V.texto_historial(fila)), 40)             # txt_maxl de h1..h6


class PruebasOrdenes(unittest.TestCase):
    def test_asignar_texto_y_numero(self) -> None:
        self.assertEqual(P.orden_asignar("principal.o2_1.txt", "20.9"), 'principal.o2_1.txt="20.9"')
        self.assertEqual(P.orden_asignar("principal.est_1.bco", 51427), "principal.est_1.bco=51427")

    def test_las_comillas_del_texto_no_rompen_la_orden(self) -> None:
        self.assertEqual(P.orden_asignar("a.b.txt", 'dice "hola"\nfin'), "a.b.txt=\"dice 'hola' fin\"")

    def test_pagina_valida_e_invalida(self) -> None:
        self.assertEqual(P.orden_pagina("alarmas"), "page alarmas")
        with self.assertRaises(ValueError):
            P.orden_pagina("inexistente")

    def test_la_ñ_viaja_en_iso_8859_1(self) -> None:
        self.assertEqual(P.codificar_orden('est_1.txt="SIN SEÑAL"'), b'est_1.txt="SIN SE\xd1AL"' + P.FIN)

    def test_interpretar_eventos(self) -> None:
        self.assertEqual(P.interpretar(bytes([0x65, 0x00, 0x06, 0x00])), P.Toque("principal", "b_acuse"))
        self.assertEqual(P.interpretar(bytes([0x65, 0x06, 0xFE, 0x00])), P.PaginaCargada("teclado"))
        self.assertEqual(P.interpretar(bytes([0x88])), P.PantallaEncendida())
        self.assertEqual(P.interpretar(bytes([0x71, 1, 0, 0, 0])), P.RespuestaNumero(1))
        self.assertEqual(P.interpretar(b"\x70Hola"), P.RespuestaTexto("Hola"))
        self.assertIsInstance(P.interpretar(bytes([0x42, 0x01])), P.Desconocido)

    def test_los_codigos_coinciden_con_la_especificacion(self) -> None:
        self.assertEqual(P.CODIGO_PAGINA["principal"], 0x00)
        self.assertEqual(P.CODIGO_PAGINA["alarmas"], 0x01)
        self.assertEqual(P.CODIGO_PAGINA["teclado"], 0x06)
        self.assertEqual(P.ORDEN_SONIDO_ALARMA, "play 0,1,0")
        self.assertEqual(P.COLOR["alarma"], 51427)

class PruebasDeteccionDeVelocidad(unittest.TestCase):
    def test_prueba_las_velocidades_en_orden_y_se_queda_con_la_primera_que_responde(self) -> None:
        from g2.pantalla.enlace import detectar_baudios
        probadas = []

        def probar(puerto, baudios):
            probadas.append(baudios)
            return baudios == 9600

        self.assertEqual(detectar_baudios("/dev/x", (115200, 9600), probar), 9600)
        self.assertEqual(probadas, [115200, 9600])

    def test_si_responde_la_rapida_no_prueba_la_lenta(self) -> None:
        from g2.pantalla.enlace import detectar_baudios
        probadas = []
        self.assertEqual(detectar_baudios("/dev/x", (115200, 9600), lambda p, b: probadas.append(b) or True), 115200)
        self.assertEqual(probadas, [115200])

    def test_si_no_responde_ninguna_devuelve_none_y_un_error_del_puerto_no_lo_rompe(self) -> None:
        from g2.pantalla.enlace import detectar_baudios

        def probar(puerto, baudios):
            if baudios == 115200:
                raise OSError("puerto ocupado")
            return False

        self.assertIsNone(detectar_baudios("/dev/x", (115200, 9600), probar))



if __name__ == "__main__":
    unittest.main()
