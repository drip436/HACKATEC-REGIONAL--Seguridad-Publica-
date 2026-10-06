"""Encabezado, navegación y contenedor común de las páginas."""

import reflex as rx

from ..estilos import ACENTO, BORDE, FONDO, TEXTO, TEXTO_2, TEXTO_3
from ..state import State
from .modal_validacion import modal_validacion

PAGINAS = [("Operación", "/"), ("Analítica", "/analitica"), ("Auditoría", "/auditoria")]


def _enlace(texto: str, ruta: str, activa: str) -> rx.Component:
    actual = ruta == activa
    return rx.link(
        texto,
        href=ruta,
        underline="none",
        color=TEXTO if actual else TEXTO_2,
        font_weight="700" if actual else "500",
        padding="0.4rem 0.8rem",
        border_radius="10px",
        background="rgba(56, 189, 248, 0.16)" if actual else "transparent",
        aria_current="page" if actual else "false",
    )


def _encabezado(activa: str) -> rx.Component:
    return rx.flex(
        rx.vstack(
            rx.text("SENTINELOPS", color=ACENTO, font_weight="700", letter_spacing="0.12em", size="1"),
            rx.heading("Operación de Seguridad Pública", size="6", color=TEXTO),
            spacing="0",
            align="start",
        ),
        rx.hstack(*[_enlace(texto, ruta, activa) for texto, ruta in PAGINAS], spacing="1", as_="nav"),
        rx.hstack(
            rx.badge("Conexión: ", State.conexion, color_scheme=rx.cond(State.conexion == "Conectado", "green", "amber"), variant="soft"),
            rx.badge("Operador ", State.operador, color_scheme="gray", variant="soft"),
            spacing="2",
            wrap="wrap",
        ),
        justify="between",
        align="center",
        wrap="wrap",
        gap="0.75rem",
        width="100%",
        padding_bottom="1rem",
        border_bottom=BORDE,
    )


def pagina(activa: str, *contenido: rx.Component) -> rx.Component:
    return rx.box(
        rx.vstack(
            _encabezado(activa),
            *contenido,
            rx.cond(
                State.modo_simulado,
                rx.text(
                    "Modo simulado: las alertas y el histórico mostrados son datos sintéticos.",
                    size="1",
                    color=TEXTO_3,
                ),
            ),
            spacing="4",
            width="100%",
            max_width="1500px",
            margin="0 auto",
        ),
        modal_validacion(),
        min_height="100vh",
        padding="1.25rem 1rem 3rem",
        background=f"radial-gradient(circle at top, rgba(14, 116, 144, 0.18), transparent 28%), {FONDO}",
    )
