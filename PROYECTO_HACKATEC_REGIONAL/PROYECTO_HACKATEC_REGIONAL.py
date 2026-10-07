"""SentinelOps: panel de supervisión (Dashboard C4)."""

import reflex as rx

from .BACKEND import ciclo_operativo, crear_api, inicializar_bd
from .pages.analitica import analitica
from .pages.auditoria import auditoria
from .pages.operacion import operacion
from .state import State

app = rx.App(api_transformer=crear_api())
app.register_lifespan_task(inicializar_bd)
app.register_lifespan_task(ciclo_operativo)
app.add_page(operacion, route="/", title="SentinelOps · Operación", on_load=State.iniciar)
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
