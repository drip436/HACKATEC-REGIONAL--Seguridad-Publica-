"""Indicadores del turno calculados desde el estado."""

import reflex as rx

from ...estilos import TEXTO, TEXTO_3, tarjeta
from ...state import State


def stat_card(titulo: str, valor, pista) -> rx.Component:
    return tarjeta(
        rx.vstack(
            rx.text(titulo, color=TEXTO_3, size="2"),
            rx.text(valor, color=TEXTO, font_size="28px", font_weight="600", line_height="1.1"),
            rx.text(pista, color=TEXTO_3, size="1"),
            align="start",
            spacing="2",
        ),
        padding="1rem 1.25rem",
    )


def fila_kpis() -> rx.Component:
    return rx.grid(
        stat_card(
            "Por revisar",
            State.total_pendientes,
            rx.text.span(State.total_criticas, " críticas"),
        ),
        stat_card(
            "Despachadas",
            State.total_despachadas,
            rx.text.span("Confirmación: ", State.tasa_confirmacion),
        ),
        stat_card("Patrullas libres", State.unidades_libres, rx.text.span("de ", State.flota.length(), " en la región")),
        stat_card("Cámaras activas", State.camaras_activas, "Sin reconocimiento facial"),
        columns=rx.breakpoints(initial="2", lg="4"),
        spacing="4",
        width="100%",
    )
