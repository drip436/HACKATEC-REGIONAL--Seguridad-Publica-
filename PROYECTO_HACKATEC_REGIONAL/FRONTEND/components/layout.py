"""Barra lateral, pestañas superiores y contenedor común de las páginas."""

import reflex as rx

from ...estilos import FONDO, LINEA, PANEL_2, TEXTO, TEXTO_2, TEXTO_3
from ...state import State
from .camara import dialogo_vincular
from .modal_validacion import modal_validacion

PAGINAS = [("Operación", "/", "cctv"), ("Analítica", "/analitica", "chart-column"), ("Auditoría", "/auditoria", "scroll-text")]


def _icono_lateral(texto: str, ruta: str, icono: str, activa: str) -> rx.Component:
    actual = ruta == activa
    return rx.tooltip(
        rx.link(
            rx.center(
                rx.icon(icono, size=20, color=TEXTO if actual else TEXTO_3),
                width="38px",
                height="38px",
                border_radius="8px",
                background=PANEL_2 if actual else "transparent",
                _hover={"background": PANEL_2},
            ),
            href=ruta,
            aria_label=texto,
        ),
        content=texto,
        side="right",
    )


def _barra_lateral(activa: str) -> rx.Component:
    return rx.vstack(
        rx.center(rx.icon("shield-half", size=24, color=TEXTO), height="38px", margin_bottom="12px"),
        *[_icono_lateral(texto, ruta, icono, activa) for texto, ruta, icono in PAGINAS],
        spacing="2",
        align="center",
        padding="12px 8px",
        width="56px",
        min_width="56px",
        border_right=f"1px solid {LINEA}",
        display=rx.breakpoints(initial="none", md="flex"),
        position="sticky",
        top="0",
        height="100vh",
    )


def _pestana(texto: str, ruta: str, activa: str) -> rx.Component:
    actual = ruta == activa
    return rx.link(
        texto,
        href=ruta,
        underline="none",
        size="2",
        color=TEXTO if actual else TEXTO_2,
        weight="medium",
        padding="6px 12px",
        border_radius="6px",
        background=PANEL_2 if actual else "transparent",
        aria_current="page" if actual else "false",
        _hover={"color": TEXTO},
    )


def _estado_conexion() -> rx.Component:
    conectado = State.conexion == "Conectado"
    return rx.hstack(
        rx.box(width="7px", height="7px", border_radius="50%", background=rx.cond(conectado, "#3fa266", "#e8b931")),
        rx.text(rx.cond(conectado, "En línea", State.conexion), size="1", color=TEXTO_2),
        spacing="2",
        align="center",
    )


def _barra_superior(activa: str) -> rx.Component:
    return rx.flex(
        rx.hstack(
            rx.text("SentinelOps", size="2", weight="bold", color=TEXTO, margin_right="10px"),
            *[_pestana(texto, ruta, activa) for texto, ruta, _ in PAGINAS],
            spacing="1",
            align="center",
            wrap="wrap",
        ),
        rx.hstack(
            _estado_conexion(),
            rx.text(State.operador, size="1", color=TEXTO_3),
            rx.button(
                rx.icon("video", size=16),
                rx.cond(State.cam_vinculada, State.cam_nombre, "Vincular cámara"),
                on_click=State.abrir_dialogo_camara,
                size="2",
            ),
            spacing="4",
            align="center",
        ),
        justify="between",
        align="center",
        wrap="wrap",
        gap="10px",
        width="100%",
        padding="10px 0 14px",
    )


def pagina(activa: str, *contenido: rx.Component) -> rx.Component:
    return rx.flex(
        _barra_lateral(activa),
        rx.box(
            rx.vstack(
                _barra_superior(activa),
                *contenido,
                rx.cond(
                    State.modo_simulado,
                    rx.text("Modo simulado: datos de ejemplo, sin backend.", size="1", color=TEXTO_3),
                ),
                spacing="3",
                width="100%",
                max_width="1600px",
                margin="0 auto",
            ),
            modal_validacion(),
            dialogo_vincular(),
            flex="1",
            min_width="0",
            padding="4px 16px 32px",
        ),
        min_height="100vh",
        background=FONDO,
    )
