from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status
from starlette.concurrency import run_in_threadpool

from ..config import get_settings
from ..models import EstadoValidacion, NivelPrioridad
from ..realtime import get_manager
from ..schemas import RESPUESTAS_ERROR, AlertaSensorIn, EventoOut, ValidacionIn
from ..services import eventos
from .dependencias import IpCliente, OperadorAutenticado, SensorAutenticado

router = APIRouter(prefix="/eventos", tags=["Eventos"], responses=RESPUESTAS_ERROR)


@router.post(
    "",
    response_model=EventoOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[SensorAutenticado],
    responses={200: {"model": EventoOut, "description": "Reintento idempotente: el evento ya existía"}},
)
async def recibir_evento(alerta: AlertaSensorIn, response: Response, ip: IpCliente) -> EventoOut:
    """Recibe una alerta del Módulo A (Edge AI), la guarda como `pendiente`,
    la sella en la bitácora y la difunde por `/ws/alertas`."""
    settings = get_settings()
    resultado = await run_in_threadpool(
        eventos.registrar_alerta,
        alerta,
        ip_origen=ip,
        auto_registrar=settings.auto_registrar_sensores,
        tolerancia_reloj_s=settings.tolerancia_reloj_segundos,
    )
    if resultado.creado:
        await get_manager().broadcast("evento.nuevo", resultado.evento)
    else:
        response.status_code = status.HTTP_200_OK
        response.headers["X-Idempotent-Replay"] = "true"
    return resultado.evento


@router.get("", response_model=list[EventoOut], dependencies=[OperadorAutenticado])
async def listar_eventos(
    estado: EstadoValidacion | None = None,
    prioridad: NivelPrioridad | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[EventoOut]:
    return await run_in_threadpool(
        eventos.listar_eventos, estado=estado, prioridad=prioridad, limit=limit, offset=offset
    )


@router.get("/{evento_id}", response_model=EventoOut, dependencies=[OperadorAutenticado])
async def obtener_evento(evento_id: Annotated[int, Path(gt=0)]) -> EventoOut:
    return await run_in_threadpool(eventos.obtener_evento, evento_id)


@router.post("/{evento_id}/validar", response_model=EventoOut, dependencies=[OperadorAutenticado])
async def validar_evento(evento_id: Annotated[int, Path(gt=0)], datos: ValidacionIn, ip: IpCliente) -> EventoOut:
    """Decisión humana (Human-in-the-loop): `validado` o `descartado_falsa_alarma`.
    Solo procede sobre eventos `pendiente`; un segundo intento devuelve 409."""
    evento = await run_in_threadpool(eventos.validar_evento, evento_id, datos, ip_origen=ip)
    await get_manager().broadcast("evento.actualizado", evento)
    return evento
