"""Cámaras de demostración: videos grabados que el Edge AI ya anotó.

`EDGE_AI/tools/preprocesar_video.py` pasa cada video una vez por el modelo, guarda el
resultado en la carpeta de videos y lo registra en `camaras.json`. Aquí solo se lee
ese índice: no se lanza ningún sensor ni se generan alertas.
"""

from __future__ import annotations

import json
import logging
import re

from ..config import get_settings
from ..schemas import CamaraDemoOut

LOGGER = logging.getLogger("sentinelops.camaras_demo")

INDICE = "camaras.json"
PREFIJO_URL = "/static/videos"
# Solo nombres planos de video: el índice no puede apuntar fuera de la carpeta.
NOMBRE_VALIDO = re.compile(r"^[A-Za-z0-9_.-]+\.(mp4|webm)$")


def listar() -> list[CamaraDemoOut]:
    """Cámaras del índice cuyo video existe. Sin índice (o ilegible) no hay ninguna."""
    carpeta = get_settings().videos_dir
    try:
        entradas = json.loads((carpeta / INDICE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as error:
        LOGGER.warning("No se pudo leer %s: %s", carpeta / INDICE, error)
        return []

    camaras: list[CamaraDemoOut] = []
    for entrada in entradas if isinstance(entradas, list) else []:
        try:
            video = str(entrada["video"])
            if not NOMBRE_VALIDO.match(video) or not (carpeta / video).is_file():
                raise ValueError(f"video no disponible: {video}")
            camaras.append(
                CamaraDemoOut(
                    id=str(entrada["id"]),
                    nombre=str(entrada["nombre"]),
                    lat=float(entrada["lat"]),
                    lng=float(entrada["lng"]),
                    video_url=f"{PREFIJO_URL}/{video}",
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            LOGGER.warning("Entrada de %s ignorada (%s)", INDICE, error)
    return camaras
