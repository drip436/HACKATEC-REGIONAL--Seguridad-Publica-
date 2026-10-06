from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..models.enums import EstadoOperativo, TipoSensor
from .comunes import CodigoSensor, Coordenadas


class SensorIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    codigo: CodigoSensor
    nombre_ubicacion: str = Field(min_length=3, max_length=200)
    tipo_sensor: TipoSensor = TipoSensor.CAMARA_IP
    estado_operativo: EstadoOperativo = EstadoOperativo.ACTIVO
    ip_rtsp_url: str | None = Field(default=None, max_length=500, pattern=r"^(rtsp|rtsps|http|https)://")
    coordenadas: Coordenadas


class SensorOut(BaseModel):
    id: int
    codigo: str
    nombre_ubicacion: str
    tipo_sensor: TipoSensor
    estado_operativo: EstadoOperativo
    ip_rtsp_url: str | None
    coordenadas: Coordenadas
    creado_en: datetime
    actualizado_en: datetime
