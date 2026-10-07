"""Validación previa de una cámara IP antes de lanzar el sensor.

Una URL mal escrita (por ejemplo `http://192.168.16.38`, sin puerto ni ruta) hace que
OpenCV se quede abierto ~30 s sin avisar. Aquí se completa la URL con los puertos
habituales de las apps de teléfono y se prueba con timeouts cortos, de modo que el
panel recibe un error claro en unos segundos y el sensor solo se lanza si la cámara
ya respondió.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..errores import CamaraInaccesible

LOGGER = logging.getLogger("sentinelops.fuente")

_CONECTAR_S = 3.0
_LEER_S = 4.0
# Apps de teléfono habituales: IP Webcam (8080) y DroidCam (4747).
_PUERTOS_Y_RUTAS = ((8080, "/video"), (4747, "/video"), (8080, "/videofeed"))
_TIPOS_VIDEO = ("multipart/", "image/", "video/")
_TIPOS_HLS = ("application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl", "audio/x-mpegurl")


@dataclass(frozen=True, slots=True)
class Prueba:
    url: str
    ok: bool
    motivo: str = ""


def candidatas(url: str) -> list[str]:
    """URLs a probar, de más a menos probable.

    - Solo el host (`http://192.168.1.50`): puertos y rutas de IP Webcam / DroidCam.
    - Host y puerto sin ruta: se agrega `/video`.
    - URL completa: tal cual.
    """
    partes = urlsplit(url)
    if partes.scheme not in ("http", "https"):
        return [url]
    sin_ruta = partes.path in ("", "/") and not partes.query
    if partes.port is None and sin_ruta:
        host = partes.netloc
        return [urlunsplit((partes.scheme, f"{host}:{puerto}", ruta, "", "")) for puerto, ruta in _PUERTOS_Y_RUTAS]
    if sin_ruta:
        return [urlunsplit((partes.scheme, partes.netloc, "/video", "", ""))]
    return [url]


def _visible(url: str) -> str:
    """URL sin usuario ni clave, para mensajes y bitácora."""
    partes = urlsplit(url)
    host = partes.hostname or ""
    netloc = f"{host}:{partes.port}" if partes.port else host
    return urlunsplit((partes.scheme, netloc, partes.path, partes.query, partes.fragment))


async def probar(url: str) -> Prueba:
    """¿Responde la URL con video? Timeouts cortos; nunca bloquea más de ~7 s."""
    partes = urlsplit(url)
    if partes.scheme in ("rtsp", "rtsps"):
        return await _probar_tcp(url, partes.hostname or "", partes.port or 554)

    limites = httpx.Timeout(connect=_CONECTAR_S, read=_LEER_S, write=_CONECTAR_S, pool=_CONECTAR_S)
    try:
        async with httpx.AsyncClient(timeout=limites, follow_redirects=True) as cliente:
            async with cliente.stream("GET", url) as respuesta:
                if respuesta.status_code in (401, 403):
                    return Prueba(url, False, "la cámara pide usuario y contraseña (usa http://usuario:clave@ip:puerto/video)")
                if respuesta.status_code != 200:
                    return Prueba(url, False, f"respondió HTTP {respuesta.status_code}")
                tipo = respuesta.headers.get("content-type", "").lower()
                if not (tipo.startswith(_TIPOS_VIDEO) or tipo.startswith(_TIPOS_HLS)):
                    return Prueba(url, False, f"respondió, pero no es video ({tipo or 'sin tipo'})")
                # Con el tipo correcto basta con recibir los primeros bytes.
                async for _ in respuesta.aiter_bytes(chunk_size=2048):
                    return Prueba(url, True)
                return Prueba(url, False, "la conexión se cerró sin enviar video")
    except httpx.ConnectTimeout:
        return Prueba(url, False, "no hay respuesta (tiempo agotado)")
    except httpx.ReadTimeout:
        return Prueba(url, False, "se conectó pero no envía video")
    except httpx.ConnectError:
        return Prueba(url, False, "conexión rechazada o equipo inalcanzable")
    except httpx.HTTPError as error:
        return Prueba(url, False, error.__class__.__name__)


async def _probar_tcp(url: str, host: str, puerto: int) -> Prueba:
    try:
        _, escritor = await asyncio.wait_for(asyncio.open_connection(host, puerto), timeout=_CONECTAR_S)
    except (TimeoutError, OSError):
        return Prueba(url, False, "no hay respuesta (tiempo agotado o conexión rechazada)")
    escritor.close()
    return Prueba(url, True)


async def resolver(url: str) -> str:
    """URL alcanzable (completada si hacía falta) o `CamaraInaccesible` con un mensaje claro.

    Las candidatas se prueban a la vez: el peor caso es un solo timeout de conexión.
    """
    opciones = candidatas(url)
    resultados = await asyncio.gather(*(probar(opcion) for opcion in opciones))
    for prueba in resultados:
        if prueba.ok:
            if prueba.url != url:
                LOGGER.info("URL completada: %s -> %s", _visible(url), _visible(prueba.url))
            return prueba.url

    detalle = "; ".join(f"{_visible(p.url)}: {p.motivo}" for p in resultados)
    ayuda = "Revisa que el teléfono y esta computadora estén en la misma red Wi-Fi y que la app esté transmitiendo."
    raise CamaraInaccesible(
        f"No se pudo abrir la cámara ({detalle}). {ayuda}",
        detalle={"probadas": [_visible(o) for o in opciones]},
    )
