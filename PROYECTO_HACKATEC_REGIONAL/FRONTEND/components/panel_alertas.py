"""Panel lateral de alertas. Flujo Human-in-the-loop: el operador despacha una unidad,
valida y federa a una dependencia, o descarta la alerta como falsa alarma."""

import reflex as rx

from ...estado_ui import EstadoUI
from ...estilos import (
    ALTO_ENCABEZADO,
    AZUL,
    BORDE,
    COLOR_SEVERIDAD,
    LINEA,
    ROJO,
    SUPERFICIE,
    SUPERFICIE_2,
    TEXTO,
    TEXTO_2,
    TEXTO_3,
    VIDEO,
    insignia_estado,
    insignia_severidad,
)
from ...modelos import DESTINOS, MOTIVOS_DESCARTE
from ...state import State
from .cola import alert_item

ANCHO_PANEL = "380px"


def _captura(alerta) -> rx.Component:
    return rx.cond(
        alerta["snapshot_url"] != "",
        rx.image(
            src=alerta["snapshot_url"],
            alt="Captura del evento, sin identificación de personas",
            width="100%",
            max_height="220px",
            object_fit="contain",
            border_radius="8px",
            border=BORDE,
            background=VIDEO,
        ),
        rx.center(
            rx.text("Sin captura disponible para este evento", color=TEXTO_3, size="1"),
            width="100%",
            height="120px",
            border=BORDE,
            border_radius="8px",
            class_name="so-sin-senal",
        ),
    )


def _campo(etiqueta: str, control: rx.Component) -> rx.Component:
    return rx.vstack(rx.text(etiqueta, size="1", color=TEXTO_3), control, spacing="1", width="100%", align="stretch")


def _selector_destino() -> rx.Component:
    return _campo(
        "Validar y despachar a",
        rx.select(list(DESTINOS), value=State.destino, on_change=State.set_destino, width="100%"),
    )


def _boton(texto: str, icono: str, **props) -> rx.Component:
    return rx.button(
        rx.icon(icono, size=16),
        texto,
        size="3",
        width="100%",
        cursor="pointer",
        text_transform="uppercase",
        letter_spacing="0.04em",
        **props,
    )


def _dato(icono: str, etiqueta: str, *valor) -> rx.Component:
    return rx.hstack(
        rx.icon(icono, size=14, color=TEXTO_3, flex_shrink="0", margin_top="2px"),
        rx.vstack(
            rx.text(etiqueta, size="1", color=TEXTO_3, text_transform="uppercase", letter_spacing="0.05em"),
            rx.text(*valor, size="2", color=TEXTO, weight="medium"),
            spacing="0",
            align="start",
            min_width="0",
        ),
        spacing="2",
        align="start",
        width="100%",
    )


def _datos(alerta) -> rx.Component:
    return rx.vstack(
        _dato("cctv", "Cámara", alerta["camara_id"]),
        _dato(
            "map-pin",
            "Ubicación",
            rx.cond(EstadoUI.lugar_sel != "", rx.text.span(EstadoUI.lugar_sel, " · ")),
            rx.text.span(alerta["lat"], ", ", alerta["lng"], color=TEXTO_2, weight="regular"),
        ),
        _dato(
            "siren",
            "Unidad cercana",
            rx.cond(State.unidad_cercana_sel != "", State.unidad_cercana_sel, "Sin patrullas libres en este momento"),
        ),
        _dato("gauge", "Confianza del modelo", alerta["confianza_txt"]),
        spacing="3",
        width="100%",
        padding="0.75rem",
        border=BORDE,
        border_radius="8px",
        background=SUPERFICIE_2,
    )


def _despachar_unidad() -> rx.Component:
    """Envía la patrulla libre más cercana; deja de ofrecerse cuando ya hay una asignada."""
    return rx.cond(
        State.caso_sel == "pendiente",
        _boton(
            "Despachar unidad",
            "siren",
            on_click=State.atender,
            loading=State.procesando,
            disabled=State.unidad_cercana_sel == "",
            color_scheme="red",
        ),
    )


def _acciones_pendiente() -> rx.Component:
    """Alerta por revisar: validar y federar a una dependencia, o descartarla."""
    return rx.vstack(
        _selector_destino(),
        _boton("Validar", "circle-check", on_click=State.confirmar, loading=State.procesando, variant="surface"),
        _campo(
            "Motivo de la falsa alarma",
            rx.select(
                MOTIVOS_DESCARTE,
                value=State.motivo,
                on_change=State.set_motivo,
                placeholder="Selecciona un motivo",
                width="100%",
            ),
        ),
        _boton(
            "Falsa alarma",
            "circle-x",
            on_click=State.descartar,
            disabled=State.procesando | (State.motivo == ""),
            color_scheme="gray",
            variant="surface",
        ),
        spacing="3",
        width="100%",
    )


def _acciones_validada(alerta) -> rx.Component:
    """Evento ya validado cuyo despacho aún no tiene acuse (o falló la federación)."""
    return rx.vstack(
        rx.hstack(insignia_estado(alerta), rx.text(alerta["despacho"], size="2", color=TEXTO_2), align="center", spacing="2", wrap="wrap"),
        rx.text("El evento ya fue validado; falta federarlo a una dependencia.", size="2", color=TEXTO_2),
        _selector_destino(),
        _boton("Despachar", "send", on_click=State.confirmar, loading=State.procesando),
        spacing="3",
        width="100%",
    )


def _resuelta(alerta) -> rx.Component:
    return rx.vstack(
        rx.hstack(insignia_estado(alerta), rx.text(alerta["despacho"], size="2", color=TEXTO_2), align="center", spacing="2", wrap="wrap"),
        rx.cond(alerta["folio"] != "", rx.text("Acuse de interoperabilidad: ", rx.code(alerta["folio"]), size="2", color=TEXTO_2)),
        spacing="2",
        width="100%",
    )


def _atencion_campo(alerta) -> rx.Component:
    """Unidad en camino o caso resuelto en el lugar (la patrulla sigue las calles en el mapa)."""
    return rx.cond(
        alerta["estado"] == "descartado",
        rx.fragment(),
        rx.match(
            State.caso_sel,
            (
                "en_camino",
                rx.callout.root(
                    rx.callout.icon(rx.icon("siren")),
                    rx.callout.text("Unidad en camino: ", State.unidad_sel, ". El caso se resolverá cuando llegue."),
                    color_scheme="blue",
                    width="100%",
                ),
            ),
            (
                "resuelto",
                rx.callout.root(
                    rx.callout.icon(rx.icon("circle-check")),
                    rx.callout.text("Caso atendido y resuelto en el lugar (", State.unidad_sel, ")."),
                    color_scheme="green",
                    width="100%",
                ),
            ),
            rx.fragment(),
        ),
    )


def _acciones(alerta) -> rx.Component:
    return rx.vstack(
        rx.cond(alerta["estado"] != "descartado", _despachar_unidad()),
        rx.match(
            alerta["estado"],
            ("pendiente", _acciones_pendiente()),
            ("validado", _acciones_validada(alerta)),
            _resuelta(alerta),
        ),
        spacing="3",
        width="100%",
    )


def _detalle(alerta) -> rx.Component:
    color = rx.match(alerta["severidad"], *COLOR_SEVERIDAD.items(), TEXTO_2)
    return rx.vstack(
        rx.hstack(
            rx.text("Alerta activa: ", rx.text.span("ID-", alerta["id"], color=AZUL), size="2", weight="bold", color=TEXTO),
            rx.text(alerta["hora"], size="2", weight="medium", color=TEXTO_2),
            justify="between",
            align="center",
            width="100%",
        ),
        rx.hstack(
            rx.text(alerta["tipo_txt"], size="2", weight="bold", color=color, text_transform="uppercase", letter_spacing="0.04em"),
            insignia_severidad(alerta),
            justify="between",
            align="center",
            width="100%",
            padding="0.5rem 0.75rem",
            border_radius="6px",
            border_left=rx.match(alerta["severidad"], *[(k, f"3px solid {v}") for k, v in COLOR_SEVERIDAD.items()], f"3px solid {LINEA}"),
            background=SUPERFICIE_2,
        ),
        _captura(alerta),
        _datos(alerta),
        _atencion_campo(alerta),
        _acciones(alerta),
        spacing="3",
        width="100%",
    )


def _cola() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text("Cola de alertas", size="1", color=TEXTO_3, text_transform="uppercase", letter_spacing="0.06em"),
            rx.text(State.total_pendientes, " por revisar", size="1", color=TEXTO_3),
            justify="between",
            width="100%",
        ),
        rx.vstack(rx.foreach(State.alertas, alert_item), spacing="1", width="100%"),
        spacing="2",
        width="100%",
        padding_top="0.75rem",
        border_top=BORDE,
    )


def _contenido() -> rx.Component:
    alerta = State.alerta_sel
    return rx.cond(
        alerta["id"] != "",
        rx.vstack(_detalle(alerta), _cola(), spacing="4", width="100%"),
        rx.center(
            rx.vstack(
                rx.icon("shield-check", size=28, color=TEXTO_3),
                rx.text("Sin alertas por ahora. Las nuevas aparecerán aquí.", color=TEXTO_3, size="2", text_align="center"),
                spacing="2",
                align="center",
            ),
            width="100%",
            padding_y="3rem",
        ),
    )


def panel_alertas() -> rx.Component:
    """Panel no modal: el mapa y el video siguen operables con el panel abierto.
    Comparte `State.modal_abierto` con el clic en el mapa y la apertura por alerta crítica."""
    return rx.drawer.root(
        rx.drawer.portal(
            rx.drawer.content(
                rx.flex(
                    rx.hstack(
                        rx.hstack(
                            rx.icon("triangle-alert", size=16, color=ROJO),
                            rx.drawer.title("Alertas activas", font_size="14px", font_weight="700", color=TEXTO, margin="0", text_transform="uppercase", letter_spacing="0.06em"),
                            spacing="2",
                            align="center",
                        ),
                        rx.icon_button(
                            rx.icon("x", size=16),
                            on_click=State.cambiar_modal(False),
                            variant="ghost",
                            color_scheme="gray",
                            size="1",
                            aria_label="Cerrar panel de alertas",
                            cursor="pointer",
                        ),
                        justify="between",
                        align="center",
                        width="100%",
                        padding="0.75rem 1rem",
                        border_bottom=BORDE,
                        flex_shrink="0",
                    ),
                    rx.drawer.description("Detalle de la alerta seleccionada y cola de eventos.", display="none"),
                    rx.box(_contenido(), width="100%", padding="1rem", overflow_y="auto", flex="1", min_height="0"),
                    direction="column",
                    width="100%",
                    height="100%",
                ),
                top=ALTO_ENCABEZADO,
                left="auto",
                width=f"min({ANCHO_PANEL}, 100vw)",
                height=f"calc(100% - {ALTO_ENCABEZADO})",
                background=SUPERFICIE,
                border_left=BORDE,
                box_shadow="-12px 0 32px rgba(2, 6, 23, 0.45)",
                # Sin z-index propio: los menús de los selectores se pintan encima por orden del DOM.
                z_index="auto",
            ),
        ),
        direction="right",
        modal=False,
        open=State.modal_abierto,
        on_open_change=State.cambiar_modal,
    )
