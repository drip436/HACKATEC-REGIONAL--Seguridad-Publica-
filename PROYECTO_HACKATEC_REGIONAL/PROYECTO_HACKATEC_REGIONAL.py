"""SentinelOps: panel de supervisión (Dashboard C4)."""

import reflex as rx

from .BACKEND import ciclo_operativo, crear_api, inicializar_bd
from .estado_ui import EstadoUI
from .pages.analitica import analitica
from .pages.auditoria import auditoria
from .pages.operacion import operacion
from .state import State

app = rx.App(
    api_transformer=crear_api(),
    stylesheets=[
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap",
        "/sentinel.css",
    ],
)
app.register_lifespan_task(inicializar_bd)
app.register_lifespan_task(ciclo_operativo)
app.add_page(
    operacion,
    route="/",
    title="SentinelOps · Operación",
    on_load=[State.iniciar, EstadoUI.cargar_camaras_demo],
)
app.add_page(
    analitica,
    route="/analitica",
    title="SentinelOps · Analítica",
    on_load=[State.iniciar, State.cargar_historico],
)
app.add_page(
    auditoria,
    route="/auditoria",
    title="SentinelOps · Auditoría",
    on_load=[State.iniciar, State.cargar_bitacora],
)
