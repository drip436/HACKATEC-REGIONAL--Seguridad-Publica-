"""Tareas que viven mientras corre la app: llegada de unidades y cierre del sensor."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from starlette.concurrency import run_in_threadpool

from ..realtime import get_manager
from ..services import atenciones
from ..services.vinculacion import SUPERVISOR

LOGGER = logging.getLogger("sentinelops.ciclo")
_INTERVALO_S = 2.0


async def _vigilar_llegadas() -> None:
    while True:
        try:
            for resultado in await run_in_threadpool(atenciones.resolver_llegadas):
                atencion = resultado.atencion
                LOGGER.info("Unidad %s llegó: evento %d resuelto", atencion.unidad, atencion.evento_id)
                await get_manager().broadcast("evento.actualizado", resultado.evento)
                await get_manager().broadcast("atencion.actualizada", atencion)
        except Exception:  # noqa: BLE001 - la vigilancia no debe morir por un error puntual
            LOGGER.exception("Error al resolver llegadas")
        await asyncio.sleep(_INTERVALO_S)


@contextlib.asynccontextmanager
async def ciclo_operativo() -> AsyncIterator[None]:
    tarea = asyncio.create_task(_vigilar_llegadas(), name="sentinelops-llegadas")
    try:
        yield
    finally:
        tarea.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tarea
        # Al apagar o recargar el backend, el sensor lanzado desde el panel se detiene.
        await run_in_threadpool(SUPERVISOR.desvincular)
