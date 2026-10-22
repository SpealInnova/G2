"""Pruebas del gestor de red (g2.red.gestor) con un nmcli FALSO: ninguna toca la red real."""

from __future__ import annotations

import logging
import unittest

from g2.red import gestor as G
from g2.red.gestor import ErrorRed, GestorRed, RedVisible

CLAVE = "Cl@ve:secreta #9"                                  # contrasena de prueba (con caracteres especiales)


class NmcliFalso:
    """Imita lo que usa el gestor de ``nmcli``: dispositivos, perfiles, escaneo, crear, borrar y activar."""

    def __init__(self) -> None:
        # redes que existen en el aire: ssid -> clave (None = abierta), si salen a internet y la senal
        self.redes = {"RedEjemplo": {"clave": "claveSpeal2", "internet": True, "senal": 99},
                      "Hospital": {"clave": CLAVE, "internet": True, "senal": 70},
                      "Sin salida": {"clave": "sinsalida123", "internet": False, "senal": 60},
                      "Abierta": {"clave": None, "internet": True, "senal": 40},
                      "Oculta": {"clave": "ocultaoculta", "internet": True, "senal": 0, "oculta": True}}
        self.perfiles: dict[str, dict] = {"netplan-wlan0-RedEjemplo": {"ssid": "RedEjemplo", "clave": "claveSpeal2", "prio": 0}}
        self.activo: str | None = "netplan-wlan0-RedEjemplo"          # perfil wifi activo
        self.ethernet = False
        self.wifi = True
        self.comandos: list[list[str]] = []
        self.fallar_al_crear = False

    # ---- la "sonda" de internet ----
    def hay_internet(self, interfaz: str | None) -> bool:
        if interfaz is None:
            if self.ethernet:
                return True
            return self.activo is not None and self.redes[self.perfiles[self.activo]["ssid"]]["internet"]
        if interfaz == "wlan0":
            return self.activo is not None and self.redes[self.perfiles[self.activo]["ssid"]]["internet"]
        return self.ethernet

    # ---- el "nmcli" ----
    def __call__(self, argumentos: list[str], tiempo_max_s: float = 30.0):
        self.comandos.append(list(argumentos))
        a = list(argumentos)
        if a[:2] == ["--wait", a[1]]:
            a = a[2:]
        if a[:4] == ["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"]:
            filas = []
            if self.wifi:
                if self.activo:
                    filas.append(f"wlan0:wifi:connected:{self.activo}")
                else:
                    filas.append("wlan0:wifi:disconnected:")
            filas.append("eth0:ethernet:" + ("connected:netplan-eth0" if self.ethernet else "unavailable:"))
            filas.append("ztexample01:tun:connected (externally):ztexample01")
            return 0, "\n".join(filas) + "\n", ""
        if a[:3] == ["-t", "-g", "IP4.ADDRESS"]:
            return 0, {"wlan0": "192.168.10.20/24", "eth0": "192.168.10.21/24", "ztexample01": "10.99.99.10/24"}[a[-1]] + "\n", ""
        if a[:3] == ["-t", "-f", "ACTIVE,SSID,SIGNAL"]:
            if not self.activo:
                return 0, "", ""
            ssid = self.perfiles[self.activo]["ssid"]
            return 0, f"no:Otra:30\nyes:{ssid.replace(':', chr(92) + ':')}:{self.redes[ssid]['senal']}\n", ""
        if a[:3] == ["-t", "-f", "SSID,SIGNAL,SECURITY"]:
            filas = []
            for ssid, r in self.redes.items():
                if r.get("oculta"):
                    continue
                filas.append(f"{ssid}:{r['senal']}:{'' if r['clave'] is None else 'WPA2'}")
            filas.append("RedEjemplo:76:WPA2")                                   # la misma red por otro punto de acceso
            filas.append(":50:WPA2")                                         # una red sin nombre
            return 0, "\n".join(filas) + "\n", ""
        if a[:5] == ["-t", "-f", "NAME,TYPE", "connection", "show"]:
            if self.activo:
                return 0, f"{self.activo}:802-11-wireless\nlo:loopback\n", ""
            return 0, "lo:loopback\n", ""
        if a[:5] == ["-t", "-f", "NAME", "connection", "show"]:
            return 0, "".join(f"{n}\n" for n in self.perfiles) + "lo\n", ""
        if a[:2] == ["connection", "delete"]:
            if a[2] in self.perfiles:
                if self.activo == a[2]:
                    self.activo = None
                del self.perfiles[a[2]]
                return 0, "", ""
            return 10, "", f"Error: unknown connection '{a[2]}'."
        if a[:3] == ["connection", "add", "type"]:
            if self.fallar_al_crear:
                return 1, "", "Error: no se pudo crear"
            datos = dict(zip(a[2::2], a[3::2]))                          # type wifi ifname wlan0 con-name X ...
            self.perfiles[datos["con-name"]] = {
                "ssid": datos["ssid"], "clave": datos.get("wifi-sec.psk"),
                "prio": int(datos["connection.autoconnect-priority"]), "oculta": datos.get("wifi.hidden") == "yes"}
            return 0, "", ""
        if a[:2] == ["connection", "up"]:
            perfil = self.perfiles.get(a[2])
            if perfil is None:
                return 10, "", "Error: unknown connection"
            red = self.redes.get(perfil["ssid"])
            if red is None or (red.get("oculta") and not perfil.get("oculta")):
                return 4, "", f"Error: Connection activation failed: No network with SSID '{perfil['ssid']}' found."
            if red["clave"] != perfil["clave"]:
                return 4, "", "Error: Connection activation failed: Secrets were required, but not provided."
            self.activo = a[2]
            return 0, "", ""
        raise AssertionError(f"comando no previsto: {a}")


def nuevo_gestor(nm: NmcliFalso) -> GestorRed:
    return GestorRed(ejecutor=nm, sonda=nm.hay_internet, dormir=lambda s: None)


class PruebasValidacion(unittest.TestCase):
    def test_nombres_y_contrasenas_validos(self) -> None:
        G.validar_credenciales("Mi red", "12345678")
        G.validar_credenciales("Abierta", "")
        G.validar_credenciales("x" * 32, "y" * 63)
        G.validar_credenciales("Red", "a" * 64 if False else "ab12" * 16)          # 64 hexadecimales

    def test_datos_invalidos(self) -> None:
        for ssid, clave in (("", "12345678"), ("x" * 33, "12345678"), ("ñ" * 17, "12345678"), ("Red", "1234567"),
                            ("Red", "x" * 64), ("Red\n", "12345678"), ("Red", "clave\x00mala"), ("Red", "tab\t1234")):
            with self.subTest(ssid=ssid[:10], clave=clave[:10]):
                with self.assertRaises(ErrorRed):
                    G.validar_credenciales(ssid, clave)

    def test_redactar_oculta_la_contrasena(self) -> None:
        r = G.redactar({"ssid": "Hospital", "contrasena": CLAVE, "oculta": False, "password": "", "psk": None})
        self.assertEqual(r, {"ssid": "Hospital", "contrasena": "***", "oculta": False, "password": "", "psk": None})
        self.assertNotIn(CLAVE, str(r))

    def test_el_perfil_de_una_red_tiene_un_nombre_estable_y_seguro(self) -> None:
        self.assertEqual(G.nombre_de_perfil("Hospital"), G.nombre_de_perfil("Hospital"))
        self.assertNotEqual(G.nombre_de_perfil("Hospital"), G.nombre_de_perfil("hospital"))
        self.assertRegex(G.nombre_de_perfil("Mi:Red \"rara\""), r"^g2-wifi-[0-9a-f]{8}$")

    def test_los_dos_puntos_escapados_de_nmcli(self) -> None:
        self.assertEqual(G._partir(r"Mi\:Red:80:WPA2"), ["Mi:Red", "80", "WPA2"])
        self.assertEqual(G._partir("RedEjemplo:99:"), ["RedEjemplo", "99", ""])

    def test_explicar_fallos(self) -> None:
        self.assertEqual(G.explicar_fallo("Error: Secrets were required, but not provided.")[0], "contrasena")
        self.assertEqual(G.explicar_fallo("No network with SSID 'X' found.")[0], "no_encontrada")
        self.assertEqual(G.explicar_fallo("Timeout expired")[0], "tiempo")
        self.assertEqual(G.explicar_fallo("algo raro")[0], "otro")


class PruebasConsulta(unittest.TestCase):
    def test_escanear_quita_repetidas_y_sin_nombre_y_ordena_por_senal(self) -> None:
        redes = nuevo_gestor(NmcliFalso()).escanear()
        self.assertEqual([r.ssid for r in redes], ["RedEjemplo", "Hospital", "Sin salida", "Abierta"])
        self.assertEqual(redes[0], RedVisible("RedEjemplo", 99, "WPA2"))
        self.assertEqual(redes[-1].seguridad, "")                                  # la abierta

    def test_estado_en_wifi(self) -> None:
        e = nuevo_gestor(NmcliFalso()).estado()
        self.assertEqual((e.tipo, e.ssid, e.ip, e.senal, e.internet), ("wifi", "RedEjemplo", "192.168.10.20", 99, True))
        self.assertEqual((e.zerotier_ip, e.interfaz_wifi), ("10.99.99.10", "wlan0"))

    def test_estado_en_ethernet(self) -> None:
        nm = NmcliFalso()
        nm.activo, nm.ethernet = None, True
        nm.wifi = False
        e = nuevo_gestor(nm).estado()
        self.assertEqual((e.tipo, e.ip, e.internet), ("ethernet", "192.168.10.21", True))
        self.assertIsNone(e.ssid)

    def test_estado_sin_conexion(self) -> None:
        nm = NmcliFalso()
        nm.activo = None
        e = nuevo_gestor(nm).estado()
        self.assertIsNone(e.tipo)
        self.assertEqual(e.zerotier_ip, "10.99.99.10")

    def test_un_nombre_con_dos_puntos_se_lee_bien(self) -> None:
        nm = NmcliFalso()
        nm.redes["Mi:Red"] = {"clave": "12345678", "internet": True, "senal": 88}
        nm.perfiles["x"] = {"ssid": "Mi:Red", "clave": "12345678", "prio": 0}
        nm.activo = "x"
        self.assertEqual(nuevo_gestor(nm).estado().ssid, "Mi:Red")


class PruebasCambioDeRed(unittest.TestCase):
    def setUp(self) -> None:
        self.nm = NmcliFalso()
        self.g = nuevo_gestor(self.nm)

    def comando(self, *inicio: str):
        return [c for c in self.nm.comandos if c[: len(inicio)] == list(inicio)]

    def test_cambia_a_una_red_nueva_con_internet(self) -> None:
        r = self.g.configurar("Hospital", CLAVE)
        self.assertTrue(r.ok and not r.revertida and not r.sin_internet)
        self.assertEqual(r.mensaje, "Conectado a «Hospital»")
        self.assertEqual(self.nm.perfiles[self.nm.activo]["ssid"], "Hospital")
        self.assertEqual(self.nm.perfiles[self.nm.activo]["prio"], 10)             # gana a las anteriores
        self.assertIn("netplan-wlan0-RedEjemplo", self.nm.perfiles)                    # la anterior queda de respaldo

    def test_la_red_anterior_no_se_borra_antes_de_comprobar_la_nueva(self) -> None:
        self.g.configurar("Hospital", CLAVE)
        self.assertEqual(self.comando("connection", "delete", "netplan-wlan0-RedEjemplo"), [])

    def test_contrasena_incorrecta_revierte_a_la_red_anterior(self) -> None:
        r = self.g.configurar("Hospital", "clavemalaaa")
        self.assertFalse(r.ok)
        self.assertTrue(r.revertida)
        self.assertEqual((r.motivo, r.mensaje), ("contrasena", "Contraseña incorrecta"))
        self.assertEqual(self.nm.activo, "netplan-wlan0-RedEjemplo")                   # volvio a la de antes
        self.assertNotIn(G.nombre_de_perfil("Hospital"), self.nm.perfiles)         # y no dejo el perfil malo

    def test_red_que_no_existe_revierte(self) -> None:
        r = self.g.configurar("NoExiste", "12345678")
        self.assertEqual((r.ok, r.revertida, r.motivo), (False, True, "no_encontrada"))
        self.assertEqual(self.nm.activo, "netplan-wlan0-RedEjemplo")

    def test_si_la_red_nueva_no_tiene_internet_y_antes_si_habia_se_revierte(self) -> None:
        r = self.g.configurar("Sin salida", "sinsalida123")
        self.assertEqual((r.ok, r.revertida, r.motivo), (False, True, "sin_internet"))
        self.assertEqual(self.nm.activo, "netplan-wlan0-RedEjemplo")

    def test_primer_uso_sin_internet_previo_acepta_una_red_sin_salida_y_avisa(self) -> None:
        self.nm.activo = None                                                       # equipo nuevo: sin red
        r = self.g.configurar("Sin salida", "sinsalida123")
        self.assertTrue(r.ok and r.sin_internet)
        self.assertIn("sin salida a internet", r.mensaje)
        self.assertEqual(self.nm.perfiles[self.nm.activo]["ssid"], "Sin salida")

    def test_primer_uso_con_contrasena_mala_no_deja_nada_a_medias(self) -> None:
        self.nm.activo = None
        self.nm.perfiles.clear()
        r = self.g.configurar("Hospital", "clavemalaaa")
        self.assertEqual((r.ok, r.revertida, r.motivo), (False, False, "contrasena"))   # no habia nada a donde volver
        self.assertEqual(self.nm.perfiles, {})

    def test_con_cable_la_red_nueva_se_prueba_por_el_wifi_no_por_el_cable(self) -> None:
        self.nm.ethernet = True
        self.nm.activo = None                                                       # solo cable
        r = self.g.configurar("Sin salida", "sinsalida123")                         # el cable SI tiene internet
        self.assertEqual((r.ok, r.revertida, r.motivo), (False, False, "sin_internet"))   # y el wifi no: se rechaza
        self.assertEqual(self.nm.perfiles, {"netplan-wlan0-RedEjemplo": self.nm.perfiles["netplan-wlan0-RedEjemplo"]})

    def test_red_abierta_no_lleva_contrasena(self) -> None:
        r = self.g.configurar("Abierta", "")
        self.assertTrue(r.ok)
        añadir = self.comando("connection", "add")[0]
        self.assertNotIn("wifi-sec.psk", añadir)
        self.assertNotIn("wifi-sec.key-mgmt", añadir)

    def test_red_oculta(self) -> None:
        self.assertFalse(self.g.configurar("Oculta", "ocultaoculta").ok)           # sin marcarla como oculta no se encuentra
        r = self.g.configurar("Oculta", "ocultaoculta", oculta=True)
        self.assertTrue(r.ok)
        self.assertIn("wifi.hidden", self.comando("connection", "add")[-1])

    def test_volver_a_configurar_la_misma_red_reemplaza_su_perfil(self) -> None:
        self.g.configurar("Hospital", CLAVE)
        self.g.configurar("Hospital", CLAVE)
        self.assertEqual(sum(1 for p in self.nm.perfiles if p == G.nombre_de_perfil("Hospital")), 1)

    def test_se_conservan_a_lo_sumo_4_perfiles_propios(self) -> None:
        for n in range(6):
            self.nm.redes[f"Red{n}"] = {"clave": "12345678", "internet": True, "senal": 50}
            self.assertTrue(self.g.configurar(f"Red{n}", "12345678").ok)
        propios = [p for p in self.nm.perfiles if p.startswith(G.PREFIJO_PERFIL)]
        self.assertEqual(len(propios), 4)
        self.assertIn(G.nombre_de_perfil("Red5"), propios)                          # la ultima si se conserva
        self.assertIn("netplan-wlan0-RedEjemplo", self.nm.perfiles)                     # lo que no es de G2 no se toca

    def test_datos_invalidos_no_tocan_nada(self) -> None:
        for ssid, clave in (("", "12345678"), ("Red", "corta")):
            r = self.g.configurar(ssid, clave)
            self.assertEqual((r.ok, r.motivo), (False, "datos"))
        self.assertEqual(self.nm.comandos, [])

    def test_sin_dispositivo_wifi(self) -> None:
        self.nm.wifi = False
        r = self.g.configurar("Hospital", CLAVE)
        self.assertEqual((r.ok, r.motivo), (False, "sin_wifi"))

    def test_si_no_se_puede_crear_el_perfil_no_se_toca_la_red_actual(self) -> None:
        self.nm.fallar_al_crear = True
        r = self.g.configurar("Hospital", CLAVE)
        self.assertEqual((r.ok, r.motivo), (False, "perfil"))
        self.assertEqual(self.nm.activo, "netplan-wlan0-RedEjemplo")

    def test_la_contrasena_nunca_sale_en_el_registro_ni_en_los_mensajes(self) -> None:
        with self.assertLogs("g2.red", level="DEBUG") as registro:
            ok = self.g.configurar("Hospital", CLAVE)
            malo = self.g.configurar("Hospital", "clavemalaaa")
            self.nm.fallar_al_crear = True
            self.g.configurar("Hospital", CLAVE)
        texto = "\n".join(registro.output) + ok.mensaje + malo.mensaje
        self.assertNotIn(CLAVE, texto)
        self.assertNotIn("clavemalaaa", texto)


if __name__ == "__main__":
    unittest.main()
