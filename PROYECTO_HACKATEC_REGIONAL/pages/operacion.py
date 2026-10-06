import reflex as rx

from ..FRONTEND.components.cola import cola_operativa, panel_seleccion
from ..FRONTEND.components.kpis import fila_kpis
from ..FRONTEND.components.layout import pagina
from ..FRONTEND.components.mapa import mapa_en_vivo


def operacion() -> rx.Component:
    return pagina(
        "/",
        fila_kpis(),
        rx.grid(
            mapa_en_vivo(),
            rx.vstack(panel_seleccion(), cola_operativa(), spacing="4", width="100%"),
            grid_template_columns=rx.breakpoints(initial="minmax(0, 1fr)", lg="minmax(0, 2fr) minmax(0, 1fr)"),
            gap="1rem",
            width="100%",
            align_items="start",
        ),
    )
