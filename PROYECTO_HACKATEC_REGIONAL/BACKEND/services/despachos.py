from __future__ import annotations

from sqlmodel import col, select

from ..errores import ConflictoEstado, FederacionFallida, RecursoNoEncontrado, SentinelError
from ..models import AccionAuditoria, DespachoInteroperable, EstadoEnvio, EstadoValidacion
from ..schemas import DespachoIn, DespachoOut, SolicitudFederacionIn
from . import xroad
from .auditoria import registrar
from .db import lectura, transaccion
from .eventos import cargar_evento_con_sensor
from .mapeo import despacho_a_dto

IP_NODO_INTERNO = "127.0.0.1"


def crear_despacho(datos: DespachoIn, *, ip_origen: str) -> DespachoOut:
    """Flujo en tres fases para que cada transición quede persistida aunque falle
    la siguiente: emitir (enviado) -> federar -> confirmar con acuse."""
    dependencia = datos.dependencia_destino

    with transaccion() as session:
        evento, sensor = cargar_evento_con_sensor(session, datos.evento_id)
        if evento.estado_validacion != EstadoValidacion.VALIDADO.value:
            raise ConflictoEstado(
                "Solo se despachan eventos validados por un operador (Human-in-the-loop).",
                detalle={"evento_id": datos.evento_id, "estado_actual": evento.estado_validacion},
            )
        previo = session.exec(
            select(DespachoInteroperable).where(
                col(DespachoInteroperable.evento_id) == datos.evento_id,
                col(DespachoInteroperable.dependencia_destino) == dependencia.value,
            )
        ).first()
        if previo is not None:
            raise ConflictoEstado(
                f"El evento ya fue despachado a {dependencia.value}.",
                detalle={"despacho_id": previo.id, "estado_envio": previo.estado_envio},
            )

        despacho = DespachoInteroperable(
            evento_id=datos.evento_id,
            dependencia_destino=dependencia.value,
            solicitado_por=datos.operador_id,
            instrucciones=datos.instrucciones,
        )
        session.add(despacho)
        session.flush()
        despacho_id = _id(despacho)

        payload = xroad.construir_payload_federado(evento, sensor, instrucciones=datos.instrucciones)
        mensaje = xroad.firmar_mensaje(payload, dependencia=dependencia, despacho_id=despacho_id)
        despacho.token_interoperabilidad = mensaje.token
        despacho.token_jti = mensaje.jti
        despacho.payload_hash = mensaje.payload_sha256
        despacho.timestamp_despacho = mensaje.emitido_en
        despacho.estado_envio = EstadoEnvio.ENVIADO.value
        session.add(despacho)
        registrar(
            session,
            accion=AccionAuditoria.DESPACHO_EMITIDO,
            usuario_o_nodo=f"operador:{datos.operador_id}",
            ip_origen=ip_origen,
            entidad="despachos_interoperables",
            entidad_id=despacho_id,
            detalle={
                "evento_id": datos.evento_id,
                "dependencia": dependencia.value,
                "miembro_xroad": dependencia.miembro_xroad,
                "jti": mensaje.jti,
                "payload_sha256": mensaje.payload_sha256,
            },
        )

    try:
        acuse = xroad.recibir_federacion(
            SolicitudFederacionIn(token=mensaje.token, payload=payload), ip_origen=IP_NODO_INTERNO
        )
        xroad.verificar_acuse(acuse, mensaje, dependencia)
    except SentinelError as exc:
        with transaccion() as session:
            registrar(
                session,
                accion=AccionAuditoria.DESPACHO_FALLIDO,
                usuario_o_nodo=f"nodo:{dependencia.miembro_xroad}",
                ip_origen=IP_NODO_INTERNO,
                entidad="despachos_interoperables",
                entidad_id=despacho_id,
                detalle={"codigo": exc.codigo, "mensaje": exc.mensaje},
            )
        raise FederacionFallida(
            f"La federación hacia {dependencia.value} falló; el despacho queda como 'enviado'.",
            detalle={"despacho_id": despacho_id, "causa": exc.codigo},
        ) from exc

    with transaccion() as session:
        confirmado = session.get(DespachoInteroperable, despacho_id)
        if confirmado is None:
            raise RecursoNoEncontrado("Despacho desaparecido durante la confirmación.")
        confirmado.estado_envio = EstadoEnvio.CONFIRMADO.value
        confirmado.acuse_recibo = acuse.model_dump(mode="json")
        confirmado.confirmado_en = acuse.recibido_en
        session.add(confirmado)
        session.flush()
        registrar(
            session,
            accion=AccionAuditoria.DESPACHO_CONFIRMADO,
            usuario_o_nodo=f"nodo:{dependencia.miembro_xroad}",
            ip_origen=IP_NODO_INTERNO,
            entidad="despachos_interoperables",
            entidad_id=despacho_id,
            detalle={"acuse_id": acuse.acuse_id, "jti": mensaje.jti},
        )
        return despacho_a_dto(confirmado)


def listar_despachos(*, evento_id: int | None, limit: int, offset: int) -> list[DespachoOut]:
    consulta = select(DespachoInteroperable)
    if evento_id is not None:
        consulta = consulta.where(col(DespachoInteroperable.evento_id) == evento_id)
    consulta = consulta.order_by(col(DespachoInteroperable.timestamp_despacho).desc()).offset(offset).limit(limit)
    with lectura() as session:
        return [despacho_a_dto(d) for d in session.exec(consulta).all()]


def obtener_despacho(despacho_id: int) -> DespachoOut:
    with lectura() as session:
        despacho = session.get(DespachoInteroperable, despacho_id)
        if despacho is None:
            raise RecursoNoEncontrado(f"Despacho {despacho_id} no encontrado.")
        return despacho_a_dto(despacho)


def _id(despacho: DespachoInteroperable) -> int:
    if despacho.id is None:
        raise RuntimeError("Despacho sin id persistido.")
    return despacho.id
