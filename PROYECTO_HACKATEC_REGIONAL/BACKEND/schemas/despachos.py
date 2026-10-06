from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..models.enums import Dependencia, EstadoEnvio
from .comunes import IdOperador


class DespachoIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evento_id: int = Field(gt=0)
    dependencia_destino: Dependencia
    operador_id: IdOperador
    instrucciones: str | None = Field(default=None, max_length=500)


class ReintentoDespachoIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    operador_id: IdOperador


class DespachoOut(BaseModel):
    id: int
    evento_id: int
    dependencia_destino: Dependencia
    miembro_xroad: str
    estado_envio: EstadoEnvio
    solicitado_por: str
    instrucciones: str | None
    token_interoperabilidad: str | None
    token_jti: str | None
    payload_hash: str | None
    acuse_recibo: dict[str, Any] | None
    timestamp_despacho: datetime
    confirmado_en: datetime | None


class SolicitudFederacionIn(BaseModel):
    """Mensaje que viaja entre servidores de seguridad (estilo X-Road): el token
    sella el hash del payload, así cualquier alteración en tránsito se detecta."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=4096)
    payload: dict[str, Any]


class AcuseFederacionOut(BaseModel):
    acuse_id: str
    miembro_receptor: str
    miembro_emisor: str
    referencia_jti: str
    payload_sha256: str
    recibido_en: datetime
    firma_acuse: str


class MiembroFederadoOut(BaseModel):
    dependencia: Dependencia
    miembro_xroad: str
