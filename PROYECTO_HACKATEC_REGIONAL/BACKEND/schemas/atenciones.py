from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..models.enums import EstadoAtencion
from .comunes import IdOperador


class AtencionIn(BaseModel):
    """El operador decide atender un evento: se envía una unidad al lugar."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evento_id: int = Field(gt=0)
    operador_id: IdOperador


class AtencionOut(BaseModel):
    id: int
    evento_id: int
    unidad: str
    estado: EstadoAtencion
    solicitado_por: str
    origen: tuple[float, float]
    destino: tuple[float, float]
    ruta: list[tuple[float, float]]
    ruta_por_calles: bool
    distancia_m: float
    duracion_s: float
    despachada_en: datetime
    llegada_estimada: datetime
    llegada_en: datetime | None


class UnidadOut(BaseModel):
    """Patrulla de la flota: libre en su base o en camino a un evento."""

    id: str
    base: str
    lat: float
    lng: float
    estado: Literal["libre", "en_camino"]
    evento_id: int | None = None
