<p align="center">
  <img src="docs/logo-sentinelops.jpg" alt="SentinelOps: seguridad integral y monitoreo" width="437">
</p>

# SentinelOps

Sistema de monitoreo de seguridad pública con IA: un sensor analiza el video de una cámara, detecta conductas de riesgo y avisa a un panel donde una persona decide qué hacer. Proyecto del HackaTec InnovaTecNM 2026, reto de Seguridad Pública.

La IA sugiere y el operador decide: ninguna patrulla sale ni se notifica a ninguna dependencia sin validación humana. No hay reconocimiento facial ni biometría; solo viajan metadatos del evento (tipo, hora, ubicación) y un fotograma de evidencia.

## Cómo funciona

```
Cámara ──► Edge AI ──► API central ──► Panel del operador
           (detecta)   (registra y      (valida, despacha
                        notifica)        o descarta)
```

1. **Edge AI** (`EDGE_AI/`) lee una cámara, un video o un stream, detecta personas, vehículos y armas con YOLOv8, y evalúa reglas de conducta: asalto, agresión física, merodeo, entre otras.
2. **API central** (`PROYECTO_HACKATEC_REGIONAL/BACKEND/`) recibe cada alerta, la guarda con su evidencia, la reenvía al panel por WebSocket y deja registro en una bitácora encadenada por hash.
3. **Panel** (`PROYECTO_HACKATEC_REGIONAL/FRONTEND/` y `pages/`) muestra el video, el mapa y la cola de alertas. El operador despacha la patrulla más cercana, valida y federa a una dependencia, o descarta la alerta como falsa alarma.

## Qué incluye el panel

| Página | Para qué sirve |
|---|---|
| **Operación** | Cámara en vivo con la detección dibujada, mosaico de cámaras, mapa con incidentes, zonas de riesgo y patrullas, indicadores del turno y panel lateral de alertas. Al final, los videos de demostración. |
| **Analítica** | Mapa de calor de eventos, franjas horarias críticas y rondines preventivos sugeridos. |
| **Auditoría** | Bitácora de cada evento, validación y despacho, con verificación de integridad. |

## Requisitos

- Python 3.11 o superior para el backend y el panel.
- Python 3.10 a 3.13 para el sensor Edge AI (`ultralytics` no tiene versión para 3.14), en su propio entorno virtual.
- `ffmpeg` (opcional) para generar los videos de demostración en `.mp4`.

## Puesta en marcha

### 1. Backend y panel

Desde la raíz del repositorio:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
reflex run
```

El panel queda en `http://localhost:3000` y la API en `http://localhost:8000` (documentación interactiva en `/docs`). Sin más configuración usa una base SQLite local (`reflex.db`) y deja los endpoints abiertos, que es lo esperado en desarrollo.

### 2. Sensor Edge AI

```bash
cd EDGE_AI
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r sentinelops/requirements.txt
```

Lo habitual es arrancarlo desde el panel: en Operación, **Vincular cámara**, con la URL de la cámara (por ejemplo la app IP Webcam de un teléfono) o el video de demostración. Para que el panel use este entorno, define en `.env`:

```
SENTINEL_EDGE_PYTHON=/ruta/al/repo/EDGE_AI/.venv/bin/python
```

También se puede ejecutar a mano; las opciones y las reglas de detección están en [EDGE_AI/README.md](EDGE_AI/README.md).

### 3. Probar sin cámara

Con la app corriendo, el simulador envía alertas sintéticas a la API:

```bash
python -m PROYECTO_HACKATEC_REGIONAL.simular_edge --historico 30   # siembra 30 días
python -m PROYECTO_HACKATEC_REGIONAL.simular_edge --vivo 10        # una alerta cada ~10 s
```

Con `SENTINEL_MOCK=1` en `.env`, el panel muestra datos simulados sin tocar la API ni la base.

### 4. Videos de demostración

Para mostrar videos propios con la detección ya dibujada, se procesan una vez con el modelo:

```bash
cd EDGE_AI
.venv/bin/python tools/preprocesar_video.py videos/mi_video.mp4 \
    --nombre "Plaza de Armas, Villahermosa" --lat 17.9892 --lng -92.9195
```

Aparecen en la sección «Videos de demostración» de Operación. No generan alertas: son solo imagen. Los originales (`EDGE_AI/videos/`) y los procesados (`static/videos/`) quedan fuera de git.

## Configuración

Todas las variables están documentadas en [.env.example](.env.example). Las más usadas:

| Variable | Qué controla |
|---|---|
| `DATABASE_URL` | Base de datos. Vacía usa SQLite local; acepta PostgreSQL (Supabase). |
| `SENTINEL_SENSOR_API_KEY`, `SENTINEL_OPERADOR_API_KEY` | Claves del sensor y del operador. Obligatorias con `SENTINEL_ENTORNO=produccion`. |
| `SENTINEL_JWT_SECRET` | Firma de los tokens de interoperabilidad. |
| `SENTINEL_EDGE_PYTHON` | Intérprete con el modelo, para el sensor que lanza el panel. |
| `SENTINEL_EDGE_URL` | Dónde publica el sensor su video anotado (puerto 8090). |
| `GOOGLE_MAPS_API_KEY` | Mapa de Google y búsqueda de direcciones. Sin ella se usa OpenStreetMap. |
| `SENTINEL_MOCK` | `1` para datos simulados en el panel. |

Nunca subas `.env` al repositorio.

## Pruebas

```bash
pip install -r requirements-dev.txt
pytest
```

Cubren la API (ingesta, validación, despacho, auditoría, WebSocket, evidencias y videos) y las reglas del sensor. No cubren la interfaz: después de cambiar el panel, verifica que compile con `reflex compile --dry` y revísalo en el navegador.

## Estructura

```
EDGE_AI/                        Sensor: detección, reglas de conducta y video anotado
  sentinelops/                  Código del sensor
  tools/                        Backend de prueba y preprocesado de videos
PROYECTO_HACKATEC_REGIONAL/
  BACKEND/                      API: rutas, servicios, modelos y tiempo real
  FRONTEND/components/          Componentes del panel (mapa, cámara, mosaico, alertas)
  pages/                        Operación, Analítica y Auditoría
  state.py, estado_ui.py        Estado del panel
  api_client.py                 Cliente de la API que usa el panel
  simular_edge.py               Simulador de alertas
assets/                         Estilos del panel
supabase/schema.sql             Esquema para PostgreSQL
tests/                          Pruebas
```

## Flujo de trabajo

Cada cambio va en su propia rama y entra a `main` por pull request. El panel está hecho con [Reflex](https://reflex.dev); las indicaciones para asistentes de código están en [AGENTS.md](AGENTS.md).
