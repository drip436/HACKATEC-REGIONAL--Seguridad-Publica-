"""Línea de tiempo de colisiones sobre un video: qué vehículos ve el sensor, qué
parejas entran en contacto y por qué (no) dispara la regla. Sirve para calibrar
los umbrales COLLISION_* de zone.py con un clip real:

    cd EDGE_AI
    python tools/diag_colisiones.py mi_choque.mp4          # 1 de cada 3 frames, 320 px (como el sensor)
    python tools/diag_colisiones.py mi_choque.mp4 1 640    # todos los frames, 640 px (perfil GPU)
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sentinelops.detector import ThreatDetector  # noqa: E402
from sentinelops.zone import (  # noqa: E402
    COLLISION_HOLD_SECONDS,
    COLLISION_PRE_SECONDS,
    COLLISION_STILL_FACTOR,
    RestrictedZone,
    ThreatAssessor,
    ThreatRule,
)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    video = sys.argv[1]
    cada = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    imgsz = int(sys.argv[3]) if len(sys.argv) > 3 else 320
    detector = ThreatDetector(imgsz=imgsz, track=True)
    assessor = ThreatAssessor(RestrictedZone([(0, 0), (1279, 0), (1279, 719), (0, 719)]))
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    fps = fps if 1 <= fps <= 120 else 30.0
    n = frames_veh = max_veh = 0
    alertas: set[tuple[float, str]] = set()
    ultimo_log = -9.0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        n += 1
        if n % cada:
            continue
        t = n / fps
        detections = detector.detect(cv2.resize(frame, (1280, 720)))
        vehiculos = [d for d in detections if d.is_vehicle]
        max_veh = max(max_veh, len(vehiculos))
        frames_veh += bool(vehiculos)
        for signal in assessor.assess(detections, t).signals:
            if signal.rule in (ThreatRule.VEHICLE_COLLISION, ThreatRule.PEDESTRIAN_HIT):
                alertas.add((round(t, 1), signal.rule.name))
        crashes = assessor._crashes  # noqa: SLF001 (herramienta de diagnóstico)
        if crashes and t - ultimo_log >= 0.5:
            ultimo_log = t
            historial = assessor._history  # noqa: SLF001
            for key, contact in crashes.items():
                a, b = key[6:].split("|")
                va = historial.speed(a, COLLISION_PRE_SECONDS, 0.0, t)
                vb = historial.speed(b, COLLISION_PRE_SECONDS, 0.0, t)
                quietos = all(historial.is_still(k, COLLISION_HOLD_SECONDS, COLLISION_STILL_FACTOR, t) for k in (a, b))
                previa = {k: round(v, 2) for k, v in contact.pre_speed.items()}
                print(
                    f"t={t:6.1f}s vehículos={len(vehiculos)} contacto {a}|{b} desde {t - contact.started_at:4.1f}s "
                    f"acercamiento={contact.approached} impacto={contact.impact} quietos={quietos} "
                    f"v_previa={previa} v_ahora={va and round(va, 2)},{vb and round(vb, 2)}"
                )
    print(f"\nframes={n} evaluados={n // cada} fps={fps:.0f} | frames con vehículo={frames_veh} | máx. vehículos a la vez={max_veh}")
    print("alertas:", sorted(alertas) or "NINGUNA")
    if not frames_veh:
        print("El detector no vio ningún vehículo: revisa encuadre/resolución (prueba 640) o si son carritos a escala.")


if __name__ == "__main__":
    main()
