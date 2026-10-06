from __future__ import annotations

from fastapi import APIRouter, status
from starlette.concurrency import run_in_threadpool

from ..schemas import RESPUESTAS_ERROR, SensorIn, SensorOut
from ..services import sensores
from .dependencias import IpCliente, OperadorAutenticado

router = APIRouter(prefix="/sensores", tags=["Sensores"], responses=RESPUESTAS_ERROR)


@router.post("", response_model=SensorOut, status_code=status.HTTP_201_CREATED, dependencies=[OperadorAutenticado])
async def registrar_sensor(datos: SensorIn, ip: IpCliente) -> SensorOut:
    """Alta de una cámara o sensor en el inventario."""
    return await run_in_threadpool(sensores.registrar_sensor, datos, actor="api:operador", ip_origen=ip)


@router.get("", response_model=list[SensorOut], dependencies=[OperadorAutenticado])
async def listar_sensores() -> list[SensorOut]:
    return await run_in_threadpool(sensores.listar_sensores)
