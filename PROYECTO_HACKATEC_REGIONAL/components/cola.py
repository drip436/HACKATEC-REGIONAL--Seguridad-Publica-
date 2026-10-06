"""Cola operativa y detalle de la alerta seleccionada."""

import reflex as rx

from ..estilos import TEXTO, TEXTO_2, TEXTO_3, insignia_estado, insignia_severidad, tarjeta, titulo
from ..state import State


def alert_item(alerta) -> rx.Component:
    elegida = alerta["id"] == State.seleccion_id
    return rx.box(
        rx.hstack(
            rx.vstack(
                rx.hstack(
                    rx.text(alerta["tipo_txt"], color=TEXTO, font_weight="700"),
                    insignia_severidad(alerta),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.text(alerta["cuadrante"], " · ", alerta["camara_id"], " · ", alerta["hora"], color=TEXTO_3, size="2"),
                align="start",
                spacing="1",
            ),
            rx.vstack(
                insignia_estado(alerta),
                rx.text(alerta["despacho"], color=TEXTO_3, size="1", text_align="right"),
                align="end",
                spacing="1",
            ),
            justify="between",
            align="center",
            width="100%",
        ),
        on_click=State.seleccionar(alerta["id"]),
        on_double_click=State.abrir_alerta(alerta["id"]),
        cursor="pointer",
        width="100%",
        padding="0.8rem 1rem",
        border_radius="14px",
        border=rx.cond(elegida, "1px solid #38bdf8", "1px solid rgba(148,163,184,0.14)"),
        background=rx.cond(elegida, "rgba(14, 116, 144, 0.18)", "rgba(15, 23, 42, 0.82)"),
    )


def cola_operativa() -> rx.Component:
    return tarjeta(
        rx.vstack(
            titulo("Cola operativa", rx.badge(State.total_pendientes, " por validar", color_scheme="amber", variant="soft")),
            rx.cond(
                State.alertas,
                rx.vstack(
                    rx.foreach(State.alertas, alert_item),
                    spacing="2",
                    width="100%",
                    max_height="420px",
                    overflow_y="auto",
                    style={"scrollbarWidth": "thin", "scrollbarColor": "#334155 transparent"},
                ),
                rx.text("Sin alertas por ahora. Las nuevas aparecerán aquí en cuanto se detecten.", color=TEXTO_3, size="2"),
            ),
            spacing="3",
            width="100%",
        )
    )


def _dato(etiqueta: str, valor) -> rx.Component:
    return rx.vstack(
        rx.text(etiqueta, color=TEXTO_3, size="1"),
        rx.text(valor, color=TEXTO, size="2", font_weight="600"),
        spacing="0",
        align="start",
    )


def datos_alerta(alerta) -> rx.Component:
    return rx.grid(
        _dato("Cámara", alerta["camara_id"]),
        _dato("Cuadrante", alerta["cuadrante"]),
        _dato("Hora", alerta["hora"]),
        _dato("Confianza", alerta["confianza_txt"]),
        columns="2",
        spacing="3",
        width="100%",
    )


def panel_seleccion() -> rx.Component:
    alerta = State.alerta_sel
    return tarjeta(
        rx.cond(
            alerta["id"] != "",
            rx.vstack(
                titulo("Alerta seleccionada", insignia_severidad(alerta)),
                rx.text(alerta["tipo_txt"], color=TEXTO, size="5", font_weight="700"),
                datos_alerta(alerta),
                rx.hstack(
                    rx.text("Estado:", color=TEXTO_2, size="2"),
                    insignia_estado(alerta),
                    rx.text(alerta["despacho"], color=TEXTO_3, size="2"),
                    align="center",
                    wrap="wrap",
                    spacing="2",
                ),
                rx.cond(alerta["folio"] != "", rx.text("Acuse: ", rx.code(alerta["folio"]), color=TEXTO_2, size="2")),
                rx.button(
                    rx.match(
                        alerta["estado"],
                        ("pendiente", "Revisar y validar"),
                        ("validado", "Despachar"),
                        "Ver detalle",
                    ),
                    on_click=State.abrir_alerta(alerta["id"]),
                    size="3",
                    width="100%",
                    cursor="pointer",
                ),
                spacing="3",
                width="100%",
                align="start",
            ),
            rx.vstack(
                titulo("Alerta seleccionada"),
                rx.text("Selecciona una alerta de la cola o del mapa.", color=TEXTO_3, size="2"),
                spacing="3",
                width="100%",
            ),
        )
    )
