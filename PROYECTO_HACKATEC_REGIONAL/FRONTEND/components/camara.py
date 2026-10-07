"""Cámara vinculada (p. ej. el teléfono con IP Webcam): video con la detección en vivo."""

import reflex as rx

from ...estilos import BORDE, TEXTO, TEXTO_2, TEXTO_3, tarjeta, titulo
from ...state import State

_NIVEL = {
    "safe": ("Sin riesgo", "green"),
    "suspicious": ("Sospechoso", "amber"),
    "danger": ("Peligro", "red"),
}


def _insignia_nivel() -> rx.Component:
    return rx.match(
        State.edge_nivel,
        *[(clave, rx.badge(texto, color_scheme=color, variant="solid")) for clave, (texto, color) in _NIVEL.items()],
        rx.badge("Analizando", color_scheme="gray", variant="soft"),
    )


def _video() -> rx.Component:
    return rx.vstack(
        rx.box(
            rx.image(
                src=State.url_transmision,
                alt="Video en vivo con la detección de personas y el semáforo de riesgo",
                width="100%",
                height="100%",
                object_fit="contain",
            ),
            width="100%",
            aspect_ratio="16 / 9",
            background="#000",
            border_radius="12px",
            overflow="hidden",
            border=BORDE,
        ),
        rx.hstack(
            _insignia_nivel(),
            rx.text(
                rx.cond(State.edge_regla != "", State.edge_regla, "Sin conductas de riesgo en este momento"),
                size="2",
                color=TEXTO_2,
            ),
            rx.spacer(),
            rx.text(State.edge_personas, " personas · ", State.edge_fps, " fps", size="1", color=TEXTO_3),
            align="center",
            width="100%",
            wrap="wrap",
            spacing="2",
        ),
        spacing="2",
        width="100%",
    )


def _aviso(icono: str, texto, detalle=None) -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.icon(icono, size=28, color=TEXTO_3),
            rx.text(texto, size="2", color=TEXTO_2, text_align="center"),
            detalle if detalle is not None else rx.fragment(),
            spacing="2",
            align="center",
            max_width="460px",
        ),
        width="100%",
        aspect_ratio="16 / 9",
        background="rgba(15, 23, 42, 0.6)",
        border=BORDE,
        border_radius="12px",
        padding="1rem",
    )


def _contenido() -> rx.Component:
    return rx.cond(
        State.edge_en_linea,
        _video(),
        rx.cond(
            State.cam_vinculada,
            rx.cond(
                State.cam_activa,
                _aviso("loader", "Cargando la IA y conectando con la cámara… (la primera vez descarga los modelos)"),
                _aviso(
                    "triangle-alert",
                    "El sensor se detuvo. Revisa que la URL de la cámara sea accesible desde esta computadora.",
                    rx.code(State.cam_error, size="1", style={"whiteSpace": "pre-wrap", "wordBreak": "break-all"}),
                ),
            ),
            _aviso(
                "smartphone",
                "Vincula la cámara de un teléfono (app IP Webcam) o usa el video de demostración "
                "para detectar conductas de riesgo en vivo.",
                rx.button(rx.icon("link", size=16), "Vincular cámara", on_click=State.abrir_dialogo_camara, size="2"),
            ),
        ),
    )


def _campo(etiqueta: str, control: rx.Component, ayuda: str = "") -> rx.Component:
    return rx.vstack(
        rx.text(etiqueta, size="2", color=TEXTO_2, weight="medium"),
        control,
        rx.text(ayuda, size="1", color=TEXTO_3) if ayuda else rx.fragment(),
        spacing="1",
        width="100%",
        align="stretch",
    )


def dialogo_vincular() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.vstack(
                rx.dialog.title("Vincular cámara", margin="0"),
                rx.dialog.description(
                    "En el teléfono abre IP Webcam y toca «Iniciar servidor». Usa la dirección que muestra "
                    "agregando /video. El teléfono y esta computadora deben estar en la misma red Wi-Fi.",
                    size="2",
                    color=TEXTO_2,
                ),
                rx.hstack(
                    rx.switch(checked=State.form_demo, on_change=State.set_form_demo),
                    rx.text("Usar el video de demostración (sin teléfono)", size="2", color=TEXTO),
                    align="center",
                    spacing="2",
                ),
                rx.cond(
                    ~State.form_demo,
                    _campo(
                        "URL de la cámara",
                        rx.input(
                            value=State.form_url,
                            on_change=State.set_form_url,
                            placeholder="http://192.168.1.50:8080/video",
                            width="100%",
                        ),
                    ),
                ),
                _campo(
                    "Lugar que vigila",
                    rx.input(
                        value=State.form_nombre,
                        on_change=State.set_form_nombre,
                        placeholder="Parque de Santa Lucía",
                        width="100%",
                    ),
                ),
                _campo(
                    "Ubicación en el mapa",
                    rx.hstack(
                        rx.input(value=State.form_lat, on_change=State.set_form_lat, placeholder="Latitud", flex="1"),
                        rx.input(value=State.form_lng, on_change=State.set_form_lng, placeholder="Longitud", flex="1"),
                        rx.button(
                            rx.icon("locate-fixed", size=16),
                            "Mi ubicación",
                            on_click=State.usar_mi_ubicacion,
                            variant="soft",
                            type="button",
                        ),
                        width="100%",
                        spacing="2",
                    ),
                    "Ahí aparecerá el punto rojo si la cámara detecta violencia.",
                ),
                rx.flex(
                    rx.dialog.close(rx.button("Cancelar", variant="soft", color_scheme="gray", flex="1")),
                    rx.button(
                        rx.icon("link", size=16),
                        "Vincular y empezar a detectar",
                        on_click=State.vincular_camara,
                        loading=State.vinculando,
                        flex="1",
                    ),
                    gap="0.75rem",
                    width="100%",
                ),
                spacing="4",
                width="100%",
            ),
            max_width="520px",
        ),
        open=State.dialogo_camara,
        on_open_change=State.cambiar_dialogo_camara,
    )


def camara_en_vivo() -> rx.Component:
    return tarjeta(
        rx.vstack(
            titulo(
                "Cámara en vivo",
                rx.cond(
                    State.cam_vinculada,
                    rx.hstack(
                        rx.text(State.cam_nombre, size="2", color=TEXTO_2),
                        rx.button(
                            rx.icon("unlink", size=14),
                            "Desvincular",
                            on_click=State.desvincular_camara,
                            variant="soft",
                            color_scheme="gray",
                            size="1",
                        ),
                        align="center",
                        spacing="2",
                    ),
                    rx.button(rx.icon("link", size=14), "Vincular cámara", on_click=State.abrir_dialogo_camara, size="1"),
                ),
            ),
            _contenido(),
            rx.text(
                "Detección de personas, posturas y armas con YOLOv8-Pose. No identifica a nadie: sin reconocimiento facial.",
                size="1",
                color=TEXTO_3,
            ),
            spacing="3",
            width="100%",
        ),
        dialogo_vincular(),
    )
