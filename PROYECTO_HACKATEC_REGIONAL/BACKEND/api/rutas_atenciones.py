from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, status
from starlette.concurrency import run_in_threadpool

from ..realtime import get_manager
from ..schemas import RESPUESTAS_ERROR, AtencionIn, AtencionOut, UnidadOut
from ..services import atenciones
from .dependencias import IpCliente, OperadorAutenticado

router = APIRouter(
    prefix="/atenciones", tags=["Atención en campo"], dependencies=[OperadorAutenticado], responses=RESPUESTAS_ERROR
)


@router.post("", response_model=AtencionOut, status_code=status.HTTP_201_CREATED)
async def atender_evento(datos: AtencionIn, ip: IpCliente) -> AtencionOut:
    """El operador atiende el evento: queda validado y se envía una unidad por las
    calles hasta el lugar. El caso se marca como resuelto automáticamente al llegar."""
    resultado = await run_in_threadpool(atenciones.crear_atencion, datos, ip_origen=ip)
    manager = get_manager()
    await manager.broadcast("evento.actualizado", resultado.evento)
    await manager.broadcast("atencion.actualizada", resultado.atencion)
    return resultado.atencion


@router.get("", response_model=list[AtencionOut])
async def listar_atenciones(limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[AtencionOut]:
    return await run_in_threadpool(atenciones.listar_atenciones, limit=limit)


@router.get("/{atencion_id}", response_model=AtencionOut)
async def obtener_atencion(atencion_id: Annotated[int, Path(gt=0)]) -> AtencionOut:
    return await run_in_threadpool(atenciones.obtener_atencion, atencion_id)


router_unidades = APIRouter(
    prefix="/unidades", tags=["Atención en campo"], dependencies=[OperadorAutenticado], responses=RESPUESTAS_ERROR
)


@router_unidades.get("", response_model=list[UnidadOut])
async def listar_unidades() -> list[UnidadOut]:
    """Flota de patrullas (simulada): libres en su base o en camino a un evento."""
    return await run_in_threadpool(atenciones.listar_unidades)
