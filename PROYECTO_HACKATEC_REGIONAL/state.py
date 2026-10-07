"""Estado del panel de supervisión SentinelOps."""

import asyncio
import math
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import TypedDict

import reflex as rx

from . import api_client, campus, mock
from .modelos import (
    ALERTA_VACIA,
    DESTINOS,
    TIPOS,
    TODOS,
    Alerta,
    Atencion,
    Camara,
    Cuadrante,
    EntradaBitacora,
    EventoHistorico,
    PuntoMapa,
    a_local,
    con_derivados,
    normalizar_alerta,
)

DESTINO_INICIAL = next(iter(DESTINOS))

# Identifica a este proceso del backend: una escucha registrada por un proceso
# anterior (recarga en caliente, reinicio) ya no existe y debe relanzarse.
ID_PROCESO = uuid.uuid4().hex

MAX_ALERTAS = 60
DIAS_SEMANA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
HORAS_FRANJA = 3
# Vida media (en días) del peso de un evento histórico al priorizar rondines.
DECAIMIENTO_DIAS = 14
# Severidades que se tratan como violencia: el mapa vuela al lugar al instante.
SEVERIDADES_VIOLENCIA = ("alta", "critica")
INTERVALO_CAMARA_S = 1.5
CAMARA_SIN_DATOS_S = 10.0


class BarraHora(TypedDict):
    hora: str
    eventos: int


class CeldaMatriz(TypedDict):
    franja: str
    eventos: int
    color: str


class FilaMatriz(TypedDict):
    dia: str
    celdas: list[CeldaMatriz]


class Rondin(TypedDict):
    cuadrante: str
    franja: str
    eventos: int
    puntaje: str
    ancho: str


class PuntoRondin(TypedDict):
    lat: float
    lng: float
    texto: str


def _franja(hora: int) -> str:
    inicio = hora - hora % HORAS_FRANJA
    return f"{inicio:02d}:00–{inicio + HORAS_FRANJA:02d}:00"


def _ms_de(timestamp: str) -> int:
    momento = a_local(timestamp)
    return int(momento.timestamp() * 1000) if momento else 0


def _punto(alerta: Alerta, caso: str) -> PuntoMapa:
    return {
        "id": alerta["id"],
        "lat": alerta["lat"],
        "lng": alerta["lng"],
        "severidad": alerta["severidad"],
        "tipo_txt": alerta["tipo_txt"],
        "sev_txt": alerta["sev_txt"],
        "camara_id": alerta["camara_id"],
        "hora": alerta["hora"],
        "caso": caso,
    }


def _cliente_conectado(token: str) -> bool:
    from . import PROYECTO_HACKATEC_REGIONAL as principal

    espacio = principal.app.event_namespace
    return espacio is None or token in espacio.token_to_sid


class State(rx.State):
    alertas: list[Alerta] = []
    camaras: list[Camara] = []
    historico: list[EventoHistorico] = []
    bitacora: list[EntradaBitacora] = []
    integridad: str = ""
    centro: list[float] = campus.CENTRO_DEFECTO
    cuadrantes: list[Cuadrante] = campus.calcular_cuadrantes([])

    seleccion_id: str = ""
    modal_abierto: bool = False
    destino: str = DESTINO_INICIAL
    motivo: str = ""
    procesando: bool = False

    conexion: str = "Conectando"
    operador: str = "OP-01"
    modo_simulado: bool = api_client.MOCK

    filtro_tipo: str = TODOS
    filtro_dias: str = "30"

    _escucha: str = ""

    # Atención en campo: unidades enviadas y su animación en el mapa.
    atenciones: list[Atencion] = []
    # [lat, lng, n]: el mapa vuela a (lat, lng) cada vez que cambia n.
    mapa_foco: list[float] = []

    # Cámara vinculada (sensor Edge AI lanzado por el backend) y su video anotado.
    cam_vinculada: bool = False
    cam_activa: bool = False
    cam_nombre: str = ""
    cam_fuente: str = ""
    cam_lat: float = 0.0
    cam_lng: float = 0.0
    cam_error: str = ""
    edge_en_linea: bool = False
    edge_nivel: str = ""
    edge_regla: str = ""
    edge_personas: int = 0
    edge_fps: float = 0.0
    url_transmision: str = api_client.url_transmision()
    _vigia: str = ""

    # Formulario de vinculación.
    dialogo_camara: bool = False
    form_url: str = ""
    form_demo: bool = False
    form_nombre: str = ""
    form_lat: str = str(campus.CENTRO_DEFECTO[0])
    form_lng: str = str(campus.CENTRO_DEFECTO[1])
    vinculando: bool = False

    # ---- Selección y KPIs -------------------------------------------------

    def _indice(self, alerta_id: str) -> int:
        return next((i for i, a in enumerate(self.alertas) if a["id"] == alerta_id), -1)

    @rx.var
    def alerta_sel(self) -> Alerta:
        i = self._indice(self.seleccion_id)
        return self.alertas[i] if i >= 0 else ALERTA_VACIA

    @rx.var
    def alertas_pendientes(self) -> list[Alerta]:
        return [a for a in self.alertas if a["estado"] == "pendiente"]

    @rx.var
    def total_pendientes(self) -> int:
        return len(self.alertas_pendientes)

    @rx.var
    def total_criticas(self) -> int:
        return sum(a["severidad"] == "critica" for a in self.alertas_pendientes)

    @rx.var
    def total_despachadas(self) -> int:
        return sum(a["estado"] == "confirmado" for a in self.alertas)

    @rx.var
    def tasa_confirmacion(self) -> str:
        resueltas = [a for a in self.alertas if a["estado"] != "pendiente"]
        if not resueltas:
            return "—"
        return f"{sum(a['estado'] != 'descartado' for a in resueltas) / len(resueltas):.0%}"

    @rx.var
    def camaras_activas(self) -> str:
        return f"{sum(c['activa'] for c in self.camaras)}/{len(self.camaras)}"

    # ---- Analítica --------------------------------------------------------

    def _historico_filtrado(self) -> list[tuple[datetime, EventoHistorico]]:
        desde = datetime.now().astimezone() - timedelta(days=int(self.filtro_dias))
        filtrado = []
        for evento in self.historico:
            if self.filtro_tipo != TODOS and TIPOS.get(evento["tipo"]) != self.filtro_tipo:
                continue
            momento = a_local(evento["timestamp"])
            if momento and momento >= desde:
                filtrado.append((momento, evento))
        return filtrado

    @rx.var
    def total_historico(self) -> int:
        return len(self._historico_filtrado())

    @rx.var
    def puntos_calor(self) -> list[list[float]]:
        return [[e["lat"], e["lng"], 1.0] for _, e in self._historico_filtrado()]

    @rx.var
    def eventos_por_hora(self) -> list[BarraHora]:
        conteo = Counter(momento.hour for momento, _ in self._historico_filtrado())
        return [{"hora": f"{h:02d}", "eventos": conteo[h]} for h in range(24)]

    @rx.var
    def franja_critica(self) -> str:
        conteo = Counter(_franja(momento.hour) for momento, _ in self._historico_filtrado())
        return conteo.most_common(1)[0][0] if conteo else "—"

    @rx.var
    def matriz_dia_franja(self) -> list[FilaMatriz]:
        conteo = Counter((m.weekday(), _franja(m.hour)) for m, _ in self._historico_filtrado())
        maximo = max(conteo.values(), default=0) or 1
        franjas = [_franja(h) for h in range(0, 24, HORAS_FRANJA)]
        return [
            {
                "dia": dia,
                "celdas": [
                    {
                        "franja": franja,
                        "eventos": conteo[(i, franja)],
                        # Secuencial de un solo tono: más eventos, más intenso.
                        "color": f"rgba(56, 189, 248, {0.06 + 0.94 * conteo[(i, franja)] / maximo:.2f})",
                    }
                    for franja in franjas
                ],
            }
            for i, dia in enumerate(DIAS_SEMANA)
        ]

    def _mejores_rondines(self) -> list[tuple[str, str, float, int, float, float]]:
        """Top 5 de lugar × franja por frecuencia histórica, pesando más lo reciente.

        El lugar es la cámara más cercana al evento (o el cuadrante si aún no hay
        inventario). Devuelve (lugar, franja, puntaje, eventos, lat, lng), donde
        lat/lng es el centro de los eventos de ese grupo: ahí conviene el rondín.
        """
        ahora = datetime.now().astimezone()
        puntaje: dict[tuple[str, str], float] = defaultdict(float)
        conteo: Counter[tuple[str, str]] = Counter()
        suma_lat: dict[tuple[str, str], float] = defaultdict(float)
        suma_lng: dict[tuple[str, str], float] = defaultdict(float)
        for momento, evento in self._historico_filtrado():
            lugar = campus.zona_de(evento["lat"], evento["lng"], self.camaras, evento["cuadrante"])
            clave = (lugar, _franja(momento.hour))
            puntaje[clave] += math.exp(-(ahora - momento).days / DECAIMIENTO_DIAS)
            conteo[clave] += 1
            suma_lat[clave] += evento["lat"]
            suma_lng[clave] += evento["lng"]
        resultado = []
        for (cuadrante, franja), valor in sorted(puntaje.items(), key=lambda par: par[1], reverse=True)[:5]:
            n = conteo[(cuadrante, franja)]
            lat = suma_lat[(cuadrante, franja)] / n
            lng = suma_lng[(cuadrante, franja)] / n
            resultado.append((cuadrante, franja, valor, n, lat, lng))
        return resultado

    @rx.var
    def rondines(self) -> list[Rondin]:
        mejores = self._mejores_rondines()
        tope = mejores[0][2] if mejores else 1.0
        return [
            {
                "cuadrante": cuadrante,
                "franja": franja,
                "eventos": eventos,
                "puntaje": f"{valor:.1f}",
                "ancho": f"{valor / tope:.0%}",
            }
            for cuadrante, franja, valor, eventos, _, _ in mejores
        ]

    @rx.var
    def puntos_rondin(self) -> list[PuntoRondin]:
        """Puntos azules del mapa: un punto por lugar del top de rondines, con sus franjas."""
        por_lugar: dict[str, list[tuple[str, int, float, float]]] = defaultdict(list)
        for lugar, franja, _, eventos, lat, lng in self._mejores_rondines():
            por_lugar[lugar].append((franja, eventos, lat, lng))
        puntos: list[PuntoRondin] = []
        for lugar, grupos in por_lugar.items():
            total = sum(eventos for _, eventos, _, _ in grupos)
            franjas = ", ".join(franja for franja, _, _, _ in grupos)
            puntos.append(
                {
                    "lat": round(sum(lat * e for _, e, lat, _ in grupos) / total, 6),
                    "lng": round(sum(lng * e for _, e, _, lng in grupos) / total, 6),
                    "texto": f"Rondín sugerido · {lugar} · {franjas} · {total} eventos",
                }
            )
        return puntos

    @rx.var
    def hay_datos_simulados(self) -> bool:
        """True si el mapa muestra cámaras del simulador (alertas sintéticas)."""
        return self.modo_simulado or any(c["id"] in mock.CODIGOS_DEMO for c in self.camaras)

    # ---- Carga y alertas en vivo -----------------------------------------

    def _registrar(self, actor: str, accion: str, entidad: str, detalle: str = "", sello: str = ""):
        """Bitácora local, solo en modo simulado: con backend la lleva el servidor."""
        if not api_client.MOCK:
            return
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.bitacora.insert(
            0,
            {"timestamp": ahora, "actor": actor, "accion": accion, "entidad": entidad, "detalle": detalle, "sello": sello},
        )

    def _fijar_camaras(self, camaras: list[Camara]):
        """Guarda el inventario y recalcula la geometría que depende de él."""
        self.camaras = camaras
        self.centro = campus.centro_de(camaras)
        self.cuadrantes = campus.calcular_cuadrantes(camaras)
        self.alertas = [
            {**a, "cuadrante": campus.cuadrante_de(a["lat"], a["lng"], self.cuadrantes)} for a in self.alertas
        ]
        self._fijar_historico(self.historico)

    def _fijar_historico(self, historico: list[EventoHistorico]):
        self.historico = [
            {**e, "cuadrante": campus.cuadrante_de(e["lat"], e["lng"], self.cuadrantes)} for e in historico
        ]

    def _agregar_alerta(self, evento: dict, en_vivo: bool = False):
        alerta = normalizar_alerta(evento)
        if not alerta["id"] or self._indice(alerta["id"]) >= 0:
            return
        alerta["cuadrante"] = campus.cuadrante_de(alerta["lat"], alerta["lng"], self.cuadrantes)
        self.alertas.insert(0, alerta)
        del self.alertas[MAX_ALERTAS:]
        self._registrar(
            f"sensor:{alerta['camara_id']}",
            "evento.recibido",
            f"evento {alerta['id']}",
            f"{alerta['tipo_txt']} · severidad {alerta['sev_txt']} · confianza {alerta['confianza_txt']}",
        )
        if not self.seleccion_id:
            self.seleccion_id = alerta["id"]
        if en_vivo and alerta["severidad"] in SEVERIDADES_VIOLENCIA:
            self._enfocar(alerta["lat"], alerta["lng"])
        # La ventana se abre sola solo con la primera alerta de la cámara: si ya hay otra
        # pendiente o una unidad en camino, reabrirla taparía el mapa a cada detección.
        if (
            alerta["severidad"] == "critica"
            and alerta["estado"] == "pendiente"
            and not self.modal_abierto
            and not self._camara_ocupada(alerta["camara_id"], excepto=alerta["id"])
        ):
            self._abrir(alerta["id"])

    def _aplicar_cambio(self, alerta_id: str, **cambios):
        i = self._indice(alerta_id)
        if i < 0:
            return
        # Un aviso tardío de "validado" no debe pisar un despacho ya confirmado.
        if self.alertas[i]["estado"] == "confirmado" and cambios.get("estado") == "validado":
            return
        self.alertas[i] = con_derivados({**self.alertas[i], **cambios})

    @rx.event
    async def iniciar(self):
        """Carga inicial (una vez por sesión) y arranque de la escucha en vivo."""
        if not self.camaras and not self.alertas:
            try:
                self._fijar_camaras(await api_client.obtener_camaras())
                for evento in reversed(await api_client.obtener_eventos()):
                    self._agregar_alerta(evento)
                self._fijar_historico(await api_client.obtener_historico())
                self.atenciones = await api_client.obtener_atenciones()
            except api_client.ErrorAPI as error:
                self.conexion = "Sin API"
                yield rx.toast.error(str(error))
            if self.alertas and not self.modal_abierto:
                self.seleccion_id = self.alertas[0]["id"]
        if self._escucha != ID_PROCESO:
            yield State.escuchar_alertas
        if self._vigia != ID_PROCESO:
            yield State.vigilar_camara

    @rx.event
    async def cargar_historico(self):
        """Refresca el histórico al entrar a Analítica."""
        try:
            self._fijar_historico(await api_client.obtener_historico())
        except api_client.ErrorAPI as error:
            yield rx.toast.error(str(error))

    @rx.event
    async def cargar_bitacora(self):
        if api_client.MOCK:
            return
        try:
            self.bitacora = await api_client.obtener_auditoria()
        except api_client.ErrorAPI as error:
            yield rx.toast.error(str(error))

    @rx.event
    async def verificar_bitacora(self):
        if api_client.MOCK:
            self.integridad = "Sin verificación en modo simulado"
            return
        try:
            resultado = await api_client.verificar_auditoria()
        except api_client.ErrorAPI as error:
            yield rx.toast.error(str(error))
            return
        if resultado["integra"]:
            self.integridad = f"Cadena íntegra · {resultado['registros_verificados']} registros verificados"
        else:
            self.integridad = f"Cadena alterada en el registro {resultado.get('primer_registro_invalido')}: {resultado.get('motivo')}"

    @rx.event(background=True)
    async def escuchar_alertas(self):
        async with self:
            if self._escucha == ID_PROCESO:
                return
            self._escucha = ID_PROCESO
            token = self.router.session.client_token
        try:
            async for clase, dato in api_client.flujo_alertas():
                if not _cliente_conectado(token):
                    break
                sensor_nuevo = False
                aviso = ""
                async with self:
                    if clase == "estado":
                        self.conexion = str(dato)
                    elif clase == "alerta" and isinstance(dato, dict):
                        self._agregar_alerta(dato, en_vivo=True)
                        sensor_nuevo = all(c["id"] != dato.get("camara_id") for c in self.camaras)
                    elif clase == "cambio" and isinstance(dato, dict):
                        cambio = dict(dato)
                        self._aplicar_cambio(cambio.pop("id"), **cambio)
                    elif clase == "atencion" and isinstance(dato, dict):
                        if self._aplicar_atencion(dato):
                            aviso = f"{dato['unidad']} llegó al lugar: caso atendido y resuelto."
                if aviso:
                    # Fuera del `async with`: no se emite con el estado bloqueado.
                    yield rx.toast.success(aviso)
                if sensor_nuevo:
                    # El backend autorregistra sensores desconocidos: se relee el inventario.
                    try:
                        camaras = await api_client.obtener_camaras()
                    except api_client.ErrorAPI:
                        continue
                    async with self:
                        self._fijar_camaras(camaras)
        finally:
            async with self:
                self._escucha = ""

    # ---- Mapa y atención en campo -----------------------------------------

    def _enfocar(self, lat: float, lng: float):
        siguiente = (self.mapa_foco[2] + 1) if len(self.mapa_foco) == 3 else 1
        self.mapa_foco = [lat, lng, siguiente]

    def _aplicar_atencion(self, atencion: Atencion) -> bool:
        """Inserta o actualiza una atención. True si la unidad acaba de llegar."""
        for i, actual in enumerate(self.atenciones):
            if actual["id"] == atencion["id"]:
                llego = actual["estado"] != "resuelto" and atencion["estado"] == "resuelto"
                self.atenciones[i] = atencion
                return llego
        self.atenciones.insert(0, atencion)
        return False

    def _camara_ocupada(self, camara_id: str, excepto: str) -> bool:
        """True si la cámara ya tiene otra alerta crítica pendiente o una unidad en camino.
        (Un merodeo previo no cuenta: la escalada a crítica sí debe abrir la ventana.)"""
        en_camino = {a["evento_id"] for a in self.atenciones if a["estado"] == "en_camino"}
        return any(
            a["camara_id"] == camara_id
            and a["id"] != excepto
            and ((a["estado"] == "pendiente" and a["severidad"] == "critica") or a["id"] in en_camino)
            for a in self.alertas
        )

    def _caso(self, alerta_id: str) -> str:
        for atencion in self.atenciones:
            if atencion["evento_id"] == alerta_id:
                return atencion["estado"]
        return "pendiente"

    @rx.var
    def puntos_mapa(self) -> list[PuntoMapa]:
        """Un punto por cámara con el estado de su incidente:

        1. Unidad en camino -> ese caso (rojo, con la patrulla acercándose).
        2. Última atención resuelta y sin alertas posteriores a la llegada -> verde.
           Las alertas que llegaron mientras la unidad iba en camino son el mismo incidente.
        3. Si no, la alerta pendiente más reciente -> rojo (incidente nuevo).
        """
        por_evento = {a["evento_id"]: a for a in self.atenciones}
        por_camara: dict[str, list[Alerta]] = defaultdict(list)
        for alerta in self.alertas:  # de la más reciente a la más antigua
            por_camara[alerta["camara_id"]].append(alerta)

        puntos: list[PuntoMapa] = []
        for alertas in por_camara.values():
            atendidas = [(a, por_evento[a["id"]]) for a in alertas if a["id"] in por_evento]
            en_camino = next(((a, at) for a, at in atendidas if at["estado"] == "en_camino"), None)
            if en_camino:
                puntos.append(_punto(en_camino[0], "en_camino"))
                continue
            resuelta = next(((a, at) for a, at in atendidas if at["estado"] == "resuelto"), None)
            pendientes = [a for a in alertas if a["estado"] == "pendiente" and a["id"] not in por_evento]
            if resuelta:
                llegada = resuelta[1]["llegada_real_ms"] or resuelta[1]["llegada_ms"]
                pendientes = [a for a in pendientes if _ms_de(a["timestamp"]) > llegada]
                if not pendientes:
                    puntos.append(_punto(resuelta[0], "resuelto"))
                    continue
            if pendientes:
                puntos.append(_punto(pendientes[0], "pendiente"))
        return puntos

    @rx.var
    def caso_sel(self) -> str:
        return self._caso(self.seleccion_id) if self.seleccion_id else ""

    @rx.var
    def unidad_sel(self) -> str:
        for atencion in self.atenciones:
            if atencion["evento_id"] == self.seleccion_id:
                return f"{atencion['unidad']} · {atencion['distancia_m'] / 1000:.1f} km" + (
                    " por calles" if atencion["por_calles"] else " en línea recta"
                )
        return ""

    @rx.var
    def camaras_mapa(self) -> list[Camara]:
        """Inventario + la cámara vinculada (antes de su primera alerta ya se ve en el mapa)."""
        if not self.cam_vinculada or any(c["nombre"] == self.cam_nombre for c in self.camaras):
            return self.camaras
        return [*self.camaras, {"id": "vinculada", "nombre": self.cam_nombre, "lat": self.cam_lat, "lng": self.cam_lng, "activa": True}]

    @rx.event
    async def atender(self):
        """Atender la alerta seleccionada: la valida y envía una patrulla al lugar."""
        alerta = self.alerta_sel
        if not alerta["id"] or self.procesando or self._caso(alerta["id"]) != "pendiente":
            return
        self.procesando = True
        yield
        try:
            atencion = await api_client.atender(alerta["id"], self.operador)
        except api_client.ErrorAPI as error:
            self.procesando = False
            yield rx.toast.error(f"No se pudo enviar la unidad: {error}")
            return
        self._aplicar_atencion(atencion)
        self._aplicar_cambio(alerta["id"], estado="validado")
        self.procesando = False
        self.modal_abierto = False  # el mapa encuadra la ruta de la unidad por su cuenta
        segundos = max(0, round((atencion["llegada_ms"] - atencion["inicio_ms"]) / 1000))
        yield rx.toast.info(f"{atencion['unidad']} en camino ({atencion['distancia_m'] / 1000:.1f} km, ~{segundos} s).")

    @rx.event
    def marcar_pendiente(self):
        """El operador lo deja en la cola para atenderlo después."""
        alerta_id = self.alerta_sel["id"]
        self.modal_abierto = False
        if alerta_id:
            return rx.toast.info(f"Alerta {alerta_id} queda pendiente.")

    # ---- Cámara vinculada -------------------------------------------------

    def _aplicar_estado_camara(self, camara: dict, edge: dict | None):
        self.cam_vinculada = bool(camara.get("vinculada"))
        self.cam_activa = bool(camara.get("activa"))
        self.cam_nombre = camara.get("nombre") or ""
        self.cam_fuente = camara.get("fuente") or ""
        self.cam_lat = float(camara.get("lat") or 0.0)
        self.cam_lng = float(camara.get("lng") or 0.0)
        caido = self.cam_vinculada and not self.cam_activa
        self.cam_error = " / ".join(camara.get("ultimas_lineas", [])[-3:]) if caido else ""
        vigente = (
            self.cam_activa
            and bool(edge)
            and edge.get("en_linea")
            and time.time() - edge.get("actualizado", 0) < CAMARA_SIN_DATOS_S
        )
        self.edge_en_linea = bool(vigente)
        if vigente:
            self.edge_nivel = edge.get("nivel") or ""
            self.edge_regla = edge.get("regla") or ""
            self.edge_personas = int(edge.get("personas") or 0)
            self.edge_fps = float(edge.get("fps") or 0.0)

    @rx.event(background=True)
    async def vigilar_camara(self):
        """Consulta el estado de la cámara vinculada mientras la pestaña siga abierta."""
        async with self:
            if self._vigia == ID_PROCESO:
                return
            self._vigia = ID_PROCESO
            token = self.router.session.client_token
        try:
            while _cliente_conectado(token):
                try:
                    camara = await api_client.estado_camara()
                except api_client.ErrorAPI:
                    camara = {"vinculada": False}
                edge = await api_client.estado_edge() if camara.get("activa") else None
                async with self:
                    self._aplicar_estado_camara(camara, edge)
                await asyncio.sleep(INTERVALO_CAMARA_S)
        finally:
            async with self:
                self._vigia = ""

    @rx.event
    def abrir_dialogo_camara(self):
        self.dialogo_camara = True

    @rx.event
    def cambiar_dialogo_camara(self, abierto: bool):
        if abierto or not self.vinculando:
            self.dialogo_camara = abierto

    @rx.event
    def set_form_url(self, valor: str):
        self.form_url = valor

    @rx.event
    def set_form_demo(self, valor: bool):
        self.form_demo = bool(valor)

    @rx.event
    def set_form_nombre(self, valor: str):
        self.form_nombre = valor

    @rx.event
    def set_form_lat(self, valor: str):
        self.form_lat = valor

    @rx.event
    def set_form_lng(self, valor: str):
        self.form_lng = valor

    @rx.event
    def usar_mi_ubicacion(self):
        """Pide al navegador la ubicación actual (requiere permiso del usuario)."""
        return rx.call_script(
            "new Promise((ok) => navigator.geolocation"
            " ? navigator.geolocation.getCurrentPosition("
            "(p) => ok([p.coords.latitude, p.coords.longitude]), () => ok(null), {timeout: 10000})"
            " : ok(null))",
            callback=State.recibir_ubicacion,
        )

    @rx.event
    def recibir_ubicacion(self, coords: list[float] | None):
        if not coords:
            return rx.toast.warning("El navegador no compartió la ubicación; escríbela a mano.")
        self.form_lat, self.form_lng = f"{coords[0]:.6f}", f"{coords[1]:.6f}"

    @rx.event
    async def vincular_camara(self):
        try:
            lat, lng = float(self.form_lat), float(self.form_lng)
        except ValueError:
            yield rx.toast.error("Latitud y longitud deben ser números.")
            return
        if len(self.form_nombre.strip()) < 3:
            yield rx.toast.error("Escribe el nombre del lugar que vigila la cámara.")
            return
        self.vinculando = True
        yield
        try:
            camara = await api_client.vincular_camara(
                url=self.form_url.strip(), demo=self.form_demo, nombre=self.form_nombre.strip(), lat=lat, lng=lng
            )
        except api_client.ErrorAPI as error:
            self.vinculando = False
            detalle = "; ".join(e.get("mensaje", "") for e in error.detalle.get("errores", [])) if error.detalle else ""
            yield rx.toast.error(f"No se pudo vincular: {detalle or error}")
            return
        self.vinculando = False
        self.dialogo_camara = False
        self._aplicar_estado_camara(camara, None)
        self._enfocar(lat, lng)
        yield rx.toast.success(f"Cámara vinculada: {self.form_nombre.strip()}. Cargando la IA…")

    @rx.event
    async def desvincular_camara(self):
        try:
            camara = await api_client.desvincular_camara()
        except api_client.ErrorAPI as error:
            yield rx.toast.error(str(error))
            return
        self._aplicar_estado_camara(camara, None)
        yield rx.toast.info("Cámara desvinculada.")

    # ---- Validación humana ------------------------------------------------

    def _abrir(self, alerta_id: str):
        self.seleccion_id = alerta_id
        self.destino = DESTINO_INICIAL
        self.motivo = ""
        self.modal_abierto = True

    @rx.event
    def seleccionar(self, alerta_id: str):
        self.seleccion_id = alerta_id

    @rx.event
    def abrir_alerta(self, alerta_id: str):
        if self._indice(alerta_id) >= 0:
            self._abrir(alerta_id)

    @rx.event
    def cambiar_modal(self, abierto: bool):
        # No se cierra a media petición: el operador debe ver el resultado.
        if abierto or not self.procesando:
            self.modal_abierto = abierto

    @rx.event
    def set_destino(self, destino: str):
        self.destino = destino

    @rx.event
    def set_motivo(self, motivo: str):
        self.motivo = motivo

    @rx.event
    def set_filtro_tipo(self, tipo: str | list[str]):
        self.filtro_tipo = str(tipo)

    @rx.event
    def set_filtro_dias(self, dias: str | list[str]):
        self.filtro_dias = str(dias)

    @rx.event
    async def confirmar(self):
        """Valida (si sigue pendiente) y despacha. Son dos pasos en el backend: si el
        despacho falla, el evento queda validado y se puede reintentar desde el modal."""
        alerta = self.alerta_sel
        if alerta["estado"] not in ("pendiente", "validado") or self.procesando:
            return
        alerta_id, destino = alerta["id"], self.destino
        self.procesando = True
        yield
        try:
            if alerta["estado"] == "pendiente":
                self._aplicar_cambio(alerta_id, **await api_client.validar(alerta_id, self.operador, confirma=True))
                self._registrar(f"operador:{self.operador}", "evento.validado", f"evento {alerta_id}")
            resultado = await api_client.despachar(alerta_id, self.operador, destino)
        except api_client.ErrorAPI as error:
            self.procesando = False
            yield rx.toast.error(f"No se completó el despacho: {error}")
            return
        self._aplicar_cambio(alerta_id, **resultado)
        self.procesando = False
        if resultado["estado"] != "confirmado":
            yield rx.toast.warning(f"Despacho a {destino} emitido, pero sin acuse. Puedes reintentar.")
            return
        self.modal_abierto = False
        self._registrar(
            f"operador:{self.operador}", "despacho.confirmado", f"evento {alerta_id}", f"Despachado a {destino}", resultado["folio"]
        )
        yield rx.toast.success(f"Despachado a {destino} · acuse {resultado['folio']}")

    @rx.event
    async def descartar(self):
        alerta = self.alerta_sel
        if alerta["estado"] != "pendiente" or self.procesando:
            return
        if not self.motivo:
            yield rx.toast.warning("Selecciona un motivo para descartar la alerta.")
            return
        alerta_id, motivo = alerta["id"], self.motivo
        self.procesando = True
        yield
        try:
            resultado = await api_client.validar(alerta_id, self.operador, confirma=False, notas=motivo)
        except api_client.ErrorAPI as error:
            self.procesando = False
            yield rx.toast.error(f"No se pudo descartar: {error}")
            return
        self._aplicar_cambio(alerta_id, **resultado)
        self.procesando = False
        self.modal_abierto = False
        self._registrar(f"operador:{self.operador}", "evento.descartado", f"evento {alerta_id}", f"Motivo: {motivo}")
        yield rx.toast.info(f"Alerta {alerta_id} descartada.")
