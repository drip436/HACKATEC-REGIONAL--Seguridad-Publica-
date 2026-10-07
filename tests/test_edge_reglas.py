"""Reglas de conducta del Edge AI con escenas sintéticas (esqueletos COCO-17).

Cada escena se reproduce a 10 fps sobre `ThreatAssessor`. Se comprueba tanto lo
que SÍ es un delito (asalto, agresión, secuestro...) como lo que NO debe ponerse
en rojo (manos arriba a solas, dos personas platicando, agacharse un momento).
"""

from __future__ import annotations

import math
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "EDGE_AI"))
np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from sentinelops.detector import Detection, Pose  # noqa: E402
from sentinelops.zone import RestrictedZone, ThreatAssessor, ThreatLevel  # noqa: E402

FPS = 10
PERSONA, CARRO, CUCHILLO = 0, 2, 43


def persona(x: float, y: float = 200, *, alto: float = 300, brazos: str = "abajo", fase: float = 0.0,
            tumbada: bool = False, agachada: bool = False, track: int | None = None) -> Detection:
    """Persona de pie con los pies en (x + ancho/2, y + alto). `brazos`:
    abajo | arriba | derecha | izquierda | golpe (las muñecas oscilan con `fase`)."""
    if tumbada:
        return Detection((int(x), int(y + alto * 0.7), int(x + alto), int(y + alto)), 0.9, PERSONA, track, None)
    ancho = alto * 0.4
    cx = x + ancho / 2
    torso = 0.3 * alto
    hombro_y, cadera_y = y + 0.2 * alto, y + 0.2 * alto + torso
    rodilla_y, tobillo_y = cadera_y + 0.22 * alto, y + 0.95 * alto
    if agachada:
        rodilla_y, tobillo_y = cadera_y + 0.05 * alto, cadera_y + 0.1 * alto
    hi, hd = (cx - 0.2 * ancho, hombro_y), (cx + 0.2 * ancho, hombro_y)
    if brazos == "arriba":
        mi, md = (hi[0], y - 0.05 * alto), (hd[0], y - 0.05 * alto)
    elif brazos == "derecha":
        mi, md = (hi[0], cadera_y), (hd[0] + 1.0 * torso, hombro_y)
    elif brazos == "izquierda":
        mi, md = (hi[0] - 1.0 * torso, hombro_y), (hd[0], cadera_y)
    elif brazos == "golpe":
        alcance = (0.2 + 0.8 * abs(math.sin(fase))) * torso
        mi, md = (hi[0], cadera_y), (hd[0] + alcance, hombro_y + 0.1 * torso)
    else:
        mi, md = (hi[0], cadera_y), (hd[0], cadera_y)
    puntos = [(cx, y + 0.08 * alto)] * 5 + [hi, hd, hi, hd, mi, md,
              (cx - 0.15 * ancho, cadera_y), (cx + 0.15 * ancho, cadera_y),
              (cx - 0.15 * ancho, rodilla_y), (cx + 0.15 * ancho, rodilla_y),
              (cx - 0.15 * ancho, tobillo_y), (cx + 0.15 * ancho, tobillo_y)]
    pose = Pose.from_array(np.array([[px, py, 0.9] for px, py in puntos]))
    alto_caja = (tobillo_y - y) if agachada else alto
    return Detection((int(x), int(y), int(x + ancho), int(y + alto_caja)), 0.9, PERSONA, track, pose)


def objeto(clase: int, x: float, y: float, ancho: float, alto: float) -> Detection:
    return Detection((int(x), int(y), int(x + ancho), int(y + alto)), 0.8, clase, None, None)


def escena(cuadro: Callable[[int, float], list[Detection]], segundos: float) -> list:
    """Reproduce la escena y devuelve la evaluación de cada frame."""
    evaluador = ThreatAssessor(RestrictedZone([(0, 0), (1920, 0), (1920, 1080), (0, 1080)]))
    resultados = []
    for i in range(int(segundos * FPS)):
        t = i / FPS
        resultados.append(evaluador.assess(cuadro(i, t), 100.0 + t))
    return resultados


def peor(resultados: list) -> tuple[ThreatLevel, set[str | None]]:
    nivel = max((r.level for r in resultados), default=ThreatLevel.SAFE)
    return nivel, {r.conducta for r in resultados if r.level == nivel}


# ------------------------------------------------------------- lo que NO es delito


def test_manos_arriba_a_solas_no_es_alerta() -> None:
    nivel, _ = peor(escena(lambda i, t: [persona(500, brazos="arriba", track=1)], 6))
    assert nivel is ThreatLevel.SAFE


def test_dos_personas_platicando_no_es_alerta() -> None:
    nivel, _ = peor(escena(lambda i, t: [persona(500, track=1), persona(620, track=2)], 10))
    assert nivel is ThreatLevel.SAFE


def test_dos_personas_celebrando_con_las_manos_arriba_no_es_alerta() -> None:
    nivel, _ = peor(escena(lambda i, t: [persona(500, brazos="arriba", track=1), persona(600, brazos="arriba", track=2)], 6))
    assert nivel is ThreatLevel.SAFE


def test_caminar_juntos_no_es_alerta() -> None:
    nivel, _ = peor(escena(lambda i, t: [persona(300 + 150 * t, track=1), persona(380 + 150 * t, track=2)], 6))
    assert nivel is ThreatLevel.SAFE


def test_agacharse_un_momento_no_es_alerta() -> None:
    nivel, _ = peor(escena(lambda i, t: [persona(500, agachada=True, track=1)], 2))
    assert nivel is ThreatLevel.SAFE


def test_cuchillo_suelto_lejos_de_todos_no_es_alerta() -> None:
    nivel, _ = peor(escena(lambda i, t: [persona(200, track=1), objeto(CUCHILLO, 1500, 900, 40, 15)], 4))
    assert nivel is ThreatLevel.SAFE


# ------------------------------------------------------------- lo que SÍ es delito


def test_intento_de_asalto_manos_arriba_y_le_apuntan() -> None:
    def cuadro(i: int, t: float) -> list[Detection]:
        return [persona(500, brazos="derecha", track=1), persona(680, brazos="arriba", track=2)]

    resultados = escena(cuadro, 3)
    nivel, conductas = peor(resultados)
    assert nivel is ThreatLevel.DANGER and "intento_asalto" in conductas
    assert resultados[-1].severity == "CRITICA"


def test_asalto_con_arma() -> None:
    def cuadro(i: int, t: float) -> list[Detection]:
        agresor = persona(500, brazos="derecha", track=1)
        return [agresor, persona(680, track=2), objeto(CUCHILLO, 640, 255, 40, 15)]

    nivel, conductas = peor(escena(cuadro, 2))
    assert nivel is ThreatLevel.DANGER and "asalto_con_arma" in conductas


def test_agresion_fisica_por_golpes_repetidos() -> None:
    def cuadro(i: int, t: float) -> list[Detection]:
        return [persona(500, brazos="golpe", fase=i * 1.3, track=1), persona(650, track=2)]

    nivel, conductas = peor(escena(cuadro, 4))
    assert nivel is ThreatLevel.DANGER and "agresion_fisica" in conductas


def test_intento_de_homicidio_golpes_a_persona_en_el_suelo() -> None:
    def cuadro(i: int, t: float) -> list[Detection]:
        return [persona(500, brazos="golpe", fase=i * 1.3, track=1), persona(560, y=300, tumbada=True, track=2)]

    nivel, conductas = peor(escena(cuadro, 4))
    assert nivel is ThreatLevel.DANGER and "intento_homicidio" in conductas


def test_posible_secuestro_arrastre_hacia_un_vehiculo() -> None:
    def cuadro(i: int, t: float) -> list[Detection]:
        dx = 220 * t  # el par avanza ~0.7 alturas de cuerpo por segundo
        return [persona(400 + dx, brazos="derecha", track=1), persona(470 + dx, track=2),
                objeto(CARRO, 1100, 250, 450, 250)]

    nivel, conductas = peor(escena(cuadro, 4))
    assert nivel is ThreatLevel.DANGER and "posible_secuestro" in conductas


def test_persona_sometida_sin_vehiculo() -> None:
    def cuadro(i: int, t: float) -> list[Detection]:
        dx = 220 * t
        return [persona(200 + dx, brazos="derecha", track=1), persona(270 + dx, track=2)]

    nivel, conductas = peor(escena(cuadro, 4))
    assert nivel is ThreatLevel.DANGER and "persona_sometida" in conductas


def test_persona_sospechosa_oculta_o_merodeando() -> None:
    nivel, conductas = peor(escena(lambda i, t: [persona(500, agachada=True, track=1)], 5))
    assert nivel is ThreatLevel.SUSPICIOUS and conductas == {"persona_sospechosa"}
    nivel, conductas = peor(escena(lambda i, t: [persona(500, track=1)], 22))
    assert nivel is ThreatLevel.SUSPICIOUS and conductas == {"persona_sospechosa"}
