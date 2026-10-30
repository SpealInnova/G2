"""Dibuja el reporte en PDF y lo cifra (D-044).

Dibujar: ``reportlab`` (ya esta en la Raspberry Pi), directamente sobre el lienzo y fila por fila, sin armar tablas en
memoria: asi 40 000 filas (una semana a 15 s, ~730 paginas) tardan ~25 s y usan ~50 MB. El numero de paginas se conoce
ANTES de dibujar (todo tiene alto fijo), de modo que cada pagina dice ``Pagina X de Y`` y se nota si faltan paginas.

Cifrar: ``pypdf`` con AES-256. La contrasena para ABRIR es el nombre del equipo; la del propietario es aleatoria y se
descarta (nadie puede quitar los permisos): el documento se puede ver, imprimir y copiar su texto, no editar.

Las filas con alerta se escriben en ROJO y NEGRITA: el identificador, la fecha, la hora, la lectura del sensor en alerta
y la descripcion de la alerta (con el umbral que tenia la alarma al dispararse).
"""

from __future__ import annotations

import math
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from g2.reportes import consulta, rango



def texto_calibracion(c: dict, zona: str) -> str:
    """Una linea de la hoja de resumen: la calibracion vigente de un sensor. Una calibracion por puntos (D-049) dice su ganancia, su
    cero y los gases patron de sus dos puntos; las anteriores, el gas y el cero."""
    f, h = rango.texto_hora(c["ts_ms"], zona)
    if c["tipo"] == "puntos":
        def gas(valor):
            return "sin medir" if valor is None else f"{valor:g} %"
        detalle = (f" · ganancia {c['ganancia'] or 1.0:.3f} · cero {c['offset_pct'] or 0.0:+.2f} %"
                   f" · gas bajo {gas(c['bajo_ref_pct'])} · gas alto {gas(c['alto_ref_pct'])}")
    else:
        detalle = ((f" · gas {c['gas_pct']:g} %" if c["gas_pct"] is not None else "")
                   + (f" · cero {c['offset_pct']:+g} %" if c["offset_pct"] is not None else ""))
    return f"Sensor {c['sensor_id']}: {c['tipo']} el {f} {h[:5]}{detalle}{' · ' + c['actor'] if c['actor'] else ''}"

class ErrorReporte(Exception):
    """No se pudo dibujar o cifrar el reporte; el mensaje se puede mostrar en la pantalla."""


class Cancelado(Exception):
    """El usuario cancelo el reporte mientras se dibujaba."""


# ---- medidas de la pagina (A4 vertical, en puntos) -------------------------------------------------------------------
ANCHO, ALTO = 595.27, 841.89
MARGEN = 36
ALTO_FILA = 12.0
Y_PRIMERA_FILA = 722.0                           # la linea de base de la primera fila de datos
FILAS_POR_PAGINA = 57
LINEAS_ANEXO_POR_PAGINA = 52
CADA_CUANTAS_FILAS_AVISAR = 400
LOGO = Path(__file__).parent / "recursos" / "speal.png"      # logo de SPEAL: el mismo de la pantalla (nextion/imagenes/logo.png)
SEPARACION_LOGO = 14.0                                       # espacio entre el nombre del equipo y el logo
LOGO_ALTO = 22.0                                             # pequeno y a un lado del titulo: sutil, no invasivo
ROJO = (0.78, 0.07, 0.07)
NEGRO = (0, 0, 0)
GRIS = (0.35, 0.35, 0.35)
VERDE = (0.05, 0.45, 0.2)
# Columnas de la tabla de lecturas: (titulo, x, alineacion)
COLUMNAS = (("Reg. S1", 40, "d", 78), ("Reg. S2", 86, "d", 124), ("Fecha", 132, "i", 0), ("Hora", 196, "i", 0),
            ("S1 % O2", 244, "d", 300), ("S2 % O2", 306, "d", 358), ("Alerta", 372, "i", 0))
X_COLUMNA_ALERTA = 372


@dataclass
class Portada:
    """Datos del equipo y de la generacion que van en el encabezado y la primera pagina."""

    nombre: str
    equipo_id: str
    version_sw: str
    generado_ms: int
    cadena: tuple[bool, int] | None = None        # (integra, diferencias); None = no se pudo verificar


def _numero(valor: float | None, marca: str = "") -> str:
    return "—" if valor is None else f"{valor:.2f}{marca}"


def _texto_intervalos(periodos: list[int]) -> str:
    if not periodos:
        return "—"
    return f"{periodos[0]} s" + (f"   (también {', '.join(f'{p} s' for p in periodos[1:])}: se cambió en el rango)"
                                 if len(periodos) > 1 else "")


def paginas_de_datos(filas: int) -> int:
    return max(1, math.ceil(filas / FILAS_POR_PAGINA))


def _lineas_anexo(datos: consulta.DatosReporte) -> list[tuple[str, str]]:
    """Las lineas del anexo (alarmas de oxigeno) como ``(estilo, texto)``; el estilo es ``t`` (titulo),
    ``e`` (encabezado de columnas), ``n`` (normal), ``a`` (alerta: rojo) o ``s`` (separador, linea en blanco)."""
    zona = datos.zona
    lineas: list[tuple[str, str]] = [("t", "Alarmas de oxígeno (fechas en día/mes y hora local)")]
    if not datos.alarmas:
        lineas.append(("n", "Sin alarmas de oxígeno en el rango."))
    else:
        lineas.append(("e", f"{'Inicio':<21}{'Fin':<21}{'Sensor':<8}{'Alarma':<18}{'Pico':<9}Acuse"))
        for a in datos.alarmas[:150]:
            f1, h1 = rango.texto_hora(a.inicio_ms, zona)
            if a.fin_ms is not None:
                f2, h2 = rango.texto_hora(a.fin_ms, zona)
                fin = f"{f2[:5]} {h2}"
            else:
                fin = "(abierta)"
            pico = f"{a.valor_pico:.2f}" if a.valor_pico is not None else "—"
            sensor = f"S{a.sensor_id}" if a.sensor_id else "?"
            lineas.append(("a" if a.fin_ms is None else "n",
                           f"{f1[:5] + ' ' + h1:<21}{fin:<21}{sensor:<8}{a.texto():<18}{pico:<9}{a.acuse_actor or 'sin acusar'}"))
        if len(datos.alarmas) > 150:
            lineas.append(("n", f"… y {len(datos.alarmas) - 150} alarmas más (consulte la base de datos)."))
    lineas += [("s", ""), ("t", "Estado de los sensores (apagados, encendidos o sin señal)")]
    if not datos.cambios_sensor:
        lineas.append(("n", "Sin cambios de estado de los sensores en el rango."))
    else:
        lineas.append(("e", f"{'Fecha y hora':<21}{'Sensor':<8}Estado"))
        for c in datos.cambios_sensor[:150]:
            f1, h1 = rango.texto_hora(c.ts_ms, zona)
            lineas.append(("n", f"{f1[:5] + ' ' + h1:<21}{'S' + str(c.sensor_id) if c.sensor_id else '?':<8}{_texto_estado(c, zona)}"))
        if len(datos.cambios_sensor) > 150:
            lineas.append(("n", f"… y {len(datos.cambios_sensor) - 150} cambios más (consulte la base de datos)."))
    return lineas


def _texto_estado(c: consulta.CambioSensor, zona: str) -> str:
    """``Apagado``, ``Encendido`` o ``Sin señal`` (con hasta cuando); la base agrupa en un solo evento los que se repiten
    en menos de un minuto (``evento.agrupar_s``), y aqui se dice cuantos fueron y cuando fue el ultimo."""
    if c.estado == "sin_senal":
        if c.fin_ms is None:
            return "Sin señal (sigue sin señal)"
        f2, h2 = rango.texto_hora(c.fin_ms, zona)
        return f"Sin señal (hasta {f2[:5]} {h2})"
    texto = "Apagado" if c.estado == "apagado" else "Encendido"
    if c.repeticiones > 1 and c.ultimo_ms is not None:
        f2, h2 = rango.texto_hora(c.ultimo_ms, zona)
        texto += f" ({c.repeticiones} veces; la última {f2[:5]} {h2})"
    return texto


def total_paginas(datos: consulta.DatosReporte) -> int:
    anexo = math.ceil(len(_lineas_anexo(datos)) / LINEAS_ANEXO_POR_PAGINA)
    return 1 + paginas_de_datos(len(datos.filas)) + anexo


# ---------------------------------------------------------------------------------------------------------------------
class _Dibujante:
    def __init__(self, lienzo, portada: Portada, datos: consulta.DatosReporte, total: int) -> None:
        self.c, self.portada, self.datos, self.total = lienzo, portada, datos, total
        self.pagina = 0

    def _color(self, rgb) -> None:
        self.c.setFillColorRGB(*rgb)

    def _texto(self, x: float, y: float, texto: str, *, negrita: bool = False, tamano: float = 8, color=NEGRO,
               derecha: bool = False) -> None:
        self._color(color)
        self.c.setFont("Helvetica-Bold" if negrita else "Helvetica", tamano)
        (self.c.drawRightString if derecha else self.c.drawString)(x, y, texto)

    def nueva_pagina(self, titulo: str, con_logo: bool = False) -> None:
        if self.pagina:
            self.c.showPage()
        self.pagina += 1
        d, p = self.datos, self.portada
        self._texto(MARGEN, ALTO - 44, "G2 · Reporte de lecturas de oxígeno", negrita=True, tamano=13)
        borde = ANCHO - MARGEN                       # donde termina el nombre del equipo: se corre a la izquierda si hay logo
        if con_logo:
            ancho_logo = self._logo()
            if ancho_logo:
                borde -= ancho_logo + SEPARACION_LOGO
        self._texto(borde, ALTO - 44, f"Equipo {p.nombre}", negrita=True, tamano=10, derecha=True)
        generado = rango.texto_hora(p.generado_ms, d.zona)
        self._texto(MARGEN, ALTO - 58, f"Rango: {d.desde} a {d.hasta} (días completos)   ·   Generado: "
                                       f"{generado[0]} {generado[1][:5]}", tamano=8, color=GRIS)
        self.c.setStrokeColorRGB(0.6, 0.6, 0.6)
        self.c.line(MARGEN, ALTO - 64, ANCHO - MARGEN, ALTO - 64)
        self._texto(MARGEN, ALTO - 80, titulo, negrita=True, tamano=10)
        self._texto(ANCHO / 2, 28, f"Página {self.pagina} de {self.total}", tamano=8, color=GRIS)
        self._texto(MARGEN, 28, "Documento protegido con contraseña", tamano=7, color=GRIS)
        self._texto(ANCHO - MARGEN, 28, "Rojo y negrita = alerta de oxígeno", tamano=7, color=ROJO, derecha=True)

    # ---- pagina 1 -------------------------------------------------------------------------------------------------
    def _logo(self) -> float:
        """Dibuja el logo de SPEAL en el extremo derecho de la cabecera de la primera pagina y devuelve su ancho (0 si no se
        pudo: el archivo falta o esta danado). Un logo nunca debe impedir un reporte."""
        try:
            from reportlab.lib.utils import ImageReader
            ancho_px, alto_px = ImageReader(str(LOGO)).getSize()
            ancho = LOGO_ALTO * ancho_px / alto_px
            self.c.drawImage(str(LOGO), ANCHO - MARGEN - ancho, ALTO - 44 - LOGO_ALTO / 2 + 4, width=ancho, height=LOGO_ALTO,
                             mask="auto")
            return ancho
        except Exception:                                  # noqa: BLE001 - archivo ausente, dañado, etc.
            return 0.0

    def portada_resumen(self) -> None:
        d, p = self.datos, self.portada
        r = d.resumen()
        self.nueva_pagina("Resumen del reporte", con_logo=True)
        y = ALTO - 104
        renglones: list[tuple[str, str, tuple]] = [
            ("Equipo", f"{p.nombre}   (ID: {p.equipo_id or 'sin definir'})", NEGRO),
            ("Rango", f"{d.desde} a {d.hasta}", NEGRO),
            ("Registros", f"{r['filas']} filas (una por intervalo de guardado, con las lecturas de los dos sensores)", NEGRO),
            ("Intervalo de guardado", _texto_intervalos(r["periodos_s"]), NEGRO)]
        for n in (1, 2):
            e = r["estadisticas"][n]
            medidas = (f"{e['n']} lecturas · mínimo {e['min']:.2f} · máximo {e['max']:.2f} · promedio {e['prom']:.2f} % O2"
                       if e["n"] else "sin lecturas en el rango")
            renglones.append((f"Sensor {n}", medidas, NEGRO))
        for n in (1, 2):
            if r["con_alerta"][n]:
                renglones.append((f"Alertas S{n}", f"{r['con_alerta'][n]} filas con alarma de oxígeno abierta (en rojo)", ROJO))
        renglones.append(("Alarmas del rango", f"{len(d.alarmas)} (detalle al final)", ROJO if d.alarmas else NEGRO))
        if d.cambios_sensor:
            renglones.append(("Estado de sensores", f"{len(d.cambios_sensor)} cambios (apagados, encendidos o sin señal; detalle al final)", NEGRO))
        if r["calidad_anomala"]:
            renglones.append(("Calidad", f"{r['calidad_anomala']} filas con una lectura de calidad no normal (marcadas con *)", NEGRO))
        if r["hora_no_confiable"]:
            renglones.append(("Hora", f"{r['hora_no_confiable']} filas con la hora sin sincronizar (marcadas con †)", NEGRO))
        if p.cadena is None:
            renglones.append(("Auditoría", "No se pudo verificar la cadena de auditoría", ROJO))
        elif p.cadena[0]:
            renglones.append(("Auditoría", "Cadena de auditoría íntegra al generar este reporte", VERDE))
        else:
            renglones.append(("Auditoría", f"CADENA ALTERADA: {p.cadena[1]} diferencia(s) al generar este reporte", ROJO))
        for rotulo, valor, color in renglones:
            self._texto(MARGEN, y, rotulo, negrita=True, tamano=9)
            self._texto(MARGEN + 130, y, valor[:105], tamano=9, color=color, negrita=color == ROJO)
            y -= 16
        y -= 8
        self._texto(MARGEN, y, "Calibraciones vigentes", negrita=True, tamano=9)
        y -= 14
        vigentes = [c for c in d.calibraciones if c["vigente"]]
        for c in vigentes[:6] or [None]:
            if c is None:
                self._texto(MARGEN + 10, y, "Ninguna registrada: se usa la calibración de fábrica del sensor.", tamano=8)
            else:
                self._texto(MARGEN + 10, y, texto_calibracion(c, d.zona), tamano=8)
            y -= 12
        y -= 14
        for linea in ("Cómo leer la tabla de lecturas:",
                      "· Una fila por intervalo de guardado; «Reg. S1» y «Reg. S2» son los números de registro de la base de datos.",
                      "· Rojo y negrita: durante ese intervalo el sensor tuvo una alarma de oxígeno BAJO o ALTO; la columna Alerta",
                      "  dice cuál y con qué umbral (el que tenía la alarma al dispararse, no el actual).",
                      "· — : el sensor no tuvo lectura en ese intervalo.   * : lectura con calidad no normal (saturada, inestable...).",
                      "· † : la hora del equipo no estaba sincronizada cuando se guardó la lectura.",
                      "· La discrepancia entre sensores no se marca. La huella SHA-256 de este archivo está en el archivo .sha256",
                      "  que se guarda a su lado y en el registro de eventos del equipo."):
            self._texto(MARGEN, y, linea, tamano=8, negrita=linea.endswith(":"))
            y -= 11

    # ---- paginas de lecturas --------------------------------------------------------------------------------------
    def _encabezado_tabla(self) -> None:
        y = ALTO - 98
        self.c.setStrokeColorRGB(0.5, 0.5, 0.5)
        for titulo, x, alineacion, x_der in COLUMNAS:
            self._texto(x_der if alineacion == "d" else x, y, titulo, negrita=True, tamano=8, derecha=alineacion == "d")
        self.c.line(MARGEN, y - 4, ANCHO - MARGEN, y - 4)

    def _fila(self, y: float, n: int, f: consulta.Fila, zona: str) -> None:
        fecha, hora = rango.texto_hora(f.ts_ms, zona)
        rojo = f.con_alerta
        color, negrita = (ROJO, True) if rojo else (NEGRO, False)
        self._texto(78, y, str(f.s1.id) if f.s1 else "—", negrita=negrita, color=color, derecha=True)
        self._texto(124, y, str(f.s2.id) if f.s2 else "—", negrita=negrita, color=color, derecha=True)
        self._texto(132, y, fecha, negrita=negrita, color=color)
        self._texto(196, y, hora + ("" if f.confiable else " †"), negrita=negrita, color=color)
        for medida, alerta, x in ((f.s1, f.alerta1, 300), (f.s2, f.alerta2, 358)):
            marca = "*" if medida is not None and medida.calidad else ""
            o2 = medida.o2 if medida is not None else None
            self._texto(x, y, _numero(o2, marca), negrita=alerta is not None, color=ROJO if alerta else NEGRO,
                        derecha=True)
        if rojo:
            partes = [f"S{n} {a}" for n, a in ((1, f.alerta1), (2, f.alerta2)) if a]
            self._texto(X_COLUMNA_ALERTA, y, " · ".join(partes), negrita=True, color=ROJO)
        if n % 5 == 4:
            self.c.setStrokeColorRGB(0.85, 0.85, 0.85)
            self.c.line(MARGEN, y - 3, ANCHO - MARGEN, y - 3)

    def lecturas(self, progreso: Callable[[int], None], cancelado: Callable[[], bool]) -> None:
        filas = self.datos.filas
        paginas = paginas_de_datos(len(filas))
        for p in range(paginas):
            self.nueva_pagina(f"Lecturas (filas {p * FILAS_POR_PAGINA + 1} a "
                              f"{min(len(filas), (p + 1) * FILAS_POR_PAGINA)} de {len(filas)})")
            self._encabezado_tabla()
            for n, f in enumerate(filas[p * FILAS_POR_PAGINA:(p + 1) * FILAS_POR_PAGINA]):
                self._fila(Y_PRIMERA_FILA - n * ALTO_FILA, n, f, self.datos.zona)
            hecho = (p + 1) * FILAS_POR_PAGINA
            if p % 8 == 0 or p == paginas - 1:
                if cancelado():
                    raise Cancelado()
                progreso(min(99, int(100 * hecho / max(1, len(filas)))))

    # ---- anexo ----------------------------------------------------------------------------------------------------
    def anexo(self) -> None:
        lineas = _lineas_anexo(self.datos)
        for p in range(math.ceil(len(lineas) / LINEAS_ANEXO_POR_PAGINA)):
            self.nueva_pagina("Alarmas y estado de los sensores")
            y = ALTO - 104
            for estilo, texto in lineas[p * LINEAS_ANEXO_POR_PAGINA:(p + 1) * LINEAS_ANEXO_POR_PAGINA]:
                if estilo == "t":
                    self._texto(MARGEN, y, texto, negrita=True, tamano=10)
                elif estilo != "s":
                    self.c.setFont("Courier-Bold" if estilo in "ae" else "Courier", 7)
                    self._color(ROJO if estilo == "a" else NEGRO)
                    self.c.drawString(MARGEN, y, texto)
                y -= 12


def dibujar(datos: consulta.DatosReporte, portada: Portada, ruta: Path, *,
            progreso: Callable[[int], None] = lambda _p: None,
            cancelado: Callable[[], bool] = lambda: False) -> int:
    """Escribe el PDF SIN cifrar en ``ruta`` y devuelve su numero de paginas.

    Raises:
        Cancelado: si ``cancelado()`` se vuelve verdadero mientras se dibuja.
        ErrorReporte: si falta reportlab.
    """
    try:
        from reportlab.pdfgen import canvas
    except ImportError as error:
        raise ErrorReporte("Falta la librería reportlab en el equipo") from error
    total = total_paginas(datos)
    lienzo = canvas.Canvas(str(ruta), pagesize=(ANCHO, ALTO), pageCompression=1, invariant=0)
    lienzo.setTitle("Reporte de lecturas de oxígeno G2")
    lienzo.setAuthor("G2")
    dibujante = _Dibujante(lienzo, portada, datos, total)
    dibujante.portada_resumen()
    dibujante.lecturas(progreso, cancelado)
    dibujante.anexo()
    lienzo.save()
    assert dibujante.pagina == total, (dibujante.pagina, total)
    return total


def cifrar(origen: Path, destino: Path, contrasena: str) -> None:
    """Cifra ``origen`` con AES-256 y deja el resultado en ``destino``; comprueba que se abre con la contrasena y que NO
    se abre sin ella.

    Raises:
        ErrorReporte: si falta pypdf, la contrasena esta vacia o la comprobacion falla.
    """
    if not contrasena:
        raise ErrorReporte("El equipo no tiene nombre: no hay contraseña para proteger el reporte")
    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.constants import UserAccessPermissions
    except ImportError as error:
        raise ErrorReporte("Falta la librería pypdf en el equipo (apt install python3-pypdf)") from error
    escritor = PdfWriter(clone_from=PdfReader(str(origen)))
    escritor.encrypt(contrasena, owner_password=secrets.token_hex(24), algorithm="AES-256",
                     permissions_flag=(UserAccessPermissions.PRINT | UserAccessPermissions.PRINT_TO_REPRESENTATION
                                       | UserAccessPermissions.EXTRACT | UserAccessPermissions.EXTRACT_TEXT_AND_GRAPHICS))
    with open(destino, "wb") as archivo:
        escritor.write(archivo)
    lector = PdfReader(str(destino))
    if not lector.is_encrypted or not lector.decrypt(contrasena):
        raise ErrorReporte("El PDF cifrado no se pudo abrir con la contraseña: se descarta")
    if len(lector.pages) != len(escritor.pages):
        raise ErrorReporte("El PDF cifrado perdió páginas: se descarta")
    sin_clave = PdfReader(str(destino))
    if sin_clave.decrypt("") != 0:                  # 0 = no se abre sin la contrasena
        raise ErrorReporte("El PDF cifrado se abre sin contraseña: se descarta")

