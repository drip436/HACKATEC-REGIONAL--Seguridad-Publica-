"""Atención en campo: una unidad (patrulla) va al lugar del evento y lo resuelve al llegar.

La ruta se pide a OSRM (enrutador de OpenStreetMap) para que la unidad siga las
calles; si no hay red se usa una línea recta. El recorrido es una SIMULACIÓN
acelerada: el tiempo de llegada se calcula al despachar y un vigilante del
backend marca el caso como resuelto cuando ese momento pasa.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from datetime import timedelta

import httpx
from sqlmodel import col, select

from ..errores import ConflictoEstado, RecursoNoEncontrado
from ..models import AccionAuditoria, AtencionCampo, EstadoAtencion, EstadoValidacion
from ..schemas import AtencionIn, AtencionOut, EventoOut
from ..utils.tiempo import ahora_utc
from .auditoria import registrar
from .db import lectura, transaccion
from .eventos import cargar_evento_con_sensor
from .mapeo import atencion_a_dto, evento_a_dto

LOGGER = logging.getLogger("sentinelops.atenciones")

_OSRM_URL = os.getenv("SENTINEL_OSRM_URL", "https://router.project-osrm.org").rstrip("/")
# Distancia (m) desde la que sale la unidad; la ruta real por calles suele ser mayor.
_DISTANCIA_SALIDA_M = 1600.0
# Velocidad de la simulación (m/s, ~6x una patrulla urbana) y sus límites de duración.
_VELOCIDAD_DEMO = float(os.getenv("SENTINEL_VELOCIDAD_DEMO_MPS", "60"))
_DURACION_MIN_S, _DURACION_MAX_S = 20.0, 75.0
_MAX_PUNTOS_RUTA = 300
_RADIO_TIERRA_M = 6_371_000.0


@dataclass(frozen=True, slots=True)
class Ruta:
    puntos: list[list[float]]  # [[lat, lng], ...]
    distancia_m: float
    por_calles: bool


@dataclass(frozen=True, slots=True)
class ResultadoAtencion:
    atencion: AtencionOut
    evento: EventoOut


def crear_atencion(datos: AtencionIn, *, ip_origen: str) -> ResultadoAtencion:
    """Valida el evento (si seguía pendiente) y despacha una unidad hacia él."""
    with lectura() as session:
        evento, _ = cargar_evento_con_sensor(session, datos.evento_id)
        destino = (evento.latitud, evento.longitud)
        _verificar_atendible(session, evento)

    # La ruta se pide fuera de la transacción: es una llamada de red.
    origen = _punto_de_salida(destino, semilla=datos.evento_id)
    ruta = calcular_ruta(origen, destino)
    duracion = min(max(ruta.distancia_m / _VELOCIDAD_DEMO, _DURACION_MIN_S), _DURACION_MAX_S)

    with transaccion() as session:
        evento, sensor = cargar_evento_con_sensor(session, datos.evento_id)
        _verificar_atendible(session, evento)
        ahora = ahora_utc()
        if evento.estado_validacion == EstadoValidacion.PENDIENTE.value:
            evento.estado_validacion = EstadoValidacion.VALIDADO.value
            evento.operador_id = datos.operador_id
            evento.notas_validacion = "Atención en campo"
            evento.validado_en = ahora
            session.add(evento)
            session.flush()
            registrar(
                session,
                accion=AccionAuditoria.EVENTO_VALIDADO,
                usuario_o_nodo=f"operador:{datos.operador_id}",
                ip_origen=ip_origen,
                entidad="eventos_detectados",
                entidad_id=evento.id,
                detalle={"decision": EstadoValidacion.VALIDADO.value, "motivo": "atención en campo"},
            )

        atencion = AtencionCampo(
            evento_id=datos.evento_id,
            unidad=f"PATRULLA-{datos.evento_id % 20 + 1:02d}",
            solicitado_por=datos.operador_id,
            origen_lat=ruta.puntos[0][0],
            origen_lng=ruta.puntos[0][1],
            destino_lat=destino[0],
            destino_lng=destino[1],
            ruta=ruta.puntos,
            ruta_por_calles=ruta.por_calles,
            distancia_m=round(ruta.distancia_m, 1),
            duracion_s=round(duracion, 1),
            despachada_en=ahora,
            llegada_estimada=ahora + timedelta(seconds=duracion),
        )
        session.add(atencion)
        session.flush()
        registrar(
            session,
            accion=AccionAuditoria.ATENCION_DESPACHADA,
            usuario_o_nodo=f"operador:{datos.operador_id}",
            ip_origen=ip_origen,
            entidad="atenciones_campo",
            entidad_id=atencion.id,
            detalle={
                "evento_id": datos.evento_id,
                "unidad": atencion.unidad,
                "distancia_m": atencion.distancia_m,
                "ruta_por_calles": ruta.por_calles,
                "duracion_simulada_s": atencion.duracion_s,
            },
        )
        return ResultadoAtencion(atencion=atencion_a_dto(atencion), evento=evento_a_dto(evento, sensor.codigo))


def resolver_llegadas() -> list[AtencionOut]:
    """Marca como resueltas las unidades cuya hora de llegada ya pasó."""
    ahora = ahora_utc()
    with transaccion() as session:
        llegadas = session.exec(
            select(AtencionCampo)
            .where(col(AtencionCampo.estado) == EstadoAtencion.EN_CAMINO.value)
            .where(col(AtencionCampo.llegada_estimada) <= ahora)
        ).all()
        resueltas = []
        for atencion in llegadas:
            atencion.estado = EstadoAtencion.RESUELTO.value
            atencion.llegada_en = ahora
            session.add(atencion)
            session.flush()
            registrar(
                session,
                accion=AccionAuditoria.ATENCION_RESUELTA,
                usuario_o_nodo=f"unidad:{atencion.unidad}",
                ip_origen="127.0.0.1",
                entidad="atenciones_campo",
                entidad_id=atencion.id,
                detalle={"evento_id": atencion.evento_id, "unidad": atencion.unidad, "resultado": "caso atendido en sitio"},
            )
            resueltas.append(atencion_a_dto(atencion))
        return resueltas


def listar_atenciones(*, limit: int) -> list[AtencionOut]:
    with lectura() as session:
        filas = session.exec(
            select(AtencionCampo).order_by(col(AtencionCampo.despachada_en).desc()).limit(limit)
        ).all()
        return [atencion_a_dto(a) for a in filas]


def obtener_atencion(atencion_id: int) -> AtencionOut:
    with lectura() as session:
        atencion = session.get(AtencionCampo, atencion_id)
        if atencion is None:
            raise RecursoNoEncontrado(f"Atención {atencion_id} no encontrada.")
        return atencion_a_dto(atencion)


# ---- Ruta -------------------------------------------------------------------


def calcular_ruta(origen: tuple[float, float], destino: tuple[float, float]) -> Ruta:
    """Ruta en coche por calles (OSRM); línea recta si el servicio no responde."""
    url = f"{_OSRM_URL}/route/v1/driving/{origen[1]:.6f},{origen[0]:.6f};{destino[1]:.6f},{destino[0]:.6f}"
    try:
        respuesta = httpx.get(url, params={"overview": "full", "geometries": "geojson"}, timeout=6.0)
        respuesta.raise_for_status()
        datos = respuesta.json()
        mejor = datos["routes"][0]
        puntos = [[round(lat, 6), round(lng, 6)] for lng, lat in mejor["geometry"]["coordinates"]]
        if len(puntos) >= 2:
            # Termina exactamente en el evento (OSRM ajusta el destino a la calle).
            puntos.append([round(destino[0], 6), round(destino[1], 6)])
            return Ruta(puntos=_reducir(puntos), distancia_m=float(mejor["distance"]), por_calles=True)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
        LOGGER.warning("OSRM no disponible (%s); la unidad irá en línea recta.", error)
    pasos = 24
    puntos = [
        [round(origen[0] + (destino[0] - origen[0]) * i / pasos, 6), round(origen[1] + (destino[1] - origen[1]) * i / pasos, 6)]
        for i in range(pasos + 1)
    ]
    return Ruta(puntos=puntos, distancia_m=_distancia_m(origen, destino), por_calles=False)


def _punto_de_salida(destino: tuple[float, float], *, semilla: int) -> tuple[float, float]:
    """Punto a `_DISTANCIA_SALIDA_M` del evento, en una dirección que varía por evento."""
    rumbo = math.radians((semilla * 137.508) % 360)  # ángulo áureo: direcciones repartidas
    dlat = _DISTANCIA_SALIDA_M * math.cos(rumbo) / _RADIO_TIERRA_M
    dlng = _DISTANCIA_SALIDA_M * math.sin(rumbo) / (_RADIO_TIERRA_M * math.cos(math.radians(destino[0])))
    return (destino[0] + math.degrees(dlat), destino[1] + math.degrees(dlng))


def _distancia_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlng = lat2 - lat1, math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * _RADIO_TIERRA_M * math.asin(math.sqrt(h))


def _reducir(puntos: list[list[float]]) -> list[list[float]]:
    if len(puntos) <= _MAX_PUNTOS_RUTA:
        return puntos
    paso = math.ceil(len(puntos) / _MAX_PUNTOS_RUTA)
    return [*puntos[:-1:paso], puntos[-1]]


def _verificar_atendible(session, evento) -> None:  # noqa: ANN001 (Session/EventoDetectado)
    if evento.estado_validacion == EstadoValidacion.DESCARTADO.value:
        raise ConflictoEstado("El evento fue descartado como falsa alarma; no requiere atención.")
    previa = session.exec(select(AtencionCampo).where(col(AtencionCampo.evento_id) == evento.id)).first()
    if previa is not None:
        raise ConflictoEstado(
            "Ya hay una unidad asignada a este evento.",
            detalle={"atencion_id": previa.id, "estado": previa.estado},
        )
