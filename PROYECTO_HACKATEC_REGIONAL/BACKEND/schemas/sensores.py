from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class SensorUpdateIn(BaseModel):
    """Actualización parcial: solo se modifican los campos enviados. El código es
    inmutable porque los eventos históricos y la bitácora lo referencian."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nombre_ubicacion: str | None = Field(default=None, min_length=3, max_length=200)
    tipo_sensor: TipoSensor | None = None
    estado_operativo: EstadoOperativo | None = None
    ip_rtsp_url: str | None = Field(default=None, max_length=500, pattern=r"^(rtsp|rtsps|http|https)://")
    coordenadas: Coordenadas | None = None

    @model_validator(mode="after")
    def _al_menos_un_campo(self) -> SensorUpdateIn:
        if not self.model_fields_set:
            raise ValueError("Envía al menos un campo a actualizar.")
        return self


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
