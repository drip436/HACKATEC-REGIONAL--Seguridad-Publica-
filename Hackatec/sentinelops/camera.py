"""Apertura, validación y lectura del stream de cámara."""

from __future__ import annotations

import logging
from types import TracebackType

import cv2
import numpy as np

LOGGER = logging.getLogger(__name__)


class CameraError(RuntimeError):
    """La cámara no está disponible o dejó de entregar frames."""


class Camera:
    """Wrapper sobre `cv2.VideoCapture` con validación y tolerancia a fallos.

    `index` acepta lo mismo que `cv2.VideoCapture`: un índice de dispositivo,
    la ruta de un archivo de video o la URL de un stream.
    """

    def __init__(
        self,
        index: int | str,
        width: int,
        height: int,
        max_failures: int,
    ) -> None:
        self._index = index
        self._width = width
        self._height = height
        self._max_failures = max_failures
        self._capture: cv2.VideoCapture | None = None
        self._consecutive_failures = 0

    def open(self) -> None:
        """Abre el dispositivo y verifica que entregue al menos un frame.

        `isOpened()` devuelve True con algunos drivers aunque el dispositivo
        esté ocupado por otro proceso, así que la validación real es leer.
        """
        capture = cv2.VideoCapture(self._index)
        if not capture.isOpened():
            capture.release()
            raise CameraError(
                f"No se pudo abrir la fuente de video {self._index!r}. "
                "Verifica que esté conectada y que ningún otro proceso la use."
            )

        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)

        ok, frame = capture.read()
        if not ok or frame is None or frame.size == 0:
            capture.release()
            raise CameraError(
                f"La fuente {self._index!r} se abrió pero no entrega frames."
            )

        self._capture = capture
        self._consecutive_failures = 0
        actual_w = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        LOGGER.info(
            "Fuente %s abierta (%dx%d solicitado, %dx%d real)",
            self._index,
            self._width,
            self._height,
            actual_w,
            actual_h,
        )

    def read(self) -> np.ndarray:
        """Devuelve el siguiente frame, redimensionado a la resolución objetivo.

        Tolera fallos transitorios y sólo aborta tras `max_failures` consecutivos.
        """
        if self._capture is None:
            raise CameraError("La cámara no está abierta; llama a open() primero.")

        while True:
            ok, frame = self._capture.read()
            if ok and frame is not None and frame.size > 0:
                self._consecutive_failures = 0
                if frame.shape[1] != self._width or frame.shape[0] != self._height:
                    frame = cv2.resize(frame, (self._width, self._height))
                return frame

            self._consecutive_failures += 1
            LOGGER.warning(
                "Frame inválido (%d/%d consecutivos)",
                self._consecutive_failures,
                self._max_failures,
            )
            if self._consecutive_failures >= self._max_failures:
                raise CameraError(
                    f"La fuente {self._index!r} falló "
                    f"{self._consecutive_failures} lecturas consecutivas."
                )

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
            LOGGER.info("Fuente %s liberada", self._index)

    def __enter__(self) -> Camera:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
