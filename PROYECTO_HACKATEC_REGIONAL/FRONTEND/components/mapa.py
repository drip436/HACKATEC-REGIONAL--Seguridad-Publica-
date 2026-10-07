"""Mapa de la región Sur-Sureste con Leaflet, envuelto como componente Reflex."""

import os

import reflex as rx

from ... import campus
from ...estilos import ACENTO, AZUL, FONDO, ROJO, TEXTO_2, TEXTO_3, VERDE, tarjeta, titulo
from ...state import State

_ruta = rx.asset("mapa_leaflet.jsx", shared=True)
# El mapa en vivo ocupa el alto libre de la ventana (encabezado, tarjeta e indicadores aparte).
ALTURA_MAPA_VIVO = "clamp(340px, calc(100vh - 345px), 760px)"


class MapaLeaflet(rx.NoSSRComponent):
    """Leaflet necesita `window`, así que solo se carga en el navegador."""

    library = _ruta.importable_path
    tag = "MapaLeaflet"
    lib_dependencies: list[str] = ["leaflet@1.9.4", "leaflet.heat@0.2.0"]

    centro: rx.Var[list[float]]
    zoom: rx.Var[int]
    camaras: rx.Var[list[dict]]
    alertas: rx.Var[list[dict]]
    unidades: rx.Var[list[dict]]
    zonas: rx.Var[list[dict]]
    rondines: rx.Var[list[dict]]
    patrullas: rx.Var[list[dict]]
    encuadre: rx.Var[list[list[float]]]
    foco: rx.Var[list[float]]
    calor: rx.Var[list[list[float]]]
    seleccion: rx.Var[str]
    marcador: rx.Var[list[float]]
    altura: rx.Var[str]

    on_alerta: rx.EventHandler[rx.event.passthrough_event_spec(str)]
    on_clic_mapa: rx.EventHandler[rx.event.passthrough_event_spec(float, float)]


class MapaGoogle(MapaLeaflet):
    """Google Maps (Maps JavaScript API) con las mismas props; si la llave falla,
    el propio componente cae a MapaLeaflet en el navegador."""

    tag = "MapaGoogle"

    clave: rx.Var[str]


# La llave del navegador queda visible en la página (así funciona Maps JavaScript API):
# restríngela por "sitio web" en Google Cloud. Puede ser otra distinta a la del backend.
_CLAVE_NAVEGADOR = (os.getenv("GOOGLE_MAPS_BROWSER_KEY") or os.getenv("GOOGLE_MAPS_API_KEY") or "").strip()


def _componente(**props) -> rx.Component:
    if _CLAVE_NAVEGADOR:
        return MapaGoogle.create(clave=_CLAVE_NAVEGADOR, **props)
    return MapaLeaflet.create(**props)


def _mapa(**props) -> rx.Component:
    return _componente(
        centro=campus.CENTRO_REGION,
        zoom=campus.ZOOM_REGION,
        camaras=State.camaras_mapa,
        encuadre=State.encuadre,
        **props,
    )


def _punto(color: str, borde: str = "2px solid #fff", radio: str = "50%", lado: str = "10px") -> rx.Component:
    return rx.box(
        width=lado,
        height=lado,
        border_radius=radio,
        background=color,
        border=borde,
                flex_shrink="0",
    )


def _leyenda_item(marca: rx.Component, texto: str) -> rx.Component:
    return rx.hstack(marca, rx.text(texto, size="1", color=TEXTO_2), spacing="2", align="center")


def _zona() -> rx.Component:
    return rx.box(
        width="14px", height="14px", border_radius="50%", background="rgba(220,38,38,.3)", border="1px solid rgba(220,38,38,.5)"
    )


def _leyenda(calor: bool = False) -> rx.Component:
    if calor:
        items = [
            _leyenda_item(
                rx.box(width="24px", height="8px", border_radius="4px", background="linear-gradient(90deg, #fecaca, #dc2626, #7f1d1d)"),
                "Concentración de eventos",
            ),
            _leyenda_item(_punto(FONDO, borde=f"2.5px solid {ACENTO}"), "Rondín sugerido"),
        ]
    else:
        items = [
            _leyenda_item(_punto(ROJO), "Incidente abierto"),
            _leyenda_item(_punto(VERDE), "Resuelto"),
            _leyenda_item(_punto(AZUL), "Patrulla"),
            _leyenda_item(_zona(), "Zona de riesgo"),
        ]
    return rx.hstack(
        *items,
        _leyenda_item(_punto(TEXTO_2, borde=f"1.5px solid {FONDO}", radio="2px", lado="9px"), "Cámara"),
        spacing="4",
        wrap="wrap",
    )


def _aviso_simulados() -> rx.Component:
    return rx.cond(
        State.hay_datos_simulados,
        rx.text("Incluye datos de demostración", size="1", color=TEXTO_3),
    )


def mapa_en_vivo() -> rx.Component:
    return tarjeta(
        rx.vstack(
            titulo(
                "Mapa GIS de la región",
                rx.hstack(
                    _aviso_simulados(),
                    rx.text(State.unidades_libres, " patrullas libres", size="1", color=TEXTO_3),
                    spacing="3",
                    align="center",
                    wrap="wrap",
                ),
            ),
            _mapa(
                alertas=State.puntos_mapa,
                unidades=State.unidades,
                zonas=State.zonas_riesgo,
                patrullas=State.atenciones,
                foco=State.mapa_foco,
                seleccion=State.seleccion_id,
                on_alerta=State.abrir_alerta,
                altura=ALTURA_MAPA_VIVO,
            ),
            _leyenda(),
            spacing="3",
            width="100%",
        )
    )


def mapa_de_calor() -> rx.Component:
    return tarjeta(
        rx.vstack(
            titulo(
                "Dónde se concentran los eventos",
                rx.hstack(
                    _aviso_simulados(),
                    rx.text(State.total_historico, " eventos en el periodo", size="1", color=TEXTO_3),
                    spacing="3",
                    align="center",
                    wrap="wrap",
                    max_width="100%",
                ),
            ),
            _mapa(calor=State.puntos_calor, rondines=State.puntos_rondin, altura="420px"),
            _leyenda(calor=True),
            rx.text(
                "Más oscuro = más eventos. Solo se usan ubicación, tipo y hora del evento.",
                size="1",
                color=TEXTO_3,
            ),
            spacing="3",
            width="100%",
        )
    )


def mapa_elegir_punto() -> rx.Component:
    """Mini mapa del diálogo de vinculación: un clic fija la ubicación exacta de la cámara."""
    return _componente(
        centro=campus.CENTRO_REGION,
        zoom=campus.ZOOM_REGION,
        unidades=[],
        marcador=State.marcador_form,
        on_clic_mapa=State.marcar_en_mapa,
        altura="220px",
    )
