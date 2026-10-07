"""Única capa que conoce la API central de SentinelOps (BACKEND/, REST + WebSocket).

Traduce los DTO del backend a las formas internas de `modelos.py`.

Variables de entorno:
  SENTINEL_MOCK              "1" usa datos simulados sin backend; por defecto "0".
  SENTINEL_API_URL           Base de la API. Por defecto, el backend de Reflex,
                             donde `crear_api()` queda montada.
  SENTINEL_OPERADOR_API_KEY  La misma llave que exige el backend (X-Operador-Key).
  SENTINEL_EDGE_URL          Video del sensor Edge AI (por defecto http://localhost:8090).
  SENTINEL_STREAM_TOKEN      Token de ese video (?token=), si está configurado.
"""

import asyncio
import hashlib
import json
import os
import random
from collections.abc import AsyncIterator
from datetime import datetime

import httpx
import websockets
from reflex.config import get_config

from . import mock
from .modelos import DESTINOS, fecha_hora_local

MOCK = os.environ.get("SENTINEL_MOCK", "0") == "1"
PREFIJO = "/api/v1"

# Conectar debe ser inmediato (es el mismo equipo); leer puede tardar si la base es remota.
_TIMEOUT = httpx.Timeout(connect=3.0, read=20.0, write=10.0, pool=5.0)
_REINTENTO_WS = 3.0
_PAGINA = 500
_MAX_HISTORICO = 3000

_ETIQUETA_DESTINO = {valor: etiqueta for etiqueta, valor in DESTINOS.items()}
_ESTADO = {"pendiente": "pendiente", "validado": "validado", "descartado_falsa_alarma": "descartado"}


class ErrorAPI(Exception):
    """Fallo al hablar con la API, con un mensaje apto para mostrar al operador."""

    def __init__(self, mensaje: str, codigo: str = "", detalle: dict | None = None, status: int = 0):
        super().__init__(mensaje)
        self.codigo = codigo
        self.detalle = detalle or {}
        self.status = status


def base_url() -> str:
    return (os.environ.get("SENTINEL_API_URL") or get_config().api_url).rstrip("/")


def _cabeceras() -> dict[str, str]:
    llave = os.environ.get("SENTINEL_OPERADOR_API_KEY", "").strip()
    return {"X-Operador-Key": llave} if llave else {}


async def _pedir(metodo: str, ruta: str, *, params: dict | None = None, cuerpo: dict | None = None):
    try:
        async with httpx.AsyncClient(base_url=base_url() + PREFIJO, timeout=_TIMEOUT, headers=_cabeceras()) as cliente:
            respuesta = await cliente.request(metodo, ruta, params=params, json=cuerpo)
    except httpx.TimeoutException as error:
        raise ErrorAPI("El servidor tardó demasiado en responder; intenta de nuevo.", codigo="timeout") from error
    except httpx.HTTPError as error:
        raise ErrorAPI(f"Sin conexión con la API ({base_url()}).", codigo="sin_conexion") from error
    if respuesta.is_success:
        return respuesta.json()
    try:
        error = respuesta.json()["error"]
        raise ErrorAPI(error["mensaje"], error.get("codigo", ""), error.get("detalle"), respuesta.status_code)
    except (ValueError, KeyError, TypeError):
        raise ErrorAPI(f"La API respondió {respuesta.status_code}.", status=respuesta.status_code) from None


# ---- Traducción backend -> modelo interno -----------------------------------


def _camara(sensor: dict) -> dict:
    return {
        "id": sensor["codigo"],
        "nombre": sensor["nombre_ubicacion"],
        "lat": sensor["coordenadas"]["lat"],
        "lng": sensor["coordenadas"]["lng"],
        "activa": sensor["estado_operativo"] == "activo",
    }


def _campos_despacho(despacho: dict) -> dict:
    """Campos de la alerta que dependen de su despacho."""
    destino = _ETIQUETA_DESTINO.get(despacho["dependencia_destino"], despacho["dependencia_destino"])
    acuse = despacho.get("acuse_recibo") or {}
    if despacho["estado_envio"] == "confirmado":
        return {"estado": "confirmado", "despacho": destino, "folio": acuse.get("acuse_id") or despacho.get("token_jti") or ""}
    # Emitido: la federación termina en segundo plano (si falla, se puede reintentar).
    return {"estado": "validado", "despacho": f"{destino} · en curso", "folio": ""}


def _url_evidencia(evidencia: str) -> str:
    """URL de la captura. El backend la protege con la llave de operador y un
    <img> no envía headers, así que la llave viaja como ?token=."""
    if not evidencia.startswith("/"):
        return evidencia
    llave = os.environ.get("SENTINEL_OPERADOR_API_KEY", "").strip()
    return base_url() + evidencia + (f"?token={llave}" if llave else "")


def _alerta(evento: dict, despacho: dict | None = None) -> dict:
    evidencia = evento.get("evidencia_url") or ""
    alerta = {
        "id": str(evento["id"]),
        "camara_id": evento["sensor_codigo"],
        "tipo": evento["tipo_evento"],
        "severidad": evento["nivel_prioridad"],
        "confianza": evento["metadata_json"].get("confianza", 0.0),
        "timestamp": evento["fecha_deteccion"],
        "lat": evento["coordenadas"]["lat"],
        "lng": evento["coordenadas"]["lng"],
        "snapshot_url": _url_evidencia(evidencia),
        "estado": _ESTADO.get(evento["estado_validacion"], evento["estado_validacion"]),
        "despacho": "",
        "folio": "",
    }
    if alerta["estado"] == "descartado":
        alerta["despacho"] = f"Descartada: {evento.get('notas_validacion') or 'falsa alarma'}"
    elif despacho and alerta["estado"] == "validado":
        alerta.update(_campos_despacho(despacho))
    if evento.get("resuelto_en"):
        # La unidad llegó: el caso queda cerrado aunque también se haya despachado.
        alerta["estado"] = "resuelto"
    return alerta


def _resumen(detalle: dict) -> str:
    """Detalle de bitácora en una línea; los hashes largos se abrevian."""
    partes = []
    for clave, valor in detalle.items():
        if isinstance(valor, (dict, list)):
            continue
        texto = str(valor)
        partes.append(f"{clave}: {texto[:16]}…" if len(texto) > 40 else f"{clave}: {texto}")
    return " · ".join(partes)


def _entrada_bitacora(registro: dict) -> dict:
    entidad = registro["entidad"].replace("_", " ")
    return {
        "timestamp": fecha_hora_local(registro["timestamp_inmutable"]),
        "actor": registro["usuario_o_nodo"],
        "accion": registro["accion"],
        "entidad": f"{entidad} #{registro['entidad_id']}" if registro.get("entidad_id") else entidad,
        "detalle": _resumen(registro["detalle_json"]),
        "sello": registro["hash_registro"][:12],
    }


# ---- Lecturas ---------------------------------------------------------------


async def obtener_camaras() -> list[dict]:
    if MOCK:
        return list(mock.CAMARAS)
    return [_camara(s) for s in await _pedir("GET", "/sensores")]


async def obtener_eventos(limite: int = 100) -> list[dict]:
    """Eventos más recientes primero, ya con el estado de su despacho."""
    if MOCK:
        return mock.eventos_iniciales()
    eventos, despachos = await asyncio.gather(
        _pedir("GET", "/eventos", params={"limit": limite}),
        _pedir("GET", "/despachos", params={"limit": _PAGINA}),
    )
    por_evento: dict[int, dict] = {}
    for despacho in despachos:
        previo = por_evento.get(despacho["evento_id"])
        if previo is None or despacho["estado_envio"] == "confirmado":
            por_evento[despacho["evento_id"]] = despacho
    return [_alerta(e, por_evento.get(e["id"])) for e in eventos]


async def obtener_historico() -> list[dict]:
    """Eventos para la analítica. Las falsas alarmas no cuentan para planear rondines."""
    if MOCK:
        return mock.historico_sintetico()
    historico: list[dict] = []
    for offset in range(0, _MAX_HISTORICO, _PAGINA):
        pagina = await _pedir("GET", "/eventos", params={"limit": _PAGINA, "offset": offset})
        historico += [
            {
                "timestamp": e["fecha_deteccion"],
                "tipo": e["tipo_evento"],
                "cuadrante": "",
                "lat": e["coordenadas"]["lat"],
                "lng": e["coordenadas"]["lng"],
            }
            for e in pagina
            if e["estado_validacion"] != "descartado_falsa_alarma"
        ]
        if len(pagina) < _PAGINA:
            break
    return historico


async def obtener_auditoria(limite: int = 200) -> list[dict]:
    """Bitácora del servidor, más reciente primero. La consulta misma queda registrada."""
    pagina = await _pedir("GET", "/auditoria", params={"limit": limite})
    return [_entrada_bitacora(r) for r in pagina["items"]]


async def verificar_auditoria() -> dict:
    return await _pedir("GET", "/auditoria/verificar")


# ---- Decisiones del operador ------------------------------------------------


def _ahora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


async def validar(evento_id: str, operador: str, *, confirma: bool, notas: str = "") -> dict:
    """Decisión humana sobre un evento pendiente. Devuelve los campos que cambian."""
    if MOCK:
        await asyncio.sleep(0.3)
        return {"estado": "validado" if confirma else "descartado", "despacho": "" if confirma else f"Descartada: {notas}"}
    cuerpo = {
        "decision": "validado" if confirma else "descartado_falsa_alarma",
        "operador_id": operador,
        "notas": notas or None,
    }
    alerta = _alerta(await _pedir("POST", f"/eventos/{evento_id}/validar", cuerpo=cuerpo))
    return {"estado": alerta["estado"], "despacho": alerta["despacho"]}


async def despachar(evento_id: str, operador: str, destino: str) -> dict:
    """Federa un evento validado hacia `destino` (etiqueta de DESTINOS)."""
    if MOCK:
        await asyncio.sleep(0.5)
        huella = hashlib.sha256(f"{evento_id}|{operador}|{destino}|{_ahora()}".encode()).hexdigest()
        return {"estado": "confirmado", "despacho": destino, "folio": f"sim-{huella[:12]}"}
    cuerpo = {"evento_id": int(evento_id), "dependencia_destino": DESTINOS[destino], "operador_id": operador}
    try:
        despacho = await _pedir("POST", "/despachos", cuerpo=cuerpo)
    except ErrorAPI as error:
        # Ya existe un despacho a ese destino: si quedó sin acuse se reintenta;
        # si ya estaba confirmado, basta con leerlo.
        previo = error.detalle.get("despacho_id")
        if error.status != 409 or previo is None:
            raise
        if error.detalle.get("estado_envio") == "confirmado":
            despacho = await _pedir("GET", f"/despachos/{previo}")
        else:
            despacho = await _pedir("POST", f"/despachos/{previo}/reintentar", cuerpo={"operador_id": operador})
    return _campos_despacho(despacho)


# ---- Tiempo real ------------------------------------------------------------


def _url_ws() -> str:
    url = base_url().replace("http", "ws", 1) + "/ws/alertas"
    llave = os.environ.get("SENTINEL_OPERADOR_API_KEY", "").strip()
    return f"{url}?token={llave}" if llave else url


async def flujo_alertas() -> AsyncIterator[tuple[str, dict | str]]:
    """Emite:
    ("estado", texto)        cambio en la conexión
    ("alerta", alerta)       evento nuevo
    ("cambio", {id, ...})    campos que cambiaron en un evento ya conocido
    ("atencion", atencion)   una unidad salió hacia un evento o ya llegó
    """
    if MOCK:
        yield "estado", "Simulado"
        while True:
            await asyncio.sleep(random.uniform(8, 16))
            yield "alerta", mock.generar_evento()

    while True:
        try:
            async with websockets.connect(_url_ws()) as ws:
                yield "estado", "Conectado"
                async for texto in ws:
                    mensaje = json.loads(texto)
                    tipo, data = mensaje.get("tipo"), mensaje.get("data", {})
                    if tipo == "evento.nuevo":
                        yield "alerta", _alerta(data)
                    elif tipo == "evento.actualizado":
                        alerta = _alerta(data)
                        yield "cambio", {"id": alerta["id"], "estado": alerta["estado"], "despacho": alerta["despacho"]}
                    elif tipo == "despacho.actualizado":
                        yield "cambio", {"id": str(data["evento_id"]), **_campos_despacho(data)}
                    elif tipo == "atencion.actualizada":
                        yield "atencion", _atencion(data)
        except (OSError, websockets.WebSocketException, ValueError, KeyError):
            pass
        yield "estado", "Reconectando"
        await asyncio.sleep(_REINTENTO_WS)


# ---- Atención en campo (patrulla simulada) -----------------------------------


def _ms(iso: str | None) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000) if iso else 0


def _atencion(dto: dict) -> dict:
    """DTO del backend -> forma que usa el mapa para animar la unidad."""
    return {
        "id": str(dto["id"]),
        "evento_id": str(dto["evento_id"]),
        "unidad": dto["unidad"],
        "estado": dto["estado"],
        "ruta": [list(p) for p in dto["ruta"]],
        "inicio_ms": _ms(dto["despachada_en"]),
        "llegada_ms": _ms(dto["llegada_estimada"]),
        "llegada_real_ms": _ms(dto.get("llegada_en")),
        "por_calles": bool(dto.get("ruta_por_calles")),
        "distancia_m": float(dto.get("distancia_m") or 0.0),
    }


async def atender(evento_id: str, operador: str) -> dict:
    if MOCK:
        raise ErrorAPI("La atención en campo necesita el backend (modo simulado activo).")
    return _atencion(await _pedir("POST", "/atenciones", cuerpo={"evento_id": int(evento_id), "operador_id": operador}))


async def obtener_unidades() -> list[dict]:
    """Patrullas (simuladas): {id, base, lat, lng, estado, evento_id}."""
    if MOCK:
        return []
    return [{**u, "evento_id": str(u["evento_id"]) if u.get("evento_id") else ""} for u in await _pedir("GET", "/unidades")]


async def obtener_atenciones() -> list[dict]:
    if MOCK:
        return []
    return [_atencion(a) for a in await _pedir("GET", "/atenciones", params={"limit": 100})]


# ---- Cámara vinculada (sensor Edge AI lanzado por el backend) -----------------


async def estado_camara() -> dict:
    if MOCK:
        return {"vinculada": False}
    return await _pedir("GET", "/camara-vinculada")


async def vincular_camara(*, url: str, demo: bool, nombre: str, lat: float, lng: float) -> dict:
    if MOCK:
        raise ErrorAPI("Vincular una cámara necesita el backend (modo simulado activo).")
    cuerpo = {"demo": demo, "nombre": nombre, "lat": lat, "lng": lng, "url": None if demo else url}
    return await _pedir("POST", "/camara-vinculada", cuerpo=cuerpo)


async def desvincular_camara() -> dict:
    return await _pedir("DELETE", "/camara-vinculada")


def _edge_base() -> str:
    return os.environ.get("SENTINEL_EDGE_URL", "http://localhost:8090").rstrip("/")


def _edge_token() -> str:
    token = os.environ.get("SENTINEL_STREAM_TOKEN", "").strip()
    return f"?token={token}" if token else ""


def url_transmision() -> str:
    """MJPEG con esqueletos y semáforo dibujados; un <img src> lo reproduce tal cual."""
    return f"{_edge_base()}/stream.mjpg{_edge_token()}"


async def estado_edge() -> dict | None:
    """`/status.json` del sensor, o None si no responde."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as cliente:
            respuesta = await cliente.get(f"{_edge_base()}/status.json{_edge_token()}")
        return respuesta.json() if respuesta.is_success else None
    except (httpx.HTTPError, ValueError):
        return None
