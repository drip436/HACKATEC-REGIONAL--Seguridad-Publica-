"""Vinculación de una cámara (p. ej. el teléfono con la app IP Webcam) desde el panel.

El backend lanza el sensor Edge AI (`EDGE_AI/`, YOLOv8-Pose + reglas de amenaza)
como un proceso aparte apuntando a esa cámara. El sensor publica el video
anotado (MJPEG) que muestra el panel y envía sus alertas a `POST /api/v1/eventos`.
Solo hay una cámara vinculada a la vez.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import sys
import threading
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from reflex.config import get_config

from ..config import RAIZ_PROYECTO
from ..models import AccionAuditoria
from ..schemas import CamaraVinculadaOut, VinculacionIn
from ..utils.tiempo import ahora_utc
from .auditoria import registrar
from .db import transaccion

LOGGER = logging.getLogger("sentinelops.vinculacion")

DIR_EDGE = RAIZ_PROYECTO / "EDGE_AI"
VIDEO_DEMO = DIR_EDGE / "asalto.mp4"
_MAX_LINEAS_LOG = 40


def _python_edge() -> str:
    """Intérprete con ultralytics/torch. Por defecto, el mismo del backend."""
    return os.getenv("SENTINEL_EDGE_PYTHON") or sys.executable


def sin_credenciales(url: str) -> str:
    """`http://usuario:clave@ip/video` -> `http://ip/video` (para mostrar y auditar)."""
    partes = urlsplit(url)
    if partes.username or partes.password:
        host = partes.hostname or ""
        netloc = f"{host}:{partes.port}" if partes.port else host
        return urlunsplit((partes.scheme, netloc, partes.path, partes.query, partes.fragment))
    return url


def codigo_sensor(nombre: str) -> str:
    """`Parque de Santa Lucía` -> `CAM-MOVIL-PARQUE-DE-SANTA-LUCIA` (formato del backend)."""
    ascii_ = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().upper()
    slug = re.sub(r"[^A-Z0-9]+", "-", ascii_).strip("-")[:40] or "CAMARA"
    return f"CAM-MOVIL-{slug}"


@dataclass
class _Proceso:
    popen: subprocess.Popen[str]
    sensor_id: str
    nombre: str
    fuente: str
    lat: float
    lng: float
    desde: datetime
    log: deque[str] = field(default_factory=lambda: deque(maxlen=_MAX_LINEAS_LOG))


class SupervisorEdge:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._actual: _Proceso | None = None

    def vincular(self, datos: VinculacionIn, *, operador: str, ip_origen: str) -> CamaraVinculadaOut:
        fuente = str(VIDEO_DEMO) if datos.demo else str(datos.url)
        fuente_visible = "video de demostración" if datos.demo else sin_credenciales(fuente)
        sensor_id = codigo_sensor(datos.nombre)
        comando = [
            _python_edge(),
            "-m",
            "sentinelops",
            f"--source={fuente}",  # con "=": una URL nunca se interpreta como otra opción
            "--no-preview",
            "--zona-completa",
            # Un incidente que sigue en cuadro no debe generar una alerta cada 5 s; una
            # escalada (p. ej. merodeo -> asalto) se avisa igual al instante.
            "--cooldown=45",
            f"--sensor-id={sensor_id}",
            f"--ubicacion={datos.nombre}",
            f"--lat={datos.lat}",
            f"--lng={datos.lng}",
            f"--backend-url={get_config().api_url.rstrip('/')}/api/v1/eventos",
        ]
        with self._lock:
            self._detener()
            popen = subprocess.Popen(  # noqa: S603 (lista de argumentos, sin shell)
                comando,
                cwd=DIR_EDGE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,  # grupo propio: se detiene completo
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            proceso = _Proceso(
                popen=popen,
                sensor_id=sensor_id,
                nombre=datos.nombre,
                fuente=fuente_visible,
                lat=datos.lat,
                lng=datos.lng,
                desde=ahora_utc(),
            )
            threading.Thread(target=_leer_log, args=(proceso,), name="edge-log", daemon=True).start()
            self._actual = proceso
        LOGGER.info("Sensor lanzado (pid %d) para %s", popen.pid, fuente_visible)
        _auditar(
            AccionAuditoria.CAMARA_VINCULADA,
            operador,
            ip_origen,
            {"sensor_id": sensor_id, "nombre": datos.nombre, "fuente": fuente_visible, "lat": datos.lat, "lng": datos.lng},
        )
        return self.estado()

    def desvincular(self, *, operador: str | None = None, ip_origen: str = "127.0.0.1") -> CamaraVinculadaOut:
        with self._lock:
            actual = self._actual
            self._detener()
        if actual is not None and operador is not None:
            _auditar(AccionAuditoria.CAMARA_DESVINCULADA, operador, ip_origen, {"sensor_id": actual.sensor_id})
        return self.estado()

    def estado(self) -> CamaraVinculadaOut:
        with self._lock:
            actual = self._actual
        if actual is None:
            return CamaraVinculadaOut(vinculada=False)
        codigo = actual.popen.poll()
        return CamaraVinculadaOut(
            vinculada=True,
            activa=codigo is None,
            sensor_id=actual.sensor_id,
            nombre=actual.nombre,
            fuente=actual.fuente,
            lat=actual.lat,
            lng=actual.lng,
            desde=actual.desde,
            codigo_salida=codigo,
            ultimas_lineas=list(actual.log)[-8:],
        )

    def _detener(self) -> None:
        actual, self._actual = self._actual, None
        if actual is None or actual.popen.poll() is not None:
            return
        try:
            os.killpg(actual.popen.pid, signal.SIGTERM)
            actual.popen.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(actual.popen.pid, signal.SIGKILL)
            actual.popen.wait(timeout=5)
        except ProcessLookupError:
            pass
        LOGGER.info("Sensor detenido (%s)", actual.sensor_id)


def _leer_log(proceso: _Proceso) -> None:
    """Guarda las últimas líneas del sensor: el panel las muestra si algo falla."""
    assert proceso.popen.stdout is not None
    for linea in proceso.popen.stdout:
        linea = linea.rstrip()
        if linea:
            proceso.log.append(linea[-300:])


def _auditar(accion: AccionAuditoria, operador: str, ip_origen: str, detalle: dict) -> None:
    with transaccion() as session:
        registrar(
            session,
            accion=accion,
            usuario_o_nodo=f"operador:{operador}",
            ip_origen=ip_origen,
            entidad="camaras_sensores",
            entidad_id=detalle.get("sensor_id"),
            detalle=detalle,
        )


SUPERVISOR = SupervisorEdge()
