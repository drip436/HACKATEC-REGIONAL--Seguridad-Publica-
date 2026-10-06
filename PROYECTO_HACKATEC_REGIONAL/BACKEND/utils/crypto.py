from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from enum import Enum
from typing import Any

from .tiempo import iso_utc


def _serializar(valor: Any) -> Any:
    if isinstance(valor, datetime):
        return iso_utc(valor)
    if isinstance(valor, Enum):
        return valor.value
    raise TypeError(f"Tipo no serializable en payload canónico: {type(valor).__name__}")


def json_canonico(data: Any) -> str:
    """JSON determinista (claves ordenadas, sin espacios): misma entrada => mismo hash
    en cualquier nodo, requisito para no repudio."""
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_serializar
    )


def sha256_hex(contenido: str | bytes) -> str:
    datos = contenido.encode("utf-8") if isinstance(contenido, str) else contenido
    return hashlib.sha256(datos).hexdigest()


def hash_payload(data: Any) -> str:
    return sha256_hex(json_canonico(data))


def derivar_secreto(secreto_maestro: str, contexto: str) -> str:
    """Deriva una llave por miembro federado (HMAC-SHA256) para simular que cada
    dependencia firma con su propia llave sin compartir el secreto maestro."""
    return hmac.new(secreto_maestro.encode(), contexto.encode(), hashlib.sha256).hexdigest()


def comparar_seguro(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return False
    return hmac.compare_digest(a.encode(), b.encode())
