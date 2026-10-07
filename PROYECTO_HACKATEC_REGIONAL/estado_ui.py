"""Estado de presentación del panel de operación.

Extiende `State` como subestado: solo guarda qué cámara se proyecta y deriva
vistas (mosaico CCTV, indicadores) de los datos que ya mantiene `State`. No
habla con el backend.
"""

from typing import TypedDict

import reflex as rx

from . import api_client
from .modelos import Camara
from .state import SEVERIDADES_VIOLENCIA, State

TILES_MOSAICO = 10
_ORDEN_SEVERIDAD = ("critica", "alta", "media", "baja")


class CamaraDemo(TypedDict):
    """Cámara de demostración: un video grabado que el Edge AI ya anotó."""

    id: str
    nombre: str
    lat: float
    lng: float
    video_url: str


class Tile(TypedDict):
    """Una celda del mosaico CCTV. `id` vacío = celda sin cámara asignada."""

    id: str
    etiqueta: str
    nombre: str
    snapshot_url: str
    # Video de demostración ya anotado por el Edge AI; "" si la cámara no tiene.
    video_url: str
    hora: str
    activa: bool
    en_vivo: bool
    en_alerta: bool
    elegida: bool


def _tile_vacio(posicion: int) -> Tile:
    return {
        "id": "",
        "etiqueta": f"CCTV-{posicion:02d}",
        "nombre": "Sin cámara",
        "snapshot_url": "",
        "video_url": "",
        "hora": "",
        "activa": False,
        "en_vivo": False,
        "en_alerta": False,
        "elegida": False,
    }


def _duracion(segundos: float) -> str:
    minutos, resto = divmod(round(segundos), 60)
    return f"{minutos}m {resto:02d}s" if minutos else f"{resto}s"


class EstadoUI(State):
    # Cámara proyectada en el reproductor principal; "" = la cámara en vivo (o el primer video).
    camara_sel: str = ""
    camaras_demo: list[CamaraDemo] = []

    def _es_vinculada(self, camara: dict) -> bool:
        return self.cam_vinculada and (camara["id"] == "vinculada" or camara["nombre"] == self.cam_nombre)

    def _camaras_panel(self) -> list[dict]:
        """Inventario + cámara vinculada + cámaras de demostración que no están en el inventario."""
        conocidas = {c["id"] for c in self.camaras_mapa}
        extra = [
            {"id": c["id"], "nombre": c["nombre"], "lat": c["lat"], "lng": c["lng"], "activa": True}
            for c in self.camaras_demo
            if c["id"] not in conocidas
        ]
        return [*self.camaras_mapa, *extra]

    @rx.var
    def camaras_panel(self) -> list[Camara]:
        """Cámaras que dibuja el mapa en vivo."""
        return self._camaras_panel()

    @rx.var
    def mosaico(self) -> list[Tile]:
        """Diez celdas: la cámara vinculada primero, luego las que tienen video de
        demostración y después el inventario (activas antes). Sin video, la miniatura
        es la captura de evidencia más reciente de la cámara."""
        ultima: dict[str, dict] = {}
        en_alerta: set[str] = set()
        for alerta in self.alertas:  # de la más reciente a la más antigua
            if alerta["snapshot_url"]:
                ultima.setdefault(alerta["camara_id"], alerta)
            if alerta["estado"] == "pendiente" and alerta["severidad"] in SEVERIDADES_VIOLENCIA:
                en_alerta.add(alerta["camara_id"])
        videos = {c["id"]: c["video_url"] for c in self.camaras_demo}

        camaras = sorted(
            self._camaras_panel(),
            key=lambda c: (not self._es_vinculada(c), c["id"] not in videos, not c["activa"]),
        )
        tiles: list[Tile] = []
        for posicion, camara in enumerate(camaras[:TILES_MOSAICO], start=1):
            captura = ultima.get(camara["id"])
            tiles.append(
                {
                    "id": camara["id"],
                    "etiqueta": f"CCTV-{posicion:02d}",
                    "nombre": camara["nombre"],
                    "snapshot_url": captura["snapshot_url"] if captura else "",
                    "video_url": videos.get(camara["id"], ""),
                    "hora": captura["hora"] if captura else "",
                    "activa": camara["activa"],
                    "en_vivo": self._es_vinculada(camara),
                    "en_alerta": camara["id"] in en_alerta,
                    "elegida": False,
                }
            )
        # Proyectada: la que eligió el operador; si no, la cámara en vivo; si tampoco hay,
        # el primer video de demostración (el reproductor no se queda vacío en la demo).
        elegida = next((t for t in tiles if t["id"] == self.camara_sel), None) if self.camara_sel else None
        elegida = elegida or next((t for t in tiles if t["en_vivo"]), None) or next((t for t in tiles if t["video_url"]), None)
        if elegida:
            elegida["elegida"] = True
        tiles += [_tile_vacio(posicion) for posicion in range(len(tiles) + 1, TILES_MOSAICO + 1)]
        return tiles

    @rx.var
    def proyeccion(self) -> Tile:
        """Celda proyectada en el reproductor (vacía si no hay ninguna cámara que mostrar)."""
        return next((tile for tile in self.mosaico if tile["elegida"]), _tile_vacio(0))

    @rx.var
    def proyecta_vivo(self) -> bool:
        """El reproductor muestra el video en vivo salvo que se elija otra cámara."""
        tile = self.proyeccion
        return not tile["id"] or tile["en_vivo"]

    @rx.var
    def lugar_sel(self) -> str:
        """Lugar de la alerta seleccionada: el nombre de su cámara (la alerta no trae dirección)."""
        alerta = self.alerta_sel
        for camara in self.camaras_mapa:
            if camara["id"] == alerta["camara_id"]:
                return camara["nombre"]
        return alerta["cuadrante"]

    @rx.var
    def tiempo_respuesta(self) -> str:
        """Promedio entre el despacho de la unidad y su llegada, en las atenciones resueltas."""
        tiempos = [
            (a["llegada_real_ms"] - a["inicio_ms"]) / 1000
            for a in self.atenciones
            if a["estado"] == "resuelto" and a["llegada_real_ms"] > a["inicio_ms"]
        ]
        return _duracion(sum(tiempos) / len(tiempos)) if tiempos else "—"

    @rx.var
    def atenciones_resueltas(self) -> int:
        return sum(a["estado"] == "resuelto" for a in self.atenciones)

    @rx.var
    def severidad_max(self) -> str:
        """Mayor severidad entre las alertas por revisar; "" si no hay ninguna."""
        presentes = {a["severidad"] for a in self.alertas_pendientes}
        return next((s for s in _ORDEN_SEVERIDAD if s in presentes), "")

    @rx.event
    async def cargar_camaras_demo(self):
        """Videos de demostración publicados en el backend (ninguno si la API no responde)."""
        try:
            self.camaras_demo = await api_client.obtener_camaras_demo()
        except api_client.ErrorAPI:
            self.camaras_demo = []

    @rx.event
    def proyectar(self, camara_id: str):
        """Proyecta una cámara del mosaico y centra el mapa en ella."""
        for camara in self._camaras_panel():
            if camara_id and camara["id"] == camara_id:
                self.camara_sel = camara_id
                self._enfocar(camara["lat"], camara["lng"])
                return

    @rx.event
    def proyectar_vivo(self):
        self.camara_sel = ""
