"""Fila de una alerta en la cola del panel lateral."""

import reflex as rx

from ...estilos import BORDE, COLOR_SEVERIDAD, LINEA, SUPERFICIE_2, TEXTO, TEXTO_3, insignia_estado, insignia_severidad
from ...state import State


def alert_item(alerta) -> rx.Component:
    elegida = alerta["id"] == State.seleccion_id
    return rx.hstack(
        rx.box(
            width="3px",
            align_self="stretch",
            border_radius="2px",
            background=rx.match(alerta["severidad"], *COLOR_SEVERIDAD.items(), LINEA),
            flex_shrink="0",
        ),
        rx.vstack(
            rx.text(alerta["tipo_txt"], color=TEXTO, size="2", weight="medium"),
            rx.text(alerta["camara_id"], " · ", alerta["hora"], color=TEXTO_3, size="1"),
            align="start",
            spacing="1",
            flex="1",
            min_width="0",
        ),
        rx.vstack(
            insignia_estado(alerta),
            insignia_severidad(alerta),
            align="end",
            spacing="1",
        ),
        on_click=State.seleccionar(alerta["id"]),
        on_double_click=State.abrir_alerta(alerta["id"]),
        cursor="pointer",
        width="100%",
        spacing="3",
        align="center",
        padding="0.625rem 0.75rem",
        border_radius="8px",
        background=rx.cond(elegida, SUPERFICIE_2, "transparent"),
        border=rx.cond(elegida, BORDE, "1px solid transparent"),
        _hover={"background": SUPERFICIE_2},
    )
