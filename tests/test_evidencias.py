"""Servicio de fotogramas de evidencia en /static/capturas/<archivo>."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from .conftest import CARPETA_EVIDENCIAS, CLAVE_OPERADOR, CLAVE_SENSOR, nueva_alerta

JPEG = b"\xff\xd8\xff\xe0" + b"sentinel" * 100 + b"\xff\xd9"


@pytest.fixture(scope="module")
def foto() -> str:
    (Path(CARPETA_EVIDENCIAS) / "evento_42.jpg").write_bytes(JPEG)
    (Path(CARPETA_EVIDENCIAS) / "notas.txt").write_text("no es imagen")
    (Path(CARPETA_EVIDENCIAS).parent / "secreto.jpg").write_bytes(b"fuera de la carpeta")
    return "/static/capturas/evento_42.jpg"


def test_carpeta_compartida_con_el_sensor() -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.config import get_settings

    assert get_settings().evidencias_dir == Path(CARPETA_EVIDENCIAS)


def test_exige_clave_de_operador(client: Any, foto: str) -> None:
    assert client.get(foto).status_code == 401
    assert client.get(foto, params={"token": "mala"}).status_code == 401


@pytest.mark.parametrize("modo", ["header", "query"])
def test_sirve_la_imagen(client: Any, foto: str, modo: str) -> None:
    if modo == "header":
        r = client.get(foto, headers={"X-Operador-Key": CLAVE_OPERADOR})
    else:  # <img src="/static/capturas/evento_42.jpg?token=...">
        r = client.get(foto, params={"token": CLAVE_OPERADOR})
    assert r.status_code == 200
    assert r.content == JPEG
    assert r.headers["content-type"] == "image/jpeg"
    assert "private" in r.headers["cache-control"]


@pytest.mark.parametrize(
    "ruta",
    [
        "/static/capturas/no_existe.jpg",
        "/static/capturas/notas.txt",  # solo imágenes
        "/static/capturas/..%2Fsecreto.jpg",  # salir de la carpeta
        "/static/capturas/%2E%2E%2Fsecreto.jpg",
    ],
)
def test_no_expone_otros_archivos(client: Any, foto: str, ruta: str) -> None:
    r = client.get(ruta, headers={"X-Operador-Key": CLAVE_OPERADOR})
    assert r.status_code == 404
    assert b"fuera de la carpeta" not in r.content


def test_evidencia_url_del_evento_es_servible(client: Any, foto: str) -> None:
    evento = client.post(
        "/api/v1/eventos",
        json=nueva_alerta(evidencia_url="/static/capturas/evento_42.jpg"),
        headers={"X-Sensor-Key": CLAVE_SENSOR},
    ).json()
    r = client.get(evento["evidencia_url"], params={"token": CLAVE_OPERADOR})
    assert r.status_code == 200 and r.content == JPEG
