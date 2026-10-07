"""Encabezado, navegación y contenedor común de las páginas."""

import reflex as rx

from ...estilos import ACENTO, BORDE, FONDO, SUPERFICIE, TEXTO, TEXTO_2, TEXTO_3, VERDE
from ...state import State
from .modal_validacion import modal_validacion

PAGINAS = [("Operación", "/"), ("Analítica", "/analitica"), ("Auditoría", "/auditoria")]


def _enlace(texto: str, ruta: str, activa: str) -> rx.Component:
    actual = ruta == activa
    return rx.link(
        texto,
        href=ruta,
        underline="none",
        color=TEXTO if actual else TEXTO_3,
        font_weight="500",
        font_size="14px",
        padding="0.9rem 0.25rem",
        border_bottom=f"2px solid {ACENTO}" if actual else "2px solid transparent",
        aria_current="page" if actual else "false",
        _hover={"color": TEXTO},
    )


def _estado_conexion() -> rx.Component:
    conectado = State.conexion == "Conectado"
    return rx.hstack(
        rx.box(width="8px", height="8px", border_radius="50%", background=rx.cond(conectado, VERDE, "#d97706")),
        rx.text(State.conexion, size="1", color=TEXTO_2),
        spacing="2",
        align="center",
    )


def _encabezado(activa: str) -> rx.Component:
    return rx.box(
        rx.flex(
            rx.hstack(
                rx.center(
                    rx.icon("shield", size=16, color="#fff"),
                    width="28px",
                    height="28px",
                    border_radius="7px",
                    background=ACENTO,
                ),
                rx.vstack(
                    rx.text("SentinelOps", size="3", weight="bold", color=TEXTO, line_height="1.1"),
                    rx.text("Monitoreo de seguridad · Región Sur-Sureste", size="1", color=TEXTO_3, line_height="1.1"),
                    spacing="0",
                    align="start",
                ),
                spacing="3",
                align="center",
            ),
            rx.hstack(*[_enlace(texto, ruta, activa) for texto, ruta in PAGINAS], spacing="5", as_="nav"),
            rx.hstack(
                _estado_conexion(),
                rx.box(width="1px", height="16px", background="#e5e7eb"),
                rx.hstack(rx.icon("user-round", size=14, color=TEXTO_3), rx.text(State.operador, size="1", color=TEXTO_2), spacing="1", align="center"),
                spacing="3",
                align="center",
            ),
            justify="between",
            align="center",
            wrap="wrap",
            gap="0 1.5rem",
            max_width="1360px",
            margin="0 auto",
            padding_x="1.5rem",
        ),
        width="100%",
        background=SUPERFICIE,
        border_bottom=BORDE,
        position="sticky",
        top="0",
        z_index="10",
    )


def pagina(activa: str, *contenido: rx.Component) -> rx.Component:
    return rx.box(
        _encabezado(activa),
        rx.vstack(
            *contenido,
            rx.cond(
                State.modo_simulado,
                rx.text("Modo simulado: las alertas y el histórico son datos sintéticos.", size="1", color=TEXTO_3),
            ),
            spacing="5",
            width="100%",
            max_width="1360px",
            margin="0 auto",
            padding="1.5rem",
        ),
        modal_validacion(),
        min_height="100vh",
        background=FONDO,
    )
