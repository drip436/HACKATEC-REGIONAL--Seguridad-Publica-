"""Revisión de una alerta: atender (enviar patrulla), dejar pendiente, despachar o descartar."""

import reflex as rx

from ...estilos import LINEA, TEXTO_2, TEXTO_3, insignia_estado, insignia_severidad
from ...modelos import DESTINOS, MOTIVOS_DESCARTE
from ...state import State


def _captura(alerta) -> rx.Component:
    return rx.cond(
        alerta["snapshot_url"] != "",
        rx.image(
            src=alerta["snapshot_url"],
            alt="Captura del evento",
            width="100%",
            max_height="260px",
            object_fit="contain",
            border_radius="6px",
            background="#000",
        ),
        rx.center(
            rx.text("Sin captura", color=TEXTO_3, size="2"),
            width="100%",
            height="120px",
            border=f"1px solid {LINEA}",
            border_radius="6px",
            background="#000",
        ),
    )


def _atender() -> rx.Component:
    return rx.vstack(
        rx.flex(
            rx.button(
                rx.icon("siren", size=16),
                "Atender",
                on_click=State.atender,
                loading=State.procesando,
                size="3",
                flex="1",
            ),
            rx.button(
                "Marcar pendiente",
                on_click=State.marcar_pendiente,
                variant="soft",
                color_scheme="gray",
                size="3",
                flex="1",
            ),
            gap="0.75rem",
            width="100%",
        ),
        rx.cond(
            State.unidad_cercana_sel != "",
            rx.text("Saldría ", State.unidad_cercana_sel, size="1", color=TEXTO_3),
        ),
        spacing="2",
        width="100%",
    )


def _mas_acciones(alerta) -> rx.Component:
    despachar = rx.hstack(
        rx.select(list(DESTINOS), value=State.destino, on_change=State.set_destino, flex="1"),
        rx.button("Despachar", on_click=State.confirmar, loading=State.procesando, variant="soft"),
        width="100%",
        spacing="2",
    )
    descartar = rx.hstack(
        rx.select(MOTIVOS_DESCARTE, value=State.motivo, on_change=State.set_motivo, placeholder="Motivo", flex="1"),
        rx.button(
            "Descartar",
            on_click=State.descartar,
            disabled=State.procesando | (State.motivo == ""),
            variant="soft",
            color_scheme="gray",
        ),
        width="100%",
        spacing="2",
    )
    return rx.accordion.root(
        rx.accordion.item(
            header=rx.text("Más acciones", size="2", color=TEXTO_2),
            content=rx.vstack(
                rx.text("Avisar a una dependencia", size="1", color=TEXTO_3),
                despachar,
                rx.cond(
                    alerta["estado"] == "pendiente",
                    rx.vstack(rx.text("Falsa alarma", size="1", color=TEXTO_3), descartar, spacing="1", width="100%"),
                ),
                spacing="2",
                width="100%",
            ),
            value="mas",
        ),
        collapsible=True,
        type="single",
        variant="ghost",
        width="100%",
    )


def _aviso(color: str, icono: str, *texto) -> rx.Component:
    return rx.callout.root(
        rx.callout.icon(rx.icon(icono)),
        rx.callout.text(*texto),
        color_scheme=color,
        variant="surface",
        width="100%",
    )


def _acciones(alerta) -> rx.Component:
    return rx.cond(
        (alerta["estado"] == "resuelto") | (State.caso_sel == "resuelto"),
        _aviso("green", "circle-check", "Atendido / Resuelto", rx.cond(State.unidad_sel != "", rx.text.span(" · ", State.unidad_sel), "")),
        rx.cond(
            State.caso_sel == "en_camino",
            _aviso("blue", "siren", "Unidad en camino: ", State.unidad_sel),
            rx.match(
                alerta["estado"],
                ("descartado", rx.text(alerta["despacho"], size="2", color=TEXTO_2)),
                ("confirmado", _aviso("indigo", "send", "Despachado a ", alerta["despacho"], rx.cond(alerta["folio"] != "", rx.text.span(" · acuse ", alerta["folio"]), ""))),
                rx.vstack(_atender(), _mas_acciones(alerta), spacing="3", width="100%"),
            ),
        ),
    )


def modal_validacion() -> rx.Component:
    from .cola import datos_alerta

    alerta = State.alerta_sel
    return rx.dialog.root(
        rx.dialog.content(
            rx.vstack(
                rx.hstack(
                    rx.dialog.title(alerta["tipo_txt"], margin="0", size="4"),
                    rx.hstack(insignia_severidad(alerta), insignia_estado(alerta), spacing="3", align="center"),
                    justify="between",
                    align="center",
                    width="100%",
                ),
                _captura(alerta),
                datos_alerta(alerta),
                _acciones(alerta),
                spacing="4",
                width="100%",
            ),
            max_width="520px",
        ),
        open=State.modal_abierto,
        on_open_change=State.cambiar_modal,
    )
