from __future__ import annotations

from sqlmodel import Session, col, select

from ..errores import ConflictoEstado, RecursoNoEncontrado
from ..models import AccionAuditoria, CamaraSensor, EstadoOperativo, TipoSensor
from ..schemas import Coordenadas, SensorIn, SensorOut, SensorUpdateIn
from ..utils.tiempo import ahora_utc
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


def obtener_sensor(sensor_id: int) -> SensorOut:
    with lectura() as session:
        return sensor_a_dto(_cargar(session, sensor_id))


def actualizar_sensor(sensor_id: int, datos: SensorUpdateIn, *, actor: str, ip_origen: str) -> SensorOut:
    with transaccion() as session:
        sensor = _cargar(session, sensor_id)
        cambios: dict[str, dict[str, object]] = {}

        def _cambiar(campo: str, nuevo: object) -> None:
            anterior = getattr(sensor, campo)
            if anterior != nuevo:
                setattr(sensor, campo, nuevo)
                cambios[campo] = {"anterior": anterior, "nuevo": nuevo}

        enviados = datos.model_fields_set
        if "nombre_ubicacion" in enviados and datos.nombre_ubicacion is not None:
            _cambiar("nombre_ubicacion", datos.nombre_ubicacion)
        if "tipo_sensor" in enviados and datos.tipo_sensor is not None:
            _cambiar("tipo_sensor", datos.tipo_sensor.value)
        if "estado_operativo" in enviados and datos.estado_operativo is not None:
            _cambiar("estado_operativo", datos.estado_operativo.value)
        if "ip_rtsp_url" in enviados:
            _cambiar("ip_rtsp_url", datos.ip_rtsp_url)
        if "coordenadas" in enviados and datos.coordenadas is not None:
            _cambiar("latitud", datos.coordenadas.lat)
            _cambiar("longitud", datos.coordenadas.lng)

        if cambios:
            sensor.actualizado_en = ahora_utc()
            session.add(sensor)
            session.flush()
            if "ip_rtsp_url" in cambios:
                # La URL RTSP puede contener credenciales: solo se registra que cambió.
                cambios["ip_rtsp_url"] = {"modificado": True}
            registrar(
                session,
                accion=AccionAuditoria.SENSOR_ACTUALIZADO,
                usuario_o_nodo=actor,
                ip_origen=ip_origen,
                entidad="camaras_sensores",
                entidad_id=sensor.id,
                detalle={"codigo": sensor.codigo, "cambios": cambios},
            )
        return sensor_a_dto(sensor)


def _cargar(session: Session, sensor_id: int) -> CamaraSensor:
    sensor = session.get(CamaraSensor, sensor_id)
    if sensor is None:
        raise RecursoNoEncontrado(f"Sensor {sensor_id} no encontrado.", detalle={"sensor_id": sensor_id})
    return sensor
