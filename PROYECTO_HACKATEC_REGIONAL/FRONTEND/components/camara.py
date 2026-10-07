"""Reproductor principal: la cámara vinculada (p. ej. el teléfono con IP Webcam) con la
detección en vivo, o la última captura de la cámara elegida en el mosaico."""

import reflex as rx

from ...estado_ui import EstadoUI
from ...estilos import AMBAR, BORDE, ROJO, TEXTO, TEXTO_2, TEXTO_3, VIDEO, tarjeta, titulo
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


def _rotulo(*hijos, **props) -> rx.Component:
    """Etiqueta superpuesta al video, estilo HUD."""
    return rx.hstack(
        *hijos,
        spacing="2",
        align="center",
        position="absolute",
        padding="2px 8px",
        border_radius="4px",
        background="rgba(2, 6, 23, 0.72)",
        font_size="11px",
        font_weight="600",
        letter_spacing="0.05em",
        color=TEXTO,
        **props,
    )


def _marco(*hijos) -> rx.Component:
    return rx.box(
        *hijos,
        position="relative",
        width="100%",
        aspect_ratio="16 / 9",
        background=VIDEO,
        border_radius="8px",
        overflow="hidden",
        border=BORDE,
    )


def _video() -> rx.Component:
    return rx.vstack(
        _marco(
            rx.image(
                src=State.url_transmision,
                alt="Video en vivo con la detección de personas y el semáforo de riesgo",
                width="100%",
                height="100%",
                object_fit="contain",
            ),
            _rotulo(
                rx.box(width="7px", height="7px", border_radius="50%", background=ROJO, class_name="so-pulso"),
                "EN VIVO",
                top="8px",
                right="8px",
            ),
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
        border=BORDE,
        border_radius="8px",
        padding="1rem",
        class_name="so-sin-senal",
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


def _mapa_punto() -> rx.Component:
    from .mapa import mapa_elegir_punto  # import tardío: mapa importa el estado completo

    return mapa_elegir_punto()


def _estado_ubicacion() -> rx.Component:
    """Qué tan confiable es la coordenada: el punto rojo caerá exactamente ahí."""
    return rx.match(
        State.ubicacion_estado,
        ("buscando", rx.text("Ubicando la cámara (GPS del teléfono o redes Wi-Fi cercanas)…", size="1", color=TEXTO_3)),
        (
            "auto_gps",
            rx.text("Ubicación del GPS del teléfono-cámara (±", State.ubicacion_precision_m, " m).", size="1", color=TEXTO_2),
        ),
        (
            "auto_wifi",
            rx.text(
                "Ubicada por las redes Wi-Fi cercanas con Google (±", State.ubicacion_precision_m,
                " m). Revisa en el mapa que el punto esté sobre el lugar de la cámara.",
                size="1",
                color=TEXTO_2,
            ),
        ),
        (
            "lista",
            rx.text("Ubicación del dispositivo (precisión ±", State.ubicacion_precision_m, " m).", size="1", color=TEXTO_2),
        ),
        (
            "aproximada",
            rx.text(
                "Ubicación aproximada (±", State.ubicacion_precision_m, " m). Si la cámara está en otro punto, "
                "corrige latitud y longitud.",
                size="1",
                color=AMBAR,
            ),
        ),
        (
            "elegida",
            rx.text("Ubicación elegida. Revisa en el mapa que el punto esté sobre el lugar correcto.", size="1", color=TEXTO_2),
        ),
        (
            "por_ip",
            rx.text(
                "No se pudo ubicar automáticamente (", State.ubicacion_motivo, "). Busca la dirección, "
                "pega un enlace de Google Maps o haz clic en el mapa.",
                size="1",
                color=AMBAR,
            ),
        ),
        (
            "denegada",
            rx.text(
                "El navegador no compartió la ubicación. Busca la dirección o haz clic en el mapa.",
                size="1",
                color=AMBAR,
            ),
        ),
        rx.text(
            "Busca la dirección o pega un enlace de Google Maps. En el mapa, cada clic acerca la vista; "
            "ya de cerca, el clic marca el punto exacto de la cámara.",
            size="1",
            color=TEXTO_3,
        ),
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
                            on_blur=State.url_lista,
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
                        placeholder="Plaza de Armas, Villahermosa",
                        width="100%",
                    ),
                ),
                _campo(
                    "Ubicación de la cámara",
                    rx.vstack(
                        rx.flex(
                            rx.input(
                                value=State.busqueda_lugar,
                                on_change=State.set_busqueda_lugar,
                                placeholder="Dirección, lugar o enlace de Google Maps",
                                flex="1",
                                min_width="200px",
                            ),
                            rx.button(
                                rx.icon("search", size=16),
                                "Buscar",
                                on_click=State.buscar_lugar,
                                loading=State.buscando_lugar,
                                variant="soft",
                                type="button",
                            ),
                            rx.button(
                                rx.icon("locate-fixed", size=16),
                                "Ubicar automáticamente",
                                on_click=State.ubicar_automatico,
                                loading=State.ubicacion_estado == "buscando",
                                variant="soft",
                                color_scheme="gray",
                                type="button",
                            ),
                            width="100%",
                            gap="0.5rem",
                            wrap="wrap",
                        ),
                        rx.foreach(
                            State.lugares,
                            lambda lugar, i: rx.button(
                                rx.icon("map-pin", size=14),
                                rx.text(lugar["nombre"], size="1", trim="end", text_align="left", flex="1"),
                                on_click=State.elegir_lugar(i),
                                variant="ghost",
                                color_scheme="gray",
                                width="100%",
                                justify="start",
                                type="button",
                            ),
                        ),
                        _mapa_punto(),
                        rx.flex(
                            rx.input(value=State.form_lat, on_change=State.set_form_lat, placeholder="Latitud", flex="1", min_width="120px", size="1"),
                            rx.input(value=State.form_lng, on_change=State.set_form_lng, placeholder="Longitud", flex="1", min_width="120px", size="1"),
                            width="100%",
                            gap="0.5rem",
                        ),
                        spacing="2",
                        width="100%",
                    ),
                ),
                _estado_ubicacion(),
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
            max_width="560px",
        ),
        open=State.dialogo_camara,
        on_open_change=State.cambiar_dialogo_camara,
    )


def _captura() -> rx.Component:
    """Cámara del mosaico sin transmisión propia: su última captura de evidencia."""
    camara = EstadoUI.proyeccion
    return rx.vstack(
        rx.cond(
            camara["snapshot_url"] != "",
            _marco(
                rx.image(
                    src=camara["snapshot_url"],
                    alt="Última captura de la cámara, sin identificación de personas",
                    width="100%",
                    height="100%",
                    object_fit="contain",
                ),
                _rotulo("ÚLTIMA CAPTURA · ", camara["hora"], top="8px", right="8px"),
            ),
            _aviso("video-off", "Esta cámara aún no tiene capturas. Su imagen aparecerá con su primera alerta."),
        ),
        rx.hstack(
            rx.badge(camara["etiqueta"], color_scheme="gray", variant="soft"),
            rx.text(camara["nombre"], size="2", color=TEXTO_2),
            rx.spacer(),
            rx.button(
                rx.icon("radio", size=14),
                "Volver a en vivo",
                on_click=EstadoUI.proyectar_vivo,
                variant="soft",
                size="1",
                cursor="pointer",
            ),
            align="center",
            width="100%",
            wrap="wrap",
            spacing="2",
        ),
        spacing="2",
        width="100%",
    )


def camara_en_vivo() -> rx.Component:
    return tarjeta(
        rx.vstack(
            titulo(
                rx.cond(EstadoUI.proyecta_vivo, "Cámara en vivo", "Cámara seleccionada"),
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
            rx.cond(EstadoUI.proyecta_vivo, _contenido(), _captura()),
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
