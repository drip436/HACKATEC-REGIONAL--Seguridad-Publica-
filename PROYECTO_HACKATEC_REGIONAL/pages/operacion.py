import reflex as rx

from ..FRONTEND.components.camara import camara_en_vivo
from ..FRONTEND.components.kpis import fila_kpis
from ..FRONTEND.components.layout import pagina
from ..FRONTEND.components.mapa import mapa_en_vivo
from ..FRONTEND.components.mosaico import mosaico_cctv


def operacion() -> rx.Component:
    return pagina(
        "/",
        rx.grid(
            rx.vstack(camara_en_vivo(), mosaico_cctv(), spacing="4", width="100%"),
            rx.vstack(mapa_en_vivo(), fila_kpis(), spacing="4", width="100%"),
            grid_template_columns=rx.breakpoints(initial="minmax(0, 1fr)", lg="minmax(0, 5fr) minmax(0, 6fr)"),
            gap="1rem",
            width="100%",
            align_items="start",
        ),
    )
