import reflex as rx

from ..components.layout import pagina
from ..estilos import TEXTO_3, tarjeta, titulo
from ..state import State

_COLUMNAS = ["Fecha y hora", "Actor", "Acción", "Evento", "Detalle", "Folio"]


def _fila(entrada) -> rx.Component:
    return rx.table.row(
        rx.table.cell(entrada["timestamp"], white_space="nowrap"),
        rx.table.cell(entrada["actor"], white_space="nowrap"),
        rx.table.cell(entrada["accion"]),
        rx.table.cell(rx.code(entrada["evento_id"])),
        rx.table.cell(entrada["detalle"]),
        rx.table.cell(rx.cond(entrada["folio"] != "", rx.code(entrada["folio"]), "—")),
    )


def auditoria() -> rx.Component:
    return pagina(
        "/auditoria",
        tarjeta(
            rx.vstack(
                titulo("Bitácora de auditoría", rx.text(State.bitacora.length(), " registros", size="2", color=TEXTO_3)),
                rx.text(
                    "Trazabilidad de cada evento: qué cámara lo detectó, qué operador lo validó y a qué dependencia se despachó.",
                    size="2",
                    color=TEXTO_3,
                ),
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
