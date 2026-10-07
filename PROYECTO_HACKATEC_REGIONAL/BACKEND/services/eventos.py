from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlmodel import Session, col, select

from ..errores import ConflictoEstado, RecursoNoEncontrado, SolicitudInvalida
from ..models import (
    AccionAuditoria,
    CamaraSensor,
    EstadoOperativo,
    EstadoValidacion,
    EventoDetectado,
    NivelPrioridad,
)
from ..schemas import AlertaSensorIn, EventoOut, ValidacionIn
from ..utils.crypto import hash_payload
from ..utils.tiempo import a_utc, ahora_utc
from .auditoria import registrar
from .db import lectura, transaccion
from .mapeo import evento_a_dto
from .sensores import autoregistrar, buscar_por_codigo


@dataclass(frozen=True, slots=True)
class ResultadoIngesta:
    evento: EventoOut
    creado: bool


def registrar_alerta(
    alerta: AlertaSensorIn,
    *,
    ip_origen: str,
    auto_registrar: bool,
    tolerancia_reloj_s: int,
) -> ResultadoIngesta:
    ahora = ahora_utc()
    if a_utc(alerta.timestamp) > ahora + timedelta(seconds=tolerancia_reloj_s):
        raise SolicitudInvalida(
            "El timestamp del sensor está en el futuro; revisa la sincronización NTP del nodo edge.",
            detalle={"timestamp": alerta.timestamp.isoformat(), "servidor": ahora.isoformat()},
        )

    payload_hash = hash_payload(alerta.model_dump(mode="json"))

    with transaccion() as session:
        # Idempotencia: el Módulo A reintenta con backoff; un reintento trae el mismo
        # payload (mismo hash) y debe devolver el evento existente, no duplicarlo.
        existente = session.exec(
            select(EventoDetectado).where(col(EventoDetectado.payload_hash_sha256) == payload_hash)
        ).first()
        if existente is not None:
            return ResultadoIngesta(evento=evento_a_dto(existente, alerta.sensor_id), creado=False)

        sensor = buscar_por_codigo(session, alerta.sensor_id)
        if sensor is None:
            if not auto_registrar:
                raise RecursoNoEncontrado(
                    f"Sensor {alerta.sensor_id} no registrado.", detalle={"sensor_id": alerta.sensor_id}
                )
            sensor = autoregistrar(
                session,
                codigo=alerta.sensor_id,
                coordenadas=alerta.coordenadas,
                ip_origen=ip_origen,
                nombre_ubicacion=alerta.ubicacion,
            )
        elif sensor.estado_operativo == EstadoOperativo.INACTIVO.value:
            raise ConflictoEstado(
                f"El sensor {sensor.codigo} está dado de baja y no puede reportar eventos.",
                detalle={"sensor_id": sensor.codigo},
            )

        evento = EventoDetectado(
            sensor_id=_id(sensor),
            tipo_evento=alerta.tipo_evento.value,
            nivel_prioridad=alerta.severidad.value,
            metadata_json=alerta.metadatos.model_dump(mode="json", exclude_none=True),
            evidencia_url=alerta.evidencia_url,
            latitud=alerta.coordenadas.lat,
            longitud=alerta.coordenadas.lng,
            payload_hash_sha256=payload_hash,
            fecha_deteccion=a_utc(alerta.timestamp),
            recibido_en=ahora,
        )
        session.add(evento)
        session.flush()
        registrar(
            session,
            accion=AccionAuditoria.EVENTO_RECIBIDO,
            usuario_o_nodo=f"sensor:{sensor.codigo}",
            ip_origen=ip_origen,
            entidad="eventos_detectados",
            entidad_id=evento.id,
            detalle={
                "tipo_evento": evento.tipo_evento,
                "nivel_prioridad": evento.nivel_prioridad,
                "payload_sensor_sha256": payload_hash,
            },
        )
        return ResultadoIngesta(evento=evento_a_dto(evento, sensor.codigo), creado=True)


def validar_evento(evento_id: int, datos: ValidacionIn, *, ip_origen: str) -> EventoOut:
    with transaccion() as session:
        evento, sensor = cargar_evento_con_sensor(session, evento_id)
        if evento.estado_validacion != EstadoValidacion.PENDIENTE.value:
            raise ConflictoEstado(
                "El evento ya fue resuelto por un operador.",
                detalle={
                    "estado_actual": evento.estado_validacion,
                    "operador_id": evento.operador_id,
                },
            )

        prioridad_anterior = evento.nivel_prioridad
        evento.estado_validacion = datos.decision.value
        evento.operador_id = datos.operador_id
        evento.notas_validacion = datos.notas
        evento.validado_en = ahora_utc()
        if datos.nivel_prioridad is not None:
            evento.nivel_prioridad = datos.nivel_prioridad.value
        session.add(evento)
        session.flush()

        registrar(
            session,
            accion=(
                AccionAuditoria.EVENTO_VALIDADO
                if datos.decision == EstadoValidacion.VALIDADO
                else AccionAuditoria.EVENTO_DESCARTADO
            ),
            usuario_o_nodo=f"operador:{datos.operador_id}",
            ip_origen=ip_origen,
            entidad="eventos_detectados",
            entidad_id=evento.id,
            detalle={
                "decision": datos.decision.value,
                "prioridad_anterior": prioridad_anterior,
                "prioridad_final": evento.nivel_prioridad,
                "notas": datos.notas,
            },
        )
        return evento_a_dto(evento, sensor.codigo)


def obtener_evento(evento_id: int) -> EventoOut:
    with lectura() as session:
        evento, sensor = cargar_evento_con_sensor(session, evento_id)
        return evento_a_dto(evento, sensor.codigo)


def listar_eventos(
    *,
    estado: EstadoValidacion | None,
    prioridad: NivelPrioridad | None,
    limit: int,
    offset: int,
) -> list[EventoOut]:
    consulta = select(EventoDetectado, CamaraSensor.codigo).join(
        CamaraSensor, col(CamaraSensor.id) == col(EventoDetectado.sensor_id)
    )
    if estado is not None:
        consulta = consulta.where(col(EventoDetectado.estado_validacion) == estado.value)
    if prioridad is not None:
        consulta = consulta.where(col(EventoDetectado.nivel_prioridad) == prioridad.value)
    consulta = consulta.order_by(col(EventoDetectado.fecha_deteccion).desc()).offset(offset).limit(limit)
    with lectura() as session:
        return [evento_a_dto(e, codigo) for e, codigo in session.exec(consulta).all()]


def cargar_evento_con_sensor(session: Session, evento_id: int) -> tuple[EventoDetectado, CamaraSensor]:
    evento = session.get(EventoDetectado, evento_id)
    if evento is None:
        raise RecursoNoEncontrado(f"Evento {evento_id} no encontrado.", detalle={"evento_id": evento_id})
    sensor = session.get(CamaraSensor, evento.sensor_id)
    if sensor is None:
        raise RecursoNoEncontrado("Sensor del evento no encontrado.", detalle={"sensor_id": evento.sensor_id})
    return evento, sensor


def _id(sensor: CamaraSensor) -> int:
    if sensor.id is None:
        raise RuntimeError("Sensor sin id persistido.")
    return sensor.id
