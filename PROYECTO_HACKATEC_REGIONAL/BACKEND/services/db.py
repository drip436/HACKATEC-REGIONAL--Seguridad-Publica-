from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import reflex as rx
import sqlalchemy as sa
from sqlmodel import Session, SQLModel

from .. import models  # noqa: F401  (registra las tablas en el metadata)

logger = logging.getLogger("sentinelops.db")

# Un solo escritor por proceso: garantiza que la cadena de hashes de la bitácora
# no se bifurque. Entre procesos (varios workers en PostgreSQL) se usa además un
# advisory lock en services/auditoria.py.
_LOCK_ESCRITURA = threading.RLock()
_LOCK_INIT = threading.Lock()
_inicializada = False

_TRIGGERS_SQLITE = (
    """
    CREATE TRIGGER IF NOT EXISTS trg_bitacora_no_update
    BEFORE UPDATE ON bitacora_auditoria
    BEGIN SELECT RAISE(ABORT, 'bitacora_auditoria es append-only'); END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_bitacora_no_delete
    BEFORE DELETE ON bitacora_auditoria
    BEGIN SELECT RAISE(ABORT, 'bitacora_auditoria es append-only'); END;
    """,
)

_TABLAS = ("camaras_sensores", "eventos_detectados", "despachos_interoperables", "bitacora_auditoria")

_TRIGGERS_POSTGRES = (
    """
    CREATE OR REPLACE FUNCTION fn_bitacora_append_only() RETURNS trigger
    LANGUAGE plpgsql SET search_path = '' AS $$
    BEGIN
        RAISE EXCEPTION 'bitacora_auditoria es append-only';
    END;
    $$;
    """,
    "DROP TRIGGER IF EXISTS trg_bitacora_append_only ON bitacora_auditoria;",
    """
    CREATE TRIGGER trg_bitacora_append_only
    BEFORE UPDATE OR DELETE ON bitacora_auditoria
    FOR EACH ROW EXECUTE FUNCTION fn_bitacora_append_only();
    """,
    # Los triggers por fila no se disparan con TRUNCATE, que vaciaría la bitácora entera.
    "DROP TRIGGER IF EXISTS trg_bitacora_no_truncate ON bitacora_auditoria;",
    """
    CREATE TRIGGER trg_bitacora_no_truncate
    BEFORE TRUNCATE ON bitacora_auditoria
    FOR EACH STATEMENT EXECUTE FUNCTION fn_bitacora_append_only();
    """,
    # Supabase expone el esquema public por su API REST con la llave anon (pública).
    # RLS activado y sin políticas = esa API no ve nada; el backend se conecta como
    # dueño de las tablas y no se ve afectado.
    *(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY;" for tabla in _TABLAS),
)


def inicializar_bd() -> None:
    """Crea tablas y triggers de inmutabilidad. Idempotente.
    Para cambios de esquema posteriores usa `reflex db makemigrations` / `reflex db migrate`."""
    global _inicializada
    with _LOCK_INIT:
        if _inicializada:
            return
        engine = rx.model.get_engine()
        SQLModel.metadata.create_all(engine)
        sentencias = {
            "sqlite": _TRIGGERS_SQLITE,
            "postgresql": _TRIGGERS_POSTGRES,
        }.get(engine.dialect.name, ())
        with engine.begin() as conn:
            for sql in sentencias:
                conn.execute(sa.text(sql))
        if not sentencias:
            logger.warning("Motor %s sin triggers append-only; la bitácora solo queda protegida por la API.",
                           engine.dialect.name)
        _inicializada = True
        logger.info("Base de datos lista (%s).", engine.dialect.name)


@contextmanager
def transaccion() -> Iterator[Session]:
    """Sesión de escritura serializada con commit/rollback automático."""
    with _LOCK_ESCRITURA, rx.session() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


@contextmanager
def lectura() -> Iterator[Session]:
    with rx.session() as session:
        yield session
