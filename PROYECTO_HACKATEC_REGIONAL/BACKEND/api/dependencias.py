from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader

from ..config import get_settings
from ..errores import NoAutenticado
from ..utils.crypto import comparar_seguro

_header_sensor = APIKeyHeader(name="X-Sensor-Key", scheme_name="SensorKey", auto_error=False)
_header_operador = APIKeyHeader(name="X-Operador-Key", scheme_name="OperadorKey", auto_error=False)


def ip_cliente(request: Request) -> str:
    reenviada = request.headers.get("x-forwarded-for")
    if reenviada:
        return reenviada.split(",")[0].strip()[:64]
    return request.client.host if request.client else "desconocida"


def requiere_sensor(clave: Annotated[str | None, Security(_header_sensor)]) -> None:
    esperada = get_settings().sensor_api_key
    if esperada is not None and not comparar_seguro(clave, esperada):
        raise NoAutenticado("X-Sensor-Key ausente o inválida.")


def requiere_operador(clave: Annotated[str | None, Security(_header_operador)]) -> None:
    esperada = get_settings().operador_api_key
    if esperada is not None and not comparar_seguro(clave, esperada):
        raise NoAutenticado("X-Operador-Key ausente o inválida.")


IpCliente = Annotated[str, Depends(ip_cliente)]
SensorAutenticado = Depends(requiere_sensor)
OperadorAutenticado = Depends(requiere_operador)
