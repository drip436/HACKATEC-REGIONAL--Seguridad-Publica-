from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket
from pydantic import BaseModel

from ..schemas import MensajeWS
from ..schemas.comunes import TipoMensajeWS
from ..utils.tiempo import ahora_utc

logger = logging.getLogger("sentinelops.ws")


class ConnectionManager:
    """Difusión a todas las consolas de monitoreo conectadas.

    El envío es concurrente y con timeout por socket: un monitor lento o caído
    no debe retrasar la alerta para los demás."""

    def __init__(self, max_conexiones: int, timeout_envio_s: float = 2.0) -> None:
        self._conexiones: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._max = max_conexiones
        self._timeout = timeout_envio_s

    @property
    def total(self) -> int:
        return len(self._conexiones)

    async def conectar(self, websocket: WebSocket) -> bool:
        async with self._lock:
            if len(self._conexiones) >= self._max:
                await websocket.close(code=1013, reason="Capacidad máxima de monitores alcanzada")
                return False
            await websocket.accept()
            self._conexiones.add(websocket)
        logger.info("Monitor conectado (%d activos).", self.total)
        return True

    async def desconectar(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._conexiones.discard(websocket)
        logger.info("Monitor desconectado (%d activos).", self.total)

    async def enviar(self, websocket: WebSocket, tipo: TipoMensajeWS, data: dict[str, Any] | BaseModel) -> None:
        await websocket.send_text(_mensaje(tipo, data))

    async def broadcast(self, tipo: TipoMensajeWS, data: dict[str, Any] | BaseModel) -> int:
        texto = _mensaje(tipo, data)
        async with self._lock:
            destinos = list(self._conexiones)
        if not destinos:
            return 0
        resultados = await asyncio.gather(*(self._enviar_texto(ws, texto) for ws in destinos), return_exceptions=True)
        caidos = [ws for ws, r in zip(destinos, resultados, strict=True) if isinstance(r, BaseException)]
        if caidos:
            async with self._lock:
                self._conexiones.difference_update(caidos)
            logger.warning("Se descartaron %d monitores sin respuesta.", len(caidos))
        return len(destinos) - len(caidos)

    async def _enviar_texto(self, websocket: WebSocket, texto: str) -> None:
        await asyncio.wait_for(websocket.send_text(texto), timeout=self._timeout)


def _mensaje(tipo: TipoMensajeWS, data: dict[str, Any] | BaseModel) -> str:
    cuerpo = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    return MensajeWS(tipo=tipo, emitido_en=ahora_utc(), data=cuerpo).model_dump_json()
