import os

import reflex as rx
from dotenv import load_dotenv

load_dotenv()  # Lee .env; las variables ya definidas en el entorno tienen prioridad.


def _db_url() -> str:
    """DATABASE_URL del .env (p. ej. Supabase) o SQLite local si no está definida.
    Supabase entrega URLs `postgresql://`; se fuerza el driver psycopg (v3) instalado."""
    url = os.getenv("DATABASE_URL", "").strip() or "sqlite:///reflex.db"
    for prefijo in ("postgres://", "postgresql://"):
        if url.startswith(prefijo):
            return "postgresql+psycopg://" + url.removeprefix(prefijo)
    return url


config = rx.Config(
    app_name="PROYECTO_HACKATEC_REGIONAL",
    db_url=_db_url(),
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(),
    ]
)
