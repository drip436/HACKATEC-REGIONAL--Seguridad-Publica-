"""Indicadores del turno calculados desde el estado."""

import reflex as rx

from ...estado_ui import EstadoUI
from ...estilos import ACENTO, COLOR_SEVERIDAD, TEXTO, TEXTO_3, VERDE, tarjeta
from ...state import State


def stat_card(titulo: str, valor, pista, color=TEXTO) -> rx.Component:
    return tarjeta(
        rx.vstack(
            rx.text(titulo, color=TEXTO_3, size="1", text_transform="uppercase", letter_spacing="0.06em"),
            rx.text(valor, color=color, font_size="24px", font_weight="700", line_height="1.1", style={"fontVariantNumeric": "tabular-nums"}),
            rx.text(pista, color=TEXTO_3, size="1"),
            align="start",
            spacing="1",
        ),
        padding="0.75rem 1rem",
    )


def fila_kpis() -> rx.Component:
    return rx.grid(
        stat_card(
            "Unidades disponibles",
            State.unidades_libres,
            rx.text.span("de ", State.flota.length(), " en la región"),
            color=ACENTO,
        ),
        stat_card(
            "Tiempo de respuesta",
            EstadoUI.tiempo_respuesta,
            rx.cond(
                EstadoUI.atenciones_resueltas > 0,
                rx.text.span("promedio de ", EstadoUI.atenciones_resueltas, " atenciones"),
                "sin atenciones resueltas aún",
            ),
        ),
        stat_card(
            "Severidad de amenaza",
            rx.match(
                EstadoUI.severidad_max,
                ("critica", "CRÍTICA"),
                ("alta", "ALTA"),
                ("media", "MEDIA"),
                ("baja", "BAJA"),
                "NORMAL",
            ),
            rx.text.span(State.total_criticas, " críticas por revisar"),
            color=rx.match(EstadoUI.severidad_max, *COLOR_SEVERIDAD.items(), VERDE),
        ),
        stat_card(
            "Alertas activas",
            State.total_pendientes,
            rx.text.span(State.total_despachadas, " despachadas · ", State.tasa_confirmacion),
        ),
        columns=rx.breakpoints(initial="2", lg="4"),
        spacing="3",
        width="100%",
    )
