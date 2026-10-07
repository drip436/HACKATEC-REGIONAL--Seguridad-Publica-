"""Reglas de amenaza del Edge AI (EDGE_AI/sentinelops/zone.py + detector.py).

Construye esqueletos y cajas a mano: no carga YOLO. Cada prueba simula una
escena cuadro a cuadro con reloj propio para verificar que los gestos exigen
persistencia, el merodeo exige quietud y el altercado exige acercamiento.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "EDGE_AI"))
pytest.importorskip("numpy")
pytest.importorskip("cv2")

from sentinelops import detector as det  # noqa: E402
from sentinelops.zone import RestrictedZone, ThreatAssessor, ThreatRule  # noqa: E402

ANCHO, ALTO = 1280, 720
ZONA = RestrictedZone([(0, 0), (ANCHO - 1, 0), (ANCHO - 1, ALTO - 1), (0, ALTO - 1)])
DT = 0.1


def esqueleto(x: float, pies: float, h: float, *, brazos: str = "abajo", agachada: bool = False) -> det.Pose:
    """Esqueleto COCO-17 de una persona vista de frente. `h` = altura en píxeles."""
    y = {}
    if agachada:
        # Piernas plegadas: hombros->tobillos mide poco más que el torso.
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
    if brazos == "una":  # solo la derecha arriba; la izquierda cae normal
        filas[7] = [x - 28, y["hombros"] + 0.2 * h, 0.9]
        filas[9] = [x - 30, y["hombros"] + 0.4 * h, 0.9]
    return det.Pose.from_array(filas)


def persona(x: float, pies: float = 600, h: float = 200, tid: int = 1, **estilo) -> det.Detection:
    pose = esqueleto(x, pies, h, **estilo)
    alto = 0.62 * h if estilo.get("agachada") else h
    return det.Detection(bbox=(int(x - 30), int(pies - alto), int(x + 30), int(pies)), confidence=0.9, track_id=tid, pose=pose)


def correr(assessor: ThreatAssessor, escena, segundos: float, t0: float = 0.0):
    """Evalúa `escena(t)` cada DT durante `segundos`; devuelve las reglas vistas y el último t."""
    reglas: set[ThreatRule] = set()
    t = t0
    pasos = int(round(segundos / DT))
    for i in range(pasos):
        t = t0 + (i + 1) * DT
        reglas |= set(assessor.assess(escena(t), t).rules)
    return reglas, t


# ---------------------------------------------------------------- gestos


def test_una_mano_arriba_es_un_saludo() -> None:
    assert persona(300, brazos="una").is_hands_up is False
    a = ThreatAssessor(ZONA)
    reglas, _ = correr(a, lambda t: [persona(300, brazos="una")], 3.0)
    assert ThreatRule.HANDS_UP not in reglas


def test_estiron_breve_no_dispara() -> None:
    assert persona(300, brazos="arriba").is_hands_up is True
    a = ThreatAssessor(ZONA)
    reglas, t = correr(a, lambda t: [persona(300, brazos="arriba")], 0.3)
    reglas2, _ = correr(a, lambda t: [persona(300)], 3.0, t0=t)
    assert ThreatRule.HANDS_UP not in reglas | reglas2


def test_rendicion_sostenida_dispara() -> None:
    a = ThreatAssessor(ZONA)
    reglas, _ = correr(a, lambda t: [persona(300, brazos="arriba")], 0.8)
    assert ThreatRule.HANDS_UP in reglas


def _con_munecas_a(pose: det.Pose, fraccion_torso: float, sin_cabeza: bool = False) -> det.Pose:
    filas = [[k.x, k.y, 0.2 if (sin_cabeza and i < 5) else k.confidence] for i, k in enumerate(pose.points)]
    for i in (9, 10):
        filas[i][1] = pose.shoulders_y - fraccion_torso * (pose.torso_height or 0.0)
    return det.Pose.from_array(filas)


def test_manos_arriba_no_depende_de_la_cabeza() -> None:
    pose = persona(300, brazos="arriba").pose
    assert _con_munecas_a(pose, 0.4, sin_cabeza=True).is_hands_up is True  # de espaldas o cortado por arriba
    assert _con_munecas_a(pose, 0.03).is_hands_up is False  # manos al nivel de los hombros: no es rendición


def test_sentado_desde_el_inicio_no_es_agachado() -> None:
    assert persona(300, agachada=True).is_crouching is True  # geometría sí, pero...
    a = ThreatAssessor(ZONA)
    reglas, _ = correr(a, lambda t: [persona(300, agachada=True)], 6.0)
    assert ThreatRule.CROUCHING not in reglas  # ...nunca estuvo de pie


def test_de_pie_y_se_agacha_dispara() -> None:
    a = ThreatAssessor(ZONA)
    reglas, t = correr(a, lambda t: [persona(300)], 3.0)
    assert ThreatRule.CROUCHING not in reglas
    reglas, _ = correr(a, lambda t: [persona(300, agachada=True)], 2.3, t0=t)
    assert ThreatRule.CROUCHING in reglas


def test_agacharse_un_instante_no_dispara() -> None:
    a = ThreatAssessor(ZONA)
    _, t = correr(a, lambda t: [persona(300)], 3.0)
    reglas, t = correr(a, lambda t: [persona(300, agachada=True)], 0.8, t0=t)
    reglas2, _ = correr(a, lambda t: [persona(300)], 3.0, t0=t)
    assert ThreatRule.CROUCHING not in reglas | reglas2


def test_caja_ancha_sin_esqueleto_solo_si_es_horizontal() -> None:
    assert det.Detection(bbox=(0, 0, 100, 90), confidence=0.9).is_crouching is False  # sentado / medio tapado
    assert det.Detection(bbox=(0, 0, 100, 40), confidence=0.9).is_crouching is True  # tumbado


# ---------------------------------------------------------------- merodeo


def test_caminar_despacio_por_la_zona_no_es_merodeo() -> None:
    a = ThreatAssessor(ZONA)
    reglas, _ = correr(a, lambda t: [persona(200 + 40 * t)], 25.0)  # 40 px/s: paseo lento
    assert ThreatRule.LOITERING not in reglas


def test_quedarse_parado_es_merodeo() -> None:
    a = ThreatAssessor(ZONA)
    reglas, _ = correr(a, lambda t: [persona(300)], 15.0)
    assert ThreatRule.LOITERING not in reglas
    reglas, _ = correr(a, lambda t: [persona(300)], 6.0, t0=15.0)
    assert ThreatRule.LOITERING in reglas


# ---------------------------------------------------------------- proximidad


def test_pareja_junta_desde_el_inicio_no_dispara() -> None:
    a = ThreatAssessor(ZONA)
    reglas, _ = correr(a, lambda t: [persona(300, tid=1), persona(320, tid=2)], 10.0)
    assert ThreatRule.PROXIMITY not in reglas


def test_acercamiento_brusco_y_contacto_sostenido_dispara() -> None:
    a = ThreatAssessor(ZONA)
    _, t = correr(a, lambda t: [persona(300, tid=1), persona(700, tid=2)], 4.0)
    reglas, _ = correr(a, lambda t: [persona(300, tid=1), persona(320, tid=2)], 6.5, t0=t)
    assert ThreatRule.PROXIMITY in reglas


def test_grupo_de_cuatro_no_es_altercado() -> None:
    a = ThreatAssessor(ZONA)
    _, t = correr(a, lambda t: [persona(300 + i * 400, tid=i) for i in range(4)], 4.0)
    reglas, _ = correr(a, lambda t: [persona(300 + i * 20, tid=i) for i in range(4)], 8.0, t0=t)
    assert ThreatRule.PROXIMITY not in reglas
