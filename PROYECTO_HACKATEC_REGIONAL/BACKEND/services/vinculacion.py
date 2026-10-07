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
import time
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


# Reconexión: esperas entre intentos y cuándo se considera estable un sensor.
_ESPERAS_S = (2.0, 5.0, 10.0)
_MAX_INTENTOS = 5
_ESTABLE_S = 30.0  # vivo este tiempo = conexión buena: el contador de intentos vuelve a 0
_CONECTANDO_S = 10.0  # primeros segundos tras lanzar: carga del modelo y apertura del video
_ESPERA_SIGTERM_S = 3.0


@dataclass
class _Proceso:
    comando: list[str]
    sensor_id: str
    nombre: str
    fuente: str  # visible: sin credenciales
    lat: float
    lng: float
    desde: datetime
    popen: subprocess.Popen[str] | None = None
    lanzado_en: float = 0.0
    intento: int = 0
    reconectando: bool = False
    agotado: bool = False
    detener: threading.Event = field(default_factory=threading.Event)
    log: deque[str] = field(default_factory=lambda: deque(maxlen=_MAX_LINEAS_LOG))


class SupervisorEdge:
    """Lanza, vigila y detiene el sensor de la cámara vinculada.

    `estado()` nunca espera a nada: solo lee la referencia actual. Detener un sensor
    (que puede tardar segundos si está abriendo una cámara que no responde) ocurre
    fuera de cualquier lock que `estado()` necesite, así el backend no se congela.
    """

    def __init__(self) -> None:
        self._actual: _Proceso | None = None
        # Serializa vincular/desvincular entre sí; `estado()` no lo usa.
        self._operacion = threading.Lock()

    def vincular(self, datos: VinculacionIn, fuente: str, *, operador: str, ip_origen: str) -> CamaraVinculadaOut:
        """`fuente` ya fue probada (o es el video de demo): el sensor arranca sobre algo que responde."""
        fuente_visible = "video de demostración" if datos.demo else sin_credenciales(fuente)
        sensor_id = codigo_sensor(datos.nombre)
        nuevo = _Proceso(
            comando=[
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
            ],
            sensor_id=sensor_id,
            nombre=datos.nombre,
            fuente=fuente_visible,
            lat=datos.lat,
            lng=datos.lng,
            desde=ahora_utc(),
        )
        with self._operacion:
            anterior, self._actual = self._actual, nuevo
            if anterior is not None:
                _detener(anterior)  # antes de lanzar: el nuevo necesita el puerto del video
            _lanzar(nuevo)
            threading.Thread(target=_vigilar, args=(nuevo,), name="edge-vigia", daemon=True).start()
        LOGGER.info("Sensor lanzado para %s", fuente_visible)
        _auditar(
            AccionAuditoria.CAMARA_VINCULADA,
            operador,
            ip_origen,
            {"sensor_id": sensor_id, "nombre": datos.nombre, "fuente": fuente_visible, "lat": datos.lat, "lng": datos.lng},
        )
        return self.estado()

    def desvincular(self, *, operador: str | None = None, ip_origen: str = "127.0.0.1") -> CamaraVinculadaOut:
        with self._operacion:
            actual, self._actual = self._actual, None
            if actual is not None:
                _detener(actual)
        if actual is not None and operador is not None:
            _auditar(AccionAuditoria.CAMARA_DESVINCULADA, operador, ip_origen, {"sensor_id": actual.sensor_id})
        return self.estado()

    def estado(self) -> CamaraVinculadaOut:
        actual = self._actual  # lectura atómica de la referencia: sin locks
        if actual is None:
            return CamaraVinculadaOut(vinculada=False)
        popen = actual.popen
        codigo = popen.poll() if popen is not None else None
        vivo = popen is not None and codigo is None
        if actual.agotado:
            estado = "detenida"
        elif actual.reconectando or (popen is not None and not vivo):
            estado = "reconectando"
        elif vivo and time.monotonic() - actual.lanzado_en >= _CONECTANDO_S:
            estado = "en_linea"
        else:
            estado = "conectando"
        return CamaraVinculadaOut(
            vinculada=True,
            estado=estado,
            intento=actual.intento,
            activa=vivo,
            sensor_id=actual.sensor_id,
            nombre=actual.nombre,
            fuente=actual.fuente,
            lat=actual.lat,
            lng=actual.lng,
            desde=actual.desde,
            codigo_salida=codigo,
            ultimas_lineas=list(actual.log)[-8:],
        )


def _lanzar(proceso: _Proceso) -> None:
    proceso.popen = subprocess.Popen(  # noqa: S603 (lista de argumentos, sin shell)
        proceso.comando,
        cwd=DIR_EDGE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,  # grupo propio: se detiene completo
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    proceso.lanzado_en = time.monotonic()
    proceso.reconectando = False
    threading.Thread(target=_leer_log, args=(proceso, proceso.popen), name="edge-log", daemon=True).start()


def _vigilar(proceso: _Proceso) -> None:
    """Relanza el sensor si termina sin que se lo pidieran (cámara caída, red, etc.)."""
    while not proceso.detener.is_set():
        popen = proceso.popen
        if popen is None:
            return
        popen.wait()
        if proceso.detener.is_set():
            return
        vivio = time.monotonic() - proceso.lanzado_en
        proceso.intento = 1 if vivio >= _ESTABLE_S else proceso.intento + 1
        if proceso.intento > _MAX_INTENTOS:
            proceso.agotado = True
            LOGGER.warning("Sensor %s detenido tras %d intentos de reconexión", proceso.sensor_id, _MAX_INTENTOS)
            return
        proceso.reconectando = True
        espera = _ESPERAS_S[min(proceso.intento - 1, len(_ESPERAS_S) - 1)]
        LOGGER.info("Sensor %s terminó (código %s); reconectando en %.0f s (intento %d)", proceso.sensor_id, popen.returncode, espera, proceso.intento)
        if proceso.detener.wait(espera):
            return
        try:
            _lanzar(proceso)
        except OSError as error:
            proceso.log.append(f"No se pudo relanzar el sensor: {error}")


def _detener(proceso: _Proceso) -> None:
    proceso.detener.set()
    popen = proceso.popen
    if popen is None or popen.poll() is not None:
        return
    try:
        os.killpg(popen.pid, signal.SIGTERM)
        popen.wait(timeout=_ESPERA_SIGTERM_S)
    except subprocess.TimeoutExpired:
        # Un sensor bloqueado abriendo una cámara no atiende SIGTERM a tiempo.
        os.killpg(popen.pid, signal.SIGKILL)
        popen.wait(timeout=5)
    except ProcessLookupError:
        pass
    LOGGER.info("Sensor detenido (%s)", proceso.sensor_id)


def _leer_log(proceso: _Proceso, popen: subprocess.Popen[str]) -> None:
    """Guarda las últimas líneas del sensor: el panel las muestra si algo falla."""
    assert popen.stdout is not None
    for linea in popen.stdout:
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
