"""Colisión vehicular y atropello (EDGE_AI/sentinelops/zone.py).

Trayectorias sintéticas de cajas con tracking, cuadro a cuadro con reloj
propio. Un choque exige acercamiento, contacto, frenada en seco y quedar
quietos; cruzarse o estacionarse no lo cumplen.
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

ZONA = RestrictedZone([(0, 0), (1279, 0), (1279, 719), (0, 719)])
DT = 0.1
ANCHO_CARRO, ALTO_CARRO = 120, 80


def carro(x: float, tid: int, pies: float = 600) -> det.Detection:
    return det.Detection(
        bbox=(int(x - ANCHO_CARRO / 2), int(pies - ALTO_CARRO), int(x + ANCHO_CARRO / 2), int(pies)),
        confidence=0.9,
        class_id=det.CAR_CLASS_ID,
        track_id=tid,
    )


def persona(x: float, tid: int, h: float = 160, pies: float = 600) -> det.Detection:
    return det.Detection(bbox=(int(x - 20), int(pies - h), int(x + 20), int(pies)), confidence=0.9, track_id=tid)


def correr(assessor: ThreatAssessor, escena, segundos: float, t0: float = 0.0):
    reglas: set[ThreatRule] = set()
    t = t0
    for i in range(int(round(segundos / DT))):
        t = t0 + (i + 1) * DT
        reglas |= set(assessor.assess(escena(t), t).rules)
    return reglas, t


def frenada(t: float, x0: float, v: float, t_freno: float, dur: float) -> float:
    """Posición de un móvil a `v` px/s que frena linealmente hasta 0 entre t_freno y t_freno+dur."""
    if t <= t_freno:
        return x0 + v * t
    if t >= t_freno + dur:
        return x0 + v * t_freno + v * dur / 2
    tau = t - t_freno
    return x0 + v * t_freno + v * tau - v * tau * tau / (2 * dur)


# ---------------------------------------------------------------- colisión vehicular


def test_cruzarse_sin_frenar_no_es_choque() -> None:
    a = ThreatAssessor(ZONA)
    reglas, _ = correr(a, lambda t: [carro(100 + 240 * t, 1), carro(900 - 240 * t, 2)], 5.0)
    assert ThreatRule.VEHICLE_COLLISION not in reglas


def test_estacionarse_despacio_junto_a_otro_no_es_choque() -> None:
    a = ThreatAssessor(ZONA)
    # Llega a 2 anchos/s y frena durante 3 s hasta quedar solapado con el estacionado.
    reglas, _ = correr(a, lambda t: [carro(frenada(t, 100, 240, 0.2, 3.0), 1), carro(560, 2)], 8.0)
    assert ThreatRule.VEHICLE_COLLISION not in reglas


def test_dos_estacionados_solapados_no_es_choque() -> None:
    a = ThreatAssessor(ZONA)
    reglas, _ = correr(a, lambda t: [carro(500, 1), carro(560, 2)], 6.0)
    assert ThreatRule.VEHICLE_COLLISION not in reglas


def test_frenada_en_seco_sobre_otro_y_quedar_quietos_es_choque() -> None:
    a = ThreatAssessor(ZONA)
    # Llega a 2 anchos/s, frena en 0.3 s al tocar al estacionado y ambos quedan quietos.
    reglas, _ = correr(a, lambda t: [carro(frenada(t, 100, 240, 1.7, 0.3), 1), carro(600, 2)], 6.0)
    assert ThreatRule.VEHICLE_COLLISION in reglas


def test_el_choque_avisa_tras_el_tiempo_de_quietud() -> None:
    a = ThreatAssessor(ZONA, collision_hold_seconds=1.0)
    escena = lambda t: [carro(frenada(t, 100, 240, 1.7, 0.3), 1), carro(600, 2)]  # noqa: E731
    reglas, t = correr(a, escena, 2.3)
    assert ThreatRule.VEHICLE_COLLISION not in reglas  # recién se detuvo
    reglas, _ = correr(a, escena, 1.5, t0=t)
    assert ThreatRule.VEHICLE_COLLISION in reglas


def test_alcance_lento_que_empuja_al_estacionado_es_choque() -> None:
    a = ThreatAssessor(ZONA)

    def escena(t: float):
        # Llega despacio (0.5 anchos/s), toca al estacionado a los ~7.3 s y lo empuja 15 px.
        x = frenada(t, 100, 60, 7.3, 0.4)
        empujado = 600 if t < 7.3 else 600 + min(15.0, 50 * (t - 7.3))
        return [carro(x, 1), carro(empujado, 2)]

    reglas, _ = correr(a, escena, 10.0)
    assert ThreatRule.VEHICLE_COLLISION in reglas


def test_frenar_despacio_junto_a_otro_sin_moverlo_no_es_choque() -> None:
    a = ThreatAssessor(ZONA)
    # Mismo acercamiento lento, pero frena en 1.5 s y el otro no se mueve: estacionarse.
    reglas, _ = correr(a, lambda t: [carro(frenada(t, 100, 60, 6.5, 1.5), 1), carro(600, 2)], 10.0)
    assert ThreatRule.VEHICLE_COLLISION not in reglas


# ---------------------------------------------------------------- atropello


def test_persona_junto_a_carro_estacionado_no_es_atropello() -> None:
    a = ThreatAssessor(ZONA)
    reglas, _ = correr(a, lambda t: [carro(600, 1), persona(650, 2)], 6.0)
    assert ThreatRule.PEDESTRIAN_HIT not in reglas


def test_conductor_visible_no_es_atropello() -> None:
    a = ThreatAssessor(ZONA)
    # La persona siempre estuvo dentro de la caja del carro en movimiento.
    reglas, _ = correr(a, lambda t: [carro(100 + 240 * t, 1), persona(100 + 240 * t, 2, h=60)], 4.0)
    assert ThreatRule.PEDESTRIAN_HIT not in reglas


def test_vehiculo_en_movimiento_que_derriba_a_una_persona_es_atropello() -> None:
    a = ThreatAssessor(ZONA)

    def escena(t: float):
        x = frenada(t, 100, 240, 2.4, 0.3)  # frena en seco al llegar a la persona
        altura = 160 if t < 2.4 else max(70.0, 160 - 300 * (t - 2.4))  # la persona cae
        return [carro(x, 1), persona(700, 2, h=altura)]

    reglas, _ = correr(a, escena, 5.0)
    assert ThreatRule.PEDESTRIAN_HIT in reglas


def test_persona_que_cruza_delante_sin_contacto_no_es_atropello() -> None:
    a = ThreatAssessor(ZONA)
    # Peatón pasa por delante del carro (solape en perspectiva) y sigue caminando; el carro no frena.
    reglas, _ = correr(a, lambda t: [carro(100 + 240 * t, 1), persona(400 + 60 * t, 2)], 5.0)
    assert ThreatRule.PEDESTRIAN_HIT not in reglas
