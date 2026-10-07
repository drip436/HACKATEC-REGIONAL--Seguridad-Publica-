# SentinelOps

Sensor Edge AI de intrusión perimetral. Lee una cámara web en tiempo real,
detecta personas con YOLOv8n y, cuando el centroide de una persona entra en un
polígono virtual (zona restringida), guarda un fotograma de evidencia y notifica
a un backend por HTTP POST sin bloquear el ciclo de video.

Sin biometría ni reconocimiento facial: sólo la clase `person` de COCO.

## Estructura

```
sentinelops/
├── config.py       # constantes y dataclass de configuración
├── camera.py       # apertura/validación y lectura de la cámara
├── detector.py     # carga de YOLOv8n e inferencia (solo personas)
├── zone.py         # geometría: punto en polígono, centroide
├── overlay.py      # dibujo del polígono, bboxes y HUD
├── evidence.py     # guardado del frame en disco
├── notifier.py     # construcción del payload y POST con reintentos
├── main.py         # orquestación del bucle y cooldown
└── requirements.txt
tools/
└── mock_backend.py # backend de prueba que imprime el JSON recibido
```

## Contrato del POST

```json
{
  "sensor_id": "CAM-01-ACCESO-PRINCIPAL",
  "tipo_evento": "INTRUSION_PERIMETRO",
  "severidad": "ALTA",
  "coordenadas": {"lat": 20.9673, "lng": -89.6242},
  "timestamp": "2026-10-06T10:45:00Z",
  "evidencia_url": "/static/capturas/evento_1042.jpg",
  "metadatos": {
    "clase_detectada": "persona",
    "confianza": 0.88,
    "bounding_box": [120, 80, 240, 310]
  }
}
```

- `timestamp`: UTC, ISO 8601 con sufijo `Z`, sin microsegundos.
- `bounding_box`: enteros `[x1, y1, x2, y2]` en píxeles del frame procesado.
- `evidencia_url`: `EVIDENCE_URL_PREFIX` + el nombre del archivo guardado.
- El id del evento es incremental y continúa la numeración de `EVIDENCE_DIR`
  entre reinicios, para no sobreescribir evidencias.
- Con varias personas dentro de la zona, la alerta reporta la de mayor confianza.

## Configuración

Todo se edita en [sentinelops/config.py](sentinelops/config.py): `SENSOR_ID`,
`LAT`/`LNG`, `BACKEND_URL`, `ZONE_POLYGON`, `CAMERA_INDEX`, `CONF_THRESHOLD`,
`COOLDOWN_SECONDS`, `HTTP_TIMEOUT`, `EVIDENCE_DIR`, `EVIDENCE_URL_PREFIX`,
`SHOW_PREVIEW`. Los más usados también se pueden pasar por CLI
(`python -m sentinelops --help`).

`ZONE_POLYGON` está en píxeles de `FRAME_WIDTH x FRAME_HEIGHT` (1280x720 por
defecto). Si cambias la resolución, recalcula los puntos.

## Cómo probarlo

### 1. Instalar dependencias

Requiere Python 3.10–3.13 (`ultralytics` aún no publica wheels para 3.14):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r sentinelops/requirements.txt
```

La primera ejecución descarga `yolov8n.pt` (~6 MB) automáticamente.

### 2. Levantar el backend mock

En una terminal:

```bash
python tools/mock_backend.py 8000
```

Imprime en consola cada payload recibido.

### 3. Ejecutar el sensor

En otra terminal (con el venv activo):

```bash
python -m sentinelops
```

Opciones útiles:

```bash
python -m sentinelops --camera 0 --conf 0.5 --cooldown 5 --log-level DEBUG
python -m sentinelops --no-preview          # headless, salir con Ctrl+C
```

### 4. Verificar la alerta, la evidencia y el cooldown

1. Párate dentro del polígono rojo/verde del preview. El polígono se pone rojo,
   el bbox también y el HUD muestra `INTRUSION`.
2. En la terminal del sensor aparece `INTRUSION id=1 conf=... bbox=(...)` y
   luego `Alerta enviada (201) ...`.
3. En la terminal del mock backend aparece el JSON completo. Comprueba que
   `evidencia_url` coincide con el archivo creado en `static/capturas/`.
4. Quédate dentro de la zona: el HUD muestra la cuenta de `cooldown` y **no** se
   generan nuevas alertas hasta que pasan 5 s. Con `COOLDOWN_SECONDS=5`, 30 s
   dentro de la zona producen ~6 alertas, no cientos.

```bash
ls -l static/capturas/
```

### 5. Probar el fallo del backend

Detén el mock backend (`Ctrl+C`) y vuelve a entrar en la zona:

- El video **no se traba**: los FPS del HUD se mantienen.
- El log muestra `Fallo de red en intento 1/3`, `2/3`, `3/3` y finalmente
  `Alerta descartada tras 3 intentos`.
- La evidencia en disco se guarda igual.

Al relanzar el backend, las alertas siguientes se entregan de nuevo.

### 6. Salida limpia

`q` en la ventana de preview, o `Ctrl+C` en cualquier modo. El proceso libera la
cámara y espera a que terminen los envíos HTTP en vuelo antes de salir.
