from __future__ import annotations

from ..models import (
    BitacoraAuditoria,
    CamaraSensor,
    Dependencia,
    DespachoInteroperable,
    EventoDetectado,
)
from ..schemas import (
    Coordenadas,
    DespachoOut,
    EventoOut,
    RegistroAuditoriaOut,
    SensorOut,
)
from ..utils.tiempo import a_utc


def _id(valor: int | None) -> int:
    if valor is None:
        raise RuntimeError("Entidad sin id: falta session.flush() antes de mapear.")
    return valor


def sensor_a_dto(s: CamaraSensor) -> SensorOut:
    return SensorOut(
        id=_id(s.id),
        codigo=s.codigo,
        nombre_ubicacion=s.nombre_ubicacion,
        tipo_sensor=s.tipo_sensor,
        estado_operativo=s.estado_operativo,
        ip_rtsp_url=s.ip_rtsp_url,
        coordenadas=Coordenadas(lat=s.latitud, lng=s.longitud),
        creado_en=a_utc(s.creado_en),
        actualizado_en=a_utc(s.actualizado_en),
    )


def evento_a_dto(e: EventoDetectado, sensor_codigo: str) -> EventoOut:
    return EventoOut(
        id=_id(e.id),
        sensor_id=e.sensor_id,
        sensor_codigo=sensor_codigo,
        tipo_evento=e.tipo_evento,
        nivel_prioridad=e.nivel_prioridad,
        estado_validacion=e.estado_validacion,
        operador_id=e.operador_id,
        notas_validacion=e.notas_validacion,
        metadata_json=dict(e.metadata_json),
        evidencia_url=e.evidencia_url,
        coordenadas=Coordenadas(lat=e.latitud, lng=e.longitud),
        payload_hash_sha256=e.payload_hash_sha256,
        fecha_deteccion=a_utc(e.fecha_deteccion),
        recibido_en=a_utc(e.recibido_en),
        validado_en=a_utc(e.validado_en) if e.validado_en else None,
    )


def despacho_a_dto(d: DespachoInteroperable) -> DespachoOut:
    dependencia = Dependencia(d.dependencia_destino)
    return DespachoOut(
        id=_id(d.id),
        evento_id=d.evento_id,
        dependencia_destino=dependencia,
        miembro_xroad=dependencia.miembro_xroad,
        estado_envio=d.estado_envio,
        solicitado_por=d.solicitado_por,
        instrucciones=d.instrucciones,
        token_interoperabilidad=d.token_interoperabilidad,
        token_jti=d.token_jti,
        payload_hash=d.payload_hash,
        acuse_recibo=dict(d.acuse_recibo) if d.acuse_recibo else None,
        timestamp_despacho=a_utc(d.timestamp_despacho),
        confirmado_en=a_utc(d.confirmado_en) if d.confirmado_en else None,
    )


def auditoria_a_dto(b: BitacoraAuditoria) -> RegistroAuditoriaOut:
    return RegistroAuditoriaOut(
        id=_id(b.id),
        accion=b.accion,
        usuario_o_nodo=b.usuario_o_nodo,
        ip_origen=b.ip_origen,
        entidad=b.entidad,
        entidad_id=b.entidad_id,
        detalle_json=dict(b.detalle_json),
        payload_hash_sha256=b.payload_hash_sha256,
        hash_anterior=b.hash_anterior,
        hash_registro=b.hash_registro,
        timestamp_inmutable=a_utc(b.timestamp_inmutable),
    )
