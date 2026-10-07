"""Orquestación del bucle de vigilancia de SentinelOps.

Flujo: calibración interactiva del polígono con el ratón ('c' confirma) ->
bucle de inferencia YOLOv8-Pose -> máquina de estados de 5 reglas -> HUD con
esqueletos y polígono en verde / amarillo / rojo -> alerta al backend.
"""

from __future__ import annotations

import argparse
import logging
import signal
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType
from typing import Any

import cv2
import numpy as np

from . import overlay
from .camera import Camera, CameraError
from .config import Config, build_config
from .detector import Detection, ThreatDetector
from .evidence import EvidenceError, EvidenceStore
from .notifier import AlertEvent, AlertNotifier
from .stream_server import FramePublisher, StreamServer
from .zone import (
    COLLISION_HOLD_SECONDS,
    CROUCH_HOLD_SECONDS,
    HANDS_UP_HOLD_SECONDS,
    PERSON_LOITER_SECONDS,
    PROXIMITY_SECONDS,
    VEHICLE_LOITER_SECONDS,
    RestrictedZone,
    ThreatAssessment,
    ThreatAssessor,
    ThreatLevel,
    ThreatRule,
)

LOGGER = logging.getLogger("sentinelops")

_WINDOW_NAME = "SentinelOps"
_CALIBRATION_WINDOW = "SentinelOps - Calibracion de zona"
_FPS_SMOOTHING = 0.9
_INFERENCE_EVERY = 3  # frame skipping: 1 inferencia cada N frames

# Fuente por defecto. Acepta un índice de cámara (0, 1, …), la ruta de un
# video o una URL de stream (la app IP Webcam publica en
# http://<IP>:8080/video).
DEFAULT_SOURCE: str | int = str(Path(__file__).resolve().parents[1] / "asalto.mp4")

# Claves de la CLI que no pertenecen a `Config` y no van a build_config.
_NON_CONFIG_ARGS = (
    "source",
    "person_loiter",
    "vehicle_loiter",
    "proximity",
    "hands_up_hold",
    "crouch_hold",
    "collision_hold",
    "inference_every",
    "calibrate",
    "zona_completa",
)


@dataclass(frozen=True, slots=True)
class RuntimeOptions:
    """Parámetros del bucle que no forman parte de la configuración persistente."""

    source: str | int
    person_loiter_seconds: float
    vehicle_loiter_seconds: float
    proximity_seconds: float
    hands_up_hold_seconds: float
    crouch_hold_seconds: float
    collision_hold_seconds: float
    inference_every: int
    calibrate: bool
    # Todo el cuadro es la zona vigilada (cámara vinculada desde el panel, sin ratón).
    zona_completa: bool = False


class _ShutdownFlag:
    """Convierte SIGINT/SIGTERM en una salida ordenada del bucle."""

    def __init__(self) -> None:
        self.requested = False

    def install(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle)

    def _handle(self, signum: int, frame: FrameType | None) -> None:
        print(f"\n[!] Señal {signal.Signals(signum).name} recibida; cerrando…")
        self.requested = True


class _PolygonBuilder:
    """Acumula los clics del ratón que definen el polígono de vigilancia."""

    def __init__(self) -> None:
        self.points: list[tuple[int, int]] = []

    def on_mouse(self, event: int, x: int, y: int, flags: int, param: Any) -> None:
        """Callback de `cv2.setMouseCallback`: izquierdo añade, derecho deshace."""
        if event == cv2.EVENT_LBUTTONDOWN:
            self.points.append((int(x), int(y)))
        elif event == cv2.EVENT_RBUTTONDOWN and self.points:
            self.points.pop()

    def clear(self) -> None:
        self.points.clear()

    @property
    def is_valid(self) -> bool:
        return len(self.points) >= 3


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sentinelops",
        description=(
            "Sensor Edge AI de comportamiento sospechoso (YOLOv8-Pose + OpenCV)."
        ),
    )
    parser.add_argument("--camera", type=int, dest="camera_index")
    parser.add_argument(
        "--source",
        dest="source",
        help="Índice de cámara, ruta de video o URL del stream.",
    )
    parser.add_argument("--backend-url", dest="backend_url")
    parser.add_argument("--conf", type=float, dest="conf_threshold")
    parser.add_argument(
        "--weapon-conf",
        type=float,
        dest="weapon_conf_threshold",
        help="Umbral para la clase 43 (cuchillo).",
    )
    parser.add_argument(
        "--vehicle-conf",
        type=float,
        dest="vehicle_conf_threshold",
        help="Umbral para las clases 2 y 3 (carro, moto).",
    )
    parser.add_argument("--pose-model", dest="pose_model_path")
    parser.add_argument(
        "--object-model",
        dest="object_model_path",
        help="Modelo COCO para vehículo y arma (el de pose sólo ve personas).",
    )
    parser.add_argument(
        "--no-objects",
        dest="object_model_path",
        action="store_const",
        const="",
        help="Sólo pose: desactiva la detección de vehículos y armas.",
    )
    parser.add_argument(
        "--no-track",
        dest="enable_tracking",
        action="store_const",
        const=False,
        help="Desactiva el tracker; la identidad se resuelve por IoU.",
    )
    parser.add_argument(
        "--loiter-person",
        type=float,
        dest="person_loiter",
        help=f"Segundos de persona en zona -> AMARILLO. Def: {PERSON_LOITER_SECONDS}.",
    )
    parser.add_argument(
        "--loiter-vehicle",
        type=float,
        dest="vehicle_loiter",
        help=f"Segundos de vehículo en zona -> AMARILLO. Def: {VEHICLE_LOITER_SECONDS}.",
    )
    parser.add_argument(
        "--proximity",
        type=float,
        dest="proximity",
        help=f"Segundos de proximidad invasiva -> ROJO. Def: {PROXIMITY_SECONDS}.",
    )
    parser.add_argument(
        "--hands-up-hold",
        type=float,
        dest="hands_up_hold",
        help=f"Segundos con ambos brazos arriba -> ROJO. Def: {HANDS_UP_HOLD_SECONDS}.",
    )
    parser.add_argument(
        "--crouch-hold",
        type=float,
        dest="crouch_hold",
        help=f"Segundos agachado en la zona -> ROJO. Def: {CROUCH_HOLD_SECONDS}.",
    )
    parser.add_argument(
        "--collision-hold",
        type=float,
        dest="collision_hold",
        help=f"Segundos quietos y en contacto tras el impacto -> ROJO. Def: {COLLISION_HOLD_SECONDS}.",
    )
    parser.add_argument(
        "--inference-every",
        type=int,
        dest="inference_every",
        help=f"Inferencia 1 de cada N frames. Def: {_INFERENCE_EVERY}.",
    )
    parser.add_argument("--cooldown", type=float, dest="cooldown_seconds")
    parser.add_argument("--evidence-dir", type=Path, dest="evidence_dir")
    parser.add_argument("--sensor-id", dest="sensor_id")
    parser.add_argument("--lat", type=float, dest="lat", help="Latitud de la cámara (punto en el mapa).")
    parser.add_argument("--lng", type=float, dest="lng", help="Longitud de la cámara.")
    parser.add_argument("--ubicacion", dest="ubicacion", help="Nombre del lugar que vigila la cámara.")
    parser.add_argument(
        "--zona-completa",
        dest="zona_completa",
        action="store_true",
        default=None,
        help="Todo el cuadro es la zona vigilada (sin calibrar el polígono).",
    )
    parser.add_argument("--stream-port", type=int, dest="stream_port", help="Puerto del video anotado (8090).")
    parser.add_argument(
        "--no-stream",
        dest="stream_enabled",
        action="store_const",
        const=False,
        help="No publica el video anotado para el panel.",
    )
    parser.add_argument("--log-level", dest="log_level")
    parser.add_argument(
        "--no-calibrate",
        dest="calibrate",
        action="store_const",
        const=False,
        help="Omite el dibujo del polígono y usa ZONE_POLYGON de config.py.",
    )
    parser.add_argument(
        "--no-preview",
        dest="show_preview",
        action="store_const",
        const=False,
        help="Ejecuta sin ventana de video (modo headless; implica --no-calibrate).",
    )
    return parser.parse_args(argv)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,  # ignora el secuestro del logging que hace Ultralytics
    )


def _resolve_source(raw: str | None, camera_index: int | None) -> str | int:
    """Precedencia: `--source` (índice, ruta o URL) > `--camera` > DEFAULT_SOURCE."""
    if raw is not None:
        return int(raw) if raw.isdigit() else raw
    if camera_index is not None:
        return camera_index
    return DEFAULT_SOURCE


# --- 1. Calibración interactiva del polígono de vigilancia -----------------
def calibrate_zone(
    snapshot: np.ndarray,
    fallback: Sequence[tuple[int, int]],
) -> tuple[tuple[int, int], ...] | None:
    """Deja al usuario dibujar el polígono sobre el primer frame real.

    Devuelve los vértices confirmados con 'c', o `None` si el usuario aborta.
    El frame se congela a propósito: así los puntos corresponden exactamente
    a las coordenadas del plano que después alimenta a `RestrictedZone`.
    """
    builder = _PolygonBuilder()
    cv2.namedWindow(_CALIBRATION_WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(_CALIBRATION_WINDOW, snapshot.shape[1], snapshot.shape[0])
    cv2.setMouseCallback(_CALIBRATION_WINDOW, builder.on_mouse)

    print(
        "\n=== CALIBRACION DE LA ZONA DE VIGILANCIA ===\n"
        "  clic izq : agregar vertice\n"
        "  clic der : deshacer ultimo vertice\n"
        "  r        : reiniciar\n"
        "  d        : usar el poligono por defecto de config.py\n"
        "  c        : confirmar y arrancar la vigilancia (minimo 3 puntos)\n"
        "  q / ESC  : abortar\n"
    )

    try:
        while True:
            canvas = _draw_calibration(snapshot, builder)
            cv2.imshow(_CALIBRATION_WINDOW, canvas)
            key = cv2.waitKey(20) & 0xFF

            if key in (ord("q"), 27):
                return None
            if key == ord("r"):
                builder.clear()
            elif key == ord("d"):
                print(f"[i] Zona por defecto: {tuple(fallback)}")
                return tuple(fallback)
            elif key == ord("c"):
                if builder.is_valid:
                    points = tuple(builder.points)
                    print(f"[i] Zona confirmada con {len(points)} vertices: {points}")
                    return points
                print("[!] Necesitas al menos 3 puntos para cerrar el poligono.")
    finally:
        cv2.destroyWindow(_CALIBRATION_WINDOW)
        cv2.waitKey(1)  # fuerza el repintado del gestor de ventanas


def _draw_calibration(snapshot: np.ndarray, builder: _PolygonBuilder) -> np.ndarray:
    """Previsualiza el polígono en construcción sobre el frame congelado."""
    canvas = snapshot.copy()
    color = (0, 215, 255)
    points = builder.points

    if len(points) >= 2:
        cv2.polylines(
            canvas,
            [np.asarray(points, dtype=np.int32).reshape(-1, 1, 2)],
            isClosed=builder.is_valid,
            color=color,
            thickness=2,
        )
    if builder.is_valid:
        fill = canvas.copy()
        cv2.fillPoly(fill, [np.asarray(points, dtype=np.int32).reshape(-1, 1, 2)], color)
        cv2.addWeighted(fill, 0.25, canvas, 0.75, 0, dst=canvas)

    for index, point in enumerate(points):
        cv2.circle(canvas, point, 6, color, -1)
        cv2.putText(
            canvas,
            str(index + 1),
            (point[0] + 9, point[1] - 9),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
            cv2.LINE_AA,
        )

    status = (
        f"{len(points)} vertices | 'c' confirmar"
        if builder.is_valid
        else f"{len(points)} vertices | faltan {3 - len(points)} para cerrar"
    )
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 34), (0, 0, 0), -1)
    cv2.putText(
        canvas,
        f"CLIC IZQ: vertice | DER: deshacer | r: reset | d: default | {status}",
        (10, 23),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return canvas


# --- 2. Bucle de vigilancia ------------------------------------------------
def run(config: Config, options: RuntimeOptions) -> int:
    shutdown = _ShutdownFlag()
    shutdown.install()

    print("-> Inicializando IA (YOLOv8-Pose + COCO: persona, vehiculo, arma)...")
    detector = ThreatDetector(
        pose_model_path=config.pose_model_path,
        object_model_path=config.object_model_path or None,
        conf_threshold=config.conf_threshold,
        weapon_conf_threshold=config.weapon_conf_threshold,
        vehicle_conf_threshold=config.vehicle_conf_threshold,
        track=config.enable_tracking,
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

    publisher = FramePublisher()
    servidor: StreamServer | None = None
    if config.stream_enabled:
        try:
            servidor = StreamServer(publisher, config.stream_port, config.stream_token, host=config.stream_host)
            servidor.start()
        except OSError as error:
            LOGGER.error("No se pudo abrir el puerto %d del video: %s", config.stream_port, error)
    publisher.actualizar_estado(
        en_linea=False,
        sensor_id=config.sensor_id,
        ubicacion=config.ubicacion,
        lat=config.lat,
        lng=config.lng,
        fuente=str(options.source),
    )
    alertas_enviadas = 0
    ultima_alerta: dict[str, str] | None = None

    camera = Camera(
        index=options.source,
        width=config.frame_width,
        height=config.frame_height,
        max_failures=config.read_max_failures,
    )

    last_alert_at = -float("inf")
    last_alert_level = ThreatLevel.SAFE
    last_alert_rules: tuple[ThreatRule, ...] = ()
    safe_since: float | None = None
    fps = 0.0
    previous_tick = time.monotonic()
    frame_counter = 0
    assessment: ThreatAssessment | None = None

    try:
        with camera:
            print(f"✅ Fuente de video conectada: {options.source}")

            # --- Calibración: el primer frame define el polígono ---
            snapshot = camera.read()
            if options.zona_completa:
                alto, ancho = snapshot.shape[:2]
                points = ((0, 0), (ancho - 1, 0), (ancho - 1, alto - 1), (0, alto - 1))
                print("-> Zona vigilada: cuadro completo")
            elif options.calibrate:
                points = calibrate_zone(snapshot, config.zone_polygon)
                if points is None:
                    print("[i] Calibración cancelada; no se inicia la vigilancia.")
                    return 0
            else:
                points = tuple(config.zone_polygon)
                print(f"-> Zona fija desde config.py: {points}")

            restricted_zone = RestrictedZone(points)
            assessor = ThreatAssessor(
                zone=restricted_zone,
                person_loiter_seconds=options.person_loiter_seconds,
                vehicle_loiter_seconds=options.vehicle_loiter_seconds,
                proximity_seconds=options.proximity_seconds,
                hands_up_hold_seconds=options.hands_up_hold_seconds,
                crouch_hold_seconds=options.crouch_hold_seconds,
                collision_hold_seconds=options.collision_hold_seconds,
            )

            # El stream siguió llenando el búfer durante la calibración.
            for _ in range(5):
                camera.read()
            previous_tick = time.monotonic()

            print("-> Vigilancia activa. Pulsa 'q' sobre la ventana para salir.")
            LOGGER.info(
                "Vigilancia iniciada | sensor=%s backend=%s cooldown=%.1fs "
                "merodeo=%.1fs vehiculo=%.1fs proximidad=%.1fs zona=%d vertices",
                config.sensor_id,
                config.backend_url,
                config.cooldown_seconds,
                options.person_loiter_seconds,
                options.vehicle_loiter_seconds,
                options.proximity_seconds,
                len(points),
            )

            while not shutdown.requested:
                frame = camera.read()
                now = time.monotonic()

                # --- Frame skipping: inferencia 1 de cada N ---
                frame_counter += 1
                if frame_counter % options.inference_every == 0 or assessment is None:
                    detections = detector.detect(frame)
                    assessment = assessor.assess(detections, now)

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
                    frame, restricted_zone, assessment, fps, cooldown_remaining
                )

                # Una escalada (AMARILLO -> ROJO) o una regla nueva ignoran el
                # cooldown: es justo lo que el operador necesita ver al instante.
                rules = assessment.rules
                escalated = assessment.level > last_alert_level or (
                    assessment.is_alertable
                    and any(rule not in last_alert_rules for rule in rules)
                )
                if assessment.is_alertable and (cooldown_remaining == 0.0 or escalated):
                    last_alert_at = now
                    last_alert_level = assessment.level
                    last_alert_rules = rules
                    if _raise_alert(config, store, notifier, annotated, assessment):
                        alertas_enviadas += 1
                        ultima_alerta = {
                            "nivel": assessment.level.name.lower(),
                            "regla": assessment.reason,
                            "tipo": assessment.event_type,
                            "severidad": assessment.severity,
                            "momento": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        }
                elif assessment.level is ThreatLevel.SAFE:
                    # El incidente se "olvida" solo tras un cooldown completo en verde:
                    # un verde de un instante (alguien sale de cuadro, el video
                    # reinicia) no debe convertir la misma situación en alertas nuevas.
                    if safe_since is None:
                        safe_since = now
                    elif now - safe_since >= config.cooldown_seconds:
                        last_alert_level = ThreatLevel.SAFE
                        last_alert_rules = ()
                if assessment.level is not ThreatLevel.SAFE:
                    safe_since = None

                publisher.publicar(annotated)
                publisher.actualizar_estado(
                    en_linea=True,
                    nivel=assessment.level.name.lower(),
                    regla=assessment.reason if assessment.is_alertable else "",
                    personas=assessment.people_total,
                    vehiculos=assessment.vehicles_total,
                    arma=assessment.weapon_present,
                    fps=round(fps, 1),
                    alertas_enviadas=alertas_enviadas,
                    ultima_alerta=ultima_alerta,
                )

                if config.show_preview:
                    cv2.imshow(_WINDOW_NAME, annotated)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        print("\n[i] Salida solicitada por el usuario ('q')")
                        break
    except CameraError as error:
        print(f"\n❌ ERROR CRÍTICO DE CÁMARA: {error}")
        LOGGER.error("%s", error)
        return 1
    except Exception as error:  # noqa: BLE001 - el sensor nunca debe tirar traceback
        print(f"\n❌ ERROR FATAL INESPERADO: {error}")
        LOGGER.exception("Fallo no controlado en el bucle de vigilancia")
        return 1
    finally:
        publisher.actualizar_estado(en_linea=False)
        notifier.shutdown()
        if servidor is not None:
            servidor.stop()
        cv2.destroyAllWindows()

    LOGGER.info("Vigilancia terminada")
    return 0


def _raise_alert(
    config: Config,
    store: EvidenceStore,
    notifier: AlertNotifier,
    annotated_frame: np.ndarray,
    assessment: ThreatAssessment,
) -> bool:
    """Guarda la evidencia y encola el POST con la severidad de la regla."""
    trigger: Detection | None = assessment.trigger
    if trigger is None:
        return False

    try:
        evidence = store.save(annotated_frame)
    except (EvidenceError, OSError) as error:
        LOGGER.error("No se pudo guardar la evidencia: %s", error)
        return False

    event = AlertEvent(
        sensor_id=config.sensor_id,
        event_type=assessment.event_type,
        severity=assessment.severity,
        lat=config.lat,
        lng=config.lng,
        timestamp=datetime.now(timezone.utc),
        evidence_url=evidence.url,
        detected_class=trigger.backend_label,
        confidence=trigger.confidence,
        bounding_box=trigger.bbox,
        ubicacion=config.ubicacion or None,
    )
    LOGGER.warning(
        "ALERTA %s id=%d motivo=%s clase=%s conf=%.2f bbox=%s",
        assessment.level.label,
        evidence.event_id,
        assessment.reason,
        trigger.class_name,
        trigger.confidence,
        trigger.bbox,
    )
    notifier.send_async(event)
    return True


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        overrides: dict[str, Any] = vars(args)
        extra = {key: overrides.pop(key) for key in _NON_CONFIG_ARGS}
        # `--camera` sí es parte de Config; se lee antes de que build_config
        # lo sustituya por el valor por defecto.
        camera_index: int | None = overrides.get("camera_index")

        config = build_config(**overrides)
        configure_logging(config.log_level)

        inference_every = extra["inference_every"] or _INFERENCE_EVERY
        if inference_every < 1:
            raise ValueError("--inference-every debe ser >= 1")

        options = RuntimeOptions(
            source=_resolve_source(extra["source"], camera_index),
            person_loiter_seconds=extra["person_loiter"] or PERSON_LOITER_SECONDS,
            vehicle_loiter_seconds=extra["vehicle_loiter"] or VEHICLE_LOITER_SECONDS,
            proximity_seconds=extra["proximity"] or PROXIMITY_SECONDS,
            hands_up_hold_seconds=extra["hands_up_hold"] or HANDS_UP_HOLD_SECONDS,
            crouch_hold_seconds=extra["crouch_hold"] or CROUCH_HOLD_SECONDS,
            collision_hold_seconds=extra["collision_hold"] or COLLISION_HOLD_SECONDS,
            inference_every=inference_every,
            zona_completa=bool(extra["zona_completa"]),
            # Sin ventana no hay ratón: headless nunca calibra.
            calibrate=extra["calibrate"] is not False and config.show_preview,
        )
        return run(config, options)
    except Exception as error:  # noqa: BLE001
        print(f"\n❌ FALLO AL CONSTRUIR CONFIGURACIÓN: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
