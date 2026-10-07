"""Cámara vinculada (p. ej. el teléfono con IP Webcam): video con la detección en vivo."""

import reflex as rx

from ...estilos import LINEA, TEXTO, TEXTO_2, TEXTO_3, tarjeta
from ...state import State

_NIVEL = {
    "safe": ("Sin riesgo", "green"),
    "suspicious": ("Sospechoso", "amber"),
    "danger": ("Peligro", "red"),
}


def _insignia_nivel() -> rx.Component:
    return rx.match(
        State.edge_nivel,
        *[(clave, rx.badge(texto, color_scheme=color, variant="soft")) for clave, (texto, color) in _NIVEL.items()],
        rx.badge("Analizando", color_scheme="gray", variant="soft"),
    )


def _estado_conexion() -> rx.Component:
    color = rx.match(
        State.cam_estado,
        ("en_linea", "#3fa266"),
        ("reconectando", "#e8b931"),
        ("detenida", "#e5484d"),
        TEXTO_3,
    )
    span = rx.text.span
    texto = rx.match(
        State.cam_estado,
        ("en_linea", span(rx.cond(State.edge_en_linea, "En vivo", "Iniciando video"))),
        ("conectando", span("Conectando")),
        ("reconectando", span("Reconectando · intento ", State.cam_intento)),
        ("detenida", span("Sin conexión")),
        span("Sin cámara"),
    )
    return rx.hstack(
        rx.box(width="7px", height="7px", border_radius="50%", background=color),
        rx.text(texto, size="1", color=TEXTO_2),
        spacing="2",
        align="center",
    )


def _aviso(icono: str, texto, detalle=None) -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.icon(icono, size=24, color=TEXTO_3),
            rx.text(texto, size="2", color=TEXTO_2, text_align="center"),
            detalle if detalle is not None else rx.fragment(),
            spacing="2",
            align="center",
            max_width="440px",
        ),
        height="100%",
        padding="1rem",
    )


def _contenido() -> rx.Component:
    return rx.cond(
        State.edge_en_linea,
        rx.image(
            src=State.url_transmision,
            alt="Video en vivo con detecciones",
            width="100%",
            height="100%",
            object_fit="contain",
        ),
        rx.match(
            State.cam_estado,
            ("conectando", _aviso("loader", "Conectando con la cámara y cargando el modelo…")),
            ("en_linea", _aviso("loader", "Conectando con la cámara y cargando el modelo…")),
            ("reconectando", _aviso("refresh-cw", "Se perdió la señal; reconectando automáticamente…")),
            (
                "detenida",
                _aviso(
                    "triangle-alert",
                    "No se pudo mantener la conexión con la cámara.",
                    rx.code(State.cam_error, size="1", variant="ghost", style={"whiteSpace": "pre-wrap", "wordBreak": "break-all"}),
                ),
            ),
            _aviso(
                "smartphone",
                "Sin cámara vinculada.",
                rx.button(rx.icon("link", size=14), "Vincular cámara", on_click=State.abrir_dialogo_camara, size="2", variant="soft"),
            ),
        ),
    )


def camara_en_vivo() -> rx.Component:
    return tarjeta(
        rx.vstack(
            rx.hstack(
                rx.hstack(
                    rx.text(rx.cond(State.cam_vinculada, State.cam_nombre, "Cámara"), size="3", weight="medium", color=TEXTO),
                    _estado_conexion(),
                    spacing="3",
                    align="center",
                    min_width="0",
                ),
                rx.cond(
                    State.cam_vinculada,
                    rx.button(
                        rx.icon("unlink", size=14),
                        "Desvincular",
                        on_click=State.desvincular_camara,
                        variant="soft",
                        color_scheme="gray",
                        size="1",
                    ),
                ),
                justify="between",
                align="center",
                width="100%",
            ),
            rx.box(
                _contenido(),
                width="100%",
                aspect_ratio="16 / 9",
                background="#000",
                border_radius="6px",
                overflow="hidden",
                border=f"1px solid {LINEA}",
            ),
            rx.cond(
                State.edge_en_linea,
                rx.hstack(
                    _insignia_nivel(),
                    rx.text(rx.cond(State.edge_regla != "", State.edge_regla, "Sin conductas de riesgo"), size="2", color=TEXTO_2),
                    rx.spacer(),
                    rx.text(State.edge_personas, " personas · ", State.edge_fps, " fps", size="1", color=TEXTO_3),
                    align="center",
                    width="100%",
                    wrap="wrap",
                    spacing="2",
                ),
            ),
            spacing="3",
            width="100%",
        ),
        padding="12px",
    )


# ---- Formulario de vinculación ----------------------------------------------------


def _campo(etiqueta: str, control: rx.Component) -> rx.Component:
    return rx.vstack(
        rx.text(etiqueta, size="2", color=TEXTO_2, weight="medium"),
        control,
        spacing="1",
        width="100%",
        align="stretch",
    )


def _ubicacion() -> rx.Component:
    resumen = rx.match(
        State.ubicacion_estado,
        ("buscando", rx.hstack(rx.spinner(size="1"), rx.text("Detectando ubicación…", size="2", color=TEXTO_2), spacing="2", align="center")),
        (
            "lista",
            rx.text(
                "Ubicación detectada",
                rx.cond(State.ubicacion_precision_m > 0, rx.text.span(" (±", State.ubicacion_precision_m, " m)"), ""),
                size="2",
                color=TEXTO_2,
            ),
        ),
        ("sin_permiso", rx.text("El navegador no dio la ubicación: se usa el campus del Tecnológico.", size="2", color=TEXTO_2)),
        rx.text("Ubicación del campus", size="2", color=TEXTO_2),
    )
    return rx.vstack(
        rx.hstack(
            rx.icon("map-pin", size=16, color=TEXTO_3),
            resumen,
            rx.spacer(),
            rx.button(rx.icon("locate-fixed", size=14), "Detectar", on_click=State.usar_mi_ubicacion, variant="ghost", size="1", type="button"),
            align="center",
            width="100%",
        ),
        rx.accordion.root(
            rx.accordion.item(
                header=rx.text("Ajustar coordenadas", size="1", color=TEXTO_3),
                content=rx.hstack(
                    rx.input(value=State.form_lat, on_change=State.set_form_lat, placeholder="Latitud", flex="1"),
                    rx.input(value=State.form_lng, on_change=State.set_form_lng, placeholder="Longitud", flex="1"),
                    width="100%",
                    spacing="2",
                ),
                value="ajustar",
            ),
            collapsible=True,
            type="single",
            variant="ghost",
            width="100%",
        ),
        spacing="1",
        width="100%",
    )


def dialogo_vincular() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.vstack(
                rx.dialog.title("Vincular cámara", margin="0"),
                rx.dialog.description(
                    "Abre IP Webcam en el teléfono y toca «Iniciar servidor». Basta con la IP que muestra; "
                    "el puerto y la ruta se completan solos.",
                    size="2",
                    color=TEXTO_2,
                ),
                rx.hstack(
                    rx.switch(checked=State.form_demo, on_change=State.set_form_demo),
                    rx.text("Usar el video de demostración", size="2", color=TEXTO),
                    align="center",
                    spacing="2",
                ),
                rx.cond(
                    ~State.form_demo,
                    _campo(
                        "Dirección de la cámara",
                        rx.input(
                            value=State.form_url,
                            on_change=State.set_form_url,
                            placeholder="http://192.168.1.50",
                            width="100%",
                        ),
                    ),
                ),
                _campo(
                    "Lugar que vigila",
                    rx.input(
                        value=State.form_nombre,
                        on_change=State.set_form_nombre,
                        placeholder="Tecnológico · acceso principal",
                        width="100%",
                    ),
                ),
                _ubicacion(),
                rx.flex(
                    rx.dialog.close(rx.button("Cancelar", variant="soft", color_scheme="gray", flex="1")),
                    rx.button("Vincular", on_click=State.vincular_camara, loading=State.vinculando, flex="1"),
                    gap="0.75rem",
                    width="100%",
                ),
                spacing="4",
                width="100%",
            ),
            max_width="480px",
        ),
        open=State.dialogo_camara,
        on_open_change=State.cambiar_dialogo_camara,
    )
