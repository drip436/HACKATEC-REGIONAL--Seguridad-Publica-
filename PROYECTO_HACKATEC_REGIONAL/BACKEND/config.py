from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("sentinelops")

_VERDADEROS = {"1", "true", "yes", "si", "sí", "on"}
# Raíz del repositorio: rutas relativas fijas sin depender del directorio de arranque.
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]


def _cargar_env_file() -> None:
    """Carga KEY=VALOR desde .env (ruta en SENTINEL_ENV_FILE o ./.env) sin depender de
    python-dotenv. Las variables ya definidas en el entorno tienen prioridad."""
    ruta = Path(os.getenv("SENTINEL_ENV_FILE", ".env"))
    if not ruta.is_file():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.removeprefix("export ").partition("=")
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        os.environ.setdefault(clave.strip(), valor)


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
    confiar_proxy: bool
    evidencias_dir: Path
    videos_dir: Path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _cargar_env_file()
    produccion = os.getenv("SENTINEL_ENTORNO", "desarrollo").strip().lower() == "produccion"

    secreto = _env_opcional("SENTINEL_JWT_SECRET")
    if secreto is None:
        if produccion:
            raise RuntimeError("SENTINEL_JWT_SECRET es obligatorio con SENTINEL_ENTORNO=produccion.")
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
        confiar_proxy=_env_bool("SENTINEL_CONFIAR_PROXY", False),
        # Misma carpeta donde el sensor Edge AI guarda las capturas (EDGE_AI/sentinelops/config.py).
        evidencias_dir=RAIZ_PROYECTO / os.getenv("SENTINEL_EVIDENCIAS_DIR", "static/capturas"),
        # Videos ya anotados por el Edge AI (EDGE_AI/tools/preprocesar_video.py) y su índice.
        videos_dir=RAIZ_PROYECTO / os.getenv("SENTINEL_VIDEOS_DIR", "static/videos"),
    )
    if settings.sensor_api_key is None or settings.operador_api_key is None:
        if produccion:
            raise RuntimeError(
                "SENTINEL_SENSOR_API_KEY y SENTINEL_OPERADOR_API_KEY son obligatorias en producción."
            )
        logger.warning("API keys no configuradas: endpoints abiertos (modo desarrollo).")
    return settings
