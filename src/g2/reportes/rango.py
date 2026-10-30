"""Rango de fechas de un reporte (D-044): dias completos, en la zona horaria del equipo.

El filtro es por DIAS ENTEROS (de las 00:00 del primer dia a las 24:00 del ultimo), sin horas. El maximo es una
semana: un reporte mas largo tardaria mucho y exigiria demasiado a la Raspberry Pi (D-044). La hora de la base es UTC;
aqui se convierte a la zona del equipo (``reporte.zona_horaria``) para saber donde empieza y termina cada dia.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_DIAS = 7                                    # un reporte cubre como maximo una semana
MAX_FILAS = 60_000                              # filas (parejas de lecturas) que se aceptan; con 15 s son ~10 dias


class ErrorRango(Exception):
    """El rango pedido no es valido; el mensaje se puede mostrar tal cual en la pantalla."""


def zona(nombre: str) -> ZoneInfo:
    try:
        return ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ErrorRango(f"Zona horaria no válida: {nombre!r}") from None


def hoy(nombre_zona: str, ahora_ms: int | None = None) -> date:
    """El dia de hoy en la zona del equipo."""
    z = zona(nombre_zona)
    if ahora_ms is None:
        return datetime.now(z).date()
    return datetime.fromtimestamp(ahora_ms / 1000, z).date()


def formato_fecha(dia: date) -> str:
    """``DD/MM/AAAA``, como se escribe y se lee en la pantalla y en el reporte."""
    return f"{dia.day:02d}/{dia.month:02d}/{dia.year:04d}"


def leer_fecha(texto: str) -> date:
    """Convierte ``DD/MM/AAAA`` o ``AAAA-MM-DD`` en fecha.

    Raises:
        ErrorRango: si el texto no es una fecha real (por ejemplo 31/02/2026).
    """
    texto = texto.strip()
    try:
        if "-" in texto:
            return date.fromisoformat(texto)
        dia, mes, anio = texto.split("/")
        return date(int(anio), int(mes), int(dia))
    except (ValueError, TypeError):
        raise ErrorRango("Fecha no válida (use día/mes/año)") from None


def validar(desde: date, hasta: date, hoy_: date) -> int:
    """Verifica el rango y devuelve el numero de dias que cubre.

    Raises:
        ErrorRango: con el motivo en lenguaje claro.
    """
    if hasta > hoy_ or desde > hoy_:
        raise ErrorRango("No hay datos de fechas futuras")
    if desde > hasta:
        raise ErrorRango("La fecha inicial es posterior a la final")
    dias = (hasta - desde).days + 1
    if dias > MAX_DIAS:
        raise ErrorRango(f"Máximo {MAX_DIAS} días por reporte")
    return dias


def limites_ms(desde: date, hasta: date, nombre_zona: str) -> tuple[int, int]:
    """``(inicio_ms, fin_ms)`` en UTC: desde las 00:00 de ``desde`` hasta las 00:00 del dia siguiente a ``hasta``
    (el fin NO se incluye). Respeta los cambios de hora de la zona."""
    z = zona(nombre_zona)
    inicio = datetime.combine(desde, time.min, tzinfo=z)
    fin = datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=z)
    return int(inicio.timestamp() * 1000), int(fin.timestamp() * 1000)


def texto_hora(ms: int, nombre_zona: str) -> tuple[str, str]:
    """``(fecha, hora)`` locales de un instante UTC: ``("27/10/2026", "10:07:15")``."""
    momento = datetime.fromtimestamp(ms / 1000, zona(nombre_zona))
    return formato_fecha(momento.date()), momento.strftime("%H:%M:%S")
