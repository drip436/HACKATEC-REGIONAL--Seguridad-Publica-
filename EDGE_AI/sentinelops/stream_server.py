"""Servidor HTTP del video anotado (MJPEG) y del estado del sensor.

Rutas:
  /stream.mjpg   video anotado en vivo; un <img src> del navegador lo reproduce.
  /snapshot.jpg  el último frame anotado.
  /status.json   estado del sensor (nivel del semáforo, regla, personas...).

Si hay token configurado se exige en `?token=` (un <img> no envía headers).
"""

from __future__ import annotations

import hmac
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import cv2
import numpy as np

LOGGER = logging.getLogger(__name__)

_FRONTERA = "sentinelframe"
_MAX_CLIENTES = 8


class FramePublisher:
    """Último frame anotado (ya en JPEG) y estado, compartidos con los clientes HTTP."""

    def __init__(self, jpeg_quality: int = 75, max_fps: float = 12.0) -> None:
        self._quality = jpeg_quality
        self._intervalo = 1.0 / max_fps if max_fps > 0 else 0.0
        self._cond = threading.Condition()
        self._jpeg: bytes | None = None
        self._seq = 0
        self._ultimo_publicado = 0.0
        self._estado: dict[str, Any] = {"en_linea": False}
        self._clientes = 0

    def publicar(self, frame: np.ndarray) -> None:
        """Codifica a JPEG como máximo a `max_fps` (ahorra CPU y ancho de banda)."""
        ahora = time.monotonic()
        sin_clientes = self._clientes == 0 and self._jpeg is not None
        if ahora - self._ultimo_publicado < (1.0 if sin_clientes else self._intervalo):
            return
        ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self._quality])
        if not ok:
            return
        with self._cond:
            self._jpeg = buffer.tobytes()
            self._seq += 1
            self._ultimo_publicado = ahora
            self._cond.notify_all()

    def actualizar_estado(self, **campos: Any) -> None:
        with self._cond:
            self._estado = {**self._estado, **campos, "actualizado": time.time()}

    def estado(self) -> dict[str, Any]:
        with self._cond:
            return {**self._estado, "clientes": self._clientes}

    def ultimo(self) -> bytes | None:
        with self._cond:
            return self._jpeg

    def esperar(self, seq: int, timeout: float = 5.0) -> tuple[int, bytes | None]:
        with self._cond:
            self._cond.wait_for(lambda: self._seq != seq, timeout=timeout)
            return self._seq, self._jpeg

    def conectar(self) -> bool:
        with self._cond:
            if self._clientes >= _MAX_CLIENTES:
                return False
            self._clientes += 1
            return True

    def desconectar(self) -> None:
        with self._cond:
            self._clientes -= 1


class StreamServer:
    def __init__(self, publisher: FramePublisher, port: int, token: str | None, host: str = "127.0.0.1") -> None:
        self._publisher = publisher
        self._token = token
        self._httpd = ThreadingHTTPServer((host, port), self._handler())
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="stream-http", daemon=True)
        self.port = self._httpd.server_address[1]

    def start(self) -> None:
        self._thread.start()
        LOGGER.info(
            "Video anotado en http://localhost:%d/stream.mjpg%s",
            self.port,
            "?token=…" if self._token else " (sin token)",
        )

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        publisher = self._publisher
        token = self._token

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802 (API de http.server)
                partes = urlsplit(self.path)
                if token is not None:
                    recibido = (parse_qs(partes.query).get("token") or [""])[0]
                    if not hmac.compare_digest(recibido.encode(), token.encode()):
                        self._json(401, {"error": "token inválido o ausente"})
                        return
                if partes.path == "/stream.mjpg":
                    self._mjpeg()
                elif partes.path == "/snapshot.jpg":
                    jpeg = publisher.ultimo()
                    if jpeg is None:
                        self._json(503, {"error": "aún no hay video"})
                    else:
                        self._enviar(200, "image/jpeg", jpeg)
                elif partes.path == "/status.json":
                    self._json(200, publisher.estado())
                else:
                    self._json(404, {"error": "ruta no encontrada"})

            def _mjpeg(self) -> None:
                if not publisher.conectar():
                    self._json(503, {"error": "demasiados clientes"})
                    return
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={_FRONTERA}")
                    self.send_header("Cache-Control", "no-store, private")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    seq = 0
                    while True:
                        seq, jpeg = publisher.esperar(seq)
                        if jpeg is None:
                            continue
                        self.wfile.write(
                            f"--{_FRONTERA}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n\r\n".encode()
                        )
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass
                finally:
                    publisher.desconectar()
                    self.close_connection = True

            def _json(self, status: int, cuerpo: dict[str, Any]) -> None:
                self._enviar(status, "application/json", json.dumps(cuerpo, ensure_ascii=False).encode())

            def _enviar(self, status: int, tipo: str, cuerpo: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(cuerpo)))
                self.send_header("Cache-Control", "no-store, private")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(cuerpo)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                LOGGER.debug("stream %s - %s", self.address_string(), format % args)

        return Handler
