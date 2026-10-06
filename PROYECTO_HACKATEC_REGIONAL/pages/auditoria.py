import reflex as rx

from ..FRONTEND.components.layout import pagina
from ..estilos import TEXTO_2, TEXTO_3, tarjeta, titulo
from ..state import State

_COLUMNAS = ["Fecha y hora", "Actor", "Acción", "Entidad", "Detalle", "Sello"]


def _fila(entrada) -> rx.Component:
    return rx.table.row(
        rx.table.cell(entrada["timestamp"], white_space="nowrap"),
        rx.table.cell(entrada["actor"]),
        rx.table.cell(entrada["accion"], white_space="nowrap"),
        rx.table.cell(entrada["entidad"]),
        rx.table.cell(entrada["detalle"], max_width="420px", style={"overflowWrap": "anywhere"}),
        rx.table.cell(rx.cond(entrada["sello"] != "", rx.code(entrada["sello"]), "—")),
    )


def auditoria() -> rx.Component:
    return pagina(
        "/auditoria",
        tarjeta(
            rx.vstack(
                titulo(
                    "Bitácora de auditoría",
                    rx.hstack(
                        rx.button("Actualizar", on_click=State.cargar_bitacora, variant="soft", color_scheme="gray"),
                        rx.button("Verificar integridad", on_click=State.verificar_bitacora, variant="soft"),
                        spacing="2",
                    ),
                ),
                rx.text(
                    "Trazabilidad de cada evento: qué sensor lo detectó, qué operador lo validó y a qué dependencia "
                    "se despachó. Los registros están encadenados por hash; el sello es el inicio de ese hash.",
                    size="2",
                    color=TEXTO_3,
                ),
                rx.cond(State.integridad != "", rx.text(State.integridad, size="2", color=TEXTO_2, font_weight="600")),
                rx.text(State.bitacora.length(), " registros mostrados (los más recientes primero)", size="1", color=TEXTO_3),
                rx.box(
                    rx.table.root(
                        rx.table.header(rx.table.row(*[rx.table.column_header_cell(c) for c in _COLUMNAS])),
                        rx.table.body(rx.foreach(State.bitacora, _fila)),
                        variant="surface",
                        size="1",
                        width="100%",
                    ),
                    width="100%",
                    overflow_x="auto",
                ),
                spacing="3",
                width="100%",
            )
        ),
    )
