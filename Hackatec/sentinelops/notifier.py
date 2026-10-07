"""Construcción del payload y envío HTTP no bloqueante al backend."""

from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)

_MAX_PENDING = 16


@dataclass(frozen=True, slots=True)
class AlertEvent:
    """Evento de intrusión listo para serializar según el contrato del backend."""

    sensor_id: str
    event_type: str
    severity: str
    lat: float
    lng: float
    timestamp: datetime
    evidence_url: str
    detected_class: str
    confidence: float
    bounding_box: tuple[int, int, int, int]

    def to_payload(self) -> dict[str, Any]:
        return {
            "sensor_id": self.sensor_id,
            "tipo_evento": self.event_type,
            "severidad": self.severity,
            "coordenadas": {"lat": self.lat, "lng": self.lng},
            "timestamp": _iso_utc(self.timestamp),
            "evidencia_url": self.evidence_url,
            "metadatos": {
                "clase_detectada": self.detected_class,
                "confianza": round(self.confidence, 2),
                "bounding_box": [int(value) for value in self.bounding_box],
            },
        }


def _iso_utc(moment: datetime) -> str:
    """ISO 8601 en UTC con sufijo `Z` y sin microsegundos."""
    utc = moment.astimezone(timezone.utc).replace(microsecond=0)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


class AlertNotifier:
    """Envía alertas en un pool de hilos; nunca propaga errores al caller."""

    def __init__(
        self,
        url: str,
        api_key: str | None,
        timeout: tuple[float, float],
        max_retries: int,
        backoff_seconds: float,
        max_workers: int = 2,
    ) -> None:
        self._url = url
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._session = requests.Session()
        if api_key:
            self._session.headers["X-Sensor-Key"] = api_key
        else:
            LOGGER.warning("SENTINEL_SENSOR_API_KEY no definida: el backend responderá 401")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="notifier"
        )
        self._pending: set[Future[None]] = set()

    def send_async(self, event: AlertEvent) -> None:
        """Encola el envío y regresa de inmediato."""
        self._pending = {future for future in self._pending if not future.done()}
        if len(self._pending) >= _MAX_PENDING:
            # El backend está caído o muy lento: descartar es preferible a
            # acumular memoria y retrasar alertas más recientes.
            LOGGER.error(
                "Cola de envíos saturada (%d pendientes); se descarta la alerta %s",
                len(self._pending),
                event.evidence_url,
            )
            return

        future = self._executor.submit(self._send, event)
        self._pending.add(future)

    def _send(self, event: AlertEvent) -> None:
        payload = event.to_payload()
        for attempt in range(1, self._max_retries + 2):
            try:
                response = self._session.post(
                    self._url, json=payload, timeout=self._timeout
                )
                if response.ok:
                    LOGGER.info(
                        "Alerta enviada (%s) para %s",
                        response.status_code,
                        event.evidence_url,
                    )
                    return
                if response.status_code == 422:
                    LOGGER.error(
                        "422: el backend rechazó el payload: %s | payload=%s",
                        self._describe_422(response),
                        payload,
                    )
                    return
                if 400 <= response.status_code < 500:
                    # Error del cliente (401, 404, 409...): reintentar no lo arregla.
                    LOGGER.error(
                        "Rechazo %s sin reintento: %s",
                        response.status_code,
                        response.text[:300],
                    )
                    return
                LOGGER.warning(
                    "Backend respondió %s en intento %d/%d",
                    response.status_code,
                    attempt,
                    self._max_retries + 1,
                )
            except requests.RequestException as error:
                LOGGER.warning(
                    "Fallo de red en intento %d/%d: %s",
                    attempt,
                    self._max_retries + 1,
                    error,
                )

            if attempt <= self._max_retries:
                time.sleep(self._backoff_seconds * (2 ** (attempt - 1)))

        LOGGER.error(
            "Alerta descartada tras %d intentos: %s",
            self._max_retries + 1,
            event.evidence_url,
        )

    @staticmethod
    def _describe_422(response: requests.Response) -> str:
        """Resume los errores de validación Pydantic del backend."""
        try:
            errores = response.json()["error"]["detalle"]["errores"]
            return "; ".join(f"{e['campo']}: {e['mensaje']}" for e in errores)
        except (ValueError, KeyError, TypeError):
            return response.text[:300]

    def shutdown(self) -> None:
        """Espera a los envíos en vuelo y cierra la sesión HTTP."""
        self._executor.shutdown(wait=True)
        self._session.close()
        LOGGER.info("Notificador cerrado")
