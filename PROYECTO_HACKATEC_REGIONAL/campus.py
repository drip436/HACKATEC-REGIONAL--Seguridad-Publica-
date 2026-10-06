"""Geometría del campus derivada del inventario de cámaras.

El backend guarda coordenadas, no cuadrantes: aquí se divide en 2×2 el área
que cubren las cámaras para poder agrupar eventos y planear rondines.
"""

from .modelos import Camara, Cuadrante

# Vista inicial mientras no haya cámaras registradas.
CENTRO_DEFECTO = [20.5365, -100.8150]
ZOOM = 17

# Media extensión mínima del área (grados): evita cuadrantes degenerados con
# pocas cámaras y deja margen alrededor de las de la orilla.
_MIN_LAT = 0.0014
_MIN_LNG = 0.0018
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
