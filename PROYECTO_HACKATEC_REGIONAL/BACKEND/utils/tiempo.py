from __future__ import annotations

from datetime import datetime, timezone

UTC = timezone.utc


def ahora_utc() -> datetime:
    return datetime.now(UTC)


def a_utc(dt: datetime) -> datetime:
    # SQLite devuelve datetimes naive; todo lo persistido se guardó en UTC.
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def iso_utc(dt: datetime) -> str:
    """Formato fijo con microsegundos: la representación debe ser idéntica al
    calcular y al re-verificar un hash, sin importar el motor de BD."""
    return a_utc(dt).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
