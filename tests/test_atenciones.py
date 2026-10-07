"""Atención en campo (patrulla simulada) y vinculación de cámara desde el panel."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import httpx
import pytest

from .conftest import CLAVE_OPERADOR, nueva_alerta

API = "/api/v1"
OP = {"X-Operador-Key": CLAVE_OPERADOR}


@pytest.fixture(autouse=True)
def sin_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """OSRM no se consulta en las pruebas: la ruta cae a línea recta."""
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import atenciones

    def _sin_red(*_: Any, **__: Any) -> None:
        raise httpx.ConnectError("sin red en pruebas")

    monkeypatch.setattr(atenciones.httpx, "get", _sin_red)


def _evento(client: Any, sensor: dict[str, str], **cambios: Any) -> dict[str, Any]:
    r = client.post(f"{API}/eventos", json=nueva_alerta(**cambios), headers=sensor)
    assert r.status_code == 201, r.text
    return r.json()


def test_atender_valida_el_evento_y_envia_una_unidad(client: Any, sensor: dict[str, str]) -> None:
    evento = _evento(client, sensor, severidad="CRITICA")
    r = client.post(f"{API}/atenciones", json={"evento_id": evento["id"], "operador_id": "op.martinez"}, headers=OP)
    assert r.status_code == 201, r.text
    atencion = r.json()
    assert atencion["estado"] == "en_camino"
    assert atencion["unidad"].startswith("YUC-")  # la alerta de prueba cae en Mérida
    assert atencion["ruta"][-1] == pytest.approx(list(atencion["destino"]))
    assert len(atencion["ruta"]) >= 2 and atencion["ruta_por_calles"] is False  # sin red: línea recta
    assert 20 <= atencion["duracion_s"] <= 75

    validado = client.get(f"{API}/eventos/{evento['id']}", headers=OP).json()
    assert validado["estado_validacion"] == "validado"
    assert validado["operador_id"] == "op.martinez"

    otra = client.post(f"{API}/atenciones", json={"evento_id": evento["id"], "operador_id": "op.lopez"}, headers=OP)
    assert otra.status_code == 409


def test_falsa_alarma_no_se_atiende(client: Any, sensor: dict[str, str]) -> None:
    evento = _evento(client, sensor)
    client.post(
        f"{API}/eventos/{evento['id']}/validar",
        json={"decision": "descartado_falsa_alarma", "operador_id": "op.martinez"},
        headers=OP,
    )
    r = client.post(f"{API}/atenciones", json={"evento_id": evento["id"], "operador_id": "op.martinez"}, headers=OP)
    assert r.status_code == 409


def test_la_unidad_llega_y_el_caso_queda_resuelto(
    client: Any, sensor: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import atenciones
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.utils.tiempo import ahora_utc

    evento = _evento(client, sensor)
    atencion = client.post(
        f"{API}/atenciones", json={"evento_id": evento["id"], "operador_id": "op.martinez"}, headers=OP
    ).json()
    assert atencion["id"] not in [a.id for a in atenciones.resolver_llegadas()]  # aún en camino

    futuro = ahora_utc() + timedelta(minutes=5)
    monkeypatch.setattr(atenciones, "ahora_utc", lambda: futuro)
    resueltas = atenciones.resolver_llegadas()
    assert atencion["id"] in [a.id for a in resueltas]

    guardada = client.get(f"{API}/atenciones/{atencion['id']}", headers=OP).json()
    assert guardada["estado"] == "resuelto" and guardada["llegada_en"] is not None
    acciones = [i["accion"] for i in client.get(f"{API}/auditoria", params={"limit": 6}, headers=OP).json()["items"]]
    assert "atencion.resuelta" in acciones and "atencion.unidad_despachada" in acciones
    assert client.get(f"{API}/auditoria/verificar", headers=OP).json()["integra"] is True


def test_websocket_avisa_la_atencion(client: Any, sensor: dict[str, str]) -> None:
    evento = _evento(client, sensor)
    with client.websocket_connect(f"/ws/alertas?token={CLAVE_OPERADOR}") as ws:
        ws.receive_text()  # conexion.establecida
        client.post(f"{API}/atenciones", json={"evento_id": evento["id"], "operador_id": "op.martinez"}, headers=OP)
        tipos = {json.loads(ws.receive_text())["tipo"] for _ in range(2)}
    assert tipos == {"evento.actualizado", "atencion.actualizada"}


# ---------------------------------------------------------------- flota y coordenadas


def _flota_bd() -> list[Any]:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import flota
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services.db import lectura

    with lectura() as session:
        return flota.unidades(session)


def _mas_cercana(lugar: dict[str, float], excepto: set[str] = frozenset()) -> Any:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import flota

    libres = [u for u in _flota_bd() if u.id not in excepto]
    return min(libres, key=lambda u: flota.distancia_m((u.lat, u.lng), (lugar["lat"], lugar["lng"])))


def test_la_flota_cubre_todo_el_sur_sureste(client: Any) -> None:
    unidades = client.get(f"{API}/unidades", headers=OP).json()
    assert len(unidades) >= 120
    prefijos = {u["id"].split("-")[0] for u in unidades}
    assert prefijos == {"TAB", "CAM", "YUC", "QROO", "CHIS", "OAX", "VER", "GRO"}


@pytest.mark.parametrize(
    ("lugar", "estado"),
    [
        ({"lat": 18.001234, "lng": -93.375678}, "TAB"),  # entre Cárdenas y Cunduacán
        ({"lat": 20.967370, "lng": -89.592586}, "YUC"),  # Mérida
        ({"lat": 21.161908, "lng": -86.851528}, "QROO"),  # Cancún
        ({"lat": 16.753554, "lng": -93.115959}, "CHIS"),  # Tuxtla Gutiérrez
        ({"lat": 17.060970, "lng": -96.725368}, "OAX"),  # Oaxaca de Juárez
        ({"lat": 19.173773, "lng": -96.134224}, "VER"),  # Veracruz
        ({"lat": 16.853109, "lng": -99.823653}, "GRO"),  # Acapulco
        ({"lat": 19.845113, "lng": -90.523671}, "CAM"),  # Campeche
    ],
)
def test_sale_la_unidad_mas_cercana_y_el_destino_es_exacto(
    client: Any, sensor: dict[str, str], lugar: dict[str, float], estado: str
) -> None:
    """En cualquier ciudad de la región atiende la unidad libre más cercana, desde su
    base y hasta la coordenada exacta del evento (sin desplazamientos ni redondeos)."""
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import flota

    evento = _evento(client, sensor, coordenadas=lugar)
    assert evento["coordenadas"] == lugar
    ocupadas = {u["id"] for u in client.get(f"{API}/unidades", headers=OP).json() if u["estado"] == "en_camino"}
    esperada = _mas_cercana(lugar, ocupadas)

    atencion = client.post(
        f"{API}/atenciones", json={"evento_id": evento["id"], "operador_id": "op.martinez"}, headers=OP
    ).json()
    assert atencion["unidad"] == esperada.id and atencion["unidad"].startswith(estado)
    assert list(atencion["origen"]) == [round(esperada.lat, 6), round(esperada.lng, 6)]
    assert list(atencion["destino"]) == [lugar["lat"], lugar["lng"]]
    assert flota.distancia_m((esperada.lat, esperada.lng), (lugar["lat"], lugar["lng"])) < 30_000

    unidades = {u["id"]: u for u in client.get(f"{API}/unidades", headers=OP).json()}
    assert unidades[esperada.id]["estado"] == "en_camino" and unidades[esperada.id]["evento_id"] == evento["id"]
    assert sum(u["evento_id"] == evento["id"] for u in unidades.values()) == 1  # solo se mueve la elegida


def test_si_la_cercana_esta_ocupada_va_la_siguiente(client: Any, sensor: dict[str, str]) -> None:
    lugar = {"lat": 17.989000, "lng": -92.921000}  # junto a la Plaza de Armas, Villahermosa
    unidades = []
    for _ in range(3):
        evento = _evento(client, sensor, coordenadas=lugar)
        r = client.post(f"{API}/atenciones", json={"evento_id": evento["id"], "operador_id": "op.martinez"}, headers=OP)
        unidades.append(r.json()["unidad"])
    assert len(set(unidades)) == 3 and all(u.startswith("TAB") for u in unidades)


def test_sin_unidades_libres_responde_409(
    client: Any, sensor: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import flota

    monkeypatch.setattr(flota, "unidades", lambda _session: [flota.Unidad("UNICA-01", "Teapa", 17.62, -92.97)])
    primero, segundo = _evento(client, sensor), _evento(client, sensor)
    ok = client.post(f"{API}/atenciones", json={"evento_id": primero["id"], "operador_id": "op.martinez"}, headers=OP)
    assert ok.status_code == 201
    r = client.post(f"{API}/atenciones", json={"evento_id": segundo["id"], "operador_id": "op.martinez"}, headers=OP)
    assert r.status_code == 409 and "unidades libres" in r.text


def test_la_ruta_por_calles_sale_de_la_unidad_y_llega_al_evento(monkeypatch: pytest.MonkeyPatch) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import atenciones

    class _Resp:
        def raise_for_status(self) -> None: ...

        def json(self) -> dict:  # OSRM ajusta los extremos a la calle
            return {"routes": [{"distance": 2300.0, "geometry": {"coordinates": [[-92.96201, 18.17093], [-92.9612, 18.1504]]}}]}

    monkeypatch.setattr(atenciones.httpx, "get", lambda *_, **__: _Resp())
    ruta = atenciones.calcular_ruta((18.178362, -92.955153), (18.150321, -92.961234))
    assert ruta.por_calles and ruta.puntos[0] == [18.178362, -92.955153] and ruta.puntos[-1] == [18.150321, -92.961234]


def test_la_semilla_es_idempotente_y_corrige_bases_viejas(client: Any) -> None:
    import reflex as rx
    from sqlmodel import Session, select

    from PROYECTO_HACKATEC_REGIONAL.BACKEND.models import UnidadPolicial
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import flota

    engine = rx.model.get_engine()
    antes = len(_flota_bd())
    assert flota.sembrar_flota(engine) == 0
    with Session(engine) as session:  # una base mal ubicada y una unidad que ya no existe
        fila = session.exec(select(UnidadPolicial).where(UnidadPolicial.codigo == "TAB-01")).one()
        bien = (fila.latitud, fila.longitud)
        fila.latitud, fila.longitud = 18.865053, -91.724854
        session.add(fila)
        session.add(UnidadPolicial(codigo="TAB-999", base="Vieja", estado="Tabasco", latitud=18.0, longitud=-93.0))
        session.add(UnidadPolicial(codigo="MOTO-PROPIA", base="Mía", estado="Tabasco", latitud=18.0, longitud=-93.0))
        session.commit()
    assert flota.sembrar_flota(engine) == 2
    codigos = {u.id: (u.lat, u.lng) for u in _flota_bd()}
    assert codigos["TAB-01"] == bien and "TAB-999" not in codigos and "MOTO-PROPIA" in codigos
    assert len(codigos) == antes + 1
    with Session(engine) as session:  # no dejar la unidad propia en las demás pruebas
        session.delete(session.exec(select(UnidadPolicial).where(UnidadPolicial.codigo == "MOTO-PROPIA")).one())
        session.commit()


# ---------------------------------------------------------------- vinculación de cámara


class _ProcesoFalso:
    pid = 999_999

    def __init__(self, comando: list[str], **kwargs: Any) -> None:
        self.comando = comando
        self.kwargs = kwargs
        self.stdout = iter(["Modelos listos\n"])
        self._vivo = True

    def poll(self) -> int | None:
        return None if self._vivo else 0

    def wait(self, timeout: float | None = None) -> int:
        self._vivo = False
        return 0


@pytest.fixture
def lanzados(monkeypatch: pytest.MonkeyPatch) -> list[_ProcesoFalso]:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import vinculacion

    procesos: list[_ProcesoFalso] = []

    def _popen(comando: list[str], **kwargs: Any) -> _ProcesoFalso:
        procesos.append(_ProcesoFalso(comando, **kwargs))
        return procesos[-1]

    monkeypatch.setattr(vinculacion.subprocess, "Popen", _popen)
    monkeypatch.setattr(vinculacion.os, "killpg", lambda pid, sig: procesos[-1].wait())
    yield procesos
    vinculacion.SUPERVISOR._actual = None


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"nombre": "Parque", "lat": 20.97, "lng": -89.62},  # sin URL ni demo
        {"url": "ftp://192.168.1.5/video", "nombre": "Parque", "lat": 20.97, "lng": -89.62},
        {"url": "http://192.168.1.5/video", "nombre": "Parque", "lat": 200, "lng": -89.62},
        {"url": "--help", "nombre": "Parque", "lat": 20.97, "lng": -89.62},
    ],
)
def test_vinculacion_rechaza_datos_invalidos(client: Any, lanzados: list, cuerpo: dict) -> None:
    assert client.post(f"{API}/camara-vinculada", json=cuerpo, headers=OP).status_code == 422
    assert lanzados == []


def test_vincular_y_desvincular_camara_del_telefono(client: Any, lanzados: list[_ProcesoFalso]) -> None:
    assert client.get(f"{API}/camara-vinculada", headers=OP).json()["vinculada"] is False
    cuerpo = {
        "url": "http://usuario:secreta@192.168.1.50:8080/video",
        "nombre": "Parque de Santa Lucía",
        "lat": 20.97055,
        "lng": -89.62186,
    }
    r = client.post(f"{API}/camara-vinculada", json=cuerpo, headers=OP)
    assert r.status_code == 200, r.text
    estado = r.json()
    assert estado["vinculada"] and estado["activa"]
    assert estado["sensor_id"] == "CAM-MOVIL-PARQUE-DE-SANTA-LUCIA"
    assert estado["fuente"] == "http://192.168.1.50:8080/video"  # sin credenciales

    comando = lanzados[0].comando
    assert "--source=http://usuario:secreta@192.168.1.50:8080/video" in comando  # el sensor sí la recibe
    assert "--zona-completa" in comando and "--no-preview" in comando
    assert "--lat=20.97055" in comando and lanzados[0].kwargs["start_new_session"] is True

    bitacora = client.get(f"{API}/auditoria", params={"accion": "camara.vinculada"}, headers=OP).json()["items"]
    assert bitacora and "secreta" not in str(bitacora)

    assert client.delete(f"{API}/camara-vinculada", headers=OP).json()["vinculada"] is False


def test_revincular_en_otro_lugar_mueve_la_camara(
    client: Any, sensor: dict[str, str], lanzados: list[_ProcesoFalso]
) -> None:
    """La alerta usa la coordenada que manda el sensor y la cámara queda donde la
    ubicó el operador: nada se ajusta a un centro fijo."""
    cuerpo = {"demo": True, "nombre": "Malecón Carlos A. Madrazo", "lat": 17.995501, "lng": -92.920302}
    client.post(f"{API}/camara-vinculada", json=cuerpo, headers=OP)
    codigo = "CAM-MOVIL-MALECON-CARLOS-A-MADRAZO"
    alerta = _evento(client, sensor, sensor_id=codigo, coordenadas={"lat": 17.995501, "lng": -92.920302})
    assert alerta["coordenadas"] == {"lat": 17.995501, "lng": -92.920302}

    otro = {**cuerpo, "lat": 18.169370, "lng": -93.705229}
    assert "--lat=18.16937" in " ".join(
        client.post(f"{API}/camara-vinculada", json=otro, headers=OP) and lanzados[-1].comando
    )
    camara = next(s for s in client.get(f"{API}/sensores", headers=OP).json() if s["codigo"] == codigo)
    assert camara["coordenadas"] == {"lat": 18.169370, "lng": -93.705229}


def test_video_de_demostracion(client: Any, lanzados: list[_ProcesoFalso]) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services.vinculacion import VIDEO_DEMO

    cuerpo = {"demo": True, "nombre": "Demo", "lat": 20.96706, "lng": -89.62373}
    estado = client.post(f"{API}/camara-vinculada", json=cuerpo, headers=OP).json()
    assert estado["fuente"] == "video de demostración"
    assert f"--source={VIDEO_DEMO}" in lanzados[0].comando


def test_vincular_exige_operador(client: Any) -> None:
    assert client.post(f"{API}/camara-vinculada", json={"demo": True, "nombre": "x" * 5, "lat": 1, "lng": 1}).status_code == 401


def test_geocodificar_usa_google_si_hay_llave(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import geocodificacion

    llamadas: list[str] = []

    class _Resp:
        def __init__(self, url: str) -> None:
            self.url = url

        def raise_for_status(self) -> None: ...

        def json(self) -> Any:
            if "googleapis" in self.url:
                return {"status": "OK", "results": [{"formatted_address": "Malecón, Villahermosa, Tab.",
                                                      "geometry": {"location": {"lat": 17.9955012, "lng": -92.9203021}}}]}
            return [{"display_name": "Malecón (OSM)", "lat": "17.99", "lon": "-92.92"}]

    def _get(url: str, **_: Any) -> _Resp:
        llamadas.append(url)
        return _Resp(url)

    monkeypatch.setattr(geocodificacion.httpx, "get", _get)
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "llave-de-prueba")
    r = client.get(f"{API}/geocodificar", params={"q": "Malecón Villahermosa"}, headers=OP)
    assert r.json() == [{"nombre": "Malecón, Villahermosa, Tab.", "lat": 17.995501, "lng": -92.920302, "fuente": "google"}]

    monkeypatch.delenv("GOOGLE_MAPS_API_KEY")
    r = client.get(f"{API}/geocodificar", params={"q": "Malecón Villahermosa"}, headers=OP)
    assert r.json()[0]["fuente"] == "openstreetmap"
    assert "googleapis" in llamadas[0] and "nominatim" in llamadas[1]


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("17.995501, -92.920302", (17.995501, -92.920302)),
        ("https://www.google.com/maps/place/Malec%C3%B3n/@17.9951,-92.9211,17z/data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d17.995501!4d-92.920302",
         (17.995501, -92.920302)),
        ("https://maps.google.com/?q=18.169370,-93.705229", (18.16937, -93.705229)),
        ("https://www.google.com/maps/@20.9673,-89.6242,15z", (20.9673, -89.6242)),
        ("Parque Juárez, Villahermosa", None),
    ],
)
def test_coordenadas_pegadas_o_de_google_maps(texto: str, esperado: tuple[float, float] | None) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services.geocodificacion import coordenadas_en_texto

    assert coordenadas_en_texto(texto) == esperado


def test_la_ruta_no_cruza_el_agua(monkeypatch: pytest.MonkeyPatch) -> None:
    """Destino a 17 km de la calle (en el mar): la ruta termina en la costa."""
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import atenciones

    class _Resp:
        def raise_for_status(self) -> None: ...

        def json(self) -> dict:
            return {
                "routes": [{"distance": 23000.0, "geometry": {"coordinates": [[-91.8149, 18.6517], [-91.70, 18.71]]}}],
                "waypoints": [{"distance": 0.0}, {"distance": 17279.0}],
            }

    monkeypatch.setattr(atenciones.httpx, "get", lambda *_, **__: _Resp())
    ruta = atenciones.calcular_ruta((18.651739, -91.81492), (18.865053, -91.724854))
    assert ruta.puntos[0] == [18.651739, -91.81492] and ruta.puntos[-1] == [18.71, -91.7]


def test_no_se_vincula_una_camara_en_el_mar(
    client: Any, lanzados: list[_ProcesoFalso], monkeypatch: pytest.MonkeyPatch
) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import geocodificacion

    monkeypatch.setattr(geocodificacion, "distancia_a_calle_m", lambda lat, lng: 17279.0)
    cuerpo = {"demo": True, "nombre": "Ciudad del Carmen", "lat": 18.865053, "lng": -91.724854}
    r = client.post(f"{API}/camara-vinculada", json=cuerpo, headers=OP)
    assert r.status_code == 422 and "17.3 km" in r.text and lanzados == []

    monkeypatch.setattr(geocodificacion, "distancia_a_calle_m", lambda lat, lng: 3.0)
    ok = client.post(f"{API}/camara-vinculada", json={**cuerpo, "lat": 18.651739, "lng": -91.81492}, headers=OP)
    assert ok.status_code == 200 and len(lanzados) == 1


@pytest.mark.parametrize(
    "respuesta",
    [
        {"gps": {"latitude": 18.175438, "longitude": -93.026901, "accuracy": 8.0}},
        {"gps": {"data": [[1760000000000, [18.175438, -93.026901, 8.0]]]}},
    ],
)
def test_ubicacion_automatica_con_el_gps_del_telefono(
    client: Any, monkeypatch: pytest.MonkeyPatch, respuesta: dict
) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import ubicacion_auto

    class _Resp:
        status_code = 200

        def json(self) -> dict:
            return respuesta

    pedidas: list[str] = []
    monkeypatch.setattr(ubicacion_auto.httpx, "get", lambda url, **_: pedidas.append(url) or _Resp())
    r = client.get(f"{API}/ubicacion-automatica", params={"url": "http://yo:clave@192.168.1.50:8080/video"}, headers=OP)
    assert r.status_code == 200, r.text
    assert r.json()["lat"] == 18.175438 and r.json()["lng"] == -93.026901 and r.json()["fuente"] == "gps_camara"
    assert pedidas[0] == "http://192.168.1.50:8080/gps.json"  # sin credenciales en la URL


def test_ubicacion_automatica_por_wifi_con_google(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from PROYECTO_HACKATEC_REGIONAL.BACKEND.services import ubicacion_auto

    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "llave")
    monkeypatch.setattr(ubicacion_auto, "_escanear_wifi", lambda: [{"macAddress": "aa:bb:cc:dd:ee:0%d" % i, "signalStrength": -60} for i in range(5)])

    class _Resp:
        status_code = 200

        def json(self) -> dict:
            return {"location": {"lat": 18.1754381, "lng": -93.0269012}, "accuracy": 32.5}

    enviado: dict = {}
    monkeypatch.setattr(ubicacion_auto.httpx, "post", lambda url, **kw: enviado.update(kw) or _Resp())
    r = client.get(f"{API}/ubicacion-automatica", headers=OP)
    assert r.json() == {"lat": 18.175438, "lng": -93.026901, "precision_m": 32.5, "fuente": "wifi_google"}
    assert enviado["json"]["considerIp"] is False and len(enviado["json"]["wifiAccessPoints"]) == 5

    monkeypatch.setattr(ubicacion_auto.httpx, "post", lambda url, **kw: type("R", (), {"status_code": 403})())
    r = client.get(f"{API}/ubicacion-automatica", headers=OP)
    assert r.status_code == 422 and "Geolocation API" in r.text
