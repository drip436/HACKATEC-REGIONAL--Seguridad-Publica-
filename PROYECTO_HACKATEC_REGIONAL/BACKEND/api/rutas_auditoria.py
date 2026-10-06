from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AwareDatetime
from starlette.concurrency import run_in_threadpool

from ..models import AccionAuditoria
from ..schemas import RESPUESTAS_ERROR, PaginaAuditoria, VerificacionCadenaOut
from ..services import auditoria
from .dependencias import IpCliente, OperadorAutenticado

router = APIRouter(
    prefix="/auditoria", tags=["Auditoría"], dependencies=[OperadorAutenticado], responses=RESPUESTAS_ERROR
)


@router.get("", response_model=PaginaAuditoria)
async def consultar_bitacora(
    ip: IpCliente,
    accion: AccionAuditoria | None = None,
    entidad: Annotated[str | None, Query(max_length=64)] = None,
    entidad_id: Annotated[str | None, Query(max_length=64)] = None,
    desde: AwareDatetime | None = None,
    hasta: AwareDatetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginaAuditoria:
    """Consulta de solo lectura de la bitácora. No existen endpoints de edición
    ni borrado, y la BD lo impide con triggers. La consulta misma queda registrada."""
    return await run_in_threadpool(
        auditoria.consultar,
        accion=accion,
        entidad=entidad,
        entidad_id=entidad_id,
        desde=desde,
        hasta=hasta,
        limit=limit,
        offset=offset,
        consultado_por="api:operador",
        ip_origen=ip,
    )


@router.get("/verificar", response_model=VerificacionCadenaOut)
async def verificar_integridad() -> VerificacionCadenaOut:
    """Recorre la cadena completa y recalcula cada hash para detectar manipulación."""
    return await run_in_threadpool(auditoria.verificar_cadena)
