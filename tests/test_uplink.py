"""Pruebas de g2-uplink (D-046): armado de mensajes, credencial, cliente HTTPS, anotacion en la cola por g2-core, ciclo del
servicio con un cliente falso, y de punta a punta contra la plataforma simulada por HTTP real."""

from __future__ import annotations

import contextlib
import gzip
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from g2 import ipc
from g2.almacenamiento import base
from g2.almacenamiento.almacen import Almacen, ErrorAlmacen
from g2.nucleo.fuentes import FuenteSimulada
from g2.nucleo.nucleo import Nucleo
from g2.tiempo import RelojPrueba
from g2.uplink import cliente as cl
from g2.uplink import credencial, mensajes, servicio
from g2.uplink.cliente import (ClientePlataforma, CredencialRechazada, ErrorProtocolo, LoteDemasiadoGrande, SinEnlace)
from g2.uplink.simulada import PlataformaSimulada

SECRETO = "secreto-de-prueba-0123456789abcdef"
EQUIPO = "ANZD-PRUEBA"
INICIO_MS = 1_793_000_000_000


class BaseConBase(unittest.TestCase):
    """Una base real con dos sensores; ``self.a`` es la escritora (g2-core) y ``self.lectora()`` la de solo lectura."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.ruta = self.dir / "g2.db"
        self.reloj = RelojPrueba(ahora_ms=INICIO_MS)
        self.a = Almacen.abrir(self.ruta, self.reloj)
        self.a.registrar_arranque(version_sw="0.1.0-test", so_boot_id="so-1")
        self.s1 = self.a.registrar_sensor(canal="ads1263:0-1", nombre="Sensor 1", modelo="P", mv_por_pct=10.0)
        self.s2 = self.a.registrar_sensor(canal="ads1263:2-3", nombre="Sensor 2", modelo="P", mv_por_pct=10.0)
        self.lector = Almacen(base.abrir_lectura(self.ruta))

    def tearDown(self) -> None:
        self.lector.cerrar()
        self.a.cerrar()
        self._tmp.cleanup()

    def lectura(self, sensor=None, o2=20.9) -> int:
        self.reloj.avanzar(1000)
        return self.a.insertar_lectura(sensor_id=sensor or self.s1, periodo_ms=15_000, n_muestras=30, o2_prom=o2,
                                       o2_min=o2, o2_max=o2, mv_prom=o2 * 10)

    def cola(self, estado=None) -> list:
        consulta = "SELECT * FROM cola_envio" + (" WHERE estado = ?" if estado else "") + " ORDER BY id"
        return self.a.db.execute(consulta, (estado,) if estado else ()).fetchall()

    def ahora_ms(self) -> int:
        return self.reloj.ahora_ms()


# ------------------------------------------------------------------------------------------------------------ mensajes
class PruebasMensajes(BaseConBase):
    def test_con_atraso_salen_primero_las_alarmas_y_los_eventos_y_al_final_las_lecturas(self) -> None:
        for _ in range(5):
            self.lectura()
        self.a.abrir_alarma("ALM_O2_ALTO", sensor_id=self.s1, umbral=92.0, valor=93.0)
        self.a.registrar_evento("SYS_AUTODIAGNOSTICO", "prueba", mensaje="x")
        orden = [e["tabla"] for e in mensajes.pendientes(self.lector.db, self.ahora_ms(), 1000)]
        indices = [mensajes.PRIORIDAD.index(t) for t in orden]
        self.assertEqual(indices, sorted(indices))
        self.assertEqual(orden[0], "alarma")
        self.assertEqual(orden[-1], "lectura")

    def test_el_limite_y_lo_ya_enviado_se_respetan(self) -> None:
        for _ in range(8):
            self.lectura()
        todas = mensajes.pendientes(self.lector.db, self.ahora_ms(), 1000)
        primeras = mensajes.pendientes(self.lector.db, self.ahora_ms(), 3)
        self.assertEqual([e["id"] for e in primeras], [e["id"] for e in todas[:3]])
        sin_las_primeras = mensajes.pendientes(self.lector.db, self.ahora_ms(), 3, excluir={e["id"] for e in primeras})
        self.assertEqual([e["id"] for e in sin_las_primeras], [e["id"] for e in todas[3:6]])

    def test_un_reintento_futuro_espera_pero_uno_de_un_reloj_desajustado_no(self) -> None:
        self.lectura()
        entrada = mensajes.pendientes(self.lector.db, self.ahora_ms(), 1000)[-1]
        self.a.cola_resultado(fallidos={entrada["id"]: "ocupada"})
        ids = lambda: {e["id"] for e in mensajes.pendientes(self.lector.db, self.ahora_ms(), 1000)}
        self.assertNotIn(entrada["id"], ids())                                  # espera 30 s
        self.reloj.avanzar(31_000)
        self.assertIn(entrada["id"], ids())
        self.a.db.execute("UPDATE cola_envio SET proximo_intento_ms = ? WHERE id = ?",
                          (self.ahora_ms() + 10 * 3_600_000, entrada["id"]))    # el reloj retrocedio horas
        self.assertIn(entrada["id"], ids())

    def test_las_revisiones_de_un_registro_viajan_una_sola_vez_con_su_contenido_de_hoy(self) -> None:
        alarma = self.a.abrir_alarma("ALM_O2_ALTO", sensor_id=self.s1, umbral=92.0, valor=93.0)
        self.a.cerrar_alarma(alarma)                                           # rev 2 de la misma alarma
        entradas = [e for e in mensajes.pendientes(self.lector.db, self.ahora_ms(), 1000) if e["tabla"] == "alarma"]
        self.assertGreaterEqual(len(entradas), 2)
        lote = mensajes.armar(self.lector.db, entradas)
        registros = [r for r in lote.registros if r["tabla"] == "alarma"]
        self.assertEqual(len(registros), 1)
        self.assertEqual(registros[0]["rev"], max(e["rev"] for e in entradas))
        self.assertEqual(registros[0]["datos"]["estado"], "cerrada")           # lo de hoy, no lo de la primera revision
        self.assertEqual(sorted(lote.entradas[("alarma", alarma)]), sorted(e["id"] for e in entradas))

    def test_el_registro_lleva_su_fila_completa(self) -> None:
        i = self.lectura(o2=87.5)
        lote = mensajes.armar(self.lector.db, [e for e in mensajes.pendientes(self.lector.db, self.ahora_ms(), 1000)
                                               if e["tabla"] == "lectura"])
        registro = lote.registros[0]
        self.assertEqual((registro["tabla"], registro["id"], registro["rev"]), ("lectura", i, 1))
        self.assertEqual((registro["datos"]["sensor_id"], registro["datos"]["o2_prom"]), (self.s1, 87.5))
        json.dumps(registro)                                                    # todo serializable

    def fantasma(self) -> int:
        """Una entrada de la cola que apunta a una lectura que no existe; devuelve su id de cola."""
        self.a.db.execute("INSERT INTO cola_envio (tabla, registro_id, rev, creado_ms) VALUES ('lectura', 999999, 1, ?)",
                          (self.ahora_ms(),))
        return self.a.db.execute("SELECT id FROM cola_envio WHERE registro_id = 999999").fetchone()[0]

    def test_un_registro_que_ya_no_existe_se_avisa_en_vez_de_reintentarse_siempre(self) -> None:
        i = self.fantasma()
        entrada = [e for e in mensajes.pendientes(self.lector.db, self.ahora_ms(), 1000) if e["id"] == i]
        lote = mensajes.armar(self.lector.db, entrada)
        self.assertEqual((lote.registros, lote.faltantes), ([], {i: "el registro ya no existe"}))


# ------------------------------------------------------------------------------------------------------------ credencial
class PruebasCredencial(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.carpeta = Path(self._tmp.name) / "secretos"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_se_guarda_y_se_lee(self) -> None:
        ruta = credencial.guardar(SECRETO, self.carpeta)
        self.assertEqual(ruta.name, credencial.NOMBRE)
        self.assertEqual(credencial.leer(self.carpeta), SECRETO)
        self.assertTrue(credencial.existe(self.carpeta))

    @unittest.skipUnless(os.name == "posix", "los permisos de Unix no existen en Windows")
    def test_el_archivo_es_solo_del_usuario_y_se_niega_a_leer_uno_abierto(self) -> None:
        ruta = credencial.guardar(SECRETO, self.carpeta)
        self.assertEqual(ruta.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.carpeta.stat().st_mode & 0o777, 0o700)
        ruta.chmod(0o644)
        with self.assertRaisesRegex(credencial.ErrorCredencial, "legible por otros usuarios"):
            credencial.leer(self.carpeta)

    def test_sin_archivo_dice_como_guardarlo(self) -> None:
        self.assertFalse(credencial.existe(self.carpeta))
        with self.assertRaisesRegex(credencial.ErrorCredencial, "plataforma-credencial"):
            credencial.leer(self.carpeta)

    def test_un_secreto_corto_o_con_espacios_no_se_acepta(self) -> None:
        for malo in ("corto", "x" * 300, "con espacios " + "a" * 30, "acentuación" + "a" * 30, ""):
            with self.assertRaises(credencial.ErrorCredencial, msg=malo):
                credencial.validar(malo)
        self.assertFalse(self.carpeta.exists())

    def test_guardar_otra_vez_sustituye_el_secreto(self) -> None:
        credencial.guardar(SECRETO, self.carpeta)
        credencial.guardar(SECRETO[::-1], self.carpeta)
        self.assertEqual(credencial.leer(self.carpeta), SECRETO[::-1])
        self.assertEqual(len(list(self.carpeta.iterdir())), 1)                  # sin temporales


# ------------------------------------------------------------------------------------------------------------ cliente
class RespuestaFalsa:
    def __init__(self, codigo=200, cuerpo=None, cabeceras=None, texto_invalido=False) -> None:
        self.status_code, self._cuerpo, self.headers = codigo, cuerpo, cabeceras or {}
        self._invalido = texto_invalido

    def json(self):
        if self._invalido:
            raise ValueError("no es JSON")
        return self._cuerpo


class SesionFalsa:
    def __init__(self, respuesta=None, error=None) -> None:
        self.respuesta, self.error, self.llamadas = respuesta or RespuestaFalsa(), error, []

    def post(self, url, **argumentos):
        self.llamadas.append((url, argumentos))
        if self.error:
            raise self.error
        return self.respuesta


def cliente_con(sesion, url="https://plataforma.example") -> ClientePlataforma:
    return ClientePlataforma(url, EQUIPO, SECRETO, version_sw="0.1.0-test", sesion=sesion)


class PruebasCliente(unittest.TestCase):
    def test_solo_https_y_http_solo_hacia_el_propio_equipo(self) -> None:
        self.assertEqual(cl.validar_url("https://sp-peek.com/"), "https://sp-peek.com")
        self.assertEqual(cl.validar_url("https://host.example:8443/api/"), "https://host.example:8443/api")
        self.assertEqual(cl.validar_url("http://127.0.0.1:8099"), "http://127.0.0.1:8099")
        self.assertEqual(cl.validar_url("http://localhost:8099"), "http://localhost:8099")
        for mala in ("http://sp-peek.com", "ftp://sp-peek.com", "https://", "sp-peek.com", "https://usuario:clave@sp-peek.com",
                     "https://sp-peek.com?a=1", "https://sp-peek.com#x", ""):
            with self.assertRaises(ValueError, msg=mala):
                cl.validar_url(mala)

    def test_el_secreto_va_en_la_cabecera_y_en_ningun_otro_lado(self) -> None:
        sesion = SesionFalsa(RespuestaFalsa(200, {"ok": True}))
        c = cliente_con(sesion)
        c.enviar_vivo({"ts_ms": 1})
        url, argumentos = sesion.llamadas[0]
        self.assertEqual(url, "https://plataforma.example" + cl.RUTA_VIVO)
        self.assertEqual(argumentos["headers"]["Authorization"], f"Bearer {SECRETO}")
        self.assertEqual(argumentos["headers"]["X-G2-Equipo"], EQUIPO)
        self.assertNotIn(SECRETO, argumentos["data"].decode("utf-8", "replace"))
        self.assertNotIn(SECRETO, repr(c))
        self.assertNotIn(SECRETO, url)

    def test_nunca_se_sigue_una_redireccion_y_siempre_se_verifica_el_certificado(self) -> None:
        sesion = SesionFalsa(RespuestaFalsa(200, {"ok": True}))
        cliente_con(sesion).enviar_vivo({})
        argumentos = sesion.llamadas[0][1]
        self.assertIs(argumentos["allow_redirects"], False)
        self.assertIs(argumentos["verify"], True)
        self.assertEqual(argumentos["timeout"], (5.0, 20.0))

    def test_un_cuerpo_grande_viaja_comprimido_y_uno_chico_no(self) -> None:
        sesion = SesionFalsa(RespuestaFalsa(200, {"ok": True}))
        c = cliente_con(sesion)
        c.enviar_vivo({"a": 1})
        c.enviar_vivo({"relleno": "x" * 5000})
        chico, grande = sesion.llamadas[0][1], sesion.llamadas[1][1]
        self.assertNotIn("Content-Encoding", chico["headers"])
        self.assertEqual(grande["headers"]["Content-Encoding"], "gzip")
        self.assertEqual(json.loads(gzip.decompress(grande["data"]))["relleno"], "x" * 5000)
        self.assertLess(len(grande["data"]), 500)

    def test_cada_codigo_se_traduce_a_lo_que_el_servicio_debe_hacer(self) -> None:
        casos = [(401, CredencialRechazada), (403, CredencialRechazada), (413, LoteDemasiadoGrande), (408, SinEnlace),
                 (429, SinEnlace), (500, SinEnlace), (503, SinEnlace), (302, ErrorProtocolo), (400, ErrorProtocolo),
                 (404, ErrorProtocolo)]
        for codigo, error in casos:
            with self.assertRaises(error, msg=codigo):
                cliente_con(SesionFalsa(RespuestaFalsa(codigo))).enviar_vivo({})

    def test_sin_red_es_sin_enlace_y_el_mensaje_no_trae_la_direccion_ni_el_secreto(self) -> None:
        with self.assertRaises(SinEnlace) as contexto:
            cliente_con(SesionFalsa(error=ConnectionError(f"fallo {SECRETO}"))).enviar_vivo({})
        self.assertNotIn(SECRETO, str(contexto.exception))
        self.assertIn("ConnectionError", str(contexto.exception))

    def test_retry_after_se_respeta_con_tope(self) -> None:
        for dicho, esperado in (("12", 12.0), ("999999", float(cl.MAX_ESPERA_S)), ("manana", None)):
            with self.assertRaises(SinEnlace) as contexto:
                cliente_con(SesionFalsa(RespuestaFalsa(429, cabeceras={"Retry-After": dicho}))).enviar_vivo({})
            self.assertEqual(contexto.exception.espera_s, esperado, dicho)

    def test_una_respuesta_que_no_es_json_no_es_de_fiar(self) -> None:
        with self.assertRaises(ErrorProtocolo):
            cliente_con(SesionFalsa(RespuestaFalsa(200, texto_invalido=True))).enviar_vivo({})

    def test_el_resultado_de_un_lote_ajeno_se_descarta(self) -> None:
        sesion = SesionFalsa(RespuestaFalsa(200, {"lote_id": "otro", "resultados": []}))
        with self.assertRaises(ErrorProtocolo):
            cliente_con(sesion).enviar_lote([{"tabla": "lectura", "id": 1, "rev": 1, "datos": {}}])

    def test_los_resultados_mal_formados_se_ignoran_y_lo_que_no_se_contesto_no_aparece(self) -> None:
        c = cliente_con(SesionFalsa())

        def responder(url, **argumentos):
            lote = json.loads(argumentos["data"])["lote_id"]
            return RespuestaFalsa(200, {"lote_id": lote, "resultados": [
                {"tabla": "lectura", "id": 1, "estado": "ok", "rev": 1},
                {"tabla": "lectura", "id": 2, "estado": "rechazado", "motivo": "valor fuera de rango"},
                {"tabla": "lectura", "id": 3, "estado": "tal vez"},                       # estado desconocido
                {"tabla": "lectura", "id": "4", "estado": "ok"},                          # id que no es entero
                "basura", {"id": 5, "estado": "ok"}]})                                    # sin tabla

        c._sesion.post = responder
        registros = [{"tabla": "lectura", "id": i, "rev": 1, "datos": {}} for i in range(1, 7)]
        self.assertEqual(c.enviar_lote(registros), {("lectura", 1): ("ok", None, 1),
                                                    ("lectura", 2): ("rechazado", "valor fuera de rango", None)})


# ------------------------------------------------------------------------------------------------------------ la cola en la base
class PruebasColaResultado(BaseConBase):
    def test_confirmar_deja_la_entrada_confirmada_y_repetirlo_no_cambia_nada(self) -> None:
        self.lectura()
        ids = [e["id"] for e in self.cola("pendiente")]
        self.assertEqual(self.a.cola_resultado(confirmados=ids)["confirmados"], len(ids))
        self.assertEqual(self.cola("pendiente"), [])
        fila = self.cola("confirmado")[0]
        self.assertEqual((fila["confirmado_ms"], fila["enviado_ms"]), (self.ahora_ms(), self.ahora_ms()))
        self.assertEqual(self.a.cola_resultado(confirmados=ids)["confirmados"], 0)

    def test_lo_confirmado_se_puede_depurar_y_lo_pendiente_no(self) -> None:
        self.lectura()
        self.lectura()
        entradas = [e for e in self.cola("pendiente") if e["tabla"] == "lectura"]
        self.a.cola_resultado(confirmados=[entradas[0]["id"]])
        depurables = {(f["tabla"], f["registro_id"]) for f in self.a.db.execute("SELECT * FROM v_depurable")}
        self.assertIn(("lectura", entradas[0]["registro_id"]), depurables)
        self.assertNotIn(("lectura", entradas[1]["registro_id"]), depurables)

    def test_rechazar_deja_el_motivo_y_un_solo_evento_por_aviso(self) -> None:
        for _ in range(3):
            self.lectura()
        lecturas = [e["id"] for e in self.cola("pendiente") if e["tabla"] == "lectura"]
        hecho = self.a.cola_resultado(rechazados={i: "valor fuera de rango" for i in lecturas})
        self.assertEqual(hecho["rechazados"], 3)
        self.assertEqual({e["ultimo_error"] for e in self.cola("rechazado")}, {"valor fuera de rango"})
        eventos = self.a.db.execute("SELECT * FROM evento WHERE codigo = 'NET_ENVIO_RECHAZADO'").fetchall()
        self.assertEqual(len(eventos), 1)
        self.assertEqual(json.loads(eventos[0]["datos_json"])["cantidad"], 3)
        self.assertEqual(self.a.cola_resultado(rechazados={lecturas[0]: "otra vez"})["rechazados"], 0)   # ya no cambia

    def test_descartar_no_borra_nada_y_deja_el_motivo_y_un_evento(self) -> None:
        for _ in range(3):
            self.lectura()
        antes = self.a.db.execute("SELECT COUNT(*) FROM lectura").fetchone()[0]
        pendientes = len(self.cola("pendiente"))
        hecho = self.a.cola_descartar(motivo="registros de prueba", actor="usuario")
        self.assertEqual(sum(hecho.values()), pendientes)
        self.assertEqual(hecho["lectura"], 3)
        self.assertEqual(len(self.cola("rechazado")), pendientes)
        self.assertEqual({e["ultimo_error"] for e in self.cola("rechazado")}, {"Descartado: registros de prueba"})
        self.assertEqual(self.a.db.execute("SELECT COUNT(*) FROM lectura").fetchone()[0], antes)      # siguen en el equipo
        self.assertEqual(self.a.db.execute("SELECT COUNT(*) FROM v_depurable").fetchone()[0], 0)      # y no se depuran
        evento = self.a.db.execute("SELECT * FROM evento WHERE codigo = 'NET_ENVIO_RECHAZADO'").fetchone()
        self.assertEqual(evento["origen"], "g2ctl:usuario")
        self.assertEqual(json.loads(evento["datos_json"])["cantidad"], pendientes)

    def test_descartar_solo_toca_lo_anterior_y_no_lo_confirmado(self) -> None:
        self.lectura()
        confirmada = [e["id"] for e in self.cola("pendiente") if e["tabla"] == "lectura"][0]
        self.a.cola_resultado(confirmados=[confirmada])
        hasta = self.a.db.execute("SELECT MAX(id) FROM cola_envio").fetchone()[0]
        self.lectura()                                                    # llega despues del corte
        self.a.cola_descartar(motivo="prueba", actor="u", hasta_id=hasta)
        self.assertEqual([e["id"] for e in self.cola("confirmado")], [confirmada])
        despues = [e for e in self.cola("pendiente") if e["id"] > hasta and e["tabla"] == "lectura"]
        self.assertEqual(len(despues), 1)

    def test_descartar_sin_nada_pendiente_no_deja_evento_y_pide_motivo(self) -> None:
        self.a.cola_resultado(confirmados=[e["id"] for e in self.cola("pendiente")])
        self.assertEqual(self.a.cola_descartar(motivo="x", actor="u"), {})
        self.assertEqual(self.a.db.execute("SELECT COUNT(*) FROM evento WHERE codigo = 'NET_ENVIO_RECHAZADO'").fetchone()[0], 0)
        with self.assertRaises(ErrorAlmacen):
            self.a.cola_descartar(motivo="  ", actor="u")

    def test_un_fallo_suma_un_intento_y_espera_cada_vez_mas_hasta_un_tope(self) -> None:
        self.lectura()
        i = [e["id"] for e in self.cola("pendiente") if e["tabla"] == "lectura"][0]
        esperas = []
        for _ in range(8):
            self.a.cola_resultado(fallidos={i: "ocupada"})
            fila = self.a.db.execute("SELECT * FROM cola_envio WHERE id = ?", (i,)).fetchone()
            esperas.append((fila["proximo_intento_ms"] - self.ahora_ms()) // 1000)
        self.assertEqual(esperas, [30, 60, 120, 240, 480, 600, 600, 600])
        self.assertEqual(fila["intentos"], 8)
        self.assertEqual(fila["estado"], "pendiente")

    def test_lo_confirmado_no_vuelve_atras_por_un_aviso_tardio(self) -> None:
        self.lectura()
        i = [e["id"] for e in self.cola("pendiente") if e["tabla"] == "lectura"][0]
        self.a.cola_resultado(confirmados=[i])
        self.a.cola_resultado(rechazados={i: "tarde"}, fallidos={i: "tarde"})
        self.assertEqual(self.a.db.execute("SELECT estado FROM cola_envio WHERE id = ?", (i,)).fetchone()[0], "confirmado")


class PruebasNucleoConLaCola(BaseConBase):
    def setUp(self) -> None:
        super().setUp()
        self.n = Nucleo(self.a, FuenteSimulada({"ads1263:0-1": 0.209}), mono=lambda: 0.0)
        self.n.iniciar()

    def orden(self, uuid="u1", **datos) -> None:
        self.n.procesar_orden({"uuid": uuid, "tipo": "cola_resultado", "origen": "local", **datos})

    def eventos(self, codigo) -> list:
        return self.a.db.execute("SELECT * FROM evento WHERE codigo = ?", (codigo,)).fetchall()

    def test_la_orden_anota_la_cola_y_no_deja_un_comando_que_a_su_vez_haya_que_enviar(self) -> None:
        self.lectura()
        ids = [e["id"] for e in self.cola("pendiente") if e["tabla"] == "lectura"]
        antes = self.a.db.execute("SELECT COUNT(*) FROM comando").fetchone()[0]
        pendientes_antes = len(self.cola("pendiente"))
        self.orden(confirmados=ids, enlace="ok")
        self.assertEqual(self.a.db.execute("SELECT COUNT(*) FROM comando").fetchone()[0], antes)
        self.assertEqual(len(self.cola("pendiente")), pendientes_antes - len(ids))   # y no aparecio nada nuevo que enviar

    def test_los_ids_que_llegan_por_json_se_aceptan_y_la_basura_se_ignora(self) -> None:
        self.lectura()
        i = [e["id"] for e in self.cola("pendiente") if e["tabla"] == "lectura"][0]
        # JSON vuelve las claves de los diccionarios texto; los ids sueltos que no son enteros se descartan
        self.orden(confirmados=[True, "x", None, 1.5], rechazados={str(i): "malo", "abc": "x"}, fallidos="no es un dict")
        self.assertEqual(self.a.db.execute("SELECT estado FROM cola_envio WHERE id = ?", (i,)).fetchone()[0], "rechazado")
        self.orden(uuid="u2", confirmados="no es una lista", rechazados=[1, 2], fallidos=None)               # no revienta

    def test_el_enlace_deja_un_evento_solo_cuando_cambia(self) -> None:
        self.orden(enlace="ok")                                                  # al arrancar bien no hay nada que contar
        self.assertEqual(self.eventos("PLAT_ENLACE_PERDIDO") + self.eventos("PLAT_ENLACE_RESTABLECIDO"), [])
        self.orden("u2", enlace="sin_enlace", detalle="sin conexion con la plataforma (ConnectionError)")
        self.orden("u3", enlace="sin_enlace")                                    # sigue igual: no se repite
        self.assertEqual(len(self.eventos("PLAT_ENLACE_PERDIDO")), 1)
        self.assertIn("ConnectionError", self.eventos("PLAT_ENLACE_PERDIDO")[0]["mensaje"])
        self.orden("u4", enlace="ok")
        self.assertEqual(len(self.eventos("PLAT_ENLACE_RESTABLECIDO")), 1)
        self.orden("u5", enlace="credencial", detalle="HTTP 401")
        self.assertEqual(len(self.eventos("PLAT_CREDENCIAL_RECHAZADA")), 1)
        self.orden("u6", enlace="ok")                                            # restablecido otra vez: se agrupa con el anterior
        self.assertEqual(sum(e["repeticiones"] for e in self.eventos("PLAT_ENLACE_RESTABLECIDO")), 2)

    def test_un_estado_de_enlace_desconocido_se_ignora(self) -> None:
        self.orden(enlace="quien-sabe")
        self.orden("u2", enlace=None)
        self.assertEqual(self.eventos("PLAT_ENLACE_PERDIDO"), [])

    def test_arrancar_sin_enlace_si_se_cuenta(self) -> None:
        self.orden(enlace="sin_enlace")
        self.assertEqual(len(self.eventos("PLAT_ENLACE_PERDIDO")), 1)


# ------------------------------------------------------------------------------------------------------------ el servicio
ESTADO_NUCLEO = {"sensores": [{"id": 1, "nombre": "Sensor 1", "o2": 87.56953, "texto_o2": "87.6", "estado": "NORMAL",
                               "acusada": False},
                              {"id": 2, "nombre": "Sensor 2", "o2": None, "texto_o2": "--", "estado": "SIN SEÑAL",
                               "acusada": False}],
                 "aviso": "Sin alarmas", "rele_bajo": False, "rele_alto": True, "alertas_salud": ["ALM_RPI_TEMP_ALTA"],
                 "salud": {"cpu_temp_c": 48.3, "mem_pct": 34.9, "disco_pct": 39.8, "throttled": "0x0", "red_ok": True,
                           "wifi_rssi_dbm": -41, "uptime_s": 9337.2, "db_bytes": 4780032, "disco_libre_gb": 7.79},
                 "red": {"red": {"tipo": "wifi", "ssid": "MiRed", "ip": "192.168.1.34", "senal": 79, "internet": True,
                                 "zerotier_ip": "10.0.0.1"}, "redes": [{"ssid": "Vecina"}]}}


class NucleoFalso:
    def __init__(self, estado=ESTADO_NUCLEO, edad_s=0.0) -> None:
        self.estado, self.edad_s, self.ordenes = estado, edad_s, []

    def leer_estado(self):
        return (self.estado, self.edad_s) if self.estado is not None else (None, float("inf"))

    def enviar_orden(self, tipo, **datos) -> str:
        self.ordenes.append((tipo, datos))
        return "uuid"


class ClienteFalso:
    def __init__(self) -> None:
        self.lotes, self.vivos, self.fallos_vivo, self.fallos_lote = [], [], [], []
        self.llamadas_lote = self.llamadas_vivo = 0
        self.respuesta = None

    def enviar_lote(self, registros):
        self.llamadas_lote += 1
        if self.fallos_lote:
            raise self.fallos_lote.pop(0)
        self.lotes.append(registros)
        if self.respuesta:
            return self.respuesta(registros)
        return {(r["tabla"], r["id"]): ("ok", None, r["rev"]) for r in registros}

    def enviar_vivo(self, foto) -> None:
        self.llamadas_vivo += 1
        if self.fallos_vivo:
            raise self.fallos_vivo.pop(0)
        self.vivos.append(foto)


class PruebasServicio(BaseConBase):
    def setUp(self) -> None:
        super().setUp()
        self.nucleo = NucleoFalso()
        self.cliente = ClienteFalso()
        self.secreto: str | Exception = SECRETO
        self.carpeta = self.dir / "run"
        self.carpeta.mkdir()
        self.fabricados: list[tuple] = []
        self.s = self.servicio()

    def tearDown(self) -> None:
        self.s.cerrar()                                                          # en Windows no se borra una base abierta
        super().tearDown()

    def servicio(self, **extra) -> servicio.ServicioUplink:
        def fabrica(url, equipo_id, secreto, **argumentos):
            self.fabricados.append((url, equipo_id, secreto))
            return self.cliente

        def secreto():
            if isinstance(self.secreto, Exception):
                raise self.secreto
            return self.secreto

        return servicio.ServicioUplink(lambda: Almacen(base.abrir_lectura(self.ruta)), self.nucleo, self.carpeta,
                                       leer_secreto=secreto, fabrica=extra.pop("fabrica", fabrica),
                                       reloj=lambda: self.reloj.ahora_ms() / 1000, mono=lambda: self.reloj.mono_ms() / 1000,
                                       version_sw="0.1.0-test", **extra)

    def activar(self, **ajustes) -> None:
        for clave, valor in {"plataforma.activa": 1, "equipo.id": EQUIPO, **ajustes}.items():
            self.a.config_fijar(clave, valor, origen="local", actor="prueba")

    def paso(self, avanzar_s: float = 0.0) -> None:
        self.reloj.avanzar(int(avanzar_s * 1000))
        self.s.paso()

    def pendientes_ahora(self) -> int:
        return len(mensajes.pendientes(self.lector.db, self.ahora_ms(), 100_000))

    def publicado(self) -> dict:
        return json.loads((self.carpeta / servicio.NOMBRE_ESTADO).read_text(encoding="utf-8"))

    # ---- lo que falta para enviar -------------------------------------------------------------------------------------
    def test_por_omision_esta_desactivado_y_no_envia_nada(self) -> None:
        self.lectura()
        self.paso()
        self.assertEqual(self.s.estado(), "desactivada")
        self.assertEqual((self.cliente.llamadas_lote, self.cliente.llamadas_vivo, self.nucleo.ordenes), (0, 0, []))
        self.assertEqual(self.fabricados, [])

    def test_sin_equipo_id_no_envia_y_dice_que_falta(self) -> None:
        self.activar(**{"equipo.id": ""})
        self.paso()
        self.assertEqual(self.s.estado(), "sin_equipo_id")
        self.assertIn("equipo.id", self.publicado()["detalle"])
        self.assertEqual(self.cliente.llamadas_vivo, 0)

    def test_sin_credencial_no_envia_y_dice_como_guardarla(self) -> None:
        self.activar()
        self.secreto = credencial.ErrorCredencial("No hay secreto guardado (use: python3 -m g2.ctl plataforma-credencial)")
        self.paso()
        self.assertEqual(self.s.estado(), "sin_credencial")
        self.assertIn("plataforma-credencial", self.publicado()["detalle"])
        self.assertEqual(self.cliente.llamadas_vivo, 0)

    def test_una_direccion_insegura_no_se_usa(self) -> None:
        self.activar(**{"plataforma.url": "http://sp-peek.com"})
        self.s = self.servicio(fabrica=ClientePlataforma)
        self.paso()
        self.assertEqual(self.s.estado(), "url_invalida")
        self.assertIn("https", self.publicado()["detalle"])

    def test_al_corregir_la_configuracion_empieza_sin_esperar(self) -> None:
        self.paso()                                                              # desactivada
        self.activar()
        self.paso(avanzar_s=servicio.PERIODO_CONFIG_S + 1)                       # vuelve a leer la configuracion
        self.assertEqual(self.s.estado(), "ok")
        self.assertEqual(self.cliente.llamadas_vivo, 1)

    # ---- el envio -------------------------------------------------------------------------------------------------------
    def test_un_envio_completo_manda_los_registros_y_le_pide_al_nucleo_que_los_anote(self) -> None:
        self.lectura()
        self.lectura(self.s2)
        self.activar()
        esperados = self.pendientes_ahora()
        self.paso()
        self.assertEqual(self.s.estado(), "ok")
        enviados = [r for lote in self.cliente.lotes for r in lote]
        self.assertEqual(len(enviados), esperados)                               # cada registro una vez, todos
        tipo, datos = self.nucleo.ordenes[-1]
        self.assertEqual((tipo, datos["origen"], datos["enlace"]), ("cola_resultado", "local", "ok"))
        self.assertEqual(len(datos["confirmados"]), esperados)
        self.assertEqual((datos["rechazados"], datos["fallidos"]), ({}, {}))
        self.assertEqual(self.s.confirmados, esperados)

    def test_el_servicio_no_escribe_en_la_base(self) -> None:
        self.lectura()
        self.activar()
        antes = [tuple(f) for f in self.a.db.execute("SELECT id, estado, intentos FROM cola_envio")]
        self.paso()
        self.assertEqual([tuple(f) for f in self.a.db.execute("SELECT id, estado, intentos FROM cola_envio")], antes)

    def test_con_atraso_envia_por_lotes_sin_repetir_lo_que_el_nucleo_aun_no_anoto(self) -> None:
        for _ in range(25):
            self.lectura()
        self.activar(**{"plataforma.lote_max": 10})
        total = self.pendientes_ahora()
        enviados: list[int] = []
        for _ in range(total // 10 + 2):
            self.paso(avanzar_s=1.0)                                             # el nucleo NO anota nada (orden en espera)
            enviados = [(r["tabla"], r["id"]) for lote in self.cliente.lotes for r in lote]
        self.assertEqual(len(enviados), len(set(enviados)))                      # ninguno dos veces
        self.assertGreaterEqual(len(enviados), 25)
        self.assertTrue(all(len(lote) <= 10 for lote in self.cliente.lotes))

    def test_al_estar_al_dia_espera_el_intervalo_para_volver_a_mirar(self) -> None:
        self.activar(**{"plataforma.intervalo_envio_s": 30})
        self.paso()
        self.cliente.lotes.clear()
        self.lectura()
        self.paso(avanzar_s=10)
        self.assertEqual(self.cliente.lotes, [])                                 # aun no toca
        self.nucleo.ordenes.clear()
        self.paso(avanzar_s=25)
        self.assertEqual(len(self.cliente.lotes), 1)

    def test_cada_resultado_de_la_plataforma_se_traduce_a_su_estado(self) -> None:
        for _ in range(4):
            self.lectura()
        self.activar()
        lecturas = [e for e in mensajes.pendientes(self.lector.db, self.ahora_ms(), 1000) if e["tabla"] == "lectura"]
        i_ok, i_mal, i_otra, i_nada = (e["registro_id"] for e in lecturas)

        def responder(registros):
            res = {}
            for r in registros:
                if r["tabla"] != "lectura":
                    res[(r["tabla"], r["id"])] = ("ok", None, r["rev"])
                elif r["id"] == i_ok:
                    res[("lectura", r["id"])] = ("ok", None, r["rev"])
                elif r["id"] == i_mal:
                    res[("lectura", r["id"])] = ("rechazado", "valor fuera de rango", None)
                elif r["id"] == i_otra:
                    res[("lectura", r["id"])] = ("reintentar", None, None)
                # i_nada: la plataforma no dice nada
            return res

        self.cliente.respuesta = responder
        self.paso()
        datos = self.nucleo.ordenes[-1][1]
        por_registro = {e["registro_id"]: e["id"] for e in lecturas}
        self.assertIn(por_registro[i_ok], datos["confirmados"])
        self.assertEqual(datos["rechazados"], {por_registro[i_mal]: "valor fuera de rango"})
        self.assertEqual(list(datos["fallidos"]), [por_registro[i_otra]])
        every = set(datos["confirmados"]) | set(datos["rechazados"]) | set(datos["fallidos"])
        self.assertNotIn(por_registro[i_nada], every)                            # sin respuesta: sigue pendiente

    def test_una_revision_confirmada_mas_vieja_de_la_enviada_no_cuenta(self) -> None:
        alarma = self.a.abrir_alarma("ALM_O2_ALTO", sensor_id=self.s1, umbral=92.0, valor=93.0)
        self.a.cerrar_alarma(alarma)                                             # va por la rev 2
        self.activar()
        entradas = len([e for e in self.cola("pendiente") if e["tabla"] == "alarma"])
        self.assertGreaterEqual(entradas, 2)
        self.cliente.respuesta = lambda registros: {(r["tabla"], r["id"]): ("ok", None, r["rev"] - 1 if r["tabla"] == "alarma"
                                                                           else r["rev"]) for r in registros}
        self.paso()
        datos = self.nucleo.ordenes[-1][1]
        self.assertEqual(len(datos["fallidos"]), entradas)                       # todas las entradas de esa alarma
        self.assertIn("revision anterior", next(iter(datos["fallidos"].values())))

    def test_un_registro_que_ya_no_existe_se_marca_rechazado_para_no_insistir(self) -> None:
        self.activar()
        self.a.db.execute("INSERT INTO cola_envio (tabla, registro_id, rev, creado_ms) VALUES ('lectura', 999999, 1, ?)",
                          (self.ahora_ms(),))
        fantasma = self.a.db.execute("SELECT id FROM cola_envio WHERE registro_id = 999999").fetchone()[0]
        self.paso()
        self.assertEqual(self.nucleo.ordenes[-1][1]["rechazados"], {fantasma: "el registro ya no existe"})
        self.assertNotIn(("lectura", 999999), [(r["tabla"], r["id"]) for lote in self.cliente.lotes for r in lote])

    # ---- el enlace -------------------------------------------------------------------------------------------------------
    def test_sin_enlace_reintenta_con_esperas_crecientes_y_avisa_una_vez(self) -> None:
        self.lectura()
        self.activar(**{"plataforma.intervalo_visualizacion_s": 3600})           # la foto en vivo no interfiere aqui
        self.cliente.fallos_lote = [SinEnlace("sin conexion"), SinEnlace("sin conexion"), SinEnlace("sin conexion")]
        self.paso()                                                              # t=0: falla (espera 5 s)
        self.assertEqual((self.s.estado(), self.cliente.llamadas_lote), ("sin_enlace", 1))
        self.paso(avanzar_s=4)
        self.assertEqual(self.cliente.llamadas_lote, 1)                          # sigue esperando
        self.paso(avanzar_s=1)                                                   # t=5: segundo intento, falla (espera 10 s)
        self.assertEqual(self.cliente.llamadas_lote, 2)
        self.paso(avanzar_s=9)
        self.assertEqual(self.cliente.llamadas_lote, 2)
        self.paso(avanzar_s=1)                                                   # t=15: tercero, falla (espera 20 s)
        self.assertEqual(self.cliente.llamadas_lote, 3)
        self.paso(avanzar_s=19)
        self.assertEqual(self.cliente.llamadas_lote, 3)
        avisos = [d for t, d in self.nucleo.ordenes if d["enlace"] == "sin_enlace"]
        self.assertEqual(len(avisos), 1)                                         # UNA vez: no cada reintento
        self.paso(avanzar_s=1)                                                   # t=35: ya sale bien
        self.assertEqual(self.s.estado(), "ok")
        self.assertEqual(self.nucleo.ordenes[-1][1]["enlace"], "ok")

    def test_la_espera_nunca_pasa_de_cinco_minutos_y_se_respeta_lo_que_pida_la_plataforma(self) -> None:
        self.activar()
        self.cliente.fallos_vivo = [SinEnlace("x") for _ in range(12)]
        esperas = []
        for _ in range(8):
            self.s._no_antes = 0.0
            self.paso()
            esperas.append(round(self.s._no_antes - self.reloj.mono_ms() / 1000))
            self.s._prox_vivo = 0.0
        self.assertEqual(esperas, [5, 10, 20, 40, 80, 160, 300, 300])
        self.s._no_antes, self.s._prox_vivo = 0.0, 0.0
        self.cliente.fallos_vivo = [SinEnlace("x", espera_s=900)]
        self.paso()
        self.assertEqual(round(self.s._no_antes - self.reloj.mono_ms() / 1000), 900)

    def test_la_credencial_rechazada_espera_cinco_minutos_y_se_reintenta_al_cambiarla(self) -> None:
        self.activar()
        self.cliente.fallos_vivo = [CredencialRechazada("HTTP 401")]
        self.paso()
        self.assertEqual(self.s.estado(), "credencial_rechazada")
        self.assertEqual(self.nucleo.ordenes[-1][1]["enlace"], "credencial")
        llamadas = self.cliente.llamadas_vivo
        self.paso(avanzar_s=60)
        self.assertEqual(self.cliente.llamadas_vivo, llamadas)                  # no insiste
        self.secreto = SECRETO[::-1]                                             # alguien guarda el secreto correcto
        self.paso(avanzar_s=servicio.PERIODO_CONFIG_S)                           # lo lee y empieza de cero
        self.assertEqual(self.cliente.llamadas_vivo, llamadas + 1)
        self.assertEqual(self.s.estado(), "ok")

    def test_un_lote_demasiado_grande_se_achica_a_la_mitad(self) -> None:
        for _ in range(40):
            self.lectura()
        self.activar(**{"plataforma.lote_max": 400})
        self.cliente.fallos_lote = [LoteDemasiadoGrande("x")]
        self.paso()
        self.assertEqual(self.s._lote_efectivo, 200)
        self.assertEqual(self.cliente.lotes, [])                                 # no se perdio nada: sigue pendiente
        self.paso(avanzar_s=1)
        self.assertGreater(len(self.cliente.lotes[0]), 0)
        self.assertEqual(self.s.estado(), "ok")

    def test_un_lote_chico_no_baja_de_su_minimo(self) -> None:
        self.activar(**{"plataforma.lote_max": 10})
        self.lectura()
        self.cliente.fallos_lote = [LoteDemasiadoGrande("x")] * 3
        for _ in range(3):
            self.s._prox_lote = 0.0
            self.paso(avanzar_s=1)
        self.assertEqual(self.s._lote_efectivo, servicio.LOTE_MIN)

    def test_el_enlace_se_vuelve_a_avisar_mientras_siga_mal_por_si_el_nucleo_se_reinicio(self) -> None:
        self.activar()
        self.cliente.fallos_vivo = [SinEnlace("x") for _ in range(100)]
        self.paso()
        self.nucleo.ordenes.clear()
        for _ in range(4):
            self.paso(avanzar_s=servicio.ESPERA_MAX_S + 1)
        avisos = [d for t, d in self.nucleo.ordenes if d["enlace"] == "sin_enlace"]
        self.assertGreaterEqual(len(avisos), 2)                                  # cada REAVISO_ENLACE_S, no en cada intento
        self.assertLess(len(avisos), 4)

    # ---- el estado del nucleo y la foto en vivo ----------------------------------------------------------------------------
    def test_la_foto_en_vivo_lleva_el_oxigeno_y_nada_de_la_red_del_hospital(self) -> None:
        self.activar()
        self.paso()
        foto = self.cliente.vivos[0]
        self.assertTrue(foto["nucleo_ok"])
        self.assertEqual(foto["ts_ms"], self.ahora_ms())
        self.assertEqual(foto["version_sw"], "0.1.0-test")
        self.assertEqual(foto["sensores"][0], {"id": 1, "nombre": "Sensor 1", "estado": "NORMAL", "acusada": False, "o2": 87.57})
        self.assertIsNone(foto["sensores"][1]["o2"])
        self.assertEqual((foto["aviso"], foto["rele_alto"]), ("Sin alarmas", True))
        self.assertEqual(foto["alertas_salud"], ["ALM_RPI_TEMP_ALTA"])
        self.assertEqual(foto["red"], {"tipo": "wifi", "senal": 79, "internet": True})
        self.assertEqual(foto["salud"]["cpu_temp_c"], 48.3)
        self.assertNotIn("db_bytes", foto["salud"])
        texto = json.dumps(foto)
        for secreto in ("MiRed", "192.168.1.34", "10.0.0.1", "Vecina"):
            self.assertNotIn(secreto, texto)

    def test_la_foto_en_vivo_se_repite_cada_intervalo_de_visualizacion(self) -> None:
        self.activar(**{"plataforma.intervalo_visualizacion_s": 15})
        self.paso()
        self.paso(avanzar_s=10)
        self.assertEqual(len(self.cliente.vivos), 1)
        self.paso(avanzar_s=5)
        self.assertEqual(len(self.cliente.vivos), 2)

    def test_si_el_nucleo_no_responde_no_se_envian_lotes_pero_la_foto_lo_dice(self) -> None:
        self.lectura()
        self.activar()
        self.nucleo.edad_s = servicio.LIMITE_ESTADO_S + 1
        self.paso()
        self.assertEqual(self.cliente.llamadas_lote, 0)                          # no habria quien anotara el resultado
        foto = self.cliente.vivos[0]
        self.assertFalse(foto["nucleo_ok"])
        self.assertNotIn("sensores", foto)
        self.assertEqual(foto["edad_estado_s"], servicio.LIMITE_ESTADO_S + 1)
        self.nucleo.edad_s = 0.0                                                 # vuelve el nucleo
        self.paso(avanzar_s=1)
        self.assertGreater(self.cliente.llamadas_lote, 0)

    def test_sin_estado_del_nucleo_la_foto_no_trae_edad(self) -> None:
        self.activar()
        self.nucleo.estado = None
        self.paso()
        self.assertEqual(self.cliente.vivos[0], {"ts_ms": self.ahora_ms(), "version_sw": "0.1.0-test", "nucleo_ok": False,
                                                 "edad_estado_s": None})

    # ---- lo que publica ----------------------------------------------------------------------------------------------------
    def test_publica_su_estado_para_g2ctl(self) -> None:
        self.lectura()
        self.activar()
        self.paso()
        publicado = self.publicado()
        self.assertEqual((publicado["estado"], publicado["version_sw"]), ("ok", "0.1.0-test"))
        self.assertEqual(publicado["ultimo_ok_s"], self.ahora_ms() / 1000)
        self.assertGreater(publicado["confirmados"], 0)
        self.assertIsNotNone(publicado["pendientes"])

    def test_sin_acceso_a_la_base_lo_dice_y_reintenta(self) -> None:
        def no_abre():
            raise OSError("no se puede abrir")

        self.s = servicio.ServicioUplink(no_abre, self.nucleo, self.carpeta, leer_secreto=lambda: SECRETO,
                                         fabrica=lambda *a, **k: self.cliente,
                                         reloj=lambda: self.reloj.ahora_ms() / 1000, mono=lambda: self.reloj.mono_ms() / 1000)
        self.paso()
        self.assertEqual(self.s.estado(), "base_ilegible")
        self.assertEqual(self.cliente.llamadas_vivo, 0)


# ------------------------------------------------------------------------------------------------------------ de punta a punta
def hay_requests() -> bool:
    try:
        import requests  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(hay_requests(), "falta la libreria requests")
class PruebasDePuntaAPunta(BaseConBase):
    """g2-core real + g2-uplink real + cliente HTTP real + plataforma simulada, comunicados por archivos en /run/g2 como en la Pi."""

    def setUp(self) -> None:
        super().setUp()
        self.plataforma = PlataformaSimulada(SECRETO, EQUIPO).iniciar()
        self.addCleanup(self.plataforma.detener)
        self.run = self.dir / "run"
        self.publicador = ipc.PublicadorEstado(self.run, reloj=lambda: self.reloj.ahora_ms() / 1000)
        self.nucleo = Nucleo(self.a, FuenteSimulada({"ads1263:0-1": 0.209}), mono=lambda: 0.0)
        self.nucleo.iniciar()
        self.secreto = SECRETO
        for clave, valor in {"plataforma.activa": 1, "equipo.id": EQUIPO, "plataforma.url": self.plataforma.url}.items():
            self.a.config_fijar(clave, valor, origen="local", actor="prueba")
        self.servicio = servicio.ServicioUplink(
            lambda: Almacen(base.abrir_lectura(self.ruta)),
            ipc.ClienteNucleo(self.run, reloj=lambda: self.reloj.ahora_ms() / 1000), self.run,
            leer_secreto=lambda: self.secreto, reloj=lambda: self.reloj.ahora_ms() / 1000,
            mono=lambda: self.reloj.mono_ms() / 1000, version_sw="0.1.0-test")

    def tearDown(self) -> None:
        self.servicio.cerrar()
        super().tearDown()

    def ciclo(self, veces: int = 1, avanzar_s: float = 1.0) -> None:
        for _ in range(veces):
            self.reloj.avanzar(int(avanzar_s * 1000))
            self.publicador.publicar(ESTADO_NUCLEO)                              # g2-core vivo
            self.servicio.paso()
            for orden in self.publicador.recoger_ordenes():                      # g2-core atiende las ordenes
                self.nucleo.procesar_orden(orden)

    def test_todo_lo_pendiente_llega_a_la_plataforma_y_queda_confirmado(self) -> None:
        for _ in range(6):
            self.lectura()
            self.lectura(self.s2)
        self.a.abrir_alarma("ALM_O2_ALTO", sensor_id=self.s1, umbral=92.0, valor=93.0)
        self.ciclo(3)
        self.assertEqual(self.cola("pendiente"), [])
        self.assertTrue(all(e["estado"] == "confirmado" for e in self.cola()))
        recibidas = {(t, i) for t, i in self.plataforma.registros}
        self.assertEqual(sum(1 for t, _ in recibidas if t == "lectura"), 12)
        self.assertIn("alarma", {t for t, _ in recibidas})
        self.assertEqual(self.plataforma.registros[("alarma", 1)][1]["codigo"], "ALM_O2_ALTO")
        self.assertEqual(self.servicio.estado(), "ok")
        self.assertGreaterEqual(len(self.plataforma.vivos), 1)
        self.assertEqual(self.plataforma.vivos[0]["sensores"][0]["o2"], 87.57)
        # nada de esto dejo comandos que a su vez haya que enviar
        self.assertEqual(self.a.db.execute("SELECT COUNT(*) FROM comando WHERE tipo = 'cola_resultado'").fetchone()[0], 0)

    def test_lo_que_se_genera_despues_tambien_llega_sin_repetir_lo_anterior(self) -> None:
        self.lectura()
        self.ciclo(2)
        primeras = self.plataforma.peticiones
        self.lectura()
        self.lectura()
        self.ciclo(1, avanzar_s=31)
        ids = [i for t, i in self.plataforma.registros if t == "lectura"]
        self.assertEqual(len(ids), 3)
        self.assertGreater(self.plataforma.peticiones, primeras)
        self.assertEqual(self.cola("pendiente"), [])

    def test_un_registro_que_la_plataforma_rechaza_queda_rechazado_y_deja_un_evento(self) -> None:
        self.lectura()
        self.plataforma.rechazar_tablas = {"lectura"}
        self.ciclo(3)
        self.assertEqual([e["tabla"] for e in self.cola("rechazado")], ["lectura"])
        self.assertEqual(self.cola("rechazado")[0]["ultimo_error"], "datos invalidos (simulado)")
        self.assertEqual(self.a.db.execute("SELECT COUNT(*) FROM evento WHERE codigo = 'NET_ENVIO_RECHAZADO'").fetchone()[0], 1)
        # El evento del rechazo es un registro nuevo y sale en el siguiente envio; el rechazado no vuelve a intentarse
        self.assertEqual(sorted(e["tabla"] for e in self.cola("pendiente")), ["auditoria_cadena", "evento"])
        self.ciclo(1, avanzar_s=31)
        self.assertEqual(self.cola("pendiente"), [])
        codigos = [datos["codigo"] for (tabla, _), (_, datos) in self.plataforma.registros.items() if tabla == "evento"]
        self.assertIn("NET_ENVIO_RECHAZADO", codigos)                             # la plataforma se entera del rechazo
        self.assertEqual(len(self.cola("rechazado")), 1)

    def test_un_registro_que_la_plataforma_pide_reintentar_vuelve_a_intentarse_despues(self) -> None:
        self.lectura()
        self.plataforma.reintentar_tablas = {"lectura"}
        self.ciclo(2)
        espera = [e for e in self.cola("pendiente") if e["tabla"] == "lectura"]
        self.assertEqual((len(espera), espera[0]["intentos"]), (1, 1))
        self.plataforma.reintentar_tablas = set()
        self.ciclo(1, avanzar_s=61)                                               # pasa la espera
        self.assertEqual(self.cola("pendiente"), [])

    def test_una_credencial_equivocada_no_envia_nada_y_deja_el_evento(self) -> None:
        self.lectura()
        self.secreto = SECRETO[::-1]
        self.ciclo(1)
        self.assertEqual(self.servicio.estado(), "credencial_rechazada")
        self.assertEqual(self.plataforma.registros, {})
        self.assertEqual(self.a.db.execute("SELECT COUNT(*) FROM evento WHERE codigo = 'PLAT_CREDENCIAL_RECHAZADA'").fetchone()[0], 1)
        self.assertNotIn(SECRETO[::-1], json.dumps(self.publicador.carpeta.joinpath(servicio.NOMBRE_ESTADO).read_text()))

    def test_si_la_plataforma_se_cae_no_se_pierde_nada_y_al_volver_se_envia_todo(self) -> None:
        for _ in range(5):
            self.lectura()
        self.plataforma.fallar = 100
        self.ciclo(3, avanzar_s=2)
        self.assertEqual(self.servicio.estado(), "sin_enlace")
        self.assertEqual(self.plataforma.registros, {})
        self.assertEqual(self.cola("confirmado"), [])
        self.assertEqual(self.a.db.execute("SELECT COUNT(*) FROM evento WHERE codigo = 'PLAT_ENLACE_PERDIDO'").fetchone()[0], 1)
        self.plataforma.fallar = 0
        self.ciclo(2, avanzar_s=301)                                              # pasa la espera
        self.assertEqual(self.servicio.estado(), "ok")
        self.assertEqual(self.cola("pendiente"), [])
        self.assertEqual(sum(1 for t, _ in self.plataforma.registros if t == "lectura"), 5)
        self.assertEqual(self.a.db.execute("SELECT COUNT(*) FROM evento WHERE codigo = 'PLAT_ENLACE_RESTABLECIDO'").fetchone()[0], 1)

    def test_si_la_plataforma_no_acepta_lotes_grandes_se_achica_y_todo_llega(self) -> None:
        for _ in range(30):
            self.lectura()
        self.plataforma.maximo = 12
        self.a.config_fijar("plataforma.lote_max", 40, origen="local", actor="prueba")
        self.ciclo(15)
        self.assertEqual(self.cola("pendiente"), [])
        self.assertEqual(sum(1 for t, _ in self.plataforma.registros if t == "lectura"), 30)
        self.assertTrue(all(len(lote) <= 12 for lote in self.plataforma.lotes))

    def test_los_lotes_grandes_viajan_comprimidos(self) -> None:
        for _ in range(40):
            self.lectura()
        self.ciclo(2)
        self.assertTrue(any(c.get("content-encoding") == "gzip" for c in self.plataforma.cabeceras))
        self.assertTrue(all(c["authorization"] == f"Bearer {SECRETO}" for c in self.plataforma.cabeceras))

    def test_con_el_nucleo_detenido_no_se_envian_lotes(self) -> None:
        self.lectura()
        self.publicador.publicar(ESTADO_NUCLEO)
        self.reloj.avanzar(int((servicio.LIMITE_ESTADO_S + 5) * 1000))             # el estado queda viejo
        self.servicio.paso()
        self.assertEqual(self.plataforma.lotes, [])
        self.assertFalse(self.plataforma.vivos[0]["nucleo_ok"])


# ------------------------------------------------------------------------------------------------------------ g2ctl
class PruebasCtl(BaseConBase):
    def ejecutar(self, *argumentos, entrada: str = "", secretos: Path | None = None) -> tuple[int, str, str]:
        from g2 import ctl
        salida, errores = io.StringIO(), io.StringIO()
        entorno = {"G2_SECRETOS": str(secretos or self.dir / "secretos"), "G2_RUN": str(self.dir / "run")}
        with mock.patch.dict(os.environ, entorno), mock.patch("sys.stdin", io.StringIO(entrada)), \
                contextlib.redirect_stdout(salida), contextlib.redirect_stderr(errores):
            codigo = ctl.main(["--bd", str(self.ruta), *argumentos])
        return codigo, salida.getvalue(), errores.getvalue()

    def test_el_estado_dice_que_esta_apagado_y_que_falta_el_secreto(self) -> None:
        codigo, salida, _ = self.ejecutar("plataforma-estado")
        self.assertEqual(codigo, 0)
        self.assertIn("Activa: NO", salida)
        self.assertIn("Secreto guardado: NO", salida)
        self.assertIn("equipo.id: (falta)", salida)
        self.assertIn("g2-uplink: no publica estado", salida)

    def test_el_secreto_entra_por_la_entrada_estandar_y_nunca_se_muestra(self) -> None:
        codigo, salida, errores = self.ejecutar("plataforma-credencial", "--desde-stdin", entrada=SECRETO + "\n")
        self.assertEqual(codigo, 0)
        self.assertNotIn(SECRETO, salida + errores)
        self.assertEqual(credencial.leer(self.dir / "secretos"), SECRETO)
        codigo, salida, _ = self.ejecutar("plataforma-estado")
        self.assertIn("Secreto guardado: si", salida)
        self.assertNotIn(SECRETO, salida)

    def test_un_secreto_invalido_no_se_guarda(self) -> None:
        codigo, _, errores = self.ejecutar("plataforma-credencial", "--desde-stdin", entrada="corto\n")
        self.assertEqual(codigo, 2)
        self.assertIn("No se guardo el secreto", errores)
        self.assertFalse(credencial.existe(self.dir / "secretos"))

    def test_descartar_sin_confirmar_solo_muestra(self) -> None:
        self.lectura()
        codigo, salida, _ = self.ejecutar("cola-descartar", "--motivo", "pruebas")
        self.assertEqual(codigo, 0)
        self.assertIn("No se cambio nada", salida)
        self.assertIn("lectura 1", salida)
        self.assertEqual(self.a.db.execute("SELECT COUNT(*) FROM cola_envio WHERE estado = 'rechazado'").fetchone()[0], 0)

    def test_descartar_confirmado_deja_lo_pendiente_en_rechazado(self) -> None:
        self.lectura()
        codigo, salida, _ = self.ejecutar("cola-descartar", "--motivo", "pruebas", "--confirmar")
        self.assertEqual(codigo, 0)
        self.assertIn("Siguen guardados", salida)
        self.assertEqual(self.a.db.execute("SELECT COUNT(*) FROM lectura").fetchone()[0], 1)
        self.assertGreater(self.a.db.execute("SELECT COUNT(*) FROM cola_envio WHERE estado = 'rechazado'").fetchone()[0], 0)

    def test_el_estado_muestra_la_cola_y_lo_que_publica_el_servicio(self) -> None:
        self.lectura()
        (self.dir / "run").mkdir()
        (self.dir / "run" / servicio.NOMBRE_ESTADO).write_text(json.dumps(
            {"estado": "sin_enlace", "detalle": "HTTP 503", "confirmados": 7, "rechazados": 1}), encoding="utf-8")
        _, salida, _ = self.ejecutar("plataforma-estado")
        self.assertRegex(salida, r"Cola: \d+ pendiente")
        self.assertIn("g2-uplink: sin_enlace - HTTP 503", salida)
        self.assertIn("confirmados en esta sesion: 7", salida)


if __name__ == "__main__":
    unittest.main()
