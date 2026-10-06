"""Tarjetas de indicadores calculados desde el estado."""

import reflex as rx

from ..estilos import TEXTO, TEXTO_2, TEXTO_3, tarjeta
from ..state import State


def stat_card(titulo: str, valor, pista) -> rx.Component:
    return tarjeta(
        rx.vstack(
            rx.text(titulo, color=TEXTO_3, size="2"),
            rx.heading(valor, size="7", color=TEXTO),
            rx.text(pista, color=TEXTO_2, size="2"),
            align="start",
            spacing="1",
        )
    )


def fila_kpis() -> rx.Component:
    return rx.grid(
        stat_card(
            "Alertas por validar",
            State.total_pendientes,
            rx.text.span(State.total_criticas, " críticas"),
        ),
        stat_card(
            "Despachos confirmados",
            State.total_despachadas,
            rx.text.span("Tasa de confirmación: ", State.tasa_confirmacion),
        ),
        stat_card("Cámaras activas", State.camaras_activas, "Sin reconocimiento facial"),
        stat_card("Franja crítica", State.franja_critica, "Según histórico de 30 días"),
        columns=rx.breakpoints(initial="1", sm="2", lg="4"),
        spacing="3",
        width="100%",
    )
