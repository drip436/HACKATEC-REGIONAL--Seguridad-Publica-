from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from starlette.concurrency import run_in_threadpool

from ..schemas import RESPUESTAS_ERROR, LugarOut, UbicacionAutoOut
from ..services import geocodificacion, ubicacion_auto
from .dependencias import OperadorAutenticado

router = APIRouter(
    prefix="/geocodificar", tags=["Ubicación"], dependencies=[OperadorAutenticado], responses=RESPUESTAS_ERROR
)


@router.get("", response_model=list[LugarOut])
async def geocodificar(q: Annotated[str, Query(min_length=3, max_length=2000)]) -> list[LugarOut]:
    """Busca una dirección o lugar y devuelve sus coordenadas (Google si hay llave; si no, OpenStreetMap)."""
    return await run_in_threadpool(geocodificacion.buscar, q)


router_ubicacion = APIRouter(
    prefix="/ubicacion-automatica", tags=["Ubicación"], dependencies=[OperadorAutenticado], responses=RESPUESTAS_ERROR
)


@router_ubicacion.get("", response_model=UbicacionAutoOut)
async def ubicacion_automatica(url: Annotated[str | None, Query(max_length=500)] = None) -> UbicacionAutoOut:
    """Ubica la cámara sin escribir coordenadas: GPS del teléfono (IP Webcam) o, si no,
    las redes Wi-Fi alrededor de esta computadora + Google Geolocation API."""
    u = await run_in_threadpool(ubicacion_auto.ubicar, url)
    return UbicacionAutoOut(lat=u.lat, lng=u.lng, precision_m=u.precision_m, fuente=u.fuente)
