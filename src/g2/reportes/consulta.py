"""Lo que lleva un reporte, leido de la base en SOLO LECTURA (D-044).

La base guarda UNA fila por sensor en cada intervalo de guardado, con su propia hora (los dos sensores se cierran con unos
milisegundos de diferencia). El reporte pone en una misma fila las dos lecturas del mismo intervalo:

  * se respeta lo que hay en la base: cada fila trae su ``periodo_ms``, asi que si el intervalo de guardado se cambio en
    algun momento, el reporte lo refleja (no se supone nunca 15 s);
  * dos lecturas son pareja si sus horas difieren menos de la mitad del intervalo; si un sensor no tiene pareja (estaba
    apagado, o el intervalo cambio) la fila lleva ``—`` en el otro;
  * una lectura es una ALERTA si, durante su intervalo, hubo una alarma de oxigeno BAJO o ALTO de ese sensor. El umbral que
    se imprime es el que tenia la alarma al dispararse (``alarma.umbral``), no el de hoy. La discrepancia entre sensores
    no se marca (decision del usuario).
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field

from g2.reportes import rango

CODIGOS_ALERTA = {"ALM_O2_BAJO": ("BAJO", "<"), "ALM_O2_ALTO": ("ALTO", ">")}
CODIGOS_ESTADO_SENSOR = {"SEN_DESHABILITADO": "apagado", "SEN_HABILITADO": "encendido"}
CODIGO_SIN_SENAL = "ALM_SENSOR_INVALIDO"
NOMBRES_CALIDAD = ((1, "saturada baja"), (2, "saturada alta"), (4, "en calibración"), (8, "sensor apagado"),
                   (16, "inestable"), (32, "sin datos"), (64, "fuera de rango"))


@dataclass(frozen=True)
class Medida:
    """Una fila de la tabla ``lectura``."""

    id: int
    ts_ms: int
    confiable: bool
    periodo_ms: int
    n_muestras: int
    o2: float | None
    calidad: int


@dataclass(frozen=True)
class Alarma:
    id: int
    codigo: str
    sensor_id: int | None
    inicio_ms: int
    fin_ms: int | None
    umbral: float | None
    valor_pico: float | None
    estado: str
    acuse_ms: int | None
    acuse_actor: str | None

    def texto(self) -> str:
        """``ALTO > 92.0``: el tipo de alarma y el umbral que tenia al dispararse."""
        nombre, signo = CODIGOS_ALERTA.get(self.codigo, (self.codigo, ""))
        return f"{nombre} {signo} {self.umbral:g}" if self.umbral is not None else nombre


@dataclass(frozen=True)
class CambioSensor:
    """Un cambio de estado de un sensor: lo apagaron o encendieron, o estuvo sin señal valida (``fin_ms`` None = sigue)."""

    ts_ms: int
    sensor_id: int | None
    estado: str                     # "apagado" | "encendido" | "sin_senal"
    fin_ms: int | None = None
    repeticiones: int = 1           # los cambios seguidos del mismo sensor se agrupan en un solo evento
    ultimo_ms: int | None = None


@dataclass
class Fila:
    """Una fila del reporte: las lecturas de los dos sensores en el mismo intervalo."""

    ts_ms: int
    confiable: bool
    s1: Medida | None
    s2: Medida | None
    alerta1: str | None = None
    alerta2: str | None = None

    @property
    def con_alerta(self) -> bool:
        return self.alerta1 is not None or self.alerta2 is not None


@dataclass
class DatosReporte:
    desde: str
    hasta: str
    zona: str
    inicio_ms: int
    fin_ms: int
    sensores: list[dict]
    filas: list[Fila] = field(default_factory=list)
    alarmas: list[Alarma] = field(default_factory=list)
    cambios_sensor: list[CambioSensor] = field(default_factory=list)
    calibraciones: list[dict] = field(default_factory=list)

    def periodos_s(self) -> list[int]:
        """Los intervalos de guardado que aparecen en el rango, en segundos enteros y del mas al menos usado (los que
        pesan menos del 1 % de las lecturas son duracion de arranques o cierres y se ignoran). Normalmente es uno solo."""
        cuenta = Counter(round(m.periodo_ms / 1000) for f in self.filas for m in (f.s1, f.s2) if m is not None)
        total = sum(cuenta.values())
        return [p for p, c in cuenta.most_common() if c >= max(1, 0.01 * total)]

    def resumen(self) -> dict:
        """Cifras para la primera pagina del reporte."""
        medidas = {1: [], 2: []}
        con_alerta = {1: 0, 2: 0}
        no_confiables = anomalas = 0
        for f in self.filas:
            for n, m in ((1, f.s1), (2, f.s2)):
                if m is not None and m.o2 is not None:
                    medidas[n].append(m.o2)
            con_alerta[1] += f.alerta1 is not None
            con_alerta[2] += f.alerta2 is not None
            no_confiables += not f.confiable
            anomalas += any(m is not None and m.calidad for m in (f.s1, f.s2))
        estadisticas = {n: ({"n": len(v), "min": min(v), "max": max(v), "prom": sum(v) / len(v)} if v else {"n": 0})
                        for n, v in medidas.items()}
        return {"filas": len(self.filas), "estadisticas": estadisticas, "con_alerta": con_alerta,
                "hora_no_confiable": no_confiables, "calidad_anomala": anomalas, "periodos_s": self.periodos_s()}


def texto_calidad(calidad: int) -> str:
    return ", ".join(nombre for bit, nombre in NOMBRES_CALIDAD if calidad & bit) or "normal"


# ---------------------------------------------------------------------------------------------- lectura de la base
def sensores(db: sqlite3.Connection) -> list[dict]:
    """Los DOS primeros sensores dados de alta (columnas S1 y S2 del reporte)."""
    filas = db.execute("SELECT id, nombre, modelo, serie_etiqueta, habilitado FROM sensor ORDER BY id LIMIT 2")
    return [dict(f) for f in filas]


def contar(db: sqlite3.Connection, inicio_ms: int, fin_ms: int) -> int:
    """Filas que tendria el reporte, sin armarlo (el mayor de los conteos por sensor: es una cota de las parejas)."""
    return int(db.execute(
        "SELECT COALESCE(MAX(c), 0) FROM (SELECT COUNT(*) AS c FROM lectura "
        "WHERE ts_ms >= ? AND ts_ms < ? GROUP BY sensor_id)", (inicio_ms, fin_ms)).fetchone()[0])


def leer_medidas(db: sqlite3.Connection, sensor_id: int, inicio_ms: int, fin_ms: int) -> list[Medida]:
    filas = db.execute(
        "SELECT id, ts_ms, ts_confiable, periodo_ms, n_muestras, o2_prom, calidad FROM lectura "
        "WHERE sensor_id = ? AND ts_ms >= ? AND ts_ms < ? ORDER BY ts_ms, id", (sensor_id, inicio_ms, fin_ms))
    return [Medida(f["id"], f["ts_ms"], bool(f["ts_confiable"]), f["periodo_ms"], f["n_muestras"],
                   f["o2_prom"], f["calidad"]) for f in filas]


def leer_alarmas(db: sqlite3.Connection, inicio_ms: int, fin_ms: int) -> list[Alarma]:
    """Las alarmas de oxigeno que estuvieron abiertas en algun momento del rango (incluidas las que empezaron antes)."""
    marcas = ",".join("?" * len(CODIGOS_ALERTA))
    filas = db.execute(
        f"SELECT id, codigo, sensor_id, inicio_ms, fin_ms, umbral, valor_pico, estado, acuse_ms, acuse_actor FROM alarma "
        f"WHERE codigo IN ({marcas}) AND inicio_ms < ? AND (fin_ms IS NULL OR fin_ms >= ?) ORDER BY inicio_ms, id",
        (*CODIGOS_ALERTA, fin_ms, inicio_ms))
    return [Alarma(f["id"], f["codigo"], f["sensor_id"], f["inicio_ms"], f["fin_ms"], f["umbral"], f["valor_pico"],
                   f["estado"], f["acuse_ms"], f["acuse_actor"]) for f in filas]


def leer_cambios_sensor(db: sqlite3.Connection, inicio_ms: int, fin_ms: int) -> list[CambioSensor]:
    """Cuando apagaron o encendieron un sensor y cuando estuvo sin señal valida, en orden de hora. Un sensor apagado no
    deja lecturas (el reporte muestra ``—``): esto dice por que."""
    marcas = ",".join("?" * len(CODIGOS_ESTADO_SENSOR))
    cambios = [
        CambioSensor(f["ts_ms"], f["sensor_id"], CODIGOS_ESTADO_SENSOR[f["codigo"]], repeticiones=f["repeticiones"],
                     ultimo_ms=f["ultimo_ms"] if f["repeticiones"] > 1 else None)
        for f in db.execute(
            f"SELECT ts_ms, sensor_id, codigo, repeticiones, ultimo_ms FROM evento "
            f"WHERE codigo IN ({marcas}) AND ts_ms >= ? AND ts_ms < ? ORDER BY ts_ms, id",
            (*CODIGOS_ESTADO_SENSOR, inicio_ms, fin_ms))]
    cambios += [
        CambioSensor(f["inicio_ms"], f["sensor_id"], "sin_senal", f["fin_ms"])
        for f in db.execute(
            "SELECT sensor_id, inicio_ms, fin_ms FROM alarma WHERE codigo = ? AND inicio_ms < ? "
            "AND (fin_ms IS NULL OR fin_ms >= ?) ORDER BY inicio_ms, id", (CODIGO_SIN_SENAL, fin_ms, inicio_ms))]
    return sorted(cambios, key=lambda c: c.ts_ms)


# ------------------------------------------------------------------------------------------------------- armado
def emparejar(a: list[Medida], b: list[Medida]) -> list[tuple[Medida | None, Medida | None]]:
    """Junta las lecturas de los dos sensores (ambas listas ordenadas por hora). Pareja = horas a menos de la mitad
    del intervalo de la fila mas corta."""
    pares: list[tuple[Medida | None, Medida | None]] = []
    i = j = 0
    while i < len(a) and j < len(b):
        tolerancia = min(a[i].periodo_ms, b[j].periodo_ms) // 2
        diferencia = a[i].ts_ms - b[j].ts_ms
        if abs(diferencia) <= tolerancia:
            pares.append((a[i], b[j]))
            i += 1
            j += 1
        elif diferencia < 0:
            pares.append((a[i], None))
            i += 1
        else:
            pares.append((None, b[j]))
            j += 1
    pares.extend((m, None) for m in a[i:])
    pares.extend((None, m) for m in b[j:])
    return pares


def alertas_de(medidas: list[Medida], alarmas: list[Alarma]) -> list[str | None]:
    """Para cada lectura (en orden de hora), el texto de la alarma de ese sensor que estuvo abierta durante su intervalo,
    o ``None``. Recorre las dos listas una sola vez."""
    resultado: list[str | None] = []
    if not medidas:
        return resultado
    mayor_periodo = max(m.periodo_ms for m in medidas)
    pendientes = sorted(alarmas, key=lambda x: x.inicio_ms)
    activas: list[Alarma] = []
    siguiente = 0
    for m in medidas:
        while siguiente < len(pendientes) and pendientes[siguiente].inicio_ms <= m.ts_ms:
            activas.append(pendientes[siguiente])
            siguiente += 1
        activas = [x for x in activas if x.fin_ms is None or x.fin_ms >= m.ts_ms - mayor_periodo]
        coincidencia = next((x for x in activas if x.fin_ms is None or x.fin_ms >= m.ts_ms - m.periodo_ms), None)
        resultado.append(coincidencia.texto() if coincidencia else None)
    return resultado


def armar(medidas1: list[Medida], medidas2: list[Medida], alarmas1: list[Alarma],
          alarmas2: list[Alarma]) -> list[Fila]:
    """Las filas del reporte: parejas de lecturas con sus alertas, en orden de hora."""
    texto1 = dict(zip((m.id for m in medidas1), alertas_de(medidas1, alarmas1)))
    texto2 = dict(zip((m.id for m in medidas2), alertas_de(medidas2, alarmas2)))
    filas = []
    for m1, m2 in emparejar(medidas1, medidas2):
        ref = m1 or m2
        assert ref is not None
        filas.append(Fila(ts_ms=ref.ts_ms, confiable=all(m.confiable for m in (m1, m2) if m is not None),
                          s1=m1, s2=m2, alerta1=texto1.get(m1.id) if m1 else None,
                          alerta2=texto2.get(m2.id) if m2 else None))
    return filas


def construir(db: sqlite3.Connection, desde, hasta, nombre_zona: str) -> DatosReporte:
    """Lee de la base todo lo que lleva el reporte del rango ``desde`` .. ``hasta`` (dias completos).

    Raises:
        rango.ErrorRango: si el rango es demasiado grande (mas de ``MAX_FILAS`` filas).
    """
    inicio, fin = rango.limites_ms(desde, hasta, nombre_zona)
    cuantas = contar(db, inicio, fin)
    if cuantas > rango.MAX_FILAS:
        raise rango.ErrorRango(f"Demasiados registros ({cuantas}): elija menos días")
    lista = sensores(db)
    datos = DatosReporte(desde=rango.formato_fecha(desde), hasta=rango.formato_fecha(hasta), zona=nombre_zona,
                         inicio_ms=inicio, fin_ms=fin, sensores=lista)
    ids = [s["id"] for s in lista]
    medidas = [leer_medidas(db, sid, inicio, fin) for sid in ids] + [[], []]
    datos.alarmas = leer_alarmas(db, inicio, fin)
    datos.cambios_sensor = leer_cambios_sensor(db, inicio, fin)
    por_sensor = [[a for a in datos.alarmas if a.sensor_id == sid] for sid in ids] + [[], []]
    datos.filas = armar(medidas[0], medidas[1], por_sensor[0], por_sensor[1])
    datos.calibraciones = [dict(f) for f in db.execute(
        "SELECT c.id, c.ts_ms, c.sensor_id, c.tipo, c.gas_pct, c.gas_certificado, c.offset_pct, c.resultado, "
        "c.vigente, c.actor, c.ganancia, c.bajo_ref_pct, c.alto_ref_pct FROM calibracion c WHERE c.vigente = 1 OR (c.ts_ms >= ? AND c.ts_ms < ?) "
        "ORDER BY c.ts_ms, c.id", (inicio, fin))]
    return datos
