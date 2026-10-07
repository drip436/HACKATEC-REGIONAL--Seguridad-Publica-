"""Paleta y piezas visuales compartidas del panel (tema oscuro neutro)."""

import reflex as rx

FONDO = "#0f0f11"
PANEL = "#18181b"
PANEL_2 = "#202024"
LINEA = "#2a2a2f"
BORDE = f"1px solid {LINEA}"
TEXTO = "#ececee"
TEXTO_2 = "#a1a1aa"
TEXTO_3 = "#6f6f78"
ACENTO = "#5b6cf0"

# Colores de estado: reservados para severidad y estado, nunca para series.
COLOR_SEVERIDAD = {"critica": "#e5484d", "alta": "#f76b15", "media": "#e8b931", "baja": "#3fa266"}
COLOR_ESTADO = {
    "pendiente": "#e8b931",
    "validado": "#5b6cf0",
    "confirmado": "#5b6cf0",
    "resuelto": "#3fa266",
    "descartado": "#6f6f78",
}

TARJETA = {
    "width": "100%",
    "padding": "14px",
    "border": BORDE,
    "border_radius": "8px",
    "background": PANEL,
}


def tarjeta(*hijos, **props) -> rx.Component:
    return rx.box(*hijos, **{**TARJETA, **props})


def titulo(texto: str, *derecha: rx.Component) -> rx.Component:
    return rx.hstack(
        rx.text(texto, size="3", weight="medium", color=TEXTO),
        *derecha,
        justify="between",
        align="center",
        width="100%",
        wrap="wrap",
    )


_UNA_LINEA = {"whiteSpace": "nowrap", "overflow": "hidden", "textOverflow": "ellipsis", "maxWidth": "100%"}


def mosaico(icono: str, color: str, etiqueta: str, valor, pie: str = "") -> rx.Component:
    """Recuadro con ícono de color, nombre y cifra (como la lista de objetos de un NVR)."""
    return rx.hstack(
        rx.center(
            rx.icon(icono, size=18, color="#fff"),
            width="34px",
            height="34px",
            border_radius="6px",
            background=color,
            flex_shrink="0",
        ),
        rx.vstack(
            rx.text(etiqueta, size="1", color=TEXTO_2, style=_UNA_LINEA),
            rx.hstack(
                rx.text(valor, size="5", color=TEXTO, weight="medium", style={"fontVariantNumeric": "tabular-nums"}),
                rx.text(pie, size="1", color=TEXTO_3, style=_UNA_LINEA) if pie else rx.fragment(),
                spacing="1",
                align="baseline",
                min_width="0",
            ),
            spacing="0",
            align="start",
            min_width="0",
            flex="1",
        ),
        align="center",
        spacing="3",
        padding="10px 12px",
        border=BORDE,
        border_radius="8px",
        background=PANEL_2,
        width="100%",
    )


def _insignia(texto, valor, colores: dict[str, str]) -> rx.Component:
    color = rx.match(valor, *colores.items(), TEXTO_3)
    return rx.hstack(
        rx.box(width="8px", height="8px", border_radius="2px", background=color, flex_shrink="0"),
        rx.text(texto, size="1", color=TEXTO_2, weight="medium"),
        spacing="1",
        align="center",
    )


def insignia_severidad(alerta) -> rx.Component:
    return _insignia(alerta["sev_txt"], alerta["severidad"], COLOR_SEVERIDAD)


def insignia_estado(alerta) -> rx.Component:
    return _insignia(alerta["estado_txt"], alerta["estado"], COLOR_ESTADO)
