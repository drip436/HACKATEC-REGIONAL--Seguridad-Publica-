import reflex as rx

from ..FRONTEND.components.camara import camara_en_vivo
from ..FRONTEND.components.cola import panel_operacion
from ..FRONTEND.components.layout import pagina
from ..FRONTEND.components.mapa import mapa_en_vivo


def operacion() -> rx.Component:
    return pagina(
        "/",
        rx.grid(
            panel_operacion(),
            rx.vstack(
                rx.grid(
                    mapa_en_vivo(),
                    camara_en_vivo(),
                    grid_template_columns=rx.breakpoints(initial="minmax(0, 1fr)", xl="minmax(0, 3fr) minmax(0, 2fr)"),
                    gap="12px",
                    width="100%",
                    align_items="start",
                ),
                spacing="3",
                width="100%",
            ),
            grid_template_columns=rx.breakpoints(initial="minmax(0, 1fr)", lg="340px minmax(0, 1fr)"),
            gap="12px",
            width="100%",
            align_items="start",
        ),
    )
