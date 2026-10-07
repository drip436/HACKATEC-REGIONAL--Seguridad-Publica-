"""Panel de operación: cola de alertas y conteos de la cámara."""

import reflex as rx

from ...estilos import COLOR_SEVERIDAD, LINEA, PANEL_2, TEXTO, TEXTO_2, TEXTO_3, insignia_estado, tarjeta
from ...state import State
from .kpis import mosaicos_camara, mosaicos_turno


def alert_item(alerta) -> rx.Component:
    elegida = alerta["id"] == State.seleccion_id
    return rx.hstack(
        rx.box(
            width="3px",
            align_self="stretch",
            border_radius="2px",
            background=rx.match(alerta["severidad"], *COLOR_SEVERIDAD.items(), TEXTO_3),
        ),
        rx.vstack(
            rx.text(alerta["tipo_txt"], size="2", color=TEXTO, weight="medium"),
            rx.text(alerta["lugar"], " · ", alerta["hora"], size="1", color=TEXTO_3),
            spacing="0",
            align="start",
            min_width="0",
        ),
        rx.spacer(),
        insignia_estado(alerta),
        on_click=State.abrir_alerta(alerta["id"]),
        cursor="pointer",
        spacing="3",
        align="center",
        width="100%",
        padding="8px 10px",
        border_radius="6px",
        background=rx.cond(elegida, PANEL_2, "transparent"),
        _hover={"background": PANEL_2},
    )


def cola_operativa() -> rx.Component:
    return rx.cond(
        State.alertas,
        rx.vstack(
            rx.foreach(State.alertas, alert_item),
            spacing="1",
            width="100%",
            max_height="560px",
            overflow_y="auto",
            style={"scrollbarWidth": "thin", "scrollbarColor": f"{LINEA} transparent"},
        ),
        rx.center(rx.text("Sin alertas.", size="2", color=TEXTO_3), padding="28px 0", width="100%"),
    )


def _dato(etiqueta: str, valor) -> rx.Component:
    return rx.vstack(
        rx.text(etiqueta, color=TEXTO_3, size="1"),
        rx.text(valor, color=TEXTO, size="2", weight="medium"),
        spacing="0",
        align="start",
    )


def datos_alerta(alerta) -> rx.Component:
    return rx.grid(
        _dato("Lugar", alerta["lugar"]),
        _dato("Severidad", alerta["sev_txt"]),
        _dato("Hora", alerta["hora"]),
        _dato("Confianza", alerta["confianza_txt"]),
        columns="2",
        spacing="3",
        width="100%",
    )


def panel_operacion() -> rx.Component:
    return tarjeta(
        rx.vstack(
            rx.text("Operación", size="5", weight="bold", color=TEXTO),
            rx.text("Haz clic en una alerta (o en su punto del mapa) para revisarla.", size="2", color=TEXTO_2),
            rx.segmented_control.root(
                rx.segmented_control.item("Alertas", value="alertas"),
                rx.segmented_control.item("En cámara", value="camara"),
                value=State.panel_tab,
                on_change=State.set_panel_tab,
                width="100%",
                size="2",
            ),
            rx.cond(
                State.panel_tab == "camara",
                rx.vstack(
                    mosaicos_camara(),
                    rx.cond(State.edge_regla != "", rx.text(State.edge_regla, size="2", color=TEXTO_2)),
                    rx.cond(~State.edge_en_linea, rx.text("La cámara no está transmitiendo.", size="1", color=TEXTO_3)),
                    spacing="3",
                    width="100%",
                ),
                rx.vstack(
                    mosaicos_turno(),
                    rx.box(height="1px", width="100%", background=LINEA),
                    cola_operativa(),
                    spacing="3",
                    width="100%",
                ),
            ),
            spacing="3",
            width="100%",
        ),
    )
