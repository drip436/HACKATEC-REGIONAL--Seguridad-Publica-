"""Geometría de la ciudad (Mérida, Yucatán) derivada del inventario de cámaras.

El backend guarda coordenadas, no cuadrantes: aquí se divide en 2×2 el área
que cubren las cámaras para poder agrupar eventos y planear rondines.
"""

import math

from .modelos import Camara, Cuadrante

# Vista inicial mientras no haya cámaras registradas: Plaza Grande, Centro de Mérida.
CENTRO_DEFECTO = [20.96706, -89.62373]
# Escala de ciudad: se ven el Centro Histórico y el Paseo de Montejo a la vez.
ZOOM = 14

# Media extensión mínima del área (grados, ~1.3 km): evita cuadrantes
# degenerados con pocas cámaras y deja margen alrededor de las de la orilla.
_MIN_LAT = 0.012
_MIN_LNG = 0.012
_MARGEN = 1.25

_NOMBRES = ["Q1 · Noroeste", "Q2 · Noreste", "Q3 · Suroeste", "Q4 · Sureste"]


def centro_de(camaras: list[Camara]) -> list[float]:
    if not camaras:
        return list(CENTRO_DEFECTO)
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

    A escala de ciudad los 4 cuadrantes son demasiado gruesos para planear un
    rondín: "Parque de Santa Lucía" orienta mejor que "Q4".
    """
    if not camaras:
        return respaldo
    # Distancia equirectangular: suficiente para comparar puntos de una ciudad.
    coseno = math.cos(math.radians(lat))
    cercana = min(camaras, key=lambda c: (c["lat"] - lat) ** 2 + ((c["lng"] - lng) * coseno) ** 2)
    return cercana["nombre"]
