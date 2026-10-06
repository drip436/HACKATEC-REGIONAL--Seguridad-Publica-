from __future__ import annotations

from sqlmodel import Session, col, select

from ..errores import ConflictoEstado
from ..models import AccionAuditoria, CamaraSensor, EstadoOperativo, TipoSensor
from ..schemas import Coordenadas, SensorIn, SensorOut
from .auditoria import registrar
from .db import lectura, transaccion
from .mapeo import sensor_a_dto


def buscar_por_codigo(session: Session, codigo: str) -> CamaraSensor | None:
    return session.exec(select(CamaraSensor).where(col(CamaraSensor.codigo) == codigo)).first()


def _crear(
    session: Session,
    *,
    codigo: str,
    nombre_ubicacion: str,
    tipo_sensor: TipoSensor,
    estado: EstadoOperativo,
    ip_rtsp_url: str | None,
    coordenadas: Coordenadas,
    actor: str,
    ip_origen: str,
    automatico: bool,
) -> CamaraSensor:
    sensor = CamaraSensor(
        codigo=codigo,
        nombre_ubicacion=nombre_ubicacion,
        tipo_sensor=tipo_sensor.value,
        estado_operativo=estado.value,
        ip_rtsp_url=ip_rtsp_url,
        latitud=coordenadas.lat,
        longitud=coordenadas.lng,
    )
    session.add(sensor)
    session.flush()
    registrar(
        session,
        accion=AccionAuditoria.SENSOR_REGISTRADO,
        usuario_o_nodo=actor,
        ip_origen=ip_origen,
        entidad="camaras_sensores",
        entidad_id=sensor.id,
        # La URL RTSP puede contener credenciales: no se copia a la bitácora.
        detalle={"codigo": codigo, "tipo_sensor": tipo_sensor.value, "automatico": automatico},
    )
    return sensor


def registrar_sensor(datos: SensorIn, *, actor: str, ip_origen: str) -> SensorOut:
    with transaccion() as session:
        if buscar_por_codigo(session, datos.codigo) is not None:
            raise ConflictoEstado(f"El sensor {datos.codigo} ya está registrado.", detalle={"codigo": datos.codigo})
        sensor = _crear(
            session,
            codigo=datos.codigo,
            nombre_ubicacion=datos.nombre_ubicacion,
            tipo_sensor=datos.tipo_sensor,
            estado=datos.estado_operativo,
            ip_rtsp_url=datos.ip_rtsp_url,
            coordenadas=datos.coordenadas,
            actor=actor,
            ip_origen=ip_origen,
            automatico=False,
        )
        return sensor_a_dto(sensor)


def autoregistrar(session: Session, *, codigo: str, coordenadas: Coordenadas, ip_origen: str) -> CamaraSensor:
    return _crear(
        session,
        codigo=codigo,
        nombre_ubicacion=f"Auto-registrado ({codigo})",
        tipo_sensor=TipoSensor.OTRO,
        estado=EstadoOperativo.ACTIVO,
        ip_rtsp_url=None,
        coordenadas=coordenadas,
        actor=f"sensor:{codigo}",
        ip_origen=ip_origen,
        automatico=True,
    )


def listar_sensores() -> list[SensorOut]:
    with lectura() as session:
        filas = session.exec(select(CamaraSensor).order_by(col(CamaraSensor.codigo))).all()
        return [sensor_a_dto(s) for s in filas]
