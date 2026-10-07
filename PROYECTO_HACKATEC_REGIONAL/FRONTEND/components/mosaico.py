"""Mosaico CCTV: diez celdas con la última imagen de cada cámara. Un clic la proyecta."""

import reflex as rx

from ...estado_ui import EstadoUI
from ...estilos import ACENTO, LINEA, ROJO, TEXTO, TEXTO_3, VERDE, VIDEO, tarjeta, titulo
from ...state import State


def _imagen(src, alt: str) -> rx.Component:
    return rx.image(src=src, alt=alt, width="100%", height="100%", object_fit="cover", loading="lazy")


def _celda(tile) -> rx.Component:
    """La celda de la cámara vinculada muestra su transmisión; las demás, su última captura."""
    return rx.box(
        rx.cond(
            tile["en_vivo"] & State.edge_en_linea,
            _imagen(State.url_transmision, "Miniatura en vivo de la cámara vinculada"),
            rx.cond(
                tile["snapshot_url"] != "",
                _imagen(tile["snapshot_url"], "Última captura de la cámara"),
                rx.center(
                    rx.text(
                        rx.cond(tile["activa"], "SIN CAPTURAS", "SIN SEÑAL"),
                        font_size="9px",
                        letter_spacing="0.08em",
                        color=TEXTO_3,
                    ),
                    width="100%",
                    height="100%",
                    class_name="so-sin-senal",
                ),
            ),
        ),
        rx.hstack(
            rx.box(
                width="6px",
                height="6px",
                border_radius="50%",
                flex_shrink="0",
                background=rx.cond(tile["en_alerta"], ROJO, rx.cond(tile["activa"], VERDE, TEXTO_3)),
            ),
            rx.text(tile["etiqueta"], font_size="10px", font_weight="600", color=TEXTO, white_space="nowrap"),
            rx.text(tile["nombre"], font_size="10px", color=TEXTO_3, trim="both", style={"overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
            spacing="1",
            align="center",
            position="absolute",
            left="0",
            right="0",
            bottom="0",
            padding="3px 6px",
            background="rgba(2, 6, 23, 0.78)",
        ),
        on_click=EstadoUI.proyectar(tile["id"]),
        title=tile["nombre"],
        position="relative",
        aspect_ratio="16 / 9",
        overflow="hidden",
        border_radius="6px",
        background=VIDEO,
        border=rx.cond(tile["en_alerta"], f"1.5px solid {ROJO}", rx.cond(tile["elegida"], f"1.5px solid {ACENTO}", f"1.5px solid {LINEA}")),
        cursor=rx.cond(tile["id"] != "", "pointer", "default"),
        opacity=rx.cond(tile["id"] != "", "1", "0.55"),
        class_name=rx.cond(tile["en_alerta"], "so-tile-alerta", ""),
        _hover={"border_color": ACENTO},
    )


def mosaico_cctv() -> rx.Component:
    return tarjeta(
        rx.vstack(
            titulo("Cámaras", rx.text(State.camaras_activas, " activas", size="1", color=TEXTO_3)),
            rx.grid(
                rx.foreach(EstadoUI.mosaico, _celda),
                columns=rx.breakpoints(initial="2", sm="5"),
                spacing="2",
                width="100%",
            ),
            spacing="3",
            width="100%",
        )
    )
