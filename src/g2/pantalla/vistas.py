"""Vistas: del estado del nucleo a lo que debe mostrar cada pagina de la pantalla.

Cada funcion es PURA (no habla con la pantalla ni con la base): recibe datos y devuelve un diccionario
``{"pagina.componente.atributo": valor}``. La interfaz compara con lo que ya mostro y envia solo lo que
cambio (a 9600 baudios cada orden cuesta tiempo). Los nombres y colores son los de
nextion/ESPECIFICACION_HMI.md.
"""

from __future__ import annotations

import time
from typing import Mapping

from g2.pantalla.protocolo import COLOR

Vista = dict[str, "str | int"]

MAX_AVISO = 60                                  # txt_maxl de ``aviso``
SIN_ALARMAS = "Sin alarmas"
NOMBRES_ALARMA = {"ALM_O2_BAJO": "BAJO", "ALM_O2_ALTO": "ALTO", "ALM_SENSOR_INVALIDO": "SIN SEÑAL",
                  "ALM_SENSORES_DISCREPANTES": "DISCREPANCIA"}


def colores_estado(texto: str, acusada: bool, fase_encendida: bool) -> tuple[int, int]:
    """``(bco, pco)`` del recuadro de estado de un sensor (seccion 5 de la especificacion).

    Alarma SIN acusar: parpadea (1 Hz), alternando el color de la alarma con los colores invertidos, asi
    el texto sigue legible en las dos fases. Alarma acusada: fija en rojo.
    """
    if texto in ("BAJA", "ALTA"):
        if acusada or fase_encendida:
            return COLOR["alarma"], COLOR["blanco"]
        return COLOR["blanco"], COLOR["alarma"]
    if texto == "NORMAL":
        return COLOR["normal"], COLOR["blanco"]
    return COLOR["inactivo"], COLOR["blanco"]            # SIN SEÑAL, APAGADO


def vista_principal(estado: Mapping | None, *, nucleo_responde: bool, fase_encendida: bool,
                    hora: str, red: str, cola: int, mensaje: str | None = None) -> Vista:
    """Pagina ``principal``. Si el nucleo no responde, no se muestra ningun valor viejo como si fuera
    actual: los recuadros pasan a ``SIN SEÑAL`` y el aviso lo dice."""
    v: Vista = {"principal.hora.txt": hora, "principal.red_s.txt": red,
                "principal.cola_s.txt": f"COLA {cola}"}
    sensores = list(estado["sensores"][:2]) if estado and nucleo_responde else [{}, {}]
    for i in (1, 2):
        s = sensores[i - 1] if i <= len(sensores) else {}
        if nucleo_responde and s:
            texto, acusada = s["estado"], bool(s["acusada"])
            valor = s["texto_o2"]
        else:
            texto, acusada, valor = "SIN SEÑAL", False, "--.-"
        bco, pco = colores_estado(texto, acusada, fase_encendida)
        v[f"principal.o2_{i}.txt"] = valor
        v[f"principal.o2_{i}.pco"] = COLOR["alarma"] if texto in ("BAJA", "ALTA") else COLOR["texto"]
        v[f"principal.est_{i}.txt"] = texto
        v[f"principal.est_{i}.bco"] = bco
        v[f"principal.est_{i}.pco"] = pco
    if not nucleo_responde:
        aviso, en_alarma = "Núcleo sin respuesta", True
    elif mensaje:
        aviso, en_alarma = mensaje, False
    else:
        aviso = str(estado.get("aviso", SIN_ALARMAS)) if estado else SIN_ALARMAS
        en_alarma = aviso != SIN_ALARMAS
        if not en_alarma and red == "SIN RED":                       # equipo nuevo o sin red: guiar al instalador
            aviso = "Sin red: toque Red para conectarse"
    v["principal.aviso.txt"] = aviso[:MAX_AVISO]
    v["principal.aviso.bco"] = COLOR["alarma"] if en_alarma else COLOR["tarjeta"]
    v["principal.aviso.pco"] = COLOR["blanco"] if en_alarma else COLOR["texto"]
    return v


def texto_historial(alarma: Mapping) -> str:
    """``DD/MM HH:MM S1 BAJO`` (hora local) para una fila del historial reciente; las alarmas del
    sistema, que no son de un sensor, van sin ``S#``."""
    t = time.localtime(alarma["inicio_ms"] / 1000)
    nombre = NOMBRES_ALARMA.get(alarma["codigo"], alarma["codigo"])
    sensor = f" S{alarma['sensor_id']}" if alarma.get("sensor_id") else ""
    return f"{t.tm_mday:02d}/{t.tm_mon:02d} {t.tm_hour:02d}:{t.tm_min:02d}{sensor} {nombre}"


def vista_alarmas(config: Mapping[str, float], historial: list[Mapping]) -> Vista:
    """Pagina ``alarmas``: los cinco ajustes con su unidad y las 6 alarmas mas recientes (las que
    siguen abiertas, en rojo; las cerradas, en gris azulado)."""
    v: Vista = {
        "alarmas.v_bajo.txt": f"{config['alarma.o2_bajo_pct']:.1f} %",
        "alarmas.v_alto.txt": f"{config['alarma.o2_alto_pct']:.1f} %",
        "alarmas.v_retardo.txt": f"{int(config['alarma.o2_retardo_s'])} s",
        "alarmas.v_histeresis.txt": f"{config['alarma.o2_histeresis_pct']:.1f} %",
        "alarmas.v_acuse.txt": f"{int(config['alarma.acuse_silencio_s'])} s",
    }
    for n in range(6):
        if n < len(historial):
            fila = historial[n]
            abierta = fila["estado"] != "cerrada"
            v[f"alarmas.h{n + 1}.txt"] = texto_historial(fila)
            v[f"alarmas.h{n + 1}.pco"] = COLOR["alarma"] if abierta else COLOR["texto_suave"]
        else:
            v[f"alarmas.h{n + 1}.txt"] = ""
            v[f"alarmas.h{n + 1}.pco"] = COLOR["texto"]
    return v


def vista_teclado(*, titulo: str, rotulo: str, valor: str, mensaje: str, mensaje_es_error: bool) -> Vista:
    """Pagina ``teclado``: titulo de la barra, que se esta tecleando, el campo (asteriscos si es un PIN) y
    el mensaje de ayuda (gris azulado) o de error (rojo)."""
    return {"teclado.titulo.txt": titulo, "teclado.t_titulo.txt": rotulo, "teclado.valor.txt": valor,
            "teclado.msg.txt": mensaje,
            "teclado.msg.pco": COLOR["alarma"] if mensaje_es_error else COLOR["texto_suave"]}


def formato_duracion(segundos: float | None) -> str:
    """``3 d 4 h``, ``5 h 12 min`` o ``12 min``: el tiempo encendido de forma corta."""
    if segundos is None:
        return "--"
    minutos = int(segundos // 60)
    dias, resto = divmod(minutos, 1440)
    horas, minutos = divmod(resto, 60)
    if dias:
        return f"{dias} d {horas} h"
    if horas:
        return f"{horas} h {minutos} min"
    return f"{minutos} min"


def _o_guiones(valor, formato: str) -> str:
    return "--" if valor is None else formato.format(valor)


ALERTAS_CPU = ("ALM_RPI_TEMP_ALTA", "ALM_RPI_RAM_ALTA")
ALERTAS_DISCO = ("ALM_DISCO_ESPACIO_BAJO", "ALM_DISCO_ESPACIO_CRITICO")


def vista_sistema(estado: Mapping | None, *, nucleo_responde: bool, protocolo: int | None, cola: int,
                  pin: str | None, resultado: str | None, resultado_es_error: bool = False) -> Vista:
    """Pagina ``sistema``: ocho lineas de informacion y el resultado de la ultima accion. Las lineas de CPU/RAM y
    de disco pasan a rojo mientras la Pi tenga la alarma correspondiente."""
    salud = (estado or {}).get("salud") or {} if nucleo_responde else {}
    alertas = (estado or {}).get("alertas_salud") or [] if nucleo_responde else []
    libre_pct = None if salud.get("disco_pct") is None else 100.0 - salud["disco_pct"]
    mb = None if salud.get("db_bytes") is None else salud["db_bytes"] / 1024 ** 2
    nombres_pin = {"fabrica": "de fábrica", "plataforma": "de la plataforma"}
    v: Vista = {
        "sistema.i1.txt": f"Software {estado.get('version_sw', '--')}" if nucleo_responde and estado else "Software --",
        "sistema.i2.txt": f"Pantalla: protocolo {protocolo if protocolo is not None else '?'}",
        "sistema.i3.txt": f"Encendido hace {formato_duracion(salud.get('uptime_s'))}",
        "sistema.i4.txt": f"CPU {_o_guiones(salud.get('cpu_temp_c'), '{:.0f}')} °C   RAM {_o_guiones(salud.get('mem_pct'), '{:.0f}')} %",
        "sistema.i5.txt": f"Disco libre {_o_guiones(salud.get('disco_libre_gb'), '{:.1f}')} GB ({_o_guiones(libre_pct, '{:.0f}')} %)",
        "sistema.i6.txt": f"Base {_o_guiones(mb, '{:.1f}')} MB   Cola {cola}",
        "sistema.i7.txt": "Núcleo OK · Pantalla OK" if nucleo_responde else "Núcleo SIN RESPUESTA",
        "sistema.i8.txt": f"PIN: {nombres_pin.get(pin, 'SIN PIN') if pin else 'SIN PIN'}",
    }
    rojo, normal = COLOR["alarma"], COLOR["texto"]
    v["sistema.i4.pco"] = rojo if any(a in alertas for a in ALERTAS_CPU) else normal
    v["sistema.i5.pco"] = rojo if any(a in alertas for a in ALERTAS_DISCO) else normal
    v["sistema.i7.pco"] = normal if nucleo_responde else rojo
    v["sistema.i8.pco"] = rojo if not pin else normal
    v["sistema.res.txt"] = resultado or ""
    v["sistema.res.pco"] = rojo if resultado_es_error else COLOR["texto_suave"]
    return v


def vista_config(config: Mapping[str, float], sensores: list[Mapping], equipo: Mapping[str, str]) -> Vista:
    """Pagina ``config``: ajustes con su unidad, sensores activos o apagados y los datos del equipo."""
    v: Vista = {
        "config.v_guardado.txt": f"{int(config['muestreo.intervalo_guardado_s'])} s",
        "config.v_pantalla.txt": f"{int(config['muestreo.intervalo_pantalla_s'])} s",
        "config.v_discrepancia.txt": f"{config['alarma.discrepancia_pct']:.1f} %",
        "config.e1.txt": f"Nombre: {equipo.get('equipo.nombre') or '(sin definir)'}",
        "config.e2.txt": f"ID: {equipo.get('equipo.id') or '(sin definir)'}",
    }
    for n in (1, 2):
        sensor = sensores[n - 1] if n <= len(sensores) else None
        if sensor is None:
            v[f"config.v_sensor{n}.txt"], v[f"config.e{n + 2}.txt"] = "SIN SENSOR", f"S{n}: no dado de alta"
            v[f"config.v_sensor{n}.pco"] = COLOR["texto_suave"]
            continue
        activo = bool(sensor["habilitado"])
        v[f"config.v_sensor{n}.txt"] = "ACTIVO" if activo else "APAGADO"
        v[f"config.v_sensor{n}.pco"] = COLOR["texto"] if activo else COLOR["alarma"]
        v[f"config.e{n + 2}.txt"] = f"S{n}: {sensor['modelo']}, serie {sensor.get('serie_etiqueta') or '-'}"[:40]
    return v


def vista_confirmar(pregunta: str, detalle: str) -> Vista:
    """Pagina ``confirmar``: la pregunta de Si / No de una accion delicada."""
    return {"confirmar.t_pregunta.txt": pregunta, "confirmar.t_detalle.txt": detalle}


def vista_red(red: Mapping | None, redes: list[Mapping], cambio: Mapping | None, *, nucleo_responde: bool,
              resultado: str | None, resultado_es_error: bool = False) -> Vista:
    """Pagina ``red``: estado de la conexion (5 lineas), redes cercanas (4) y el progreso o resultado de un cambio."""
    red = red if (nucleo_responde and red) else {}
    if red.get("tipo") == "wifi":
        conexion = f"Conexión: WiFi «{red.get('ssid') or '?'}»"
    elif red.get("tipo") == "ethernet":
        conexion = "Conexión: Cable (Ethernet)"
    else:
        conexion = "Conexión: SIN RED"
    internet = red.get("internet")
    v: Vista = {
        "red.i1.txt": conexion[:40],
        "red.i2.txt": f"IP: {red.get('ip') or '--'}",
        "red.i3.txt": f"Señal: {red['senal']} %" if red.get("senal") is not None else "Señal: --",
        "red.i4.txt": "Internet: --" if internet is None else f"Internet: {'SÍ' if internet else 'NO'}",
        "red.i5.txt": f"ZeroTier: {red.get('zerotier_ip') or 'no conectado'}",
    }
    v["red.i1.pco"] = COLOR["texto"] if red.get("tipo") else COLOR["alarma"]
    v["red.i4.pco"] = COLOR["alarma"] if internet is False else COLOR["texto"]
    for n in range(4):
        if nucleo_responde and n < len(redes):
            r = redes[n]
            v[f"red.n{n + 1}.txt"] = f"{r['ssid'][:22]}  {r['senal']}%"
        else:
            v[f"red.n{n + 1}.txt"] = ""
    if cambio and cambio.get("en_curso"):
        v["red.res.txt"], v["red.res.pco"] = f"Conectando a «{cambio['en_curso']}»...", COLOR["texto_suave"]
    else:
        v["red.res.txt"] = resultado or ""
        v["red.res.pco"] = COLOR["alarma"] if resultado_es_error else COLOR["texto_suave"]
    return v


def vista_texto(entrada, *, titulo: str, mensaje: str, mensaje_es_error: bool) -> Vista:
    """Pagina ``texto``: titulo de la barra, el campo, el mensaje y la etiqueta de cada tecla en la capa actual."""
    v: Vista = {"texto.titulo.txt": titulo, "texto.valor.txt": entrada.mostrar(), "texto.msg.txt": mensaje,
                "texto.msg.pco": COLOR["alarma"] if mensaje_es_error else COLOR["texto_suave"],
                "texto.b_mayus.txt": entrada.rotulo_mayus(), "texto.b_simbolos.txt": entrada.rotulo_simbolos(),
                "texto.b_ver.txt": entrada.rotulo_ver()}
    for n, rotulo in enumerate(entrada.rotulos()):
        v[f"texto.t_{n:02d}.txt"] = rotulo
    return v
