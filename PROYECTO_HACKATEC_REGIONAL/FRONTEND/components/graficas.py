"""Analítica: franjas horarias críticas y priorización de rondines."""

import reflex as rx

from ...estilos import ACENTO, TEXTO, TEXTO_2, TEXTO_3, tarjeta, titulo
from ...modelos import TIPOS, TODOS
from ...state import State

_REJILLA = "rgba(148, 163, 184, 0.18)"


def filtros() -> rx.Component:
    return rx.flex(
        rx.hstack(
            rx.text("Tipo", size="2", color=TEXTO_2),
            rx.select([TODOS, *TIPOS.values()], value=State.filtro_tipo, on_change=State.set_filtro_tipo),
            align="center",
            spacing="2",
            wrap="wrap",
            max_width="100%",
        ),
        rx.hstack(
            rx.text("Periodo", size="2", color=TEXTO_2),
            rx.segmented_control.root(
                rx.segmented_control.item("7 días", value="7"),
                rx.segmented_control.item("14 días", value="14"),
                rx.segmented_control.item("30 días", value="30"),
                value=State.filtro_dias,
                on_change=State.set_filtro_dias,
            ),
            align="center",
            spacing="2",
            wrap="wrap",
            max_width="100%",
        ),
        gap="1rem",
        wrap="wrap",
        width="100%",
    )


def eventos_por_hora() -> rx.Component:
    return tarjeta(
        rx.vstack(
            titulo("Eventos por hora del día", rx.text("Franja crítica: ", State.franja_critica, size="2", color=TEXTO_2)),
            rx.recharts.bar_chart(
                rx.recharts.cartesian_grid(vertical=False, stroke=_REJILLA),
                rx.recharts.bar(data_key="eventos", name="Eventos", fill=ACENTO, radius=[4, 4, 0, 0], max_bar_size=24),
                rx.recharts.x_axis(data_key="hora", stroke=TEXTO_3, tick_line=False, axis_line=False),
                rx.recharts.y_axis(stroke=TEXTO_3, tick_line=False, axis_line=False, allow_decimals=False, width=32),
                rx.recharts.graphing_tooltip(
                    cursor={"fill": "rgba(148, 163, 184, 0.12)"},
                    content_style={"background": "#0f172a", "border": "1px solid #334155", "borderRadius": "8px"},
                    label_style={"color": TEXTO},
                    item_style={"color": TEXTO_2},
                ),
                data=State.eventos_por_hora,
                width="100%",
                height=260,
            ),
            spacing="3",
            width="100%",
        )
    )


def _celda(celda) -> rx.Component:
    return rx.tooltip(
        rx.center(
            rx.text(celda["eventos"], size="1", color=TEXTO, font_weight="600"),
            background=celda["color"],
            border_radius="4px",
            height="30px",
        ),
        content=rx.Var.create("") + celda["franja"] + ": " + celda["eventos"].to_string() + " eventos",
    )


def _fila(fila) -> rx.Component:
    return rx.fragment(
        rx.center(rx.text(fila["dia"], size="1", color=TEXTO_2), justify="start"),
        rx.foreach(fila["celdas"], _celda),
    )


def matriz_semanal() -> rx.Component:
    columnas = "2.2rem repeat(8, minmax(0, 1fr))"
    return tarjeta(
        rx.vstack(
            titulo("Día de la semana × franja horaria"),
            rx.box(
                rx.grid(
                    rx.box(),
                    *[rx.center(rx.text(f"{h:02d}h", size="1", color=TEXTO_3)) for h in range(0, 24, 3)],
                    rx.foreach(State.matriz_dia_franja, _fila),
                    grid_template_columns=columnas,
                    gap="2px",
                ),
                width="100%",
            ),
            rx.text("Cada columna inicia una franja de 3 horas. Más intenso = más eventos.", size="1", color=TEXTO_3),
            spacing="3",
            width="100%",
        )
    )


def _rondin(rondin, indice) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text((indice + 1).to_string(), ". ", rondin["cuadrante"], " · ", rondin["franja"], size="2", color=TEXTO, font_weight="600"),
            rx.text(rondin["eventos"], " eventos", size="1", color=TEXTO_3),
            justify="between",
            width="100%",
        ),
        rx.box(
            rx.box(width=rondin["ancho"], height="6px", background=ACENTO, border_radius="4px"),
            width="100%",
            background=_REJILLA,
            border_radius="4px",
        ),
        spacing="1",
        width="100%",
    )


def rondines_sugeridos() -> rx.Component:
    return tarjeta(
        rx.vstack(
            titulo("Rondines preventivos sugeridos"),
            rx.foreach(State.rondines, _rondin),
            rx.text(
                "Priorización basada en histórico: frecuencia por lugar y franja, con mayor peso a lo reciente. "
                "Es un apoyo para planear; la asignación la decide el personal.",
                size="1",
                color=TEXTO_3,
            ),
            spacing="3",
            width="100%",
        )
    )
