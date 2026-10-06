"""Entorno aislado para las pruebas del backend: BD SQLite temporal y claves propias.
No toca reflex.db ni el .env del proyecto."""

from __future__ import annotations

import os
import warnings
from collections.abc import Iterator
from datetime import timedelta
from itertools import count
from typing import Any

import pytest

CLAVE_SENSOR = "clave-sensor-de-pruebas-0123456789"
CLAVE_OPERADOR = "clave-operador-de-pruebas-0123456789"

# Deben fijarse antes de importar el backend: get_settings() se cachea.
os.environ.update(
    {
        "SENTINEL_ENV_FILE": os.devnull,
        "SENTINEL_ENTORNO": "desarrollo",
        "SENTINEL_JWT_SECRET": "secreto-jwt-de-pruebas-con-mas-de-32-caracteres",
        "SENTINEL_SENSOR_API_KEY": CLAVE_SENSOR,
        "SENTINEL_OPERADOR_API_KEY": CLAVE_OPERADOR,
        "SENTINEL_AUTO_REGISTRAR_SENSORES": "true",
        "SENTINEL_CONFIAR_PROXY": "false",
    }
)
warnings.filterwarnings("ignore", category=DeprecationWarning)


@pytest.fixture(scope="session")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    from fastapi.testclient import TestClient
    from reflex.config import get_config

    # Por defecto SQLite temporal. Para probar contra PostgreSQL (BD vacía y desechable):
    #   TEST_DATABASE_URL=postgresql+psycopg://usuario:clave@host:5432/bd pytest
    get_config().db_url = os.getenv("TEST_DATABASE_URL") or f"sqlite:///{tmp_path_factory.mktemp('bd') / 'pruebas.db'}"

    from PROYECTO_HACKATEC_REGIONAL.BACKEND import crear_api, inicializar_bd

    inicializar_bd()
    with TestClient(crear_api()) as c:
        yield c


@pytest.fixture
def op() -> dict[str, str]:
    return {"X-Operador-Key": CLAVE_OPERADOR}


@pytest.fixture
def sensor() -> dict[str, str]:
    return {"X-Sensor-Key": CLAVE_SENSOR}


_segundos = count()


def nueva_alerta(**cambios: Any) -> dict[str, Any]:
    """Alerta válida con timestamp único (dos alertas idénticas cuentan como reintento)."""
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.utils.tiempo import ahora_utc, iso_utc

    ts = ahora_utc() - timedelta(hours=1) + timedelta(seconds=next(_segundos))
    alerta: dict[str, Any] = {
        "sensor_id": "CAM-01-ACCESO-PRINCIPAL",
        "tipo_evento": "INTRUSION_PERIMETRO",
        "severidad": "ALTA",
        "coordenadas": {"lat": 20.9673, "lng": -89.6242},
        "timestamp": iso_utc(ts),
        "evidencia_url": "/static/capturas/evento_1042.jpg",
        "metadatos": {"clase_detectada": "persona", "confianza": 0.88, "bounding_box": [120, 80, 240, 310]},
    }
    alerta.update(cambios)
    return alerta


@pytest.fixture
def evento_validado(client: Any, op: dict[str, str], sensor: dict[str, str]) -> dict[str, Any]:
    evento = client.post("/api/v1/eventos", json=nueva_alerta(), headers=sensor).json()
    r = client.post(
        f"/api/v1/eventos/{evento['id']}/validar",
        json={"decision": "validado", "operador_id": "op.martinez"},
        headers=op,
    )
    assert r.status_code == 200, r.text
    return r.json()
