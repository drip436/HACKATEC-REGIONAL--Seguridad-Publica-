"""Mapa de Mérida, Yucatán (Leaflet) envuelto como componente Reflex."""

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


def _leyenda_item(marca: rx.Component, texto: str) -> rx.Component:
    return rx.hstack(marca, rx.text(texto, size="1", color=TEXTO_2), spacing="1", align="center")


def _leyenda(calor: bool = False) -> rx.Component:
    rojo = (
        _leyenda_item(
            rx.box(width="22px", height="8px", border_radius="4px", background="linear-gradient(90deg, #7f1d1d, #dc2626, #fde68a)"),
            "Concentración de alertas",
        )
        if calor
        else _leyenda_item(
            rx.box(width="10px", height="10px", border_radius="50%", background=ROJO), "Alerta de inseguridad (más grande = más grave)"
        )
    )
    en_vivo = (
        []
        if calor
        else [
            _leyenda_item(rx.box(width="10px", height="10px", border_radius="50%", background=AZUL, border="2px solid #f8fafc"), "Patrulla"),
            _leyenda_item(rx.box(width="10px", height="10px", border_radius="50%", background=VERDE), "Caso resuelto"),
        ]
    )
    return rx.hstack(
        rojo,
        *en_vivo,
        _leyenda_item(rx.box(width="10px", height="10px", border_radius="50%", border=f"2px solid {AZUL}"), "Rondín sugerido"),
        _leyenda_item(rx.box(width="10px", height="10px", border_radius="2px", background="#e2e8f0"), "Cámara"),
        spacing="3",
        wrap="wrap",
    )


def _aviso_simulados() -> rx.Component:
    return rx.cond(
        State.hay_datos_simulados,
        rx.badge("Datos simulados: no son cifras oficiales de incidencia", color_scheme="amber", variant="soft"),
    )


def mapa_en_vivo() -> rx.Component:
    return tarjeta(
        rx.vstack(
            titulo("Mérida, Yucatán · alertas en vivo", _aviso_simulados()),
            _mapa(
                alertas=State.puntos_mapa,
                patrullas=State.atenciones,
                foco=State.mapa_foco,
                seleccion=State.seleccion_id,
                on_alerta=State.abrir_alerta,
                altura="460px",
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
                "Mérida, Yucatán · mapa de calor",
                rx.hstack(
                    _aviso_simulados(),
                    rx.text(State.total_historico, " eventos en el periodo", size="2", color=TEXTO_3),
                    spacing="3",
                    align="center",
                ),
            ),
            _mapa(calor=State.puntos_calor, altura="420px"),
            _leyenda(calor=True),
            rx.text(
                "Más claro = más alertas en esa zona. Solo se usan ubicación, tipo y hora del evento.",
                size="1",
                color=TEXTO_3,
            ),
            spacing="3",
            width="100%",
        )
    )
