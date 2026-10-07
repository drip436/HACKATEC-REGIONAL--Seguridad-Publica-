"""Datos simulados con la forma interna de `modelos.py`.

Sirven de respaldo sin backend (SENTINEL_MOCK=1) y como fuente del simulador
de Edge AI (`simular_edge.py`). Todo lo que sale de aquí es sintético.
"""

import random
import uuid
from datetime import datetime, timedelta

from .modelos import Camara, EventoHistorico

# Las alertas en vivo caen exactamente en la coordenada de su cámara. Solo el
# histórico se reparte (~400 m) para que el mapa de calor tenga forma.
_DISPERSION_HISTORICO = 0.004


def _cam(id_: str, nombre: str, lat: float, lng: float, activa: bool = True) -> Camara:
    return {"id": id_, "nombre": nombre, "lat": lat, "lng": lng, "activa": activa}


# Cámaras de DEMOSTRACIÓN en espacios públicos de Tabasco (coordenadas de
# OpenStreetMap). Las alertas que el simulador genera aquí son sintéticas: no son
# datos oficiales de incidencia delictiva de esas zonas.
CAMARAS: list[Camara] = [
    _cam("CAM-VHS-PLAZA-ARMAS", "Plaza de Armas, Villahermosa", 17.987172, -92.919115),
    _cam("CAM-VHS-LA-CHOCA", "Parque La Choca, Villahermosa", 18.004057, -92.952883),
    _cam("CAM-VHS-TAMULTE", "Tamulté de las Barrancas, Villahermosa", 17.970279, -92.958208),
    _cam("CAM-VHS-ATASTA", "Atasta, Villahermosa", 17.979867, -92.950540),
    _cam("CAM-VHS-CD-INDUSTRIAL", "Ciudad Industrial, Villahermosa", 18.025609, -92.901099, activa=False),
    _cam("CAM-CAR-CENTRO", "Centro de Cárdenas", 18.169370, -93.705229),
    _cam("CAM-COM-CENTRO", "Centro de Comalcalco", 18.261508, -93.223152),
]
CODIGOS_DEMO = frozenset(c["id"] for c in CAMARAS)

# Peso relativo de cada cámara y de cada hora: sesga el histórico para que
# existan franjas y zonas críticas reconocibles.
_PESO_CAMARA = [4, 2, 3, 2, 1, 2, 1]
_PESO_HORA = [1, 1, 1, 1, 1, 1, 2, 4, 5, 3, 2, 2, 4, 5, 4, 2, 2, 4, 7, 9, 8, 5, 3, 2]
_TIPOS = ["traspaso_perimetro", "aglomeracion", "merodeo", "objeto_abandonado"]
_PESO_TIPO = [5, 3, 2, 1]


def generar_evento(
    momento: datetime | None = None,
    rng: random.Random | None = None,
    solo_activas: bool = True,
    dispersion: float = 0.0,
) -> dict:
    """Evento pendiente con la forma interna de una alerta."""
    rng = rng or random
    opciones = [(c, p) for c, p in zip(CAMARAS, _PESO_CAMARA, strict=True) if c["activa"] or not solo_activas]
    camara = rng.choices([c for c, _ in opciones], weights=[p for _, p in opciones])[0]
    momento = momento or datetime.now()
    return {
        "id": f"sim-{uuid.UUID(int=rng.getrandbits(128)).hex[:8]}",
        "camara_id": camara["id"],
        "tipo": rng.choices(_TIPOS, weights=_PESO_TIPO)[0],
        "severidad": rng.choices(["baja", "media", "alta", "critica"], weights=[3, 4, 3, 1])[0],
        "confianza": round(rng.uniform(0.55, 0.97), 2),
        "timestamp": momento.astimezone().isoformat(timespec="seconds"),
        "lat": round(camara["lat"] + rng.uniform(-dispersion, dispersion), 6),
        "lng": round(camara["lng"] + rng.uniform(-dispersion, dispersion), 6),
        "snapshot_url": "",
        "estado": "pendiente",
    }


def eventos_iniciales() -> list[dict]:
    ahora = datetime.now()
    return [generar_evento(ahora - timedelta(minutes=m)) for m in (2, 6, 11)]


def eventos_historicos(dias: int = 30) -> list[dict]:
    """Histórico reproducible (semilla fija) de los `dias` días anteriores a hoy."""
    rng = random.Random(2026)
    hoy = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    eventos = []
    for d in range(1, dias + 1):
        dia = hoy - timedelta(days=d)
        factor_dia = 0.4 if dia.weekday() >= 5 else 1.0
        for _ in range(int(rng.randint(10, 18) * factor_dia)):
            hora = rng.choices(range(24), weights=_PESO_HORA)[0]
            momento = dia.replace(hour=hora, minute=rng.randint(0, 59), second=rng.randint(0, 59))
            eventos.append(generar_evento(momento, rng, solo_activas=False, dispersion=_DISPERSION_HISTORICO))
    return eventos


def historico_sintetico(dias: int = 30) -> list[EventoHistorico]:
    return [
        {"timestamp": e["timestamp"], "tipo": e["tipo"], "cuadrante": "", "lat": e["lat"], "lng": e["lng"]}
        for e in eventos_historicos(dias)
    ]
