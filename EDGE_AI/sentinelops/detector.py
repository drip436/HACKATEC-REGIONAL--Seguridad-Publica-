"""Inferencia con YOLOv8n restringida a la clase `person`."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from ultralytics import YOLO

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Detection:
    """Una persona detectada en el frame actual.

    `bbox` es `(x1, y1, x2, y2)` en píxeles enteros del frame procesado.
    """

    bbox: tuple[int, int, int, int]
    confidence: float

    @property
    def foot_point(self) -> tuple[int, int]:
        """Punto medio inferior del bbox.

        Se usa como centroide porque aproxima los pies: el centro geométrico
        de una persona alta dispara la zona antes de que realmente la pise.
        """
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) // 2, y2)


class PersonDetector:
    """Carga el modelo una vez y expone una inferencia por frame."""

    def __init__(
        self,
        model_path: str,
        conf_threshold: float,
        class_id: int,
    ) -> None:
        self._conf_threshold = conf_threshold
        self._class_id = class_id
        LOGGER.info("Cargando modelo %s", model_path)
        self._model = YOLO(model_path)
        LOGGER.info("Modelo listo")

    def detect(self, frame: np.ndarray) -> list[Detection]:
        """Devuelve las personas detectadas sobre el umbral de confianza."""
        results = self._model.predict(
            frame,
            classes=[self._class_id],
            conf=self._conf_threshold,
            verbose=False,
        )
        if not results:
            return []

        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return []

        height, width = frame.shape[:2]
        detections: list[Detection] = []
        for xyxy, conf in zip(
            boxes.xyxy.cpu().numpy(), boxes.conf.cpu().numpy(), strict=True
        ):
            x1, y1, x2, y2 = (float(value) for value in xyxy)
            bbox = (
                max(0, int(round(x1))),
                max(0, int(round(y1))),
                min(width - 1, int(round(x2))),
                min(height - 1, int(round(y2))),
            )
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                continue  # el clamp degeneró la caja
            detections.append(Detection(bbox=bbox, confidence=round(float(conf), 2)))

        return detections
