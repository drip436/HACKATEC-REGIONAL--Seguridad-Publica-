"""Simulador de servidor de seguridad estilo X-Road.

Principios que se reproducen:
- Identidad de miembros (INSTANCIA/CLASE/MIEMBRO/SUBSISTEMA) en `iss`/`aud`.
- Integridad y no repudio: el JWT firma el SHA-256 del payload canónico.
- Sello de tiempo (`iat`/`nbf`/`exp`) y anti-replay por `jti`.
- Acuse de recibo firmado por el receptor con su propia llave.
- Minimización de datos: solo metadatos operativos, nunca evidencia visual.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import jwt

from ..config import get_settings
from ..errores import FederacionFallida, FirmaInvalida, IntegridadComprometida, ReplayDetectado, SentinelError
from ..models import AccionAuditoria, CamaraSensor, Dependencia, EventoDetectado
from ..schemas import AcuseFederacionOut, MiembroFederadoOut, SolicitudFederacionIn
from ..utils.crypto import comparar_seguro, derivar_secreto, hash_payload
from ..utils.tiempo import UTC, a_utc, ahora_utc, iso_utc
from .auditoria import registrar
from .db import transaccion

PROTOCOLO = "sentinelops-xroad-sim/1.0"
SERVICIO = "alertas.recibir/v1"
_CLAIMS_REQUERIDOS = ["iss", "sub", "aud", "iat", "nbf", "exp", "jti", "payload_sha256"]
_MIEMBRO_A_DEPENDENCIA: dict[str, Dependencia] = {d.miembro_xroad: d for d in Dependencia}


@dataclass(frozen=True, slots=True)
class MensajeFirmado:
    token: str
    jti: str
    payload_sha256: str
    emitido_en: datetime
    expira_en: datetime


class _CacheAntiReplay:
    """Registro en memoria de `jti` ya aceptados mientras el token siga vigente."""

    def __init__(self) -> None:
        self._vistos: dict[str, float] = {}
        self._lock = threading.Lock()

    def consumir(self, jti: str, expira_epoch: float) -> bool:
        ahora = time.time()
        with self._lock:
            self._vistos = {k: v for k, v in self._vistos.items() if v > ahora}
            if jti in self._vistos:
                return False
            self._vistos[jti] = expira_epoch
            return True


_anti_replay = _CacheAntiReplay()


def miembros_federados() -> list[MiembroFederadoOut]:
    return [MiembroFederadoOut(dependencia=d, miembro_xroad=d.miembro_xroad) for d in Dependencia]


def construir_payload_federado(
    evento: EventoDetectado,
    sensor: CamaraSensor,
    *,
    instrucciones: str | None,
) -> dict[str, Any]:
    deteccion = evento.metadata_json or {}
    return {
        "esquema": "sentinelops.alerta/v1",
        "evento_id": evento.id,
        "tipo_evento": evento.tipo_evento,
        "nivel_prioridad": evento.nivel_prioridad,
        "fecha_deteccion": iso_utc(evento.fecha_deteccion),
        "ubicacion": {
            "lat": evento.latitud,
            "lng": evento.longitud,
            "sensor": sensor.codigo,
            "referencia": sensor.nombre_ubicacion,
        },
        "deteccion": {
            "clase": deteccion.get("clase_detectada"),
            "confianza": deteccion.get("confianza"),
            "conteo_personas": deteccion.get("conteo_personas"),
        },
        "validacion_humana": {
            "operador_id": evento.operador_id,
            "validado_en": iso_utc(evento.validado_en) if evento.validado_en else None,
        },
        "instrucciones": instrucciones,
        # La evidencia visual no viaja: la dependencia la solicita por un canal autorizado.
        "evidencia_disponible": evento.evidencia_url is not None,
    }


def firmar_mensaje(payload: dict[str, Any], *, dependencia: Dependencia, despacho_id: int) -> MensajeFirmado:
    settings = get_settings()
    emitido = ahora_utc().replace(microsecond=0)
    expira = emitido + timedelta(seconds=settings.jwt_ttl_segundos)
    jti = uuid.uuid4().hex
    payload_sha256 = hash_payload(payload)
    claims = {
        "iss": settings.nodo_central_id,
        "sub": f"despacho:{despacho_id}",
        "aud": dependencia.miembro_xroad,
        "iat": int(emitido.timestamp()),
        "nbf": int(emitido.timestamp()),
        "exp": int(expira.timestamp()),
        "jti": jti,
        "payload_sha256": payload_sha256,
        "xrd": {"protocolo": PROTOCOLO, "servicio": SERVICIO},
    }
    token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algoritmo)
    return MensajeFirmado(token=token, jti=jti, payload_sha256=payload_sha256, emitido_en=emitido, expira_en=expira)


def recibir_federacion(solicitud: SolicitudFederacionIn, *, ip_origen: str) -> AcuseFederacionOut:
    """Lado receptor (dependencia externa): verifica firma, integridad y frescura,
    y devuelve un acuse firmado. Todo intento, aceptado o rechazado, queda en bitácora."""
    settings = get_settings()
    try:
        claims = _decodificar(solicitud.token)
        miembro = str(claims["aud"])
        calculado = hash_payload(solicitud.payload)
        if not comparar_seguro(calculado, str(claims["payload_sha256"])):
            raise IntegridadComprometida(
                "El payload no coincide con el hash sellado en el token.",
                detalle={"esperado": claims["payload_sha256"], "recibido": calculado},
            )
        if not _anti_replay.consumir(str(claims["jti"]), float(claims["exp"])):
            raise ReplayDetectado("El token ya fue utilizado.", detalle={"jti": claims["jti"]})
    except SentinelError as exc:
        _auditar_rechazo(exc, ip_origen=ip_origen)
        raise

    recibido = ahora_utc()
    acuse_id = uuid.uuid4().hex
    firma = jwt.encode(
        {
            "iss": miembro,
            "aud": settings.nodo_central_id,
            "iat": int(recibido.timestamp()),
            "acuse_id": acuse_id,
            "ref_jti": claims["jti"],
            "payload_sha256": claims["payload_sha256"],
        },
        derivar_secreto(settings.jwt_secret, miembro),
        algorithm=settings.jwt_algoritmo,
    )
    acuse = AcuseFederacionOut(
        acuse_id=acuse_id,
        miembro_receptor=miembro,
        miembro_emisor=str(claims["iss"]),
        referencia_jti=str(claims["jti"]),
        payload_sha256=str(claims["payload_sha256"]),
        recibido_en=recibido,
        firma_acuse=firma,
    )
    with transaccion() as session:
        registrar(
            session,
            accion=AccionAuditoria.FEDERACION_RECIBIDA,
            usuario_o_nodo=f"nodo:{miembro}",
            ip_origen=ip_origen,
            entidad="federacion",
            entidad_id=str(claims["sub"]),
            detalle={
                "emisor": claims["iss"],
                "jti": claims["jti"],
                "acuse_id": acuse_id,
                "payload_sha256": claims["payload_sha256"],
                "sello_tiempo": iso_utc(datetime.fromtimestamp(int(claims["iat"]), tz=UTC)),
            },
        )
    return acuse


def verificar_acuse(acuse: AcuseFederacionOut, mensaje: MensajeFirmado, dependencia: Dependencia) -> None:
    settings = get_settings()
    try:
        claims = jwt.decode(
            acuse.firma_acuse,
            derivar_secreto(settings.jwt_secret, dependencia.miembro_xroad),
            algorithms=[settings.jwt_algoritmo],
            audience=settings.nodo_central_id,
            issuer=dependencia.miembro_xroad,
            options={"require": ["iss", "aud", "iat", "acuse_id", "ref_jti", "payload_sha256"]},
        )
    except jwt.InvalidTokenError as exc:
        raise FederacionFallida("Acuse de recibo con firma inválida.", detalle={"causa": str(exc)}) from exc
    if claims["ref_jti"] != mensaje.jti or not comparar_seguro(claims["payload_sha256"], mensaje.payload_sha256):
        raise FederacionFallida("El acuse no corresponde al mensaje enviado.", detalle={"jti": mensaje.jti})
    if a_utc(acuse.recibido_en) > mensaje.expira_en:
        raise FederacionFallida("Acuse recibido fuera de la vigencia del token.")


def _decodificar(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algoritmo],
            audience=list(_MIEMBRO_A_DEPENDENCIA),
            issuer=settings.nodo_central_id,
            leeway=5,
            options={"require": _CLAIMS_REQUERIDOS},
        )
    except jwt.ExpiredSignatureError as exc:
        raise FirmaInvalida("Token de interoperabilidad expirado.") from exc
    except jwt.InvalidAudienceError as exc:
        raise FirmaInvalida("El miembro destino no pertenece a la federación.") from exc
    except jwt.InvalidTokenError as exc:
        raise FirmaInvalida("Token de interoperabilidad inválido.", detalle={"causa": str(exc)}) from exc


def _auditar_rechazo(exc: SentinelError, *, ip_origen: str) -> None:
    with transaccion() as session:
        registrar(
            session,
            accion=AccionAuditoria.FEDERACION_RECHAZADA,
            usuario_o_nodo="nodo:desconocido",
            ip_origen=ip_origen,
            entidad="federacion",
            entidad_id=None,
            detalle={"codigo": exc.codigo, "mensaje": exc.mensaje},
        )
