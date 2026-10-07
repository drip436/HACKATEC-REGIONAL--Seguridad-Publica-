"""Convierte un video grabado en una cámara de demostración del panel.

Pasa el video UNA vez por el mismo pipeline del sensor (YOLOv8-Pose + reglas de
conducta + HUD), guarda el resultado ya anotado y lo registra en el índice que lee
el backend. El panel lo reproduce en bucle en el mosaico de cámaras. No envía
alertas: para eso está el sensor en vivo (`python -m sentinelops`).

Uso, desde la carpeta EDGE_AI:

    python tools/preprocesar_video.py videos/plaza.mp4 \
        --nombre "Plaza de Armas, Villahermosa" --lat 17.9892 --lng -92.9195

Con ffmpeg instalado el resultado es un .mp4 (H.264), que reproduce cualquier
navegador; sin ffmpeg se guarda un .webm (VP8) con OpenCV.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

_EDGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_EDGE))

from sentinelops import overlay  # noqa: E402
from sentinelops.config import build_config  # noqa: E402
from sentinelops.detector import ThreatDetector  # noqa: E402
from sentinelops.zone import (  # noqa: E402
    PERSON_LOITER_SECONDS,
    PROXIMITY_SECONDS,
    VEHICLE_LOITER_SECONDS,
    RestrictedZone,
    ThreatAssessor,
)

# Misma carpeta que sirve el backend (BACKEND/config.py: videos_dir).
CARPETA_VIDEOS = _EDGE.parent / os.getenv("SENTINEL_VIDEOS_DIR", "static/videos")
INDICE = "camaras.json"


def codigo_camara(nombre: str) -> str:
    """"Plaza de Armas, Villahermosa" -> "CAM-DEMO-PLAZA-DE-ARMAS-VILLAHERMOSA"."""
    plano = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", plano).strip("-").upper()[:40].rstrip("-")
    return f"CAM-DEMO-{slug or 'SIN-NOMBRE'}"


class _Escritor:
    """Codifica los cuadros anotados: ffmpeg (H.264) si está, si no OpenCV (VP8)."""

    def __init__(self, destino_sin_extension: Path, ancho: int, alto: int, fps: float) -> None:
        self._ffmpeg: subprocess.Popen[bytes] | None = None
        self._cv: cv2.VideoWriter | None = None
        if shutil.which("ffmpeg"):
            self.ruta = destino_sin_extension.with_suffix(".mp4")
            self._ffmpeg = subprocess.Popen(  # noqa: S603, S607 (lista de argumentos, sin shell)
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{ancho}x{alto}", "-r", f"{fps:.3f}", "-i", "-",
                    "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
                    # El índice al inicio: el navegador empieza a reproducir sin bajar todo el archivo.
                    "-movflags", "+faststart", "-f", "mp4", str(self.ruta),
                ],
                stdin=subprocess.PIPE,
            )
        else:
            self.ruta = destino_sin_extension.with_suffix(".webm")
            self._cv = cv2.VideoWriter(str(self.ruta), cv2.VideoWriter_fourcc(*"VP80"), fps, (ancho, alto))
            if not self._cv.isOpened():
                raise RuntimeError("OpenCV no pudo crear el .webm. Instala ffmpeg y vuelve a intentar.")

    def escribir(self, cuadro: np.ndarray) -> None:
        if self._ffmpeg is not None:
            try:
                self._ffmpeg.stdin.write(cuadro.tobytes())
            except BrokenPipeError as error:
                raise RuntimeError("ffmpeg se detuvo al codificar (¿tu ffmpeg trae libx264?).") from error
        else:
            self._cv.write(cuadro)

    def cerrar(self) -> None:
        if self._ffmpeg is not None:
            self._ffmpeg.stdin.close()
            if self._ffmpeg.wait() != 0:
                raise RuntimeError("ffmpeg terminó con error; el video no se guardó.")
        else:
            self._cv.release()


def procesar(video: Path, destino_sin_extension: Path, inferir_cada: int) -> tuple[Path, Counter[str], Counter[str]]:
    """Anota el video completo. Devuelve el archivo, los cuadros por nivel y las conductas vistas."""
    config = build_config()
    captura = cv2.VideoCapture(str(video))
    if not captura.isOpened():
        raise RuntimeError(f"No se pudo abrir el video: {video}")
    fps = captura.get(cv2.CAP_PROP_FPS)
    fps = fps if 1.0 <= fps <= 120.0 else 30.0
    total = int(captura.get(cv2.CAP_PROP_FRAME_COUNT))
    ancho, alto = config.frame_width, config.frame_height

    print("-> Inicializando IA (YOLOv8-Pose + COCO: persona, vehiculo, arma)...")
    detector = ThreatDetector(
        pose_model_path=config.pose_model_path,
        object_model_path=config.object_model_path or None,
        conf_threshold=config.conf_threshold,
        weapon_conf_threshold=config.weapon_conf_threshold,
        vehicle_conf_threshold=config.vehicle_conf_threshold,
        track=config.enable_tracking,
    )
    # Todo el cuadro es la zona vigilada, igual que una cámara vinculada desde el panel.
    zona = RestrictedZone(((0, 0), (ancho - 1, 0), (ancho - 1, alto - 1), (0, alto - 1)))
    evaluador = ThreatAssessor(
        zone=zona,
        person_loiter_seconds=PERSON_LOITER_SECONDS,
        vehicle_loiter_seconds=VEHICLE_LOITER_SECONDS,
        proximity_seconds=PROXIMITY_SECONDS,
    )

    escritor = _Escritor(destino_sin_extension, ancho, alto, fps)
    niveles: Counter[str] = Counter()
    conductas: Counter[str] = Counter()
    evaluacion = None
    indice = 0
    try:
        while True:
            ok, cuadro = captura.read()
            if not ok or cuadro is None:
                break
            if cuadro.shape[1] != ancho or cuadro.shape[0] != alto:
                cuadro = cv2.resize(cuadro, (ancho, alto))
            # El reloj de las reglas (merodeo, proximidad) es el del video, no el de esta máquina:
            # así el resultado no depende de qué tan rápido procese.
            ahora = indice / fps
            if indice % inferir_cada == 0 or evaluacion is None:
                evaluacion = evaluador.assess(detector.detect(cuadro), ahora)
            escritor.escribir(overlay.annotate(cuadro, zona, evaluacion, fps, 0.0))
            niveles[evaluacion.level.name.lower()] += 1
            if evaluacion.is_alertable:
                conductas[evaluacion.reason] += 1
            indice += 1
            if total and indice % max(1, total // 10) == 0:
                print(f"   {100 * indice // total:3d}%  ({indice}/{total} cuadros)")
    finally:
        captura.release()
        escritor.cerrar()
    if indice == 0:
        escritor.ruta.unlink(missing_ok=True)
        raise RuntimeError("El video no tiene cuadros legibles.")
    return escritor.ruta, niveles, conductas


def registrar(carpeta: Path, camara_id: str, nombre: str, lat: float, lng: float, video: str) -> None:
    """Agrega (o reemplaza) la cámara en el índice que lee el backend."""
    ruta = carpeta / INDICE
    try:
        camaras = json.loads(ruta.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        camaras = []
    camaras = [c for c in camaras if isinstance(c, dict) and c.get("id") != camara_id]
    camaras.append({"id": camara_id, "nombre": nombre, "lat": lat, "lng": lng, "video": video})
    ruta.write_text(json.dumps(camaras, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Anota un video con el Edge AI y lo publica como cámara de demostración.")
    parser.add_argument("video", type=Path, help="Video grabado (mp4, mov, avi…).")
    parser.add_argument("--nombre", required=True, help="Lugar que vigila la cámara.")
    parser.add_argument("--lat", type=float, required=True, help="Latitud de la cámara (punto en el mapa).")
    parser.add_argument("--lng", type=float, required=True, help="Longitud de la cámara.")
    parser.add_argument("--id", dest="camara_id", help="Código de la cámara (por defecto se deriva del nombre).")
    parser.add_argument("--cada", type=int, default=1, help="Inferencia 1 de cada N cuadros (1 = todos; más rápido con 2 o 3).")
    parser.add_argument("--salida", type=Path, default=CARPETA_VIDEOS, help=f"Carpeta de videos (por defecto {CARPETA_VIDEOS}).")
    args = parser.parse_args(argv)

    if not (-90.0 <= args.lat <= 90.0 and -180.0 <= args.lng <= 180.0):
        parser.error("--lat/--lng fuera de rango")
    if args.cada < 1:
        parser.error("--cada debe ser 1 o más")
    camara_id = args.camara_id or codigo_camara(args.nombre)
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,60}", camara_id):
        parser.error("--id solo admite letras, números, guion y guion bajo (3 a 60 caracteres)")

    args.salida.mkdir(parents=True, exist_ok=True)
    try:
        # Se anota en un archivo temporal: el panel nunca reproduce un video a medias.
        temporal, niveles, conductas = procesar(args.video, args.salida / f".{camara_id}.tmp", args.cada)
    except RuntimeError as error:
        print(f"❌ {error}")
        return 1
    final = args.salida / f"{camara_id}{temporal.suffix}"
    for anterior in (args.salida / f"{camara_id}.mp4", args.salida / f"{camara_id}.webm"):
        anterior.unlink(missing_ok=True)
    temporal.replace(final)
    registrar(args.salida, camara_id, args.nombre, args.lat, args.lng, final.name)

    total = sum(niveles.values())
    print(f"✅ {final}  ({final.stat().st_size / 1_048_576:.1f} MB, {total} cuadros)")
    print("   Niveles: " + ", ".join(f"{nivel} {100 * n // total}%" for nivel, n in niveles.most_common()))
    if conductas:
        print("   Conductas detectadas: " + "; ".join(conducta for conducta, _ in conductas.most_common()))
    else:
        print("   El modelo no marcó ninguna conducta de riesgo en este video.")
    print(f"   Cámara '{camara_id}' registrada en {args.salida / INDICE}. Recarga el panel para verla.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
