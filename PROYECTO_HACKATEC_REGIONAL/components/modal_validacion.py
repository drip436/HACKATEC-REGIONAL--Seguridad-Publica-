"""Flujo Human-in-the-loop: el operador confirma y despacha, o descarta."""

import reflex as rx

from ..estilos import BORDE, TEXTO_2, TEXTO_3, insignia_estado, insignia_severidad
from ..modelos import DESTINOS, MOTIVOS_DESCARTE
from ..state import State


def _captura(alerta) -> rx.Component:
    return rx.cond(
        alerta["snapshot_url"] != "",
        rx.image(
            src=alerta["snapshot_url"],
            alt="Captura del evento, sin identificación de personas",
            width="100%",
            max_height="260px",
            object_fit="contain",
            border_radius="12px",
            background="#000",
        ),
        rx.center(
            rx.text("Sin captura disponible para este evento", color=TEXTO_3, size="2"),
            width="100%",
            height="160px",
            border=BORDE,
            border_radius="12px",
            background="rgba(15, 23, 42, 0.6)",
        ),
    )


def _campo(etiqueta: str, control: rx.Component) -> rx.Component:
    return rx.vstack(rx.text(etiqueta, size="2", color=TEXTO_2), control, spacing="1", width="100%", align="stretch")


def _acciones() -> rx.Component:
    return rx.vstack(
        rx.grid(
            _campo(
                "Despachar a",
                rx.select(list(DESTINOS), value=State.destino, on_change=State.set_destino, width="100%"),
            ),
            _campo(
                "Motivo (solo para descartar)",
                rx.select(
                    MOTIVOS_DESCARTE,
                    value=State.motivo,
                    on_change=State.set_motivo,
                    placeholder="Selecciona un motivo",
                    width="100%",
                ),
            ),
            columns=rx.breakpoints(initial="1", sm="2"),
            spacing="3",
            width="100%",
        ),
        rx.flex(
            rx.button(
                "Descartar",
                on_click=State.descartar,
                disabled=State.procesando | (State.motivo == ""),
                color_scheme="gray",
                variant="soft",
                size="3",
                flex="1",
            ),
            rx.button(
                "Confirmar y despachar",
                on_click=State.confirmar,
                loading=State.procesando,
                color_scheme="green",
                size="3",
                flex="1",
            ),
            gap="0.75rem",
            wrap="wrap",
            width="100%",
        ),
        spacing="4",
        width="100%",
    )


def _despacho_pendiente(alerta) -> rx.Component:
    """Evento ya validado cuyo despacho aún no tiene acuse (o falló la federación)."""
    return rx.vstack(
        rx.hstack(insignia_estado(alerta), rx.text(alerta["despacho"], size="2"), align="center", spacing="2", wrap="wrap"),
        rx.text("El evento ya fue validado; falta federarlo a una dependencia.", size="2", color=TEXTO_2),
        _campo(
            "Despachar a",
            rx.select(list(DESTINOS), value=State.destino, on_change=State.set_destino, width="100%"),
        ),
        rx.button(
            "Despachar",
            on_click=State.confirmar,
            loading=State.procesando,
            color_scheme="green",
            size="3",
            width="100%",
        ),
        spacing="3",
        width="100%",
    )


def _resuelta(alerta) -> rx.Component:
    return rx.vstack(
        rx.hstack(insignia_estado(alerta), rx.text(alerta["despacho"], size="2"), align="center", spacing="2"),
        rx.cond(alerta["folio"] != "", rx.text("Acuse de interoperabilidad: ", rx.code(alerta["folio"]), size="2")),
        rx.dialog.close(rx.button("Cerrar", variant="soft", color_scheme="gray", size="3", width="100%")),
        spacing="3",
        width="100%",
    )


def modal_validacion() -> rx.Component:
    from .cola import datos_alerta

    alerta = State.alerta_sel
    return rx.dialog.root(
        rx.dialog.content(
            rx.vstack(
                rx.hstack(
                    rx.dialog.title(alerta["tipo_txt"], margin="0"),
                    insignia_severidad(alerta),
                    justify="between",
                    align="center",
                    width="100%",
                ),
                rx.dialog.description(
                    "Evento ", rx.code(alerta["id"]), ". La decisión es del operador; la IA solo sugiere.",
                    size="2",
                    color=TEXTO_2,
                ),
                _captura(alerta),
                datos_alerta(alerta),
                rx.match(
                    alerta["estado"],
                    ("pendiente", _acciones()),
                    ("validado", _despacho_pendiente(alerta)),
                    _resuelta(alerta),
                ),
                spacing="4",
                width="100%",
            ),
            max_width="560px",
        ),
        open=State.modal_abierto,
        on_open_change=State.cambiar_modal,
    )
