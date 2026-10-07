"""Paleta y estilos compartidos del panel (tema claro con los colores del logo).

Fondo casi blanco, el verde azulado del logo como único color de acento y su
dorado solo para detalles de marca. Los demás colores tienen un significado
fijo y no se usan para decorar: rojo = incidente, azul = patrulla,
verde = caso resuelto, ámbar = advertencia.
"""

import reflex as rx

# Verde azulado y dorado tomados del logo de SentinelOps.
MARCA = "#0f5152"
ORO = "#b0975a"
FONDO = "#f4f6f2"
SUPERFICIE = "#ffffff"
SUPERFICIE_2 = "#eef2ee"
LINEA = "#d5ddd8"
BORDE = f"1px solid {LINEA}"
TEXTO = "#0c3536"
TEXTO_2 = "#3d5c5b"
TEXTO_3 = "#64807d"
ACENTO = MARCA
ACENTO_SUAVE = "rgba(15, 81, 82, 0.1)"

ROJO = "#dc2626"
AZUL = "#2563eb"
VERDE = "#16a34a"
AMBAR = "#b45309"
# El video y las capturas conservan fondo oscuro: el encuadre no compite con la imagen.
VIDEO = "#031516"
# Velo y texto de los rótulos superpuestos al video.
VELO = "rgba(3, 21, 22, 0.75)"
SOBRE_VIDEO = "#f1f5f2"
SOBRE_VIDEO_2 = "#a9c2bd"

# Colores de estado: reservados para severidad y estado, nunca para series.
COLOR_SEVERIDAD = {"critica": "#b91c1c", "alta": "#c2410c", "media": "#a16207", "baja": "#64807d"}
COLOR_ESTADO = {
    "pendiente": "#a16207",
    "validado": "#0f766e",
    "confirmado": "#15803d",
    "descartado": "#64807d",
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
    # Esquinas doradas tipo visor (assets/sentinel.css).
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
