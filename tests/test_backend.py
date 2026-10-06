"""Pruebas de extremo a extremo de la API SentinelOps.

Ejecutar desde la raíz del proyecto:  pytest -v
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from starlette.websockets import WebSocketDisconnect

from .conftest import CLAVE_OPERADOR, nueva_alerta

API = "/api/v1"
H = dict[str, str]


# ---------------------------------------------------------------- Sistema y seguridad


def test_health_no_requiere_clave(client: Any) -> None:
    r = client.get(f"{API}/health")
    assert r.status_code == 200
    assert r.json()["estado"] == "ok"


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [("get", "/auditoria"), ("get", "/eventos"), ("get", "/despachos"), ("get", "/sensores")],
)
def test_endpoints_de_operador_exigen_clave(client: Any, metodo: str, ruta: str) -> None:
    assert getattr(client, metodo)(f"{API}{ruta}").status_code == 401
    assert getattr(client, metodo)(f"{API}{ruta}", headers={"X-Operador-Key": "mala"}).status_code == 401


def test_ingesta_exige_clave_de_sensor(client: Any, op: H) -> None:
    assert client.post(f"{API}/eventos", json=nueva_alerta()).status_code == 401
    # La clave de operador no sirve para reportar como sensor.
    assert client.post(f"{API}/eventos", json=nueva_alerta(), headers={"X-Sensor-Key": CLAVE_OPERADOR}).status_code == 401


def test_errores_tienen_formato_uniforme(client: Any) -> None:
    cuerpo = client.get(f"{API}/auditoria").json()
    assert set(cuerpo["error"]) == {"codigo", "mensaje", "detalle"}


# ---------------------------------------------------------------- Ingesta de eventos


def test_ingesta_normaliza_y_autoregistra(client: Any, sensor: H) -> None:
    r = client.post(f"{API}/eventos", json=nueva_alerta(sensor_id="CAM-NUEVA-01"), headers=sensor)
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["tipo_evento"] == "traspaso_perimetro"  # alias INTRUSION_PERIMETRO
    assert e["nivel_prioridad"] == "alta"
    assert e["estado_validacion"] == "pendiente"
    assert e["sensor_codigo"] == "CAM-NUEVA-01"


def test_reintento_es_idempotente(client: Any, sensor: H) -> None:
    alerta = nueva_alerta()
    primero = client.post(f"{API}/eventos", json=alerta, headers=sensor)
    segundo = client.post(f"{API}/eventos", json=alerta, headers=sensor)
    assert (primero.status_code, segundo.status_code) == (201, 200)
    assert segundo.headers["X-Idempotent-Replay"] == "true"
    assert primero.json()["id"] == segundo.json()["id"]


@pytest.mark.parametrize(
    "cambios",
    [
        {"timestamp": "2099-01-01T00:00:00Z"},  # futuro
        {"timestamp": "2026-10-06T10:45:00"},  # sin zona horaria
        {"severidad": "URGENTISIMA"},
        {"metadatos": {"confianza": 0.9, "bounding_box": [10, 10, 5, 5]}},  # bbox invertida
        {"metadatos": {"confianza": 0.9, "bounding_box": [1, 2, 3, 4], "embedding_facial": [0.1]}},  # privacidad
        {"evidencia_url": "http://otro-sitio.com/x.jpg"},
        {"coordenadas": {"lat": 200, "lng": 0}},
    ],
)
def test_ingesta_rechaza_datos_invalidos(client: Any, sensor: H, cambios: dict[str, Any]) -> None:
    r = client.post(f"{API}/eventos", json=nueva_alerta(**cambios), headers=sensor)
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------- Validación humana


def test_validacion_y_doble_validacion(client: Any, op: H, sensor: H) -> None:
    evento = client.post(f"{API}/eventos", json=nueva_alerta(), headers=sensor).json()
    url = f"{API}/eventos/{evento['id']}/validar"
    r = client.post(url, json={"decision": "validado", "operador_id": "op.martinez", "nivel_prioridad": "critica"}, headers=op)
    assert r.status_code == 200
    assert r.json()["nivel_prioridad"] == "critica"
    assert r.json()["validado_en"] is not None
    otra = client.post(url, json={"decision": "descartado_falsa_alarma", "operador_id": "op.lopez"}, headers=op)
    assert otra.status_code == 409


def test_no_se_reclasifica_una_falsa_alarma(client: Any, op: H, sensor: H) -> None:
    evento = client.post(f"{API}/eventos", json=nueva_alerta(), headers=sensor).json()
    r = client.post(
        f"{API}/eventos/{evento['id']}/validar",
        json={"decision": "descartado_falsa_alarma", "operador_id": "op.martinez", "nivel_prioridad": "alta"},
        headers=op,
    )
    assert r.status_code == 422


def test_listar_y_filtrar_eventos(client: Any, op: H, evento_validado: dict[str, Any]) -> None:
    r = client.get(f"{API}/eventos", params={"estado": "validado"}, headers=op)
    assert r.status_code == 200
    assert all(e["estado_validacion"] == "validado" for e in r.json())
    assert client.get(f"{API}/eventos/{evento_validado['id']}", headers=op).status_code == 200
    assert client.get(f"{API}/eventos/999999", headers=op).status_code == 404


# ---------------------------------------------------------------- Despachos X-Road


def test_despacho_completo_queda_confirmado(client: Any, op: H, evento_validado: dict[str, Any]) -> None:
    datos = {"evento_id": evento_validado["id"], "dependencia_destino": "C4 Municipal", "operador_id": "op.martinez"}
    r = client.post(f"{API}/despachos", json=datos, headers=op)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["estado_envio"] == "confirmado"
    assert d["miembro_xroad"] == "MX/GOB-MUN/C4/DESPACHO"
    assert d["acuse_recibo"]["referencia_jti"] == d["token_jti"]
    # Mismo evento y dependencia otra vez: conflicto.
    assert client.post(f"{API}/despachos", json=datos, headers=op).status_code == 409


def test_no_se_despacha_evento_pendiente(client: Any, op: H, sensor: H) -> None:
    evento = client.post(f"{API}/eventos", json=nueva_alerta(), headers=sensor).json()
    datos = {"evento_id": evento["id"], "dependencia_destino": "Proteccion Civil", "operador_id": "op.martinez"}
    assert client.post(f"{API}/despachos", json=datos, headers=op).status_code == 409


def test_token_federado_no_se_reutiliza_ni_se_altera(client: Any, op: H, evento_validado: dict[str, Any]) -> None:
    datos = {"evento_id": evento_validado["id"], "dependencia_destino": "Seguridad Campus", "operador_id": "op.martinez"}
    token = client.post(f"{API}/despachos", json=datos, headers=op).json()["token_interoperabilidad"]
    federar = f"{API}/interoperabilidad/federar"
    assert client.post(federar, json={"token": token, "payload": {"alterado": True}}).status_code == 422
    assert client.post(federar, json={"token": token[:-4] + "AAAA", "payload": {}}).status_code == 401


def test_reintento_de_despacho_tras_falla(
    client: Any, op: H, evento_validado: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.errores import FirmaInvalida
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import xroad

    def _falla(*_: Any, **__: Any) -> None:
        raise FirmaInvalida("Falla simulada del nodo receptor.")

    monkeypatch.setattr(xroad, "verificar_acuse", _falla)
    datos = {"evento_id": evento_validado["id"], "dependencia_destino": "C4 Municipal", "operador_id": "op.martinez"}
    r = client.post(f"{API}/despachos", json=datos, headers=op)
    assert r.status_code == 502
    despacho_id = r.json()["error"]["detalle"]["despacho_id"]
    assert client.get(f"{API}/despachos/{despacho_id}", headers=op).json()["estado_envio"] == "enviado"

    monkeypatch.undo()
    url = f"{API}/despachos/{despacho_id}/reintentar"
    r = client.post(url, json={"operador_id": "op.martinez"}, headers=op)
    assert r.status_code == 200, r.text
    assert r.json()["estado_envio"] == "confirmado"
    assert client.post(url, json={"operador_id": "op.martinez"}, headers=op).status_code == 409


# ---------------------------------------------------------------- Sensores


def test_alta_consulta_y_actualizacion_de_sensor(client: Any, op: H, sensor: H) -> None:
    alta = {"codigo": "CAM-PRUEBA-SENSOR", "nombre_ubicacion": "Edificio K", "coordenadas": {"lat": 21.0, "lng": -89.6}}
    r = client.post(f"{API}/sensores", json=alta, headers=op)
    assert r.status_code == 201
    sid = r.json()["id"]
    assert client.post(f"{API}/sensores", json=alta, headers=op).status_code == 409
    assert client.get(f"{API}/sensores/{sid}", headers=op).json()["codigo"] == "CAM-PRUEBA-SENSOR"

    assert client.patch(f"{API}/sensores/{sid}", json={}, headers=op).status_code == 422
    assert client.patch(f"{API}/sensores/{sid}", json={"codigo": "OTRO"}, headers=op).status_code == 422
    r = client.patch(f"{API}/sensores/{sid}", json={"estado_operativo": "inactivo"}, headers=op)
    assert r.json()["estado_operativo"] == "inactivo"

    # Un sensor dado de baja no puede reportar.
    r = client.post(f"{API}/eventos", json=nueva_alerta(sensor_id="CAM-PRUEBA-SENSOR"), headers=sensor)
    assert r.status_code == 409


def test_url_rtsp_no_llega_a_la_bitacora(client: Any, op: H) -> None:
    alta = {"codigo": "CAM-RTSP-01", "nombre_ubicacion": "Estacionamiento", "coordenadas": {"lat": 21.0, "lng": -89.6}}
    sid = client.post(f"{API}/sensores", json=alta, headers=op).json()["id"]
    client.patch(f"{API}/sensores/{sid}", json={"ip_rtsp_url": "rtsp://admin:secreta@10.0.0.5/stream"}, headers=op)
    items = client.get(f"{API}/auditoria", params={"accion": "sensor.actualizado"}, headers=op).json()["items"]
    assert items and "secreta" not in str(items)


# ---------------------------------------------------------------- Auditoría


def test_auditoria_filtra_fechas_con_zona_horaria(client: Any, op: H) -> None:
    from datetime import timedelta, timezone

    from PROYECTO_HACKATEC_REGIONAL.BACKEND.utils.tiempo import ahora_utc

    # Fechas a ±1 h de "ahora" escritas en otra zona horaria: si el servidor ignorara
    # el desfase (-06:00 / +05:00), ambos resultados se invertirían.
    mexico, asia = timezone(timedelta(hours=-6)), timezone(timedelta(hours=5))
    en_una_hora = (ahora_utc() + timedelta(hours=1)).astimezone(mexico).isoformat()
    hace_una_hora = (ahora_utc() - timedelta(hours=1)).astimezone(asia).isoformat()
    assert client.get(f"{API}/auditoria", params={"desde": en_una_hora}, headers=op).json()["total"] == 0
    assert client.get(f"{API}/auditoria", params={"desde": hace_una_hora}, headers=op).json()["total"] > 0
    invertido = {"desde": "2026-10-07T00:00:00Z", "hasta": "2026-10-06T00:00:00Z"}
    assert client.get(f"{API}/auditoria", params=invertido, headers=op).status_code == 422


def test_x_forwarded_for_no_falsea_la_ip(client: Any, op: H) -> None:
    client.get(f"{API}/auditoria", headers={**op, "X-Forwarded-For": "8.8.8.8"})
    ultimo = client.get(f"{API}/auditoria", params={"limit": 1}, headers=op).json()["items"][0]
    assert ultimo["accion"] == "auditoria.consultada"
    assert ultimo["ip_origen"] != "8.8.8.8"


def test_cadena_de_auditoria_integra(client: Any, op: H) -> None:
    v = client.get(f"{API}/auditoria/verificar", headers=op).json()
    assert v["integra"] is True, v
    assert v["registros_verificados"] > 0


def test_bitacora_es_append_only_y_detecta_manipulacion(client: Any, op: H) -> None:
    import reflex as rx

    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import db

    engine = rx.model.get_engine()
    trigger_update = "trg_bitacora_append_only" if engine.dialect.name == "postgresql" else "trg_bitacora_no_update"
    # 1) La BD bloquea UPDATE y DELETE.
    with pytest.raises(sa.exc.DatabaseError), engine.begin() as conn:
        conn.execute(sa.text("UPDATE bitacora_auditoria SET ip_origen = 'x' WHERE id = 1"))
    with pytest.raises(sa.exc.DatabaseError), engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM bitacora_auditoria WHERE id = 1"))
    if engine.dialect.name == "postgresql":
        with pytest.raises(sa.exc.DatabaseError), engine.begin() as conn:
            conn.execute(sa.text("TRUNCATE bitacora_auditoria"))

    # 2) Aun quitando los triggers, la verificación detecta el registro alterado.
    with engine.begin() as conn:
        original = conn.execute(sa.text("SELECT ip_origen FROM bitacora_auditoria WHERE id = 1")).scalar_one()
        conn.execute(sa.text(f"DROP TRIGGER {trigger_update}" + (" ON bitacora_auditoria" if engine.dialect.name == "postgresql" else "")))
        conn.execute(sa.text("UPDATE bitacora_auditoria SET ip_origen = '6.6.6.6' WHERE id = 1"))
    try:
        v = client.get(f"{API}/auditoria/verificar", headers=op).json()
        assert v["integra"] is False
        assert v["primer_registro_invalido"] == 1
    finally:
        # Restaura el registro y los triggers para no afectar otras pruebas.
        with engine.begin() as conn:
            conn.execute(sa.text("UPDATE bitacora_auditoria SET ip_origen = :ip WHERE id = 1"), {"ip": original})
        db._inicializada = False
        db.inicializar_bd()
    assert client.get(f"{API}/auditoria/verificar", headers=op).json()["integra"] is True


# ---------------------------------------------------------------- Tiempo real


def test_websocket_exige_token(client: Any) -> None:
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(f"{API.removesuffix('/api/v1')}/ws/alertas") as ws:
        ws.receive_text()


def test_websocket_recibe_alertas_nuevas(client: Any, sensor: H) -> None:
    with client.websocket_connect(f"/ws/alertas?token={CLAVE_OPERADOR}") as ws:
        assert '"conexion.establecida"' in ws.receive_text()
        ws.send_text("ping")
        assert '"pong"' in ws.receive_text()
        client.post(f"{API}/eventos", json=nueva_alerta(), headers=sensor)
        assert '"evento.nuevo"' in ws.receive_text()
