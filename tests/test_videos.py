"""Cámaras de demostración: índice en /api/v1/camaras-demo y videos en /static/videos/<archivo>."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from .conftest import CARPETA_VIDEOS, CLAVE_OPERADOR

VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"sentinel" * 200
OPERADOR = {"X-Operador-Key": CLAVE_OPERADOR}


@pytest.fixture(scope="module")
def carpeta() -> Path:
    carpeta = Path(CARPETA_VIDEOS)
    (carpeta / "CAM-DEMO-PLAZA.mp4").write_bytes(VIDEO)
    (carpeta.parent / "secreto.mp4").write_bytes(b"fuera de la carpeta")
    (carpeta / "camaras.json").write_text(
        json.dumps(
            [
                {"id": "CAM-DEMO-PLAZA", "nombre": "Plaza de Armas", "lat": 17.989, "lng": -92.93, "video": "CAM-DEMO-PLAZA.mp4"},
                {"id": "CAM-DEMO-SIN-VIDEO", "nombre": "Sin archivo", "lat": 17.9, "lng": -92.9, "video": "no_existe.mp4"},
                {"id": "CAM-DEMO-FUERA", "nombre": "Fuera", "lat": 17.9, "lng": -92.9, "video": "../secreto.mp4"},
                {"nombre": "Sin id"},
            ]
        ),
        encoding="utf-8",
    )
    return carpeta


def test_lista_solo_las_camaras_con_video(client: Any, carpeta: Path) -> None:
    assert client.get("/api/v1/camaras-demo").status_code == 401
    r = client.get("/api/v1/camaras-demo", headers=OPERADOR)
    assert r.status_code == 200
    assert r.json() == [
        {"id": "CAM-DEMO-PLAZA", "nombre": "Plaza de Armas", "lat": 17.989, "lng": -92.93, "video_url": "/static/videos/CAM-DEMO-PLAZA.mp4"}
    ]


def test_sin_indice_no_hay_camaras(client: Any, carpeta: Path) -> None:
    indice = carpeta / "camaras.json"
    contenido = indice.read_text(encoding="utf-8")
    try:
        indice.write_text("{ no es json", encoding="utf-8")
        assert client.get("/api/v1/camaras-demo", headers=OPERADOR).json() == []
        indice.unlink()
        assert client.get("/api/v1/camaras-demo", headers=OPERADOR).json() == []
    finally:
        indice.write_text(contenido, encoding="utf-8")


def test_video_exige_clave_de_operador(client: Any, carpeta: Path) -> None:
    assert client.get("/static/videos/CAM-DEMO-PLAZA.mp4").status_code == 401


def test_sirve_el_video_completo_y_por_rangos(client: Any, carpeta: Path) -> None:
    # <video src="/static/videos/CAM-DEMO-PLAZA.mp4?token=..."> pide rangos para repetir en bucle.
    r = client.get("/static/videos/CAM-DEMO-PLAZA.mp4", params={"token": CLAVE_OPERADOR})
    assert r.status_code == 200
    assert r.content == VIDEO
    assert r.headers["content-type"] == "video/mp4"
    parcial = client.get("/static/videos/CAM-DEMO-PLAZA.mp4", headers={**OPERADOR, "Range": "bytes=0-99"})
    assert parcial.status_code == 206
    assert parcial.content == VIDEO[:100]


@pytest.mark.parametrize("archivo", ["camaras.json", "no_existe.mp4", "..%2Fsecreto.mp4"])
def test_no_sirve_otros_archivos(client: Any, carpeta: Path, archivo: str) -> None:
    assert client.get(f"/static/videos/{archivo}", headers=OPERADOR).status_code == 404
