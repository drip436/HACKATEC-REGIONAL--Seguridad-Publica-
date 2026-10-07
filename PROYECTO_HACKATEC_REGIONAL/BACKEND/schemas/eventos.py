from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from ..models.enums import ALIAS_TIPO_EVENTO, EstadoValidacion, NivelPrioridad, TipoEvento
from .comunes import CodigoSensor, Coordenadas, IdOperador


class MetadatosDeteccion(BaseModel):
    # extra="forbid": privacidad por diseño. Si un sensor intenta adjuntar campos no
    # contemplados (embeddings faciales, rostros recortados, etc.) se rechaza el mensaje.
    model_config = ConfigDict(extra="forbid")

    clase_detectada: Literal["persona", "vehiculo", "objeto"] = "persona"
    confianza: float = Field(ge=0.0, le=1.0)
    bounding_box: tuple[int, int, int, int] = Field(description="[x1, y1, x2, y2] en píxeles")
    conteo_personas: int | None = Field(default=None, ge=1, le=10_000)
    # Conducta que reconoció el Edge AI (el tipo_evento conserva el catálogo base).
    conducta: (
        Literal[
            "asalto_con_arma",
            "intento_asalto",
            "intento_homicidio",
            "agresion_fisica",
            "posible_secuestro",
            "persona_sometida",
            "persona_sospechosa",
            "vehiculo_sospechoso",
        ]
        | None
    ) = None

    @field_validator("confianza")
    @classmethod
    def _redondear(cls, v: float) -> float:
        return round(v, 2)

    @field_validator("bounding_box")
    @classmethod
    def _bbox_valido(cls, v: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = v
        if min(v) < 0 or x2 <= x1 or y2 <= y1:
            raise ValueError("bounding_box debe cumplir 0 <= x1 < x2 y 0 <= y1 < y2")
        return v


class AlertaSensorIn(BaseModel):
    """Contrato del POST que emite el Módulo A (Edge AI / YOLOv8)."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "sensor_id": "CAM-01-ACCESO-PRINCIPAL",
                "tipo_evento": "INTRUSION_PERIMETRO",
                "severidad": "ALTA",
                "coordenadas": {"lat": 17.987172, "lng": -92.919115},
                "timestamp": "2026-10-06T10:45:00Z",
                "evidencia_url": "/static/capturas/evento_1042.jpg",
                "metadatos": {
                    "clase_detectada": "persona",
                    "confianza": 0.88,
                    "bounding_box": [120, 80, 240, 310],
                },
            }
        },
    )

    sensor_id: CodigoSensor
    tipo_evento: TipoEvento
    severidad: NivelPrioridad
    coordenadas: Coordenadas
    timestamp: AwareDatetime
    evidencia_url: str | None = Field(
        default=None, max_length=300, pattern=r"^/static/capturas/[A-Za-z0-9_.-]+\.(jpg|jpeg|png)$"
    )
    metadatos: MetadatosDeteccion
    ubicacion: str | None = Field(
        default=None,
        min_length=3,
        max_length=200,
        description="Nombre del lugar; se usa solo al autorregistrar un sensor nuevo.",
    )

    @field_validator("tipo_evento", mode="before")
    @classmethod
    def _normalizar_tipo(cls, v: Any) -> Any:
        if isinstance(v, str):
            return ALIAS_TIPO_EVENTO.get(v.strip().upper(), v.strip().lower())
        return v

    @field_validator("severidad", mode="before")
    @classmethod
    def _normalizar_severidad(cls, v: Any) -> Any:
        if isinstance(v, str):
            limpio = v.strip().lower()
            return "critica" if limpio == "crítica" else limpio
        return v


class ValidacionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal[EstadoValidacion.VALIDADO, EstadoValidacion.DESCARTADO]
    operador_id: IdOperador
    notas: str | None = Field(default=None, max_length=500)
    nivel_prioridad: NivelPrioridad | None = Field(
        default=None, description="Permite al operador reclasificar la prioridad al validar."
    )

    @model_validator(mode="after")
    def _prioridad_solo_si_valida(self) -> ValidacionIn:
        if self.decision == EstadoValidacion.DESCARTADO and self.nivel_prioridad is not None:
            raise ValueError("No se puede reclasificar la prioridad de una falsa alarma.")
        return self


class EventoOut(BaseModel):
    id: int
    sensor_id: int
    sensor_codigo: str
    tipo_evento: TipoEvento
    nivel_prioridad: NivelPrioridad
    estado_validacion: EstadoValidacion
    operador_id: str | None
    notas_validacion: str | None
    metadata_json: dict[str, Any]
    evidencia_url: str | None
    coordenadas: Coordenadas
    payload_hash_sha256: str
    fecha_deteccion: datetime
    recibido_en: datetime
    validado_en: datetime | None
