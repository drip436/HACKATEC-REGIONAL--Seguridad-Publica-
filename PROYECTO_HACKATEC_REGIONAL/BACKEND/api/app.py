from __future__ import annotations

from fastapi import APIRouter, FastAPI

from ..config import get_settings
from ..realtime import get_manager
from .manejadores_error import registrar_manejadores
from .rutas_auditoria import router as auditoria_router
from .rutas_despachos import router as despachos_router
from .rutas_eventos import router as eventos_router
from .rutas_interoperabilidad import router as interop_router
from .rutas_sensores import router as sensores_router
from .rutas_websocket import router as ws_router

DESCRIPCION = """
API central de **SentinelOps** — monitoreo inteligente con despacho Human-in-the-loop.

Flujo: `POST /eventos` (Edge AI) → `/ws/alertas` (monitores) →
`POST /eventos/{id}/validar` (operador) → `POST /despachos` (federación X-Road) →
`GET /auditoria` (gobernanza).

Privacidad por diseño: solo se aceptan y transmiten metadatos de detección.
"""


def crear_api() -> FastAPI:
    settings = get_settings()
    api = FastAPI(
        title="SentinelOps API",
        version="1.0.0",
        description=DESCRIPCION,
        openapi_tags=[
            {"name": "Eventos", "description": "Ingesta desde sensores y validación humana."},
            {"name": "Despachos", "description": "Órdenes hacia dependencias externas."},
            {"name": "Interoperabilidad X-Road", "description": "Nodo federado simulado."},
            {"name": "Auditoría", "description": "Bitácora inmutable encadenada por SHA-256."},
            {"name": "Sensores", "description": "Inventario de cámaras y sensores."},
            {"name": "Sistema", "description": "Salud del servicio."},
        ],
    )
    registrar_manejadores(api)

    v1 = APIRouter(prefix=settings.api_prefix)
    for router in (eventos_router, despachos_router, interop_router, auditoria_router, sensores_router):
        v1.include_router(router)

    @v1.get("/health", tags=["Sistema"])
    async def health() -> dict[str, object]:
        return {"estado": "ok", "monitores_ws": get_manager().total}

    api.include_router(v1)
    api.include_router(ws_router)
    return api
