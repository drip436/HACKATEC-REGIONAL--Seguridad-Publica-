"""Configuración central de SentinelOps.

Todas las constantes editables viven aquí. `build_config` permite sobreescribir
cualquiera de ellas (por ejemplo desde la CLI) sin tocar el módulo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


def _cargar_env_file() -> None:
    """Carga KEY=VALOR del primer `.env` encontrado (directorio actual o algún
    ancestro del paquete), sin pisar variables ya definidas. Así, en la misma
    máquina que el backend, la clave del sensor se toma del `.env` compartido."""
    candidatos = [Path.cwd() / ".env", *(p / ".env" for p in Path(__file__).resolve().parents)]
    for ruta in candidatos:
        if not ruta.is_file():
            continue
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, _, valor = linea.removeprefix("export ").partition("=")
            valor = valor.strip()
            if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
                valor = valor[1:-1]
            os.environ.setdefault(clave.strip(), valor)
        return


_cargar_env_file()

# --- Identidad del sensor --------------------------------------------------
SENSOR_ID: str = "CAM-01-ACCESO-PRINCIPAL"
LAT: float = 20.9673
LNG: float = -89.6242

# --- Backend ---------------------------------------------------------------
BACKEND_URL: str = os.getenv("SENTINELOPS_BACKEND_URL", "http://127.0.0.1:8000/api/v1/eventos")
# Debe coincidir con SENTINEL_SENSOR_API_KEY del backend (se envía en X-Sensor-Key).
SENSOR_API_KEY: str | None = os.getenv("SENTINEL_SENSOR_API_KEY") or None
HTTP_TIMEOUT: tuple[float, float] = (3.0, 5.0)  # (connect, read) en segundos
HTTP_MAX_RETRIES: int = 2
HTTP_BACKOFF_SECONDS: float = 0.5

# --- Cámara ----------------------------------------------------------------
CAMERA_INDEX: int = 0
FRAME_WIDTH: int = 1280
FRAME_HEIGHT: int = 720
# Fallos de lectura consecutivos tolerados antes de abortar. Una webcam USB
# devuelve frames vacíos esporádicamente sin que el dispositivo esté perdido.
READ_MAX_FAILURES: int = 15

# --- Inferencia ------------------------------------------------------------
MODEL_PATH: str = "yolov8n.pt"
CONF_THRESHOLD: float = 0.45
PERSON_CLASS_ID: int = 0  # COCO: "person"
DETECTED_CLASS_LABEL: str = "persona"

# --- Zona restringida ------------------------------------------------------
# Puntos en píxeles del frame redimensionado (FRAME_WIDTH x FRAME_HEIGHT),
# en orden horario. Si cambias la resolución, recalcula estos puntos.
ZONE_POLYGON: tuple[tuple[int, int], ...] = (
    (420, 240),
    (900, 240),
    (1040, 700),
    (300, 700),
)

# --- Alertas ---------------------------------------------------------------
COOLDOWN_SECONDS: float = 5.0
# Raíz del repositorio: si el sensor corre en la misma máquina que el backend,
# ambos usan la misma carpeta sin importar desde dónde se lancen. El backend la
# sirve en /static/capturas/<archivo> (con clave de operador).
_RAIZ_PROYECTO = Path(__file__).resolve().parents[2]
EVIDENCE_DIR: Path = _RAIZ_PROYECTO / os.getenv("SENTINEL_EVIDENCIAS_DIR", "static/capturas")
EVIDENCE_URL_PREFIX: str = "/static/capturas"
EVIDENCE_JPEG_QUALITY: int = 85
EVENT_TYPE: str = "INTRUSION_PERIMETRO"
EVENT_SEVERITY: str = "ALTA"

# --- Runtime ---------------------------------------------------------------
SHOW_PREVIEW: bool = True
LOG_LEVEL: str = "INFO"


@dataclass(frozen=True, slots=True)
class Config:
    """Snapshot inmutable de la configuración efectiva del proceso."""

    sensor_id: str = SENSOR_ID
    lat: float = LAT
    lng: float = LNG

    backend_url: str = BACKEND_URL
    sensor_api_key: str | None = SENSOR_API_KEY
    http_timeout: tuple[float, float] = HTTP_TIMEOUT
    http_max_retries: int = HTTP_MAX_RETRIES
    http_backoff_seconds: float = HTTP_BACKOFF_SECONDS

    camera_index: int = CAMERA_INDEX
    frame_width: int = FRAME_WIDTH
    frame_height: int = FRAME_HEIGHT
    read_max_failures: int = READ_MAX_FAILURES

    model_path: str = MODEL_PATH
    conf_threshold: float = CONF_THRESHOLD
    person_class_id: int = PERSON_CLASS_ID
    detected_class_label: str = DETECTED_CLASS_LABEL

    zone_polygon: tuple[tuple[int, int], ...] = ZONE_POLYGON

    cooldown_seconds: float = COOLDOWN_SECONDS
    evidence_dir: Path = EVIDENCE_DIR
    evidence_url_prefix: str = EVIDENCE_URL_PREFIX
    evidence_jpeg_quality: int = EVIDENCE_JPEG_QUALITY
    event_type: str = EVENT_TYPE
    event_severity: str = EVENT_SEVERITY

    show_preview: bool = SHOW_PREVIEW
    log_level: str = LOG_LEVEL

    def __post_init__(self) -> None:
        if len(self.zone_polygon) < 3:
            raise ValueError("ZONE_POLYGON necesita al menos 3 puntos")
        if not 0.0 < self.conf_threshold <= 1.0:
            raise ValueError("CONF_THRESHOLD debe estar en (0, 1]")
        if self.cooldown_seconds < 0:
            raise ValueError("COOLDOWN_SECONDS no puede ser negativo")
        if self.camera_index < 0:
            raise ValueError("CAMERA_INDEX no puede ser negativo")
        if not self.backend_url.startswith(("http://", "https://")):
            raise ValueError("BACKEND_URL debe empezar con http:// o https://")


def build_config(**overrides: Any) -> Config:
    """Devuelve la configuración por defecto con `overrides` aplicados.

    Los valores `None` se ignoran, para poder pasar argumentos de CLI tal cual.
    """
    clean = {key: value for key, value in overrides.items() if value is not None}
    return replace(Config(), **clean)
