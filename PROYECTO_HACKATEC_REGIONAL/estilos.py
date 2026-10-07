"""Paleta y estilos compartidos del panel (tema oscuro táctico).

Un solo color de acento (cian) para lo interactivo y la telemetría. Los demás colores
tienen un significado fijo y no se usan para decorar: rojo = incidente,
azul = patrulla, verde = caso resuelto, ámbar = advertencia.
"""

import reflex as rx

FONDO = "#0f172a"
SUPERFICIE = "#1e293b"
SUPERFICIE_2 = "#273449"
LINEA = "#334155"
BORDE = f"1px solid {LINEA}"
TEXTO = "#e2e8f0"
TEXTO_2 = "#cbd5e1"
TEXTO_3 = "#94a3b8"
ACENTO = "#22d3ee"
ACENTO_SUAVE = "rgba(34, 211, 238, 0.12)"

ROJO = "#ef4444"
AZUL = "#3b82f6"
VERDE = "#22c55e"
AMBAR = "#f59e0b"
# Fondo de video y capturas: casi negro, para que el encuadre no compita con la imagen.
VIDEO = "#020617"

# Colores de estado: reservados para severidad y estado, nunca para series.
COLOR_SEVERIDAD = {"critica": "#f87171", "alta": "#fb923c", "media": "#fbbf24", "baja": "#94a3b8"}
COLOR_ESTADO = {
    "pendiente": "#fbbf24",
    "validado": "#22d3ee",
    "confirmado": "#4ade80",
    "descartado": "#94a3b8",
}

# Alto del encabezado fijo: el riel y el panel lateral empiezan debajo.
ALTO_ENCABEZADO = "56px"

TARJETA = {
    "width": "100%",
    "padding": "1rem",
    "border": BORDE,
    "border_radius": "10px",
    "background": SUPERFICIE,
}


def tarjeta(*hijos, **props) -> rx.Component:
    return rx.box(*hijos, **{**TARJETA, **props})


def titulo(texto: str, *derecha: rx.Component) -> rx.Component:
    return rx.hstack(
        rx.heading(texto, size="2", weight="medium", color=TEXTO_2, text_transform="uppercase", letter_spacing="0.06em"),
        *derecha,
        justify="between",
        align="center",
        width="100%",
        wrap="wrap",
        gap="0.5rem",
    )


def _insignia(texto, valor, colores: dict[str, str]) -> rx.Component:
    color = rx.match(valor, *colores.items(), TEXTO_2)
    return rx.text.span(
        rx.box(width="6px", height="6px", border_radius="50%", background=color, flex_shrink="0"),
        texto,
        display="inline-flex",
        align_items="center",
        gap="0.375rem",
        font_size="12px",
        font_weight="500",
        color=color,
        white_space="nowrap",
    )


def insignia_severidad(alerta) -> rx.Component:
    return _insignia(alerta["sev_txt"], alerta["severidad"], COLOR_SEVERIDAD)


def insignia_estado(alerta) -> rx.Component:
    return _insignia(alerta["estado_txt"], alerta["estado"], COLOR_ESTADO)
