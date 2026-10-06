"""Orquestación del bucle de vigilancia de SentinelOps."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType

import cv2

from . import overlay, zone as zone_module
from .camera import Camera, CameraError
from .config import Config, build_config
from .detector import PersonDetector
from .evidence import EvidenceError, EvidenceStore
from .notifier import AlertEvent, AlertNotifier

LOGGER = logging.getLogger("sentinelops")

_WINDOW_NAME = "SentinelOps"
_FPS_SMOOTHING = 0.9


class _ShutdownFlag:
    """Convierte SIGINT/SIGTERM en una salida ordenada del bucle."""

    def __init__(self) -> None:
        self.requested = False

    def install(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle)

    def _handle(self, signum: int, frame: FrameType | None) -> None:
        LOGGER.info("Señal %s recibida; cerrando…", signal.Signals(signum).name)
        self.requested = True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sentinelops",
        description="Sensor Edge AI de intrusión perimetral (YOLOv8n + OpenCV).",
    )
    parser.add_argument("--camera", type=int, dest="camera_index")
    parser.add_argument("--backend-url", dest="backend_url")
    parser.add_argument("--conf", type=float, dest="conf_threshold")
    parser.add_argument("--cooldown", type=float, dest="cooldown_seconds")
    parser.add_argument("--model", dest="model_path")
    parser.add_argument("--evidence-dir", type=Path, dest="evidence_dir")
    parser.add_argument("--sensor-id", dest="sensor_id")
    parser.add_argument("--log-level", dest="log_level")
    parser.add_argument(
        "--no-preview",
        dest="show_preview",
        action="store_const",
        const=False,
        help="Ejecuta sin ventana de video (modo headless).",
    )
    return parser.parse_args(argv)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def run(config: Config) -> int:
    shutdown = _ShutdownFlag()
    shutdown.install()

    restricted_zone = zone_module.RestrictedZone(config.zone_polygon)
    detector = PersonDetector(
        model_path=config.model_path,
        conf_threshold=config.conf_threshold,
        class_id=config.person_class_id,
    )
    store = EvidenceStore(
        directory=config.evidence_dir,
        url_prefix=config.evidence_url_prefix,
        jpeg_quality=config.evidence_jpeg_quality,
    )
    notifier = AlertNotifier(
        url=config.backend_url,
        timeout=config.http_timeout,
        max_retries=config.http_max_retries,
        backoff_seconds=config.http_backoff_seconds,
        api_key=config.sensor_api_key,
    )
    notifier.check_backend()

    camera = Camera(
        index=config.camera_index,
        width=config.frame_width,
        height=config.frame_height,
        max_failures=config.read_max_failures,
    )

    last_alert_at = -float("inf")
    fps = 0.0
    previous_tick = time.monotonic()

    try:
        with camera:
            LOGGER.info(
                "Vigilancia iniciada | sensor=%s backend=%s cooldown=%.1fs",
                config.sensor_id,
                config.backend_url,
                config.cooldown_seconds,
            )
            while not shutdown.requested:
                frame = camera.read()
                evaluation = zone_module.evaluate(restricted_zone, detector.detect(frame))

                now = time.monotonic()
                elapsed = now - previous_tick
                previous_tick = now
                if elapsed > 0:
                    instant_fps = 1.0 / elapsed
                    fps = (
                        instant_fps
                        if fps == 0.0
                        else fps * _FPS_SMOOTHING + instant_fps * (1 - _FPS_SMOOTHING)
                    )

                cooldown_remaining = max(
                    0.0, config.cooldown_seconds - (now - last_alert_at)
                )
                annotated = overlay.annotate(
                    frame, restricted_zone, evaluation, fps, cooldown_remaining
                )

                intruder = evaluation.primary_intruder
                if intruder is not None and cooldown_remaining == 0.0:
                    last_alert_at = now
                    _raise_alert(config, store, notifier, annotated, intruder)

                if config.show_preview:
                    cv2.imshow(_WINDOW_NAME, annotated)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        LOGGER.info("Salida solicitada con 'q'")
                        break
    except CameraError as error:
        LOGGER.error("%s", error)
        return 1
    finally:
        notifier.shutdown()
        if config.show_preview:
            cv2.destroyAllWindows()

    LOGGER.info("Vigilancia terminada")
    return 0


def _raise_alert(
    config: Config,
    store: EvidenceStore,
    notifier: AlertNotifier,
    annotated_frame,
    intruder,
) -> None:
    """Guarda evidencia y encola el POST. Ningún fallo detiene el video."""
    try:
        evidence = store.save(annotated_frame)
    except (EvidenceError, OSError) as error:
        LOGGER.error("No se pudo guardar la evidencia: %s", error)
        return

    event = AlertEvent(
        sensor_id=config.sensor_id,
        event_type=config.event_type,
        severity=config.event_severity,
        lat=config.lat,
        lng=config.lng,
        timestamp=datetime.now(timezone.utc),
        evidence_url=evidence.url,
        detected_class=config.detected_class_label,
        confidence=intruder.confidence,
        bounding_box=intruder.bbox,
    )
    LOGGER.warning(
        "INTRUSION id=%d conf=%.2f bbox=%s",
        evidence.event_id,
        intruder.confidence,
        intruder.bbox,
    )
    notifier.send_async(event)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = build_config(**vars(args))
    except ValueError as error:
        print(f"Configuración inválida: {error}", file=sys.stderr)
        return 2
    configure_logging(config.log_level)
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
