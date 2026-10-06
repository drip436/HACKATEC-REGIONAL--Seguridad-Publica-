"""Paleta y estilos compartidos del panel (tema oscuro fijo)."""

import reflex as rx

FONDO = "#020817"
SUPERFICIE = "rgba(15, 23, 42, 0.8)"
BORDE = "1px solid rgba(148, 163, 184, 0.16)"
TEXTO = "#f8fafc"
TEXTO_2 = "#cbd5e1"
TEXTO_3 = "#94a3b8"
ACENTO = "#38bdf8"

# Colores de estado: reservados para severidad y estado, nunca para series.
COLOR_SEVERIDAD = {"critica": "#f43f5e", "alta": "#f97316", "media": "#fbbf24", "baja": "#22c55e"}
COLOR_ESTADO = {"pendiente": "#fbbf24", "validado": "#38bdf8", "confirmado": "#22c55e", "descartado": "#94a3b8"}

TARJETA = {
    "width": "100%",
    "padding": "1rem",
    "border": BORDE,
    "border_radius": "18px",
    "background": SUPERFICIE,
}


def tarjeta(*hijos, **props) -> rx.Component:
    return rx.box(*hijos, **{**TARJETA, **props})


def titulo(texto: str, *derecha: rx.Component) -> rx.Component:
    return rx.hstack(
        rx.heading(texto, size="4", color=TEXTO),
        *derecha,
        justify="between",
        align="center",
        width="100%",
        wrap="wrap",
    )


def _insignia(texto, valor, colores: dict[str, str]) -> rx.Component:
    color = rx.match(valor, *colores.items(), "#6366f1")
    return rx.badge(
        texto,
        variant="outline",
        style={"color": color, "boxShadow": "inset 0 0 0 1px currentColor", "fontWeight": "700"},
    )


def insignia_severidad(alerta) -> rx.Component:
    return _insignia(alerta["sev_txt"], alerta["severidad"], COLOR_SEVERIDAD)


def insignia_estado(alerta) -> rx.Component:
    return _insignia(alerta["estado_txt"], alerta["estado"], COLOR_ESTADO)
