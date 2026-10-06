from __future__ import annotations

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from ..schemas import RESPUESTAS_ERROR, AcuseFederacionOut, MiembroFederadoOut, SolicitudFederacionIn
from ..services import xroad
from .dependencias import IpCliente

router = APIRouter(prefix="/interoperabilidad", tags=["Interoperabilidad X-Road"], responses=RESPUESTAS_ERROR)


@router.post("/federar", response_model=AcuseFederacionOut)
async def federar(solicitud: SolicitudFederacionIn, ip: IpCliente) -> AcuseFederacionOut:
    """Webhook del nodo receptor simulado. La autenticación es el propio JWT:
    se verifican firma, emisor, miembro destino, vigencia, `jti` (anti-replay) e
    integridad del payload contra el hash sellado. Devuelve un acuse firmado."""
    return await run_in_threadpool(xroad.recibir_federacion, solicitud, ip_origen=ip)


@router.get("/miembros", response_model=list[MiembroFederadoOut])
async def listar_miembros() -> list[MiembroFederadoOut]:
    return xroad.miembros_federados()
