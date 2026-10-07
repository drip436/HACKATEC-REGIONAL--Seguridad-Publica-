"""Paleta y estilos compartidos del panel (tema claro, sobrio).

Un solo color de acento (verde azulado) para lo interactivo. Los demás colores
tienen un significado fijo y no se usan para decorar: rojo = incidente,
azul = patrulla, verde = caso resuelto.
"""

import reflex as rx

FONDO = "#f5f6f8"
SUPERFICIE = "#ffffff"
SUPERFICIE_2 = "#f9fafb"
LINEA = "#e5e7eb"
BORDE = f"1px solid {LINEA}"
TEXTO = "#111827"
TEXTO_2 = "#4b5563"
TEXTO_3 = "#6b7280"
ACENTO = "#0f766e"
ACENTO_SUAVE = "#ecfdf5"

ROJO = "#dc2626"
AZUL = "#2563eb"
VERDE = "#16a34a"

# Colores de estado: reservados para severidad y estado, nunca para series.
COLOR_SEVERIDAD = {"critica": "#b91c1c", "alta": "#c2410c", "media": "#a16207", "baja": "#4b5563"}
COLOR_ESTADO = {
    "pendiente": "#a16207",
    "validado": "#0f766e",
    "confirmado": "#15803d",
    "descartado": "#6b7280",
}

TARJETA = {
    "width": "100%",
    "padding": "1.25rem",
    "border": BORDE,
    "border_radius": "12px",
    "background": SUPERFICIE,
}


def tarjeta(*hijos, **props) -> rx.Component:
    return rx.box(*hijos, **{**TARJETA, **props})


def titulo(texto: str, *derecha: rx.Component) -> rx.Component:
    return rx.hstack(
        rx.heading(texto, size="3", weight="medium", color=TEXTO),
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
