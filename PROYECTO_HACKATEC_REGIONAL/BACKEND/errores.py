from __future__ import annotations

from typing import Any


class SentinelError(Exception):
    """Error de dominio con código estable para que el frontend y los nodos lo interpreten."""

    status_code: int = 500
    codigo: str = "error_interno"

    def __init__(self, mensaje: str, *, detalle: dict[str, Any] | None = None) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalle = detalle or {}

    def a_dict(self) -> dict[str, Any]:
        return {"error": {"codigo": self.codigo, "mensaje": self.mensaje, "detalle": self.detalle}}


class RecursoNoEncontrado(SentinelError):
    status_code = 404
    codigo = "recurso_no_encontrado"


class ConflictoEstado(SentinelError):
    status_code = 409
    codigo = "conflicto_estado"


class SolicitudInvalida(SentinelError):
    status_code = 422
    codigo = "solicitud_invalida"


class NoAutenticado(SentinelError):
    status_code = 401
    codigo = "no_autenticado"


class FirmaInvalida(SentinelError):
    status_code = 401
    codigo = "firma_invalida"


class IntegridadComprometida(SentinelError):
    status_code = 422
    codigo = "integridad_comprometida"


class ReplayDetectado(SentinelError):
    status_code = 409
    codigo = "replay_detectado"


class FederacionFallida(SentinelError):
    status_code = 502
    codigo = "federacion_fallida"
