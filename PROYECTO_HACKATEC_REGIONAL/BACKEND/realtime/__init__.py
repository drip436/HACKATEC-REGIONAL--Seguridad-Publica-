from functools import lru_cache

from ..config import get_settings
from .manager import ConnectionManager


@lru_cache(maxsize=1)
def get_manager() -> ConnectionManager:
    return ConnectionManager(max_conexiones=get_settings().ws_max_conexiones)


__all__ = ["ConnectionManager", "get_manager"]
