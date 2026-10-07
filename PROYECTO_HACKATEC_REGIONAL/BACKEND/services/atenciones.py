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
from ..schemas import AtencionIn, AtencionOut, EventoOut, UnidadOut
from ..utils.tiempo import ahora_utc
from . import flota
from .auditoria import registrar
from .db import lectura, transaccion
from .eventos import cargar_evento_con_sensor
from .mapeo import atencion_a_dto, evento_a_dto

LOGGER = logging.getLogger("sentinelops.atenciones")

_OSRM_URL = os.getenv("SENTINEL_OSRM_URL", "https://router.project-osrm.org").rstrip("/")
# Velocidad de la simulación (m/s, ~6x una patrulla urbana) y sus límites de duración.
_VELOCIDAD_DEMO = float(os.getenv("SENTINEL_VELOCIDAD_DEMO_MPS", "60"))
_DURACION_MIN_S, _DURACION_MAX_S = 20.0, 75.0
_MAX_PUNTOS_RUTA = 300
_TIMEOUT_OSRM_S = 2.5
_MAX_CACHE_RUTAS = 64



@dataclass(frozen=True, slots=True)
class Ruta:
    puntos: list[list[float]]  # [[lat, lng], ...]
    distancia_m: float
    por_calles: bool


_CACHE_RUTAS: dict[tuple[float, float, float, float], Ruta] = {}


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
        unidad = flota.mas_cercana(destino, flota.asignaciones(session))
    if unidad is None:
        raise ConflictoEstado("No hay unidades libres: todas están atendiendo otros casos.")

    # La ruta se pide fuera de la transacción: es una llamada de red.
    ruta = calcular_ruta((unidad.lat, unidad.lng), destino)
    duracion = min(max(ruta.distancia_m / _VELOCIDAD_DEMO, _DURACION_MIN_S), _DURACION_MAX_S)

    with transaccion() as session:
        evento, sensor = cargar_evento_con_sensor(session, datos.evento_id)
        _verificar_atendible(session, evento)
        if unidad.id in flota.asignaciones(session):
            raise ConflictoEstado(f"{unidad.id} acaba de ser asignada a otro caso; intenta de nuevo.")
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
            unidad=unidad.id,
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
                "base": unidad.base,
                "distancia_m": atencion.distancia_m,
                "ruta_por_calles": ruta.por_calles,
                "duracion_simulada_s": atencion.duracion_s,
            },
        )
        return ResultadoAtencion(atencion=atencion_a_dto(atencion), evento=evento_a_dto(evento, sensor.codigo))


def resolver_llegadas() -> list[ResultadoAtencion]:
    """Marca como resueltas las unidades cuya hora de llegada ya pasó y cierra su evento
    (`resuelto_en`). Sin llegadas pendientes no abre ninguna transacción de escritura."""
    ahora = ahora_utc()
    pendientes = (
        select(AtencionCampo)
        .where(col(AtencionCampo.estado) == EstadoAtencion.EN_CAMINO.value)
        .where(col(AtencionCampo.llegada_estimada) <= ahora)
    )
    with lectura() as session:
        if session.exec(pendientes.limit(1)).first() is None:
            return []

    with transaccion() as session:
        resueltas = []
        for atencion in session.exec(pendientes).all():
            atencion.estado = EstadoAtencion.RESUELTO.value
            atencion.llegada_en = ahora
            session.add(atencion)
            evento, sensor = cargar_evento_con_sensor(session, atencion.evento_id)
            evento.resuelto_en = ahora
            session.add(evento)
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
            resueltas.append(ResultadoAtencion(atencion=atencion_a_dto(atencion), evento=evento_a_dto(evento, sensor.codigo)))
        return resueltas


def listar_unidades() -> list[UnidadOut]:
    with lectura() as session:
        return flota.listar(session)


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
    """Ruta en coche por calles (OSRM); línea recta si el servicio no responde.
    Las rutas por calles se guardan en caché: de una base a una cámara casi siempre es la misma."""
    clave = (round(origen[0], 5), round(origen[1], 5), round(destino[0], 5), round(destino[1], 5))
    if clave in _CACHE_RUTAS:
        return _CACHE_RUTAS[clave]
    ruta = _ruta_osrm(origen, destino)
    if ruta.por_calles:
        if len(_CACHE_RUTAS) >= _MAX_CACHE_RUTAS:
            _CACHE_RUTAS.pop(next(iter(_CACHE_RUTAS)))
        _CACHE_RUTAS[clave] = ruta
    return ruta


def _ruta_osrm(origen: tuple[float, float], destino: tuple[float, float]) -> Ruta:
    url = f"{_OSRM_URL}/route/v1/driving/{origen[1]:.6f},{origen[0]:.6f};{destino[1]:.6f},{destino[0]:.6f}"
    try:
        respuesta = httpx.get(url, params={"overview": "full", "geometries": "geojson"}, timeout=_TIMEOUT_OSRM_S)
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
    return Ruta(puntos=puntos, distancia_m=flota.distancia_m(origen, destino), por_calles=False)


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
