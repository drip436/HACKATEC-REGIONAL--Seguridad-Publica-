from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, status
from starlette.concurrency import run_in_threadpool

from ..schemas import RESPUESTAS_ERROR, SensorIn, SensorOut, SensorUpdateIn
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


@router.get("/{sensor_id}", response_model=SensorOut, dependencies=[OperadorAutenticado])
async def obtener_sensor(sensor_id: Annotated[int, Path(gt=0)]) -> SensorOut:
    return await run_in_threadpool(sensores.obtener_sensor, sensor_id)


@router.patch("/{sensor_id}", response_model=SensorOut, dependencies=[OperadorAutenticado])
async def actualizar_sensor(sensor_id: Annotated[int, Path(gt=0)], datos: SensorUpdateIn, ip: IpCliente) -> SensorOut:
    """Actualización parcial (p. ej. pasar a `mantenimiento` o dar de baja con `inactivo`).
    Un sensor `inactivo` deja de poder reportar eventos."""
    return await run_in_threadpool(
        sensores.actualizar_sensor, sensor_id, datos, actor="api:operador", ip_origen=ip
    )
