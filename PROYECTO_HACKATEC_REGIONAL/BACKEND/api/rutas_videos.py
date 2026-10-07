from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path
from fastapi.responses import FileResponse

from ..config import get_settings
from ..errores import RecursoNoEncontrado
from ..schemas import RESPUESTAS_ERROR, CamaraDemoOut
from ..services import camaras_demo
from .dependencias import OperadorAutenticado, OperadorOToken

_TIPOS = {"mp4": "video/mp4", "webm": "video/webm"}

router = APIRouter(
    prefix="/camaras-demo", tags=["Cámaras de demostración"], dependencies=[OperadorAutenticado], responses=RESPUESTAS_ERROR
)


@router.get("", response_model=list[CamaraDemoOut])
async def listar_camaras_demo() -> list[CamaraDemoOut]:
    """Videos grabados y ya anotados por el Edge AI que el panel muestra como cámaras."""
    return camaras_demo.listar()


# Sin prefijo /api/v1, igual que las evidencias: el panel usa `video_url` tal cual (+ ?token=...).
router_archivos = APIRouter(prefix=camaras_demo.PREFIJO_URL, tags=["Cámaras de demostración"], responses=RESPUESTAS_ERROR)


@router_archivos.get("/{archivo}", response_class=FileResponse, dependencies=[OperadorOToken])
async def obtener_video(archivo: Annotated[str, Path(max_length=200)]) -> FileResponse:
    """Video de una cámara de demostración. Muestra personas, por eso exige la clave de
    operador (header `X-Operador-Key` o `?token=`, que es lo que puede enviar un <video>)."""
    carpeta = get_settings().videos_dir.resolve()
    ruta = (carpeta / archivo).resolve()
    if not camaras_demo.NOMBRE_VALIDO.match(archivo) or ruta.parent != carpeta or not ruta.is_file():
        raise RecursoNoEncontrado("Video no encontrado.", detalle={"archivo": archivo})
    return FileResponse(
        ruta,
        media_type=_TIPOS[ruta.suffix.lower().lstrip(".")],
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )
