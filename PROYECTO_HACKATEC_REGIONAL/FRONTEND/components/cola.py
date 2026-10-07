"""Cola operativa y detalle de la alerta seleccionada."""

import reflex as rx

from ...estilos import (
    AZUL,
    BORDE,
    COLOR_SEVERIDAD,
    LINEA,
    SUPERFICIE_2,
    TEXTO,
    TEXTO_2,
    TEXTO_3,
    insignia_estado,
    insignia_severidad,
    tarjeta,
    titulo,
)
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


def cola_operativa() -> rx.Component:
    return tarjeta(
        rx.vstack(
            titulo("Alertas", rx.text(State.total_pendientes, " por revisar", size="1", color=TEXTO_3)),
            rx.cond(
                State.alertas,
                rx.vstack(
                    rx.foreach(State.alertas, alert_item),
                    spacing="1",
                    width="100%",
                    max_height="440px",
                    overflow_y="auto",
                    style={"scrollbarWidth": "thin"},
                ),
                rx.text("Sin alertas por ahora. Las nuevas aparecerán aquí.", color=TEXTO_3, size="2"),
            ),
            spacing="3",
            width="100%",
        )
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
        _dato("Cámara", alerta["camara_id"]),
        _dato("Ubicación", rx.text.span(alerta["lat"], ", ", alerta["lng"])),
        _dato("Hora", alerta["hora"]),
        _dato("Confianza", alerta["confianza_txt"]),
        columns="2",
        spacing="3",
        width="100%",
    )


def _unidad_cercana() -> rx.Component:
    return rx.cond(
        (State.caso_sel == "pendiente") & (State.unidad_cercana_sel != ""),
        rx.hstack(
            rx.box(width="8px", height="8px", border_radius="50%", background=AZUL, flex_shrink="0"),
            rx.text("Más cercana: ", State.unidad_cercana_sel, size="1", color=TEXTO_2),
            spacing="2",
            align="center",
        ),
    )


def panel_seleccion() -> rx.Component:
    alerta = State.alerta_sel
    return tarjeta(
        rx.cond(
            alerta["id"] != "",
            rx.vstack(
                rx.hstack(
                    rx.text("Alerta seleccionada", size="1", color=TEXTO_3),
                    insignia_severidad(alerta),
                    justify="between",
                    align="center",
                    width="100%",
                ),
                rx.text(alerta["tipo_txt"], color=TEXTO, size="5", weight="medium"),
                datos_alerta(alerta),
                rx.hstack(
                    insignia_estado(alerta),
                    rx.text(alerta["despacho"], color=TEXTO_3, size="1"),
                    align="center",
                    wrap="wrap",
                    spacing="2",
                ),
                _unidad_cercana(),
                rx.cond(alerta["folio"] != "", rx.text("Acuse: ", rx.code(alerta["folio"]), color=TEXTO_2, size="1")),
                rx.button(
                    rx.match(
                        alerta["estado"],
                        ("pendiente", "Revisar"),
                        ("validado", "Despachar"),
                        "Ver detalle",
                    ),
                    on_click=State.abrir_alerta(alerta["id"]),
                    size="2",
                    width="100%",
                    cursor="pointer",
                ),
                spacing="3",
                width="100%",
                align="start",
            ),
            rx.vstack(
                rx.text("Alerta seleccionada", size="1", color=TEXTO_3),
                rx.text("Elige una alerta de la lista o un punto del mapa.", color=TEXTO_2, size="2"),
                spacing="2",
                width="100%",
            ),
        )
    )
