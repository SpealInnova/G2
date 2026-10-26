"""Pruebas de la interfaz de la pantalla (g2.pantalla.interfaz) con una pantalla emulada, un estado del
nucleo publicado en archivos y un reloj controlado."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from g2 import ipc
from g2.pantalla import protocolo as P
from g2.pantalla.enlace import EnlaceEmulado
from g2.pantalla import texto as txt
from g2.pantalla.interfaz import Interfaz
from g2.seguridad import pin as seguridad_pin

CONFIG = {"alarma.o2_bajo_pct": 20.0, "alarma.o2_alto_pct": 92.0, "alarma.o2_retardo_s": 10.0,
          "alarma.o2_histeresis_pct": 0.5, "alarma.acuse_silencio_s": 120.0}


PIN_DE_PRUEBA = "1357"                                  # inventado: el PIN de fabrica real NO esta en el repositorio
CONFIG_PIN = {"pantalla.pin_vigencia_s": 300.0, "pantalla.pin_intentos": 3.0, "pantalla.pin_bloqueo_s": 60.0}


class DatosFalsos:
    def __init__(self) -> None:
        self.historial = []
        self.cola = 3
        self.auditoria = (True, 0)
        self.sensores_activos = [True, True]
        self.volumen = 50.0
        self.grafica_espera = 0.0                             # desactivada salvo en las pruebas de la grafica
        sal, huella, iteraciones = seguridad_pin.nueva_huella(PIN_DE_PRUEBA, iteraciones=10_000)
        self.pin = {"tipo": "fabrica", "sal": sal, "huella": huella, "iteraciones": iteraciones}

    def config_alarmas(self):
        return dict(CONFIG)

    def config_general(self):
        return {"muestreo.intervalo_guardado_s": 15.0, "muestreo.intervalo_pantalla_s": 1.0,
                "alarma.discrepancia_pct": 0.5, "pantalla.volumen": self.volumen,
                "pantalla.grafica_espera_s": self.grafica_espera}

    def datos_del_equipo(self):
        return {"equipo.nombre": "", "equipo.id": ""}

    def sensores(self):
        return [{"id": n + 1, "nombre": f"Sensor {n + 1}", "modelo": "Paracube Micro", "serie_etiqueta": None,
                 "habilitado": int(activo)} for n, activo in enumerate(self.sensores_activos)]

    def verificar_auditoria(self):
        return self.auditoria

    def config_pin(self):
        return dict(CONFIG_PIN)

    def pin_activo(self):
        return self.pin

    def historial_alarmas(self, cantidad: int = 6):
        return list(self.historial)

    def cola_pendiente(self) -> int:
        return self.cola


def estado(s1=("20.9", "NORMAL", False), s2=("20.9", "NORMAL", False), aviso="Sin alarmas", sonar=False) -> dict:
    def o2(texto):
        return None if texto == "--.-" else float(texto)
    return {"sensores": [{"id": 1, "o2": o2(s1[0]), "texto_o2": s1[0], "estado": s1[1], "acusada": s1[2]},
                         {"id": 2, "o2": o2(s2[0]), "texto_o2": s2[0], "estado": s2[1], "acusada": s2[2]}],
            "aviso": aviso, "sonar": sonar, "parpadeo": False}


class BaseInterfaz(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.t = [100.0]                                           # reloj de la interfaz y del ipc
        self.nucleo = ipc.PublicadorEstado(self.dir, reloj=lambda: self.t[0])
        self.cliente = ipc.ClienteNucleo(self.dir, reloj=lambda: self.t[0])
        self.enlace = EnlaceEmulado()
        self.datos = DatosFalsos()
        self.ui = Interfaz(self.enlace, self.cliente, self.datos, reloj=lambda: self.t[0],
                           hora=lambda: "12:34", red=lambda: "WIFI OK", segundo_plano=lambda tarea: tarea())
        self.nucleo.publicar(estado())

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def avanzar(self, segundos: float, paso: float = 0.1) -> None:
        """Avanza el tiempo; el nucleo "sigue vivo": republica el ultimo estado cada segundo."""
        fin = self.t[0] + segundos
        while self.t[0] < fin - 1e-9:
            self.t[0] += paso
            if self.publicando and int(self.t[0]) > self._segundo_publicado:       # una vez por segundo
                self._segundo_publicado = int(self.t[0])
                self.nucleo.publicar(self.ultimo)
            self.ui.paso()

    publicando = True
    ultimo = None
    _segundo_publicado = 0

    def publicar(self, est: dict) -> None:
        self.ultimo = est
        self.nucleo.publicar(est)

    def cargar(self, pagina: str) -> None:
        self.enlace.pagina_cargada(pagina)
        self.ui.paso()

    def arrancar_en_principal(self) -> None:
        self.ultimo = self.ultimo or estado()                  # respeta el estado que la prueba ya haya publicado
        self.ui.iniciar()
        self.cargar("principal")


class PruebasArranqueYPintado(BaseInterfaz):
    def test_al_iniciar_lleva_la_pantalla_a_principal(self) -> None:
        self.ui.iniciar()
        self.assertEqual(self.enlace.enviadas, ["volume=50", "page principal", "sendxy=1"])

    def test_al_cargar_la_pagina_la_pinta_entera(self) -> None:
        self.arrancar_en_principal()
        o = self.enlace.enviadas
        for esperado in ('principal.hora.txt="12:34"', 'principal.red_s.txt="WIFI OK"',
                         'principal.cola_s.txt="COLA 3"', 'principal.o2_1.txt="20.9"',
                         'principal.est_1.txt="NORMAL"', 'principal.est_1.bco=1128',
                         'principal.aviso.txt="Sin alarmas"'):
            self.assertIn(esperado, o)

    def test_pide_y_verifica_la_version_del_protocolo(self) -> None:
        self.arrancar_en_principal()
        self.assertIn("get principal.proto.val", self.enlace.enviadas)
        self.enlace.responder_numero(1)
        self.ui.paso()
        self.assertTrue(self.ui.protocolo_compatible)

    def test_un_protocolo_distinto_se_detecta_y_se_registra(self) -> None:
        self.arrancar_en_principal()
        self.enlace.responder_numero(9)
        with self.assertLogs("g2.pantalla", level="ERROR"):
            self.ui.paso()
        self.assertFalse(self.ui.protocolo_compatible)

    def test_solo_envia_lo_que_cambia(self) -> None:
        self.arrancar_en_principal()
        antes = len(self.enlace.enviadas)
        self.avanzar(2.0)
        self.assertEqual(len(self.enlace.enviadas), antes)           # nada cambio: no se reenvia nada
        self.publicar(estado(s1=("21.4", "NORMAL", False)))
        self.avanzar(0.6)
        nuevas = self.enlace.enviadas[antes:]
        self.assertEqual(nuevas, ['principal.o2_1.txt="21.4"'])

    def test_al_encender_la_pantalla_se_reinicia_la_sesion(self) -> None:
        self.arrancar_en_principal()
        self.enlace.enviadas.clear()
        self.enlace.encendida()
        self.ui.paso()
        self.assertEqual(self.enlace.enviadas, ["volume=50", "page principal", "sendxy=1"])
        self.cargar("principal")
        self.assertIn('principal.o2_1.txt="20.9"', self.enlace.enviadas)      # se repinta todo


class PruebasAlarmasEnPantalla(BaseInterfaz):
    def test_el_recuadro_parpadea_mientras_la_alarma_no_se_acusa(self) -> None:
        self.arrancar_en_principal()
        self.publicar(estado(s1=("15.0", "BAJA", False), aviso="S1 BAJO 15.0 %"))
        self.avanzar(3.0)
        colores = [o for o in self.enlace.enviadas if o.startswith("principal.est_1.bco=")]
        self.assertGreaterEqual(len(set(colores)), 2)                           # alterna entre dos colores
        self.assertIn("principal.est_1.bco=51427", colores)
        self.assertIn("principal.est_1.bco=65535", colores)

    def test_acusada_queda_fija_y_deja_de_parpadear(self) -> None:
        self.arrancar_en_principal()
        self.publicar(estado(s1=("15.0", "BAJA", True), aviso="S1 BAJO 15.0 %"))
        self.avanzar(1.0)
        antes = len([o for o in self.enlace.enviadas if o.startswith("principal.est_1.bco=")])
        self.avanzar(3.0)
        despues = len([o for o in self.enlace.enviadas if o.startswith("principal.est_1.bco=")])
        self.assertEqual(antes, despues)
        self.assertEqual(self.enlace.ordenes_con("est_1.bco=")[-1], "principal.est_1.bco=51427")

    def test_el_sonido_se_repite_cada_3_segundos_mientras_el_nucleo_lo_pide(self) -> None:
        self.arrancar_en_principal()
        self.publicar(estado(s1=("15.0", "BAJA", False), aviso="S1 BAJO 15.0 %", sonar=True))
        self.avanzar(7.0)
        self.assertIn(self.enlace.enviadas.count("play 0,1,0"), (2, 3))         # uno cada 3 s: en 7 s, 2 o 3
        self.publicar(estado(s1=("15.0", "BAJA", True), aviso="S1 BAJO 15.0 %", sonar=False))
        antes = self.enlace.enviadas.count("play 0,1,0")
        self.avanzar(7.0)
        self.assertEqual(self.enlace.enviadas.count("play 0,1,0"), antes)       # acusada: en silencio

    def test_si_el_nucleo_deja_de_publicar_se_avisa_y_se_calla(self) -> None:
        self.arrancar_en_principal()
        self.publicar(estado(sonar=True))
        self.avanzar(2.0)
        self.publicando = False                                                 # el nucleo se cuelga
        self.enlace.enviadas.clear()
        self.avanzar(8.0)                                                       # mas de los 5 s de tolerancia
        self.assertIn('principal.aviso.txt="Núcleo sin respuesta"', self.enlace.enviadas)
        self.assertIn('principal.est_1.txt="SIN SEÑAL"', self.enlace.enviadas)
        self.assertIn('principal.o2_1.txt="--.-"', self.enlace.enviadas)
        sonidos = self.enlace.enviadas.count("play 0,1,0")
        self.avanzar(8.0)
        self.assertEqual(self.enlace.enviadas.count("play 0,1,0"), sonidos)     # no sigue sonando

    def test_cuando_el_nucleo_vuelve_la_pantalla_se_recupera(self) -> None:
        self.arrancar_en_principal()
        self.publicando = False
        self.avanzar(8.0)
        self.publicando = True
        self.avanzar(2.0)
        self.assertEqual(self.enlace.ordenes_con("aviso.txt=")[-1], 'principal.aviso.txt="Sin alarmas"')
        self.assertEqual(self.enlace.ordenes_con("est_1.txt=")[-1], 'principal.est_1.txt="NORMAL"')


class PruebasNavegacionYOrdenes(BaseInterfaz):
    def test_alarmas_abre_la_pagina_y_la_pinta_con_ajustes_e_historial(self) -> None:
        self.arrancar_en_principal()
        self.enlace.tocar("principal", "b_alarmas")
        self.ui.paso()
        self.assertEqual(self.enlace.enviadas[-1], "page alarmas")
        ms = int(time.mktime((2026, 10, 16, 14, 32, 0, 0, 0, -1)) * 1000)
        self.datos.historial = [{"codigo": "ALM_O2_BAJO", "sensor_id": 1, "estado": "activa", "inicio_ms": ms}]
        self.cargar("alarmas")
        self.avanzar(0.5)
        for esperado in ('alarmas.v_bajo.txt="20.0 %"', 'alarmas.v_alto.txt="92.0 %"',
                         'alarmas.v_retardo.txt="10 s"', 'alarmas.v_acuse.txt="120 s"',
                         'alarmas.h1.txt="16/10 14:32 S1 BAJO"'):
            self.assertIn(esperado, self.enlace.enviadas)

    def test_volver_regresa_a_principal(self) -> None:
        self.arrancar_en_principal()
        self.cargar("alarmas")
        self.enlace.tocar("alarmas", "b_volver")
        self.ui.paso()
        self.assertEqual(self.enlace.enviadas[-1], "page principal")

    def test_acusar_deja_una_orden_para_el_nucleo_y_no_toca_la_base(self) -> None:
        self.arrancar_en_principal()
        self.enlace.tocar("principal", "b_acuse")
        self.ui.paso()
        ordenes = self.nucleo.recoger_ordenes()
        self.assertEqual(len(ordenes), 1)
        self.assertEqual((ordenes[0]["tipo"], ordenes[0]["actor"], ordenes[0]["origen"]),
                         ("acusar", "pantalla", "pantalla"))

    def test_las_paginas_aun_sin_construir_muestran_un_aviso_pasajero(self) -> None:
        self.arrancar_en_principal()
        self.enlace.tocar("principal", "b_calib")
        self.ui.paso()
        self.assertEqual(self.enlace.ordenes_con("aviso.txt=")[-1], 'principal.aviso.txt="Página en construcción"')
        self.assertNotIn("page calibracion", self.enlace.enviadas)              # esa pagina todavia no existe
        self.avanzar(4.0)
        self.assertEqual(self.enlace.ordenes_con("aviso.txt=")[-1], 'principal.aviso.txt="Sin alarmas"')

    def test_un_toque_en_una_pagina_distinta_a_la_actual_no_rompe_nada(self) -> None:
        self.arrancar_en_principal()
        self.enlace.tocar("teclado", "k_7")
        self.ui.paso()                                                          # sin excepcion

    def test_una_orden_rechazada_por_la_pantalla_se_registra(self) -> None:
        self.arrancar_en_principal()
        self.enlace.inyectar(bytes([0x03]))
        with self.assertLogs("g2.pantalla", level="WARNING") as registro:
            self.ui.paso()
        self.assertIn("pagina inexistente", registro.output[0])

class PruebasPinYTeclado(BaseInterfaz):
    """El recorrido completo de un cambio de ajuste: ajuste -> PIN -> valor -> orden al nucleo (D-038)."""

    def abrir_teclado(self, boton: str = "v_bajo") -> None:
        self.arrancar_en_principal()
        self.cargar("alarmas")
        self.avanzar(2.5)                                   # la interfaz lee la configuracion de la base
        self.enlace.tocar("alarmas", boton)
        self.ui.paso()
        self.cargar("teclado")

    def teclear(self, texto: str) -> None:
        for caracter in texto:
            self.enlace.tocar("teclado", "k_punto" if caracter == "." else f"k_{caracter}")
        self.ui.paso()

    def aceptar(self) -> None:
        self.enlace.tocar("teclado", "b_aceptar")
        self.ui.paso()

    def ultima_orden(self, componente: str) -> str:
        return self.enlace.ordenes_con(f"teclado.{componente}")[-1]

    def ordenes(self) -> list:
        return self.nucleo.recoger_ordenes()

    def poner_pin_correcto(self) -> None:
        self.teclear(PIN_DE_PRUEBA)
        self.aceptar()

    # ---- pedir el PIN ----
    def test_al_tocar_un_ajuste_se_abre_el_teclado_y_pide_el_pin(self) -> None:
        self.abrir_teclado()
        self.assertIn("page teclado", self.enlace.enviadas)
        self.assertEqual(self.ultima_orden("titulo.txt"), 'teclado.titulo.txt="Ingrese el PIN"')
        self.assertEqual(self.ultima_orden("t_titulo.txt"), 'teclado.t_titulo.txt="PIN"')
        self.assertEqual(self.ultima_orden("msg.txt"), 'teclado.msg.txt="Escriba el PIN y pulse Aceptar"')

    def test_el_pin_se_muestra_con_asteriscos_nunca_en_claro(self) -> None:
        self.abrir_teclado()
        self.teclear("13")
        self.avanzar(0.5)
        self.assertEqual(self.ultima_orden("valor.txt"), 'teclado.valor.txt="**"')
        self.assertFalse([o for o in self.enlace.enviadas if "13" in o and "valor.txt" in o])

    def test_borrar_y_limpiar_funcionan_y_el_punto_no_entra_en_un_pin(self) -> None:
        self.abrir_teclado()
        self.teclear("1.23")
        self.enlace.tocar("teclado", "b_borrar")
        self.ui.paso()
        self.avanzar(0.5)
        self.assertEqual(self.ultima_orden("valor.txt"), 'teclado.valor.txt="**"')       # 1, 2 (el punto se ignoro; el 3 se borro)
        self.enlace.tocar("teclado", "b_limpiar")
        self.ui.paso()
        self.avanzar(0.5)
        self.assertEqual(self.ultima_orden("valor.txt"), 'teclado.valor.txt=""')

    # ---- PIN correcto ----
    def test_con_el_pin_correcto_pasa_al_valor_y_avisa_al_nucleo(self) -> None:
        self.abrir_teclado()
        self.poner_pin_correcto()
        self.avanzar(0.5)
        self.assertEqual(self.ultima_orden("titulo.txt"), 'teclado.titulo.txt="Ajustar"')
        self.assertEqual(self.ultima_orden("t_titulo.txt"), 'teclado.t_titulo.txt="Oxígeno bajo (%)"')
        self.assertEqual(self.ultima_orden("msg.txt"), 'teclado.msg.txt="Actual: 20.0 %. Entre 0 y 100 % O2"')
        self.assertEqual(self.ultima_orden("valor.txt"), 'teclado.valor.txt=""')
        (orden,) = self.ordenes()
        self.assertEqual((orden["tipo"], orden["resultado"]), ("pin_resultado", "aceptado"))
        self.assertNotIn(PIN_DE_PRUEBA, str(orden))                                  # el PIN nunca viaja

    def test_el_valor_valido_se_pide_al_nucleo_y_vuelve_a_alarmas(self) -> None:
        self.abrir_teclado()
        self.poner_pin_correcto()
        self.ordenes()
        self.teclear("25")
        self.aceptar()
        (orden,) = self.ordenes()
        self.assertEqual((orden["tipo"], orden["clave"], orden["valor"], orden["actor"]),
                         ("config_fijar", "alarma.o2_bajo_pct", "25.0", "pantalla"))
        self.assertEqual(self.enlace.enviadas[-1], "page alarmas")

    def test_un_valor_con_decimales_y_las_claves_enteras(self) -> None:
        self.abrir_teclado("v_histeresis")
        self.poner_pin_correcto()
        self.ordenes()
        self.teclear("1.5")
        self.aceptar()
        self.assertEqual(self.ordenes()[0]["valor"], "1.5")
        self.cargar("alarmas")
        self.enlace.tocar("alarmas", "v_retardo")
        self.ui.paso()
        self.cargar("teclado")                                          # el PIN sigue vigente: va directo al valor
        self.teclear("12.5")                                            # el punto se ignora en un entero
        self.avanzar(0.5)
        self.assertEqual(self.ultima_orden("valor.txt"), 'teclado.valor.txt="125"')

    # ---- valores invalidos ----
    def test_un_valor_fuera_de_rango_se_explica_y_no_se_envia(self) -> None:
        self.abrir_teclado()
        self.poner_pin_correcto()
        self.ordenes()
        self.teclear("150")
        self.aceptar()
        self.avanzar(0.5)
        self.assertEqual(self.ultima_orden("msg.txt"), 'teclado.msg.txt="Entre 0 y 100 % O2"')
        self.assertEqual(self.ultima_orden("msg.pco"), "teclado.msg.pco=51427")           # en rojo
        self.assertEqual(self.ordenes(), [])

    def test_un_minimo_mayor_que_el_maximo_se_rechaza_con_su_motivo(self) -> None:
        self.abrir_teclado("v_bajo")
        self.poner_pin_correcto()
        self.ordenes()
        self.teclear("95")                                              # el maximo es 92
        self.aceptar()
        self.avanzar(0.5)
        self.assertEqual(self.ultima_orden("msg.txt"), 'teclado.msg.txt="Debe ser menor que el máximo (92 %)"')
        self.assertEqual(self.ordenes(), [])

    def test_sin_escribir_nada_pide_un_valor(self) -> None:
        self.abrir_teclado()
        self.poner_pin_correcto()
        self.aceptar()
        self.avanzar(0.5)
        self.assertEqual(self.ultima_orden("msg.txt"), 'teclado.msg.txt="Escriba un valor"')

    # ---- PIN incorrecto y bloqueo ----
    def test_un_pin_incorrecto_cuenta_los_intentos_y_limpia_el_campo(self) -> None:
        self.abrir_teclado()
        self.teclear("9999")
        self.aceptar()
        self.avanzar(0.5)
        self.assertEqual(self.ultima_orden("msg.txt"), 'teclado.msg.txt="PIN incorrecto. Intentos restantes: 2"')
        self.assertEqual(self.ultima_orden("valor.txt"), 'teclado.valor.txt=""')
        (orden,) = self.ordenes()
        self.assertEqual((orden["resultado"], orden["intentos"]), ("fallido", 1))

    def test_tres_fallos_bloquean_el_teclado_60_segundos(self) -> None:
        self.abrir_teclado()
        for _ in range(3):
            self.teclear("9999")
            self.aceptar()
        self.avanzar(0.5)
        self.assertIn("Bloqueado por intentos fallidos. Espere", self.ultima_orden("msg.txt"))
        resultados = [o["resultado"] for o in self.ordenes()]
        self.assertEqual(resultados, ["fallido", "fallido", "bloqueado"])
        self.teclear(PIN_DE_PRUEBA)                                     # estando bloqueado ni el PIN bueno sirve
        self.aceptar()
        self.avanzar(0.5)
        self.assertEqual(self.ordenes(), [])
        self.assertEqual(self.ultima_orden("valor.txt"), 'teclado.valor.txt=""')          # las teclas se ignoraron

    def test_pasado_el_bloqueo_se_puede_volver_a_intentar(self) -> None:
        self.abrir_teclado()
        for _ in range(3):
            self.teclear("9999")
            self.aceptar()
        self.ordenes()
        self.avanzar(61.0)
        self.assertEqual(self.ultima_orden("msg.txt"), 'teclado.msg.txt="Escriba el PIN y pulse Aceptar"')
        self.poner_pin_correcto()
        self.assertEqual(self.ordenes()[0]["resultado"], "aceptado")

    def test_un_pin_corto_no_cuenta_como_intento_fallido(self) -> None:
        self.abrir_teclado()
        self.teclear("12")
        self.aceptar()
        self.avanzar(0.5)
        self.assertIn("al menos 4 dígitos", self.ultima_orden("msg.txt"))
        self.assertEqual(self.ordenes(), [])

    def test_sin_ningun_pin_configurado_no_se_permite_cambiar_nada(self) -> None:
        self.datos.pin = None
        self.abrir_teclado()
        self.teclear("1234")
        self.aceptar()
        self.avanzar(0.5)
        self.assertEqual(self.ultima_orden("msg.txt"), 'teclado.msg.txt="PIN no configurado: no se permiten cambios"')
        self.assertEqual(self.ordenes(), [])

    # ---- vigencia ----
    def test_el_pin_aceptado_vale_5_minutos_y_no_se_vuelve_a_pedir(self) -> None:
        self.abrir_teclado("v_bajo")
        self.poner_pin_correcto()
        self.teclear("25")
        self.aceptar()
        self.ordenes()
        self.cargar("alarmas")
        self.avanzar(60.0)
        self.enlace.tocar("alarmas", "v_alto")
        self.ui.paso()
        self.cargar("teclado")
        self.avanzar(0.5)
        self.assertEqual(self.ultima_orden("t_titulo.txt"), 'teclado.t_titulo.txt="Oxígeno alto (%)"')    # directo al valor

    def test_pasados_5_minutos_se_pide_el_pin_otra_vez(self) -> None:
        self.abrir_teclado("v_bajo")
        self.poner_pin_correcto()
        self.teclear("25")
        self.aceptar()
        self.cargar("alarmas")
        self.avanzar(301.0)
        self.enlace.tocar("alarmas", "v_alto")
        self.ui.paso()
        self.cargar("teclado")
        self.avanzar(0.5)
        self.assertEqual(self.ultima_orden("t_titulo.txt"), 'teclado.t_titulo.txt="PIN"')

    def test_si_el_pin_vence_mientras_se_teclea_el_valor_se_vuelve_a_pedir(self) -> None:
        self.abrir_teclado()
        self.poner_pin_correcto()
        self.ordenes()
        self.teclear("25")
        self.avanzar(301.0)
        self.aceptar()
        self.avanzar(0.5)
        self.assertEqual(self.ultima_orden("msg.txt"), 'teclado.msg.txt="El PIN venció: escríbalo otra vez"')
        self.assertEqual(self.ordenes(), [])

    # ---- cancelar y salir ----
    def test_cancelar_vuelve_a_alarmas_sin_cambiar_nada(self) -> None:
        self.abrir_teclado()
        self.teclear("12")
        self.enlace.tocar("teclado", "b_cancelar")
        self.ui.paso()
        self.assertEqual(self.enlace.enviadas[-1], "page alarmas")
        self.assertEqual(self.ordenes(), [])

    def test_salir_del_teclado_por_otra_via_descarta_lo_tecleado(self) -> None:
        self.abrir_teclado()
        self.teclear("1357")
        self.cargar("principal")                                        # p. ej. otra orden de pagina
        self.enlace.tocar("teclado", "b_aceptar")                       # un toque tardio no debe hacer nada
        self.ui.paso()
        self.assertEqual(self.ordenes(), [])

    def test_otros_botones_de_alarmas_abren_el_teclado_de_su_ajuste(self) -> None:
        esperados = {"v_alto": "Oxígeno alto (%)", "v_retardo": "Retardo (s)",
                     "v_histeresis": "Histéresis (%)", "v_acuse": "Tiempo de acuse (s)"}
        for boton, rotulo in esperados.items():
            with self.subTest(boton):
                self.setUp()
                self.abrir_teclado(boton)
                self.poner_pin_correcto()
                self.avanzar(0.5)
                self.assertEqual(self.ultima_orden("t_titulo.txt"), f'teclado.t_titulo.txt="{rotulo}"')
                self.tearDown()

class BaseEtapa1(BaseInterfaz):
    """Ayudas comunes: abrir una pagina, pasar el PIN y leer lo ultimo que se pinto."""

    def abrir(self, pagina: str, boton: str) -> None:
        self.arrancar_en_principal()
        self.enlace.tocar("principal", boton)
        self.ui.paso()
        self.cargar(pagina)
        self.avanzar(2.5)                                    # la interfaz lee la base

    def tocar(self, pagina: str, control: str) -> None:
        self.enlace.tocar(pagina, control)
        self.ui.paso()

    def pasar_el_pin(self) -> None:
        self.cargar("teclado")
        for d in PIN_DE_PRUEBA:
            self.enlace.tocar("teclado", f"k_{d}")
        self.enlace.tocar("teclado", "b_aceptar")
        self.ui.paso()

    def pintado(self, clave: str) -> str:
        return self.enlace.ordenes_con(clave)[-1]

    def ordenes(self) -> list:
        return [o for o in self.nucleo.recoger_ordenes() if o["tipo"] != "pin_resultado"]


class PruebasPaginaSistema(BaseEtapa1):
    def estado_con_salud(self, **extra) -> dict:
        e = estado()
        e["version_sw"] = "0.1.0-dev"
        e["salud"] = {"cpu_temp_c": 46.2, "mem_pct": 38.0, "disco_pct": 28.0, "disco_libre_gb": 21.4,
                      "uptime_s": 3 * 86400 + 4 * 3600 + 30, "db_bytes": 940_000}
        e["alertas_salud"] = []
        e.update(extra)
        return e

    def abrir_sistema(self) -> None:
        self.ultimo = self.estado_con_salud()
        self.nucleo.publicar(self.ultimo)
        self.abrir("sistema", "b_sistema")

    def test_principal_abre_la_pagina_de_sistema(self) -> None:
        self.arrancar_en_principal()
        self.enlace.tocar("principal", "b_sistema")
        self.ui.paso()
        self.assertEqual(self.enlace.enviadas[-1], "page sistema")

    def test_muestra_las_ocho_lineas_de_informacion(self) -> None:
        self.abrir_sistema()
        esperadas = ['sistema.i1.txt="Software 0.1.0-dev"', 'sistema.i2.txt="Pantalla: protocolo ?"',
                     'sistema.i3.txt="Encendido hace 3 d 4 h"', 'sistema.i4.txt="CPU 46 °C   RAM 38 %"',
                     'sistema.i5.txt="Disco libre 21.4 GB (72 %)"', 'sistema.i6.txt="Base 0.9 MB   Cola 3"',
                     'sistema.i7.txt="Núcleo OK · Pantalla OK"', 'sistema.i8.txt="PIN: de fábrica"']
        for linea in esperadas:
            self.assertIn(linea, self.enlace.enviadas)

    def test_las_lineas_de_cpu_y_disco_pasan_a_rojo_con_su_alarma(self) -> None:
        self.ultimo = self.estado_con_salud(alertas_salud=["ALM_RPI_TEMP_ALTA", "ALM_DISCO_ESPACIO_BAJO"])
        self.nucleo.publicar(self.ultimo)
        self.abrir("sistema", "b_sistema")
        self.assertEqual(self.pintado("sistema.i4.pco"), "sistema.i4.pco=51427")
        self.assertEqual(self.pintado("sistema.i5.pco"), "sistema.i5.pco=51427")
        self.assertEqual(self.pintado("sistema.i7.pco"), "sistema.i7.pco=6438")

    def test_si_el_nucleo_no_responde_se_dice_y_no_se_muestran_valores_viejos(self) -> None:
        self.abrir_sistema()
        self.publicando = False
        self.enlace.enviadas.clear()
        self.avanzar(8.0)
        self.assertIn('sistema.i7.txt="Núcleo SIN RESPUESTA"', self.enlace.enviadas)
        self.assertIn('sistema.i4.txt="CPU -- °C   RAM -- %"', self.enlace.enviadas)

    def test_sin_pin_configurado_la_linea_lo_dice_en_rojo(self) -> None:
        self.datos.pin = None
        self.abrir_sistema()
        self.assertEqual(self.pintado("sistema.i8.txt"), 'sistema.i8.txt="PIN: SIN PIN"')
        self.assertEqual(self.pintado("sistema.i8.pco"), "sistema.i8.pco=51427")

    def test_volver_regresa_a_principal(self) -> None:
        self.abrir_sistema()
        self.tocar("sistema", "b_volver")
        self.assertEqual(self.enlace.enviadas[-1], "page principal")

    def test_reportes_aun_no_existe_y_lo_dice(self) -> None:
        self.abrir_sistema()
        self.tocar("sistema", "b_reportes")
        self.avanzar(0.5)
        self.assertEqual(self.pintado("sistema.res.txt"), 'sistema.res.txt="Reportes: próxima etapa"')

    # ---- reiniciar servicios y equipo: PIN + confirmacion + orden ----
    def test_reiniciar_servicios_pide_pin_luego_confirmacion_y_luego_la_orden(self) -> None:
        self.abrir_sistema()
        self.tocar("sistema", "b_servicios")
        self.assertEqual(self.enlace.enviadas[-1], "page teclado")
        self.pasar_el_pin()
        self.assertEqual(self.enlace.enviadas[-1], "page confirmar")
        self.assertEqual(self.ordenes(), [])                                     # aun no se pidio nada
        self.cargar("confirmar")
        self.avanzar(0.5)
        self.assertEqual(self.pintado("confirmar.t_pregunta.txt"), 'confirmar.t_pregunta.txt="¿Reiniciar los servicios?"')
        self.tocar("confirmar", "b_si")
        (orden,) = self.ordenes()
        self.assertEqual((orden["tipo"], orden["accion"], orden["actor"]), ("sistema_accion", "reiniciar_servicios", "pantalla"))
        self.assertEqual(self.enlace.enviadas[-1], "page sistema")

    def test_reiniciar_el_equipo_avisa_de_las_alarmas_externas(self) -> None:
        self.abrir_sistema()
        self.tocar("sistema", "b_reiniciar")
        self.pasar_el_pin()
        self.cargar("confirmar")
        self.avanzar(0.5)
        self.assertIn("alarmas externas", self.pintado("confirmar.t_detalle.txt"))
        self.tocar("confirmar", "b_si")
        self.assertEqual(self.ordenes()[0]["accion"], "reiniciar_equipo")

    def test_decir_no_cancela_y_no_envia_nada(self) -> None:
        self.abrir_sistema()
        self.tocar("sistema", "b_reiniciar")
        self.pasar_el_pin()
        self.cargar("confirmar")
        self.tocar("confirmar", "b_no")
        self.assertEqual(self.ordenes(), [])
        self.assertEqual(self.enlace.enviadas[-1], "page sistema")

    def test_cancelar_el_pin_vuelve_a_sistema_sin_hacer_nada(self) -> None:
        self.abrir_sistema()
        self.tocar("sistema", "b_servicios")
        self.cargar("teclado")
        self.tocar("teclado", "b_cancelar")
        self.assertEqual(self.enlace.enviadas[-1], "page sistema")
        self.assertEqual(self.ordenes(), [])

    def test_con_el_pin_vigente_no_se_vuelve_a_pedir_pero_si_se_confirma(self) -> None:
        self.abrir_sistema()
        self.tocar("sistema", "b_servicios")
        self.pasar_el_pin()
        self.cargar("confirmar")
        self.tocar("confirmar", "b_no")
        self.cargar("sistema")
        self.tocar("sistema", "b_reiniciar")
        self.assertEqual(self.enlace.enviadas[-1], "page confirmar")              # sin teclado

    def test_un_toque_suelto_en_confirmar_sin_pregunta_no_hace_nada(self) -> None:
        self.abrir_sistema()
        self.tocar("confirmar", "b_si")
        self.assertEqual(self.ordenes(), [])

    # ---- verificar la auditoria ----
    def test_verificar_la_auditoria_pide_pin_y_avisa_el_resultado_al_nucleo(self) -> None:
        self.abrir_sistema()
        self.tocar("sistema", "b_auditoria")
        self.pasar_el_pin()
        self.cargar("sistema")
        self.avanzar(1.0)
        self.assertEqual(self.pintado("sistema.res.txt"), 'sistema.res.txt="Auditoría íntegra: sin diferencias"')
        (orden,) = self.ordenes()
        self.assertEqual((orden["tipo"], orden["correcta"], orden["diferencias"]), ("auditoria_resultado", True, 0))

    def test_una_auditoria_alterada_se_muestra_en_rojo_y_se_avisa(self) -> None:
        self.datos.auditoria = (False, 3)
        self.abrir_sistema()
        self.tocar("sistema", "b_auditoria")
        self.pasar_el_pin()
        self.cargar("sistema")
        self.avanzar(1.0)
        self.assertEqual(self.pintado("sistema.res.txt"), 'sistema.res.txt="AUDITORÍA ALTERADA: 3 diferencia(s)"')
        self.assertEqual(self.pintado("sistema.res.pco"), "sistema.res.pco=51427")
        self.assertFalse(self.ordenes()[0]["correcta"])

    def test_si_la_verificacion_no_puede_hacerse_no_se_dice_que_esta_bien(self) -> None:
        self.datos.auditoria = (False, -1)
        self.abrir_sistema()
        self.tocar("sistema", "b_auditoria")
        self.pasar_el_pin()
        self.cargar("sistema")
        self.avanzar(1.0)
        self.assertEqual(self.pintado("sistema.res.txt"), 'sistema.res.txt="No se pudo verificar la auditoría"')

    def test_el_resultado_se_borra_solo_pasado_un_tiempo(self) -> None:
        self.abrir_sistema()
        self.tocar("sistema", "b_reportes")
        self.avanzar(25.0)
        self.assertEqual(self.pintado("sistema.res.txt"), 'sistema.res.txt=""')


class PruebasPaginaConfig(BaseEtapa1):
    def abrir_config(self) -> None:
        self.abrir("config", "b_config")

    def test_principal_abre_la_pagina_de_configuracion_con_sus_valores(self) -> None:
        self.abrir_config()
        for linea in ('config.v_guardado.txt="15 s"', 'config.v_pantalla.txt="1 s"', 'config.v_discrepancia.txt="0.5 %"',
                      'config.v_sensor1.txt="ACTIVO"', 'config.v_sensor2.txt="ACTIVO"',
                      'config.e1.txt="Nombre: (sin definir)"', 'config.e2.txt="ID: (sin definir)"',
                      'config.e3.txt="S1: Paracube Micro, serie -"'):
            self.assertIn(linea, self.enlace.enviadas)

    def test_cambiar_el_intervalo_de_guardado_pasa_por_pin_y_teclado(self) -> None:
        self.abrir_config()
        self.tocar("config", "v_guardado")
        self.pasar_el_pin()
        self.avanzar(0.5)
        self.assertEqual(self.pintado("teclado.t_titulo.txt"), 'teclado.t_titulo.txt="Guardado de datos (s)"')
        self.assertEqual(self.pintado("teclado.msg.txt"), 'teclado.msg.txt="Actual: 15 s. Entre 1 y 3600 s"')
        for d in "30":
            self.enlace.tocar("teclado", f"k_{d}")
        self.enlace.tocar("teclado", "b_aceptar")
        self.ui.paso()
        (orden,) = self.ordenes()
        self.assertEqual((orden["tipo"], orden["clave"], orden["valor"]), ("config_fijar", "muestreo.intervalo_guardado_s", "30"))
        self.assertEqual(self.enlace.enviadas[-1], "page config")                # vuelve a CONFIG, no a alarmas

    def test_la_discrepancia_admite_decimales_y_vuelve_a_config(self) -> None:
        self.abrir_config()
        self.tocar("config", "v_discrepancia")
        self.pasar_el_pin()
        for c in ("k_1", "k_punto", "k_5"):
            self.enlace.tocar("teclado", c)
        self.enlace.tocar("teclado", "b_aceptar")
        self.ui.paso()
        self.assertEqual(self.ordenes()[0]["valor"], "1.5")

    def test_un_valor_fuera_de_rango_se_explica(self) -> None:
        self.abrir_config()
        self.tocar("config", "v_pantalla")
        self.pasar_el_pin()
        for d in "99":
            self.enlace.tocar("teclado", f"k_{d}")
        self.enlace.tocar("teclado", "b_aceptar")
        self.ui.paso()
        self.avanzar(0.5)
        self.assertEqual(self.pintado("teclado.msg.txt"), 'teclado.msg.txt="Entre 1 y 60 s"')
        self.assertEqual(self.ordenes(), [])

    def test_cancelar_en_config_vuelve_a_config(self) -> None:
        self.abrir_config()
        self.tocar("config", "v_guardado")
        self.cargar("teclado")
        self.tocar("teclado", "b_cancelar")
        self.assertEqual(self.enlace.enviadas[-1], "page config")

    # ---- sensores ----
    def test_apagar_un_sensor_pide_pin_confirmacion_y_envia_la_orden(self) -> None:
        self.abrir_config()
        self.tocar("config", "v_sensor2")
        self.pasar_el_pin()
        self.assertEqual(self.enlace.enviadas[-1], "page confirmar")
        self.cargar("confirmar")
        self.avanzar(0.5)
        self.assertEqual(self.pintado("confirmar.t_pregunta.txt"), 'confirmar.t_pregunta.txt="¿Apagar el Sensor 2?"')
        self.tocar("confirmar", "b_si")
        (orden,) = self.ordenes()
        self.assertEqual((orden["tipo"], orden["sensor_id"], orden["habilitado"]), ("sensor_habilitar", 2, False))
        self.assertEqual(self.enlace.enviadas[-1], "page config")

    def test_encender_un_sensor_apagado_no_pide_confirmacion(self) -> None:
        self.datos.sensores_activos = [True, False]
        self.abrir_config()
        self.assertEqual(self.pintado("config.v_sensor2.txt"), 'config.v_sensor2.txt="APAGADO"')
        self.assertEqual(self.pintado("config.v_sensor2.pco"), "config.v_sensor2.pco=51427")
        self.tocar("config", "v_sensor2")
        self.pasar_el_pin()
        self.assertNotIn("page confirmar", self.enlace.enviadas)
        (orden,) = self.ordenes()
        self.assertEqual((orden["sensor_id"], orden["habilitado"]), (2, True))

    def test_con_un_solo_sensor_dado_de_alta_la_otra_fila_dice_sin_sensor(self) -> None:
        self.datos.sensores_activos = [True]
        self.abrir_config()
        self.assertEqual(self.pintado("config.v_sensor2.txt"), 'config.v_sensor2.txt="SIN SENSOR"')
        self.tocar("config", "v_sensor2")                                          # no hay nada que alternar
        self.assertNotIn("page teclado", self.enlace.enviadas)

    def test_volver_regresa_a_principal(self) -> None:
        self.abrir_config()
        self.tocar("config", "b_volver")
        self.assertEqual(self.enlace.enviadas[-1], "page principal")

    def test_la_edicion_de_alarmas_sigue_volviendo_a_alarmas(self) -> None:
        self.abrir("alarmas", "b_alarmas")
        self.tocar("alarmas", "v_bajo")
        self.cargar("teclado")
        self.tocar("teclado", "b_cancelar")
        self.assertEqual(self.enlace.enviadas[-1], "page alarmas")

CLAVE_DE_PRUEBA = "Hosp1tal/2026-Seguro!"                     # inventada: con mayusculas, numeros y simbolos


def red_publicada(**cambios) -> dict:
    base = {"red": {"tipo": "wifi", "ssid": "RedEjemplo", "ip": "192.168.10.20", "senal": 99, "internet": True,
                    "zerotier_ip": "10.99.99.10", "interfaz_wifi": "wlan0"},
            "redes": [{"ssid": "RedEjemplo", "senal": 99, "seguridad": "WPA2"},
                      {"ssid": "Hospital", "senal": 70, "seguridad": "WPA2"},
                      {"ssid": "Invitados", "senal": 55, "seguridad": ""}],
            "cambio": {"en_curso": None, "ultimo": None}}
    base.update(cambios)
    return base


class PruebasPaginaRed(BaseEtapa1):
    def estado_con_red(self, **cambios) -> dict:
        e = estado()
        e["red"] = red_publicada(**cambios)
        return e

    def abrir_red(self, **cambios) -> None:
        self.ultimo = self.estado_con_red(**cambios)
        self.nucleo.publicar(self.ultimo)
        self.abrir("red", "b_red")

    def publicar_red(self, **cambios) -> None:
        self.publicar(self.estado_con_red(**cambios))

    def tecla_de(self, caracter: str, capa: str) -> str:
        return f"t_{txt.CAPAS[capa].index(caracter):02d}"

    def escribir(self, texto: str) -> None:
        """Escribe ``texto`` usando las capas del teclado, como lo haria una persona."""
        capa = "minusculas"
        for c in texto:
            for nombre in ("minusculas", "mayusculas", "simbolos"):
                if c in txt.CAPAS[nombre] and c != " ":
                    destino = nombre
                    break
            else:
                self.enlace.tocar("texto", "b_espacio")
                continue
            while capa != destino:
                if destino == "simbolos":
                    self.enlace.tocar("texto", "b_simbolos")
                    capa = "simbolos"
                elif capa == "simbolos":
                    self.enlace.tocar("texto", "b_simbolos")
                    capa = "minusculas"
                else:
                    self.enlace.tocar("texto", "b_mayus")
                    capa = "mayusculas" if capa == "minusculas" else "minusculas"
            self.enlace.tocar("texto", self.tecla_de(c, capa))
        self.ui.paso()

    def pedir_ssid_a_mano(self) -> None:
        self.tocar("red", "b_conectar")
        self.pasar_el_pin()
        self.cargar("texto")

    # ---- la pagina ----
    def test_principal_abre_la_pagina_de_red_con_el_estado_y_las_redes_cercanas(self) -> None:
        self.abrir_red()
        for linea in ('red.i1.txt="Conexión: WiFi «RedEjemplo»"', 'red.i2.txt="IP: 192.168.10.20"', 'red.i3.txt="Señal: 99 %"',
                      'red.i4.txt="Internet: SÍ"', 'red.i5.txt="ZeroTier: 10.99.99.10"',
                      'red.n1.txt="RedEjemplo  99%"', 'red.n2.txt="Hospital  70%"', 'red.n3.txt="Invitados  55%"', 'red.n4.txt=""'):
            self.assertIn(linea, self.enlace.enviadas)

    def test_sin_red_se_dice_en_rojo(self) -> None:
        self.abrir_red(red={"tipo": None, "internet": None, "zerotier_ip": None})
        self.assertIn('red.i1.txt="Conexión: SIN RED"', self.enlace.enviadas)
        self.assertEqual(self.pintado("red.i1.pco"), "red.i1.pco=51427")

    def test_internet_no_se_muestra_en_rojo(self) -> None:
        self.abrir_red(red={"tipo": "ethernet", "ip": "10.0.0.5", "internet": False})
        self.assertIn('red.i1.txt="Conexión: Cable (Ethernet)"', self.enlace.enviadas)
        self.assertEqual(self.pintado("red.i4.pco"), "red.i4.pco=51427")

    def test_la_barra_principal_guia_al_instalador_cuando_no_hay_red(self) -> None:
        self.datos.cola = 0
        self.ui._red = lambda: "SIN RED"
        self.arrancar_en_principal()
        self.avanzar(2.5)
        self.assertEqual(self.pintado("principal.aviso.txt"), 'principal.aviso.txt="Sin red: toque Red para conectarse"')

    def test_buscar_redes_pide_un_escaneo_al_nucleo(self) -> None:
        self.abrir_red()
        self.tocar("red", "b_buscar")
        (orden,) = self.ordenes()
        self.assertEqual(orden["tipo"], "red_buscar")
        self.avanzar(0.5)
        self.assertEqual(self.pintado("red.res.txt"), 'red.res.txt="Buscando redes..."')

    def test_volver_regresa_a_principal(self) -> None:
        self.abrir_red()
        self.tocar("red", "b_volver")
        self.assertEqual(self.enlace.enviadas[-1], "page principal")

    # ---- escribir una red a mano: PIN -> nombre -> contrasena -> confirmar -> orden ----
    def test_conectar_a_una_red_escribiendo_el_nombre_y_la_contrasena(self) -> None:
        self.abrir_red()
        self.tocar("red", "b_conectar")
        self.assertEqual(self.enlace.enviadas[-1], "page teclado")              # primero el PIN
        self.pasar_el_pin()
        self.assertEqual(self.enlace.enviadas[-1], "page texto")
        self.cargar("texto")
        self.avanzar(0.5)
        self.assertEqual(self.pintado("texto.titulo.txt"), 'texto.titulo.txt="Nombre de la red"')
        self.escribir("Mi Hospital")
        self.avanzar(0.5)
        self.assertEqual(self.pintado("texto.valor.txt"), 'texto.valor.txt="Mi Hospital"')    # el nombre se ve
        self.tocar("texto", "b_aceptar")
        self.avanzar(0.5)
        self.assertEqual(self.pintado("texto.titulo.txt"), 'texto.titulo.txt="Contraseña de Mi Hospital"')
        self.escribir(CLAVE_DE_PRUEBA)
        self.tocar("texto", "b_aceptar")
        self.assertEqual(self.enlace.enviadas[-1], "page confirmar")
        self.assertEqual(self.ordenes(), [])                                      # aun no se pidio nada
        self.cargar("confirmar")
        self.avanzar(0.5)
        self.assertEqual(self.pintado("confirmar.t_pregunta.txt"), 'confirmar.t_pregunta.txt="¿Conectar a «Mi Hospital»?"')
        self.tocar("confirmar", "b_si")
        (orden,) = self.ordenes()
        self.assertEqual((orden["tipo"], orden["ssid"], orden["contrasena"], orden["oculta"]),
                         ("red_configurar", "Mi Hospital", CLAVE_DE_PRUEBA, True))     # no se vio en la busqueda: oculta
        self.assertEqual(self.enlace.enviadas[-1], "page red")

    def test_la_contrasena_se_ve_al_escribirla_y_se_puede_ocultar_y_volver_a_ver(self) -> None:
        self.abrir_red()
        self.pedir_ssid_a_mano()
        self.escribir("Red")
        self.tocar("texto", "b_aceptar")
        self.escribir("Clave123")
        self.avanzar(0.5)
        self.assertEqual(self.pintado("texto.valor.txt"), 'texto.valor.txt="Clave123"')
        self.assertEqual(self.pintado("texto.b_ver.txt"), 'texto.b_ver.txt="Ocultar"')
        self.tocar("texto", "b_ver")
        self.avanzar(0.5)
        self.assertEqual(self.pintado("texto.valor.txt"), 'texto.valor.txt="********"')
        self.assertEqual(self.pintado("texto.b_ver.txt"), 'texto.b_ver.txt="Ver"')
        self.tocar("texto", "b_ver")
        self.avanzar(0.5)
        self.assertEqual(self.pintado("texto.valor.txt"), 'texto.valor.txt="Clave123"')

    def test_la_contrasena_oculta_no_se_manda_a_la_pantalla(self) -> None:
        self.abrir_red()
        self.pedir_ssid_a_mano()
        self.escribir("Red")
        self.tocar("texto", "b_aceptar")
        self.tocar("texto", "b_ver")                                              # la oculta antes de escribir
        self.enlace.enviadas.clear()
        self.escribir(CLAVE_DE_PRUEBA)
        self.avanzar(1.0)
        self.assertEqual([o for o in self.enlace.enviadas if CLAVE_DE_PRUEBA in o], [])

    def test_la_contrasena_no_sale_en_el_registro_de_la_interfaz(self) -> None:
        self.abrir_red()
        with self.assertLogs("g2.pantalla", level="DEBUG") as registro:
            self.pedir_ssid_a_mano()
            self.escribir("Mi Hospital")
            self.tocar("texto", "b_aceptar")
            self.escribir(CLAVE_DE_PRUEBA)
            self.tocar("texto", "b_aceptar")
            self.cargar("confirmar")
            self.tocar("confirmar", "b_si")
        self.assertNotIn(CLAVE_DE_PRUEBA, "\n".join(registro.output))
        self.assertIn("Mi Hospital", "\n".join(registro.output))                  # el nombre de la red SI se registra

    def test_la_capa_de_mayusculas_y_simbolos_repinta_las_teclas(self) -> None:
        self.abrir_red()
        self.pedir_ssid_a_mano()
        self.avanzar(0.5)
        self.assertEqual(self.pintado("texto.t_10.txt"), 'texto.t_10.txt="q"')
        self.assertEqual(self.pintado("texto.b_mayus.txt"), 'texto.b_mayus.txt="ABC"')
        self.tocar("texto", "b_mayus")
        self.avanzar(0.5)
        self.assertEqual(self.pintado("texto.t_10.txt"), 'texto.t_10.txt="Q"')
        self.assertEqual(self.pintado("texto.b_mayus.txt"), 'texto.b_mayus.txt="abc"')
        self.tocar("texto", "b_simbolos")
        self.avanzar(0.5)
        self.assertEqual(self.pintado("texto.t_00.txt"), 'texto.t_00.txt="!"')
        self.assertEqual(self.pintado("texto.t_30.txt"), 'texto.t_30.txt=";"'.replace(";", txt.CAPAS["simbolos"][30]))

    def test_las_comillas_y_la_barra_invertida_se_escapan_en_las_etiquetas(self) -> None:
        self.abrir_red()
        self.pedir_ssid_a_mano()
        self.tocar("texto", "b_simbolos")
        self.avanzar(0.5)
        self.assertIn('texto.t_19.txt="\\\\"', self.enlace.enviadas)                  # la barra invertida
        self.assertIn('texto.t_23.txt="\\""', self.enlace.enviadas)                    # la comilla doble

    def test_se_puede_escribir_cualquier_simbolo_ascii_y_un_espacio(self) -> None:
        self.abrir_red()
        self.pedir_ssid_a_mano()
        self.escribir("a b")
        self.tocar("texto", "b_limpiar")
        self.escribir("a\\\"'~`")
        self.avanzar(0.5)
        self.assertEqual(self.pintado("texto.valor.txt"), 'texto.valor.txt="a\\\\\\"\'~`"')

    # ---- elegir una red de la lista ----
    def test_tocar_una_red_cercana_salta_el_nombre_y_pide_solo_la_contrasena(self) -> None:
        self.abrir_red()
        self.tocar("red", "n2")                                                   # Hospital
        self.pasar_el_pin()
        self.cargar("texto")
        self.avanzar(0.5)
        self.assertEqual(self.pintado("texto.titulo.txt"), 'texto.titulo.txt="Contraseña de Hospital"')
        self.assertEqual(self.pintado("texto.msg.txt"), 'texto.msg.txt="Entre 8 y 63 caracteres"')
        self.escribir(CLAVE_DE_PRUEBA)
        self.tocar("texto", "b_aceptar")
        self.cargar("confirmar")
        self.tocar("confirmar", "b_si")
        (orden,) = self.ordenes()
        self.assertEqual((orden["ssid"], orden["contrasena"], orden["oculta"]), ("Hospital", CLAVE_DE_PRUEBA, False))

    def test_una_red_abierta_de_la_lista_no_pide_contrasena(self) -> None:
        self.abrir_red()
        self.tocar("red", "n3")                                                   # Invitados (sin seguridad)
        self.pasar_el_pin()
        self.assertEqual(self.enlace.enviadas[-1], "page confirmar")
        self.cargar("confirmar")
        self.avanzar(0.5)
        self.assertIn("Red abierta", self.pintado("confirmar.t_detalle.txt"))
        self.tocar("confirmar", "b_si")
        (orden,) = self.ordenes()
        self.assertEqual((orden["ssid"], orden["contrasena"]), ("Invitados", ""))

    def test_un_nombre_escrito_que_coincide_con_una_red_vista_no_se_marca_oculta(self) -> None:
        self.abrir_red()
        self.pedir_ssid_a_mano()
        self.escribir("Hospital")
        self.tocar("texto", "b_aceptar")
        self.escribir(CLAVE_DE_PRUEBA)
        self.tocar("texto", "b_aceptar")
        self.cargar("confirmar")
        self.tocar("confirmar", "b_si")
        self.assertFalse(self.ordenes()[0]["oculta"])

    def test_una_red_vista_con_seguridad_no_admite_contrasena_vacia(self) -> None:
        self.abrir_red()
        self.tocar("red", "n2")
        self.pasar_el_pin()
        self.cargar("texto")
        self.tocar("texto", "b_aceptar")
        self.avanzar(0.5)
        self.assertEqual(self.pintado("texto.msg.txt"), 'texto.msg.txt="Esta red necesita contraseña"')
        self.assertEqual(self.ordenes(), [])

    def test_un_nombre_escrito_desconocido_admite_contrasena_vacia_como_red_abierta(self) -> None:
        self.abrir_red()
        self.pedir_ssid_a_mano()
        self.escribir("Kiosco")
        self.tocar("texto", "b_aceptar")
        self.avanzar(0.5)
        self.assertIn("Vacío = red abierta", self.pintado("texto.msg.txt"))
        self.tocar("texto", "b_aceptar")
        self.assertEqual(self.enlace.enviadas[-1], "page confirmar")

    # ---- errores y cancelaciones ----
    def test_un_nombre_vacio_o_una_contrasena_corta_se_explican_y_no_se_envian(self) -> None:
        self.abrir_red()
        self.pedir_ssid_a_mano()
        self.tocar("texto", "b_aceptar")
        self.avanzar(0.5)
        self.assertEqual(self.pintado("texto.msg.txt"), 'texto.msg.txt="Escriba el nombre de la red"')
        self.escribir("Red")
        self.tocar("texto", "b_aceptar")
        self.escribir("corta")
        self.tocar("texto", "b_aceptar")
        self.avanzar(0.5)
        self.assertIn("entre 8 y 63", self.pintado("texto.msg.txt"))
        self.assertEqual(self.pintado("texto.msg.pco"), "texto.msg.pco=51427")
        self.assertEqual(self.ordenes(), [])

    def test_los_limites_de_largo_se_respetan(self) -> None:
        self.abrir_red()
        self.pedir_ssid_a_mano()
        for _ in range(40):
            self.enlace.tocar("texto", "t_10")
        self.ui.paso()
        self.assertEqual(len(self.ui._texto.buffer), 32)                           # el nombre admite 32
        self.tocar("texto", "b_aceptar")
        for _ in range(70):
            self.enlace.tocar("texto", "t_10")
        self.ui.paso()
        self.assertEqual(len(self.ui._texto.buffer), 63)                           # la contrasena admite 63

    def test_el_campo_muestra_solo_los_ultimos_caracteres_si_no_caben(self) -> None:
        self.abrir_red()
        self.pedir_ssid_a_mano()
        for _ in range(30):
            self.enlace.tocar("texto", "t_10")
        self.ui.paso()
        self.avanzar(0.5)
        valor = self.pintado("texto.valor.txt")
        self.assertTrue(valor.startswith('texto.valor.txt="...'))
        self.assertLessEqual(len(valor) - len('texto.valor.txt=""'), 24)

    def test_cancelar_descarta_lo_escrito_y_vuelve_a_red(self) -> None:
        self.abrir_red()
        self.pedir_ssid_a_mano()
        self.escribir("Red")
        self.tocar("texto", "b_cancelar")
        self.assertEqual(self.enlace.enviadas[-1], "page red")
        self.assertEqual(self.ordenes(), [])
        self.assertIsNone(self.ui._texto)

    def test_decir_no_en_la_confirmacion_descarta_la_contrasena(self) -> None:
        self.abrir_red()
        self.pedir_ssid_a_mano()
        self.escribir("Red")
        self.tocar("texto", "b_aceptar")
        self.escribir(CLAVE_DE_PRUEBA)
        self.tocar("texto", "b_aceptar")
        self.cargar("confirmar")
        self.tocar("confirmar", "b_no")
        self.assertEqual(self.ordenes(), [])
        self.assertIsNone(self.ui._confirmacion)

    def test_salir_del_teclado_de_texto_por_otra_via_descarta_lo_escrito(self) -> None:
        self.abrir_red()
        self.pedir_ssid_a_mano()
        self.escribir("Red")
        self.cargar("principal")
        self.assertIsNone(self.ui._texto)
        self.enlace.tocar("texto", "b_aceptar")                                    # un toque tardio no hace nada
        self.ui.paso()
        self.assertEqual(self.ordenes(), [])

    def test_sin_el_pin_no_se_puede_empezar_a_cambiar_la_red(self) -> None:
        self.abrir_red()
        self.tocar("red", "b_conectar")
        self.cargar("teclado")
        self.tocar("teclado", "b_cancelar")
        self.assertEqual(self.enlace.enviadas[-1], "page red")
        self.assertNotIn("page texto", self.enlace.enviadas)

    # ---- progreso y resultado ----
    def test_mientras_se_conecta_la_pagina_lo_dice(self) -> None:
        self.abrir_red()
        self.publicar_red(cambio={"en_curso": "Hospital", "ultimo": None})
        self.avanzar(1.5)
        self.assertEqual(self.pintado("red.res.txt"), 'red.res.txt="Conectando a «Hospital»..."')

    def test_el_resultado_de_un_cambio_se_muestra_y_el_fallo_en_rojo(self) -> None:
        self.abrir_red()
        self.publicar_red(cambio={"en_curso": None, "ultimo": {"ssid": "Hospital", "ok": False, "revertida": True,
                                                                "sin_internet": False, "motivo": "contrasena",
                                                                "mensaje": "Contraseña incorrecta"}})
        self.avanzar(1.5)
        self.assertEqual(self.pintado("red.res.txt"), 'red.res.txt="Contraseña incorrecta"')
        self.assertEqual(self.pintado("red.res.pco"), "red.res.pco=51427")
        self.publicar_red(cambio={"en_curso": None, "ultimo": {"ssid": "Hospital", "ok": True, "revertida": False,
                                                                "sin_internet": False, "motivo": "",
                                                                "mensaje": "Conectado a «Hospital»"}})
        self.avanzar(1.5)
        self.assertEqual(self.pintado("red.res.txt"), 'red.res.txt="Conectado a «Hospital»"')
        self.assertEqual(self.pintado("red.res.pco"), "red.res.pco=25423")

    def test_un_resultado_viejo_de_antes_de_arrancar_la_interfaz_no_se_muestra(self) -> None:
        viejo = {"ssid": "X", "ok": False, "revertida": False, "sin_internet": False, "motivo": "otro",
                 "mensaje": "Mensaje de ayer"}
        self.abrir_red(cambio={"en_curso": None, "ultimo": viejo})
        self.avanzar(1.5)
        self.assertEqual(self.pintado("red.res.txt"), 'red.res.txt=""')

    def test_si_el_nucleo_no_responde_la_pagina_no_muestra_una_red_vieja(self) -> None:
        self.abrir_red()
        self.publicando = False
        self.enlace.enviadas.clear()
        self.avanzar(8.0)
        self.assertIn('red.i1.txt="Conexión: SIN RED"', self.enlace.enviadas)


class PruebasEntradaDeTexto(unittest.TestCase):
    def test_cada_capa_tiene_40_teclas_y_cubre_todo_el_ascii_imprimible(self) -> None:
        import string
        for capa, teclas in txt.CAPAS.items():
            self.assertEqual(len(teclas), 40, capa)
        todo = set("".join(txt.CAPAS.values()))
        self.assertTrue(set(string.ascii_letters + string.digits + string.punctuation) <= todo)

    def test_teclas_capas_y_borrado(self) -> None:
        e = txt.EntradaTexto(secreto=False, largo_max=10)
        e.tecla("t_10")
        e.tecla("b_mayus")
        e.tecla("t_11")
        e.tecla("b_simbolos")
        e.tecla("t_00")
        self.assertEqual((e.buffer, e.capa), ("qW!", "simbolos"))
        e.tecla("b_simbolos")
        self.assertEqual(e.capa, "minusculas")
        e.tecla("b_borrar")
        self.assertEqual(e.buffer, "qW")
        e.tecla("b_espacio")
        self.assertEqual(e.buffer, "qW ")
        e.tecla("b_limpiar")
        self.assertEqual(e.buffer, "")

    def test_las_teclas_vacias_de_la_capa_de_simbolos_no_hacen_nada(self) -> None:
        e = txt.EntradaTexto(secreto=False, largo_max=10)
        e.tecla("b_simbolos")
        self.assertFalse(e.tecla("t_39"))
        self.assertEqual(e.buffer, "")

    def test_un_toque_raro_no_rompe_nada(self) -> None:
        e = txt.EntradaTexto(secreto=False, largo_max=10)
        for control in ("t_40", "t_99", "t_", "t_x", "b_inexistente", ""):
            self.assertFalse(e.tecla(control), control)

    def test_ver_solo_funciona_en_los_campos_secretos(self) -> None:
        nombre = txt.EntradaTexto(secreto=False, largo_max=10, inicial="Red")
        self.assertFalse(nombre.tecla("b_ver"))
        self.assertEqual((nombre.mostrar(), nombre.rotulo_ver()), ("Red", ""))
        clave = txt.EntradaTexto(secreto=True, largo_max=10, inicial="abcd")
        self.assertEqual((clave.mostrar(), clave.rotulo_ver()), ("abcd", "Ocultar"))
        self.assertTrue(clave.tecla("b_ver"))
        self.assertEqual((clave.mostrar(), clave.rotulo_ver()), ("****", "Ver"))

    def test_el_largo_maximo(self) -> None:
        e = txt.EntradaTexto(secreto=False, largo_max=3)
        for _ in range(10):
            e.tecla("t_10")
        self.assertEqual(len(e.buffer), 3)
        e.tecla("b_espacio")
        self.assertEqual(len(e.buffer), 3)


class PruebasVistasDeRed(unittest.TestCase):
    def test_con_el_nucleo_caido_no_hay_red_ni_redes(self) -> None:
        from g2.pantalla import vistas
        v = vistas.vista_red({"tipo": "wifi", "ssid": "X"}, [{"ssid": "Y", "senal": 5}], None, nucleo_responde=False,
                             resultado=None)
        self.assertEqual(v["red.i1.txt"], "Conexión: SIN RED")
        self.assertEqual(v["red.n1.txt"], "")

    def test_nombres_largos_se_recortan(self) -> None:
        from g2.pantalla import vistas
        redes = [{"ssid": "N" * 40, "senal": 50, "seguridad": "WPA2"}]
        v = vistas.vista_red({"tipo": "wifi", "ssid": "S" * 60}, redes, None, nucleo_responde=True, resultado=None)
        self.assertLessEqual(len(v["red.n1.txt"]), 40)
        self.assertLessEqual(len(v["red.i1.txt"]), 40)

class PruebasDiagnosticoDeOrdenesRechazadas(BaseEtapa1):
    def test_el_aviso_de_orden_rechazada_dice_cuales_fueron_las_ultimas_ordenes(self) -> None:
        self.arrancar_en_principal()
        self.enlace.inyectar(bytes([0x1A]))
        with self.assertLogs("g2.pantalla", level="WARNING") as registro:
            self.ui.paso()
        self.assertIn("variable o atributo invalido", registro.output[0])
        self.assertIn("principal.aviso.txt", registro.output[0])                  # las ultimas ordenes que se mandaron

    def test_el_campo_del_teclado_de_texto_nunca_se_copia_al_aviso(self) -> None:
        self.ultimo = None
        self.nucleo.publicar(estado())
        self.arrancar_en_principal()
        self.cargar("texto")
        self.enlace.tocar("texto", "t_10")
        self.enlace.tocar("texto", "b_ver")
        self.ui.paso()
        self.avanzar(0.5)
        self.enlace.inyectar(bytes([0x1A]))
        with self.assertLogs("g2.pantalla", level="WARNING") as registro:
            self.ui.paso()
        self.assertNotIn('texto.valor.txt="q"', registro.output[0])

class PruebasVolumenYProteccion(BaseEtapa1):
    def con_alarma_sonando(self) -> None:
        self.ultimo = estado(s1=("15.0", "BAJA", False), aviso="S1 BAJO 15.0 %", sonar=True)
        self.nucleo.publicar(self.ultimo)
        self.arrancar_en_principal()

    def volumenes(self) -> list[str]:
        return [o for o in self.enlace.enviadas if o.startswith("volume=")]

    def test_al_iniciar_fija_el_volumen_antes_de_cambiar_de_pagina(self) -> None:
        self.ui.iniciar()
        self.assertEqual(self.enlace.enviadas[:2], ["volume=50", "page principal"])

    def test_el_volumen_sale_de_la_configuracion(self) -> None:
        self.datos.volumen = 35.0
        self.ui.iniciar()
        self.assertEqual(self.volumenes(), ["volume=35"])

    def test_un_volumen_fuera_de_rango_se_recorta(self) -> None:
        self.datos.volumen = 250.0
        self.ui.iniciar()
        self.assertEqual(self.volumenes(), ["volume=100"])

    def test_cada_vez_que_la_pantalla_enciende_la_pi_corrige_el_volumen_del_hmi(self) -> None:
        self.arrancar_en_principal()
        self.enlace.enviadas.clear()
        self.enlace.encendida()
        self.ui.paso()
        self.assertEqual(self.enlace.enviadas[:2], ["volume=50", "page principal"])

    def test_un_reinicio_sin_relacion_con_el_sonido_no_baja_el_volumen(self) -> None:
        self.arrancar_en_principal()
        self.avanzar(30.0)
        self.enlace.encendida()
        self.ui.paso()
        self.assertEqual(self.volumenes()[-1], "volume=50")

    def test_un_reinicio_justo_despues_de_sonar_baja_el_volumen(self) -> None:
        self.con_alarma_sonando()
        self.avanzar(1.0)
        self.assertIn("play 0,1,0", self.enlace.enviadas)
        with self.assertLogs("g2.pantalla", level="ERROR") as registro:
            self.enlace.encendida()
            self.ui.paso()
        self.assertEqual(self.volumenes()[-1], "volume=30")
        self.assertIn("demasiado alto", registro.output[0])

    def test_si_sigue_reiniciandose_el_volumen_baja_mas_y_al_tercero_se_calla_el_sonido(self) -> None:
        self.con_alarma_sonando()
        with self.assertLogs("g2.pantalla", level="ERROR"):
            for _ in range(3):
                self.avanzar(3.5)                                          # vuelve a sonar
                self.enlace.encendida()                                    # y la pantalla se reinicia
                self.ui.paso()
        self.assertEqual(self.volumenes()[-3:], ["volume=30", "volume=10", "volume=10"])      # nunca por debajo de 10
        sonidos = self.enlace.enviadas.count("play 0,1,0")
        self.avanzar(30.0)
        self.assertEqual(self.enlace.enviadas.count("play 0,1,0"), sonidos)                    # callado

    def test_con_el_sonido_callado_la_alarma_visual_sigue(self) -> None:
        self.con_alarma_sonando()
        with self.assertLogs("g2.pantalla", level="ERROR"):
            for _ in range(3):
                self.avanzar(3.5)
                self.enlace.encendida()
                self.ui.paso()
        self.cargar("principal")
        self.avanzar(2.0)
        self.assertIn('principal.est_1.txt="BAJA"', self.enlace.enviadas)
        self.assertIn('principal.aviso.txt="S1 BAJO 15.0 %"', self.enlace.enviadas)

    def test_pasados_10_minutos_el_sonido_vuelve_a_intentarse(self) -> None:
        self.con_alarma_sonando()
        with self.assertLogs("g2.pantalla", level="ERROR"):
            for _ in range(3):
                self.avanzar(3.5)
                self.enlace.encendida()
                self.ui.paso()
        sonidos = self.enlace.enviadas.count("play 0,1,0")
        self.avanzar(601.0)
        self.assertGreater(self.enlace.enviadas.count("play 0,1,0"), sonidos)

    def test_reinicios_espaciados_en_el_tiempo_no_acumulan_hasta_callar(self) -> None:
        self.con_alarma_sonando()
        with self.assertLogs("g2.pantalla", level="ERROR"):
            for _ in range(3):
                self.avanzar(3.5)
                self.enlace.encendida()
                self.ui.paso()
                self.avanzar(70.0)                                          # pasa la ventana de 60 s entre uno y otro
        sonidos = self.enlace.enviadas.count("play 0,1,0")
        self.avanzar(8.0)
        self.assertGreater(self.enlace.enviadas.count("play 0,1,0"), sonidos)                  # sigue intentando sonar

class PruebasCambioDePagina(BaseInterfaz):
    def test_mientras_llega_la_pagina_nueva_no_se_pinta_la_vieja(self) -> None:
        self.arrancar_en_principal()
        self.enlace.tocar("principal", "b_alarmas")
        self.ui.paso()
        self.assertEqual(self.enlace.enviadas[-1], "page alarmas")
        self.enlace.enviadas.clear()
        self.publicar(estado(s1=("21.4", "NORMAL", False)))                   # el valor cambia mientras la pantalla cambia de pagina
        self.avanzar(1.0)
        self.assertEqual([o for o in self.enlace.enviadas if o.startswith("principal.")], [])
        self.cargar("alarmas")
        self.avanzar(0.5)
        self.assertTrue([o for o in self.enlace.enviadas if o.startswith("alarmas.")])      # y la nueva si se pinta

    def test_si_la_pagina_nunca_carga_se_vuelve_a_pintar_pasado_un_tiempo(self) -> None:
        self.arrancar_en_principal()
        self.enlace.tocar("principal", "b_alarmas")
        self.ui.paso()
        self.enlace.enviadas.clear()
        self.publicar(estado(s1=("21.4", "NORMAL", False)))
        self.avanzar(4.0)
        self.assertIn('principal.o2_1.txt="21.4"', self.enlace.enviadas)


class PruebasGrafica(BaseInterfaz):
    """La grafica de las dos senales aparece tras 10 s sin tocar la pantalla principal y un toque la cierra (D-043)."""

    def setUp(self) -> None:
        super().setUp()
        self.datos.grafica_espera = 10.0

    def pedidas(self) -> int:
        return self.enlace.enviadas.count("page grafica")

    def completar_transferencias(self) -> None:
        """Hace de pantalla: responde "lista" y "recibido" a cada addt que la Pi espera."""
        for _ in range(8):
            self.enlace.datos_listos()
            self.ui.paso()
            self.enlace.datos_recibidos()
            self.ui.paso()

    def llegar_a_la_grafica(self, est: dict | None = None) -> None:
        """Arranca en la principal, deja pasar el tiempo hasta que la Pi pide la grafica y la pantalla la carga."""
        if est is not None:
            self.publicar(est)
        self.arrancar_en_principal()
        self.avanzar(11.0)
        self.assertEqual(self.pedidas(), 1)
        self.cargar("grafica")
        self.avanzar(0.6)

    def abrir(self, est: dict | None = None) -> None:
        self.llegar_a_la_grafica(est)
        self.completar_transferencias()

    @staticmethod
    def con_alarma_sin_acusar() -> dict:
        e = estado(s1=("15.0", "BAJA", False), aviso="S1 BAJO 15.0 %", sonar=True)
        e["parpadeo"] = True
        return e

    # ---- cuando se abre ----
    def test_al_iniciar_y_al_encender_pide_los_toques_de_toda_la_pantalla(self) -> None:
        self.ui.iniciar()
        self.assertIn("sendxy=1", self.enlace.enviadas)
        self.enlace.enviadas.clear()
        self.enlace.encendida()
        self.ui.paso()
        self.assertIn("sendxy=1", self.enlace.enviadas)

    def test_desactivada_si_la_espera_es_cero(self) -> None:
        self.datos.grafica_espera = 0.0
        self.arrancar_en_principal()
        self.avanzar(60.0)
        self.assertEqual(self.pedidas(), 0)

    def test_se_abre_tras_10_segundos_sin_tocar(self) -> None:
        self.arrancar_en_principal()
        self.avanzar(9.0)
        self.assertEqual(self.pedidas(), 0)
        self.avanzar(3.0)
        self.assertEqual(self.pedidas(), 1)

    def test_un_toque_en_cualquier_punto_reinicia_la_cuenta(self) -> None:
        self.arrancar_en_principal()
        self.avanzar(8.0)
        self.enlace.tocar_en(100, 100)                                   # en una zona sin botones
        self.avanzar(8.0)
        self.assertEqual(self.pedidas(), 0)
        self.avanzar(3.0)
        self.assertEqual(self.pedidas(), 1)

    def test_el_toque_de_un_boton_tambien_reinicia_la_cuenta(self) -> None:
        self.arrancar_en_principal()
        self.avanzar(8.0)
        self.enlace.tocar("principal", "b_acuse")
        self.avanzar(8.0)
        self.assertEqual(self.pedidas(), 0)

    def test_no_se_abre_con_una_alarma_sin_acusar(self) -> None:
        self.publicar(self.con_alarma_sin_acusar())
        self.arrancar_en_principal()
        self.avanzar(30.0)
        self.assertEqual(self.pedidas(), 0)

    def test_con_la_alarma_acusada_si_se_abre(self) -> None:
        self.publicar(estado(s1=("15.0", "BAJA", True), aviso="S1 BAJO 15.0 %"))
        self.arrancar_en_principal()
        self.avanzar(12.0)
        self.assertEqual(self.pedidas(), 1)

    def test_solo_se_abre_desde_la_principal(self) -> None:
        self.arrancar_en_principal()
        self.cargar("alarmas")
        self.avanzar(30.0)
        self.assertEqual(self.pedidas(), 0)

    def test_no_se_abre_si_el_nucleo_no_responde(self) -> None:
        self.arrancar_en_principal()
        self.publicando = False
        self.avanzar(30.0)
        self.assertEqual(self.pedidas(), 0)

    def test_la_pi_sigue_tomando_muestras_aunque_la_grafica_este_cerrada(self) -> None:
        self.datos.grafica_espera = 0.0
        self.arrancar_en_principal()
        self.avanzar(20.0)
        self.assertGreaterEqual(self.ui._hist.cantidad(), 14)

    # ---- como se cierra ----
    def test_un_toque_en_la_grafica_vuelve_a_la_principal(self) -> None:
        self.abrir()
        self.enlace.enviadas.clear()
        self.enlace.tocar("grafica", "salir")
        self.ui.paso()
        self.assertEqual(self.enlace.enviadas[-1], "page principal")

    def test_despues_de_cerrarla_no_vuelve_a_abrirse_hasta_pasar_otros_10_segundos(self) -> None:
        self.abrir()
        self.enlace.tocar("grafica", "salir")
        self.ui.paso()
        self.cargar("principal")
        self.avanzar(8.0)
        self.assertEqual(self.pedidas(), 1)
        self.avanzar(3.0)
        self.assertEqual(self.pedidas(), 2)

    def test_si_salta_una_alarma_con_la_grafica_abierta_vuelve_a_la_principal(self) -> None:
        self.abrir()
        self.enlace.enviadas.clear()
        self.publicar(self.con_alarma_sin_acusar())
        self.avanzar(1.5)
        self.assertIn("page principal", self.enlace.enviadas)
        self.cargar("principal")
        self.enlace.enviadas.clear()
        self.avanzar(30.0)
        self.assertEqual(self.pedidas(), 0)                                # y no se reabre mientras siga sin acusar

    def test_si_el_nucleo_deja_de_responder_con_la_grafica_abierta_vuelve_a_la_principal(self) -> None:
        self.abrir()
        self.enlace.enviadas.clear()
        self.publicando = False
        self.avanzar(8.0)
        self.assertIn("page principal", self.enlace.enviadas)

    def test_si_la_pantalla_no_tiene_la_pagina_se_desactiva_sin_repetir_el_error(self) -> None:
        self.arrancar_en_principal()
        self.avanzar(11.0)
        self.assertEqual(self.pedidas(), 1)
        with self.assertLogs("g2.pantalla", level="ERROR"):
            self.enlace.inyectar(bytes([0x03]))                              # "pagina inexistente"
            self.ui.paso()
        self.avanzar(60.0)
        self.assertEqual(self.pedidas(), 1)
        self.enlace.encendida()                                              # un .tft nuevo: se vuelve a intentar
        self.ui.paso()
        self.cargar("principal")
        self.avanzar(11.0)
        self.assertEqual(self.pedidas(), 2)

    # ---- como se dibuja ----
    def test_al_abrirla_se_dibuja_todo_con_addt(self) -> None:
        self.llegar_a_la_grafica()
        n = self.ui._hist.cantidad()
        self.assertIn("cle s0.id,255", self.enlace.enviadas)
        self.assertIn(f"addt s0.id,0,{n}", self.enlace.enviadas)
        self.assertEqual(self.enlace.crudas, [])                             # los bytes esperan a que la pantalla este lista
        self.enlace.datos_listos()
        self.ui.paso()
        self.assertEqual(len(self.enlace.crudas[0]), n)
        self.enlace.datos_recibidos()
        self.ui.paso()
        self.assertIn(f"addt s0.id,1,{n}", self.enlace.enviadas)             # sigue con el segundo canal

    def test_se_dibujan_los_valores_actuales_y_las_marcas_del_eje(self) -> None:
        self.abrir()
        for esperado in ('grafica.v1.txt="S1  20.9 %  NORMAL"', f"grafica.v1.pco={P.COLOR['sensor1']}",
                         'grafica.y_max.txt="24"', 'grafica.y_min.txt="17"'):
            self.assertIn(esperado, self.enlace.enviadas)

    def test_el_limite_bajo_de_alarma_se_dibuja_como_tercer_canal_y_el_alto_no_(self) -> None:
        self.abrir()
        canales = [o for o in self.enlace.enviadas if o.startswith("addt s0.id,")]
        self.assertEqual([c.split(",")[1] for c in canales], ["0", "1", "2"])   # el limite alto (92 %) cae fuera del eje

    def test_un_sensor_sin_senal_se_dibuja_en_el_nivel_cero(self) -> None:
        self.abrir(estado(s2=("--.-", "SIN SEÑAL", False)))
        self.assertNotIn(0, self.enlace.crudas[0])
        self.assertEqual(set(self.enlace.crudas[1]), {0})

    def test_con_la_grafica_abierta_cada_segundo_agrega_un_punto_a_cada_canal(self) -> None:
        self.abrir()
        self.enlace.enviadas.clear()
        self.avanzar(5.0)
        sensor1 = [o for o in self.enlace.enviadas if o.startswith("add s0.id,0,")]
        sensor2 = [o for o in self.enlace.enviadas if o.startswith("add s0.id,1,")]
        self.assertGreaterEqual(len(sensor1), 3)
        self.assertEqual(len(sensor1), len(sensor2))
        self.assertEqual(self.enlace.crudas[0:0], [])
        self.assertFalse([o for o in self.enlace.enviadas if o.startswith(("cle", "addt"))])   # sin redibujar todo

    def test_si_un_valor_sale_del_eje_se_redibuja_todo(self) -> None:
        self.abrir()
        self.enlace.enviadas.clear()
        self.publicar(estado(s1=("40.0", "NORMAL", False)))
        self.avanzar(3.0)
        self.assertIn("cle s0.id,255", self.enlace.enviadas)
        self.assertTrue([o for o in self.enlace.enviadas if o.startswith("addt")])

    def test_lo_que_llega_durante_la_transferencia_espera_a_que_termine(self) -> None:
        self.llegar_a_la_grafica()
        antes = len(self.enlace.enviadas)
        self.publicar(estado(s1=("21.4", "NORMAL", False)))
        self.avanzar(2.0)
        self.assertEqual([o for o in self.enlace.enviadas[antes:] if "grafica.v1" in o], [])    # nada se mezcla con los bytes
        self.completar_transferencias()
        self.assertIn('grafica.v1.txt="S1  21.4 %  NORMAL"', self.enlace.enviadas[antes:])

    def test_si_la_pantalla_no_responde_al_addt_se_dibuja_con_add(self) -> None:
        self.llegar_a_la_grafica()
        with self.assertLogs("g2.pantalla", level="WARNING"):
            self.avanzar(6.0)
        self.assertFalse(self.ui._con_bloques)
        self.assertTrue([o for o in self.enlace.enviadas if o.startswith("add s0.id,0,")])
        self.assertEqual(self.enlace.crudas, [])

    def test_un_reinicio_de_la_pantalla_abandona_la_transferencia(self) -> None:
        self.llegar_a_la_grafica()
        self.enlace.encendida()
        self.ui.paso()
        self.assertIsNone(self.ui._espera_datos)
        self.enlace.enviadas.clear()
        self.cargar("principal")
        self.assertIn('principal.o2_1.txt="20.9"', self.enlace.enviadas)       # sigue funcionando con normalidad

    def test_si_la_pantalla_rechaza_las_ordenes_de_la_grafica_se_desactiva_y_vuelve_a_la_principal(self) -> None:
        self.abrir()
        self.avanzar(2.0)                                                       # ya se estan mandando puntos con add
        self.assertTrue([o for o in self.enlace.enviadas if o.startswith("add s0.id,")])
        with self.assertLogs("g2.pantalla", level="WARNING") as registro:
            for _ in range(5):
                self.enlace.inyectar(bytes([0x1A]))                              # "variable o atributo invalido"
                self.ui.paso()
        self.assertEqual(self.enlace.enviadas[-1], "page principal")
        self.assertEqual(len(registro.output), 2)                               # un aviso y un error: no una linea por rechazo
        self.cargar("principal")
        self.avanzar(30.0)
        self.assertEqual(self.pedidas(), 1)                                     # y no vuelve a abrirse

    def test_tras_ordenar_volver_no_se_siguen_mandando_puntos_a_la_pagina_que_ya_no_los_tiene(self) -> None:
        self.abrir()
        self.avanzar(2.0)
        self.enlace.tocar("grafica", "salir")
        self.ui.paso()
        indice = len(self.enlace.enviadas)
        self.avanzar(3.0)                                                       # la pagina principal aun no termina de cargar
        self.assertEqual([o for o in self.enlace.enviadas[indice:] if o.startswith(("add ", "cle ", "addt "))], [])

    def test_la_cuenta_de_rechazos_no_desactiva_la_grafica_por_ordenes_enviadas_al_volver(self) -> None:
        self.abrir()
        self.avanzar(2.0)
        self.enlace.tocar("grafica", "salir")
        self.ui.paso()
        for _ in range(5):                                                      # rechazos de puntos que ya estaban en camino
            self.enlace.inyectar(bytes([0x1A]))
            self.ui.paso()
        self.cargar("principal")
        self.avanzar(11.0)
        self.assertEqual(self.pedidas(), 2)                                     # la grafica sigue disponible

    def test_un_rechazo_ajeno_a_la_grafica_se_sigue_registrando_como_siempre(self) -> None:
        self.arrancar_en_principal()
        with self.assertLogs("g2.pantalla", level="WARNING") as registro:
            self.enlace.inyectar(bytes([0x1A]))
            self.ui.paso()
        self.assertIn("la pantalla rechazo una orden:", registro.output[0])



if __name__ == "__main__":
    unittest.main()
