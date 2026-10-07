"""Geometría de gestos del detector (EDGE_AI/sentinelops/detector.py) y su efecto
sobre el motor de conductas.

Complementa a `test_edge_reglas.py`: aquí se prueba qué cuenta como "manos
arriba" o "agachado" antes de llegar a las reglas, y que un gesto inocente no
se convierte en delito al pasar por `ThreatAssessor`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "EDGE_AI"))
pytest.importorskip("numpy")
pytest.importorskip("cv2")

from sentinelops import detector as det  # noqa: E402
from sentinelops.zone import RestrictedZone, ThreatAssessor, ThreatLevel  # noqa: E402

ZONA = RestrictedZone([(0, 0), (1279, 0), (1279, 719), (0, 719)])
DT = 0.1


def esqueleto(x: float, pies: float, h: float, *, brazos: str = "abajo", agachada: bool = False) -> det.Pose:
    """Esqueleto COCO-17 visto de frente. `brazos`: abajo | arriba | una (solo la derecha)."""
    y = {}
    if agachada:
        y.update(cabeza=pies - 0.62 * h, hombros=pies - 0.5 * h, caderas=pies - 0.1 * h, rodillas=pies - 0.05 * h)
    else:
        y.update(cabeza=pies - h, hombros=pies - 0.85 * h, caderas=pies - 0.5 * h, rodillas=pies - 0.25 * h)
    y["codos"], y["munecas"] = y["hombros"] + 0.2 * h, y["hombros"] + 0.4 * h
    if brazos in ("arriba", "una"):
        y["codos"], y["munecas"] = y["hombros"] - 0.1 * h, y["cabeza"] - 0.15 * h
    puntos = [
        (x, y["cabeza"]), (x - 5, y["cabeza"]), (x + 5, y["cabeza"]), (x - 10, y["cabeza"]), (x + 10, y["cabeza"]),
        (x - 20, y["hombros"]), (x + 20, y["hombros"]),
        (x - 28, y["codos"]), (x + 28, y["codos"]),
        (x - 30, y["munecas"]), (x + 30, y["munecas"]),
        (x - 12, y["caderas"]), (x + 12, y["caderas"]),
        (x - 12, y["rodillas"]), (x + 12, y["rodillas"]),
        (x - 12, pies), (x + 12, pies),
    ]
    filas = [[px, py, 0.9] for px, py in puntos]
    if brazos == "una":  # el brazo izquierdo cae normal
        filas[7] = [x - 28, y["hombros"] + 0.2 * h, 0.9]
        filas[9] = [x - 30, y["hombros"] + 0.4 * h, 0.9]
    return det.Pose.from_array(filas)


def persona(x: float, pies: float = 600, h: float = 200, tid: int = 1, **estilo) -> det.Detection:
    alto = 0.62 * h if estilo.get("agachada") else h
    caja = (int(x - 30), int(pies - alto), int(x + 30), int(pies))
    return det.Detection(bbox=caja, confidence=0.9, track_id=tid, pose=esqueleto(x, pies, h, **estilo))


def peor(escena, segundos: float) -> tuple[ThreatLevel, set[str | None]]:
    evaluador = ThreatAssessor(ZONA)
    resultados = [evaluador.assess(escena((i + 1) * DT), (i + 1) * DT) for i in range(int(round(segundos / DT)))]
    nivel = max(r.level for r in resultados)
    return nivel, {r.conducta for r in resultados if r.level == nivel}


def _con(pose: det.Pose, *, munecas_a: float | None = None, sin: tuple[int, ...] = ()) -> det.Pose:
    """Copia de `pose` con las muñecas a `munecas_a` torsos sobre los hombros y/o articulaciones sin certeza."""
    filas = [[k.x, k.y, 0.2 if i in sin else k.confidence] for i, k in enumerate(pose.points)]
    if munecas_a is not None:
        for i in (det.LEFT_WRIST, det.RIGHT_WRIST):
            filas[i][1] = pose.shoulders_y - munecas_a * (pose.torso_height or 0.0)
    return det.Pose.from_array(filas)


# ---------------------------------------------------------------- manos arriba


def test_una_sola_mano_no_es_manos_arriba() -> None:
    assert persona(300, brazos="una").is_hands_up is False


def test_las_dos_manos_arriba_si() -> None:
    assert persona(300, brazos="arriba").is_hands_up is True


def test_manos_a_la_altura_de_la_cara_cuentan_aunque_no_se_vea_la_cabeza() -> None:
    pose = persona(300, brazos="arriba").pose
    cabeza = (det.NOSE, det.LEFT_EYE, det.RIGHT_EYE, det.LEFT_EAR, det.RIGHT_EAR)
    assert _con(pose, munecas_a=0.4, sin=cabeza).is_hands_up is True  # de espaldas o cortado por arriba


def test_manos_al_nivel_de_los_hombros_no_cuentan() -> None:
    assert _con(persona(300, brazos="arriba").pose, munecas_a=0.03).is_hands_up is False


def test_munecas_sin_certeza_no_cuentan() -> None:
    pose = persona(300, brazos="arriba").pose
    assert _con(pose, sin=(det.LEFT_WRIST,)).is_hands_up is False


# ---------------------------------------------------------------- agachado


def test_piernas_plegadas_es_agachado() -> None:
    assert persona(300, agachada=True).is_crouching is True
    assert persona(300).is_crouching is False


def test_sin_caderas_visibles_no_se_decide() -> None:
    pose = persona(300, agachada=True).pose
    assert _con(pose, sin=(det.LEFT_HIP, det.RIGHT_HIP)).is_crouching is False  # cortado por el borde o tapado


def test_caja_sin_esqueleto_solo_cuenta_si_es_horizontal() -> None:
    assert det.Detection(bbox=(0, 0, 100, 90), confidence=0.9).is_crouching is False  # sentado o medio tapado
    assert det.Detection(bbox=(0, 0, 100, 40), confidence=0.9).is_crouching is True  # tumbado


# ---------------------------------------------------------------- efecto en las conductas


def test_saludar_con_una_mano_junto_a_un_amigo_no_es_asalto() -> None:
    nivel, _ = peor(lambda t: [persona(300, tid=1, brazos="una"), persona(330, tid=2)], 4)
    assert nivel is ThreatLevel.SAFE


def test_caja_ancha_sin_esqueleto_no_es_persona_ocultandose() -> None:
    nivel, _ = peor(lambda t: [det.Detection(bbox=(300, 400, 400, 490), confidence=0.9, track_id=1)], 6)
    assert nivel is ThreatLevel.SAFE


def test_dos_manos_arriba_con_otra_persona_encima_sigue_siendo_asalto() -> None:
    nivel, conductas = peor(lambda t: [persona(300, tid=1, brazos="arriba"), persona(330, tid=2)], 3)
    assert nivel is ThreatLevel.DANGER and "intento_asalto" in conductas
