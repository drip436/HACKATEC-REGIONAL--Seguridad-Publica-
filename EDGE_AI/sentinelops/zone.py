"""Geometría de la zona vigilada y máquina de estados de amenaza.

Cinco reglas se evalúan por frame sobre el polígono calibrado:

  1. Vehículo de espera   -> AMARILLO (vehículo >10 s dentro de la zona)
  2. Merodeo              -> AMARILLO (persona >4 s dentro de la zona)
  3. Ocultamiento         -> ROJO     (persona agachada dentro de la zona)
  4. Asalto inminente     -> ROJO     (arma en el frame, o manos arriba)
  5. Acoso físico         -> ROJO     (dos personas pegadas >4 s en la zona)
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import median
from enum import Enum, IntEnum
from itertools import combinations

import cv2
import numpy as np

from .detector import Detection

# --- Umbrales temporales de las reglas -------------------------------------
PERSON_LOITER_SECONDS: float = 20.0
VEHICLE_LOITER_SECONDS: float = 30.0
PROXIMITY_SECONDS: float = 6.0
# Un gesto cuenta solo si la misma persona lo sostiene este tiempo. Manos
# arriba: solo antiparpadeo (en el video de demo el gesto dura ~1 s, y con
# inferencia 1 de cada 3 frames se ve ~0.7 s). Agacharse: un recogido de
# suelo dura menos de 2 s; un ocultamiento, más.
HANDS_UP_HOLD_SECONDS: float = 0.5
CROUCH_HOLD_SECONDS: float = 2.0
# El arma (y la postura) aparecen y desaparecen entre frames; sostener el
# ROJO unos segundos evita el parpadeo del semáforo.
DANGER_HOLD_SECONDS: float = 2.0
# Tolerancia a huecos de detección: un objeto que se pierde menos de esto no
# reinicia su cronómetro de permanencia.
TRACK_GRACE_SECONDS: float = 1.0

# --- Umbrales de la heurística de proximidad -------------------------------
# Superposición mínima (intersección sobre la caja menor) para considerar
# invasión del espacio personal.
PROXIMITY_OVERLAP_RATIO: float = 0.50
# O bien centroides a menos de esta fracción del ancho medio de los bboxes:
# escala con la distancia a la cámara, al contrario que un umbral en píxeles.
PROXIMITY_DISTANCE_FACTOR: float = 0.60

# IoU mínimo para reasignar la identidad de un frame al siguiente cuando el
# tracker de Ultralytics no entrega `track_id`.
IDENTITY_MIN_IOU: float = 0.25

# --- Historial por identidad (quietud, caída de altura, acercamiento) --------
HISTORY_SECONDS: float = 10.0
# Merodear es quedarse: en los últimos N segundos los pies no se movieron más
# de esta fracción del ancho de la propia caja. Caminar despacio no cuenta.
LOITER_STILLNESS_SECONDS: float = 5.0
LOITER_STILLNESS_FACTOR: float = 1.5
# Agacharse es una caída: la caja baja a esta fracción de su altura habitual.
# Alguien sentado desde que apareció nunca "se agacha".
CROUCH_HEIGHT_DROP_RATIO: float = 0.65
CROUCH_HEIGHT_MIN_HISTORY_SECONDS: float = 1.0
# Un altercado empieza con un acercamiento brusco: la distancia entre los dos
# cayó a la mitad en los últimos segundos. Dos personas que ya estaban juntas
# (conversación, fila) no cuentan.
CONVERGE_SECONDS: float = 3.0
CONVERGE_RATIO: float = 0.5
# Tres o más personas pegadas son un grupo o una fila, no una agresión.
GROUP_SUPPRESS_SIZE: int = 3

# Compatibilidad con la CLI previa, que hablaba de un único "merodeo".
LOITERING_SECONDS: float = PERSON_LOITER_SECONDS


class ThreatLevel(IntEnum):
    """Nivel de amenaza de la escena. El orden importa: escalar = subir."""

    SAFE = 0
    SUSPICIOUS = 1
    DANGER = 2

    @property
    def label(self) -> str:
        return _LEVEL_LABELS[self]

    @property
    def color(self) -> tuple[int, int, int]:
        """Color BGR para OpenCV (verde, ámbar, rojo)."""
        return _LEVEL_COLORS[self]

    @property
    def severity(self) -> str:
        """Severidad en el vocabulario del backend (`NivelPrioridad`)."""
        return _LEVEL_SEVERITIES[self]


_LEVEL_LABELS: dict[ThreatLevel, str] = {
    ThreatLevel.SAFE: "VERDE / SEGURO",
    ThreatLevel.SUSPICIOUS: "AMARILLO / SOSPECHOSO",
    ThreatLevel.DANGER: "ROJO / PELIGRO",
}

_LEVEL_COLORS: dict[ThreatLevel, tuple[int, int, int]] = {
    ThreatLevel.SAFE: (0, 200, 0),
    ThreatLevel.SUSPICIOUS: (0, 215, 255),
    ThreatLevel.DANGER: (0, 0, 255),
}

_LEVEL_SEVERITIES: dict[ThreatLevel, str] = {
    ThreatLevel.SAFE: "BAJA",
    ThreatLevel.SUSPICIOUS: "MEDIA",
    ThreatLevel.DANGER: "ALTA",
}


class ThreatRule(Enum):
    """Las cinco reglas de comportamiento, con su traducción al backend."""

    VEHICLE_WAITING = "VEHICULO DE ESPERA"
    LOITERING = "MERODEO Y RECONOCIMIENTO"
    CROUCHING = "OCULTAMIENTO / INTRUSION TACTICA"
    WEAPON = "ASALTO INMINENTE: ARMA"
    HANDS_UP = "ASALTO INMINENTE: MANOS ARRIBA"
    PROXIMITY = "ACOSO FISICO / ALTERCADO"

    @property
    def label(self) -> str:
        return self.value

    @property
    def level(self) -> ThreatLevel:
        return _RULE_LEVELS[self]

    @property
    def priority(self) -> int:
        """Desempata entre reglas del mismo nivel; mayor gana."""
        return _RULE_PRIORITIES[self]

    @property
    def event_type(self) -> str:
        """Alias de `tipo_evento` admitido por el backend."""
        return _RULE_EVENT_TYPES[self]

    @property
    def severity(self) -> str:
        """Valor admitido por `NivelPrioridad`."""
        return _RULE_SEVERITIES[self]


_RULE_LEVELS: dict[ThreatRule, ThreatLevel] = {
    ThreatRule.VEHICLE_WAITING: ThreatLevel.SUSPICIOUS,
    ThreatRule.LOITERING: ThreatLevel.SUSPICIOUS,
    ThreatRule.CROUCHING: ThreatLevel.DANGER,
    ThreatRule.WEAPON: ThreatLevel.DANGER,
    ThreatRule.HANDS_UP: ThreatLevel.DANGER,
    ThreatRule.PROXIMITY: ThreatLevel.DANGER,
}

_RULE_PRIORITIES: dict[ThreatRule, int] = {
    ThreatRule.WEAPON: 6,
    ThreatRule.HANDS_UP: 5,
    ThreatRule.CROUCHING: 4,
    ThreatRule.PROXIMITY: 3,
    ThreatRule.LOITERING: 2,
    ThreatRule.VEHICLE_WAITING: 1,
}

# El catálogo del backend (ALIAS_TIPO_EVENTO) no tiene un tipo para armas ni
# para posturas: el ROJO individual viaja como traspaso de perímetro y el
# altercado entre personas como aglomeración.
_RULE_EVENT_TYPES: dict[ThreatRule, str] = {
    ThreatRule.VEHICLE_WAITING: "MERODEO",
    ThreatRule.LOITERING: "MERODEO",
    ThreatRule.CROUCHING: "INTRUSION_PERIMETRO",
    ThreatRule.WEAPON: "INTRUSION_PERIMETRO",
    ThreatRule.HANDS_UP: "INTRUSION_PERIMETRO",
    ThreatRule.PROXIMITY: "AGLOMERACION",
}

_RULE_SEVERITIES: dict[ThreatRule, str] = {
    ThreatRule.VEHICLE_WAITING: "MEDIA",
    ThreatRule.LOITERING: "MEDIA",
    ThreatRule.CROUCHING: "ALTA",
    ThreatRule.WEAPON: "CRITICA",
    ThreatRule.HANDS_UP: "CRITICA",
    ThreatRule.PROXIMITY: "ALTA",
}


class RestrictedZone:
    """Polígono virtual contra el que se evalúan los centroides."""

    def __init__(self, points: Sequence[tuple[int, int]]) -> None:
        if len(points) < 3:
            raise ValueError("Una zona necesita al menos 3 puntos")
        # pointPolygonTest y polylines esperan un contorno (N, 1, 2) int32.
        self._contour = np.asarray(points, dtype=np.int32).reshape(-1, 1, 2)

    @property
    def contour(self) -> np.ndarray:
        return self._contour

    @property
    def points(self) -> tuple[tuple[int, int], ...]:
        return tuple((int(x), int(y)) for x, y in self._contour.reshape(-1, 2))

    def contains(self, point: tuple[int, int]) -> bool:
        """True si el punto está dentro del polígono o sobre su borde."""
        return (
            cv2.pointPolygonTest(
                self._contour, (float(point[0]), float(point[1])), False
            )
            >= 0
        )


@dataclass(frozen=True, slots=True)
class ThreatSignal:
    """Una regla disparada en el frame actual."""

    rule: ThreatRule
    detection: Detection | None = None
    partner: Detection | None = None
    elapsed: float = 0.0

    @property
    def level(self) -> ThreatLevel:
        return self.rule.level

    @property
    def label(self) -> str:
        if self.elapsed <= 0.0:
            return self.rule.label
        return f"{self.rule.label} ({self.elapsed:.1f}s)"


@dataclass(frozen=True, slots=True)
class ThreatAssessment:
    """Resultado de evaluar un frame completo contra la zona y el histórico."""

    level: ThreatLevel
    signals: tuple[ThreatSignal, ...]
    people_inside: tuple[Detection, ...] = ()
    people_outside: tuple[Detection, ...] = ()
    vehicles_inside: tuple[Detection, ...] = ()
    vehicles_outside: tuple[Detection, ...] = ()
    weapons: tuple[Detection, ...] = ()

    @property
    def primary(self) -> ThreatSignal | None:
        """Señal que manda: primero el nivel, luego la prioridad de la regla."""
        if not self.signals:
            return None
        return max(self.signals, key=lambda s: (s.level, s.rule.priority, s.elapsed))

    @property
    def reason(self) -> str:
        """Etiqueta(s) de las señales del nivel más alto, máximo dos."""
        if not self.signals:
            return "ZONA DESPEJADA"
        top = [signal for signal in self.signals if signal.level == self.level]
        top.sort(key=lambda s: (s.rule.priority, s.elapsed), reverse=True)
        unique: list[str] = []
        for signal in top:
            if signal.label not in unique:
                unique.append(signal.label)
        return " + ".join(unique[:2])

    @property
    def rules(self) -> tuple[ThreatRule, ...]:
        return tuple(dict.fromkeys(signal.rule for signal in self.signals))

    @property
    def breached(self) -> bool:
        return bool(self.people_inside or self.vehicles_inside)

    @property
    def weapon_present(self) -> bool:
        return bool(self.weapons)

    @property
    def people_total(self) -> int:
        return len(self.people_inside) + len(self.people_outside)

    @property
    def vehicles_total(self) -> int:
        return len(self.vehicles_inside) + len(self.vehicles_outside)

    @property
    def dwell_seconds(self) -> float:
        """Permanencia más larga entre las señales activas."""
        return max((signal.elapsed for signal in self.signals), default=0.0)

    @property
    def color(self) -> tuple[int, int, int]:
        return self.level.color

    @property
    def is_alertable(self) -> bool:
        """Sólo AMARILLO y ROJO generan evento hacia el backend."""
        return self.level >= ThreatLevel.SUSPICIOUS

    @property
    def event_type(self) -> str:
        primary = self.primary
        return primary.rule.event_type if primary is not None else "MERODEO"

    @property
    def severity(self) -> str:
        primary = self.primary
        return primary.rule.severity if primary is not None else self.level.severity

    @property
    def trigger(self) -> Detection | None:
        """Detección que justifica la alerta, si la señal apunta a una."""
        primary = self.primary
        if primary is not None and primary.detection is not None:
            return primary.detection
        return self.primary_intruder

    @property
    def primary_intruder(self) -> Detection | None:
        """Persona dentro de la zona con mayor confianza, si hay alguna."""
        if not self.people_inside:
            return None
        return max(self.people_inside, key=lambda detection: detection.confidence)


@dataclass(slots=True)
class _Dwell:
    started_at: float
    last_seen: float


class _DwellRegistry:
    """Cronómetros de permanencia continua, uno por clave de identidad."""

    def __init__(self, grace_seconds: float) -> None:
        self._grace = grace_seconds
        self._clocks: dict[str, _Dwell] = {}

    def tick(self, key: str, now: float) -> float:
        """Suma este frame al cronómetro de `key` y devuelve los segundos."""
        clock = self._clocks.get(key)
        if clock is None or now - clock.last_seen > self._grace:
            clock = _Dwell(started_at=now, last_seen=now)
            self._clocks[key] = clock
        else:
            clock.last_seen = now
        return now - clock.started_at

    def sweep(self, now: float) -> None:
        """Olvida las claves que ya superaron la tolerancia de ausencia."""
        for key in [
            key
            for key, clock in self._clocks.items()
            if now - clock.last_seen > self._grace
        ]:
            del self._clocks[key]

    def clear(self) -> None:
        self._clocks.clear()


@dataclass(frozen=True, slots=True)
class _Sample:
    at: float
    x: float
    y: float
    height: float
    width: float


class _TrackHistory:
    """Últimos segundos de posición y tamaño de cada identidad.

    Alimenta las heurísticas que necesitan pasado: quietud (merodeo), caída de
    altura (agacharse) y acercamiento (altercado).
    """

    def __init__(self, seconds: float) -> None:
        self._seconds = seconds
        self._samples: dict[str, deque[_Sample]] = {}

    def push(self, key: str, detection: Detection, now: float) -> None:
        x, y = detection.foot_point
        samples = self._samples.setdefault(key, deque())
        samples.append(_Sample(now, float(x), float(y), float(detection.height), float(detection.width)))
        while samples and now - samples[0].at > self._seconds:
            samples.popleft()

    def _recent(self, key: str, window: float, now: float) -> list[_Sample]:
        return [s for s in self._samples.get(key, ()) if now - s.at <= window]

    def is_still(self, key: str, window: float, factor: float, now: float) -> bool:
        """True si en `window` segundos los pies no salieron de `factor` anchos de caja."""
        samples = self._recent(key, window, now)
        if not samples or now - samples[0].at < 0.8 * window:
            return False  # historial corto: aún no se puede afirmar quietud
        last = samples[-1]
        radius = factor * max(last.width, 1.0)
        return all(np.hypot(s.x - last.x, s.y - last.y) <= radius for s in samples)

    def dropped_height(self, key: str, ratio: float, min_history: float, now: float) -> bool:
        """True si la altura actual es <= `ratio` de la mediana previa del track."""
        samples = self._samples.get(key)
        if not samples:
            return False
        last = samples[-1]
        previous = [s.height for s in samples if last.at - s.at >= min_history]
        if not previous:
            return False
        return last.height <= ratio * median(previous)

    def distance_ago(self, key_a: str, key_b: str, ago: float, now: float) -> float | None:
        """Distancia entre dos identidades hace `ago` segundos (None si no hay datos)."""
        target = now - ago
        pair = []
        for key in (key_a, key_b):
            samples = self._samples.get(key)
            if not samples or samples[0].at > target + 0.5:
                return None
            pair.append(min(samples, key=lambda s: abs(s.at - target)))
        return float(np.hypot(pair[0].x - pair[1].x, pair[0].y - pair[1].y))

    def sweep(self, now: float) -> None:
        for key in [k for k, v in self._samples.items() if not v or now - v[-1].at > self._seconds]:
            del self._samples[key]

    def clear(self) -> None:
        self._samples.clear()


class _Latch:
    """Sostiene una detección instantánea durante `hold_seconds`."""

    def __init__(self, hold_seconds: float) -> None:
        self._hold = hold_seconds
        self._fired_at: float | None = None
        self._detection: Detection | None = None

    def fire(self, detection: Detection, now: float) -> None:
        self._fired_at = now
        self._detection = detection

    def active(self, now: float) -> Detection | None:
        if self._fired_at is None or self._detection is None:
            return None
        if now - self._fired_at > self._hold:
            self._fired_at = None
            self._detection = None
            return None
        return self._detection

    def clear(self) -> None:
        self._fired_at = None
        self._detection = None


class _IdentityResolver:
    """Da una clave estable a cada detección, con tracker o sin él.

    Con `track_id` la clave es directa. Si el tracker no está disponible, se
    reasigna la clave del frame anterior por IoU: suficiente para sostener el
    cronómetro de un vehículo detenido o de alguien que merodea.
    """

    def __init__(self, prefix: str, min_iou: float, grace_seconds: float) -> None:
        self._prefix = prefix
        self._min_iou = min_iou
        self._grace = grace_seconds
        self._active: dict[str, tuple[Detection, float]] = {}
        self._next_id = 1

    def resolve(self, detections: Sequence[Detection], now: float) -> dict[str, Detection]:
        self._active = {
            key: value
            for key, value in self._active.items()
            if now - value[1] <= self._grace
        }

        assigned: dict[str, Detection] = {}
        pending: list[Detection] = []
        for detection in detections:
            if detection.track_id is not None:
                assigned[f"{self._prefix}:t{detection.track_id}"] = detection
            else:
                pending.append(detection)

        for detection in pending:
            best_key: str | None = None
            best_iou = 0.0
            for key, (previous, _) in self._active.items():
                if key in assigned:
                    continue
                score = detection.iou(previous)
                if score > best_iou:
                    best_key, best_iou = key, score
            if best_key is not None and best_iou >= self._min_iou:
                assigned[best_key] = detection
            else:
                assigned[f"{self._prefix}:g{self._next_id}"] = detection
                self._next_id += 1

        for key, detection in assigned.items():
            self._active[key] = (detection, now)
        return assigned

    def clear(self) -> None:
        self._active.clear()


def _is_invasive(
    first: Detection,
    second: Detection,
    overlap_ratio: float,
    distance_factor: float,
) -> bool:
    """True si dos personas comparten un espacio críticamente corto."""
    if first.overlap_ratio(second) >= overlap_ratio:
        return True
    scale = 0.5 * (first.width + second.width)
    return scale > 0.0 and first.centroid_distance(second) <= distance_factor * scale


class ThreatAssessor:
    """Máquina de estados que convierte detecciones sueltas en un nivel.

    Mantiene los cronómetros entre frames, así que debe existir una sola
    instancia por cámara y recibir `now` monotónico. El tiempo es de reloj, no
    de frames, para que el frame skipping no altere la heurística.
    """

    def __init__(
        self,
        zone: RestrictedZone,
        person_loiter_seconds: float = PERSON_LOITER_SECONDS,
        vehicle_loiter_seconds: float = VEHICLE_LOITER_SECONDS,
        proximity_seconds: float = PROXIMITY_SECONDS,
        proximity_overlap_ratio: float = PROXIMITY_OVERLAP_RATIO,
        proximity_distance_factor: float = PROXIMITY_DISTANCE_FACTOR,
        danger_hold_seconds: float = DANGER_HOLD_SECONDS,
        track_grace_seconds: float = TRACK_GRACE_SECONDS,
        hands_up_hold_seconds: float = HANDS_UP_HOLD_SECONDS,
        crouch_hold_seconds: float = CROUCH_HOLD_SECONDS,
    ) -> None:
        for name, value in (
            ("person_loiter_seconds", person_loiter_seconds),
            ("vehicle_loiter_seconds", vehicle_loiter_seconds),
            ("proximity_seconds", proximity_seconds),
            ("danger_hold_seconds", danger_hold_seconds),
            ("track_grace_seconds", track_grace_seconds),
            ("hands_up_hold_seconds", hands_up_hold_seconds),
            ("crouch_hold_seconds", crouch_hold_seconds),
        ):
            if value < 0:
                raise ValueError(f"{name} no puede ser negativo")

        self._zone = zone
        self._person_seconds = person_loiter_seconds
        self._vehicle_seconds = vehicle_loiter_seconds
        self._proximity_seconds = proximity_seconds
        self._proximity_overlap = proximity_overlap_ratio
        self._proximity_distance = proximity_distance_factor
        self._hands_up_seconds = hands_up_hold_seconds
        self._crouch_seconds = crouch_hold_seconds

        self._person_ids = _IdentityResolver("person", IDENTITY_MIN_IOU, track_grace_seconds)
        self._vehicle_ids = _IdentityResolver("vehicle", IDENTITY_MIN_IOU, track_grace_seconds)
        self._person_dwell = _DwellRegistry(track_grace_seconds)
        self._vehicle_dwell = _DwellRegistry(track_grace_seconds)
        self._pair_dwell = _DwellRegistry(track_grace_seconds)
        self._hands_up_dwell = _DwellRegistry(track_grace_seconds)
        self._crouch_dwell = _DwellRegistry(track_grace_seconds)
        self._history = _TrackHistory(HISTORY_SECONDS)
        # Pareja -> si su contacto empezó con un acercamiento brusco.
        self._pair_converged: dict[str, bool] = {}
        self._weapon_latch = _Latch(danger_hold_seconds)
        self._crouch_latch = _Latch(danger_hold_seconds)
        self._hands_up_latch = _Latch(danger_hold_seconds)

    @property
    def zone(self) -> RestrictedZone:
        return self._zone

    @property
    def person_loiter_seconds(self) -> float:
        return self._person_seconds

    @property
    def vehicle_loiter_seconds(self) -> float:
        return self._vehicle_seconds

    @property
    def proximity_seconds(self) -> float:
        return self._proximity_seconds

    def reset(self) -> None:
        """Olvida el histórico (cambio de zona, reconexión de cámara)."""
        for registry in (
            self._person_dwell,
            self._vehicle_dwell,
            self._pair_dwell,
            self._hands_up_dwell,
            self._crouch_dwell,
        ):
            registry.clear()
        for resolver in (self._person_ids, self._vehicle_ids):
            resolver.clear()
        self._history.clear()
        self._pair_converged.clear()
        for latch in (self._weapon_latch, self._crouch_latch, self._hands_up_latch):
            latch.clear()

    def assess(self, detections: Iterable[Detection], now: float) -> ThreatAssessment:
        """Clasifica la escena en VERDE / AMARILLO / ROJO según las 5 reglas."""
        people_inside: list[Detection] = []
        people_outside: list[Detection] = []
        vehicles_inside: list[Detection] = []
        vehicles_outside: list[Detection] = []
        weapons: list[Detection] = []

        for detection in detections:
            if detection.is_weapon:
                weapons.append(detection)
            elif detection.is_person:
                target = (
                    people_inside
                    if self._zone.contains(detection.foot_point)
                    else people_outside
                )
                target.append(detection)
            elif detection.is_vehicle:
                target = (
                    vehicles_inside
                    if self._zone.contains(detection.center)
                    else vehicles_outside
                )
                target.append(detection)

        signals: list[ThreatSignal] = []
        # Identidad para todas las personas: los gestos cuentan también fuera
        # de la zona, y el historial debe seguir a quien entra y sale.
        all_person_keys = self._person_ids.resolve([*people_inside, *people_outside], now)
        inside_ids = {id(person) for person in people_inside}
        person_keys = {k: p for k, p in all_person_keys.items() if id(p) in inside_ids}
        vehicle_keys = self._vehicle_ids.resolve(vehicles_inside, now)
        for key, person in all_person_keys.items():
            self._history.push(key, person, now)

        # --- Regla 1: vehículo de espera ---------------------------------
        for key, vehicle in vehicle_keys.items():
            elapsed = self._vehicle_dwell.tick(key, now)
            if elapsed >= self._vehicle_seconds:
                signals.append(
                    ThreatSignal(ThreatRule.VEHICLE_WAITING, vehicle, None, elapsed)
                )

        # --- Regla 2: merodeo y reconocimiento ---------------------------
        for key, person in person_keys.items():
            elapsed = self._person_dwell.tick(key, now)
            if elapsed >= self._person_seconds and self._history.is_still(
                key, LOITER_STILLNESS_SECONDS, LOITER_STILLNESS_FACTOR, now
            ):
                signals.append(
                    ThreatSignal(ThreatRule.LOITERING, person, None, elapsed)
                )

        # --- Regla 3: ocultamiento / intrusión táctica -------------------
        for key, person in person_keys.items():
            if not person.is_crouching or not self._history.dropped_height(
                key, CROUCH_HEIGHT_DROP_RATIO, CROUCH_HEIGHT_MIN_HISTORY_SECONDS, now
            ):
                continue
            if self._crouch_dwell.tick(key, now) >= self._crouch_seconds:
                self._crouch_latch.fire(person, now)
        held_crouch = self._crouch_latch.active(now)
        if held_crouch is not None:
            signals.append(ThreatSignal(ThreatRule.CROUCHING, held_crouch))

        # --- Regla 4: asalto inminente (arma o manos arriba) -------------
        # Sin restricción de zona: un asalto justo en el borde del polígono
        # es igual de urgente que uno dentro.
        if weapons:
            self._weapon_latch.fire(
                max(weapons, key=lambda detection: detection.confidence), now
            )
        held_weapon = self._weapon_latch.active(now)
        if held_weapon is not None:
            signals.append(ThreatSignal(ThreatRule.WEAPON, held_weapon))

        for key, person in all_person_keys.items():
            if not person.is_hands_up:
                continue
            if self._hands_up_dwell.tick(key, now) >= self._hands_up_seconds:
                self._hands_up_latch.fire(person, now)
        held_hands_up = self._hands_up_latch.active(now)
        if held_hands_up is not None:
            signals.append(ThreatSignal(ThreatRule.HANDS_UP, held_hands_up))

        # --- Regla 5: acoso físico / altercado ---------------------------
        close_pairs = [
            (key_a, first, key_b, second)
            for (key_a, first), (key_b, second) in combinations(person_keys.items(), 2)
            if _is_invasive(first, second, self._proximity_overlap, self._proximity_distance)
        ]
        contacts: dict[str, set[str]] = {}
        for key_a, _, key_b, _ in close_pairs:
            contacts.setdefault(key_a, set()).add(key_b)
            contacts.setdefault(key_b, set()).add(key_a)
        active_pairs: set[str] = set()
        for key_a, first, key_b, second in close_pairs:
            # Grupo o fila: ambos tienen más gente pegada que solo el otro.
            cluster = {key_a, key_b} | contacts[key_a] | contacts[key_b]
            if len(cluster) >= GROUP_SUPPRESS_SIZE:
                continue
            pair_key = f"pair:{min(key_a, key_b)}|{max(key_a, key_b)}"
            active_pairs.add(pair_key)
            elapsed = self._pair_dwell.tick(pair_key, now)
            if pair_key not in self._pair_converged:
                # Se decide al empezar el contacto: ¿venían de lejos?
                before = self._history.distance_ago(key_a, key_b, CONVERGE_SECONDS, now)
                current = first.centroid_distance(second)
                self._pair_converged[pair_key] = (
                    before is not None and current <= CONVERGE_RATIO * before
                )
            if elapsed >= self._proximity_seconds and self._pair_converged[pair_key]:
                signals.append(
                    ThreatSignal(ThreatRule.PROXIMITY, first, second, elapsed)
                )
        for pair_key in [k for k in self._pair_converged if k not in active_pairs]:
            del self._pair_converged[pair_key]

        for registry in (
            self._person_dwell,
            self._vehicle_dwell,
            self._pair_dwell,
            self._hands_up_dwell,
            self._crouch_dwell,
        ):
            registry.sweep(now)
        self._history.sweep(now)

        held_weapons: tuple[Detection, ...]
        if weapons:
            held_weapons = tuple(weapons)
        elif held_weapon is not None:
            held_weapons = (held_weapon,)
        else:
            held_weapons = ()

        level = max(
            (signal.level for signal in signals), default=ThreatLevel.SAFE
        )
        return ThreatAssessment(
            level=level,
            signals=tuple(signals),
            people_inside=tuple(people_inside),
            people_outside=tuple(people_outside),
            vehicles_inside=tuple(vehicles_inside),
            vehicles_outside=tuple(vehicles_outside),
            weapons=held_weapons,
        )
