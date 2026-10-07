"""Flota de patrullas (simulada) y elección de la unidad libre más cercana.

Las bases son lugares públicos de Mérida verificados en OpenStreetMap; las
unidades y sus bases son de DEMOSTRACIÓN, no el despliegue real de ninguna
corporación. Una unidad está ocupada mientras tenga una atención en camino;
al llegar queda libre de nuevo (vuelve a su base).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlmodel import Session, col, select

from ..models import AtencionCampo, EstadoAtencion
from ..schemas import UnidadOut

_RADIO_TIERRA_M = 6_371_000.0


@dataclass(frozen=True, slots=True)
class Unidad:
    id: str
    base: str
    lat: float
    lng: float


FLOTA: tuple[Unidad, ...] = (
    Unidad("PATRULLA-01", "Base Gran Plaza", 21.030114, -89.624435),
    Unidad("PATRULLA-02", "Base Parque de las Américas", 20.987489, -89.633197),
    Unidad("PATRULLA-03", "Base Centro (Plaza Grande)", 20.967074, -89.623744),
)


def distancia_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distancia en línea recta (haversine) entre (lat, lng)."""
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlng = lat2 - lat1, math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * _RADIO_TIERRA_M * math.asin(math.sqrt(h))


def asignaciones(session: Session) -> dict[str, int]:
    """Unidad -> evento que está atendiendo ahora (solo las que van en camino)."""
    filas = session.exec(
        select(AtencionCampo.unidad, AtencionCampo.evento_id).where(
            col(AtencionCampo.estado) == EstadoAtencion.EN_CAMINO.value
        )
    ).all()
    return {unidad: evento_id for unidad, evento_id in filas}


def mas_cercana(destino: tuple[float, float], ocupadas: set[str] | dict[str, int]) -> Unidad | None:
    libres = [u for u in FLOTA if u.id not in ocupadas]
    return min(libres, key=lambda u: distancia_m((u.lat, u.lng), destino), default=None)


def listar(session: Session) -> list[UnidadOut]:
    ocupadas = asignaciones(session)
    return [
        UnidadOut(
            id=u.id,
            base=u.base,
            lat=u.lat,
            lng=u.lng,
            estado="en_camino" if u.id in ocupadas else "libre",
            evento_id=ocupadas.get(u.id),
        )
        for u in FLOTA
    ]
