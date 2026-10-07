from __future__ import annotations

from typing import Annotated

import logging

from fastapi import APIRouter, BackgroundTasks, Path, Query, status
from starlette.concurrency import run_in_threadpool

from ..errores import SentinelError
from ..realtime import get_manager
from ..schemas import RESPUESTAS_ERROR, DespachoIn, DespachoOut, ErrorRespuesta, ReintentoDespachoIn
from ..services import despachos
from .dependencias import IpCliente, OperadorAutenticado

router = APIRouter(
    prefix="/despachos",
    tags=["Despachos"],
    dependencies=[OperadorAutenticado],
    responses={**RESPUESTAS_ERROR, 502: {"model": ErrorRespuesta, "description": "Falló la federación"}},
)


LOGGER = logging.getLogger("sentinelops.despachos")


@router.post("", response_model=DespachoOut, status_code=status.HTTP_202_ACCEPTED)
async def crear_despacho(datos: DespachoIn, ip: IpCliente, tareas: BackgroundTasks) -> DespachoOut:
    """Emite la orden de despacho de un evento **validado** y responde al instante con
    estado `enviado`. La federación X-Road y el acuse firmado se completan después de
    responder; el resultado llega por `/ws/alertas` (`despacho.actualizado`)."""
    despacho, federacion = await run_in_threadpool(despachos.emitir_despacho, datos, ip_origen=ip)
    await get_manager().broadcast("despacho.actualizado", despacho)
    tareas.add_task(_completar_federacion, federacion)
    return despacho


async def _completar_federacion(federacion: despachos.Federacion) -> None:
    try:
        despacho = await run_in_threadpool(despachos.completar_despacho, federacion)
    except SentinelError as error:
        # Queda `enviado`: el operador puede reintentar desde el panel.
        LOGGER.warning("Federación del despacho %d falló: %s", federacion.despacho_id, error)
        despacho = await run_in_threadpool(despachos.obtener_despacho, federacion.despacho_id)
    except Exception:  # noqa: BLE001 - una tarea de fondo nunca debe tumbar el servidor
        LOGGER.exception("Error inesperado al completar el despacho %d", federacion.despacho_id)
        return
    await get_manager().broadcast("despacho.actualizado", despacho)


@router.post("/{despacho_id}/reintentar", response_model=DespachoOut)
async def reintentar_despacho(
    despacho_id: Annotated[int, Path(gt=0)], datos: ReintentoDespachoIn, ip: IpCliente
) -> DespachoOut:
    """Vuelve a federar un despacho que quedó en `enviado` tras un 502. Se emite un
    token nuevo (nuevo `jti`); si el despacho ya está `confirmado` devuelve 409."""
    despacho = await run_in_threadpool(
        despachos.reintentar_despacho, despacho_id, operador_id=datos.operador_id, ip_origen=ip
    )
    await get_manager().broadcast("despacho.actualizado", despacho)
    return despacho


@router.get("", response_model=list[DespachoOut])
async def listar_despachos(
    evento_id: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DespachoOut]:
    return await run_in_threadpool(despachos.listar_despachos, evento_id=evento_id, limit=limit, offset=offset)


@router.get("/{despacho_id}", response_model=DespachoOut)
async def obtener_despacho(despacho_id: Annotated[int, Path(gt=0)]) -> DespachoOut:
    return await run_in_threadpool(despachos.obtener_despacho, despacho_id)
