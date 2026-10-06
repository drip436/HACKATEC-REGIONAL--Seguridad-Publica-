"""Persistencia local del fotograma de evidencia."""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

LOGGER = logging.getLogger(__name__)

_FILENAME_PATTERN = re.compile(r"^evento_(\d+)\.jpg$")


class EvidenceError(RuntimeError):
    """No se pudo escribir el archivo de evidencia."""


@dataclass(frozen=True, slots=True)
class Evidence:
    event_id: int
    path: Path
    url: str


class EvidenceStore:
    """Guarda frames como `evento_<id>.jpg` y calcula su URL pública."""

    def __init__(self, directory: Path, url_prefix: str, jpeg_quality: int) -> None:
        self._directory = directory
        self._url_prefix = url_prefix.rstrip("/")
        self._jpeg_quality = jpeg_quality
        self._lock = threading.Lock()
        self._directory.mkdir(parents=True, exist_ok=True)
        self._next_id = self._scan_next_id()
        LOGGER.info(
            "Evidencias en %s (próximo id: %d)",
            self._directory.resolve(),
            self._next_id,
        )

    def _scan_next_id(self) -> int:
        """Continúa la numeración existente para no sobreescribir evidencias."""
        used = [
            int(match.group(1))
            for entry in self._directory.iterdir()
            if entry.is_file() and (match := _FILENAME_PATTERN.match(entry.name))
        ]
        return max(used, default=0) + 1

    def save(self, frame: np.ndarray) -> Evidence:
        with self._lock:
            event_id = self._next_id
            self._next_id += 1

        path = self._directory / f"evento_{event_id}.jpg"
        params = [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality]
        if not cv2.imwrite(str(path), frame, params):
            raise EvidenceError(f"cv2.imwrite falló al escribir {path}")

        evidence = Evidence(
            event_id=event_id,
            path=path,
            url=f"{self._url_prefix}/{path.name}",
        )
        LOGGER.info("Evidencia guardada: %s", evidence.path)
        return evidence
