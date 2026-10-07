from __future__ import annotations

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from ..schemas import RESPUESTAS_ERROR, CamaraVinculadaOut, VinculacionIn
from ..services import fuente_video
from ..services.vinculacion import SUPERVISOR, VIDEO_DEMO
from .dependencias import IpCliente, OperadorAutenticado

router = APIRouter(
    prefix="/camara-vinculada", tags=["Cámara vinculada"], dependencies=[OperadorAutenticado], responses=RESPUESTAS_ERROR
)


@router.get("", response_model=CamaraVinculadaOut)
async def estado_camara() -> CamaraVinculadaOut:
    # Sin locks ni E/S: es seguro llamarlo desde el bucle de eventos (el panel lo sondea).
    return SUPERVISOR.estado()


@router.post("", response_model=CamaraVinculadaOut)
async def vincular_camara(datos: VinculacionIn, ip: IpCliente) -> CamaraVinculadaOut:
    """Prueba la cámara (completa la URL si solo trae la IP) y, si responde, lanza el
    sensor Edge AI sobre ella. Si no responde devuelve 422 en pocos segundos y la cámara
    que estuviera vinculada sigue funcionando."""
    fuente = str(VIDEO_DEMO) if datos.demo else await fuente_video.resolver(str(datos.url))
    return await run_in_threadpool(SUPERVISOR.vincular, datos, fuente, operador="api:operador", ip_origen=ip)


@router.delete("", response_model=CamaraVinculadaOut)
async def desvincular_camara(ip: IpCliente) -> CamaraVinculadaOut:
    return await run_in_threadpool(SUPERVISOR.desvincular, operador="api:operador", ip_origen=ip)
