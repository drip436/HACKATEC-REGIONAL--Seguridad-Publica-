from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CodigoSensor = Annotated[str, Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{2,63}$", examples=["CAM-01-ACCESO-PRINCIPAL"])]
IdOperador = Annotated[str, Field(pattern=r"^[A-Za-z0-9._@-]{3,64}$", examples=["op.martinez"])]


class Coordenadas(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90, le=90, examples=[20.9673])
    lng: float = Field(ge=-180, le=180, examples=[-89.6242])


class ErrorDetalle(BaseModel):
    codigo: str
    mensaje: str
    detalle: dict[str, Any] = Field(default_factory=dict)


class ErrorRespuesta(BaseModel):
    error: ErrorDetalle


TipoMensajeWS = Literal[
    "conexion.establecida",
    "evento.nuevo",
    "evento.actualizado",
    "despacho.actualizado",
    "pong",
]


class MensajeWS(BaseModel):
    tipo: TipoMensajeWS
    emitido_en: datetime
    data: dict[str, Any] = Field(default_factory=dict)


RESPUESTAS_ERROR: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorRespuesta, "description": "Credencial o firma inválida"},
    404: {"model": ErrorRespuesta, "description": "Recurso no encontrado"},
    409: {"model": ErrorRespuesta, "description": "Conflicto de estado"},
    422: {"model": ErrorRespuesta, "description": "Validación fallida"},
}
