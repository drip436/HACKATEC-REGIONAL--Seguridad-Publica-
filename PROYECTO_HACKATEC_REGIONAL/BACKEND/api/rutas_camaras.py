from __future__ import annotations

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from ..schemas import RESPUESTAS_ERROR, CamaraVinculadaOut, VinculacionIn
from ..services.vinculacion import SUPERVISOR
from .dependencias import IpCliente, OperadorAutenticado

router = APIRouter(
    prefix="/camara-vinculada", tags=["Cámara vinculada"], dependencies=[OperadorAutenticado], responses=RESPUESTAS_ERROR
)


@router.get("", response_model=CamaraVinculadaOut)
async def estado_camara() -> CamaraVinculadaOut:
    return SUPERVISOR.estado()


@router.post("", response_model=CamaraVinculadaOut)
async def vincular_camara(datos: VinculacionIn, ip: IpCliente) -> CamaraVinculadaOut:
    """Lanza el sensor Edge AI sobre la cámara indicada (reemplaza la anterior)."""
    return await run_in_threadpool(SUPERVISOR.vincular, datos, operador="api:operador", ip_origen=ip)


@router.delete("", response_model=CamaraVinculadaOut)
async def desvincular_camara(ip: IpCliente) -> CamaraVinculadaOut:
    return await run_in_threadpool(SUPERVISOR.desvincular, operador="api:operador", ip_origen=ip)
