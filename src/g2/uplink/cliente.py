"""Cliente HTTPS de la plataforma (contrato en CONTRATO_PLATAFORMA.md).

Reglas de seguridad (D-042):
  * solo ``https`` con el certificado VERIFICADO (nunca ``verify=False``); ``http`` unicamente hacia el propio equipo
    (127.0.0.1 / localhost), para probar con la plataforma simulada;
  * el secreto viaja solo en la cabecera ``Authorization`` y NO se sigue ninguna redireccion (un servidor desviado no
    recibe el secreto);
  * ningun mensaje de error incluye el secreto ni la cabecera.

Los errores se separan por lo que el servicio debe HACER: reintentar mas tarde (``SinEnlace``), dejar de insistir hasta que
alguien corrija la credencial (``CredencialRechazada``), achicar el lote (``LoteDemasiadoGrande``) o no fiarse de la
respuesta (``ErrorProtocolo``). Un registro solo se rechaza si la plataforma lo dice, registro por registro.
"""

from __future__ import annotations

import gzip
import json
import uuid
from typing import Any
from urllib.parse import urlsplit

RUTA_LOTES = "/api/g2/v1/lotes"
RUTA_VIVO = "/api/g2/v1/vivo"
COMPRIMIR_DESDE = 1024                       # bytes: por debajo no vale la pena
ESTADOS_RESULTADO = ("ok", "rechazado", "reintentar")
MAX_ESPERA_S = 3600                          # tope de lo que la plataforma puede pedir esperar (Retry-After)


class ErrorEnvio(Exception):
    """Base de los errores de envio. ``espera_s``: cuanto pidio esperar la plataforma, si lo dijo."""

    def __init__(self, mensaje: str, espera_s: float | None = None) -> None:
        super().__init__(mensaje)
        self.espera_s = espera_s


class SinEnlace(ErrorEnvio):
    """No hubo respuesta util (sin red, tiempo agotado, plataforma caida o saturada): reintentar mas tarde."""


class CredencialRechazada(ErrorEnvio):
    """La plataforma no acepta el identificador o el secreto del equipo."""


class LoteDemasiadoGrande(ErrorEnvio):
    """La plataforma no acepta un lote tan grande."""


class ErrorProtocolo(ErrorEnvio):
    """Respondio algo que no se entiende o que no corresponde (otro codigo HTTP, JSON invalido, lote ajeno)."""


def validar_url(url: str) -> str:
    """La direccion base sin barra final, o ``ValueError`` si no es segura."""
    partes = urlsplit(url.strip())
    if not partes.hostname or partes.username or partes.password or partes.query or partes.fragment:
        raise ValueError("la direccion de la plataforma no es valida")
    if partes.scheme == "https":
        pass
    elif partes.scheme == "http" and partes.hostname in ("127.0.0.1", "localhost", "::1"):
        pass
    else:
        raise ValueError("la plataforma debe usar https (http solo hacia el propio equipo)")
    return f"{partes.scheme}://{partes.netloc}{partes.path.rstrip('/')}"


class ClientePlataforma:
    def __init__(self, url: str, equipo_id: str, secreto: str, *, version_sw: str = "", sesion=None,
                 tiempo_s: tuple[float, float] = (5.0, 20.0)) -> None:
        """``sesion``: algo con ``post`` como ``requests.Session`` (las pruebas pasan una falsa)."""
        self.base = validar_url(url)
        self.equipo_id = equipo_id
        self._secreto = secreto
        self.version_sw = version_sw
        self.tiempo_s = tiempo_s
        if sesion is None:
            import requests                                   # la libreria solo hace falta si de verdad se envia
            sesion = requests.Session()
        self._sesion = sesion

    def __repr__(self) -> str:                                # nunca muestra el secreto, ni en un registro de errores
        return f"ClientePlataforma({self.base!r}, {self.equipo_id!r})"

    # ------------------------------------------------------------------------------------------------- llamadas
    def enviar_lote(self, registros: list[dict]) -> dict[tuple[str, int], tuple[str, str | None, int | None]]:
        """Envia un lote. Devuelve ``{(tabla, id): (estado, motivo, rev)}`` con lo que la plataforma contesto por registro;
        ``estado`` es ``ok``, ``rechazado`` o ``reintentar``. Lo que no contesto no aparece (queda pendiente)."""
        lote_id = str(uuid.uuid4())
        cuerpo = {"equipo_id": self.equipo_id, "lote_id": lote_id, "registros": registros}
        respuesta = self._enviar(RUTA_LOTES, cuerpo, lote_id)
        if not isinstance(respuesta, dict) or respuesta.get("lote_id") != lote_id \
                or not isinstance(respuesta.get("resultados"), list):
            raise ErrorProtocolo("la respuesta de la plataforma no corresponde al lote enviado")
        resultados: dict[tuple[str, int], tuple[str, str | None, int | None]] = {}
        for r in respuesta["resultados"]:
            if not isinstance(r, dict) or not isinstance(r.get("tabla"), str) or not isinstance(r.get("id"), int) \
                    or r.get("estado") not in ESTADOS_RESULTADO:
                continue                                           # un resultado mal formado se ignora: queda pendiente
            rev = r.get("rev") if isinstance(r.get("rev"), int) and not isinstance(r.get("rev"), bool) else None
            motivo = r.get("motivo") if isinstance(r.get("motivo"), str) else None
            resultados[(r["tabla"], r["id"])] = (r["estado"], motivo, rev)
        return resultados

    def enviar_vivo(self, instantanea: dict) -> None:
        """Envia la foto del valor actual (se muestra en vivo; no es durable y no se reintenta)."""
        self._enviar(RUTA_VIVO, {"equipo_id": self.equipo_id, **instantanea}, None)

    # ------------------------------------------------------------------------------------------------- HTTP
    def _enviar(self, ruta: str, cuerpo: dict, lote_id: str | None) -> Any:
        datos = json.dumps(cuerpo, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        cabeceras = {"Authorization": f"Bearer {self._secreto}", "X-G2-Equipo": self.equipo_id,
                     "Content-Type": "application/json; charset=utf-8", "Accept": "application/json",
                     "User-Agent": f"g2-uplink/{self.version_sw or 'sin-version'}"}
        if lote_id:
            cabeceras["X-G2-Lote"] = lote_id
        if len(datos) >= COMPRIMIR_DESDE:
            datos = gzip.compress(datos, compresslevel=6, mtime=0)
            cabeceras["Content-Encoding"] = "gzip"
        try:
            r = self._sesion.post(self.base + ruta, data=datos, headers=cabeceras, timeout=self.tiempo_s,
                                  allow_redirects=False, verify=True)
        except Exception as error:                                # sin red, DNS, TLS, tiempo agotado...
            raise SinEnlace(f"sin conexion con la plataforma ({type(error).__name__})") from None
        codigo = r.status_code
        if codigo in (200, 201):
            try:
                return r.json()
            except ValueError:
                raise ErrorProtocolo("la plataforma no contesto JSON") from None
        if codigo in (401, 403):
            raise CredencialRechazada(f"la plataforma rechazo la credencial del equipo (HTTP {codigo})")
        if codigo == 413:
            raise LoteDemasiadoGrande("la plataforma no acepta un lote tan grande")
        if codigo in (408, 429) or codigo >= 500:
            raise SinEnlace(f"la plataforma no puede atender ahora (HTTP {codigo})", _espera(r))
        if 300 <= codigo < 400:
            raise ErrorProtocolo(f"la plataforma redirige (HTTP {codigo}); no se sigue para no enviar el secreto a otro lado")
        raise ErrorProtocolo(f"la plataforma contesto HTTP {codigo}")


def _espera(respuesta) -> float | None:
    """``Retry-After`` en segundos (solo la forma numerica), con un tope."""
    try:
        valor = float(respuesta.headers.get("Retry-After", ""))
    except (ValueError, AttributeError):
        return None
    return min(max(valor, 0.0), MAX_ESPERA_S)
