"""Mapa del campus (Leaflet) envuelto como componente Reflex."""

import reflex as rx

from .. import mock
from ..estilos import COLOR_SEVERIDAD, TEXTO_2, TEXTO_3, tarjeta, titulo
from ..modelos import SEVERIDADES
from ..state import State

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
    calor: rx.Var[list[list[float]]]
    seleccion: rx.Var[str]
    altura: rx.Var[str]

    on_alerta: rx.EventHandler[rx.event.passthrough_event_spec(str)]


def _mapa(**props) -> rx.Component:
    return MapaLeaflet.create(
        centro=mock.CENTRO,
        zoom=mock.ZOOM,
        cuadrantes=mock.CUADRANTES,
        camaras=State.camaras,
        **props,
    )


def _leyenda_item(marca: rx.Component, texto: str) -> rx.Component:
    return rx.hstack(marca, rx.text(texto, size="1", color=TEXTO_2), spacing="1", align="center")


def _leyenda() -> rx.Component:
    return rx.hstack(
        *[
            _leyenda_item(rx.box(width="10px", height="10px", border_radius="50%", background=COLOR_SEVERIDAD[clave]), texto)
            for clave, texto in reversed(SEVERIDADES.items())
        ],
        _leyenda_item(rx.box(width="10px", height="10px", border_radius="2px", background="#e2e8f0"), "Cámara"),
        spacing="3",
        wrap="wrap",
    )


def mapa_en_vivo() -> rx.Component:
    return tarjeta(
        rx.vstack(
            titulo("Mapa del campus y alertas en vivo"),
            _mapa(
                alertas=State.alertas_pendientes,
                seleccion=State.seleccion_id,
                on_alerta=State.abrir_alerta,
                altura="380px",
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
                "Mapa de calor histórico",
                rx.text(State.total_historico, " eventos en el periodo", size="2", color=TEXTO_3),
            ),
            _mapa(calor=State.puntos_calor, altura="420px"),
            rx.text(
                "Más claro = mayor concentración de eventos. Solo se usan ubicación, tipo y hora del evento.",
                size="1",
                color=TEXTO_3,
            ),
            spacing="3",
            width="100%",
        )
    )
