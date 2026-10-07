"""Mapa del Tecnológico de Mérida (Leaflet) envuelto como componente Reflex."""

import reflex as rx

from ... import campus
from ...estilos import TEXTO_2, TEXTO_3, tarjeta, titulo
from ...state import State

ROJO = "#ef4444"
AZUL = "#3b82f6"
VERDE = "#22c55e"

_ruta = rx.asset("mapa_leaflet.jsx", shared=True)


class MapaLeaflet(rx.NoSSRComponent):
    """Leaflet necesita `window`, así que solo se carga en el navegador."""

    library = _ruta.importable_path
    tag = "MapaLeaflet"
    lib_dependencies: list[str] = ["leaflet@1.9.4", "leaflet.heat@0.2.0"]

    centro: rx.Var[list[float]]
    zoom: rx.Var[int]
    cuadrantes: rx.Var[list[dict]]
    camaras: rx.Var[list[dict]]
    alertas: rx.Var[list[dict]]
    rondines: rx.Var[list[dict]]
    unidades: rx.Var[list[dict]]
    patrullas: rx.Var[list[dict]]
    foco: rx.Var[list[float]]
    calor: rx.Var[list[list[float]]]
    seleccion: rx.Var[str]
    altura: rx.Var[str]

    on_alerta: rx.EventHandler[rx.event.passthrough_event_spec(str)]


def _mapa(**props) -> rx.Component:
    return MapaLeaflet.create(
        centro=State.centro,
        zoom=campus.ZOOM,
        cuadrantes=State.cuadrantes,
        camaras=State.camaras_mapa,
        rondines=State.puntos_rondin,
        **props,
    )


def _punto(color: str, borde: str = "2px solid #f8fafc", relleno: bool = True) -> rx.Component:
    return rx.box(
        width="9px",
        height="9px",
        border_radius="50%",
        background=color if relleno else "transparent",
        border=borde,
        flex_shrink="0",
    )


def _leyenda_item(marca: rx.Component, texto: str) -> rx.Component:
    return rx.hstack(marca, rx.text(texto, size="1", color=TEXTO_2), spacing="1", align="center")


def _leyenda(calor: bool = False) -> rx.Component:
    if calor:
        items = [
            _leyenda_item(
                rx.box(width="22px", height="8px", border_radius="4px", background="linear-gradient(90deg, #7f1d1d, #dc2626, #fde68a)"),
                "Concentración de alertas",
            ),
        ]
    else:
        items = [
            _leyenda_item(_punto(ROJO), "Alerta abierta"),
            _leyenda_item(_punto(VERDE), "Resuelta"),
            _leyenda_item(_punto(AZUL), "Patrulla"),
        ]
    return rx.hstack(
        *items,
        _leyenda_item(_punto(AZUL, f"2px solid {AZUL}", relleno=False), "Rondín sugerido"),
        _leyenda_item(rx.box(width="8px", height="8px", border_radius="2px", background="#d4d4d8"), "Cámara"),
        spacing="3",
        wrap="wrap",
    )


def _aviso_simulados() -> rx.Component:
    return rx.cond(
        State.hay_datos_simulados,
        rx.text("Datos de demostración", size="1", color=TEXTO_3),
    )


def mapa_en_vivo() -> rx.Component:
    return tarjeta(
        rx.vstack(
            titulo("Mapa", _aviso_simulados()),
            _mapa(
                alertas=State.puntos_mapa,
                unidades=State.unidades,
                patrullas=State.atenciones,
                foco=State.mapa_foco,
                seleccion=State.seleccion_id,
                on_alerta=State.abrir_alerta,
                altura="440px",
            ),
            _leyenda(),
            spacing="3",
            width="100%",
        ),
        padding="12px",
    )


def mapa_de_calor() -> rx.Component:
    return tarjeta(
        rx.vstack(
            titulo(
                "Mapa de calor",
                rx.hstack(
                    _aviso_simulados(),
                    rx.text(State.total_historico, " eventos en el periodo", size="1", color=TEXTO_3),
                    spacing="3",
                    align="center",
                ),
            ),
            _mapa(calor=State.puntos_calor, altura="420px"),
            _leyenda(calor=True),
            spacing="3",
            width="100%",
        ),
        padding="12px",
    )
