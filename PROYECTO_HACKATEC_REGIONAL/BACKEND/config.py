from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger("sentinelops")

_VERDADEROS = {"1", "true", "yes", "si", "sí", "on"}


def _env_bool(nombre: str, default: bool) -> bool:
    valor = os.getenv(nombre)
    return default if valor is None else valor.strip().lower() in _VERDADEROS


def _env_int(nombre: str, default: int) -> int:
    valor = os.getenv(nombre)
    if valor is None or not valor.strip():
        return default
    try:
        return int(valor)
    except ValueError as exc:
        raise RuntimeError(f"La variable {nombre} debe ser un entero, recibido: {valor!r}") from exc


def _env_opcional(nombre: str) -> str | None:
    valor = os.getenv(nombre, "").strip()
    return valor or None


@dataclass(frozen=True, slots=True)
class Settings:
    api_prefix: str
    jwt_secret: str
    jwt_algoritmo: str
    jwt_ttl_segundos: int
    nodo_central_id: str
    sensor_api_key: str | None
    operador_api_key: str | None
    auto_registrar_sensores: bool
    ws_max_conexiones: int
    tolerancia_reloj_segundos: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    secreto = _env_opcional("SENTINEL_JWT_SECRET")
    if secreto is None:
        # Secreto efímero: los tokens emitidos dejan de ser verificables al reiniciar.
        secreto = secrets.token_urlsafe(48)
        logger.warning("SENTINEL_JWT_SECRET no definido: usando secreto efímero (solo desarrollo).")
    elif len(secreto) < 32:
        raise RuntimeError("SENTINEL_JWT_SECRET debe tener al menos 32 caracteres.")

    settings = Settings(
        api_prefix="/api/v1",
        jwt_secret=secreto,
        jwt_algoritmo="HS256",
        jwt_ttl_segundos=_env_int("SENTINEL_JWT_TTL_SEGUNDOS", 600),
        nodo_central_id=os.getenv("SENTINEL_NODO_CENTRAL_ID", "MX/GOB/TECNM/SENTINELOPS-CENTRAL"),
        sensor_api_key=_env_opcional("SENTINEL_SENSOR_API_KEY"),
        operador_api_key=_env_opcional("SENTINEL_OPERADOR_API_KEY"),
        auto_registrar_sensores=_env_bool("SENTINEL_AUTO_REGISTRAR_SENSORES", True),
        ws_max_conexiones=_env_int("SENTINEL_WS_MAX_CONEXIONES", 200),
        tolerancia_reloj_segundos=_env_int("SENTINEL_TOLERANCIA_RELOJ_SEGUNDOS", 300),
    )
    if settings.sensor_api_key is None or settings.operador_api_key is None:
        logger.warning("API keys no configuradas: endpoints abiertos (modo desarrollo).")
    return settings
