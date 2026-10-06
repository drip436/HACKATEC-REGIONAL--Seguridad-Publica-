"""Geometría de la zona restringida."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import cv2
import numpy as np

from .detector import Detection


class RestrictedZone:
    """Polígono virtual contra el que se evalúan los centroides."""

    def __init__(self, points: Sequence[tuple[int, int]]) -> None:
        if len(points) < 3:
            raise ValueError("Una zona necesita al menos 3 puntos")
        # pointPolygonTest y polylines esperan un contorno (N, 1, 2) int32.
        self._contour = np.asarray(points, dtype=np.int32).reshape(-1, 1, 2)

    @property
    def contour(self) -> np.ndarray:
        return self._contour

    def contains(self, point: tuple[int, int]) -> bool:
        """True si el punto está dentro del polígono o sobre su borde."""
        return cv2.pointPolygonTest(self._contour, (float(point[0]), float(point[1])), False) >= 0


@dataclass(frozen=True, slots=True)
class ZoneEvaluation:
    """Resultado de evaluar un frame completo contra la zona."""

    inside: tuple[Detection, ...]
    outside: tuple[Detection, ...]

    @property
    def breached(self) -> bool:
        return bool(self.inside)

    @property
    def primary_intruder(self) -> Detection | None:
        """Detección dentro de la zona con mayor confianza, si hay alguna."""
        if not self.inside:
            return None
        return max(self.inside, key=lambda detection: detection.confidence)


def evaluate(zone: RestrictedZone, detections: Iterable[Detection]) -> ZoneEvaluation:
    inside: list[Detection] = []
    outside: list[Detection] = []
    for detection in detections:
        target = inside if zone.contains(detection.foot_point) else outside
        target.append(detection)
    return ZoneEvaluation(inside=tuple(inside), outside=tuple(outside))
