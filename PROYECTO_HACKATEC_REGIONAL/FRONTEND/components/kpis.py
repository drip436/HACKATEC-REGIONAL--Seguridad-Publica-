"""Mosaicos de conteo: el turno (alertas) y lo que ve la cámara ahora."""

import reflex as rx

from ...estilos import ACENTO, COLOR_ESTADO, COLOR_SEVERIDAD, mosaico
from ...state import State


def mosaicos_turno() -> rx.Component:
    return rx.grid(
        mosaico("bell", COLOR_ESTADO["pendiente"], "Pendientes", State.total_pendientes),
        mosaico("siren", COLOR_SEVERIDAD["critica"], "Críticas", State.total_criticas),
        mosaico("circle-check", COLOR_ESTADO["resuelto"], "Resueltas", State.total_resueltas),
        mosaico("cctv", "#52525b", "Cámaras", State.camaras_activas),
        columns="2",
        spacing="2",
        width="100%",
    )


def mosaicos_camara() -> rx.Component:
    return rx.grid(
        mosaico("user", ACENTO, "Personas", State.edge_personas),
        mosaico("gauge", "#52525b", "Procesamiento", State.edge_fps.to_string(), "fps"),
        columns="2",
        spacing="2",
        width="100%",
    )
