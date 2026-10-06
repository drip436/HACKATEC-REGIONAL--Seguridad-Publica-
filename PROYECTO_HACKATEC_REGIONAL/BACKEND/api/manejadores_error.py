from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError

from ..errores import SentinelError

logger = logging.getLogger("sentinelops.api")


def _respuesta(status: int, codigo: str, mensaje: str, detalle: object | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"codigo": codigo, "mensaje": mensaje, "detalle": jsonable_encoder(detalle or {})}},
    )


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(SentinelError)
    async def _dominio(_: Request, exc: SentinelError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("Error de dominio %s: %s", exc.codigo, exc.mensaje)
        return _respuesta(exc.status_code, exc.codigo, exc.mensaje, exc.detalle)

    @app.exception_handler(RequestValidationError)
    async def _validacion(_: Request, exc: RequestValidationError) -> JSONResponse:
        errores = [
            {"campo": ".".join(str(p) for p in e.get("loc", ())), "mensaje": e.get("msg"), "tipo": e.get("type")}
            for e in exc.errors()
        ]
        return _respuesta(422, "validacion_fallida", "La solicitud no cumple el esquema.", {"errores": errores})

    @app.exception_handler(IntegrityError)
    async def _integridad(_: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning("Violación de integridad: %s", exc.orig)
        return _respuesta(409, "conflicto_integridad", "La operación viola una restricción de la base de datos.")

    @app.exception_handler(OperationalError)
    async def _bd(_: Request, exc: OperationalError) -> JSONResponse:
        logger.error("Base de datos no disponible: %s", exc.orig)
        return _respuesta(503, "bd_no_disponible", "Base de datos no disponible temporalmente.")

    @app.exception_handler(Exception)
    async def _inesperado(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Error no controlado", exc_info=exc)
        return _respuesta(500, "error_interno", "Error interno del servidor.")
