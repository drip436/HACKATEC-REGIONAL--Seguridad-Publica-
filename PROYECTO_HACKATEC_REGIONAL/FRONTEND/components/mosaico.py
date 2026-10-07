"""Mosaico CCTV de las cámaras reales (un clic proyecta la cámara) y, aparte, los videos de demostración."""

import reflex as rx

from ...estado_ui import EstadoUI
from ...estilos import ACENTO, LINEA, ROJO, SOBRE_VIDEO, SOBRE_VIDEO_2, TEXTO_3, VELO, VIDEO, tarjeta, titulo
from ...state import State


def _imagen(src, alt: str) -> rx.Component:
    return rx.image(src=src, alt=alt, width="100%", height="100%", object_fit="cover", loading="lazy")


def _sin_video(tile) -> rx.Component:
    return rx.cond(
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
    )


def video_en_bucle(src, **props) -> rx.Component:
    """Video de demostración: se reproduce solo, sin sonido y en bucle, como un monitor CCTV."""
    return rx.el.video(src=src, auto_play=True, loop=True, muted=True, plays_inline=True, preload="auto", width="100%", height="100%", **props)


def _celda(tile) -> rx.Component:
    """La celda de la cámara vinculada muestra su transmisión; las demás, su última captura."""
    return rx.box(
        rx.cond(
            tile["en_vivo"] & State.edge_en_linea,
            _imagen(State.url_transmision, "Miniatura en vivo de la cámara vinculada"),
            _sin_video(tile),
        ),
        rx.hstack(
            rx.box(
                width="6px",
                height="6px",
                border_radius="50%",
                flex_shrink="0",
                background=rx.cond(tile["en_alerta"], ROJO, rx.cond(tile["activa"], "#4ade80", SOBRE_VIDEO_2)),
            ),
            rx.text(tile["etiqueta"], font_size="10px", font_weight="600", color=SOBRE_VIDEO, white_space="nowrap"),
            rx.text(tile["nombre"], font_size="10px", color=SOBRE_VIDEO_2, trim="both", style={"overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
            spacing="1",
            align="center",
            position="absolute",
            left="0",
            right="0",
            bottom="0",
            padding="3px 6px",
            background=VELO,
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


def _celda_demo(camara) -> rx.Component:
    return rx.box(
        video_en_bucle(camara["video_url"], style={"objectFit": "cover"}),
        rx.hstack(
            rx.icon("map-pin", size=12, color=SOBRE_VIDEO_2, flex_shrink="0"),
            rx.text(camara["nombre"], font_size="12px", font_weight="600", color=SOBRE_VIDEO, style={"overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"}),
            spacing="1",
            align="center",
            position="absolute",
            left="0",
            right="0",
            bottom="0",
            padding="4px 8px",
            background=VELO,
        ),
        on_click=EstadoUI.ubicar_demo(camara["id"]),
        title="Ver en el mapa",
        position="relative",
        aspect_ratio="16 / 9",
        overflow="hidden",
        border_radius="8px",
        background=VIDEO,
        border=f"1.5px solid {LINEA}",
        cursor="pointer",
        _hover={"border_color": ACENTO},
    )


def videos_demostracion() -> rx.Component:
    """Videos grabados y ya anotados por el Edge AI, separados de las cámaras reales.
    La sección no se muestra si no hay ninguno publicado."""
    return rx.cond(
        EstadoUI.camaras_demo,
        tarjeta(
            rx.vstack(
                titulo(
                    "Videos de demostración",
                    rx.text("Grabados y analizados por la IA; no generan alertas", size="1", color=TEXTO_3),
                ),
                rx.grid(
                    rx.foreach(EstadoUI.camaras_demo, _celda_demo),
                    columns=rx.breakpoints(initial="1", sm="2", lg="4"),
                    spacing="3",
                    width="100%",
                ),
                spacing="3",
                width="100%",
            )
        ),
    )
