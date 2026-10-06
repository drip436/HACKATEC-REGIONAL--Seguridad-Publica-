from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from ..models.enums import AccionAuditoria


class RegistroAuditoriaOut(BaseModel):
    id: int
    accion: AccionAuditoria
    usuario_o_nodo: str
    ip_origen: str
    entidad: str
    entidad_id: str | None
    detalle_json: dict[str, Any]
    payload_hash_sha256: str
    hash_anterior: str
    hash_registro: str
    timestamp_inmutable: datetime


class PaginaAuditoria(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[RegistroAuditoriaOut]


class VerificacionCadenaOut(BaseModel):
    integra: bool
    registros_verificados: int
    ultimo_hash: str
    primer_registro_invalido: int | None = None
    motivo: str | None = None
