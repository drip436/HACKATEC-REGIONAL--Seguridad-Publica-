from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Path
from fastapi.responses import FileResponse

from ..config import get_settings
from ..errores import RecursoNoEncontrado
from ..schemas import RESPUESTAS_ERROR
from .dependencias import OperadorOToken

# Mismo patrón que AlertaSensorIn.evidencia_url: solo nombres planos de imagen.
_NOMBRE_VALIDO = re.compile(r"^[A-Za-z0-9_.-]+\.(jpg|jpeg|png)$")
_TIPOS = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}

# Sin prefijo /api/v1: la ruta coincide con la `evidencia_url` que envía el sensor,
# así el frontend usa ese valor tal cual (+ ?token=... en un <img>).
router = APIRouter(prefix="/static/capturas", tags=["Evidencias"], responses=RESPUESTAS_ERROR)


@router.get("/{archivo}", response_class=FileResponse, dependencies=[OperadorOToken])
async def obtener_evidencia(archivo: Annotated[str, Path(max_length=200)]) -> FileResponse:
    """Fotograma de evidencia guardado por el sensor Edge AI. Contiene imágenes de
    personas, por eso exige la clave de operador (header `X-Operador-Key` o `?token=`)."""
    carpeta = get_settings().evidencias_dir.resolve()
    ruta = (carpeta / archivo).resolve()
    if not _NOMBRE_VALIDO.match(archivo) or ruta.parent != carpeta or not ruta.is_file():
        raise RecursoNoEncontrado("Evidencia no encontrada.", detalle={"archivo": archivo})
    return FileResponse(
        ruta,
        media_type=_TIPOS[ruta.suffix.lower().lstrip(".")],
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )
