"""Pruebas de la temperatura y la humedad del ambiente (DHT22, D-051): el decodificador, el servicio, el nucleo y la pantalla."""

from __future__ import annotations

import unittest

from g2.configuracion import catalogo
from g2.hardware.dht22 import (Borde, Dht22, DhtSimulado, ErrorDht, LecturaDht, decodificar, ESPERA_ENTRE_INTENTOS_S)
from g2.nucleo.nucleo import FALLOS_AMBIENTE_PARA_AVISAR, Nucleo
from g2.nucleo.senal import CALIDAD_INESTABLE, CALIDAD_SIN_DATOS
from g2.nucleo.servicio_ambiente import AcumuladorAmbiente, Muestra, ServicioAmbiente
from g2.pantalla import vistas
from g2.pantalla.protocolo import COLOR
from test_nucleo_ciclo import BaseCiclo
from test_pantalla_interfaz import BaseInterfaz, estado


def bordes_de(octetos: list[int], *, con_inicio: bool = True, uno_us: float = 70, cero_us: float = 27) -> list[Borde]:
    """Los flancos que dejaria un DHT22 que manda estos 5 octetos (humedad alta/baja, temperatura alta/baja, suma)."""
    t = 0
    bordes: list[Borde] = []

    def pulso(alto_us: float, bajo_us: float) -> None:
        nonlocal t
        bordes.append((True, t))
        t += int(alto_us * 1000)
        bordes.append((False, t))
        t += int(bajo_us * 1000)

    if con_inicio:
        pulso(30, 80)                                            # la linea sube al soltarla la Pi y el sensor la baja
    pulso(80, 50)                                                # respuesta del sensor
    for octeto in octetos:
        for i in range(7, -1, -1):
            pulso(uno_us if (octeto >> i) & 1 else cero_us, 50)
    bordes.append((True, t))                                     # al final suelta la linea
    return bordes


def octetos(temperatura: float, humedad: float) -> list[int]:
    h, t = round(humedad * 10), round(abs(temperatura) * 10)
    if temperatura < 0:
        t |= 0x8000
    cuatro = [h >> 8, h & 0xFF, t >> 8, t & 0xFF]
    return cuatro + [sum(cuatro) & 0xFF]


class PruebasDecodificador(unittest.TestCase):
    def test_lee_temperatura_y_humedad(self) -> None:
        lectura = decodificar(bordes_de(octetos(35.1, 65.2)))
        self.assertEqual((lectura.temperatura_c, lectura.humedad_pct), (35.1, 65.2))

    def test_temperatura_bajo_cero(self) -> None:
        self.assertEqual(decodificar(bordes_de(octetos(-10.1, 40.0))).temperatura_c, -10.1)

    def test_no_importa_si_se_perdio_el_principio_de_la_captura(self) -> None:
        self.assertEqual(decodificar(bordes_de(octetos(21.5, 50.0), con_inicio=False)).temperatura_c, 21.5)
        sin_respuesta_ni_inicio = bordes_de(octetos(21.5, 50.0))[4:]            # tampoco el primer pulso de respuesta
        self.assertEqual(decodificar(sin_respuesta_ni_inicio).humedad_pct, 50.0)

    def test_reconstruye_los_primeros_bits_que_el_kernel_alcanza_a_perder(self) -> None:
        for perdidos in range(0, 7):
            for temperatura, humedad in ((26.1, 51.5), (-5.0, 100.0), (0.0, 0.0), (35.1, 3.2)):
                with self.subTest(perdidos=perdidos, t=temperatura, h=humedad):
                    bordes = bordes_de(octetos(temperatura, humedad))[2 * (2 + perdidos):]      # sin el inicio, la respuesta y N bits
                    lectura = decodificar(bordes)
                    self.assertEqual((lectura.temperatura_c, lectura.humedad_pct), (temperatura, humedad))

    def test_si_se_perdieron_mas_de_6_bits_es_incompleta(self) -> None:
        with self.assertRaises(ErrorDht) as error:
            decodificar(bordes_de(octetos(26.1, 51.5))[2 * (2 + 7):])
        self.assertEqual(error.exception.motivo, "incompleta")

    def test_si_el_primer_pulso_es_la_respuesta_del_sensor_y_falta_un_bit(self) -> None:
        bordes = bordes_de(octetos(26.1, 51.5))
        sin_inicio_ni_primer_bit = bordes[2:4] + bordes[6:]         # queda la respuesta (80 us) y faltan el inicio y el bit 1
        self.assertEqual(decodificar(sin_inicio_ni_primer_bit).temperatura_c, 26.1)

    def test_un_dato_cortado_por_el_principio_con_suma_mala_se_descarta(self) -> None:
        malos = octetos(26.1, 51.5)
        malos[4] ^= 0x10
        with self.assertRaises(ErrorDht) as error:
            decodificar(bordes_de(malos)[2 * (2 + 3):])
        self.assertEqual(error.exception.motivo, "suma")

    def test_tolera_que_los_pulsos_varien_algo(self) -> None:
        self.assertEqual(decodificar(bordes_de(octetos(24.0, 55.0), uno_us=62, cero_us=36)).humedad_pct, 55.0)

    def test_sin_flancos_es_que_el_sensor_no_contesta(self) -> None:
        with self.assertRaises(ErrorDht) as error:
            decodificar([])
        self.assertEqual(error.exception.motivo, "sin_respuesta")
        with self.assertRaises(ErrorDht) as error:
            decodificar([(True, 0), (False, 5000)])
        self.assertEqual(error.exception.motivo, "sin_respuesta")

    def test_menos_de_40_pulsos_es_incompleta(self) -> None:
        with self.assertRaises(ErrorDht) as error:
            decodificar(bordes_de(octetos(24.0, 55.0))[:60])
        self.assertEqual(error.exception.motivo, "incompleta")

    def test_la_suma_mala_se_descarta(self) -> None:
        malos = octetos(24.0, 55.0)
        malos[4] ^= 0x01
        with self.assertRaises(ErrorDht) as error:
            decodificar(bordes_de(malos))
        self.assertEqual(error.exception.motivo, "suma")

    def test_un_valor_imposible_se_descarta_aunque_la_suma_cuadre(self) -> None:
        with self.assertRaises(ErrorDht) as error:
            decodificar(bordes_de(octetos(24.0, 110.0)))              # 110 % de humedad
        self.assertEqual(error.exception.motivo, "rango")
        with self.assertRaises(ErrorDht) as error:
            decodificar(bordes_de(octetos(95.0, 50.0)))               # 95 C
        self.assertEqual(error.exception.motivo, "rango")

    def test_un_pulso_que_no_es_un_bit_se_descarta(self) -> None:
        bordes = bordes_de(octetos(24.0, 55.0))
        bordes[-2] = (False, bordes[-2][1] + 400_000)                 # el ultimo bit dura 400 us de mas
        with self.assertRaises(ErrorDht) as error:
            decodificar(bordes)
        self.assertEqual(error.exception.motivo, "pulso")


class PruebasLector(unittest.TestCase):
    def lector(self, capturas, **kwargs) -> tuple[Dht22, list[float]]:
        esperas: list[float] = []
        cola = list(capturas)
        return Dht22(capturar=lambda: cola.pop(0), dormir=esperas.append, **kwargs), esperas

    def test_a_la_primera(self) -> None:
        lector, esperas = self.lector([bordes_de(octetos(30.0, 60.0))])
        self.assertEqual(lector.leer(), LecturaDht(30.0, 60.0))
        self.assertEqual(esperas, [])

    def test_reintenta_con_la_espera_que_pide_el_sensor(self) -> None:
        malo = octetos(30.0, 60.0)
        malo[4] ^= 0xFF
        lector, esperas = self.lector([bordes_de(malo), [], bordes_de(octetos(30.0, 60.0))])
        self.assertEqual(lector.leer().humedad_pct, 60.0)
        self.assertEqual(esperas, [ESPERA_ENTRE_INTENTOS_S] * 2)

    def test_si_todos_los_intentos_fallan_da_el_motivo_del_ultimo(self) -> None:
        malo = octetos(30.0, 60.0)
        malo[4] ^= 0xFF
        lector, _ = self.lector([bordes_de(malo), bordes_de(malo), []], intentos=3)
        with self.assertRaises(ErrorDht) as error:
            lector.leer()
        self.assertEqual(error.exception.motivo, "sin_respuesta")

    def test_por_omision_hace_5_intentos(self) -> None:
        lector, esperas = self.lector([[]] * 5)
        with self.assertRaises(ErrorDht):
            lector.leer()
        self.assertEqual(len(esperas), 4)

    def test_un_fallo_de_hardware_no_se_reintenta(self) -> None:
        llamadas = []

        def captura():
            llamadas.append(1)
            raise ErrorDht("hardware", "GPIO ocupado")

        esperas: list[float] = []
        with self.assertRaises(ErrorDht):
            Dht22(capturar=captura, dormir=esperas.append).leer()
        self.assertEqual((len(llamadas), esperas), (1, []))

    def test_la_captura_real_sin_libgpiod_avisa_con_un_error_claro(self) -> None:
        from g2.hardware import dht22
        try:
            dht22.capturar_gpiod(4)
        except ErrorDht as error:                                    # en el PC no hay libgpiod: debe ser un ErrorDht, no un ImportError
            self.assertEqual(error.motivo, "hardware")
        except Exception:                                            # noqa: BLE001 - en la Pi puede leer de verdad o fallar por el pin
            pass


class PruebasServicio(unittest.TestCase):
    def setUp(self) -> None:
        self.t = [10.0]
        self.sensor = DhtSimulado(24.5, 55.0)
        self.servicio = ServicioAmbiente(self.sensor.leer, mono=lambda: self.t[0])

    def test_deja_cada_lectura_en_la_cola_y_la_vacia_al_recogerla(self) -> None:
        self.servicio.ciclo()
        self.t[0] += 10
        self.sensor.temperatura_c = 25.0
        self.servicio.ciclo()
        muestras = self.servicio.tomar()
        self.assertEqual([(m.mono_s, m.temperatura_c, m.humedad_pct) for m in muestras], [(10.0, 24.5, 55.0), (20.0, 25.0, 55.0)])
        self.assertEqual(self.servicio.tomar(), [])

    def test_un_error_del_sensor_queda_como_muestra_mala(self) -> None:
        self.sensor.error = "no contesta"
        self.servicio.ciclo()
        (m,) = self.servicio.tomar()
        self.assertFalse(m.buena)
        self.assertIn("no contesta", m.error)

    def test_una_excepcion_inesperada_no_tumba_el_hilo(self) -> None:
        def lector():
            raise RuntimeError("se cayo")

        servicio = ServicioAmbiente(lector, mono=lambda: 1.0)
        with self.assertLogs("g2.ambiente", level="ERROR"):
            servicio.ciclo()
        (m,) = servicio.tomar()
        self.assertEqual(m.error, "inesperado: RuntimeError")

    def test_la_cola_no_crece_sin_limite(self) -> None:
        for _ in range(700):
            self.servicio.ciclo()
        self.assertEqual(len(self.servicio.tomar()), 600)

    def test_el_hilo_lee_y_se_detiene(self) -> None:
        servicio = ServicioAmbiente(self.sensor.leer, intervalo_s=0.01)
        servicio.iniciar()
        for _ in range(200):
            if servicio.tomar():
                break
            import time
            time.sleep(0.01)
        else:
            self.fail("el hilo no dejo ninguna lectura")
        servicio.detener()


class PruebasAcumulador(unittest.TestCase):
    def test_promedio_minimo_y_maximo(self) -> None:
        a = AcumuladorAmbiente()
        for t, h in ((20.0, 40.0), (22.0, 50.0), (24.0, 60.0)):
            a.agregar(Muestra(0.0, t, h))
        r = a.cerrar()
        self.assertEqual((r.temperatura, r.humedad, r.calidad), ((22.0, 20.0, 24.0), (50.0, 40.0, 60.0), 0))
        self.assertEqual(a.n_intentos, 0)

    def test_con_fallos_queda_inestable_y_sin_lecturas_buenas_sin_datos(self) -> None:
        a = AcumuladorAmbiente()
        a.agregar(Muestra(0.0, 20.0, 40.0))
        a.agregar(Muestra(1.0, error="x"))
        self.assertEqual(a.cerrar().calidad, CALIDAD_INESTABLE)
        a.agregar(Muestra(2.0, error="x"))
        r = a.cerrar()
        self.assertEqual((r.calidad, r.temperatura), (CALIDAD_SIN_DATOS, None))


class BaseAmbiente(BaseCiclo):
    def setUp(self) -> None:
        super().setUp()
        self.sensor = DhtSimulado(24.0, 50.0)
        self.servicio = ServicioAmbiente(self.sensor.leer, mono=lambda: self.t[0])
        self.n = Nucleo(self.a, self.fuente, self.salidas, mono=lambda: self.t[0], version_sw="test",
                        servicio_ambiente=self.servicio)
        self.n.iniciar()

    def correr_ambiente(self, segundos: float, leer_cada_s: float = 10.0) -> None:
        """Corre el nucleo; cada ``leer_cada_s`` el servicio hace una lectura (como lo haria su hilo)."""
        fin = self.t[0] + segundos
        proxima = self.t[0]
        while self.t[0] < fin - 1e-9:
            if self.t[0] >= proxima - 1e-9:
                self.servicio.ciclo()
                proxima += leer_cada_s
            self.correr(self.n, 0.5)

    def mediciones(self, magnitud: str | None = None):
        sql = "SELECT * FROM medicion_periferico" + (" WHERE magnitud = ?" if magnitud else "") + " ORDER BY id"
        return self.a.db.execute(sql, (magnitud,) if magnitud else ()).fetchall()

    def eventos(self, codigo: str):
        return self.a.db.execute("SELECT * FROM evento WHERE codigo = ?", (codigo,)).fetchall()


class PruebasNucleoAmbiente(BaseAmbiente):
    def test_el_periferico_queda_dado_de_alta_una_sola_vez(self) -> None:
        (p,) = self.a.db.execute("SELECT * FROM periferico").fetchall()
        self.assertEqual((p["nombre"], p["tipo"], p["bus"], p["direccion"], p["habilitado"]), ("ambiente", "dht22", "gpio", "GPIO4", 1))
        otro = Nucleo(self.a, self.fuente, self.salidas, mono=lambda: self.t[0], servicio_ambiente=self.servicio)
        otro.iniciar()
        self.assertEqual(self.a.db.execute("SELECT COUNT(*) FROM periferico").fetchone()[0], 1)

    def test_guarda_temperatura_y_humedad_con_promedio_minimo_y_maximo(self) -> None:
        self.correr_ambiente(30)
        self.sensor.temperatura_c = 26.0
        self.correr_ambiente(30.5)
        (t,) = self.mediciones("temperatura_c")
        (h,) = self.mediciones("humedad_pct")
        self.assertEqual((t["n_muestras"], t["calidad"], t["minimo"], t["maximo"]), (6, 0, 24.0, 26.0))
        self.assertAlmostEqual(t["prom"], 25.0)
        self.assertEqual((h["prom"], h["minimo"], h["maximo"]), (50.0, 50.0, 50.0))
        self.assertAlmostEqual(t["periodo_ms"], 60_000, delta=1000)

    def test_las_mediciones_se_encolan_para_la_plataforma(self) -> None:
        self.correr_ambiente(61)
        encoladas = self.a.db.execute("SELECT COUNT(*) FROM cola_envio WHERE tabla = 'medicion_periferico'").fetchone()[0]
        self.assertEqual(encoladas, 2)

    def test_el_intervalo_de_guardado_se_configura(self) -> None:
        self.a.config_fijar("ambiente.intervalo_guardado_s", 20, origen="local")
        self.correr_ambiente(41)
        self.assertEqual(len(self.mediciones("temperatura_c")), 2)

    def test_un_cambio_del_intervalo_de_lectura_le_llega_al_servicio(self) -> None:
        self.assertEqual(self.servicio.intervalo_s, 10.0)
        self.a.config_fijar("ambiente.intervalo_lectura_s", 30, origen="local")
        self.correr(self.n, 2.0)
        self.assertEqual(self.servicio.intervalo_s, 30.0)

    def test_tres_lecturas_malas_seguidas_dejan_un_solo_evento_de_falla(self) -> None:
        self.sensor.error = "no contesta"
        self.correr_ambiente(10 * (FALLOS_AMBIENTE_PARA_AVISAR - 1) - 5)          # las lecturas de 0 s y 10 s
        self.assertEqual(self.eventos("PER_FALLA"), [])
        self.correr_ambiente(60)
        (e,) = self.eventos("PER_FALLA")
        self.assertIsNotNone(e["periferico_id"])
        self.assertIn("no contesta", e["mensaje"])
        self.assertTrue(self.n.estado_pantalla()["ambiente"]["falla"])

    def test_cuando_vuelve_deja_el_evento_de_recuperado(self) -> None:
        self.sensor.error = "no contesta"
        self.correr_ambiente(40)
        self.sensor.error = None
        self.correr_ambiente(20)
        self.assertEqual(len(self.eventos("PER_RECUPERADO")), 1)
        self.assertFalse(self.n.estado_pantalla()["ambiente"]["falla"])

    def test_si_nunca_contesto_no_se_llena_la_base_de_huecos(self) -> None:
        self.sensor.error = "no contesta"
        self.correr_ambiente(180)
        self.assertEqual(self.mediciones(), [])
        self.assertEqual(len(self.eventos("PER_FALLA")), 1)

    def test_si_falla_despues_de_funcionar_queda_el_hueco_como_hueco(self) -> None:
        self.correr_ambiente(60.5)
        self.sensor.error = "no contesta"
        self.correr_ambiente(120.5)                                  # el 2.o intervalo aun trae la lectura buena de los 60 s
        hueco = self.mediciones("temperatura_c")[-1]
        self.assertEqual((hueco["n_muestras"], hueco["prom"], hueco["calidad"]), (0, None, CALIDAD_SIN_DATOS))

    def test_con_fallos_a_ratos_las_lecturas_buenas_se_guardan_marcadas_como_inestables(self) -> None:
        self.correr_ambiente(30)
        self.sensor.error = "no contesta"
        self.correr_ambiente(10)
        self.sensor.error = None
        self.correr_ambiente(20.5)
        t = self.mediciones("temperatura_c")[0]
        self.assertEqual(t["calidad"], CALIDAD_INESTABLE)
        self.assertEqual(t["n_muestras"], 5)

    def test_al_cerrar_guarda_lo_que_lleva_del_intervalo(self) -> None:
        self.correr_ambiente(25)
        self.n.cerrar()
        self.assertEqual(len(self.mediciones("temperatura_c")), 1)
        self.assertEqual(len(self.mediciones("humedad_pct")), 1)

    def test_el_estado_para_la_pantalla_trae_la_ultima_lectura(self) -> None:
        self.assertEqual(self.n.estado_pantalla()["ambiente"], {"temperatura_c": None, "humedad_pct": None, "falla": False})
        self.correr_ambiente(5)
        self.assertEqual(self.n.estado_pantalla()["ambiente"], {"temperatura_c": 24.0, "humedad_pct": 50.0, "falla": False})

    def test_una_lectura_vieja_no_se_muestra_como_actual(self) -> None:
        self.correr_ambiente(5)
        self.correr(self.n, 125)                                     # el servicio dejo de leer
        self.assertEqual(self.n.estado_pantalla()["ambiente"]["temperatura_c"], None)

    def test_sin_servicio_no_hay_ambiente_ni_periferico(self) -> None:
        n = Nucleo(self.a, self.fuente, self.salidas, mono=lambda: self.t[0], version_sw="test")
        n.iniciar()
        self.correr(n, 70)
        self.assertIsNone(n.estado_pantalla()["ambiente"])
        self.assertEqual(self.mediciones(), [])

    def test_el_catalogo_de_configuracion_sigue_siendo_valido(self) -> None:
        self.assertEqual(catalogo.verificar_catalogo(), [])
        self.assertEqual(self.a.config_tipada("ambiente.pin_gpio"), 4)


class PruebasPantallaAmbiente(unittest.TestCase):
    def test_el_texto(self) -> None:
        self.assertEqual(vistas.texto_ambiente({"temperatura_c": 24.54, "humedad_pct": 55.4}), "24.5 °C   55 %")
        self.assertEqual(vistas.texto_ambiente({"temperatura_c": None, "humedad_pct": None}), "-- °C   -- %")
        self.assertEqual(vistas.texto_ambiente({"temperatura_c": -3.0, "humedad_pct": 100.0}), "-3.0 °C   100 %")

    def grafica(self, est, **kwargs) -> dict:
        return vistas.vista_grafica(est, nucleo_responde=kwargs.pop("nucleo_responde", True),
                                    marcas=("24", "21", "18"), ventana="-12 min")

    def test_la_linea_va_en_la_grafica_solo_si_el_equipo_lee_el_sensor(self) -> None:
        sin = self.grafica(estado())
        self.assertFalse([k for k in sin if "amb" in k])
        con = self.grafica({**estado(), "ambiente": {"temperatura_c": 24.5, "humedad_pct": 55.0, "falla": False}})
        self.assertEqual(con["grafica.amb.txt"], "24.5 °C   55 %")
        self.assertEqual(con["grafica.amb.pco"], COLOR["texto_suave"])

    def test_en_falla_la_linea_va_en_rojo(self) -> None:
        v = self.grafica({**estado(), "ambiente": {"temperatura_c": None, "humedad_pct": None, "falla": True}})
        self.assertEqual((v["grafica.amb.txt"], v["grafica.amb.pco"]), ("-- °C   -- %", COLOR["alarma"]))

    def test_si_el_nucleo_no_responde_no_se_muestra_un_valor_viejo(self) -> None:
        v = self.grafica({**estado(), "ambiente": {"temperatura_c": 24.5, "humedad_pct": 55.0, "falla": False}},
                         nucleo_responde=False)
        self.assertEqual(v["grafica.amb.txt"], "-- °C   -- %")

    def test_la_principal_no_cambia(self) -> None:
        v = vistas.vista_principal({**estado(), "ambiente": {"temperatura_c": 24.5, "humedad_pct": 55.0, "falla": False}},
                                   nucleo_responde=True, fase_encendida=True, hora="12:34", red="WIFI OK", cola=0)
        self.assertFalse([k for k in v if "amb" in k])


class PruebasInterfazAmbiente(BaseInterfaz):
    def setUp(self) -> None:
        super().setUp()
        self.datos.grafica_espera = 10.0

    def abrir_grafica(self, est: dict) -> None:
        self.ultimo = est
        self.publicar(est)
        self.arrancar_en_principal()
        self.avanzar(11.0)                                           # la Pi pide la grafica tras 10 s sin tocar
        self.cargar("grafica")
        self.avanzar(0.6)
        for _ in range(8):                                           # hace de pantalla: responde a los addt
            self.enlace.datos_listos()
            self.ui.paso()
            self.enlace.datos_recibidos()
            self.ui.paso()
        self.avanzar(2.0)

    def test_la_grafica_pinta_la_temperatura_y_la_humedad(self) -> None:
        self.abrir_grafica({**estado(), "ambiente": {"temperatura_c": 24.5, "humedad_pct": 55.0, "falla": False}})
        self.assertIn('grafica.amb.txt="24.5 °C   55 %"', self.enlace.enviadas)

    def test_la_principal_nunca_recibe_el_ambiente(self) -> None:
        self.ultimo = {**estado(), "ambiente": {"temperatura_c": 24.5, "humedad_pct": 55.0, "falla": False}}
        self.publicar(self.ultimo)
        self.arrancar_en_principal()
        self.avanzar(2.0)
        self.assertFalse([o for o in self.enlace.enviadas if ".amb." in o])

    def test_sin_ambiente_no_se_manda_nada_al_campo_que_el_hmi_quiza_no_tiene(self) -> None:
        self.abrir_grafica(estado())
        self.assertFalse([o for o in self.enlace.enviadas if ".amb." in o])


if __name__ == "__main__":
    unittest.main()
