"""Contrato de datos compartido con Dev 1 (Edge AI) y Dev 2 (API).

Solo viajan metadatos del evento: nada de biometría ni identidad de personas.
"""

from datetime import datetime
from typing import TypedDict

TIPOS = {"intrusion": "Intrusión", "aglomeracion": "Aglomeración"}
SEVERIDADES = {"baja": "Baja", "media": "Media", "alta": "Alta", "critica": "Crítica"}
ESTADOS = {"pendiente": "Pendiente", "confirmado": "Confirmado", "descartado": "Descartado"}

DESTINOS = ["Seguridad de campus", "C4 Municipal", "Protección Civil"]
MOTIVOS_DESCARTE = ["Falso positivo", "Personal autorizado", "Evento ya atendido", "Otro"]


class Camara(TypedDict):
    id: str
    nombre: str
    cuadrante: str
    lat: float
    lng: float
    activa: bool


class Cuadrante(TypedDict):
    id: str
    nombre: str
    coords: list[list[float]]


class Alerta(TypedDict):
    id: str
    camara_id: str
    tipo: str
    severidad: str
    confianza: float
    timestamp: str
    cuadrante: str
    lat: float
    lng: float
    snapshot_url: str
    estado: str
    despacho: str
    folio: str
    # Campos derivados para mostrar (no forman parte del contrato).
    hora: str
    tipo_txt: str
    sev_txt: str
    confianza_txt: str


class EventoHistorico(TypedDict):
    timestamp: str
    tipo: str
    cuadrante: str
    lat: float
    lng: float


class EntradaBitacora(TypedDict):
    timestamp: str
    actor: str
    accion: str
    evento_id: str
    detalle: str
    folio: str


ALERTA_VACIA: Alerta = {
    "id": "",
    "camara_id": "",
    "tipo": "",
    "severidad": "",
    "confianza": 0.0,
    "timestamp": "",
    "cuadrante": "",
    "lat": 0.0,
    "lng": 0.0,
    "snapshot_url": "",
    "estado": "",
    "despacho": "",
    "folio": "",
    "hora": "",
    "tipo_txt": "",
    "sev_txt": "",
    "confianza_txt": "",
}


def hora_local(timestamp: str) -> str:
    """Devuelve HH:MM:SS de un timestamp ISO 8601 (o el texto tal cual si no lo es)."""
    try:
        return datetime.fromisoformat(timestamp).strftime("%H:%M:%S")
    except ValueError:
        return timestamp


def normalizar_alerta(evento: dict) -> Alerta:
    """Convierte un evento crudo del contrato en una alerta lista para la interfaz."""
    alerta: Alerta = {**ALERTA_VACIA, **{k: v for k, v in evento.items() if k in ALERTA_VACIA and v is not None}}
    alerta["estado"] = alerta["estado"] or "pendiente"
    alerta["confianza"] = float(alerta["confianza"])
    alerta["hora"] = hora_local(alerta["timestamp"])
    alerta["tipo_txt"] = TIPOS.get(alerta["tipo"], alerta["tipo"].capitalize())
    alerta["sev_txt"] = SEVERIDADES.get(alerta["severidad"], alerta["severidad"].capitalize())
    alerta["confianza_txt"] = f"{alerta['confianza']:.0%}"
    return alerta
