"""Estado de presentación del panel de operación.

Extiende `State` como subestado: solo guarda qué cámara se proyecta y deriva
vistas (mosaico CCTV, indicadores) de los datos que ya mantiene `State`. No
habla con el backend.
"""

from typing import TypedDict

import reflex as rx

from .state import SEVERIDADES_VIOLENCIA, State

TILES_MOSAICO = 10
_ORDEN_SEVERIDAD = ("critica", "alta", "media", "baja")


class Tile(TypedDict):
    """Una celda del mosaico CCTV. `id` vacío = celda sin cámara asignada."""

    id: str
    etiqueta: str
    nombre: str
    snapshot_url: str
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
    # Cámara proyectada en el reproductor principal; "" = la cámara en vivo.
    camara_sel: str = ""

    def _es_vinculada(self, camara: dict) -> bool:
        return self.cam_vinculada and (camara["id"] == "vinculada" or camara["nombre"] == self.cam_nombre)

    @rx.var
    def mosaico(self) -> list[Tile]:
        """Diez celdas: la cámara vinculada primero, luego el inventario (activas antes).
        La miniatura es la captura de evidencia más reciente de cada cámara."""
        ultima: dict[str, dict] = {}
        en_alerta: set[str] = set()
        for alerta in self.alertas:  # de la más reciente a la más antigua
            if alerta["snapshot_url"]:
                ultima.setdefault(alerta["camara_id"], alerta)
            if alerta["estado"] == "pendiente" and alerta["severidad"] in SEVERIDADES_VIOLENCIA:
                en_alerta.add(alerta["camara_id"])

        camaras = sorted(self.camaras_mapa, key=lambda c: (not self._es_vinculada(c), not c["activa"]))
        tiles: list[Tile] = []
        for posicion, camara in enumerate(camaras[:TILES_MOSAICO], start=1):
            en_vivo = self._es_vinculada(camara)
            captura = ultima.get(camara["id"])
            tiles.append(
                {
                    "id": camara["id"],
                    "etiqueta": f"CCTV-{posicion:02d}",
                    "nombre": camara["nombre"],
                    "snapshot_url": captura["snapshot_url"] if captura else "",
                    "hora": captura["hora"] if captura else "",
                    "activa": camara["activa"],
                    "en_vivo": en_vivo,
                    "en_alerta": camara["id"] in en_alerta,
                    "elegida": camara["id"] == self.camara_sel or (en_vivo and not self.camara_sel),
                }
            )
        tiles += [_tile_vacio(posicion) for posicion in range(len(tiles) + 1, TILES_MOSAICO + 1)]
        return tiles

    @rx.var
    def proyeccion(self) -> Tile:
        """Celda proyectada en el reproductor (vacía si se muestra la cámara en vivo)."""
        for tile in self.mosaico:
            if tile["id"] and tile["id"] == self.camara_sel:
                return tile
        return _tile_vacio(0)

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
    def proyectar(self, camara_id: str):
        """Proyecta una cámara del mosaico y centra el mapa en ella."""
        for camara in self.camaras_mapa:
            if camara_id and camara["id"] == camara_id:
                self.camara_sel = camara_id
                self._enfocar(camara["lat"], camara["lng"])
                return

    @rx.event
    def proyectar_vivo(self):
        self.camara_sel = ""
