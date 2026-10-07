import os
from pathlib import Path

import reflex as rx
from dotenv import load_dotenv

load_dotenv()  # Lee .env; las variables ya definidas en el entorno tienen prioridad.

# El hot reload de Reflex vigila toda la raíz y no ignora imágenes: cada foto de
# evidencia que guarda el sensor reiniciaría el backend (y cortaría los WebSocket).
# Reflex exige que las rutas excluidas existan, así que la carpeta se crea antes.
_RAIZ = Path(__file__).resolve().parent
(_RAIZ / "static" / "capturas").mkdir(parents=True, exist_ok=True)
os.environ.setdefault(
    "REFLEX_HOT_RELOAD_EXCLUDE_PATHS",
    ":".join(nombre for nombre in ("static", "EDGE_AI") if (_RAIZ / nombre).is_dir()),
)


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
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(appearance="dark", accent_color="cyan", gray_color="slate", radius="medium", scaling="100%"),
        ),
    ],
)
