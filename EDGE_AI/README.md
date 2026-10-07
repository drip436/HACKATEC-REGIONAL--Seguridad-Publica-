# SentinelOps · Sensor Edge AI

Lee una **webcam, un archivo de video o un stream** (RTSP, la app IP Webcam de un
teléfono…), detecta **personas con esqueleto, vehículos y armas** con
YOLOv8-Pose + YOLOv8 COCO y evalúa reglas de comportamiento sobre una zona de
vigilancia:

| Regla | Nivel | Se envía al backend como |
|---|---|---|
| Vehículo detenido en la zona | amarillo | `merodeo` (media) |
| Persona que permanece en la zona | amarillo | `merodeo` (media) |
| Persona agachada / ocultándose en la zona | rojo | `traspaso_perimetro` (alta) |
| Proximidad invasiva sostenida entre personas | rojo | `aglomeracion` (alta) |
| Arma o manos arriba | rojo | `traspaso_perimetro` (crítica) |

Publica el **video anotado en vivo** (MJPEG) y el estado del análisis, que el
panel muestra en "Cámara en vivo"; guarda un fotograma de evidencia por alerta y
notifica al backend sin bloquear el video.

Sin biometría ni reconocimiento facial: solo cajas, articulaciones, conteos,
posiciones y tiempos.

## Dos formas de arrancarlo

**Desde el panel (lo normal en la demo).** En Operación → "Cámara en vivo" →
*Vincular cámara*: se indica la URL de la cámara (o el video de demostración), el
nombre del lugar y su ubicación. El backend lanza este sensor como proceso aparte
con `--no-preview --zona-completa` (todo el cuadro es la zona vigilada), lo
detiene al desvincular o al apagar la app, y el panel enseña sus últimas líneas
de log si se cae. El intérprete usado es el del backend salvo que se defina
`SENTINEL_EDGE_PYTHON` (útil si ultralytics/torch viven en otro venv).

**A mano**, con ventana y calibración de la zona con el ratón:

```bash
cd EDGE_AI
python3.12 -m venv .venv && source .venv/bin/activate   # Python 3.10–3.13
pip install -r sentinelops/requirements.txt
python -m sentinelops                  # video de prueba asalto.mp4
python -m sentinelops --source 0       # webcam
```

- Al arrancar se dibuja la zona sobre el primer frame (`c` confirma, `d` usa la
  zona por defecto de `config.py`). `--no-calibrate` la omite; `--no-preview`
  corre sin ventana y tampoco calibra; `--zona-completa` vigila todo el cuadro.
- La primera vez descarga los modelos (`yolov8n-pose.pt` y `yolov8n.pt`).
- Un archivo de video se reproduce a su velocidad real y en bucle.

## Video anotado y estado

Mientras corre, el sensor sirve por HTTP (puerto 8090 por defecto):

| Ruta | Qué devuelve |
|---|---|
| `/stream.mjpg` | video anotado en vivo; un `<img src>` lo reproduce tal cual |
| `/snapshot.jpg` | el último frame anotado |
| `/status.json` | `en_linea`, `nivel` (safe/suspicious/danger), `regla`, `personas`, `vehiculos`, `arma`, `fps`, `alertas_enviadas`, `ultima_alerta` |

| Variable | Para qué | Por defecto |
|---|---|---|
| `SENTINELOPS_STREAM_HOST` | interfaz donde escucha | `127.0.0.1` (solo esta máquina) |
| `SENTINELOPS_STREAM_PORT` | puerto | `8090` |
| `SENTINEL_STREAM_TOKEN` | si se define, se exige como `?token=` en cada ruta | — (abierto) |

El panel carga el video desde el navegador con `SENTINEL_EDGE_URL`
(`http://localhost:8090`), así que solo se ve cuando el navegador corre en la
misma máquina que el sensor. Para verlo desde otra, define
`SENTINELOPS_STREAM_HOST=0.0.0.0` **y** un token: el video muestra personas.

## Estructura

```
sentinelops/
├── config.py        # constantes y dataclass de configuración
├── camera.py        # lectura de la fuente (webcam, archivo en bucle, stream)
├── detector.py      # YOLOv8-Pose + COCO: persona, vehículo, arma (con tracking)
├── zone.py          # zona de vigilancia y motor de reglas de amenaza
├── overlay.py       # dibujo de zona, cajas, esqueletos y HUD
├── stream_server.py # video anotado MJPEG + /status.json para el panel
├── evidence.py      # guardado del frame en disco
├── notifier.py      # construcción del payload y POST con reintentos
├── main.py          # calibración, bucle de vigilancia y alertas
└── requirements.txt
tools/
└── mock_backend.py  # backend de prueba que imprime el JSON recibido
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
  "ubicacion": "Parque de Santa Lucía",
  "metadatos": {
    "clase_detectada": "persona",
    "confianza": 0.88,
    "bounding_box": [120, 80, 240, 310]
  }
}
```

- `timestamp`: UTC, ISO 8601 con sufijo `Z`, sin microsegundos.
- `bounding_box`: enteros `[x1, y1, x2, y2]` en píxeles del frame procesado.
- `evidencia_url`: `EVIDENCE_URL_PREFIX` + el nombre del archivo guardado. El
  backend lo sirve en `/static/capturas/<archivo>` con la clave de operador.
- `ubicacion` (opcional): el backend lo usa como nombre al autorregistrar un
  sensor nuevo.
- El id del evento es incremental y continúa la numeración de `EVIDENCE_DIR`
  entre reinicios, para no sobreescribir evidencias.
- Con varias detecciones, la alerta reporta la que disparó la regla principal
  (si la regla no apunta a una en concreto, la de mayor confianza en la zona).

## Conexión con el backend

El sensor envía cada alerta a `POST /api/v1/eventos` del backend SentinelOps
(`PROYECTO_HACKATEC_REGIONAL/BACKEND`) con el header `X-Sensor-Key`.

| Variable de entorno | Para qué | Por defecto |
|---|---|---|
| `SENTINEL_SENSOR_API_KEY` | Clave del sensor; **debe ser igual** a la del backend | — (sin ella el backend responde 401 si tiene clave) |
| `SENTINELOPS_BACKEND_URL` | Endpoint de ingesta | `http://127.0.0.1:8000/api/v1/eventos` |

Se leen del entorno o del primer `.env` que se encuentre (directorio actual o la
raíz del repositorio). En la misma máquina que el backend no hay que configurar
nada. En otra máquina (p. ej. una Raspberry):

```bash
export SENTINEL_SENSOR_API_KEY="<la misma clave del .env del backend>"
export SENTINELOPS_BACKEND_URL="http://<ip-del-backend>:8000/api/v1/eventos"
```

Comportamiento ante respuestas del backend:

- `201` alerta registrada · `200` reenvío ya registrado (idempotencia: no se duplica).
- `401/404/409/422`: error de configuración o de datos; se registra el motivo
  que devuelve el backend y **no** se reintenta.
- Errores de red, `408`, `429` y `5xx`: se reintenta con backoff exponencial.

Al arrancar, el sensor consulta `/api/v1/health` y avisa si el backend no responde.

## Configuración

Los valores por defecto viven en `Config` ([sentinelops/config.py](sentinelops/config.py));
lo más usado se pasa por CLI (`python -m sentinelops --help`):

```bash
python -m sentinelops --source 0 --loiter-person 6 --cooldown 10
python -m sentinelops --source http://192.168.1.50:8080/video --no-preview --zona-completa \
    --sensor-id CAM-MOVIL-PARQUE --ubicacion "Parque de Santa Lucía" --lat 20.9696 --lng -89.6233
```

| Opción | Qué controla |
|---|---|
| `--source` / `--camera` | qué video se analiza (índice, archivo, URL) |
| `--sensor-id`, `--ubicacion`, `--lat`, `--lng` | identidad del sensor y su punto en el mapa |
| `--pose-model`, `--object-model`, `--no-objects`, `--conf`, `--weapon-conf`, `--vehicle-conf` | modelos y umbrales |
| `--loiter-person S`, `--loiter-vehicle S`, `--proximity S` | tiempos de las reglas |
| `--inference-every N` | inferencia 1 de cada N frames |
| `--cooldown S` | espera mínima entre alertas del mismo incidente (una escalada avisa igual) |
| `--no-calibrate`, `--no-preview`, `--zona-completa` | zona por defecto / sin ventana / todo el cuadro |
| `--stream-port`, `--no-stream` | servidor del video anotado |
| `--evidence-dir`, `--backend-url`, `--log-level` | rutas y conexión |

La zona por defecto (`ZONE_POLYGON`) está en píxeles del frame redimensionado
(`FRAME_WIDTH × FRAME_HEIGHT`); la calibración con el ratón o `--zona-completa`
la sustituyen.

## Cómo probarlo a mano

### 1. Instalar dependencias

Requiere Python 3.10–3.13 (`ultralytics` aún no publica wheels para 3.14):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r sentinelops/requirements.txt
```

### 2. Levantar el backend

**Opción A: backend real** (desde la raíz del repo, con su propio venv):

```bash
reflex run
```

**Opción B: backend mock** (solo imprime los payloads; puerto 8001 para no chocar
con el real):

```bash
python tools/mock_backend.py
```

### 3. Ejecutar el sensor

En otra terminal, desde `EDGE_AI/` y con el venv del sensor activo:

```bash
python -m sentinelops                                                   # backend real
python -m sentinelops --backend-url http://127.0.0.1:8001/api/v1/eventos  # mock
```

### 4. Verificar la alerta, la evidencia y el cooldown

1. Dibuja la zona y confirma con `c`. Permanece dentro unos segundos (merodeo,
   amarillo) o agáchate / levanta las manos (rojo): el borde y el polígono cambian
   de color y el HUD muestra la regla activa.
2. En la terminal del sensor aparece `ALERTA <nivel> id=1 motivo=...` y
   luego `Alerta enviada (201) id=... ...`.
3. Con el backend real, la alerta aparece como `pendiente` en el panel y en
   `GET /api/v1/eventos`. Con el mock, se imprime el JSON completo. Comprueba que
   `evidencia_url` coincide con el archivo creado en `static/capturas/`.
4. Quédate dentro de la zona: el HUD muestra la cuenta de `cooldown` y **no** se
   generan nuevas alertas hasta que pasa, salvo que el nivel escale
   (amarillo → rojo) o aparezca una regla nueva. El incidente se da por
   terminado tras un cooldown completo en verde.

### 5. Probar el fallo del backend

Detén el backend (`Ctrl+C`) y vuelve a entrar en la zona:

- El video **no se traba**: los FPS del HUD se mantienen.
- El log muestra `Backend no disponible` al arrancar o `Fallo de red en intento 1/3`, `2/3`, `3/3` y finalmente
  `Alerta descartada tras 3 intentos`.
- La evidencia en disco se guarda igual.

### 6. Salida limpia

`q` en la ventana de preview, o `Ctrl+C` en cualquier modo. El proceso cierra el
servidor de video, libera la cámara y espera a que terminen los envíos HTTP en
vuelo antes de salir.
