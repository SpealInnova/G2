"""Pruebas de los reportes en PDF (D-044): rango de fechas, emparejado y alertas, PDF cifrado, memoria USB, el trabajo
completo, el servicio del nucleo y las ordenes del nucleo. Nada toca una memoria USB ni la pantalla reales."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from g2.almacenamiento.almacen import Almacen
from g2.almacenamiento import base
from g2.nucleo.fuentes import FuenteSimulada
from g2.nucleo.nucleo import Nucleo
from g2.nucleo.servicio_reportes import ServicioReportes
from g2.reportes import consulta, pdf, rango, trabajo, usb
from g2.reportes.consulta import Alarma, CambioSensor, Fila, Medida
from g2.tiempo import RelojPrueba

ZONA = "America/Bogota"                                # UTC-5 todo el ano (Colombia no cambia la hora)
NOMBRE = "ANZD-000000001"
# 2026-10-27 05:00 UTC = 00:00 en Colombia: el inicio del dia 27.
DIA_27_MS = 1_793_077_200_000


def medida(id_, ts_ms, o2=20.9, periodo_ms=15_000, calidad=0, confiable=True, n=30) -> Medida:
    return Medida(id_, ts_ms, confiable, periodo_ms, n, o2, calidad)


def alarma(inicio_ms, fin_ms, codigo="ALM_O2_ALTO", sensor=1, umbral=92.0) -> Alarma:
    return Alarma(1, codigo, sensor, inicio_ms, fin_ms, umbral, 95.0, "cerrada", None, None)


class PruebasRango(unittest.TestCase):
    def test_un_dia_son_las_24_horas_de_la_zona_del_equipo(self) -> None:
        inicio, fin = rango.limites_ms(date(2026, 10, 27), date(2026, 10, 27), ZONA)
        self.assertEqual(inicio, DIA_27_MS)
        self.assertEqual(fin - inicio, 24 * 3600 * 1000)

    def test_varios_dias_se_cuentan_completos(self) -> None:
        inicio, fin = rango.limites_ms(date(2026, 10, 21), date(2026, 10, 27), ZONA)
        self.assertEqual((fin - inicio) // (24 * 3600 * 1000), 7)

    def test_validar_acepta_hasta_una_semana_y_rechaza_mas(self) -> None:
        hoy = date(2026, 10, 27)
        self.assertEqual(rango.validar(date(2026, 10, 21), hoy, hoy), 7)
        self.assertEqual(rango.validar(hoy, hoy, hoy), 1)
        with self.assertRaisesRegex(rango.ErrorRango, "Máximo 7 días"):
            rango.validar(date(2026, 10, 20), hoy, hoy)

    def test_validar_rechaza_el_futuro_y_el_orden_invertido(self) -> None:
        hoy = date(2026, 10, 27)
        with self.assertRaisesRegex(rango.ErrorRango, "futuras"):
            rango.validar(hoy, date(2026, 10, 28), hoy)
        with self.assertRaisesRegex(rango.ErrorRango, "posterior"):
            rango.validar(date(2026, 10, 26), date(2026, 10, 25), hoy)

    def test_leer_fecha_acepta_los_dos_formatos_y_rechaza_las_inexistentes(self) -> None:
        self.assertEqual(rango.leer_fecha("27/10/2026"), date(2026, 10, 27))
        self.assertEqual(rango.leer_fecha("2026-10-27"), date(2026, 10, 27))
        for malo in ("31/02/2026", "ayer", "", "1/2"):
            with self.assertRaises(rango.ErrorRango):
                rango.leer_fecha(malo)

    def test_zona_invalida(self) -> None:
        with self.assertRaises(rango.ErrorRango):
            rango.limites_ms(date(2026, 10, 27), date(2026, 10, 27), "Marte/Olympus")

    def test_la_hora_se_escribe_en_la_zona_del_equipo(self) -> None:
        self.assertEqual(rango.texto_hora(DIA_27_MS + 3_723_000, ZONA), ("27/10/2026", "01:02:03"))

    def test_hoy_usa_la_zona_no_la_hora_utc(self) -> None:
        # 02:00 UTC del 28 todavia es 21:00 del 27 en Colombia
        self.assertEqual(rango.hoy(ZONA, DIA_27_MS + 20 * 3600 * 1000), date(2026, 10, 27))


class PruebasEmparejarYAlertas(unittest.TestCase):
    def test_dos_lecturas_con_unos_milisegundos_de_diferencia_son_pareja(self) -> None:
        a = [medida(1, 1000), medida(3, 16_000)]
        b = [medida(2, 1040), medida(4, 16_001)]
        self.assertEqual([(x.id, y.id) for x, y in consulta.emparejar(a, b)], [(1, 2), (3, 4)])

    def test_sin_pareja_queda_el_otro_sensor_vacio(self) -> None:
        a = [medida(1, 1000), medida(3, 16_000), medida(5, 31_000)]
        b = [medida(4, 16_020)]
        pares = consulta.emparejar(a, b)
        self.assertEqual([(x.id if x else None, y.id if y else None) for x, y in pares], [(1, None), (3, 4), (5, None)])

    def test_respeta_el_intervalo_guardado_en_cada_fila(self) -> None:
        # el intervalo cambio de 15 s a 5 s: las parejas se buscan con la mitad del intervalo de cada fila
        a = [medida(1, 15_000, periodo_ms=15_000), medida(3, 20_000, periodo_ms=5_000), medida(5, 25_000, periodo_ms=5_000)]
        b = [medida(2, 15_030, periodo_ms=15_000), medida(4, 20_010, periodo_ms=5_000), medida(6, 25_020, periodo_ms=5_000)]
        self.assertEqual([(x.id, y.id) for x, y in consulta.emparejar(a, b)], [(1, 2), (3, 4), (5, 6)])

    def test_una_lectura_es_alerta_si_hubo_alarma_abierta_en_su_intervalo(self) -> None:
        medidas = [medida(i, 15_000 * i) for i in range(1, 7)]                 # intervalos que terminan en 15, 30, ... 90 s
        al = alarma(inicio_ms=40_000, fin_ms=70_000, umbral=75.0)
        textos = consulta.alertas_de(medidas, [al])
        # la 3 (30-45 s) ya incluye el inicio; la 5 (60-75 s) todavia el final; la 6 (75-90 s) ya no
        self.assertEqual(textos, [None, None, "ALTO > 75", "ALTO > 75", "ALTO > 75", None])

    def test_una_alarma_abierta_marca_todo_lo_que_sigue(self) -> None:
        medidas = [medida(i, 15_000 * i) for i in range(1, 5)]
        textos = consulta.alertas_de(medidas, [alarma(inicio_ms=20_000, fin_ms=None, codigo="ALM_O2_BAJO", umbral=20.0)])
        self.assertEqual(textos, [None, "BAJO < 20", "BAJO < 20", "BAJO < 20"])

    def test_el_umbral_que_se_imprime_es_el_de_la_alarma_no_el_actual(self) -> None:
        textos = consulta.alertas_de([medida(1, 15_000)], [alarma(0, None, umbral=75.0)])
        self.assertEqual(textos, ["ALTO > 75"])

    def test_la_alerta_de_un_sensor_no_marca_al_otro(self) -> None:
        a = [medida(1, 15_000)]
        b = [medida(2, 15_010)]
        filas = consulta.armar(a, b, [alarma(0, None, sensor=1)], [])
        self.assertEqual((filas[0].alerta1, filas[0].alerta2, filas[0].con_alerta), ("ALTO > 92", None, True))

    def test_la_discrepancia_entre_sensores_no_se_marca(self) -> None:
        # solo cuentan ALM_O2_BAJO y ALM_O2_ALTO
        self.assertNotIn("ALM_SENSORES_DISCREPANTES", consulta.CODIGOS_ALERTA)

    def test_el_resumen_cuenta_filas_alertas_y_horas_sin_sincronizar(self) -> None:
        a = [medida(1, 15_000, o2=80.0), medida(3, 30_000, o2=90.0, confiable=False, calidad=1)]
        b = [medida(2, 15_010, o2=79.0), medida(4, 30_010, o2=89.0)]
        datos = consulta.DatosReporte("27/10/2026", "27/10/2026", ZONA, 0, 1, [], filas=consulta.armar(a, b, [alarma(20_000, None)], []))
        r = datos.resumen()
        self.assertEqual((r["filas"], r["con_alerta"][1], r["hora_no_confiable"], r["calidad_anomala"]), (2, 1, 1, 1))
        self.assertEqual((r["estadisticas"][1]["min"], r["estadisticas"][1]["max"]), (80.0, 90.0))
        self.assertEqual(r["periodos_s"], [15])


class BaseConBase(unittest.TestCase):
    """Una base real con dos sensores y lecturas cada 15 s (el segundo sensor, unos ms despues)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.ruta = self.dir / "g2.db"
        self.reloj = RelojPrueba(ahora_ms=DIA_27_MS + 3_600_000)          # 01:00 del 27 en Colombia
        self.a = Almacen.abrir(self.ruta, self.reloj)
        self.a.registrar_arranque(version_sw="0.1.0-test", so_boot_id="so-1")
        self.s1 = self.a.registrar_sensor(canal="ads1263:0-1", nombre="Sensor 1", modelo="Paracube Micro",
                                          mv_por_pct=10.0, serie_etiqueta="SN1")
        self.s2 = self.a.registrar_sensor(canal="ads1263:2-3", nombre="Sensor 2", modelo="Paracube Micro",
                                          mv_por_pct=10.0)
        self.a.config_fijar("equipo.nombre", NOMBRE, origen="local", actor="prueba")

    def tearDown(self) -> None:
        self.a.cerrar()
        self._tmp.cleanup()

    def lecturas(self, cuantas: int, o2_1=80.0, o2_2=79.5, periodo_ms=15_000) -> list[tuple[int, int]]:
        ids = []
        for _ in range(cuantas):
            self.reloj.avanzar(periodo_ms)
            i1 = self.a.insertar_lectura(sensor_id=self.s1, periodo_ms=periodo_ms, n_muestras=30, o2_prom=o2_1,
                                         o2_min=o2_1, o2_max=o2_1, mv_prom=o2_1 * 10)
            self.reloj.avanzar(40)
            i2 = self.a.insertar_lectura(sensor_id=self.s2, periodo_ms=periodo_ms, n_muestras=30, o2_prom=o2_2,
                                         o2_min=o2_2, o2_max=o2_2, mv_prom=o2_2 * 10)
            ids.append((i1, i2))
        return ids

    def leer(self, desde=date(2026, 10, 27), hasta=date(2026, 10, 27)) -> consulta.DatosReporte:
        conexion = base.abrir_lectura(self.ruta)
        try:
            return consulta.construir(conexion, desde, hasta, ZONA)
        finally:
            conexion.close()


class PruebasConsultaConBase(BaseConBase):
    def test_una_fila_por_intervalo_con_los_dos_sensores_y_sus_numeros_de_registro(self) -> None:
        ids = self.lecturas(4)
        datos = self.leer()
        self.assertEqual(len(datos.filas), 4)
        self.assertEqual([(f.s1.id, f.s2.id) for f in datos.filas], ids)
        self.assertEqual((datos.filas[0].s1.o2, datos.filas[0].s2.o2), (80.0, 79.5))

    def test_solo_entran_los_dias_pedidos(self) -> None:
        self.lecturas(3)
        self.reloj.avanzar(24 * 3600 * 1000)                               # ya es el dia 28
        self.lecturas(2)
        self.assertEqual(len(self.leer(date(2026, 10, 27), date(2026, 10, 27)).filas), 3)
        self.assertEqual(len(self.leer(date(2026, 10, 28), date(2026, 10, 28)).filas), 2)
        self.assertEqual(len(self.leer(date(2026, 10, 27), date(2026, 10, 28)).filas), 5)

    def test_si_el_intervalo_de_guardado_cambio_cada_fila_conserva_el_suyo(self) -> None:
        self.lecturas(3, periodo_ms=15_000)
        self.lecturas(3, periodo_ms=5_000)
        datos = self.leer()
        self.assertEqual(len(datos.filas), 6)
        self.assertEqual([f.s1.periodo_ms for f in datos.filas], [15_000] * 3 + [5_000] * 3)

    def test_las_alarmas_marcan_las_filas_con_el_umbral_de_ese_momento(self) -> None:
        self.lecturas(2)
        alarma_id = self.a.abrir_alarma("ALM_O2_ALTO", sensor_id=self.s1, umbral=75.0, valor=80.0)
        self.lecturas(2)
        self.a.cerrar_alarma(alarma_id)
        self.a.config_fijar("alarma.o2_alto_pct", 95, origen="pantalla", actor="t")     # el umbral de HOY es otro
        self.lecturas(2)
        filas = self.leer().filas
        self.assertEqual([f.alerta1 for f in filas], [None, None, "ALTO > 75", "ALTO > 75", "ALTO > 75", None])
        self.assertTrue(all(f.alerta2 is None for f in filas))

    def test_un_sensor_apagado_deja_la_otra_columna_en_blanco(self) -> None:
        self.reloj.avanzar(15_000)
        self.a.insertar_lectura(sensor_id=self.s1, periodo_ms=15_000, n_muestras=30, o2_prom=80.0, o2_min=80.0,
                                o2_max=80.0, mv_prom=800.0)
        filas = self.leer().filas
        self.assertEqual((len(filas), filas[0].s2), (1, None))

    def test_el_reporte_dice_cuando_un_sensor_se_apago_se_encendio_o_quedo_sin_senal(self) -> None:
        self.lecturas(2)
        self.a.fijar_sensor_habilitado(self.s2, False, origen="pantalla", actor="pantalla")
        self.reloj.avanzar(120_000)                                         # fuera de la ventana de agrupacion
        self.a.fijar_sensor_habilitado(self.s2, True, origen="pantalla", actor="pantalla")
        self.reloj.avanzar(1_000)
        alarma_id = self.a.abrir_alarma("ALM_SENSOR_INVALIDO", sensor_id=self.s1)
        self.reloj.avanzar(30_000)
        self.a.cerrar_alarma(alarma_id)
        self.a.abrir_alarma("ALM_SENSOR_INVALIDO", sensor_id=self.s2)       # esta sigue abierta
        cambios = self.leer().cambios_sensor
        self.assertEqual([(c.sensor_id, c.estado) for c in cambios],
                         [(self.s2, "apagado"), (self.s2, "encendido"), (self.s1, "sin_senal"), (self.s2, "sin_senal")])
        self.assertIsNotNone(cambios[2].fin_ms)
        self.assertIsNone(cambios[3].fin_ms)

    def test_sin_cambios_de_sensor_la_lista_va_vacia_y_las_alarmas_de_oxigeno_no_cuentan(self) -> None:
        self.lecturas(2)
        self.a.abrir_alarma("ALM_O2_ALTO", sensor_id=self.s1, umbral=75.0, valor=80.0)
        self.assertEqual(self.leer().cambios_sensor, [])

    def test_un_hueco_sin_muestras_queda_como_hueco(self) -> None:
        self.reloj.avanzar(15_000)
        self.a.insertar_lectura(sensor_id=self.s1, periodo_ms=15_000, n_muestras=0, o2_prom=None, o2_min=None,
                                o2_max=None, mv_prom=None, calidad=32)
        self.assertIsNone(self.leer().filas[0].s1.o2)

    def test_demasiados_registros_se_rechazan_antes_de_armar_nada(self) -> None:
        self.lecturas(3)
        anterior, rango.MAX_FILAS = rango.MAX_FILAS, 2
        try:
            with self.assertRaisesRegex(rango.ErrorRango, "Demasiados registros"):
                self.leer()
        finally:
            rango.MAX_FILAS = anterior


class FalsoLienzo:
    """Apunta cada texto dibujado con la fuente y el color vigentes (para comprobar el rojo y la negrita)."""

    def __init__(self) -> None:
        self.fuente, self.color, self.dibujado = "", (0, 0, 0), []

    def setFont(self, fuente, tamano):
        self.fuente = fuente

    def setFillColorRGB(self, r, g, b):
        self.color = (r, g, b)

    def setStrokeColorRGB(self, *_):
        pass

    def line(self, *_):
        pass

    def _anotar(self, x, y, texto):
        self.dibujado.append((texto, self.fuente, self.color))

    drawString = drawRightString = _anotar


class PruebasPdf(unittest.TestCase):
    def dibujante(self, filas) -> tuple[pdf._Dibujante, FalsoLienzo]:
        datos = consulta.DatosReporte("27/10/2026", "27/10/2026", ZONA, 0, 1, [], filas=filas)
        lienzo = FalsoLienzo()
        return pdf._Dibujante(lienzo, pdf.Portada(NOMBRE, "", "0.1", DIA_27_MS), datos, 1), lienzo

    def test_la_fila_con_alerta_va_en_rojo_y_negrita_y_la_normal_no(self) -> None:
        normal = Fila(DIA_27_MS + 1000, True, medida(1, 0), medida(2, 0))
        con_alerta = Fila(DIA_27_MS + 2000, True, medida(3, 0), medida(4, 0, o2=79.0), alerta1="ALTO > 92")
        d, lienzo = self.dibujante([normal, con_alerta])
        d._fila(700, 0, normal, ZONA)
        d._fila(688, 1, con_alerta, ZONA)
        sin_alerta, con = lienzo.dibujado[:6], lienzo.dibujado[6:]
        self.assertTrue(all(f == "Helvetica" and c == (0, 0, 0) for _, f, c in sin_alerta))
        por_texto = {t: (f, c) for t, f, c in con}
        for texto in ("3", "4", "27/10/2026", "S1 ALTO > 92"):
            self.assertEqual(por_texto[texto], ("Helvetica-Bold", pdf.ROJO), texto)
        # la lectura del sensor 1 (en alerta) va en rojo; la del 2 (sin alerta) no
        self.assertEqual(por_texto["20.90"], ("Helvetica-Bold", pdf.ROJO))
        self.assertEqual(por_texto["79.00"], ("Helvetica", pdf.NEGRO))

    def test_un_sensor_sin_lectura_se_escribe_con_guion(self) -> None:
        fila = Fila(DIA_27_MS, True, medida(1, 0), None)
        d, lienzo = self.dibujante([fila])
        d._fila(700, 0, fila, ZONA)
        self.assertEqual([t for t, _, _ in lienzo.dibujado].count("—"), 2)        # numero de registro y valor

    def test_marca_la_calidad_anormal_y_la_hora_sin_sincronizar(self) -> None:
        fila = Fila(DIA_27_MS, False, medida(1, 0, calidad=1), medida(2, 0))
        d, lienzo = self.dibujante([fila])
        d._fila(700, 0, fila, ZONA)
        textos = [t for t, _, _ in lienzo.dibujado]
        self.assertIn("20.90*", textos)
        self.assertIn("00:00:00 †", textos)

    def test_el_numero_de_paginas_se_conoce_antes_de_dibujar(self) -> None:
        filas = [Fila(DIA_27_MS + i * 1000, True, medida(2 * i, 0), medida(2 * i + 1, 0)) for i in range(120)]
        datos = consulta.DatosReporte("27/10/2026", "27/10/2026", ZONA, 0, 1, [], filas=filas)
        self.assertEqual(pdf.paginas_de_datos(120), 3)
        self.assertEqual(pdf.total_paginas(datos), 1 + 3 + 1)

    def test_dibujar_y_cifrar_produce_un_pdf_que_solo_abre_con_el_nombre_del_equipo(self) -> None:
        from pypdf import PdfReader
        filas = [Fila(DIA_27_MS + i * 15_000, True, medida(2 * i + 1, 0, o2=80.0 + i / 100), medida(2 * i + 2, 0),
                      alerta1="ALTO > 92" if i == 5 else None) for i in range(130)]
        datos = consulta.DatosReporte("27/10/2026", "27/10/2026", ZONA, DIA_27_MS, DIA_27_MS + 86_400_000,
                                      [{"nombre": "Sensor 1", "modelo": "Paracube Micro", "serie_etiqueta": None},
                                       {"nombre": "Sensor 2", "modelo": "Paracube Micro", "serie_etiqueta": None}],
                                      filas=filas, alarmas=[alarma(DIA_27_MS, None, umbral=92.0)])
        with tempfile.TemporaryDirectory() as tmp:
            claro, cifrado = Path(tmp) / "a.pdf", Path(tmp) / "b.pdf"
            avances = []
            paginas = pdf.dibujar(datos, pdf.Portada(NOMBRE, "ID-1", "0.1.0", DIA_27_MS, cadena=(True, 0)), claro,
                                  progreso=avances.append)
            pdf.cifrar(claro, cifrado, NOMBRE)
            lector = PdfReader(str(cifrado))
            self.assertTrue(lector.is_encrypted)
            self.assertEqual(lector.decrypt("otra-cosa"), 0)                       # con otra contrasena no abre
            self.assertGreater(lector.decrypt(NOMBRE), 0)
            self.assertEqual(len(lector.pages), paginas)
            texto = "\n".join(p.extract_text() for p in lector.pages)
            for esperado in (f"Equipo {NOMBRE}", "Resumen del reporte", "Cadena de auditoría íntegra", "S1 ALTO > 92",
                             "Página 1 de", "Alarmas y estado de los sensores",
                             "Sin cambios de estado de los sensores en el rango."):
                self.assertIn(esperado, texto)
            self.assertEqual(avances, sorted(avances))                              # el avance nunca retrocede
            self.assertNotIn(ZONA, texto)                                           # no se escribe la zona horaria
            permisos = lector.user_access_permissions                              # se puede copiar e imprimir, no editar
            from pypdf.constants import UserAccessPermissions as Permiso
            self.assertTrue(permisos & Permiso.EXTRACT)
            self.assertTrue(permisos & Permiso.PRINT)
            self.assertFalse(permisos & Permiso.MODIFY)
            self.assertRegex(lector.pages[1].extract_text(), r"1\s+2\s+27/10/2026\s+00:00:00\s+80\.00\s+20\.90")   # una fila sale completa y en orden
            self.assertNotIn("Software", texto)                                     # la version del software es interna
            self.assertNotIn("0.1.0", texto)
            self.assertNotIn("Paracube", texto)                                     # ni el modelo ni la serie de los sensores
            self.assertNotIn("serie", texto)
            self.assertRegex(texto, r"Sensor 1\s+130 lecturas")                     # pero si sus estadisticas
            self.assertRegex(texto, r"Sensor 2\s+130 lecturas")
            self.assertNotIn("Cambios de configuración", texto)                     # ni la lista de cambios de configuracion
            self.assertNotIn("cambios de configuración", texto.lower().replace("cómo leer", ""))

    def _datos_pequenos(self) -> "consulta.DatosReporte":
        filas = [Fila(DIA_27_MS + i * 15_000, True, medida(2 * i + 1, 0), medida(2 * i + 2, 0)) for i in range(70)]
        return consulta.DatosReporte("27/10/2026", "27/10/2026", ZONA, DIA_27_MS, DIA_27_MS + 86_400_000,
                                     [{"nombre": "S1", "modelo": "P", "serie_etiqueta": None}] * 2, filas=filas)

    def test_el_logo_de_speal_esta_solo_en_la_primera_pagina(self) -> None:
        from pypdf import PdfReader
        self.assertTrue(pdf.LOGO.is_file())
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "a.pdf"
            pdf.dibujar(self._datos_pequenos(), pdf.Portada(NOMBRE, "", "0.1", DIA_27_MS), ruta)
            paginas = PdfReader(str(ruta)).pages
            self.assertEqual(len(paginas[0].images), 1)
            self.assertTrue(all(len(p.images) == 0 for p in paginas[1:]))
            # el nombre del equipo se corre a la izquierda del logo en la primera pagina; en las demas queda en el borde derecho
            posiciones = {}
            for n in (0, 1):
                paginas[n].extract_text(visitor_text=lambda texto, cm, tm, fd, fs, n=n:
                                        posiciones.__setitem__(n, tm[4]) if texto.startswith("Equipo ") else None)
            self.assertLess(posiciones[0], posiciones[1] - 40)

    def test_el_anexo_lista_los_cambios_de_estado_de_los_sensores(self) -> None:
        from pypdf import PdfReader
        datos = self._datos_pequenos()
        datos.cambios_sensor = [
            CambioSensor(DIA_27_MS + 60_000, 2, "apagado", repeticiones=2, ultimo_ms=DIA_27_MS + 90_000),
            CambioSensor(DIA_27_MS + 120_000, 2, "encendido"),
            CambioSensor(DIA_27_MS + 180_000, 1, "sin_senal", DIA_27_MS + 240_000),
            CambioSensor(DIA_27_MS + 300_000, 1, "sin_senal")]
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "a.pdf"
            pdf.dibujar(datos, pdf.Portada(NOMBRE, "", "0.1", DIA_27_MS), ruta)
            lector = PdfReader(str(ruta))
            texto = "\n".join(p.extract_text() for p in lector.pages)
        self.assertRegex(texto, r"Estado de sensores\s+4 cambios")                    # resumen de la primera pagina
        self.assertIn("Estado de los sensores", texto)
        self.assertRegex(texto, r"27/10 00:01:00\s+S2\s+Apagado \(2 veces; la última 27/10 00:01:30\)")
        self.assertRegex(texto, r"27/10 00:02:00\s+S2\s+Encendido")
        self.assertRegex(texto, r"27/10 00:03:00\s+S1\s+Sin señal \(hasta 27/10 00:04:00\)")
        self.assertRegex(texto, r"27/10 00:05:00\s+S1\s+Sin señal \(sigue sin señal\)")
        self.assertNotIn("Sin cambios de estado", texto)

    def test_si_falta_el_logo_el_reporte_sale_igual(self) -> None:
        from pypdf import PdfReader
        anterior = pdf.LOGO
        pdf.LOGO = Path("no-existe.png")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                ruta = Path(tmp) / "a.pdf"
                pdf.dibujar(self._datos_pequenos(), pdf.Portada(NOMBRE, "", "0.1", DIA_27_MS), ruta)
                lector = PdfReader(str(ruta))
                self.assertEqual(len(lector.pages[0].images), 0)
                self.assertIn("Resumen del reporte", lector.pages[0].extract_text())
        finally:
            pdf.LOGO = anterior

    def test_cifrar_sin_nombre_se_niega(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.pdf").write_bytes(b"%PDF-1.4")
            with self.assertRaisesRegex(pdf.ErrorReporte, "no tiene nombre"):
                pdf.cifrar(Path(tmp) / "a.pdf", Path(tmp) / "b.pdf", "")

    def test_cancelar_mientras_se_dibuja(self) -> None:
        filas = [Fila(DIA_27_MS + i * 1000, True, medida(2 * i, 0), medida(2 * i + 1, 0)) for i in range(300)]
        datos = consulta.DatosReporte("27/10/2026", "27/10/2026", ZONA, 0, 1,
                                      [{"nombre": "S1", "modelo": "P", "serie_etiqueta": None}] * 2, filas=filas)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(pdf.Cancelado):
                pdf.dibujar(datos, pdf.Portada(NOMBRE, "", "0.1", DIA_27_MS), Path(tmp) / "a.pdf", cancelado=lambda: True)


def lsblk(*volumenes) -> "FalsoResultado":
    """Salida de ``lsblk -J`` con los volumenes dados como (ruta, etiqueta, fstype, montaje, extraible)."""
    dispositivos = [{"path": r, "label": e, "fstype": f, "mountpoint": m, "rm": x, "hotplug": x,
                     "tran": "usb" if x else None, "type": "part"} for r, e, f, m, x in volumenes]
    return FalsoResultado(0, json.dumps({"blockdevices": dispositivos}))


class FalsoResultado:
    def __init__(self, codigo: int, salida: str = "") -> None:
        self.returncode, self.stdout, self.stderr = codigo, salida, ""


class EjecutorFalso:
    """Sustituye a ``lsblk`` y ``udisksctl``: devuelve lo que se le diga y anota los comandos."""

    def __init__(self, volumenes=(), punto: str = "") -> None:
        self.volumenes, self.punto, self.comandos, self.montaje_ok, self.desmontaje_ok = list(volumenes), punto, [], True, True

    def __call__(self, comando):
        self.comandos.append(comando)
        if comando[0] == "lsblk":
            return lsblk(*self.volumenes)
        if comando[:2] == ["udisksctl", "mount"]:
            return FalsoResultado(0 if self.montaje_ok else 1, f"Mounted {comando[3]} at {self.punto}.\n")
        if comando[:2] == ["udisksctl", "unmount"]:
            return FalsoResultado(0 if self.desmontaje_ok else 1)
        raise AssertionError(comando)


class PruebasUsb(unittest.TestCase):
    def test_encuentra_la_memoria_con_el_nombre_del_equipo(self) -> None:
        e = EjecutorFalso([("/dev/sda1", NOMBRE, "exfat", None, True)])
        self.assertEqual(usb.buscar(NOMBRE, e).ruta, "/dev/sda1")

    def test_no_distingue_mayusculas(self) -> None:
        e = EjecutorFalso([("/dev/sda1", NOMBRE.lower(), "exfat", None, True)])
        self.assertEqual(usb.buscar(NOMBRE, e).etiqueta, NOMBRE.lower())

    def test_sin_memoria_pide_insertarla(self) -> None:
        with self.assertRaisesRegex(usb.ErrorUsb, f"Inserte la memoria USB llamada «{NOMBRE}»"):
            usb.buscar(NOMBRE, EjecutorFalso())

    def test_una_memoria_con_otro_nombre_se_rechaza_y_dice_como_se_llama(self) -> None:
        e = EjecutorFalso([("/dev/sda1", "MIUSB", "exfat", None, True)])
        with self.assertRaisesRegex(usb.ErrorUsb, f"«MIUSB».*debe llamarse «{NOMBRE}»"):
            usb.buscar(NOMBRE, e)

    def test_un_disco_que_no_es_extraible_no_cuenta(self) -> None:
        e = EjecutorFalso([("/dev/mmcblk0p2", NOMBRE, "ext4", "/", False)])
        with self.assertRaises(usb.ErrorUsb):
            usb.buscar(NOMBRE, e)

    def test_la_tarjeta_sd_de_la_pi_no_es_una_memoria_usb(self) -> None:
        # la Pi declara su tarjeta SD como «extraible» (rm/hotplug = 1) pero su transporte no es usb (comprobado en la Pi)
        sd = {"path": "/dev/mmcblk0p2", "label": "rootfs", "fstype": "ext4", "mountpoint": "/", "rm": True,
              "hotplug": True, "tran": None, "type": "part"}
        boot = {**sd, "path": "/dev/mmcblk0p1", "label": "bootfs", "fstype": "vfat", "mountpoint": "/boot/firmware"}
        ejecutor = lambda _c: FalsoResultado(0, json.dumps({"blockdevices": [sd, boot]}))
        self.assertEqual(usb.listar(ejecutor), [])

    def test_el_transporte_usb_del_disco_vale_para_sus_particiones(self) -> None:
        disco = {"path": "/dev/sda", "label": None, "fstype": None, "mountpoint": None, "tran": "usb", "type": "disk",
                 "children": [{"path": "/dev/sda1", "label": NOMBRE, "fstype": "exfat", "mountpoint": None, "type": "part"}]}
        ejecutor = lambda _c: FalsoResultado(0, json.dumps({"blockdevices": [disco]}))
        self.assertEqual([p.ruta for p in usb.listar(ejecutor)], ["/dev/sda1"])

    def test_una_usb_sin_formato_reconocible_lo_dice_en_vez_de_pedir_insertarla(self) -> None:
        # caso real de la Pi: sda (tran usb) con sda1 sin FSTYPE ni LABEL
        disco = {"path": "/dev/sda", "label": None, "fstype": None, "mountpoint": None, "tran": "usb", "type": "disk",
                 "size": "3.8G", "children": [{"path": "/dev/sda1", "label": None, "fstype": None, "mountpoint": None,
                                                "type": "part", "size": "3.7G"}]}
        ejecutor = lambda _c: FalsoResultado(0, json.dumps({"blockdevices": [disco]}))
        self.assertEqual(usb.explorar(ejecutor), ([], 1))
        with self.assertRaisesRegex(usb.ErrorUsb, "formato legible"):
            usb.buscar(NOMBRE, ejecutor)

    def test_pide_a_lsblk_el_arbol_con_name_primero(self) -> None:
        # con otra columna primera lsblk entrega una lista plana y la particion pierde el transporte usb de su disco
        pedidos = []
        ejecutor = lambda c: (pedidos.append(c), FalsoResultado(0, json.dumps({"blockdevices": []})))[1]
        usb.explorar(ejecutor)
        self.assertEqual(pedidos[0][:3], ["lsblk", "-J", "-o"])
        self.assertTrue(pedidos[0][3].startswith("NAME,"))

    def test_memoria_ntfs_real_de_la_pi_ya_montada_por_el_escritorio(self) -> None:
        # salida real de lsblk en arbol: la particion no trae tran, lo hereda del disco
        disco = {"name": "sda", "path": "/dev/sda", "label": None, "fstype": None, "mountpoint": None, "rm": True,
                 "hotplug": False, "tran": "usb", "type": "disk", "size": "3.8G",
                 "children": [{"name": "sda1", "path": "/dev/sda1", "label": NOMBRE, "fstype": "ntfs",
                               "mountpoint": f"/media/pi/{NOMBRE}", "rm": True, "hotplug": False, "tran": None,
                               "type": "part", "size": "3.7G"}]}
        sd = {"name": "mmcblk0", "path": "/dev/mmcblk0", "fstype": None, "tran": "mmc", "type": "disk", "size": "14.8G",
              "children": [{"name": "mmcblk0p2", "path": "/dev/mmcblk0p2", "label": "rootfs", "fstype": "ext4",
                            "mountpoint": "/", "tran": "mmc", "type": "part"}]}
        ejecutor = lambda _c: FalsoResultado(0, json.dumps({"blockdevices": [disco, sd]}))
        self.assertEqual(usb.explorar(ejecutor)[1], 0)
        particion = usb.buscar(NOMBRE, ejecutor)
        self.assertEqual((particion.ruta, particion.fstype, particion.montaje), ("/dev/sda1", "ntfs", f"/media/pi/{NOMBRE}"))
        carpeta, montamos = usb.montar(particion, ejecutor)
        self.assertEqual((str(carpeta).replace("\\", "/"), montamos), (f"/media/pi/{NOMBRE}", False))   # ya estaba: se usa y no se desmonta

    def test_un_lector_de_tarjetas_vacio_no_cuenta_como_usb_sin_formato(self) -> None:
        lector = {"path": "/dev/sda", "label": None, "fstype": None, "mountpoint": None, "tran": "usb", "type": "disk",
                  "size": "0B"}
        ejecutor = lambda _c: FalsoResultado(0, json.dumps({"blockdevices": [lector]}))
        self.assertEqual(usb.explorar(ejecutor), ([], 0))
        with self.assertRaisesRegex(usb.ErrorUsb, "Inserte la memoria USB"):
            usb.buscar(NOMBRE, ejecutor)

    def test_la_tarjeta_sd_sin_formato_tampoco_cuenta(self) -> None:
        sd = {"path": "/dev/mmcblk0", "fstype": None, "mountpoint": None, "tran": "mmc", "type": "disk", "size": "14.8G"}
        ejecutor = lambda _c: FalsoResultado(0, json.dumps({"blockdevices": [sd]}))
        self.assertEqual(usb.explorar(ejecutor), ([], 0))

    def test_nunca_se_usa_un_volumen_montado_en_el_sistema_aunque_sea_usb(self) -> None:
        e = EjecutorFalso([("/dev/sda1", NOMBRE, "ext4", "/", True)])
        with self.assertRaises(usb.ErrorUsb):
            usb.buscar(NOMBRE, e)

    def test_en_fat_avisa_que_el_nombre_largo_no_cabe(self) -> None:
        e = EjecutorFalso([("/dev/sda1", "ANZD-000000", "vfat", None, True)])      # FAT corta el nombre a 11 letras
        with self.assertRaisesRegex(usb.ErrorUsb, "exFAT"):
            usb.buscar(NOMBRE, e)

    def test_monta_con_udisks_y_desmonta_lo_que_monto(self) -> None:
        e = EjecutorFalso([("/dev/sda1", NOMBRE, "exfat", None, True)], punto="/media/pi/ANZD")
        particion = usb.buscar(NOMBRE, e)
        carpeta, montamos = usb.montar(particion, e)
        self.assertEqual((str(carpeta).replace("\\", "/"), montamos), ("/media/pi/ANZD", True))
        self.assertTrue(usb.desmontar(particion, montamos, e))
        self.assertEqual(e.comandos[-1][:2], ["udisksctl", "unmount"])

    def test_si_ya_estaba_montada_se_usa_donde_esta_y_no_se_desmonta(self) -> None:
        e = EjecutorFalso([("/dev/sda1", NOMBRE, "exfat", "/media/pi/ANZD", True)])
        particion = usb.buscar(NOMBRE, e)
        carpeta, montamos = usb.montar(particion, e)
        self.assertFalse(montamos)
        usb.desmontar(particion, montamos, e)
        self.assertFalse(any(c[0] == "udisksctl" for c in e.comandos))

    def test_copiar_deja_el_archivo_y_su_huella_y_ningun_temporal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origen, destino = Path(tmp) / "o.pdf", Path(tmp) / "usb"
            destino.mkdir()
            origen.write_bytes(b"contenido del reporte" * 1000)
            final, huella = usb.copiar(origen, destino, "reporte.pdf")
            self.assertEqual(huella, hashlib.sha256(origen.read_bytes()).hexdigest())
            self.assertEqual(final.read_bytes(), origen.read_bytes())
            self.assertEqual((destino / "reporte.pdf.sha256").read_text(), f"{huella} *reporte.pdf\n")
            self.assertEqual(sorted(p.name for p in destino.iterdir()), ["reporte.pdf", "reporte.pdf.sha256"])

    def test_nunca_sobrescribe_un_reporte_anterior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origen, destino = Path(tmp) / "o.pdf", Path(tmp) / "usb"
            destino.mkdir()
            origen.write_bytes(b"x")
            usb.copiar(origen, destino, "reporte.pdf")
            final, _ = usb.copiar(origen, destino, "reporte.pdf")
            self.assertEqual(final.name, "reporte_2.pdf")
            self.assertTrue((destino / "reporte.pdf").exists())

    def test_sin_espacio_no_copia_nada(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origen, destino = Path(tmp) / "o.pdf", Path(tmp) / "usb"
            destino.mkdir()
            origen.write_bytes(b"x" * 100)
            anterior, usb.HOLGURA_ESPACIO = usb.HOLGURA_ESPACIO, 10 ** 15
            try:
                with self.assertRaisesRegex(usb.ErrorUsb, "espacio"):
                    usb.copiar(origen, destino, "reporte.pdf")
            finally:
                usb.HOLGURA_ESPACIO = anterior
            self.assertEqual(list(destino.iterdir()), [])


class PruebasTrabajo(BaseConBase):
    def correr(self, **kw) -> tuple[dict, list[dict]]:
        avisos: list[dict] = []
        kw.setdefault("destino", self.dir / "salida")
        kw.setdefault("ahora_ms", lambda: self.reloj.ahora_ms())
        resultado = trabajo.ejecutar(self.ruta, date(2026, 10, 27), date(2026, 10, 27), emitir=avisos.append,
                                     carpeta_tmp=self.dir / "tmp", **kw)
        return resultado, avisos

    def test_genera_un_pdf_cifrado_con_su_huella(self) -> None:
        from pypdf import PdfReader
        self.lecturas(10)
        resultado, avisos = self.correr()
        pdf_final = self.dir / "salida" / resultado["archivo"]
        self.assertEqual(resultado["sha256"], hashlib.sha256(pdf_final.read_bytes()).hexdigest())
        self.assertEqual((resultado["filas"], resultado["cadena_integra"]), (10, True))
        lector = PdfReader(str(pdf_final))
        self.assertTrue(lector.is_encrypted)
        self.assertGreater(lector.decrypt(NOMBRE), 0)
        self.assertEqual(len(lector.pages), resultado["paginas"])
        self.assertEqual([a["fase"] for a in avisos if a["fase"] in ("leyendo", "dibujando", "cifrando", "copiando", "listo")][0], "leyendo")
        self.assertEqual(avisos[-1]["fase"], "listo")
        self.assertEqual(sorted(p.name for p in (self.dir / "tmp").iterdir()), [])        # no deja el PDF sin cifrar

    def test_el_nombre_del_archivo_no_lleva_el_nombre_del_equipo(self) -> None:
        self.lecturas(2)
        resultado, _ = self.correr()
        self.assertNotIn(NOMBRE, resultado["archivo"])
        self.assertRegex(resultado["archivo"], r"^G2_reporte_2026-10-27_a_2026-10-27_20261027-\d{4}\.pdf$")

    def test_el_avance_nunca_retrocede_y_llega_a_100(self) -> None:
        self.lecturas(200)
        _, avisos = self.correr()
        progresos = [a["progreso"] for a in avisos]
        self.assertEqual(progresos, sorted(progresos))
        self.assertEqual(progresos[-1], 100)

    def test_sin_nombre_del_equipo_se_niega(self) -> None:
        self.lecturas(2)
        self.a.config_fijar("equipo.nombre", "", origen="local", actor="prueba")
        with self.assertRaisesRegex(pdf.ErrorReporte, "nombre del equipo"):
            self.correr()
        self.assertFalse((self.dir / "salida").exists())

    def test_sin_registros_en_el_rango(self) -> None:
        with self.assertRaisesRegex(rango.ErrorRango, "No hay registros"):
            self.correr()

    def test_con_usb_de_otro_nombre_se_para_antes_de_dibujar(self) -> None:
        self.lecturas(5)
        avisos: list[dict] = []
        e = EjecutorFalso([("/dev/sda1", "OTRA", "exfat", None, True)])
        with self.assertRaisesRegex(usb.ErrorUsb, "debe llamarse"):
            trabajo.ejecutar(self.ruta, date(2026, 10, 27), date(2026, 10, 27), emitir=avisos.append, ejecutor=e,
                             carpeta_tmp=self.dir / "tmp", ahora_ms=self.reloj.ahora_ms)
        self.assertNotIn("dibujando", [a["fase"] for a in avisos])
        self.assertFalse(any(c[:2] == ["udisksctl", "mount"] for c in e.comandos))

    def test_con_usb_correcta_la_monta_copia_y_desmonta(self) -> None:
        self.lecturas(5)
        punto = self.dir / "media"
        punto.mkdir()
        e = EjecutorFalso([("/dev/sda1", NOMBRE, "exfat", None, True)], punto=str(punto))
        avisos: list[dict] = []
        resultado = trabajo.ejecutar(self.ruta, date(2026, 10, 27), date(2026, 10, 27), emitir=avisos.append, ejecutor=e,
                                     carpeta_tmp=self.dir / "tmp", ahora_ms=self.reloj.ahora_ms)
        self.assertTrue((punto / resultado["archivo"]).exists())
        self.assertTrue((punto / f"{resultado['archivo']}.sha256").exists())
        self.assertEqual([c[1] for c in e.comandos if c[0] == "udisksctl"], ["mount", "unmount"])
        self.assertTrue(resultado["desmontada"])

    def test_aunque_la_copia_falle_se_desmonta_la_memoria(self) -> None:
        self.lecturas(5)
        e = EjecutorFalso([("/dev/sda1", NOMBRE, "exfat", None, True)], punto=str(self.dir / "no_existe"))
        with self.assertRaises(usb.ErrorUsb):
            trabajo.ejecutar(self.ruta, date(2026, 10, 27), date(2026, 10, 27), emitir=lambda _a: None, ejecutor=e,
                             carpeta_tmp=self.dir / "tmp", ahora_ms=self.reloj.ahora_ms)
        self.assertEqual(e.comandos[-1][:2], ["udisksctl", "unmount"])

    def test_cancelar_no_deja_nada_en_la_memoria(self) -> None:
        self.lecturas(200)
        veces = [0]

        def cancelado() -> bool:
            veces[0] += 1
            return veces[0] > 4                                                           # a mitad del camino

        with self.assertRaises(trabajo.Cancelado):
            self.correr(cancelado=cancelado)
        self.assertFalse((self.dir / "salida").exists() and any((self.dir / "salida").iterdir()))

    def test_si_la_cadena_de_auditoria_esta_alterada_el_reporte_lo_dice(self) -> None:
        from pypdf import PdfReader
        self.lecturas(3)
        alarma_id = self.a.abrir_alarma("ALM_O2_ALTO", sensor_id=self.s1, umbral=92.0, valor=95.0)
        for disparador in ("tr_alarma_rev_auto", "tr_alarma_encolar_rev", "tr_alarma_cadena_rev"):
            self.a.db.execute(f"DROP TRIGGER {disparador}")                   # quien manipula el archivo se salta las protecciones
        self.a.db.execute("UPDATE alarma SET valor_disparo = 99.9 WHERE id = ?", (alarma_id,))
        resultado, _ = self.correr()
        self.assertFalse(resultado["cadena_integra"])
        lector = PdfReader(str(self.dir / "salida" / resultado["archivo"]))
        lector.decrypt(NOMBRE)
        self.assertIn("CADENA ALTERADA", lector.pages[0].extract_text())

    def test_con_la_cadena_integra_lo_dice(self) -> None:
        from pypdf import PdfReader
        self.lecturas(3)
        resultado, _ = self.correr()
        lector = PdfReader(str(self.dir / "salida" / resultado["archivo"]))
        lector.decrypt(NOMBRE)
        self.assertIn("íntegra", lector.pages[0].extract_text())


class ProcesoFalso:
    """Un Popen que entrega lineas de salida y un codigo de salida."""

    def __init__(self, lineas: list[str], codigo: int = 0) -> None:
        self.stdout = io.StringIO("".join(l + "\n" for l in lineas))
        self.codigo, self.terminado = codigo, False

    def wait(self, timeout=None):
        return self.codigo

    def poll(self):
        return self.codigo if self.terminado else None

    def terminate(self):
        self.terminado = True

    def kill(self):
        self.terminado = True


def lineas_ok() -> list[str]:
    resultado = {"archivo": "G2_reporte.pdf", "sha256": "ab" * 32, "filas": 10, "paginas": 3, "cadena_integra": True,
                 "desmontada": True, "desde": "27/10/2026", "hasta": "27/10/2026"}
    return [json.dumps({"fase": "usb", "progreso": 2, "mensaje": "Buscando"}),
            json.dumps({"fase": "dibujando", "progreso": 50, "mensaje": "Dibujando 50 %"}),
            "ruido que no es json",
            json.dumps({"fase": "resultado", "progreso": 100, "mensaje": "Reporte listo", "resultado": resultado})]


class PruebasServicioReportes(unittest.TestCase):
    def servicio(self, proceso: ProcesoFalso, **kw) -> ServicioReportes:
        self.lanzados = []

        def lanzar(ruta, desde, hasta):
            self.lanzados.append((desde, hasta))
            return proceso

        return ServicioReportes(Path("g2.db"), lanzar=lanzar, **kw)

    def esperar(self, s: ServicioReportes) -> None:
        s._hilo.join(timeout=5)

    def test_un_reporte_terminado_deja_su_resultado_una_sola_vez(self) -> None:
        s = self.servicio(ProcesoFalso(lineas_ok()))
        self.assertTrue(s.iniciar("2026-10-27", "2026-10-27"))
        self.esperar(s)
        r = s.resultado_pendiente()
        self.assertEqual((r["ok"], r["archivo"], r["filas"], r["numero"]), (True, "G2_reporte.pdf", 10, 1))
        self.assertIsNone(s.resultado_pendiente())
        self.assertEqual(s.estado()["ultimo"]["numero"], 1)
        self.assertFalse(s.estado()["en_curso"])

    def test_solo_un_reporte_a_la_vez(self) -> None:
        proceso = ProcesoFalso([])
        proceso.stdout = _Bloqueado()
        s = self.servicio(proceso)
        self.assertTrue(s.iniciar("2026-10-27", "2026-10-27"))
        self.assertFalse(s.iniciar("2026-10-26", "2026-10-26"))
        self.assertEqual(len(self.lanzados), 1)
        self.assertTrue(s.estado()["en_curso"])
        proceso.stdout.liberar()
        self.esperar(s)

    def test_el_avance_se_publica_mientras_corre(self) -> None:
        proceso = ProcesoFalso([])
        proceso.stdout = _Bloqueado(lineas_ok()[:2])
        s = self.servicio(proceso)
        s.iniciar("2026-10-27", "2026-10-27")
        proceso.stdout.esperar_lineas()
        e = s.estado()
        self.assertEqual((e["fase"], e["progreso"], e["mensaje"]), ("dibujando", 50, "Dibujando 50 %"))
        proceso.stdout.liberar()
        self.esperar(s)

    def test_un_error_del_reporte_trae_su_motivo(self) -> None:
        s = self.servicio(ProcesoFalso([json.dumps({"fase": "error", "mensaje": "La memoria USB se llama «X»"})], 1))
        s.iniciar("2026-10-27", "2026-10-27")
        self.esperar(s)
        r = s.resultado_pendiente()
        self.assertEqual((r["ok"], r["cancelado"], r["mensaje"]), (False, False, "La memoria USB se llama «X»"))

    def test_un_proceso_que_muere_sin_avisar_es_un_error(self) -> None:
        s = self.servicio(ProcesoFalso([], 139))
        s.iniciar("2026-10-27", "2026-10-27")
        self.esperar(s)
        r = s.resultado_pendiente()
        self.assertFalse(r["ok"])
        self.assertIn("139", r["mensaje"])

    def test_cancelar_marca_el_resultado_como_cancelado(self) -> None:
        proceso = ProcesoFalso([])
        proceso.stdout = _Bloqueado()
        s = self.servicio(proceso)
        s.iniciar("2026-10-27", "2026-10-27")
        self.assertTrue(s.cancelar())
        self.assertTrue(proceso.terminado)
        proceso.stdout.liberar()
        self.esperar(s)
        r = s.resultado_pendiente()
        self.assertEqual((r["ok"], r["cancelado"]), (False, True))
        self.assertFalse(s.cancelar())                                           # ya no hay nada que cancelar

    def test_un_reporte_que_se_cuelga_se_mata(self) -> None:
        t = [0.0]
        proceso = ProcesoFalso([])
        proceso.stdout = _Bloqueado()
        s = self.servicio(proceso, mono=lambda: t[0], tiempo_maximo_s=60)
        s.iniciar("2026-10-27", "2026-10-27")
        s.vigilar()
        self.assertFalse(proceso.terminado)
        t[0] = 61
        s.vigilar()
        self.assertTrue(proceso.terminado)
        proceso.stdout.liberar()
        self.esperar(s)


class _Bloqueado:
    """Una salida que entrega unas lineas y luego espera a que se la libere (el proceso 'sigue corriendo')."""

    def __init__(self, lineas: list[str] | None = None) -> None:
        import threading
        self._lineas, self._leidas, self._libre = list(lineas or []), threading.Event(), threading.Event()
        if not self._lineas:
            self._leidas.set()

    def __iter__(self):
        for l in self._lineas:
            yield l + "\n"
        self._leidas.set()
        self._libre.wait(timeout=5)

    def esperar_lineas(self) -> None:
        self._leidas.wait(timeout=5)
        import time
        time.sleep(0.05)

    def liberar(self) -> None:
        self._libre.set()


class ServicioFalso:
    """Sustituye al servicio de reportes en las pruebas del nucleo."""

    def __init__(self) -> None:
        self.llamadas, self.ocupado, self.pendiente, self.canceladas = [], False, None, 0

    def iniciar(self, desde, hasta):
        if self.ocupado:
            return False
        self.llamadas.append((desde, hasta))
        self.ocupado = True
        return True

    def cancelar(self):
        self.canceladas += 1
        return self.ocupado

    def vigilar(self):
        pass

    def resultado_pendiente(self):
        r, self.pendiente = self.pendiente, None
        if r is not None:
            self.ocupado = False
        return r

    def estado(self):
        return {"en_curso": self.ocupado, "ultimo": None}

    def detener(self):
        pass


class PruebasOrdenesDeReporte(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.reloj = RelojPrueba(ahora_ms=DIA_27_MS + 3_600_000)
        self.a = Almacen.abrir(Path(self._tmp.name) / "g2.db", self.reloj)
        self.a.registrar_sensor(canal="ads1263:0-1", nombre="Sensor 1", modelo="P", mv_por_pct=10.0)
        self.servicio = ServicioFalso()
        self.n = Nucleo(self.a, FuenteSimulada({"ads1263:0-1": 0.209}), mono=lambda: 0.0, servicio_reportes=self.servicio)
        self.n.iniciar()
        self.a.config_fijar("equipo.nombre", NOMBRE, origen="local", actor="prueba")

    def tearDown(self) -> None:
        self.a.cerrar()
        self._tmp.cleanup()

    def orden(self, uuid, tipo, **datos) -> None:
        self.n.procesar_orden({"uuid": uuid, "tipo": tipo, "origen": "pantalla", "actor": "pantalla", **datos})

    def comando(self):
        return self.a.db.execute("SELECT estado, resultado_json FROM comando ORDER BY id DESC LIMIT 1").fetchone()

    def eventos(self, codigo):
        return self.a.db.execute("SELECT * FROM evento WHERE codigo = ?", (codigo,)).fetchall()

    def resultado(self, **extra) -> dict:
        return {"ok": True, "desde": "2026-10-27", "hasta": "2026-10-27", "archivo": "G2_reporte.pdf",
                "sha256": "ab" * 32, "filas": 10, "paginas": 3, "cadena_integra": True, "desmontada": True,
                "mensaje": "Reporte copiado a la memoria USB", "numero": 1, **extra}

    def test_una_orden_valida_lanza_el_reporte_y_deja_el_comando_en_curso(self) -> None:
        self.orden("r1", "reporte_generar", desde="2026-10-27", hasta="2026-10-27")
        self.assertEqual(self.servicio.llamadas, [("2026-10-27", "2026-10-27")])
        self.assertEqual(self.comando()["estado"], "recibido")

    def test_al_terminar_registra_el_evento_con_la_huella_y_cierra_el_comando(self) -> None:
        self.orden("r1", "reporte_generar", desde="2026-10-27", hasta="2026-10-27")
        self.servicio.pendiente = self.resultado()
        self.n.paso()
        (e,) = self.eventos("REPORTE_GENERADO")
        self.assertEqual(json.loads(e["datos_json"])["sha256"], "ab" * 32)
        self.assertEqual(self.comando()["estado"], "ok")

    def test_un_error_queda_como_evento_fallido_con_su_motivo(self) -> None:
        self.orden("r1", "reporte_generar", desde="2026-10-27", hasta="2026-10-27")
        self.servicio.pendiente = {"ok": False, "cancelado": False, "desde": "2026-10-27", "hasta": "2026-10-27",
                                   "mensaje": "La memoria USB se llama «X»", "numero": 1}
        self.n.paso()
        (e,) = self.eventos("REPORTE_FALLIDO")
        self.assertIn("«X»", e["mensaje"])
        self.assertEqual(self.comando()["estado"], "error")

    def test_cancelado_queda_como_evento_cancelado(self) -> None:
        self.orden("r1", "reporte_generar", desde="2026-10-27", hasta="2026-10-27")
        self.servicio.pendiente = {"ok": False, "cancelado": True, "desde": "2026-10-27", "hasta": "2026-10-27",
                                   "mensaje": "Reporte cancelado", "numero": 1}
        self.n.paso()
        self.assertEqual(len(self.eventos("REPORTE_CANCELADO")), 1)

    def test_se_rechazan_las_ordenes_con_fechas_malas(self) -> None:
        casos = {"mala": ("ayer", "hoy"), "futuro": ("2099-01-01", "2099-01-01"), "largo": ("2026-10-10", "2026-10-27"),
                 "invertido": ("2026-10-27", "2026-10-26")}
        for uuid, (desde, hasta) in casos.items():
            self.orden(uuid, "reporte_generar", desde=desde, hasta=hasta)
            self.assertEqual(self.comando()["estado"], "rechazado", uuid)
        self.assertEqual(self.servicio.llamadas, [])

    def test_sin_nombre_del_equipo_se_rechaza(self) -> None:
        self.a.config_fijar("equipo.nombre", "", origen="local", actor="prueba")
        self.orden("r1", "reporte_generar", desde="2026-10-27", hasta="2026-10-27")
        self.assertEqual(self.comando()["estado"], "rechazado")
        self.assertIn("nombre", self.comando()["resultado_json"])

    def test_no_acepta_otro_mientras_hay_uno_en_curso(self) -> None:
        self.orden("r1", "reporte_generar", desde="2026-10-27", hasta="2026-10-27")
        self.orden("r2", "reporte_generar", desde="2026-10-27", hasta="2026-10-27")
        self.assertEqual(self.comando()["estado"], "rechazado")
        self.assertEqual(len(self.servicio.llamadas), 1)

    def test_cancelar_pide_parar_el_reporte(self) -> None:
        self.orden("r1", "reporte_generar", desde="2026-10-27", hasta="2026-10-27")
        self.orden("c1", "reporte_cancelar")
        self.assertEqual(self.servicio.canceladas, 1)
        self.assertEqual(self.comando()["estado"], "ok")

    def test_cancelar_sin_reporte_en_curso_se_rechaza(self) -> None:
        self.orden("c1", "reporte_cancelar")
        self.assertEqual(self.comando()["estado"], "rechazado")

    def test_el_estado_publicado_lleva_el_reporte(self) -> None:
        self.assertEqual(self.n.estado_pantalla()["reporte"], {"en_curso": False, "ultimo": None})

    def test_el_evento_no_lleva_la_contrasena_ni_el_nombre_del_equipo(self) -> None:
        self.orden("r1", "reporte_generar", desde="2026-10-27", hasta="2026-10-27")
        self.servicio.pendiente = self.resultado()
        self.n.paso()
        (e,) = self.eventos("REPORTE_GENERADO")
        self.assertNotIn(NOMBRE, e["datos_json"] + (e["mensaje"] or ""))


class PruebasTextoDeCalibracion(unittest.TestCase):
    BASE = {"id": 1, "ts_ms": 1_793_000_000_000, "sensor_id": 1, "tipo": "puntos", "gas_pct": 98.0, "gas_certificado": None,
            "offset_pct": -0.2, "resultado": "ok", "vigente": 1, "actor": "pantalla", "ganancia": 1.0051,
            "bajo_ref_pct": 0.0, "alto_ref_pct": 98.0}

    def test_una_calibracion_por_puntos_dice_ganancia_cero_y_los_dos_gases(self) -> None:
        texto = pdf.texto_calibracion(self.BASE, "America/Bogota")
        self.assertIn("Sensor 1: puntos el ", texto)
        self.assertIn("ganancia 1.005 · cero -0.20 %", texto)
        self.assertIn("gas bajo 0 % · gas alto 98 %", texto)
        self.assertTrue(texto.endswith("· pantalla"))

    def test_un_punto_sin_medir_se_dice(self) -> None:
        texto = pdf.texto_calibracion({**self.BASE, "alto_ref_pct": None, "ganancia": None}, "America/Bogota")
        self.assertIn("gas alto sin medir", texto)
        self.assertIn("ganancia 1.000", texto)

    def test_las_calibraciones_anteriores_se_leen_como_antes(self) -> None:
        texto = pdf.texto_calibracion({**self.BASE, "tipo": "offset_cero", "gas_pct": 20.9, "ganancia": None}, "America/Bogota")
        self.assertIn("offset_cero", texto)
        self.assertIn("gas 20.9 % · cero -0.2 %", texto)


if __name__ == "__main__":
    unittest.main()
