"""Geometría de la región Sur-Sureste derivada del inventario de cámaras.

El backend guarda coordenadas, no cuadrantes: aquí se divide en 2×2 el área
que cubren las cámaras para poder agrupar eventos y planear rondines. Ninguna
función de este módulo modifica las coordenadas de una cámara o alerta.
"""

import math

from .modelos import Camara, Cuadrante, ZonaRiesgo

# Vista inicial mientras no haya datos: la región Sur-Sureste completa.
# En cuanto llegan cámaras o incidentes, el mapa se encuadra sobre ellos.
CENTRO_REGION = [18.6, -93.4]
ZOOM_REGION = 6

# Media extensión mínima del área (grados, ~1.3 km): evita cuadrantes
# degenerados con pocas cámaras y deja margen alrededor de las de la orilla.
_MIN_LAT = 0.012
_MIN_LNG = 0.012
_MARGEN = 1.25

_NOMBRES = ["Q1 · Noroeste", "Q2 · Noreste", "Q3 · Suroeste", "Q4 · Sureste"]

# Zonas de riesgo: cuántas se dibujan, eventos mínimos y radio (m).
_MAX_ZONAS = 8
_MIN_EVENTOS_ZONA = 3
_RADIO_MIN_M, _RADIO_MAX_M = 600.0, 3000.0
_RADIO_TIERRA_M = 6_371_000.0


def distancia_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distancia haversine en metros entre (lat, lng)."""
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlng = lat2 - lat1, math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * _RADIO_TIERRA_M * math.asin(math.sqrt(h))


def centro_de(camaras: list[Camara]) -> list[float]:
    if not camaras:
        return list(CENTRO_REGION)
    lats = [c["lat"] for c in camaras]
    lngs = [c["lng"] for c in camaras]
    return [(min(lats) + max(lats)) / 2, (min(lngs) + max(lngs)) / 2]


def calcular_cuadrantes(camaras: list[Camara]) -> list[Cuadrante]:
    lat0, lng0 = centro_de(camaras)
    dlat = max([_MIN_LAT, *[abs(c["lat"] - lat0) * _MARGEN for c in camaras]])
    dlng = max([_MIN_LNG, *[abs(c["lng"] - lng0) * _MARGEN for c in camaras]])
    esquinas = [(lat0, lng0 - dlng), (lat0, lng0), (lat0 - dlat, lng0 - dlng), (lat0 - dlat, lng0)]
    return [
        {
            "id": nombre[:2],
            "nombre": nombre,
            "coords": [[lat, lng], [lat + dlat, lng], [lat + dlat, lng + dlng], [lat, lng + dlng]],
        }
        for nombre, (lat, lng) in zip(_NOMBRES, esquinas, strict=True)
    ]


def cuadrante_de(lat: float, lng: float, cuadrantes: list[Cuadrante]) -> str:
    for cuadrante in cuadrantes:
        (lat_min, lng_min), _, (lat_max, lng_max), _ = cuadrante["coords"]
        if lat_min <= lat <= lat_max and lng_min <= lng <= lng_max:
            return cuadrante["id"]
    return "Fuera"


def zona_de(lat: float, lng: float, camaras: list[Camara], respaldo: str) -> str:
    """Nombre del lugar (cámara) más cercano al punto; `respaldo` si no hay cámaras.

    Los 4 cuadrantes son demasiado gruesos para planear un rondín:
    "Plaza de Armas" orienta mejor que "Q4".
    """
    if not camaras:
        return respaldo
    cercana = min(camaras, key=lambda c: distancia_m((c["lat"], c["lng"]), (lat, lng)))
    return cercana["nombre"]


def zonas_de_riesgo(puntos: list[tuple[float, float]], camaras: list[Camara]) -> list[ZonaRiesgo]:
    """Círculos de riesgo a partir de dónde se concentran los eventos.

    Los eventos se agrupan por el lugar (cámara) más cercano; el círculo se
    centra en el promedio de sus coordenadas y su radio cubre al 80 % de ellos.
    La opacidad (0.25–0.40) crece con la cantidad relativa de eventos.
    """
    grupos: dict[str, list[tuple[float, float]]] = {}
    for lat, lng in puntos:
        clave = zona_de(lat, lng, camaras, f"{lat:.2f},{lng:.2f}")
        grupos.setdefault(clave, []).append((lat, lng))
    candidatas = sorted(
        ((nombre, pts) for nombre, pts in grupos.items() if len(pts) >= _MIN_EVENTOS_ZONA),
        key=lambda par: len(par[1]),
        reverse=True,
    )[:_MAX_ZONAS]
    if not candidatas:
        return []
    tope = len(candidatas[0][1])
    zonas: list[ZonaRiesgo] = []
    for nombre, pts in candidatas:
        centro = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        distancias = sorted(distancia_m(centro, p) for p in pts)
        radio = distancias[int(0.8 * (len(distancias) - 1))]
        zonas.append(
            {
                "nombre": nombre,
                "lat": round(centro[0], 6),
                "lng": round(centro[1], 6),
                "radio_m": round(min(max(radio, _RADIO_MIN_M), _RADIO_MAX_M)),
                "eventos": len(pts),
                "opacidad": round(0.25 + 0.15 * len(pts) / tope, 2),
            }
        )
    return zonas
