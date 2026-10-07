"""Ubicación automática de una cámara recién vinculada, sin escribir coordenadas.

Fuentes, de la más precisa a la menos:
  1. GPS del teléfono que hace de cámara (app IP Webcam con "ubicación" activada).
  2. Redes Wi-Fi alrededor de esta computadora + Google Geolocation API. La cámara
     está en la misma red Wi-Fi que la PC, así que su posición es la misma (±20-50 m
     en ciudad). Es lo que hace un celular sin GPS.
Si ninguna responde, el operador busca la dirección o marca el punto en el mapa.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..errores import SolicitudInvalida

LOGGER = logging.getLogger("sentinelops.ubicacion")

_GEOLOCATION_URL = "https://www.googleapis.com/geolocation/v1/geolocate"
_TIMEOUT = httpx.Timeout(connect=2.0, read=4.0, write=2.0, pool=2.0)
# Rutas donde IP Webcam (Android) publica la posición del teléfono.
_RUTAS_GPS = ("/gps.json", "/sensors.json?sense=gps", "/sensors.json")


@dataclass(frozen=True, slots=True)
class Ubicacion:
    lat: float
    lng: float
    precision_m: float
    fuente: str  # gps_camara | wifi_google


def ubicar(url_camara: str | None) -> Ubicacion:
    """Mejor ubicación disponible; 422 con el motivo si ninguna fuente respondió."""
    motivos: list[str] = []
    if url_camara:
        gps = gps_de_camara(url_camara)
        if gps is not None:
            return gps
        motivos.append("la cámara no comparte su GPS (actívalo en IP Webcam: Ajustes > Ubicación)")
    try:
        return por_wifi()
    except SolicitudInvalida as error:
        motivos.append(error.mensaje)
    raise SolicitudInvalida(
        "No se pudo ubicar automáticamente: " + "; ".join(motivos) + ". Busca la dirección o marca el punto en el mapa.",
        detalle={"motivos": motivos},
    )


# --- 1. GPS del teléfono -----------------------------------------------------


def _base(url: str) -> str:
    """`http://usuario:clave@ip:8080/video` -> `http://ip:8080` (las credenciales van aparte)."""
    partes = urlsplit(url)
    netloc = (partes.hostname or "") + (f":{partes.port}" if partes.port else "")
    return urlunsplit((partes.scheme or "http", netloc, "", "", ""))


def _buscar_coordenadas(dato: Any) -> tuple[float, float, float] | None:
    """Encuentra latitud/longitud (y precisión) en el JSON, tenga la forma que tenga."""
    if isinstance(dato, dict):
        claves = {k.lower(): v for k, v in dato.items()}
        lat = claves.get("latitude", claves.get("lat"))
        lng = claves.get("longitude", claves.get("lng", claves.get("lon")))
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)) and (lat, lng) != (0, 0):
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                precision = claves.get("accuracy", claves.get("acc", 25.0))
                return float(lat), float(lng), float(precision) if isinstance(precision, (int, float)) else 25.0
        hijos = list(dato.values())
    elif isinstance(dato, list):
        hijos = dato
        # IP Webcam guarda lecturas como [[timestamp, [lat, lng, ...]]]
        if len(dato) >= 2 and all(isinstance(x, (int, float)) for x in dato[:2]):
            lat, lng = dato[0], dato[1]
            if -90 <= lat <= 90 and -180 <= lng <= 180 and abs(lat) > 1 and abs(lng) > 1:
                return float(lat), float(lng), 25.0
    else:
        return None
    for hijo in reversed(hijos):  # la lectura más reciente suele ir al final
        encontrado = _buscar_coordenadas(hijo)
        if encontrado is not None:
            return encontrado
    return None


def gps_de_camara(url_camara: str) -> Ubicacion | None:
    if not url_camara.lower().startswith(("http://", "https://")):
        return None
    base = _base(url_camara)
    partes = urlsplit(url_camara)
    auth = (partes.username or "", partes.password or "") if partes.username else None
    for ruta in _RUTAS_GPS:
        try:
            r = httpx.get(base + ruta, timeout=_TIMEOUT, auth=auth)
            if r.status_code != 200:
                continue
            encontrado = _buscar_coordenadas(r.json())
        except (httpx.HTTPError, ValueError):
            continue
        if encontrado is not None:
            lat, lng, precision = encontrado
            return Ubicacion(round(lat, 6), round(lng, 6), round(precision, 1), "gps_camara")
    return None


# --- 2. Wi-Fi + Google Geolocation ------------------------------------------------


def _escanear_wifi() -> list[dict[str, Any]]:
    """Puntos de acceso visibles: BSSID e intensidad. Linux (nmcli) o Windows (netsh)."""
    sistema = platform.system()
    try:
        if sistema == "Linux" and shutil.which("nmcli"):
            salida = subprocess.run(
                ["nmcli", "-t", "-f", "BSSID,SIGNAL,CHAN", "dev", "wifi", "list"],
                capture_output=True, text=True, timeout=10, check=False,
            ).stdout
            puntos = []
            for linea in salida.splitlines():
                campos = re.split(r"(?<!\\):", linea)
                if len(campos) < 3:
                    continue
                mac = campos[0].replace("\\:", ":")
                senal = int(campos[1] or 0)  # 0-100
                puntos.append({"macAddress": mac, "signalStrength": senal // 2 - 100, "channel": int(campos[2] or 0)})
            return puntos
        if sistema == "Windows":
            salida = subprocess.run(
                ["netsh", "wlan", "show", "networks", "mode=bssid"], capture_output=True, text=True, timeout=10, check=False
            ).stdout
            macs = re.findall(r"BSSID \d+\s*:\s*([0-9a-fA-F:]{17})", salida)
            senales = [int(s) for s in re.findall(r"(?:Signal|Señal)\s*:\s*(\d+)%", salida)]
            return [
                {"macAddress": mac, "signalStrength": (senales[i] if i < len(senales) else 50) // 2 - 100}
                for i, mac in enumerate(macs)
            ]
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        LOGGER.warning("No se pudieron escanear redes Wi-Fi: %s", error)
    return []


def por_wifi() -> Ubicacion:
    llave = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not llave:
        raise SolicitudInvalida("falta GOOGLE_MAPS_API_KEY para ubicar por Wi-Fi")
    puntos = _escanear_wifi()
    if len(puntos) < 2:
        raise SolicitudInvalida("esta computadora no ve redes Wi-Fi suficientes para ubicarse")
    try:
        r = httpx.post(
            _GEOLOCATION_URL, params={"key": llave}, json={"considerIp": False, "wifiAccessPoints": puntos}, timeout=_TIMEOUT
        )
    except httpx.HTTPError as error:
        raise SolicitudInvalida(f"Google Geolocation no respondió ({error})") from error
    if r.status_code == 403:
        raise SolicitudInvalida("la Geolocation API no está habilitada en el proyecto de Google Cloud")
    if r.status_code == 404:
        raise SolicitudInvalida("Google no reconoce las redes Wi-Fi de este lugar")
    if r.status_code != 200:
        raise SolicitudInvalida(f"Google Geolocation respondió {r.status_code}")
    datos = r.json()
    return Ubicacion(
        round(datos["location"]["lat"], 6), round(datos["location"]["lng"], 6), round(float(datos.get("accuracy", 0)), 1), "wifi_google"
    )
