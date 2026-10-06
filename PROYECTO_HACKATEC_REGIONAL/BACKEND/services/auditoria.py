from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlmodel import Session, col, func, select

from ..models import AccionAuditoria, BitacoraAuditoria
from ..schemas import PaginaAuditoria, VerificacionCadenaOut
from ..utils.crypto import hash_payload
from ..utils.tiempo import ahora_utc, iso_utc
from .db import lectura, transaccion
from .mapeo import auditoria_a_dto

HASH_GENESIS = "0" * 64
_PG_ADVISORY_KEY = 0x5E7140  # constante arbitraria compartida por todos los workers


def calcular_hash_registro(
    *,
    hash_anterior: str,
    accion: str,
    usuario_o_nodo: str,
    ip_origen: str,
    entidad: str,
    entidad_id: str | None,
    payload_hash_sha256: str,
    timestamp: datetime,
) -> str:
    """hash_n = SHA256(hash_{n-1} || campos_n). Alterar cualquier registro rompe
    todos los hashes posteriores, lo que hace detectable la manipulación."""
    return hash_payload(
        {
            "hash_anterior": hash_anterior,
            "accion": accion,
            "usuario_o_nodo": usuario_o_nodo,
            "ip_origen": ip_origen,
            "entidad": entidad,
            "entidad_id": entidad_id,
            "payload_hash_sha256": payload_hash_sha256,
            "timestamp": iso_utc(timestamp),
        }
    )


def registrar(
    session: Session,
    *,
    accion: AccionAuditoria,
    usuario_o_nodo: str,
    ip_origen: str,
    entidad: str,
    entidad_id: int | str | None,
    detalle: dict[str, Any],
) -> BitacoraAuditoria:
    """Agrega un eslabón a la cadena dentro de la transacción del llamador, de modo
    que la acción de negocio y su rastro se confirman (o se revierten) juntos."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(sa.text("SELECT pg_advisory_xact_lock(:k)"), {"k": _PG_ADVISORY_KEY})

    ultimo = session.exec(
        select(BitacoraAuditoria.hash_registro).order_by(col(BitacoraAuditoria.id).desc()).limit(1)
    ).first()
    hash_anterior = ultimo or HASH_GENESIS
    timestamp = ahora_utc()
    entidad_id_txt = str(entidad_id) if entidad_id is not None else None
    payload_hash = hash_payload(detalle)

    registro = BitacoraAuditoria(
        accion=accion.value,
        usuario_o_nodo=usuario_o_nodo,
        ip_origen=ip_origen,
        entidad=entidad,
        entidad_id=entidad_id_txt,
        detalle_json=detalle,
        payload_hash_sha256=payload_hash,
        hash_anterior=hash_anterior,
        hash_registro=calcular_hash_registro(
            hash_anterior=hash_anterior,
            accion=accion.value,
            usuario_o_nodo=usuario_o_nodo,
            ip_origen=ip_origen,
            entidad=entidad,
            entidad_id=entidad_id_txt,
            payload_hash_sha256=payload_hash,
            timestamp=timestamp,
        ),
        timestamp_inmutable=timestamp,
    )
    session.add(registro)
    session.flush()
    return registro


def consultar(
    *,
    accion: AccionAuditoria | None,
    entidad: str | None,
    entidad_id: str | None,
    desde: datetime | None,
    hasta: datetime | None,
    limit: int,
    offset: int,
    consultado_por: str,
    ip_origen: str,
) -> PaginaAuditoria:
    filtros: list[Any] = []
    if accion is not None:
        filtros.append(col(BitacoraAuditoria.accion) == accion.value)
    if entidad is not None:
        filtros.append(col(BitacoraAuditoria.entidad) == entidad)
    if entidad_id is not None:
        filtros.append(col(BitacoraAuditoria.entidad_id) == entidad_id)
    if desde is not None:
        filtros.append(col(BitacoraAuditoria.timestamp_inmutable) >= desde)
    if hasta is not None:
        filtros.append(col(BitacoraAuditoria.timestamp_inmutable) <= hasta)

    with lectura() as session:
        total = session.exec(select(func.count()).select_from(BitacoraAuditoria).where(*filtros)).one()
        filas = session.exec(
            select(BitacoraAuditoria)
            .where(*filtros)
            .order_by(col(BitacoraAuditoria.id).desc())
            .offset(offset)
            .limit(limit)
        ).all()
        items = [auditoria_a_dto(f) for f in filas]

    # El acceso a la bitácora también deja rastro (requisito de gobernanza).
    with transaccion() as session:
        registrar(
            session,
            accion=AccionAuditoria.AUDITORIA_CONSULTADA,
            usuario_o_nodo=consultado_por,
            ip_origen=ip_origen,
            entidad="bitacora_auditoria",
            entidad_id=None,
            detalle={
                "filtros": {
                    "accion": accion.value if accion else None,
                    "entidad": entidad,
                    "entidad_id": entidad_id,
                    "desde": iso_utc(desde) if desde else None,
                    "hasta": iso_utc(hasta) if hasta else None,
                },
                "resultados": len(items),
            },
        )
    return PaginaAuditoria(total=total, limit=limit, offset=offset, items=items)


def verificar_cadena(lote: int = 500) -> VerificacionCadenaOut:
    esperado_anterior = HASH_GENESIS
    verificados = 0
    ultimo_id = 0
    with lectura() as session:
        while True:
            filas = session.exec(
                select(BitacoraAuditoria)
                .where(col(BitacoraAuditoria.id) > ultimo_id)
                .order_by(col(BitacoraAuditoria.id))
                .limit(lote)
            ).all()
            if not filas:
                break
            for r in filas:
                rid = r.id or 0
                if r.hash_anterior != esperado_anterior:
                    return _fallo(verificados, esperado_anterior, rid, "Eslabón roto: hash_anterior no coincide.")
                if hash_payload(r.detalle_json) != r.payload_hash_sha256:
                    return _fallo(verificados, esperado_anterior, rid, "El detalle fue alterado (payload hash).")
                recalculado = calcular_hash_registro(
                    hash_anterior=r.hash_anterior,
                    accion=r.accion,
                    usuario_o_nodo=r.usuario_o_nodo,
                    ip_origen=r.ip_origen,
                    entidad=r.entidad,
                    entidad_id=r.entidad_id,
                    payload_hash_sha256=r.payload_hash_sha256,
                    timestamp=r.timestamp_inmutable,
                )
                if recalculado != r.hash_registro:
                    return _fallo(verificados, esperado_anterior, rid, "hash_registro no corresponde al contenido.")
                esperado_anterior = r.hash_registro
                verificados += 1
                ultimo_id = rid
    return VerificacionCadenaOut(integra=True, registros_verificados=verificados, ultimo_hash=esperado_anterior)


def _fallo(verificados: int, ultimo_hash: str, rid: int, motivo: str) -> VerificacionCadenaOut:
    return VerificacionCadenaOut(
        integra=False,
        registros_verificados=verificados,
        ultimo_hash=ultimo_hash,
        primer_registro_invalido=rid,
        motivo=motivo,
    )
