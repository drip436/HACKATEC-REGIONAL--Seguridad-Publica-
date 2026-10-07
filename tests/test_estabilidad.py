"""Estabilidad: el API no se congela, la cámara se valida antes de lanzar el sensor,
el despacho no bloquea, la patrulla más cercana atiende y el caso queda resuelto."""

from __future__ import annotations

import asyncio
import json
import socket
import sqlite3
import subprocess
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa

from .conftest import CLAVE_OPERADOR, nueva_alerta

API = "/api/v1"
OP = {"X-Operador-Key": CLAVE_OPERADOR}
ITM = {"lat": 21.012881, "lng": -89.621920}  # Instituto Tecnológico de Mérida
CENTRO = {"lat": 20.967074, "lng": -89.623744}  # Plaza Grande


@pytest.fixture(autouse=True)
def sin_osrm(monkeypatch: pytest.MonkeyPatch) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import atenciones

    def _sin_red(*_: Any, **__: Any) -> None:
        raise httpx.ConnectError("sin red en pruebas")

    monkeypatch.setattr(atenciones.httpx, "get", _sin_red)


def _liberar_flota(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hace llegar a todas las unidades en camino (adelanta el reloj del resolvedor)."""
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import atenciones
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.utils.tiempo import ahora_utc

    futuro = ahora_utc() + timedelta(hours=1)
    with monkeypatch.context() as m:
        m.setattr(atenciones, "ahora_utc", lambda: futuro)
        atenciones.resolver_llegadas()


def _evento_en(client: Any, sensor: dict[str, str], coords: dict[str, float]) -> dict[str, Any]:
    r = client.post(f"{API}/eventos", json=nueva_alerta(coordenadas=coords, severidad="CRITICA"), headers=sensor)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- flota y cierre del caso


def test_sale_la_unidad_libre_mas_cercana(client: Any, sensor: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    _liberar_flota(monkeypatch)
    en_campus = _evento_en(client, sensor, ITM)
    en_centro = _evento_en(client, sensor, CENTRO)
    a1 = client.post(f"{API}/atenciones", json={"evento_id": en_campus["id"], "operador_id": "op.m"}, headers=OP).json()
    a2 = client.post(f"{API}/atenciones", json={"evento_id": en_centro["id"], "operador_id": "op.m"}, headers=OP).json()
    assert a1["unidad"] == "PATRULLA-01"  # Base Gran Plaza: la más cercana al Tecnológico
    assert a2["unidad"] == "PATRULLA-03"  # Base Centro
    assert a1["ruta"][0] == pytest.approx([21.030114, -89.624435])  # sale de su base

    unidades = {u["id"]: u for u in client.get(f"{API}/unidades", headers=OP).json()}
    assert unidades["PATRULLA-01"]["estado"] == "en_camino" and unidades["PATRULLA-01"]["evento_id"] == en_campus["id"]
    assert unidades["PATRULLA-02"]["estado"] == "libre"
    _liberar_flota(monkeypatch)
    assert all(u["estado"] == "libre" for u in client.get(f"{API}/unidades", headers=OP).json())


def test_sin_unidades_libres_responde_409(client: Any, sensor: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    _liberar_flota(monkeypatch)
    for _ in range(3):
        evento = _evento_en(client, sensor, ITM)
        assert client.post(f"{API}/atenciones", json={"evento_id": evento["id"], "operador_id": "op.m"}, headers=OP).status_code == 201
    otro = _evento_en(client, sensor, ITM)
    r = client.post(f"{API}/atenciones", json={"evento_id": otro["id"], "operador_id": "op.m"}, headers=OP)
    assert r.status_code == 409 and "unidades libres" in r.json()["error"]["mensaje"]
    _liberar_flota(monkeypatch)


def test_sin_llegadas_no_abre_transaccion(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import atenciones

    _liberar_flota(monkeypatch)

    def _prohibida() -> None:
        raise AssertionError("no debía abrir una transacción de escritura")

    monkeypatch.setattr(atenciones, "transaccion", _prohibida)
    assert atenciones.resolver_llegadas() == []


def test_llegada_cierra_el_evento_y_avisa(client: Any, sensor: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import atenciones

    _liberar_flota(monkeypatch)
    evento = _evento_en(client, sensor, ITM)
    client.post(f"{API}/atenciones", json={"evento_id": evento["id"], "operador_id": "op.m"}, headers=OP)
    assert client.get(f"{API}/eventos/{evento['id']}", headers=OP).json()["resuelto_en"] is None
    _liberar_flota(monkeypatch)
    cerrado = client.get(f"{API}/eventos/{evento['id']}", headers=OP).json()
    assert cerrado["resuelto_en"] is not None and cerrado["estado_validacion"] == "validado"
    assert atenciones.resolver_llegadas() == []  # ya no queda nada por resolver


# ---------------------------------------------------------------- despacho en segundo plano


def test_despacho_responde_202_y_confirma_por_websocket(client: Any, evento_validado: dict[str, Any]) -> None:
    datos = {"evento_id": evento_validado["id"], "dependencia_destino": "Proteccion Civil", "operador_id": "op.m"}
    with client.websocket_connect(f"/ws/alertas?token={CLAVE_OPERADOR}") as ws:
        ws.receive_text()  # conexion.establecida
        r = client.post(f"{API}/despachos", json=datos, headers=OP)
        assert r.status_code == 202 and r.json()["estado_envio"] == "enviado"
        estados = [json.loads(ws.receive_text())["data"]["estado_envio"] for _ in range(2)]
    assert estados == ["enviado", "confirmado"]


# ---------------------------------------------------------------- cámara: validación previa


class _Camara(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/video"):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n\xff\xd8\xff\xd9\r\n")
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html>IP Webcam</html>")

    def log_message(self, *_: Any) -> None:
        pass


@pytest.fixture
def camara_local() -> Any:
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), _Camara)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{servidor.server_address[1]}"
    servidor.shutdown()


def _puerto_cerrado() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_url_sin_ruta_se_completa_con_video(camara_local: str) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import fuente_video

    assert asyncio.run(fuente_video.resolver(camara_local)) == f"{camara_local}/video"
    assert fuente_video.candidatas("http://192.168.16.38")[0] == "http://192.168.16.38:8080/video"


def test_pagina_que_no_es_video_se_rechaza(camara_local: str) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.errores import CamaraInaccesible
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import fuente_video

    with pytest.raises(CamaraInaccesible, match="no es video"):
        asyncio.run(fuente_video.resolver(f"{camara_local}/pagina"))


def test_camara_que_no_responde_da_422_rapido_sin_lanzar_el_sensor(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import vinculacion

    def _no_lanzar(*_: Any, **__: Any) -> None:
        raise AssertionError("no debía lanzar el sensor")

    monkeypatch.setattr(vinculacion.subprocess, "Popen", _no_lanzar)
    cuerpo = {"url": f"http://127.0.0.1:{_puerto_cerrado()}/video", "nombre": "Prueba", "lat": 21.01, "lng": -89.62}
    inicio = time.monotonic()
    r = client.post(f"{API}/camara-vinculada", json=cuerpo, headers=OP)
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "camara_inaccesible"
    assert time.monotonic() - inicio < 5


# ---------------------------------------------------------------- supervisor: sin congelar, con reconexión


class _Sensor:
    """Proceso falso. `ignora_sigterm` imita al sensor bloqueado abriendo una cámara."""

    pid = 424_242

    def __init__(self, comando: list[str], ignora_sigterm: bool = False, **_: Any) -> None:
        self.comando = comando
        self.ignora_sigterm = ignora_sigterm
        self.returncode: int | None = None
        self.stdout = iter(["cargando modelos\n"])
        self._fin = threading.Event()

    def poll(self) -> int | None:
        return self.returncode

    def morir(self, codigo: int) -> None:
        self.returncode = codigo
        self._fin.set()

    def wait(self, timeout: float | None = None) -> int:
        if not self._fin.wait(timeout):
            raise subprocess.TimeoutExpired("sentinelops", timeout or 0)
        return self.returncode or 0


@pytest.fixture
def sensores(monkeypatch: pytest.MonkeyPatch) -> Any:
    import signal

    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import vinculacion

    lanzados: list[_Sensor] = []
    opciones = {"ignora_sigterm": False}

    def _popen(comando: list[str], **kwargs: Any) -> _Sensor:
        lanzados.append(_Sensor(comando, **opciones))
        return lanzados[-1]

    def _killpg(pid: int, senal: int) -> None:
        sensor = lanzados[-1]
        if senal == signal.SIGKILL or not sensor.ignora_sigterm:
            sensor.morir(-senal)

    monkeypatch.setattr(vinculacion.subprocess, "Popen", _popen)
    monkeypatch.setattr(vinculacion.os, "killpg", _killpg)
    monkeypatch.setattr(vinculacion, "_ESPERAS_S", (0.05,))
    yield lanzados, opciones
    vinculacion.SUPERVISOR.desvincular()


def _vincular_demo(client: Any) -> dict[str, Any]:
    cuerpo = {"demo": True, "nombre": "Campus ITM", "lat": ITM["lat"], "lng": ITM["lng"]}
    r = client.post(f"{API}/camara-vinculada", json=cuerpo, headers=OP)
    assert r.status_code == 200, r.text
    return r.json()


def test_estado_no_se_congela_mientras_se_detiene_un_sensor_colgado(client: Any, sensores: Any) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services.vinculacion import SUPERVISOR

    lanzados, opciones = sensores
    opciones["ignora_sigterm"] = True
    _vincular_demo(client)
    lanzados[-1].ignora_sigterm = True

    deteniendo = threading.Thread(target=SUPERVISOR.desvincular)
    deteniendo.start()  # tardará ~3 s: SIGTERM ignorado, luego SIGKILL
    time.sleep(0.2)
    inicio = time.monotonic()
    r = client.get(f"{API}/camara-vinculada", headers=OP)
    assert r.status_code == 200 and time.monotonic() - inicio < 0.5
    assert deteniendo.is_alive()  # el estado respondió mientras la detención seguía
    deteniendo.join(timeout=10)
    assert lanzados[-1].returncode is not None


def test_sensor_caido_se_reconecta_solo(client: Any, sensores: Any) -> None:
    lanzados, _ = sensores
    estado = _vincular_demo(client)
    assert estado["estado"] == "conectando" and len(lanzados) == 1

    lanzados[0].morir(1)  # la cámara se cayó
    for _ in range(50):
        if len(lanzados) == 2:
            break
        time.sleep(0.05)
    assert len(lanzados) == 2, "el supervisor no relanzó el sensor"
    estado = client.get(f"{API}/camara-vinculada", headers=OP).json()
    assert estado["intento"] == 1 and estado["activa"] is True


# ---------------------------------------------------------------- migración


def test_migracion_resuelto_en_es_idempotente(tmp_path: Path) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services.db import _migrar

    ruta = tmp_path / "vieja.db"
    with sqlite3.connect(ruta) as conn:
        conn.executescript(
            """
            CREATE TABLE eventos_detectados (id INTEGER PRIMARY KEY, tipo_evento TEXT);
            CREATE TABLE atenciones_campo (id INTEGER PRIMARY KEY, evento_id INTEGER, estado TEXT, llegada_en DATETIME);
            INSERT INTO eventos_detectados VALUES (1, 'merodeo'), (2, 'merodeo');
            INSERT INTO atenciones_campo VALUES (1, 1, 'resuelto', '2026-10-06 18:00:00');
            """
        )
    engine = sa.create_engine(f"sqlite:///{ruta}")
    _migrar(engine)
    _migrar(engine)  # segunda vez: no falla ni duplica
    with engine.connect() as conn:
        filas = dict(conn.execute(sa.text("SELECT id, resuelto_en FROM eventos_detectados")).all())
    assert filas[1] is not None and filas[2] is None
    engine.dispose()
