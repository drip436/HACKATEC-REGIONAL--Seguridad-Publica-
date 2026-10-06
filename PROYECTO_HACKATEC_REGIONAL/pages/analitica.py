import reflex as rx

from ..components.graficas import eventos_por_hora, filtros, matriz_semanal, rondines_sugeridos
from ..components.layout import pagina
from ..components.mapa import mapa_de_calor


def analitica() -> rx.Component:
    return pagina(
        "/analitica",
        filtros(),
        rx.grid(
            mapa_de_calor(),
            rondines_sugeridos(),
            eventos_por_hora(),
            matriz_semanal(),
            grid_template_columns=rx.breakpoints(initial="minmax(0, 1fr)", lg="minmax(0, 3fr) minmax(0, 2fr)"),
            gap="1rem",
            width="100%",
            align_items="start",
        ),
    )
