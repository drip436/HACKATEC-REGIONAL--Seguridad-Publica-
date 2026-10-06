from __future__ import annotations

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..config import get_settings
from ..realtime import get_manager
from ..utils.crypto import comparar_seguro

router = APIRouter(tags=["Tiempo real"])


@router.websocket("/ws/alertas")
async def ws_alertas(websocket: WebSocket, token: str | None = Query(default=None)) -> None:
    esperado = get_settings().operador_api_key
    if esperado is not None and not comparar_seguro(token, esperado):
        await websocket.close(code=1008, reason="Token de operador inválido")
        return

    manager = get_manager()
    if not await manager.conectar(websocket):
        return
    try:
        await manager.enviar(websocket, "conexion.establecida", {"monitores_activos": manager.total})
        while True:
            # El canal es de bajada; el cliente solo envía "ping" como keep-alive.
            if (await websocket.receive_text()).strip().lower() == "ping":
                await manager.enviar(websocket, "pong", {})
    except WebSocketDisconnect:
        pass
    finally:
        await manager.desconectar(websocket)
