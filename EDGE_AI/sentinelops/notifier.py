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
# 4xx que sí vale la pena reintentar (timeout del servidor / rate limit). El resto
# de 4xx (401 clave, 404 ruta, 409 sensor inactivo, 422 payload) no se corrige
# repitiendo el mismo mensaje.
_REINTENTABLES_4XX = {408, 429}


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
    # Nombre del lugar; el backend lo usa al autorregistrar una cámara nueva.
    ubicacion: str | None = None

    def to_payload(self) -> dict[str, Any]:
        extra = {"ubicacion": self.ubicacion} if self.ubicacion else {}
        return {
            **extra,
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
        timeout: tuple[float, float],
        max_retries: int,
        backoff_seconds: float,
        api_key: str | None = None,
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
            LOGGER.warning("Sin SENTINEL_SENSOR_API_KEY: el backend rechazará las alertas con 401.")
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
        # El payload se arma una sola vez: los reintentos llevan el mismo hash y el
        # backend los reconoce como el mismo evento (200 + X-Idempotent-Replay).
        payload = event.to_payload()
        for attempt in range(1, self._max_retries + 2):
            try:
                response = self._session.post(
                    self._url, json=payload, timeout=self._timeout
                )
                if response.ok:
                    replay = response.headers.get("X-Idempotent-Replay") == "true"
                    LOGGER.info(
                        "Alerta %s (%s) id=%s para %s",
                        "ya registrada" if replay else "enviada",
                        response.status_code,
                        _campo(response, "id"),
                        event.evidence_url,
                    )
                    return
                if 400 <= response.status_code < 500 and response.status_code not in _REINTENTABLES_4XX:
                    LOGGER.error(
                        "Backend rechazó la alerta (%s): %s. No se reintenta: %s",
                        response.status_code,
                        _motivo(response),
                        event.evidence_url,
                    )
                    return
                LOGGER.warning(
                    "Backend respondió %s en intento %d/%d: %s",
                    response.status_code,
                    attempt,
                    self._max_retries + 1,
                    _motivo(response),
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

    def check_backend(self) -> bool:
        """Consulta `/health` del backend al arrancar, solo para avisar en el log."""
        base = self._url.split("/api/", 1)[0]
        try:
            response = self._session.get(f"{base}/api/v1/health", timeout=self._timeout)
            if response.ok:
                LOGGER.info("Backend disponible en %s", base)
                return True
            LOGGER.warning("El backend respondió %s en /api/v1/health", response.status_code)
        except requests.RequestException as error:
            LOGGER.warning("Backend no disponible (%s); las alertas se reintentarán al enviarse.", error)
        return False

    def shutdown(self) -> None:
        """Espera a los envíos en vuelo y cierra la sesión HTTP."""
        self._executor.shutdown(wait=True)
        self._session.close()
        LOGGER.info("Notificador cerrado")


def _campo(response: requests.Response, nombre: str) -> Any:
    try:
        return response.json().get(nombre)
    except ValueError:
        return None


def _motivo(response: requests.Response) -> str:
    """Extrae el mensaje del formato de error del backend: {"error": {codigo, mensaje, detalle}}."""
    try:
        error = response.json().get("error", {})
    except ValueError:
        return response.text[:200] or response.reason
    errores = error.get("detalle", {}).get("errores") if isinstance(error.get("detalle"), dict) else None
    if errores:
        return "; ".join(f"{e.get('campo')}: {e.get('mensaje')}" for e in errores)[:300]
    return f"{error.get('codigo', '?')}: {error.get('mensaje', '')}"
