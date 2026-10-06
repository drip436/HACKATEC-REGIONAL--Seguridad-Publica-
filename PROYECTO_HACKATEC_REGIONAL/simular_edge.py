"""Simulador del Módulo A (Edge AI): envía alertas sintéticas a la API central.

Permite probar y demostrar el dashboard contra el backend real sin cámara.
Usa el mismo contrato que el script de visión (`POST /api/v1/eventos`).

Uso (con la app corriendo):
    python -m PROYECTO_HACKATEC_REGIONAL.simular_edge --historico 30   # siembra 30 días
    python -m PROYECTO_HACKATEC_REGIONAL.simular_edge --vivo 10        # una alerta cada ~10 s
"""

import argparse
import os
import random
import time
from datetime import datetime

import httpx
from dotenv import load_dotenv

from . import mock

_CLASE = {"objeto_abandonado": "objeto"}


def _cabeceras(nombre: str, variable: str) -> dict[str, str]:
    llave = os.environ.get(variable, "").strip()
    return {nombre: llave} if llave else {}


def _alerta_sensor(evento: dict) -> dict:
    """Evento interno de `mock` -> cuerpo `AlertaSensorIn` del backend."""
    # Sembrado con el id: el mismo evento produce el mismo cuerpo, y el backend
    # lo reconoce como reintento idempotente en vez de duplicarlo.
    rng = random.Random(evento["id"])
    x, y = rng.randint(0, 400), rng.randint(0, 200)
    metadatos = {
        "clase_detectada": _CLASE.get(evento["tipo"], "persona"),
        "confianza": evento["confianza"],
        "bounding_box": [x, y, x + rng.randint(40, 200), y + rng.randint(80, 260)],
    }
    if evento["tipo"] == "aglomeracion":
        metadatos["conteo_personas"] = rng.randint(8, 40)
    return {
        "sensor_id": evento["camara_id"],
        "tipo_evento": evento["tipo"],
        "severidad": evento["severidad"],
        "coordenadas": {"lat": evento["lat"], "lng": evento["lng"]},
        "timestamp": evento["timestamp"],
        "metadatos": metadatos,
    }


def registrar_sensores(cliente: httpx.Client) -> None:
    cabeceras = _cabeceras("X-Operador-Key", "SENTINEL_OPERADOR_API_KEY")
    for camara in mock.CAMARAS:
        cuerpo = {
            "codigo": camara["id"],
            "nombre_ubicacion": camara["nombre"],
            "estado_operativo": "activo" if camara["activa"] else "mantenimiento",
            "coordenadas": {"lat": camara["lat"], "lng": camara["lng"]},
        }
        respuesta = cliente.post("/sensores", json=cuerpo, headers=cabeceras)
        if respuesta.status_code not in (201, 409):  # 409: ya estaba registrado
            raise SystemExit(f"No se pudo registrar {camara['id']}: {respuesta.status_code} {respuesta.text}")


def enviar(cliente: httpx.Client, evento: dict, *, historico: bool = False) -> None:
    respuesta = cliente.post(
        "/eventos", json=_alerta_sensor(evento), headers=_cabeceras("X-Sensor-Key", "SENTINEL_SENSOR_API_KEY")
    )
    if not respuesta.is_success:
        raise SystemExit(f"Evento rechazado: {respuesta.status_code} {respuesta.text}")
    # El histórico se deja validado para que no llene la cola del operador.
    # 201 = recién creado; un 200 es reintento y ya se resolvió antes.
    if historico and respuesta.status_code == 201:
        cuerpo = {"decision": "validado", "operador_id": "sim.historico", "notas": "Histórico sintético"}
        cliente.post(
            f"/eventos/{respuesta.json()['id']}/validar",
            json=cuerpo,
            headers=_cabeceras("X-Operador-Key", "SENTINEL_OPERADOR_API_KEY"),
        ).raise_for_status()


def main() -> None:
    load_dotenv()  # mismas llaves que el backend (SENTINEL_SENSOR_API_KEY / SENTINEL_OPERADOR_API_KEY)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=os.environ.get("SENTINEL_API_URL", "http://localhost:8000"))
    parser.add_argument("--historico", type=int, metavar="DIAS", help="siembra eventos de los últimos DIAS días")
    parser.add_argument("--vivo", type=float, metavar="SEG", help="envía una alerta nueva cada ~SEG segundos")
    args = parser.parse_args()
    if args.historico is None and args.vivo is None:
        parser.error("indica --historico DIAS y/o --vivo SEG")

    with httpx.Client(base_url=args.url.rstrip("/") + "/api/v1", timeout=10) as cliente:
        registrar_sensores(cliente)
        if args.historico:
            eventos = mock.eventos_historicos(args.historico)
            for evento in eventos:
                enviar(cliente, evento, historico=True)
            print(f"Histórico: {len(eventos)} eventos enviados (los repetidos se ignoran por idempotencia).")
        while args.vivo:
            evento = mock.generar_evento(datetime.now())
            enviar(cliente, evento)
            print(f"{evento['timestamp']}  {evento['camara_id']}  {evento['tipo']}  {evento['severidad']}")
            time.sleep(random.uniform(0.6, 1.4) * args.vivo)


if __name__ == "__main__":
    main()
