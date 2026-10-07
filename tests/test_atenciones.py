"""Atención en campo (patrulla simulada) y vinculación de cámara desde el panel."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import httpx
import pytest

from .conftest import CLAVE_OPERADOR, nueva_alerta

API = "/api/v1"
OP = {"X-Operador-Key": CLAVE_OPERADOR}


@pytest.fixture(autouse=True)
def sin_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """OSRM no se consulta en las pruebas: la ruta cae a línea recta."""
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import atenciones

    def _sin_red(*_: Any, **__: Any) -> None:
        raise httpx.ConnectError("sin red en pruebas")

    monkeypatch.setattr(atenciones.httpx, "get", _sin_red)


def _evento(client: Any, sensor: dict[str, str], **cambios: Any) -> dict[str, Any]:
    r = client.post(f"{API}/eventos", json=nueva_alerta(**cambios), headers=sensor)
    assert r.status_code == 201, r.text
    return r.json()


def test_atender_valida_el_evento_y_envia_una_unidad(client: Any, sensor: dict[str, str]) -> None:
    evento = _evento(client, sensor, severidad="CRITICA")
    r = client.post(f"{API}/atenciones", json={"evento_id": evento["id"], "operador_id": "op.martinez"}, headers=OP)
    assert r.status_code == 201, r.text
    atencion = r.json()
    assert atencion["estado"] == "en_camino"
    assert atencion["unidad"].startswith("PATRULLA-")
    assert atencion["ruta"][-1] == pytest.approx(list(atencion["destino"]))
    assert len(atencion["ruta"]) >= 2 and atencion["ruta_por_calles"] is False  # sin red: línea recta
    assert 20 <= atencion["duracion_s"] <= 75

    validado = client.get(f"{API}/eventos/{evento['id']}", headers=OP).json()
    assert validado["estado_validacion"] == "validado"
    assert validado["operador_id"] == "op.martinez"

    otra = client.post(f"{API}/atenciones", json={"evento_id": evento["id"], "operador_id": "op.lopez"}, headers=OP)
    assert otra.status_code == 409


def test_falsa_alarma_no_se_atiende(client: Any, sensor: dict[str, str]) -> None:
    evento = _evento(client, sensor)
    client.post(
        f"{API}/eventos/{evento['id']}/validar",
        json={"decision": "descartado_falsa_alarma", "operador_id": "op.martinez"},
        headers=OP,
    )
    r = client.post(f"{API}/atenciones", json={"evento_id": evento["id"], "operador_id": "op.martinez"}, headers=OP)
    assert r.status_code == 409


def test_la_unidad_llega_y_el_caso_queda_resuelto(
    client: Any, sensor: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import atenciones
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.utils.tiempo import ahora_utc

    evento = _evento(client, sensor)
    atencion = client.post(
        f"{API}/atenciones", json={"evento_id": evento["id"], "operador_id": "op.martinez"}, headers=OP
    ).json()
    assert atencion["id"] not in [a.id for a in atenciones.resolver_llegadas()]  # aún en camino

    futuro = ahora_utc() + timedelta(minutes=5)
    monkeypatch.setattr(atenciones, "ahora_utc", lambda: futuro)
    resueltas = atenciones.resolver_llegadas()
    assert atencion["id"] in [a.id for a in resueltas]

    guardada = client.get(f"{API}/atenciones/{atencion['id']}", headers=OP).json()
    assert guardada["estado"] == "resuelto" and guardada["llegada_en"] is not None
    acciones = [i["accion"] for i in client.get(f"{API}/auditoria", params={"limit": 6}, headers=OP).json()["items"]]
    assert "atencion.resuelta" in acciones and "atencion.unidad_despachada" in acciones
    assert client.get(f"{API}/auditoria/verificar", headers=OP).json()["integra"] is True


def test_websocket_avisa_la_atencion(client: Any, sensor: dict[str, str]) -> None:
    evento = _evento(client, sensor)
    with client.websocket_connect(f"/ws/alertas?token={CLAVE_OPERADOR}") as ws:
        ws.receive_text()  # conexion.establecida
        client.post(f"{API}/atenciones", json={"evento_id": evento["id"], "operador_id": "op.martinez"}, headers=OP)
        tipos = {json.loads(ws.receive_text())["tipo"] for _ in range(2)}
    assert tipos == {"evento.actualizado", "atencion.actualizada"}


# ---------------------------------------------------------------- vinculación de cámara


class _ProcesoFalso:
    pid = 999_999

    def __init__(self, comando: list[str], **kwargs: Any) -> None:
        self.comando = comando
        self.kwargs = kwargs
        self.stdout = iter(["Modelos listos\n"])
        self._vivo = True

    def poll(self) -> int | None:
        return None if self._vivo else 0

    def wait(self, timeout: float | None = None) -> int:
        self._vivo = False
        return 0


@pytest.fixture
def lanzados(monkeypatch: pytest.MonkeyPatch) -> list[_ProcesoFalso]:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import vinculacion

    procesos: list[_ProcesoFalso] = []

    def _popen(comando: list[str], **kwargs: Any) -> _ProcesoFalso:
        procesos.append(_ProcesoFalso(comando, **kwargs))
        return procesos[-1]

    monkeypatch.setattr(vinculacion.subprocess, "Popen", _popen)
    monkeypatch.setattr(vinculacion.os, "killpg", lambda pid, sig: procesos[-1].wait())
    yield procesos
    vinculacion.SUPERVISOR._actual = None


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"nombre": "Parque", "lat": 20.97, "lng": -89.62},  # sin URL ni demo
        {"url": "ftp://192.168.1.5/video", "nombre": "Parque", "lat": 20.97, "lng": -89.62},
        {"url": "http://192.168.1.5/video", "nombre": "Parque", "lat": 200, "lng": -89.62},
        {"url": "--help", "nombre": "Parque", "lat": 20.97, "lng": -89.62},
    ],
)
def test_vinculacion_rechaza_datos_invalidos(client: Any, lanzados: list, cuerpo: dict) -> None:
    assert client.post(f"{API}/camara-vinculada", json=cuerpo, headers=OP).status_code == 422
    assert lanzados == []


def test_vincular_y_desvincular_camara_del_telefono(client: Any, lanzados: list[_ProcesoFalso]) -> None:
    assert client.get(f"{API}/camara-vinculada", headers=OP).json()["vinculada"] is False
    cuerpo = {
        "url": "http://usuario:secreta@192.168.1.50:8080/video",
        "nombre": "Parque de Santa Lucía",
        "lat": 20.97055,
        "lng": -89.62186,
    }
    r = client.post(f"{API}/camara-vinculada", json=cuerpo, headers=OP)
    assert r.status_code == 200, r.text
    estado = r.json()
    assert estado["vinculada"] and estado["activa"]
    assert estado["sensor_id"] == "CAM-MOVIL-PARQUE-DE-SANTA-LUCIA"
    assert estado["fuente"] == "http://192.168.1.50:8080/video"  # sin credenciales

    comando = lanzados[0].comando
    assert "--source=http://usuario:secreta@192.168.1.50:8080/video" in comando  # el sensor sí la recibe
    assert "--zona-completa" in comando and "--no-preview" in comando
    assert "--lat=20.97055" in comando and lanzados[0].kwargs["start_new_session"] is True

    bitacora = client.get(f"{API}/auditoria", params={"accion": "camara.vinculada"}, headers=OP).json()["items"]
    assert bitacora and "secreta" not in str(bitacora)

    assert client.delete(f"{API}/camara-vinculada", headers=OP).json()["vinculada"] is False


def test_video_de_demostracion(client: Any, lanzados: list[_ProcesoFalso]) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services.vinculacion import VIDEO_DEMO

    cuerpo = {"demo": True, "nombre": "Demo", "lat": 20.96706, "lng": -89.62373}
    estado = client.post(f"{API}/camara-vinculada", json=cuerpo, headers=OP).json()
    assert estado["fuente"] == "video de demostración"
    assert f"--source={VIDEO_DEMO}" in lanzados[0].comando


def test_vincular_exige_operador(client: Any) -> None:
    assert client.post(f"{API}/camara-vinculada", json={"demo": True, "nombre": "x" * 5, "lat": 1, "lng": 1}).status_code == 401
