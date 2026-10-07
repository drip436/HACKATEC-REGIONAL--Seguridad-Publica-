"""Flota de patrullas (tabla `unidades_policiales`) y elección de la más cercana.

La carga inicial cubre la región Sur-Sureste (Tabasco, Campeche, Yucatán,
Quintana Roo, Chiapas, Oaxaca, Veracruz y Guerrero) con bases en los centros de
99 ciudades, colonias importantes de las capitales, 20 aeropuertos y 20 terminales
de autobuses. Cada base se localizó en OpenStreetMap (Nominatim) validando su tipo,
estado y distancia a la ciudad, y se ajustó al punto de calle más cercano (OSRM):
toda patrulla sale de una vialidad transitable. Son unidades de DEMOSTRACIÓN, no
el despliegue real de ninguna corporación. Las unidades con otro formato de código
que agregues a la tabla no se tocan.

Una unidad está ocupada mientras tenga una atención en camino; al llegar queda
libre de nuevo en su base.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from sqlmodel import Session, col, select

from ..models import AtencionCampo, EstadoAtencion, UnidadPolicial
from ..schemas import UnidadOut

LOGGER = logging.getLogger("sentinelops.flota")

ARCHIVO_SEMILLA = Path(__file__).resolve().parent.parent / "datos" / "flota_sursureste.json"
_RADIO_TIERRA_M = 6_371_000.0


@dataclass(frozen=True, slots=True)
class Unidad:
    id: str
    base: str
    lat: float
    lng: float


# Códigos que administra la semilla (TAB-01, QROO-12...). Las unidades que agregues con
# otro formato (p. ej. "MOTO-VHS-1") nunca se tocan.
_CODIGO_SEMILLA = re.compile(r"^(TAB|CAM|YUC|QROO|CHIS|OAX|VER|GRO)-\d+$")


def sembrar_flota(engine: sa.Engine) -> int:
    """Sincroniza las unidades de la semilla con la tabla. Idempotente.

    - Inserta las que faltan y corrige base/coordenadas de las que cambiaron.
    - Desactiva (no borra: hay atenciones que las mencionan) las unidades de la
      semilla anterior que ya no existen en la nueva.
    Devuelve cuántas filas cambiaron.
    """
    semilla = {u["codigo"]: u for u in json.loads(ARCHIVO_SEMILLA.read_text(encoding="utf-8"))}
    cambios = 0
    with Session(engine) as session:
        actuales = {u.codigo: u for u in session.exec(select(UnidadPolicial)).all()}
        for codigo, u in semilla.items():
            fila = actuales.get(codigo)
            if fila is None:
                session.add(UnidadPolicial(codigo=codigo, base=u["base"], estado=u["estado"], latitud=u["lat"], longitud=u["lng"]))
                cambios += 1
            elif (fila.base, fila.estado, fila.latitud, fila.longitud, fila.activa) != (u["base"], u["estado"], u["lat"], u["lng"], True):
                fila.base, fila.estado, fila.latitud, fila.longitud, fila.activa = u["base"], u["estado"], u["lat"], u["lng"], True
                session.add(fila)
                cambios += 1
        for codigo, fila in actuales.items():
            if codigo not in semilla and _CODIGO_SEMILLA.match(codigo) and fila.activa:
                fila.activa = False
                session.add(fila)
                cambios += 1
        if cambios:
            session.commit()
            LOGGER.info("Flota: %d unidades insertadas, corregidas o retiradas en unidades_policiales.", cambios)
    return cambios


def distancia_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distancia en línea recta (haversine) entre (lat, lng)."""
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlng = lat2 - lat1, math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * _RADIO_TIERRA_M * math.asin(math.sqrt(h))


def unidades(session: Session) -> list[Unidad]:
    filas = session.exec(
        select(UnidadPolicial).where(col(UnidadPolicial.activa).is_(True)).order_by(col(UnidadPolicial.codigo))
    ).all()
    return [Unidad(id=u.codigo, base=u.base, lat=u.latitud, lng=u.longitud) for u in filas]


def asignaciones(session: Session) -> dict[str, int]:
    """Unidad -> evento que está atendiendo ahora (solo las que van en camino)."""
    filas = session.exec(
        select(AtencionCampo.unidad, AtencionCampo.evento_id).where(
            col(AtencionCampo.estado) == EstadoAtencion.EN_CAMINO.value
        )
    ).all()
    return {unidad: evento_id for unidad, evento_id in filas}


def mas_cercana(session: Session, destino: tuple[float, float]) -> Unidad | None:
    ocupadas = asignaciones(session)
    libres = [u for u in unidades(session) if u.id not in ocupadas]
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
        for u in unidades(session)
    ]
