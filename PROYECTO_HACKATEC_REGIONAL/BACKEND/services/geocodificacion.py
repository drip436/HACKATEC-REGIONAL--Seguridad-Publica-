"""Dirección -> coordenadas, para ubicar una cámara con precisión.

Con `GOOGLE_MAPS_API_KEY` en el .env se usa la Geocoding API de Google (la llave
nunca sale del backend); sin ella, Nominatim de OpenStreetMap. La búsqueda se
limita a México y prioriza la región Sur-Sureste.
"""

from __future__ import annotations

import logging
import os
import re

import httpx

from ..errores import SolicitudInvalida
from ..schemas import LugarOut

LOGGER = logging.getLogger("sentinelops.geocodificacion")

_GOOGLE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Caja de la región Sur-Sureste (sur-oeste | nor-este): sesga, no excluye.
_REGION_GOOGLE = "14.3,-102.2|21.9,-86.6"
_REGION_NOMINATIM = "-102.2,21.9,-86.6,14.3"
_TIMEOUT = httpx.Timeout(connect=3.0, read=6.0, write=3.0, pool=3.0)
_MAX_RESULTADOS = 5

_NUM = r"(-?\d{1,3}\.\d+)"
# Enlace de Google Maps: el pin exacto (!3d..!4d..) manda sobre el centro de la vista (@lat,lng).
_PATRONES_COORDENADAS = (
    re.compile(rf"!3d{_NUM}!4d{_NUM}"),
    re.compile(rf"[?&](?:q|query|ll|destination)={_NUM},\s*{_NUM}"),
    re.compile(rf"@{_NUM},{_NUM}"),
    re.compile(rf"^\s*{_NUM}\s*,\s*{_NUM}\s*$"),  # "17.995501, -92.920302"
)


def coordenadas_en_texto(texto: str) -> tuple[float, float] | None:
    """Coordenadas pegadas tal cual o dentro de un enlace de Google Maps."""
    for patron in _PATRONES_COORDENADAS:
        encontrado = patron.search(texto)
        if encontrado:
            lat, lng = float(encontrado.group(1)), float(encontrado.group(2))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
    return None


def proveedor() -> str:
    return "google" if os.getenv("GOOGLE_MAPS_API_KEY", "").strip() else "openstreetmap"


def buscar(consulta: str) -> list[LugarOut]:
    consulta = consulta.strip()
    if len(consulta) < 3:
        return []
    exactas = coordenadas_en_texto(consulta)
    if exactas is not None:
        return [LugarOut(nombre=f"Coordenadas {exactas[0]:.6f}, {exactas[1]:.6f}", lat=round(exactas[0], 6),
                         lng=round(exactas[1], 6), fuente="coordenadas")]
    llave = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    try:
        return _google(consulta, llave) if llave else _nominatim(consulta)
    except (httpx.HTTPError, ValueError, KeyError) as error:
        LOGGER.warning("Geocodificación falló (%s): %s", proveedor(), error)
        return []


def _google(consulta: str, llave: str) -> list[LugarOut]:
    r = httpx.get(
        _GOOGLE_URL,
        params={"address": consulta, "key": llave, "region": "mx", "language": "es", "bounds": _REGION_GOOGLE,
                "components": "country:MX"},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    datos = r.json()
    if datos.get("status") not in ("OK", "ZERO_RESULTS"):
        # REQUEST_DENIED / OVER_QUERY_LIMIT: llave mal configurada. Se intenta con OSM.
        LOGGER.warning("Google Geocoding respondió %s: %s", datos.get("status"), datos.get("error_message", ""))
        return _nominatim(consulta)
    return [
        LugarOut(
            nombre=res["formatted_address"],
            lat=round(res["geometry"]["location"]["lat"], 6),
            lng=round(res["geometry"]["location"]["lng"], 6),
            fuente="google",
        )
        for res in datos.get("results", [])[:_MAX_RESULTADOS]
    ]


def _nominatim(consulta: str) -> list[LugarOut]:
    r = httpx.get(
        _NOMINATIM_URL,
        params={"q": consulta, "format": "json", "limit": _MAX_RESULTADOS, "countrycodes": "mx",
                "viewbox": _REGION_NOMINATIM, "accept-language": "es"},
        headers={"User-Agent": "SentinelOps/1.0 (HackaTec)"},
        timeout=_TIMEOUT,
    )
    r.raise_for_status()
    return [
        LugarOut(nombre=res["display_name"], lat=round(float(res["lat"]), 6), lng=round(float(res["lon"]), 6),
                 fuente="openstreetmap")
        for res in r.json()
    ]


# --- ¿Está en tierra? ----------------------------------------------------------

_OSRM_URL = os.getenv("SENTINEL_OSRM_URL", "https://router.project-osrm.org").rstrip("/")
# Una cámara (y por lo tanto un incidente) debe quedar a menos de esto de una calle:
# más lejos es mar, laguna o un clic mal dado, y la patrulla no podría llegar.
MAX_DISTANCIA_A_CALLE_M = 1000.0


def distancia_a_calle_m(lat: float, lng: float) -> float | None:
    """Metros a la calle transitable más cercana (OSRM nearest). None si no hay red.

    El servidor público de OSRM a veces tarda en el saludo TLS: se reintenta una vez
    con más paciencia antes de aceptar la ubicación sin verificar."""
    ultimo: Exception | None = None
    for intento in range(2):
        try:
            r = httpx.get(
                f"{_OSRM_URL}/nearest/v1/driving/{lng:.6f},{lat:.6f}",
                params={"number": 1},
                timeout=httpx.Timeout(connect=5.0 + 5.0 * intento, read=8.0, write=5.0, pool=5.0),
            )
            r.raise_for_status()
            return float(r.json()["waypoints"][0]["distance"])
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
            ultimo = error
    LOGGER.warning("No se pudo verificar la ubicación con OSRM (%s); se acepta tal cual.", ultimo)
    return None


def verificar_en_tierra(lat: float, lng: float) -> None:
    """422 si el punto está lejos de cualquier calle (p. ej. en el mar)."""
    distancia = distancia_a_calle_m(lat, lng)
    if distancia is not None and distancia > MAX_DISTANCIA_A_CALLE_M:
        raise SolicitudInvalida(
            f"La ubicación ({lat:.6f}, {lng:.6f}) está a {distancia / 1000:.1f} km de la calle más cercana "
            "(¿en el mar o en una laguna?). Acerca el mapa y marca el punto exacto de la cámara.",
            detalle={"distancia_a_calle_m": round(distancia)},
        )
