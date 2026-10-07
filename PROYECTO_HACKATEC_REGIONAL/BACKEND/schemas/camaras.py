from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VinculacionIn(BaseModel):
    """Cámara a vincular: URL de la app IP Webcam del teléfono (o el video de demo)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: str | None = Field(
        default=None,
        max_length=500,
        pattern=r"^(https?|rtsps?)://[^\s]+$",
        examples=["http://192.168.1.50:8080/video"],
    )
    demo: bool = Field(default=False, description="Usa el video de demostración en lugar de una cámara.")
    nombre: str = Field(min_length=3, max_length=120, examples=["Plaza de Armas, Villahermosa"])
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def _fuente(self) -> VinculacionIn:
        if not self.demo and not self.url:
            raise ValueError("Indica la URL de la cámara o activa el video de demostración.")
        return self


class CamaraVinculadaOut(BaseModel):
    vinculada: bool
    activa: bool = False  # el proceso del sensor sigue vivo
    sensor_id: str | None = None
    nombre: str | None = None
    fuente: str | None = None  # URL sin credenciales
    lat: float | None = None
    lng: float | None = None
    desde: datetime | None = None
    codigo_salida: int | None = None
    ultimas_lineas: list[str] = Field(default_factory=list)
