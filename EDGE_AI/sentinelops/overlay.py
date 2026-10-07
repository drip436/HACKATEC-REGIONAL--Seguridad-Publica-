"""Dibujo del polígono, esqueletos, bounding boxes y HUD del semáforo."""

from __future__ import annotations

import cv2
import numpy as np

from .detector import (
    KEYPOINT_COUNT,
    LEFT_WRIST,
    NOSE,
    RIGHT_WRIST,
    SKELETON_EDGES,
    Detection,
)
from .zone import RestrictedZone, ThreatAssessment, ThreatLevel

_COLOR_NEUTRAL = (180, 180, 180)
_COLOR_WEAPON = (0, 0, 255)
_COLOR_SKELETON = (255, 200, 0)
_COLOR_JOINT = (255, 255, 255)
_COLOR_HIGHLIGHT = (0, 0, 255)
_COLOR_TEXT = (255, 255, 255)
_COLOR_TEXT_BG = (0, 0, 0)
_ZONE_FILL_ALPHA = 0.25
_FONT = cv2.FONT_HERSHEY_SIMPLEX


def annotate(
    frame: np.ndarray,
    zone: RestrictedZone,
    assessment: ThreatAssessment,
    fps: float,
    cooldown_remaining: float,
) -> np.ndarray:
    """Devuelve una copia anotada del frame; nunca modifica el original."""
    canvas = frame.copy()
    level_color = assessment.level.color

    _draw_zone(canvas, zone, level_color)

    for detection in assessment.vehicles_outside:
        _draw_detection(canvas, detection, _COLOR_NEUTRAL)
    for detection in assessment.vehicles_inside:
        _draw_detection(canvas, detection, level_color)
    for detection in assessment.people_outside:
        _draw_detection(canvas, detection, _COLOR_NEUTRAL)
        _draw_skeleton(canvas, detection, _COLOR_SKELETON)
    for detection in assessment.people_inside:
        _draw_detection(canvas, detection, level_color)
        _draw_skeleton(canvas, detection, _COLOR_SKELETON)
    for detection in assessment.weapons:
        _draw_detection(canvas, detection, _COLOR_WEAPON)
    # Los implicados en una señal (p. ej. los dos vehículos de un choque) van
    # en el color del nivel aunque estén fuera de la zona.
    for signal in assessment.signals:
        for detection in (signal.detection, signal.partner):
            if detection is not None:
                _draw_detection(canvas, detection, level_color)

    _draw_hud(canvas, assessment, fps, cooldown_remaining)
    if assessment.level is ThreatLevel.DANGER:
        _draw_border(canvas, _COLOR_WEAPON)
    return canvas


def _draw_zone(
    frame: np.ndarray, zone: RestrictedZone, color: tuple[int, int, int]
) -> None:
    """Polígono de vigilancia pintado con el color del estado más alto."""
    fill = frame.copy()
    cv2.fillPoly(fill, [zone.contour], color)
    cv2.addWeighted(fill, _ZONE_FILL_ALPHA, frame, 1 - _ZONE_FILL_ALPHA, 0, dst=frame)
    cv2.polylines(frame, [zone.contour], isClosed=True, color=color, thickness=3)
    for point in zone.points:
        cv2.circle(frame, point, 4, color, -1)

    anchor = zone.contour.reshape(-1, 2).min(axis=0)
    _draw_label(frame, "ZONA DE VIGILANCIA", (int(anchor[0]), int(anchor[1]) - 8), color)


def _draw_detection(
    frame: np.ndarray,
    detection: Detection,
    color: tuple[int, int, int],
) -> None:
    x1, y1, x2, y2 = detection.bbox
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    anchor = detection.foot_point if detection.is_person else detection.center
    cv2.circle(frame, anchor, 5, color, -1)

    parts = [detection.class_name]
    if detection.track_id is not None:
        parts.append(f"#{detection.track_id}")
    parts.append(f"{detection.confidence:.2f}")
    if detection.is_crouching:
        parts.append("AGACHADO")
    if detection.is_hands_up:
        parts.append("MANOS ARRIBA")
    _draw_label(frame, " ".join(parts), (x1, y1 - 8), color)


def _draw_skeleton(
    frame: np.ndarray,
    detection: Detection,
    color: tuple[int, int, int],
) -> None:
    """Huesos y articulaciones COCO-17 sobre la persona."""
    pose = detection.pose
    if pose is None:
        return

    for start, end in SKELETON_EDGES:
        first = pose.get(start)
        second = pose.get(end)
        if first is None or second is None:
            continue
        cv2.line(frame, first.pixel, second.pixel, color, 2, cv2.LINE_AA)

    highlighted = {NOSE, LEFT_WRIST, RIGHT_WRIST}
    for index in range(min(KEYPOINT_COUNT, len(pose.points))):
        point = pose.get(index)
        if point is None:
            continue
        joint_color = _COLOR_HIGHLIGHT if index in highlighted else _COLOR_JOINT
        cv2.circle(frame, point.pixel, 3, joint_color, -1, cv2.LINE_AA)


def _draw_border(frame: np.ndarray, color: tuple[int, int, int]) -> None:
    """Marco perimetral: hace imposible ignorar el estado ROJO."""
    height, width = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (width - 1, height - 1), color, 8)


def _draw_hud(
    frame: np.ndarray,
    assessment: ThreatAssessment,
    fps: float,
    cooldown_remaining: float,
) -> None:
    color = assessment.level.color
    lines = [
        assessment.level.label,
        assessment.reason,
        f"personas: {len(assessment.people_inside)}/{assessment.people_total}"
        f" | vehiculos: {len(assessment.vehicles_inside)}/{assessment.vehicles_total}"
        f" | armas: {len(assessment.weapons)}",
        f"FPS: {fps:.1f}",
    ]
    if cooldown_remaining > 0:
        lines.append(f"cooldown: {cooldown_remaining:.1f}s")

    for row, text in enumerate(lines):
        _draw_label(
            frame,
            text,
            (12, 28 + row * 26),
            color if row == 0 else _COLOR_TEXT,
        )

    # Las reglas activas por debajo del nivel máximo también se listan: el
    # operador necesita ver que el merodeo sigue vivo durante un ROJO.
    extra = [
        signal.label
        for signal in sorted(
            assessment.signals,
            key=lambda s: (s.level, s.rule.priority),
            reverse=True,
        )
        if signal.level < assessment.level
    ]
    for row, text in enumerate(dict.fromkeys(extra)):
        _draw_label(
            frame,
            f"- {text}",
            (12, 28 + (len(lines) + row) * 26),
            assessment.level.color,
        )


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
