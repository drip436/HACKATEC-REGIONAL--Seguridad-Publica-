"""Modelo de datos interno del dashboard.

`api_client.py` traduce los DTO de la API central (BACKEND/schemas) a estas
formas. Solo viajan metadatos del evento: nada de biometría ni identidad.
"""

from datetime import datetime
from typing import TypedDict

# Vocabulario canónico del backend (BACKEND/models/enums.py).
TIPOS = {
    "traspaso_perimetro": "Traspaso de perímetro",
    "aglomeracion": "Aglomeración",
    "merodeo": "Merodeo",
    "objeto_abandonado": "Objeto abandonado",
}
# Conducta reconocida por el Edge AI: cuando viene, es lo que ve el operador.
CONDUCTAS = {
    "asalto_con_arma": "Asalto con arma",
    "intento_asalto": "Intento de asalto",
    "intento_homicidio": "Intento de homicidio",
    "agresion_fisica": "Agresión física",
    "posible_secuestro": "Posible secuestro",
    "persona_sometida": "Persona sometida a la fuerza",
    "persona_sospechosa": "Persona sospechosa",
    "vehiculo_sospechoso": "Vehículo sospechoso",
}
SEVERIDADES = {"baja": "Baja", "media": "Media", "alta": "Alta", "critica": "Crítica"}
# "validado": el operador confirmó pero aún no hay despacho con acuse.
ESTADOS = {
    "pendiente": "Pendiente",
    "validado": "Validado",
    "confirmado": "Despachado",
    "descartado": "Descartado",
}

# Etiqueta en pantalla -> valor de `Dependencia` en el backend.
DESTINOS = {
    "Seguridad de campus": "Seguridad Campus",
    "C4 Municipal": "C4 Municipal",
    "Protección Civil": "Proteccion Civil",
}
MOTIVOS_DESCARTE = ["Falso positivo", "Personal autorizado", "Evento ya atendido", "Otro"]
TODOS = "Todos"


class Camara(TypedDict):
    id: str
    nombre: str
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
    conducta: str
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
    # Campos derivados para mostrar.
    hora: str
    tipo_txt: str
    sev_txt: str
    estado_txt: str
    confianza_txt: str


class Atencion(TypedDict):
    """Unidad enviada a un evento; el mapa la anima sobre `ruta` entre inicio y llegada."""

    id: str
    evento_id: str
    unidad: str
    estado: str  # en_camino | resuelto
    ruta: list[list[float]]
    inicio_ms: int
    llegada_ms: int
    llegada_real_ms: int
    por_calles: bool
    distancia_m: float


class Unidad(TypedDict):
    """Patrulla de la flota con su posición actual (base si está libre)."""

    id: str
    base: str
    lat: float
    lng: float
    estado: str  # libre | en_camino
    evento_id: str


class Lugar(TypedDict):
    """Resultado de buscar una dirección."""

    nombre: str
    lat: float
    lng: float
    fuente: str


class ZonaRiesgo(TypedDict):
    """Círculo rojo semitransparente donde se concentran los eventos."""

    nombre: str
    lat: float
    lng: float
    radio_m: float
    eventos: int
    opacidad: float


class PuntoMapa(TypedDict):
    """Alerta en el mapa con el estado de su caso: pendiente, en_camino o resuelto."""

    id: str
    lat: float
    lng: float
    severidad: str
    tipo_txt: str
    sev_txt: str
    camara_id: str
    hora: str
    caso: str


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
    entidad: str
    detalle: str
    sello: str


ALERTA_VACIA: Alerta = {
    "id": "",
    "camara_id": "",
    "tipo": "",
    "conducta": "",
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
    "estado_txt": "",
    "confianza_txt": "",
}


def a_local(timestamp: str) -> datetime | None:
    """Convierte un timestamp ISO 8601 a hora local; None si no es válido."""
    try:
        return datetime.fromisoformat(timestamp).astimezone()
    except ValueError:
        return None


def fecha_hora_local(timestamp: str) -> str:
    momento = a_local(timestamp)
    return momento.strftime("%Y-%m-%d %H:%M:%S") if momento else timestamp


def con_derivados(alerta: Alerta) -> Alerta:
    """Recalcula los campos de presentación a partir de los del contrato."""
    momento = a_local(alerta["timestamp"])
    alerta["hora"] = momento.strftime("%H:%M:%S") if momento else alerta["timestamp"]
    alerta["tipo_txt"] = CONDUCTAS.get(alerta["conducta"]) or TIPOS.get(
        alerta["tipo"], alerta["tipo"].replace("_", " ").capitalize()
    )
    alerta["sev_txt"] = SEVERIDADES.get(alerta["severidad"], alerta["severidad"].capitalize())
    alerta["estado_txt"] = ESTADOS.get(alerta["estado"], alerta["estado"].capitalize())
    alerta["confianza_txt"] = f"{alerta['confianza']:.0%}"
    return alerta


def normalizar_alerta(evento: dict) -> Alerta:
    """Completa un evento ya traducido por `api_client` para usarlo en la interfaz."""
    alerta: Alerta = {**ALERTA_VACIA, **{k: v for k, v in evento.items() if k in ALERTA_VACIA and v is not None}}
    alerta["estado"] = alerta["estado"] or "pendiente"
    alerta["confianza"] = float(alerta["confianza"])
    return con_derivados(alerta)
