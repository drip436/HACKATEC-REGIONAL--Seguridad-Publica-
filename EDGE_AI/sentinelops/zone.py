"""Geometría de la zona vigilada y máquina de estados de amenaza.

Las reglas buscan CONDUCTAS DELICTIVAS, no gestos sueltos. Levantar las manos,
agacharse o estar junto a otra persona no es un delito por sí mismo; lo es la
combinación con otra persona, un arma o el movimiento (golpes, arrastre):

  ROJO (crítico)
    - Asalto con arma        arma en la mano de alguien que está frente a otra persona
    - Intento de homicidio   golpes repetidos o arma sobre una persona en el suelo
    - Posible secuestro      una persona arrastra/somete a otra junto a un vehículo
    - Intento de asalto      alguien con las manos arriba y otra persona encima de él,
                             o apuntándole con el brazo extendido
  ROJO (alto)
    - Agresión física        golpes repetidos (muñecas a gran velocidad) contra otra persona
    - Persona sometida       forcejeo/arrastre sostenido sin vehículo cerca
  AMARILLO
    - Persona sospechosa     merodeo prolongado, ocultarse agachado, o portar un arma a solas
    - Vehículo sospechoso    vehículo detenido mucho tiempo en la zona

Todo se calcula con el esqueleto (YOLOv8-Pose) y el movimiento entre frames,
escalado al tamaño del cuerpo: funciona igual cerca o lejos de la cámara.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum, IntEnum
from itertools import combinations

import cv2
import numpy as np

from .detector import LEFT_SHOULDER, LEFT_WRIST, RIGHT_SHOULDER, RIGHT_WRIST, Detection

# --- Umbrales temporales de las reglas -------------------------------------
PERSON_LOITER_SECONDS: float = 20.0  # merodeo: alguien que se queda mucho tiempo
VEHICLE_LOITER_SECONDS: float = 15.0
# Contacto físico sostenido (forcejeo, arrastre) antes de considerarlo sometimiento.
PROXIMITY_SECONDS: float = 1.5
HANDS_UP_SECONDS: float = 1.0  # manos arriba sostenidas (no un saludo o estiramiento)
HIDING_SECONDS: float = 3.0  # agachado sin interactuar con nadie
ARMED_SECONDS: float = 0.5  # arma vista en la mano durante al menos esto
# Un ROJO se sostiene unos segundos: las detecciones parpadean entre frames.
DANGER_HOLD_SECONDS: float = 3.0
# Tolerancia a huecos de detección: un objeto que se pierde menos de esto no
# reinicia su cronómetro de permanencia.
TRACK_GRACE_SECONDS: float = 1.0

# --- Geometría (todo relativo al tamaño del cuerpo) -------------------------
# Dos personas interactúan si sus centros están a menos de esto × su tamaño medio.
INTERACTION_DISTANCE_FACTOR: float = 1.1
# Contacto físico: superposición de cajas o centros muy cercanos.
PROXIMITY_OVERLAP_RATIO: float = 0.25
PROXIMITY_DISTANCE_FACTOR: float = 0.60
# El arma "la porta" una persona si su centro cae en su caja ampliada este margen.
WEAPON_REACH_FACTOR: float = 0.35
# Brazo extendido: muñeca a ≥ esto × torso del hombro, casi a la altura del hombro.
ARM_EXTENDED_RATIO: float = 0.85
ARM_LEVEL_RATIO: float = 0.6
# Golpe: una muñeca a más de esto (torsos por segundo).
STRIKE_SPEED: float = 4.0
STRIKES_FOR_FIGHT: int = 3
STRIKE_WINDOW_SECONDS: float = 2.5
# Embestida: quien ataca llegó a más de esto (alturas de cuerpo/s) en el último
# segundo y ahora sujeta a la otra persona con el brazo estirado (medido en video
# real: ~0.45 al lanzarse; frena justo al sujetar, por eso se usa el pico reciente).
LUNGE_SPEED: float = 0.35
LUNGE_WINDOW_SECONDS: float = 1.2
LUNGE_GRAB_SECONDS: float = 0.3
# Arrastre: el par se desplaza a más de esto (alturas de cuerpo por segundo).
DRAG_SPEED: float = 0.6
# Vehículo "cerca" del par: a menos de esto × la altura del cuerpo.
VEHICLE_NEAR_FACTOR: float = 2.0
# Persona en el suelo: caja más ancha que alta por este factor.
LYING_ASPECT: float = 1.25
# Ventana para medir velocidades.
MOTION_WINDOW_SECONDS: float = 0.8

# IoU mínimo para reasignar la identidad de un frame al siguiente cuando el
# tracker de Ultralytics no entrega `track_id`.
IDENTITY_MIN_IOU: float = 0.25

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
    """Conductas reconocidas, con su traducción al backend."""

    VEHICLE_WAITING = "VEHICULO SOSPECHOSO"
    LOITERING = "PERSONA SOSPECHOSA: MERODEO"
    HIDING = "PERSONA SOSPECHOSA: OCULTANDOSE"
    ARMED_PERSON = "PERSONA SOSPECHOSA: PORTA ARMA"
    FIGHT = "AGRESION FISICA"
    SUBDUED = "PERSONA SOMETIDA A LA FUERZA"
    ROBBERY = "INTENTO DE ASALTO"
    KIDNAPPING = "POSIBLE SECUESTRO"
    ARMED_ROBBERY = "ASALTO CON ARMA"
    HOMICIDE_ATTEMPT = "INTENTO DE HOMICIDIO"

    @property
    def label(self) -> str:
        return self.value

    @property
    def level(self) -> ThreatLevel:
        return _RULE_SPECS[self][0]

    @property
    def priority(self) -> int:
        """Desempata entre reglas del mismo nivel; mayor gana."""
        return _RULE_SPECS[self][1]

    @property
    def event_type(self) -> str:
        """Alias de `tipo_evento` admitido por el backend."""
        return _RULE_SPECS[self][2]

    @property
    def severity(self) -> str:
        """Valor admitido por `NivelPrioridad`."""
        return _RULE_SPECS[self][3]

    @property
    def conducta(self) -> str:
        """`metadatos.conducta` del backend: lo que lee el operador."""
        return _RULE_SPECS[self][4]


_D, _S = ThreatLevel.DANGER, ThreatLevel.SUSPICIOUS
# regla: (nivel, prioridad, tipo_evento, severidad, conducta)
_RULE_SPECS: dict[ThreatRule, tuple[ThreatLevel, int, str, str, str]] = {
    ThreatRule.VEHICLE_WAITING: (_S, 1, "MERODEO", "MEDIA", "vehiculo_sospechoso"),
    ThreatRule.LOITERING: (_S, 2, "MERODEO", "MEDIA", "persona_sospechosa"),
    ThreatRule.HIDING: (_S, 3, "INTRUSION_PERIMETRO", "MEDIA", "persona_sospechosa"),
    ThreatRule.ARMED_PERSON: (_S, 4, "INTRUSION_PERIMETRO", "ALTA", "persona_sospechosa"),
    ThreatRule.FIGHT: (_D, 5, "AGLOMERACION", "ALTA", "agresion_fisica"),
    ThreatRule.SUBDUED: (_D, 6, "INTRUSION_PERIMETRO", "ALTA", "persona_sometida"),
    ThreatRule.ROBBERY: (_D, 7, "INTRUSION_PERIMETRO", "CRITICA", "intento_asalto"),
    ThreatRule.KIDNAPPING: (_D, 8, "INTRUSION_PERIMETRO", "CRITICA", "posible_secuestro"),
    ThreatRule.ARMED_ROBBERY: (_D, 9, "INTRUSION_PERIMETRO", "CRITICA", "asalto_con_arma"),
    ThreatRule.HOMICIDE_ATTEMPT: (_D, 10, "INTRUSION_PERIMETRO", "CRITICA", "intento_homicidio"),
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
    def conducta(self) -> str | None:
        primary = self.primary
        return primary.rule.conducta if primary is not None else None

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


class _Latch:  # se conserva por compatibilidad con código externo
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




# --- Geometría del cuerpo ----------------------------------------------------


def _size(detection: Detection) -> float:
    """Tamaño del cuerpo en píxeles (sirve también tumbado)."""
    return float(max(detection.width, detection.height, 1))


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _interacting(first: Detection, second: Detection, factor: float = INTERACTION_DISTANCE_FACTOR) -> bool:
    """True si dos personas están lo bastante cerca para agredirse o someterse."""
    scale = 0.5 * (_size(first) + _size(second))
    return first.centroid_distance(second) <= factor * scale


def _in_contact(first: Detection, second: Detection) -> bool:
    """Contacto físico: cajas superpuestas o centros muy juntos."""
    if first.overlap_ratio(second) >= PROXIMITY_OVERLAP_RATIO:
        return True
    scale = 0.5 * (first.width + second.width)
    return scale > 0.0 and first.centroid_distance(second) <= PROXIMITY_DISTANCE_FACTOR * scale


def _is_lying(person: Detection) -> bool:
    """En el suelo: la caja es claramente más ancha que alta."""
    return person.height > 0 and person.width >= LYING_ASPECT * person.height


def _is_down(person: Detection) -> bool:
    """Indefenso: en el suelo o agachado/encogido."""
    return _is_lying(person) or person.is_crouching


def _torso(person: Detection) -> float:
    pose = person.pose
    torso = pose.torso_height if pose is not None else None
    return float(torso) if torso else 0.3 * _size(person)


def _arm_extended_toward(person: Detection, target: Detection) -> bool:
    """Brazo estirado a la altura del hombro y en dirección a `target` (apuntar, encañonar, jalar)."""
    pose = person.pose
    if pose is None:
        return False
    torso = _torso(person)
    side = target.center[0] - person.center[0]
    for shoulder_idx, wrist_idx in ((LEFT_SHOULDER, LEFT_WRIST), (RIGHT_SHOULDER, RIGHT_WRIST)):
        shoulder, wrist = pose.get(shoulder_idx), pose.get(wrist_idx)
        if shoulder is None or wrist is None:
            continue
        reach = _distance((shoulder.x, shoulder.y), (wrist.x, wrist.y))
        level = abs(wrist.y - shoulder.y) <= ARM_LEVEL_RATIO * torso
        toward = (wrist.x - shoulder.x) * side > 0
        if reach >= ARM_EXTENDED_RATIO * torso and level and toward:
            return True
    return False


def _carries(person: Detection, weapon: Detection) -> bool:
    """El arma está en la mano/cuerpo de la persona (caja ampliada un margen)."""
    x1, y1, x2, y2 = person.bbox
    margin_x, margin_y = WEAPON_REACH_FACTOR * person.width, WEAPON_REACH_FACTOR * person.height
    cx, cy = weapon.center
    return x1 - margin_x <= cx <= x2 + margin_x and y1 - margin_y <= cy <= y2 + margin_y


# --- Movimiento entre frames ------------------------------------------------


@dataclass(slots=True)
class _Sample:
    t: float
    center: tuple[float, float]
    size: float
    torso: float
    wrists: tuple[tuple[float, float] | None, tuple[float, float] | None]


class _MotionTracker:
    """Historial corto por persona: velocidad del cuerpo y golpes (muñecas rápidas)."""

    def __init__(self, window: float = MOTION_WINDOW_SECONDS, grace: float = TRACK_GRACE_SECONDS) -> None:
        self._window = window
        self._grace = grace
        self._samples: dict[str, deque[_Sample]] = {}
        self._strikes: dict[str, deque[float]] = {}
        self._speeds: dict[str, deque[tuple[float, float]]] = {}

    def update(self, key: str, person: Detection, now: float) -> None:
        wrists: list[tuple[float, float] | None] = [None, None]
        if person.pose is not None:
            for i, idx in enumerate((LEFT_WRIST, RIGHT_WRIST)):
                point = person.pose.get(idx)
                wrists[i] = (point.x, point.y) if point is not None else None
        sample = _Sample(now, (float(person.center[0]), float(person.center[1])), _size(person), _torso(person), (wrists[0], wrists[1]))
        history = self._samples.setdefault(key, deque())
        previous = history[-1] if history else None
        history.append(sample)
        while history and now - history[0].t > max(self._window, STRIKE_WINDOW_SECONDS):
            history.popleft()
        if previous is not None and 0.0 < now - previous.t <= self._grace:
            dt = now - previous.t
            for before, after in zip(previous.wrists, sample.wrists):
                if before is None or after is None:
                    continue
                # Velocidad de la muñeca RELATIVA al cuerpo: caminar rápido no es golpear.
                rel_before = (before[0] - previous.center[0], before[1] - previous.center[1])
                rel_after = (after[0] - sample.center[0], after[1] - sample.center[1])
                speed = _distance(rel_before, rel_after) / dt / max(sample.torso, 1.0)
                if speed >= STRIKE_SPEED:
                    self._strikes.setdefault(key, deque()).append(now)
                    break
        strikes = self._strikes.get(key)
        while strikes and now - strikes[0] > STRIKE_WINDOW_SECONDS:
            strikes.popleft()
        speeds = self._speeds.setdefault(key, deque())
        speeds.append((now, self.speed(key, now)))
        while speeds and now - speeds[0][0] > LUNGE_WINDOW_SECONDS:
            speeds.popleft()

    def peak_speed(self, key: str) -> float:
        """Velocidad máxima reciente (alturas de cuerpo/s): detecta a quien se abalanzó."""
        return max((v for _, v in self._speeds.get(key, ())), default=0.0)

    def speed(self, key: str, now: float) -> float:
        """Desplazamiento del cuerpo en alturas de cuerpo por segundo."""
        history = [s for s in self._samples.get(key, ()) if now - s.t <= self._window]
        if len(history) < 2 or history[-1].t <= history[0].t:
            return 0.0
        first, last = history[0], history[-1]
        return _distance(first.center, last.center) / (last.t - first.t) / max(last.size, 1.0)

    def strikes(self, key: str) -> int:
        return len(self._strikes.get(key, ()))

    def sweep(self, now: float) -> None:
        for key in [k for k, h in self._samples.items() if not h or now - h[-1].t > self._grace]:
            self._samples.pop(key, None)
            self._strikes.pop(key, None)
            self._speeds.pop(key, None)

    def clear(self) -> None:
        self._samples.clear()
        self._strikes.clear()
        self._speeds.clear()


class ThreatAssessor:
    """Máquina de estados que convierte detecciones sueltas en un nivel.

    Mantiene los cronómetros y el movimiento entre frames, así que debe existir
    una sola instancia por cámara y recibir `now` monotónico. El tiempo es de
    reloj, no de frames, para que el frame skipping no altere la heurística.
    """

    def __init__(
        self,
        zone: RestrictedZone,
        person_loiter_seconds: float = PERSON_LOITER_SECONDS,
        vehicle_loiter_seconds: float = VEHICLE_LOITER_SECONDS,
        proximity_seconds: float = PROXIMITY_SECONDS,
        danger_hold_seconds: float = DANGER_HOLD_SECONDS,
        track_grace_seconds: float = TRACK_GRACE_SECONDS,
        **_legacy: float,
    ) -> None:
        for name, value in (
            ("person_loiter_seconds", person_loiter_seconds),
            ("vehicle_loiter_seconds", vehicle_loiter_seconds),
            ("proximity_seconds", proximity_seconds),
            ("danger_hold_seconds", danger_hold_seconds),
            ("track_grace_seconds", track_grace_seconds),
        ):
            if value < 0:
                raise ValueError(f"{name} no puede ser negativo")

        self._zone = zone
        self._person_seconds = person_loiter_seconds
        self._vehicle_seconds = vehicle_loiter_seconds
        self._proximity_seconds = proximity_seconds
        self._hold = danger_hold_seconds

        self._person_ids = _IdentityResolver("person", IDENTITY_MIN_IOU, track_grace_seconds)
        self._vehicle_ids = _IdentityResolver("vehicle", IDENTITY_MIN_IOU, track_grace_seconds)
        self._person_dwell = _DwellRegistry(track_grace_seconds)
        self._vehicle_dwell = _DwellRegistry(track_grace_seconds)
        self._contact_dwell = _DwellRegistry(track_grace_seconds)
        self._hands_dwell = _DwellRegistry(track_grace_seconds)
        self._hiding_dwell = _DwellRegistry(track_grace_seconds)
        self._armed_dwell = _DwellRegistry(track_grace_seconds)
        self._grab_dwell = _DwellRegistry(track_grace_seconds)
        self._motion = _MotionTracker(grace=track_grace_seconds)
        # Último disparo de cada regla grave: se sostiene `danger_hold_seconds`.
        self._held: dict[ThreatRule, tuple[ThreatSignal, float]] = {}

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
        for registry in self._registries():
            registry.clear()
        for resolver in (self._person_ids, self._vehicle_ids):
            resolver.clear()
        self._motion.clear()
        self._held.clear()

    def _registries(self) -> tuple[_DwellRegistry, ...]:
        return (self._person_dwell, self._vehicle_dwell, self._contact_dwell,
                self._hands_dwell, self._hiding_dwell, self._armed_dwell, self._grab_dwell)

    def _lunged(self, k1: str, p1: Detection, k2: str, p2: Detection, now: float) -> bool:
        """`p1` se abalanzó sobre `p2` y lo sujeta con el brazo estirado."""
        if not (_in_contact(p1, p2) and _arm_extended_toward(p1, p2)):
            return False
        grab = self._grab_dwell.tick(f"{k1}>{k2}", now)
        peak, other = self._motion.peak_speed(k1), self._motion.peak_speed(k2)
        return grab >= LUNGE_GRAB_SECONDS and peak >= LUNGE_SPEED and peak > 2.0 * other

    def assess(self, detections: Iterable[Detection], now: float) -> ThreatAssessment:
        """Clasifica la escena en VERDE / AMARILLO / ROJO según las conductas."""
        people_inside: list[Detection] = []
        people_outside: list[Detection] = []
        vehicles_inside: list[Detection] = []
        vehicles_outside: list[Detection] = []
        weapons: list[Detection] = []

        for detection in detections:
            if detection.is_weapon:
                weapons.append(detection)
            elif detection.is_person:
                inside = self._zone.contains(detection.foot_point)
                (people_inside if inside else people_outside).append(detection)
            elif detection.is_vehicle:
                inside = self._zone.contains(detection.center)
                (vehicles_inside if inside else vehicles_outside).append(detection)

        # Las conductas entre personas no respetan el borde del polígono.
        people = self._person_ids.resolve([*people_inside, *people_outside], now)
        inside_ids = {id(p) for p in people_inside}
        vehicle_keys = self._vehicle_ids.resolve(vehicles_inside, now)
        vehicles = [*vehicles_inside, *vehicles_outside]
        for key, person in people.items():
            self._motion.update(key, person, now)

        signals: list[ThreatSignal] = []
        busy: set[str] = set()  # personas ya involucradas en una conducta grave

        # --- Armas en la mano --------------------------------------------
        carriers: dict[str, Detection] = {}
        for key, person in people.items():
            weapon = next((w for w in weapons if _carries(person, w)), None)
            if weapon is not None and self._armed_dwell.tick(key, now) >= ARMED_SECONDS:
                carriers[key] = weapon

        pairs = [
            ((ka, a), (kb, b))
            for (ka, a), (kb, b) in combinations(people.items(), 2)
            if _interacting(a, b)
        ]
        for (key_a, a), (key_b, b) in pairs:
            for (k1, p1), (k2, p2) in (((key_a, a), (key_b, b)), ((key_b, b), (key_a, a))):
                weapon = carriers.get(k1)
                striking = self._motion.strikes(k1) >= STRIKES_FOR_FIGHT
                # 1. Intento de homicidio: golpes o arma contra alguien en el suelo,
                #    o arma + golpes (apuñalar).
                if (_is_down(p2) and (striking or weapon is not None)) or (weapon is not None and striking):
                    signals.append(ThreatSignal(ThreatRule.HOMICIDE_ATTEMPT, p1, p2))
                    busy.update((k1, k2))
                # 2. Asalto con arma: arma en la mano frente a otra persona.
                elif weapon is not None:
                    signals.append(ThreatSignal(ThreatRule.ARMED_ROBBERY, p1, p2))
                    busy.update((k1, k2))
                # 3. Agresión física: golpes repetidos, o embestida (se lanza con el
                #    brazo estirado hasta sujetar a la otra persona).
                elif striking or self._lunged(k1, p1, k2, p2, now):
                    signals.append(ThreatSignal(ThreatRule.FIGHT, p1, p2))
                    busy.update((k1, k2))

            # 4. Intento de asalto: alguien con las manos arriba (sostenidas) y otra
            #    persona encima de él o apuntándole con el brazo.
            for (kv, victim), (ka2, aggressor) in (((key_a, a), (key_b, b)), ((key_b, b), (key_a, a))):
                if not victim.is_hands_up or aggressor.is_hands_up:
                    continue  # los dos con las manos arriba: celebración, baile, etc.
                held_up = self._hands_dwell.tick(f"{kv}>{ka2}", now)
                threatened = _in_contact(victim, aggressor) or _arm_extended_toward(aggressor, victim)
                if held_up >= HANDS_UP_SECONDS and threatened:
                    signals.append(ThreatSignal(ThreatRule.ROBBERY, aggressor, victim, held_up))
                    busy.update((kv, ka2))

            # 5. Sometimiento / secuestro: contacto sostenido mientras uno jala o
            #    arrastra al otro (brazo extendido + desplazamiento) o uno está en el suelo.
            if _in_contact(a, b):
                contact = self._contact_dwell.tick(f"pair:{min(key_a, key_b)}|{max(key_a, key_b)}", now)
                moving = min(self._motion.speed(key_a, now), self._motion.speed(key_b, now)) >= DRAG_SPEED
                pulling = _arm_extended_toward(a, b) or _arm_extended_toward(b, a)
                forced = (moving and pulling) or (moving and (_is_down(a) or _is_down(b)))
                if contact >= self._proximity_seconds and forced:
                    near_vehicle = any(
                        min(v.centroid_distance(a), v.centroid_distance(b)) <= VEHICLE_NEAR_FACTOR * max(_size(a), _size(b))
                        for v in vehicles
                    )
                    rule = ThreatRule.KIDNAPPING if near_vehicle else ThreatRule.SUBDUED
                    signals.append(ThreatSignal(rule, a, b, contact))
                    busy.update((key_a, key_b))

        # --- Conductas individuales (amarillo) ---------------------------
        for key, person in people.items():
            if key in busy:
                continue
            if key in carriers and not any(key in (ka, kb) for (ka, _), (kb, _) in pairs):
                signals.append(ThreatSignal(ThreatRule.ARMED_PERSON, person))
            if id(person) not in inside_ids:
                continue
            elapsed = self._person_dwell.tick(key, now)
            if elapsed >= self._person_seconds:
                signals.append(ThreatSignal(ThreatRule.LOITERING, person, None, elapsed))
            if person.is_crouching and not _is_lying(person):
                hidden = self._hiding_dwell.tick(key, now)
                if hidden >= HIDING_SECONDS:
                    signals.append(ThreatSignal(ThreatRule.HIDING, person, None, hidden))

        for key, vehicle in vehicle_keys.items():
            elapsed = self._vehicle_dwell.tick(key, now)
            if elapsed >= self._vehicle_seconds:
                signals.append(ThreatSignal(ThreatRule.VEHICLE_WAITING, vehicle, None, elapsed))

        # --- Sostener los ROJOS unos segundos (anti-parpadeo) --------------
        for signal in signals:
            if signal.level is ThreatLevel.DANGER:
                self._held[signal.rule] = (signal, now)
        fired = {signal.rule for signal in signals}
        for rule, (signal, at) in list(self._held.items()):
            if now - at > self._hold:
                del self._held[rule]
            elif rule not in fired:
                signals.append(signal)

        for registry in self._registries():
            registry.sweep(now)
        self._motion.sweep(now)

        level = max((signal.level for signal in signals), default=ThreatLevel.SAFE)
        return ThreatAssessment(
            level=level,
            signals=tuple(signals),
            people_inside=tuple(people_inside),
            people_outside=tuple(people_outside),
            vehicles_inside=tuple(vehicles_inside),
            vehicles_outside=tuple(vehicles_outside),
            weapons=tuple(weapons),
        )
