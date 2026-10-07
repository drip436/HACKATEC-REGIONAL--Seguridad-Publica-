"""Encabezado, navegación y contenedor común de las páginas."""

import reflex as rx

from ...estilos import ALTO_ENCABEZADO, ACENTO, ACENTO_SUAVE, AMBAR, BORDE, FONDO, LINEA, MARCA, ROJO, SUPERFICIE, SUPERFICIE_2, TEXTO, TEXTO_2, TEXTO_3, VERDE
from ...state import State
from .panel_alertas import panel_alertas

PAGINAS = [("Operación", "/", "layout-dashboard"), ("Analítica", "/analitica", "activity"), ("Auditoría", "/auditoria", "scroll-text")]
ANCHO_RIEL = "56px"


def _enlace(texto: str, ruta: str, icono: str, activa: str) -> rx.Component:
    actual = ruta == activa
    return rx.tooltip(
        rx.link(
            rx.center(
                rx.icon(icono, size=18),
                width="36px",
                height="36px",
                border_radius="8px",
                color=ACENTO if actual else TEXTO_3,
                background=ACENTO_SUAVE if actual else "transparent",
                _hover={"color": TEXTO, "background": SUPERFICIE_2},
            ),
            href=ruta,
            aria_label=texto,
            aria_current="page" if actual else "false",
        ),
        content=texto,
        side="right",
    )


def _navegacion(activa: str, **props) -> rx.Component:
    return rx.flex(*[_enlace(texto, ruta, icono, activa) for texto, ruta, icono in PAGINAS], gap="0.5rem", as_="nav", **props)


def _punto(color, pulso: bool = False) -> rx.Component:
    return rx.box(
        width="8px", height="8px", border_radius="50%", background=color, flex_shrink="0", class_name="so-pulso" if pulso else ""
    )


def _estado_conexion() -> rx.Component:
    conectado = State.conexion == "Conectado"
    return rx.hstack(
        _punto(rx.cond(conectado, VERDE, AMBAR), pulso=True),
        rx.text(State.conexion, size="1", weight="medium", color=rx.cond(conectado, VERDE, AMBAR), text_transform="uppercase", letter_spacing="0.05em"),
        spacing="2",
        align="center",
    )


def _estado_ia() -> rx.Component:
    return rx.hstack(
        rx.icon("scan-eye", size=14, color=rx.cond(State.edge_en_linea, ACENTO, TEXTO_3)),
        rx.text(
            rx.cond(State.edge_en_linea, "IA en línea", "IA sin señal"),
            size="1",
            color=rx.cond(State.edge_en_linea, TEXTO_2, TEXTO_3),
        ),
        spacing="2",
        align="center",
        display=rx.breakpoints(initial="none", sm="flex"),
    )


def _separador() -> rx.Component:
    return rx.box(width="1px", height="16px", background=LINEA, display=rx.breakpoints(initial="none", sm="block"))


def _boton_alertas() -> rx.Component:
    """Abre y cierra el panel lateral; el contador son las alertas por revisar."""
    criticas = State.total_criticas > 0
    return rx.button(
        rx.icon("bell-ring", size=16),
        "Alertas",
        rx.cond(
            State.total_pendientes > 0,
            rx.center(
                State.total_pendientes,
                min_width="20px",
                height="20px",
                padding_x="6px",
                border_radius="10px",
                background=rx.cond(criticas, ROJO, AMBAR),
                color="#fff",
                font_size="11px",
                font_weight="700",
            ),
        ),
        on_click=State.cambiar_modal(~State.modal_abierto),
        variant=rx.cond(State.modal_abierto, "solid", "surface"),
        color_scheme=rx.cond(criticas, "red", "amber"),
        size="2",
        cursor="pointer",
        aria_expanded=State.modal_abierto,
        text_transform="uppercase",
        letter_spacing="0.05em",
    )


def _encabezado(activa: str) -> rx.Component:
    return rx.flex(
        rx.hstack(
            rx.center(
                rx.icon("shield", size=16, color=ACENTO),
                width="28px",
                height="28px",
                border_radius="7px",
                background=MARCA,
                border=f"1px solid {ACENTO}",
                flex_shrink="0",
            ),
            rx.vstack(
                rx.text("Sentinel", rx.text.span("Ops", color=ACENTO), size="3", weight="bold", color=TEXTO, line_height="1.1"),
                rx.text(
                    "Monitoreo de seguridad · Región Sur-Sureste",
                    size="1",
                    color=TEXTO_3,
                    line_height="1.1",
                    display=rx.breakpoints(initial="none", md="block"),
                ),
                spacing="0",
                align="start",
            ),
            _separador(),
            _estado_conexion(),
            _separador(),
            _estado_ia(),
            spacing="3",
            align="center",
        ),
        _navegacion(activa, display=rx.breakpoints(initial="flex", md="none")),
        rx.hstack(
            rx.hstack(
                rx.icon("user-round", size=14, color=TEXTO_3),
                rx.text(State.operador, size="1", color=TEXTO_2),
                spacing="1",
                align="center",
                display=rx.breakpoints(initial="none", sm="flex"),
            ),
            _boton_alertas(),
            spacing="3",
            align="center",
        ),
        justify="between",
        align="center",
        wrap="wrap",
        gap="0.5rem 1rem",
        width="100%",
        min_height=ALTO_ENCABEZADO,
        padding="0.5rem 1rem",
        background=SUPERFICIE,
        border_bottom=BORDE,
        position="sticky",
        top="0",
        z_index="10",
    )


def _riel(activa: str) -> rx.Component:
    return _navegacion(
        activa,
        direction="column",
        align="center",
        display=rx.breakpoints(initial="none", md="flex"),
        width=ANCHO_RIEL,
        flex_shrink="0",
        padding_y="0.75rem",
        background=SUPERFICIE,
        border_right=BORDE,
        position="sticky",
        top=ALTO_ENCABEZADO,
        height=f"calc(100vh - {ALTO_ENCABEZADO})",
    )


def pagina(activa: str, *contenido: rx.Component) -> rx.Component:
    return rx.box(
        _encabezado(activa),
        rx.flex(
            _riel(activa),
            rx.vstack(
                *contenido,
                rx.cond(
                    State.modo_simulado,
                    rx.text("Modo simulado: las alertas y el histórico son datos sintéticos.", size="1", color=TEXTO_3),
                ),
                spacing="4",
                flex="1",
                min_width="0",
                padding="1rem",
            ),
            align="start",
            width="100%",
        ),
        panel_alertas(),
        min_height="100vh",
        background=FONDO,
    )
