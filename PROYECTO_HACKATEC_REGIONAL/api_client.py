"""Única capa que conoce la API de Dev 2 (REST + WebSocket).

Variables de entorno:
  SENTINEL_MOCK     "1" (por defecto) usa datos simulados; "0" llama a la API real.
  SENTINEL_API_URL  Base de la API de Dev 2. Reflex ya ocupa el puerto 8000.
"""

import asyncio
import hashlib
import json
import os
import random
from collections.abc import AsyncIterator
from datetime import datetime

import httpx
import websockets

from . import mock

MOCK = os.environ.get("SENTINEL_MOCK", "1") != "0"
API_URL = os.environ.get("SENTINEL_API_URL", "http://localhost:8001").rstrip("/")
WS_URL = API_URL.replace("http", "ws", 1) + "/ws/alertas"

_TIMEOUT = 5.0
_REINTENTO_WS = 3.0


async def _get(ruta: str, **params) -> list[dict]:
    async with httpx.AsyncClient(base_url=API_URL, timeout=_TIMEOUT) as cliente:
        respuesta = await cliente.get(ruta, params=params)
        respuesta.raise_for_status()
        return respuesta.json()


async def _post(ruta: str, cuerpo: dict) -> dict:
    async with httpx.AsyncClient(base_url=API_URL, timeout=_TIMEOUT) as cliente:
        respuesta = await cliente.post(ruta, json=cuerpo)
        respuesta.raise_for_status()
        return respuesta.json()


async def obtener_camaras() -> list[dict]:
    return list(mock.CAMARAS) if MOCK else await _get("/camaras")


async def obtener_eventos() -> list[dict]:
    return mock.eventos_iniciales() if MOCK else await _get("/eventos")


async def obtener_historico() -> list[dict]:
    return mock.historico_sintetico() if MOCK else await _get("/analitica/historico")


async def obtener_auditoria() -> list[dict]:
    return [] if MOCK else await _get("/auditoria")


def _ahora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


async def confirmar(evento_id: str, operador: str, destino: str) -> dict:
    """Confirma y despacha. Devuelve al menos `folio` y `timestamp`."""
    if not MOCK:
        return await _post(f"/eventos/{evento_id}/confirmar", {"operador_id": operador, "destino": destino})
    await asyncio.sleep(0.6)
    timestamp = _ahora()
    huella = hashlib.sha256(f"{evento_id}|{operador}|{destino}|{timestamp}".encode()).hexdigest()
    return {"folio": f"XRD-{huella[:10].upper()}", "timestamp": timestamp}


async def descartar(evento_id: str, operador: str, motivo: str) -> dict:
    if not MOCK:
        return await _post(f"/eventos/{evento_id}/descartar", {"operador_id": operador, "motivo": motivo})
    await asyncio.sleep(0.3)
    return {"timestamp": _ahora()}


async def flujo_alertas() -> AsyncIterator[tuple[str, dict | str]]:
    """Emite ("estado", texto) al cambiar la conexión y ("alerta", evento) por cada alerta."""
    if MOCK:
        yield "estado", "Simulado"
        while True:
            await asyncio.sleep(random.uniform(8, 16))
            yield "alerta", mock.generar_evento()

    while True:
        try:
            async with websockets.connect(WS_URL) as ws:
                yield "estado", "Conectado"
                async for mensaje in ws:
                    yield "alerta", json.loads(mensaje)
        except (OSError, websockets.WebSocketException, json.JSONDecodeError):
            pass
        yield "estado", "Reconectando"
        await asyncio.sleep(_REINTENTO_WS)
