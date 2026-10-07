"""Paleta y estilos compartidos del panel (tema oscuro con los colores del logo).

Fondos en el verde azulado del logo y un solo color de acento (su dorado) para
lo interactivo y la telemetría. Los demás colores
tienen un significado fijo y no se usan para decorar: rojo = incidente,
azul = patrulla, verde = caso resuelto, ámbar = advertencia.
"""

import reflex as rx

# Verde azulado y dorado tomados del logo de SentinelOps.
MARCA = "#0f5152"
FONDO = "#07292a"
SUPERFICIE = "#0d3b3c"
SUPERFICIE_2 = "#124a4b"
LINEA = "#1f5f60"
BORDE = f"1px solid {LINEA}"
TEXTO = "#f1f5f2"
TEXTO_2 = "#c9d8d4"
TEXTO_3 = "#8fb0ab"
ACENTO = "#c8b88e"
ACENTO_SUAVE = "rgba(200, 184, 142, 0.14)"

ROJO = "#ef4444"
AZUL = "#3b82f6"
VERDE = "#22c55e"
AMBAR = "#f59e0b"
# Fondo de video y capturas: casi negro, para que el encuadre no compita con la imagen.
VIDEO = "#031516"
# Velo de los rótulos superpuestos al video.
VELO = "rgba(3, 21, 22, 0.75)"

# Colores de estado: reservados para severidad y estado, nunca para series.
COLOR_SEVERIDAD = {"critica": "#f87171", "alta": "#fb923c", "media": "#fbbf24", "baja": "#8fb0ab"}
COLOR_ESTADO = {
    "pendiente": "#fbbf24",
    "validado": "#5eead4",
    "confirmado": "#4ade80",
    "descartado": "#8fb0ab",
}

# Alto del encabezado fijo: el riel y el panel lateral empiezan debajo.
ALTO_ENCABEZADO = "56px"

TARJETA = {
    "width": "100%",
    "padding": "1rem",
    "border": BORDE,
    "border_radius": "10px",
    "background": SUPERFICIE,
    "position": "relative",
    # Esquinas blancas tipo visor (assets/sentinel.css).
    "class_name": "so-tarjeta",
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
