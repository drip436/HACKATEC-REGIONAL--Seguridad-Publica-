from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from ..utils.tiempo import ahora_utc
from .enums import (
    Dependencia,
    EstadoAtencion,
    EstadoEnvio,
    EstadoOperativo,
    EstadoValidacion,
    NivelPrioridad,
    TipoEvento,
    TipoSensor,
)


def _check_enum(columna: str, enum: type[StrEnum], tabla: str) -> sa.CheckConstraint:
    valores = ", ".join(f"'{v.value}'" for v in enum)
    return sa.CheckConstraint(f"{columna} IN ({valores})", name=f"ck_{tabla}_{columna}")


def _ts(nullable: bool = False, index: bool = False) -> Any:
    return sa.Column(sa.DateTime(timezone=True), nullable=nullable, index=index)


class _Base(SQLModel):
    # rx.Model está deprecado desde Reflex 0.9.2; Reflex recomienda SQLModel directo.
    id: int | None = Field(default=None, primary_key=True)


class CamaraSensor(_Base, table=True):
    __tablename__ = "camaras_sensores"
    __table_args__ = (
        _check_enum("tipo_sensor", TipoSensor, "camaras_sensores"),
        _check_enum("estado_operativo", EstadoOperativo, "camaras_sensores"),
        sa.CheckConstraint("latitud BETWEEN -90 AND 90", name="ck_camaras_sensores_lat"),
        sa.CheckConstraint("longitud BETWEEN -180 AND 180", name="ck_camaras_sensores_lng"),
    )

    codigo: str = Field(sa_column=sa.Column(sa.String(64), unique=True, nullable=False, index=True))
    nombre_ubicacion: str = Field(sa_column=sa.Column(sa.String(200), nullable=False))
    tipo_sensor: str = Field(default=TipoSensor.CAMARA_IP.value, max_length=32)
    estado_operativo: str = Field(default=EstadoOperativo.ACTIVO.value, max_length=32)
    ip_rtsp_url: str | None = Field(default=None, max_length=500)
    latitud: float
    longitud: float
    creado_en: datetime = Field(default_factory=ahora_utc, sa_column=_ts())
    actualizado_en: datetime = Field(default_factory=ahora_utc, sa_column=_ts())


class EventoDetectado(_Base, table=True):
    __tablename__ = "eventos_detectados"
    __table_args__ = (
        _check_enum("tipo_evento", TipoEvento, "eventos_detectados"),
        _check_enum("nivel_prioridad", NivelPrioridad, "eventos_detectados"),
        _check_enum("estado_validacion", EstadoValidacion, "eventos_detectados"),
        sa.Index("ix_eventos_estado_fecha", "estado_validacion", "fecha_deteccion"),
    )

    sensor_id: int = Field(foreign_key="camaras_sensores.id", index=True)
    tipo_evento: str = Field(max_length=32)
    nivel_prioridad: str = Field(max_length=16)
    estado_validacion: str = Field(default=EstadoValidacion.PENDIENTE.value, max_length=32)
    operador_id: str | None = Field(default=None, max_length=64)
    notas_validacion: str | None = Field(default=None, max_length=500)
    # Solo metadatos de la detección (bbox, confianza, clase); nunca rasgos biométricos.
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    evidencia_url: str | None = Field(default=None, max_length=300)
    latitud: float
    longitud: float
    # Hash del mensaje original del sensor: sirve como llave de idempotencia y prueba de origen.
    payload_hash_sha256: str = Field(sa_column=sa.Column(sa.String(64), unique=True, nullable=False))
    fecha_deteccion: datetime = Field(sa_column=_ts(index=True))
    recibido_en: datetime = Field(default_factory=ahora_utc, sa_column=_ts())
    validado_en: datetime | None = Field(default=None, sa_column=_ts(nullable=True))
    # Se llena cuando la unidad enviada llega al lugar: caso atendido y resuelto.
    resuelto_en: datetime | None = Field(default=None, sa_column=_ts(nullable=True))


class DespachoInteroperable(_Base, table=True):
    __tablename__ = "despachos_interoperables"
    __table_args__ = (
        _check_enum("dependencia_destino", Dependencia, "despachos_interoperables"),
        _check_enum("estado_envio", EstadoEnvio, "despachos_interoperables"),
        sa.UniqueConstraint("evento_id", "dependencia_destino", name="uq_despacho_evento_dependencia"),
    )

    evento_id: int = Field(foreign_key="eventos_detectados.id", index=True)
    dependencia_destino: str = Field(max_length=64)
    estado_envio: str = Field(default=EstadoEnvio.PENDIENTE.value, max_length=16)
    solicitado_por: str = Field(max_length=64)
    instrucciones: str | None = Field(default=None, max_length=500)
    token_interoperabilidad: str | None = Field(default=None, sa_column=sa.Column(sa.Text, nullable=True))
    token_jti: str | None = Field(default=None, sa_column=sa.Column(sa.String(64), unique=True, nullable=True))
    payload_hash: str | None = Field(default=None, max_length=64)
    acuse_recibo: dict[str, Any] | None = Field(default=None, sa_column=sa.Column(sa.JSON, nullable=True))
    timestamp_despacho: datetime = Field(default_factory=ahora_utc, sa_column=_ts(index=True))
    confirmado_en: datetime | None = Field(default=None, sa_column=_ts(nullable=True))


class AtencionCampo(_Base, table=True):
    """Unidad (patrulla) enviada al lugar de un evento. Se resuelve al llegar."""

    __tablename__ = "atenciones_campo"
    __table_args__ = (_check_enum("estado", EstadoAtencion, "atenciones_campo"),)

    # Una sola atención por evento: el reintento devuelve 409.
    evento_id: int = Field(sa_column=sa.Column(sa.Integer, sa.ForeignKey("eventos_detectados.id"), unique=True, nullable=False))
    unidad: str = Field(max_length=32)
    estado: str = Field(default=EstadoAtencion.EN_CAMINO.value, max_length=16)
    solicitado_por: str = Field(max_length=64)
    origen_lat: float
    origen_lng: float
    destino_lat: float
    destino_lng: float
    # Trazo de la ruta por calles: [[lat, lng], ...] (OSRM, o línea recta si no hay red).
    ruta: list[list[float]] = Field(default_factory=list, sa_column=sa.Column(sa.JSON, nullable=False))
    ruta_por_calles: bool = Field(default=False)
    distancia_m: float
    duracion_s: float  # duración de la simulación (acelerada para la demo)
    despachada_en: datetime = Field(default_factory=ahora_utc, sa_column=_ts(index=True))
    llegada_estimada: datetime = Field(sa_column=_ts(index=True))
    llegada_en: datetime | None = Field(default=None, sa_column=_ts(nullable=True))


class BitacoraAuditoria(_Base, table=True):
    """Bitácora append-only encadenada por hash (cada registro sella al anterior).
    UPDATE/DELETE se bloquean con triggers creados en services/db.py."""

    __tablename__ = "bitacora_auditoria"

    accion: str = Field(max_length=64, index=True)
    usuario_o_nodo: str = Field(max_length=128)
    ip_origen: str = Field(max_length=64)
    entidad: str = Field(max_length=64)
    entidad_id: str | None = Field(default=None, max_length=64)
    detalle_json: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    payload_hash_sha256: str = Field(max_length=64)
    hash_anterior: str = Field(max_length=64)
    hash_registro: str = Field(sa_column=sa.Column(sa.String(64), unique=True, nullable=False))
    timestamp_inmutable: datetime = Field(default_factory=ahora_utc, sa_column=_ts(index=True))
