"""Datos simulados que respetan el contrato de `modelos.py`.

Se usan mientras la API de Dev 2 no esté disponible (SENTINEL_MOCK=1) y como
respaldo para la demo. Todo lo que sale de aquí es sintético.
"""

import random
import uuid
from datetime import datetime, timedelta

from .modelos import Camara, Cuadrante, EventoHistorico

# TODO(equipo): coordenadas de ejemplo; sustituir por las reales del campus.
CENTRO = [20.5365, -100.8150]
ZOOM = 17

_DLAT = 0.0014
_DLNG = 0.0018


def _rect(fila: int, col: int) -> list[list[float]]:
    lat0 = CENTRO[0] + (_DLAT if fila == 0 else 0) - _DLAT
    lng0 = CENTRO[1] + (_DLNG if col == 1 else 0) - _DLNG
    return [
        [lat0, lng0],
        [lat0 + _DLAT, lng0],
        [lat0 + _DLAT, lng0 + _DLNG],
        [lat0, lng0 + _DLNG],
    ]


CUADRANTES: list[Cuadrante] = [
    {"id": "Q1", "nombre": "Q1 · Acceso Norte", "coords": _rect(0, 0)},
    {"id": "Q2", "nombre": "Q2 · Laboratorios", "coords": _rect(0, 1)},
    {"id": "Q3", "nombre": "Q3 · Patio Central", "coords": _rect(1, 0)},
    {"id": "Q4", "nombre": "Q4 · Estacionamiento", "coords": _rect(1, 1)},
]


def _cam(id_: str, nombre: str, cuadrante: str, dlat: float, dlng: float, activa: bool = True) -> Camara:
    return {
        "id": id_,
        "nombre": nombre,
        "cuadrante": cuadrante,
        "lat": round(CENTRO[0] + dlat * _DLAT, 6),
        "lng": round(CENTRO[1] + dlng * _DLNG, 6),
        "activa": activa,
    }


CAMARAS: list[Camara] = [
    _cam("C-05", "Puerta Oeste", "Q1", 0.35, -0.75),
    _cam("C-12", "Acceso Norte / Edificio A", "Q1", 0.8, -0.3),
    _cam("C-19", "Laboratorios", "Q2", 0.55, 0.6),
    _cam("C-08", "Patio Central", "Q3", -0.4, -0.45),
    _cam("C-14", "Biblioteca", "Q3", -0.75, -0.8, activa=False),
    _cam("C-21", "Estacionamiento Sur", "Q4", -0.6, 0.55),
]

# Peso relativo de cada cámara y de cada hora: sesga el histórico para que
# existan franjas y zonas críticas reconocibles.
_PESO_CAMARA = {"C-05": 1, "C-12": 2, "C-19": 1, "C-08": 3, "C-14": 1, "C-21": 4}
_PESO_HORA = [1, 1, 1, 1, 1, 1, 2, 4, 5, 3, 2, 2, 4, 5, 4, 2, 2, 4, 7, 9, 8, 5, 3, 2]


def _evento_base(camara: Camara, momento: datetime, rng: random.Random) -> dict:
    return {
        "timestamp": momento.astimezone().isoformat(timespec="seconds"),
        "tipo": rng.choices(["intrusion", "aglomeracion"], weights=[3, 2])[0],
        "cuadrante": camara["cuadrante"],
        "lat": round(camara["lat"] + rng.uniform(-0.00025, 0.00025), 6),
        "lng": round(camara["lng"] + rng.uniform(-0.00025, 0.00025), 6),
    }


def generar_evento(momento: datetime | None = None, rng: random.Random | None = None) -> dict:
    """Evento con la misma forma que el POST de Dev 1."""
    rng = rng or random
    camaras = [c for c in CAMARAS if c["activa"]]
    camara = rng.choices(camaras, weights=[_PESO_CAMARA[c["id"]] for c in camaras])[0]
    return {
        "id": f"evt_{uuid.uuid4().hex[:8]}",
        "camara_id": camara["id"],
        "severidad": rng.choices(["baja", "media", "alta", "critica"], weights=[3, 4, 3, 1])[0],
        "confianza": round(rng.uniform(0.55, 0.97), 2),
        "snapshot_url": "",
        "estado": "pendiente",
        **_evento_base(camara, momento or datetime.now(), rng),
    }


def eventos_iniciales() -> list[dict]:
    ahora = datetime.now()
    return [generar_evento(ahora - timedelta(minutes=m)) for m in (2, 6, 11)]


def historico_sintetico(dias: int = 30) -> list[EventoHistorico]:
    """Histórico reproducible (semilla fija) de los últimos `dias` días."""
    rng = random.Random(2026)
    hoy = datetime.now().replace(minute=0, second=0, microsecond=0)
    eventos: list[EventoHistorico] = []
    for d in range(dias):
        dia = hoy - timedelta(days=d)
        factor_dia = 0.4 if dia.weekday() >= 5 else 1.0
        for _ in range(int(rng.randint(10, 18) * factor_dia)):
            hora = rng.choices(range(24), weights=_PESO_HORA)[0]
            camara = rng.choices(CAMARAS, weights=[_PESO_CAMARA[c["id"]] for c in CAMARAS])[0]
            momento = dia.replace(hour=hora, minute=rng.randint(0, 59))
            eventos.append(_evento_base(camara, momento, rng))  # type: ignore[arg-type]
    return eventos
