"""Dibujo del polígono, bounding boxes y HUD de estado."""

from __future__ import annotations

import cv2
import numpy as np

from .detector import Detection
from .zone import RestrictedZone, ZoneEvaluation

_COLOR_SAFE = (0, 200, 0)
_COLOR_ALERT = (0, 0, 255)
_COLOR_TEXT = (255, 255, 255)
_COLOR_TEXT_BG = (0, 0, 0)
_ZONE_FILL_ALPHA = 0.25
_FONT = cv2.FONT_HERSHEY_SIMPLEX


def annotate(
    frame: np.ndarray,
    zone: RestrictedZone,
    evaluation: ZoneEvaluation,
    fps: float,
    cooldown_remaining: float,
) -> np.ndarray:
    """Devuelve una copia anotada del frame; nunca modifica el original."""
    canvas = frame.copy()
    _draw_zone(canvas, zone, breached=evaluation.breached)
    for detection in evaluation.outside:
        _draw_detection(canvas, detection, color=_COLOR_SAFE)
    for detection in evaluation.inside:
        _draw_detection(canvas, detection, color=_COLOR_ALERT)
    _draw_hud(canvas, evaluation, fps, cooldown_remaining)
    return canvas


def _draw_zone(frame: np.ndarray, zone: RestrictedZone, *, breached: bool) -> None:
    color = _COLOR_ALERT if breached else _COLOR_SAFE
    fill = frame.copy()
    cv2.fillPoly(fill, [zone.contour], color)
    cv2.addWeighted(fill, _ZONE_FILL_ALPHA, frame, 1 - _ZONE_FILL_ALPHA, 0, dst=frame)
    cv2.polylines(frame, [zone.contour], isClosed=True, color=color, thickness=2)

    anchor = zone.contour.reshape(-1, 2).min(axis=0)
    _draw_label(frame, "ZONA RESTRINGIDA", (int(anchor[0]), int(anchor[1]) - 8), color)


def _draw_detection(
    frame: np.ndarray,
    detection: Detection,
    *,
    color: tuple[int, int, int],
) -> None:
    x1, y1, x2, y2 = detection.bbox
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    cv2.circle(frame, detection.foot_point, 5, color, -1)
    _draw_label(frame, f"persona {detection.confidence:.2f}", (x1, y1 - 8), color)


def _draw_hud(
    frame: np.ndarray,
    evaluation: ZoneEvaluation,
    fps: float,
    cooldown_remaining: float,
) -> None:
    status = "INTRUSION" if evaluation.breached else "VIGILANDO"
    color = _COLOR_ALERT if evaluation.breached else _COLOR_SAFE
    intruders = len(evaluation.inside)
    total = intruders + len(evaluation.outside)
    lines = [
        f"{status} | personas: {intruders}/{total}",
        f"FPS: {fps:.1f}",
    ]
    if cooldown_remaining > 0:
        lines.append(f"cooldown: {cooldown_remaining:.1f}s")

    for row, text in enumerate(lines):
        _draw_label(frame, text, (12, 28 + row * 26), color if row == 0 else _COLOR_TEXT)


def _draw_label(
    frame: np.ndarray,
    text: str,
    origin: tuple[int, int],
    color: tuple[int, int, int],
) -> None:
    """Texto con fondo opaco para que sea legible sobre cualquier escena."""
    x, y = origin
    y = max(y, 18)
    (width, height), baseline = cv2.getTextSize(text, _FONT, 0.6, 1)
    cv2.rectangle(
        frame,
        (x - 3, y - height - baseline - 2),
        (x + width + 3, y + baseline - 1),
        _COLOR_TEXT_BG,
        -1,
    )
    cv2.putText(frame, text, (x, y - baseline + 1), _FONT, 0.6, color, 1, cv2.LINE_AA)
