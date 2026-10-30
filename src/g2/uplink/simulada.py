"""Plataforma SIMULADA para probar g2-uplink sin tocar la plataforma real (D-046).

Cumple el contrato de CONTRATO_PLATAFORMA.md en lo minimo: comprueba el secreto, acepta o rechaza los registros por
tabla, guarda en memoria lo que recibe y permite provocar fallos. Sirve para las pruebas automaticas y para probar el
servicio en la Pi a mano:

    python3 -m g2.uplink.simulada --puerto 8099 --secreto <el-mismo-que-guardo-plataforma-credencial> --equipo ANZD-PRUEBA

y en el equipo:  python3 -m g2.ctl config-fijar plataforma.url http://127.0.0.1:8099
(``http`` solo se acepta hacia 127.0.0.1; la plataforma real exige https).
"""

from __future__ import annotations

import argparse
import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from g2.uplink.cliente import RUTA_LOTES, RUTA_VIVO


class PlataformaSimulada:
    """Servidor HTTP en un hilo. Atributos para inspeccionar y provocar casos:

    ``registros``: ``{(tabla, id): (rev, datos)}`` lo guardado; ``vivos``: las fotos recibidas; ``peticiones``: cuantas
    llegaron; ``rechazar_tablas``: tablas que se rechazan; ``reintentar_tablas``: tablas que piden reintento;
    ``fallar``: cuantas respuestas siguientes seran HTTP ``codigo_fallo``; ``maximo``: registros maximos por lote (413 si se pasa).
    """

    def __init__(self, secreto: str, equipo_id: str, puerto: int = 0) -> None:
        self.secreto, self.equipo_id = secreto, equipo_id
        self.registros: dict[tuple[str, int], tuple[int, dict]] = {}
        self.vivos: list[dict] = []
        self.lotes: list[list[dict]] = []
        self.peticiones = 0
        self.rechazar_tablas: set[str] = set()
        self.reintentar_tablas: set[str] = set()
        self.fallar = 0
        self.codigo_fallo = 503
        self.maximo: int | None = None
        self.cabeceras: list[dict] = []
        simulada = self

        class Atiende(BaseHTTPRequestHandler):
            def do_POST(self):                                    # noqa: N802 (nombre que exige http.server)
                simulada.peticiones += 1
                largo = int(self.headers.get("Content-Length") or 0)
                crudo = self.rfile.read(largo)
                simulada.cabeceras.append({k.lower(): v for k, v in self.headers.items()})
                if simulada.fallar > 0:
                    simulada.fallar -= 1
                    return self._responder(simulada.codigo_fallo, {"error": "simulado"})
                if self.headers.get("Authorization") != f"Bearer {simulada.secreto}" \
                        or self.headers.get("X-G2-Equipo") != simulada.equipo_id:
                    return self._responder(401, {"error": "credencial"})
                try:
                    if self.headers.get("Content-Encoding") == "gzip":
                        crudo = gzip.decompress(crudo)
                    cuerpo = json.loads(crudo)
                except (OSError, ValueError):
                    return self._responder(400, {"error": "cuerpo"})
                if cuerpo.get("equipo_id") != simulada.equipo_id:
                    return self._responder(401, {"error": "equipo"})
                if self.path == RUTA_VIVO:
                    simulada.vivos.append(cuerpo)
                    return self._responder(200, {"ok": True})
                if self.path == RUTA_LOTES:
                    registros = cuerpo.get("registros") or []
                    if simulada.maximo is not None and len(registros) > simulada.maximo:
                        return self._responder(413, {"error": "lote grande"})
                    simulada.lotes.append(registros)
                    resultados = []
                    for r in registros:
                        if r["tabla"] in simulada.rechazar_tablas:
                            resultados.append({"tabla": r["tabla"], "id": r["id"], "estado": "rechazado",
                                               "motivo": "datos invalidos (simulado)"})
                        elif r["tabla"] in simulada.reintentar_tablas:
                            resultados.append({"tabla": r["tabla"], "id": r["id"], "estado": "reintentar",
                                               "motivo": "ocupada (simulado)"})
                        else:
                            actual = simulada.registros.get((r["tabla"], r["id"]))
                            if actual is None or r["rev"] >= actual[0]:
                                simulada.registros[(r["tabla"], r["id"])] = (r["rev"], r["datos"])
                            resultados.append({"tabla": r["tabla"], "id": r["id"], "rev": r["rev"], "estado": "ok"})
                    return self._responder(200, {"lote_id": cuerpo.get("lote_id"), "resultados": resultados})
                return self._responder(404, {"error": "ruta"})

            def _responder(self, codigo: int, cuerpo: dict) -> None:
                datos = json.dumps(cuerpo).encode("utf-8")
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)

            def log_message(self, *_):                            # en silencio
                pass

        self._servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Atiende)
        self.puerto = self._servidor.server_address[1]
        self.url = f"http://127.0.0.1:{self.puerto}"
        self._hilo = threading.Thread(target=self._servidor.serve_forever, daemon=True)

    def iniciar(self) -> "PlataformaSimulada":
        self._hilo.start()
        return self

    def detener(self) -> None:
        self._servidor.shutdown()
        self._servidor.server_close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Plataforma simulada para probar g2-uplink")
    ap.add_argument("--puerto", type=int, default=8099)
    ap.add_argument("--secreto", required=True)
    ap.add_argument("--equipo", required=True)
    args = ap.parse_args()
    simulada = PlataformaSimulada(args.secreto, args.equipo, args.puerto).iniciar()
    print(f"Plataforma simulada en {simulada.url} (equipo {args.equipo}). Ctrl+C para terminar.")
    try:
        while True:
            threading.Event().wait(5)
            print(f"  {simulada.peticiones} peticiones, {len(simulada.registros)} registros guardados, "
                  f"{len(simulada.vivos)} fotos en vivo")
    except KeyboardInterrupt:
        simulada.detener()


if __name__ == "__main__":
    main()
