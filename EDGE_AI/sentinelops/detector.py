"""Inferencia Edge: YOLOv8-Pose (persona + esqueleto) y COCO (vehículo, arma).

El checkpoint `yolov8n-pose.pt` sólo tiene la clase 0 (person): es un modelo
de pose, no un detector multiclase. Para cubrir vehículo (2, 3) y arma (43)
se carga en paralelo un `yolov8n.pt` COCO. Ambos corren sobre el mismo frame
y sus detecciones se fusionan en una sola lista.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, NamedTuple

import numpy as np

if TYPE_CHECKING:
    from ultralytics import YOLO

LOGGER = logging.getLogger(__name__)

# --- Vocabulario COCO ------------------------------------------------------
PERSON_CLASS_ID: Final[int] = 0
CAR_CLASS_ID: Final[int] = 2
MOTORCYCLE_CLASS_ID: Final[int] = 3
BUS_CLASS_ID: Final[int] = 5
TRUCK_CLASS_ID: Final[int] = 7
WEAPON_CLASS_ID: Final[int] = 43  # COCO: "knife"

# Camiones y autobuses también chocan; además yolov8n etiqueta como "truck"
# muchas camionetas y carritos a escala.
VEHICLE_CLASS_IDS: Final[tuple[int, ...]] = (CAR_CLASS_ID, MOTORCYCLE_CLASS_ID, BUS_CLASS_ID, TRUCK_CLASS_ID)
POSE_CLASS_IDS: Final[tuple[int, ...]] = (PERSON_CLASS_ID,)
OBJECT_CLASS_IDS: Final[tuple[int, ...]] = (*VEHICLE_CLASS_IDS, WEAPON_CLASS_ID)

DEFAULT_POSE_MODEL: Final[str] = "yolov8n-pose.pt"
DEFAULT_OBJECT_MODEL: Final[str] = "yolov8n.pt"

CLASS_NAMES: Final[dict[int, str]] = {
    PERSON_CLASS_ID: "persona",
    CAR_CLASS_ID: "carro",
    MOTORCYCLE_CLASS_ID: "moto",
    BUS_CLASS_ID: "autobus",
    TRUCK_CLASS_ID: "camion",
    WEAPON_CLASS_ID: "arma",
}

# El backend sólo acepta `clase_detectada` en {persona, vehiculo, objeto}
# (MetadatosDeteccion usa extra="forbid"), así que el cuchillo viaja como
# "objeto". Mandar "arma" devolvería 422.
BACKEND_CLASS_LABELS: Final[dict[int, str]] = {
    PERSON_CLASS_ID: "persona",
    CAR_CLASS_ID: "vehiculo",
    MOTORCYCLE_CLASS_ID: "vehiculo",
    BUS_CLASS_ID: "vehiculo",
    TRUCK_CLASS_ID: "vehiculo",
    WEAPON_CLASS_ID: "objeto",
}

# --- Esqueleto COCO-17 -----------------------------------------------------
NOSE: Final[int] = 0
LEFT_EYE: Final[int] = 1
RIGHT_EYE: Final[int] = 2
LEFT_EAR: Final[int] = 3
RIGHT_EAR: Final[int] = 4
LEFT_SHOULDER: Final[int] = 5
RIGHT_SHOULDER: Final[int] = 6
LEFT_ELBOW: Final[int] = 7
RIGHT_ELBOW: Final[int] = 8
LEFT_WRIST: Final[int] = 9
RIGHT_WRIST: Final[int] = 10
LEFT_HIP: Final[int] = 11
RIGHT_HIP: Final[int] = 12
LEFT_KNEE: Final[int] = 13
RIGHT_KNEE: Final[int] = 14
LEFT_ANKLE: Final[int] = 15
RIGHT_ANKLE: Final[int] = 16

KEYPOINT_COUNT: Final[int] = 17

SKELETON_EDGES: Final[tuple[tuple[int, int], ...]] = (
    (LEFT_ANKLE, LEFT_KNEE),
    (LEFT_KNEE, LEFT_HIP),
    (RIGHT_ANKLE, RIGHT_KNEE),
    (RIGHT_KNEE, RIGHT_HIP),
    (LEFT_HIP, RIGHT_HIP),
    (LEFT_SHOULDER, LEFT_HIP),
    (RIGHT_SHOULDER, RIGHT_HIP),
    (LEFT_SHOULDER, RIGHT_SHOULDER),
    (LEFT_SHOULDER, LEFT_ELBOW),
    (RIGHT_SHOULDER, RIGHT_ELBOW),
    (LEFT_ELBOW, LEFT_WRIST),
    (RIGHT_ELBOW, RIGHT_WRIST),
    (LEFT_SHOULDER, NOSE),
    (RIGHT_SHOULDER, NOSE),
    (NOSE, LEFT_EYE),
    (NOSE, RIGHT_EYE),
    (LEFT_EYE, LEFT_EAR),
    (RIGHT_EYE, RIGHT_EAR),
)

# --- Umbrales de la geometría corporal -------------------------------------
# Confianza mínima de un keypoint para considerarlo visible. Por debajo de
# esto Ultralytics devuelve coordenadas inventadas (o (0, 0)).
KEYPOINT_MIN_CONFIDENCE: Final[float] = 0.35
# Torso (hombros->cadera) mínimo en píxeles para que las proporciones sean
# estables: una persona de 10 px de torso es ruido, no una postura.
MIN_TORSO_PIXELS: Final[float] = 8.0
# De pie, hombros->tobillos mide ~2.2-2.6 torsos. Agachado las piernas se
# plieguen y la proporción cae por debajo de 1.5.
CROUCH_ANKLE_TORSO_RATIO: Final[float] = 1.5
# Mismo criterio cuando los tobillos están ocultos y sólo hay rodillas
# (de pie, hombros->rodillas mide ~1.5 torsos).
CROUCH_KNEE_TORSO_RATIO: Final[float] = 1.0
# Los gestos (manos arriba, agachado) deciden alertas ROJAS: sus articulaciones
# deben verse, no inventarse. Con yolov8n-pose a 320 px las muñecas de una
# persona a media distancia rondan 0.4-0.6; un umbral más alto deja ciego al
# sensor en la demo.
GESTURE_MIN_CONFIDENCE: Final[float] = 0.35
# "Manos arriba": ambas muñecas por encima de los hombros al menos esta fracción
# del torso. Una rendición o una defensa llevan las manos a la altura de la
# cara, no necesariamente por encima de la cabeza; en el video de demo las
# muñecas quedan 0.1-0.35 torsos sobre los hombros.
HANDS_UP_WRIST_RATIO: Final[float] = 0.10
# Codos como mucho esta fracción del torso por debajo de los hombros: brazos
# levantados o doblados hacia arriba, no colgando.
HANDS_UP_ELBOW_RATIO: Final[float] = 0.25
# Caja claramente horizontal (tumbado, gateando) cuando no hay esqueleto.
LYING_ASPECT_RATIO: Final[float] = 0.60


class Keypoint(NamedTuple):
    """Articulación en píxeles del frame procesado."""

    x: float
    y: float
    confidence: float

    @property
    def pixel(self) -> tuple[int, int]:
        return (int(round(self.x)), int(round(self.y)))


@dataclass(frozen=True, slots=True)
class Pose:
    """Esqueleto COCO-17 de una persona y la geometría derivada de él.

    El eje Y de OpenCV crece hacia abajo: "por encima" significa Y menor.
    """

    points: tuple[Keypoint, ...]
    min_confidence: float = KEYPOINT_MIN_CONFIDENCE

    @classmethod
    def from_array(
        cls,
        data: np.ndarray,
        min_confidence: float = KEYPOINT_MIN_CONFIDENCE,
    ) -> Pose | None:
        """Construye la pose desde una fila `(17, 2|3)` de `Results.keypoints`."""
        array = np.asarray(data, dtype=np.float32)
        if array.ndim != 2 or array.shape[0] == 0 or array.shape[1] < 2:
            return None

        has_confidence = array.shape[1] >= 3
        points = tuple(
            Keypoint(
                x=float(row[0]),
                y=float(row[1]),
                confidence=float(row[2]) if has_confidence else 1.0,
            )
            for row in array
        )
        return cls(points=points, min_confidence=min_confidence)

    def get(self, index: int) -> Keypoint | None:
        """Keypoint visible en `index`, o None si no es fiable."""
        if not 0 <= index < len(self.points):
            return None
        point = self.points[index]
        if point.confidence < self.min_confidence:
            return None
        if point.x <= 0.0 and point.y <= 0.0:
            return None  # el modelo no encontró la articulación
        return point

    def visible(self, indices: Iterable[int]) -> tuple[Keypoint, ...]:
        return tuple(
            point for point in (self.get(index) for index in indices) if point is not None
        )

    def get_sure(self, index: int) -> Keypoint | None:
        """Keypoint con confianza de gesto (>= GESTURE_MIN_CONFIDENCE), o None."""
        point = self.get(index)
        if point is None or point.confidence < GESTURE_MIN_CONFIDENCE:
            return None
        return point

    def sure(self, indices: Iterable[int]) -> tuple[Keypoint, ...]:
        return tuple(
            point for point in (self.get_sure(index) for index in indices) if point is not None
        )


    def mean_y(self, indices: Iterable[int]) -> float | None:
        """Promedio de Y de las articulaciones visibles (None si no hay)."""
        points = self.visible(indices)
        if not points:
            return None
        return sum(point.y for point in points) / len(points)

    @property
    def is_empty(self) -> bool:
        return not self.visible(range(len(self.points)))

    @property
    def shoulders_y(self) -> float | None:
        return self.mean_y((LEFT_SHOULDER, RIGHT_SHOULDER))

    @property
    def hips_y(self) -> float | None:
        return self.mean_y((LEFT_HIP, RIGHT_HIP))

    @property
    def knees_y(self) -> float | None:
        return self.mean_y((LEFT_KNEE, RIGHT_KNEE))

    @property
    def ankles_y(self) -> float | None:
        return self.mean_y((LEFT_ANKLE, RIGHT_ANKLE))

    @property
    def torso_height(self) -> float | None:
        """Distancia vertical hombros->cadera: la escala del cuerpo."""
        shoulders = self.shoulders_y
        hips = self.hips_y
        if shoulders is None or hips is None:
            return None
        height = abs(hips - shoulders)
        return height if height >= MIN_TORSO_PIXELS else None

    @property
    def is_crouching(self) -> bool:
        """True si el tren inferior está plegado respecto al torso.

        Invariante a la escala: compara el recorrido vertical
        hombros->tobillos (o hombros->rodillas) contra la altura del torso,
        así funciona igual con alguien cerca o lejos de la cámara.
        """
        torso = self.torso_height
        shoulders = self.shoulders_y
        if torso is None or shoulders is None:
            return False
        # Caderas y piernas con certeza: una persona cortada por el borde o
        # tapada hasta la cintura no "está agachada", simplemente no se ve.
        if len(self.sure((LEFT_HIP, RIGHT_HIP))) < 1:
            return False

        ankles = self.sure((LEFT_ANKLE, RIGHT_ANKLE))
        if ankles:
            ankles_y = sum(point.y for point in ankles) / len(ankles)
            return (ankles_y - shoulders) < CROUCH_ANKLE_TORSO_RATIO * torso
        knees = self.sure((LEFT_KNEE, RIGHT_KNEE))
        if knees:
            knees_y = sum(point.y for point in knees) / len(knees)
            return (knees_y - shoulders) < CROUCH_KNEE_TORSO_RATIO * torso
        return False

    @property
    def is_hands_up(self) -> bool:
        """True si los dos brazos están levantados: ambas muñecas claramente por
        encima de los hombros (a la altura de la cabeza o más) y los codos que
        se vean a la altura de los hombros o más arriba.

        Un saludo, señalar o hablar por teléfono usan una sola mano y no
        cumplen. No depende de ver la cabeza: funciona de espaldas o con la
        cabeza fuera de cuadro. Las muñecas deben verse con certeza.
        """
        shoulders = self.shoulders_y
        torso = self.torso_height
        if shoulders is None or torso is None:
            return False

        wrists = self.sure((LEFT_WRIST, RIGHT_WRIST))
        if len(wrists) < 2:
            return False
        if not all(wrist.y < shoulders - HANDS_UP_WRIST_RATIO * torso for wrist in wrists):
            return False
        elbow_limit = shoulders + HANDS_UP_ELBOW_RATIO * torso
        return all(elbow.y <= elbow_limit for elbow in self.sure((LEFT_ELBOW, RIGHT_ELBOW)))


@dataclass(frozen=True, slots=True)
class Detection:
    """Un objeto detectado en el frame actual.

    `bbox` es `(x1, y1, x2, y2)` en píxeles enteros del frame procesado,
    `class_id` el índice COCO original, `track_id` la identidad que asigna el
    tracker de Ultralytics (None si no hay tracking) y `pose` el esqueleto,
    presente sólo en las personas que vienen del modelo de pose.
    """

    bbox: tuple[int, int, int, int]
    confidence: float
    class_id: int = PERSON_CLASS_ID
    track_id: int | None = None
    pose: Pose | None = None

    @property
    def class_name(self) -> str:
        return CLASS_NAMES.get(self.class_id, str(self.class_id))

    @property
    def backend_label(self) -> str:
        """Valor admitido por `MetadatosDeteccion.clase_detectada`."""
        return BACKEND_CLASS_LABELS.get(self.class_id, "objeto")

    @property
    def is_person(self) -> bool:
        return self.class_id == PERSON_CLASS_ID

    @property
    def is_weapon(self) -> bool:
        return self.class_id == WEAPON_CLASS_ID

    @property
    def is_vehicle(self) -> bool:
        return self.class_id in VEHICLE_CLASS_IDS

    @property
    def width(self) -> int:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> int:
        return self.bbox[3] - self.bbox[1]

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    @property
    def center(self) -> tuple[int, int]:
        """Centro geométrico: centroide de vehículos y objetos pequeños."""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    @property
    def foot_point(self) -> tuple[int, int]:
        """Punto medio inferior del bbox.

        Se usa como centroide de la persona porque aproxima los pies: el
        centro geométrico de alguien alto dispara la zona antes de pisarla.
        """
        x1, _, x2, y2 = self.bbox
        return ((x1 + x2) // 2, y2)

    @property
    def is_crouching(self) -> bool:
        """Agachado por geometría del bbox o por proporciones del esqueleto."""
        if not self.is_person:
            return False
        if self.pose is not None:
            return self.pose.is_crouching
        # Sin esqueleto solo cuenta una caja claramente horizontal (tumbado,
        # gateando); "un poco más ancha que alta" también lo es alguien sentado
        # o medio tapado.
        return 0 < self.height < LYING_ASPECT_RATIO * self.width

    @property
    def is_hands_up(self) -> bool:
        if not self.is_person or self.pose is None:
            return False
        return self.pose.is_hands_up

    def intersection_area(self, other: Detection) -> int:
        ax1, ay1, ax2, ay2 = self.bbox
        bx1, by1, bx2, by2 = other.bbox
        overlap_w = min(ax2, bx2) - max(ax1, bx1)
        overlap_h = min(ay2, by2) - max(ay1, by1)
        if overlap_w <= 0 or overlap_h <= 0:
            return 0
        return overlap_w * overlap_h

    def iou(self, other: Detection) -> float:
        intersection = self.intersection_area(other)
        if intersection == 0:
            return 0.0
        union = self.area + other.area - intersection
        return intersection / union if union > 0 else 0.0

    def overlap_ratio(self, other: Detection) -> float:
        """Intersección sobre la caja más pequeña.

        Mide "cuánto me invaden" mejor que el IoU: dos personas de tamaños
        distintos pueden estar pegadas con un IoU bajo.
        """
        intersection = self.intersection_area(other)
        smaller = min(self.area, other.area)
        return intersection / smaller if smaller > 0 else 0.0

    def centroid_distance(self, other: Detection) -> float:
        ax, ay = self.center
        bx, by = other.center
        return float(np.hypot(ax - bx, ay - by))


class ThreatDetector:
    """Carga los modelos una vez y entrega las detecciones de cada frame."""

    def __init__(
        self,
        pose_model_path: str = DEFAULT_POSE_MODEL,
        object_model_path: str | None = DEFAULT_OBJECT_MODEL,
        conf_threshold: float = 0.45,
        weapon_conf_threshold: float | None = None,
        vehicle_conf_threshold: float | None = None,
        keypoint_min_confidence: float = KEYPOINT_MIN_CONFIDENCE,
        imgsz: int = 320,
        track: bool = True,
    ) -> None:
        if not 0.0 < conf_threshold <= 1.0:
            raise ValueError("conf_threshold debe estar en (0, 1]")

        # yolov8n es flojo con objetos pequeños: el cuchillo necesita un umbral
        # más permisivo que la persona o nunca se dispara el estado ROJO.
        self._conf_threshold = conf_threshold
        self._weapon_conf = (
            conf_threshold if weapon_conf_threshold is None else weapon_conf_threshold
        )
        self._vehicle_conf = (
            conf_threshold if vehicle_conf_threshold is None else vehicle_conf_threshold
        )
        for name, value in (
            ("weapon_conf_threshold", self._weapon_conf),
            ("vehicle_conf_threshold", self._vehicle_conf),
        ):
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} debe estar en (0, 1]")

        self._keypoint_min_confidence = keypoint_min_confidence
        self._imgsz = imgsz
        self._track = track

        # Import diferido: la geometría y las reglas se prueban sin torch.
        from ultralytics import YOLO

        LOGGER.info("Cargando modelo de pose %s", pose_model_path)
        self._pose_model = YOLO(pose_model_path)

        self._object_model: YOLO | None = None
        if object_model_path:
            LOGGER.info("Cargando modelo de objetos %s", object_model_path)
            self._object_model = YOLO(object_model_path)

        LOGGER.info(
            "Modelos listos | pose=%s objetos=%s imgsz=%d tracking=%s",
            pose_model_path,
            object_model_path or "deshabilitado",
            imgsz,
            track,
        )

    @property
    def class_ids(self) -> tuple[int, ...]:
        if self._object_model is None:
            return POSE_CLASS_IDS
        return (*POSE_CLASS_IDS, *OBJECT_CLASS_IDS)

    @property
    def tracking_enabled(self) -> bool:
        return self._track

    def detect(self, frame: np.ndarray) -> list[Detection]:
        """Devuelve personas (con esqueleto), vehículos y armas del frame."""
        detections = self._infer(
            self._pose_model, frame, POSE_CLASS_IDS, with_pose=True
        )
        if self._object_model is not None:
            detections.extend(
                self._infer(self._object_model, frame, OBJECT_CLASS_IDS, with_pose=False)
            )
        return detections

    def _min_confidence(self, class_id: int) -> float:
        if class_id == WEAPON_CLASS_ID:
            return self._weapon_conf
        if class_id in VEHICLE_CLASS_IDS:
            return self._vehicle_conf
        return self._conf_threshold

    def _infer(
        self,
        model: YOLO,
        frame: np.ndarray,
        class_ids: Sequence[int],
        with_pose: bool,
    ) -> list[Detection]:
        # Umbral que se le pide a YOLO: el más bajo de las clases pedidas. El
        # filtrado fino por clase se hace después, ya con las cajas en la mano.
        predict_conf = min(self._min_confidence(class_id) for class_id in class_ids)
        kwargs: dict[str, Any] = {
            "classes": list(class_ids),
            "conf": predict_conf,
            "imgsz": self._imgsz,
            "verbose": False,
        }

        results: Any
        if self._track:
            try:
                results = model.track(frame, persist=True, **kwargs)
            except Exception as error:  # noqa: BLE001 - el tracker es opcional
                LOGGER.warning(
                    "Tracker no disponible (%s); se degrada a predict()", error
                )
                self._track = False
                results = model.predict(frame, **kwargs)
        else:
            results = model.predict(frame, **kwargs)

        if not results:
            return []
        return self._parse(results[0], frame.shape[:2], with_pose)

    def _parse(
        self,
        result: Any,
        frame_shape: tuple[int, int],
        with_pose: bool,
    ) -> list[Detection]:
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return []

        xyxy = boxes.xyxy.cpu().numpy()
        confidences = boxes.conf.cpu().numpy()
        classes = boxes.cls.cpu().numpy()
        track_ids = (
            boxes.id.int().cpu().numpy() if getattr(boxes, "id", None) is not None else None
        )

        keypoints: np.ndarray | None = None
        if with_pose:
            raw = getattr(result, "keypoints", None)
            data = getattr(raw, "data", None) if raw is not None else None
            if data is not None:
                keypoints = data.cpu().numpy()

        height, width = frame_shape
        detections: list[Detection] = []
        for index in range(len(xyxy)):
            class_id = int(classes[index])
            confidence = float(confidences[index])
            if confidence < self._min_confidence(class_id):
                continue

            x1, y1, x2, y2 = (float(value) for value in xyxy[index])
            bbox = (
                max(0, int(round(x1))),
                max(0, int(round(y1))),
                min(width - 1, int(round(x2))),
                min(height - 1, int(round(y2))),
            )
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                continue  # el clamp degeneró la caja

            pose: Pose | None = None
            if keypoints is not None and index < len(keypoints):
                pose = Pose.from_array(
                    keypoints[index], self._keypoint_min_confidence
                )
                if pose is not None and pose.is_empty:
                    pose = None

            track_id: int | None = None
            if track_ids is not None and index < len(track_ids):
                track_id = int(track_ids[index])

            detections.append(
                Detection(
                    bbox=bbox,
                    confidence=round(confidence, 2),
                    class_id=class_id,
                    track_id=track_id,
                    pose=pose,
                )
            )

        return detections


# Alias de compatibilidad con el código previo al análisis de posturas.
PersonDetector = ThreatDetector
