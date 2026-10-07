"""Apertura, validación y lectura del stream de cámara."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from types import TracebackType

import cv2
import numpy as np

LOGGER = logging.getLogger(__name__)

# Streams de red (IP Webcam, RTSP...): sin estos límites OpenCV puede quedarse ~30 s
# esperando a una cámara que no responde, sin atender las señales de cierre.
_TIMEOUT_STREAM_MS = 5000
_REINTENTOS_STREAM = 3


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
        # Un archivo de video (demo) se reproduce a su velocidad real y en bucle;
        # una cámara o un stream se leen tal cual llegan.
        self._is_file = isinstance(index, str) and Path(index).is_file()
        self._frame_interval = 0.0
        self._next_frame_at = 0.0
        self._is_stream = isinstance(index, str) and "://" in index

    def open(self) -> None:
        """Abre el dispositivo y verifica que entregue al menos un frame.

        `isOpened()` devuelve True con algunos drivers aunque el dispositivo
        esté ocupado por otro proceso, así que la validación real es leer.
        """
        if self._is_stream:
            capture = cv2.VideoCapture(
                self._index,
                cv2.CAP_FFMPEG,
                [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, _TIMEOUT_STREAM_MS, cv2.CAP_PROP_READ_TIMEOUT_MSEC, _TIMEOUT_STREAM_MS],
            )
        else:
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
        if self._is_file:
            fps = capture.get(cv2.CAP_PROP_FPS)
            self._frame_interval = 1.0 / fps if 1.0 <= fps <= 120.0 else 1.0 / 30.0
            self._next_frame_at = time.monotonic()
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
            if self._is_file:
                espera = self._next_frame_at - time.monotonic()
                if espera > 0:
                    time.sleep(espera)
                self._next_frame_at = max(self._next_frame_at + self._frame_interval, time.monotonic() - 0.5)
            ok, frame = self._capture.read()
            if not ok and self._is_file:
                # Fin del video de demostración: vuelve al inicio.
                self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._capture.read()
            if ok and frame is not None and frame.size > 0:
                self._consecutive_failures = 0
                if frame.shape[1] != self._width or frame.shape[0] != self._height:
                    frame = cv2.resize(frame, (self._width, self._height))
                return frame

            self._consecutive_failures += 1
            if self._is_stream and self._consecutive_failures >= self._max_failures:
                # Señal caída a media transmisión: reabrir antes de rendirse.
                if self._reconectar():
                    continue
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

    def _reconectar(self) -> bool:
        for intento in range(1, _REINTENTOS_STREAM + 1):
            LOGGER.warning("Señal perdida; reconectando (intento %d/%d)…", intento, _REINTENTOS_STREAM)
            if self._capture is not None:
                self._capture.release()
                self._capture = None
            time.sleep(min(2.0 * intento, 5.0))
            try:
                self.open()
                return True
            except CameraError as error:
                LOGGER.warning("%s", error)
        return False

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
