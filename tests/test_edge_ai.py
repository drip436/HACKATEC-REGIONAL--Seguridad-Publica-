"""Contrato Edge AI (EDGE_AI/sentinelops) <-> backend.

Usa el código real del sensor (config + notifier) contra la API en proceso. No
carga YOLO ni OpenCV: la cámara queda fuera; se prueba lo que viaja por la red.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from .conftest import CLAVE_SENSOR

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "EDGE_AI"))
pytest.importorskip("requests")

from sentinelops import config as edge_config  # noqa: E402
from sentinelops import notifier as edge_notifier  # noqa: E402

_segundos = iter(range(10_000))


def _evento(**cambios: Any) -> edge_notifier.AlertEvent:
    cfg = edge_config.Config()
    datos: dict[str, Any] = {
        "sensor_id": cfg.sensor_id,
        "event_type": cfg.event_type,
        "severity": cfg.event_severity,
        "lat": cfg.lat,
        "lng": cfg.lng,
        "timestamp": datetime.now(timezone.utc) - timedelta(minutes=30, seconds=next(_segundos)),
        "evidence_url": "/static/capturas/evento_1.jpg",
        "detected_class": cfg.detected_class_label,
        "confidence": 0.876,
        "bounding_box": (120, 80, 240, 310),
    }
    datos.update(cambios)
    return edge_notifier.AlertEvent(**datos)


class _SesionHaciaTestClient:
    """Sustituye a requests.Session: reenvía los POST del notificador a la API en proceso."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.headers: dict[str, str] = {}
        self.respuestas: list[Any] = []

    def post(self, url: str, json: Any, timeout: Any) -> Any:
        r = self._client.post(urlsplit(url).path, json=json, headers=self.headers)
        # TestClient devuelve respuestas httpx; el notificador usa la interfaz de requests.
        r.ok, r.reason = r.is_success, r.reason_phrase
        self.respuestas.append(r)
        return r

    def close(self) -> None:
        pass


def _notificador(client: Any, api_key: str | None) -> tuple[edge_notifier.AlertNotifier, _SesionHaciaTestClient]:
    cfg = edge_config.Config()
    n = edge_notifier.AlertNotifier(
        url=cfg.backend_url, timeout=cfg.http_timeout, max_retries=2, backoff_seconds=0, api_key=api_key
    )
    sesion = _SesionHaciaTestClient(client)
    sesion.headers.update(n._session.headers)
    n._session = sesion  # type: ignore[assignment]
    return n, sesion


def test_url_por_defecto_apunta_a_la_ruta_real(client: Any) -> None:
    ruta = urlsplit(edge_config.Config().backend_url).path
    assert ruta == "/api/v1/eventos"
    assert "post" in client.get("/openapi.json").json()["paths"][ruta]


def test_alerta_del_sensor_se_registra(client: Any) -> None:
    n, sesion = _notificador(client, CLAVE_SENSOR)
    n._send(_evento())
    assert [r.status_code for r in sesion.respuestas] == [201]
    evento = sesion.respuestas[0].json()
    assert evento["tipo_evento"] == "traspaso_perimetro"
    assert evento["nivel_prioridad"] == "alta"
    assert evento["sensor_codigo"] == edge_config.Config().sensor_id
    assert evento["metadata_json"]["confianza"] == 0.88


def test_reintento_del_sensor_no_duplica(client: Any) -> None:
    n, sesion = _notificador(client, CLAVE_SENSOR)
    evento = _evento()
    n._send(evento)
    n._send(evento)  # mismo evento reenviado (p. ej. tras un timeout)
    primero, segundo = sesion.respuestas
    assert (primero.status_code, segundo.status_code) == (201, 200)
    assert primero.json()["id"] == segundo.json()["id"]


def test_sin_clave_no_reintenta_en_vano(client: Any, caplog: pytest.LogCaptureFixture) -> None:
    n, sesion = _notificador(client, api_key=None)
    n._send(_evento())
    assert [r.status_code for r in sesion.respuestas] == [401]  # un solo intento, no tres
    assert "no_autenticado" in caplog.text


def test_payload_invalido_muestra_el_motivo(client: Any, caplog: pytest.LogCaptureFixture) -> None:
    n, sesion = _notificador(client, CLAVE_SENSOR)
    n._send(_evento(timestamp=datetime.now(timezone.utc) + timedelta(hours=2)))  # reloj adelantado
    assert [r.status_code for r in sesion.respuestas] == [422]
    assert "futuro" in caplog.text


@pytest.mark.parametrize("bbox", [(0, 0, 1, 1), (1279, 0, 1280, 720)])
def test_cajas_validas_del_detector_se_aceptan(client: Any, bbox: tuple[int, int, int, int]) -> None:
    n, sesion = _notificador(client, CLAVE_SENSOR)
    n._send(_evento(bounding_box=bbox))
    assert sesion.respuestas[0].status_code == 201
