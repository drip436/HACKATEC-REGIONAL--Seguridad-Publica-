"""Estado del panel de supervisión SentinelOps."""

import math
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import TypedDict

import httpx
import reflex as rx

from . import api_client
from .modelos import (
    ALERTA_VACIA,
    DESTINOS,
    Alerta,
    Camara,
    EntradaBitacora,
    EventoHistorico,
    normalizar_alerta,
)

# Identifica a este proceso del backend: una escucha registrada por un proceso
# anterior (recarga en caliente, reinicio) ya no existe y debe relanzarse.
ID_PROCESO = uuid.uuid4().hex

MAX_ALERTAS = 60
DIAS_SEMANA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
HORAS_FRANJA = 3
# Vida media (en días) del peso de un evento histórico al priorizar rondines.
DECAIMIENTO_DIAS = 14


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


def _franja(hora: int) -> str:
    inicio = hora - hora % HORAS_FRANJA
    return f"{inicio:02d}:00–{inicio + HORAS_FRANJA:02d}:00"


def _cliente_conectado(token: str) -> bool:
    from . import PROYECTO_HACKATEC_REGIONAL as principal

    espacio = principal.app.event_namespace
    return espacio is None or token in espacio.token_to_sid


class State(rx.State):
    alertas: list[Alerta] = []
    camaras: list[Camara] = []
    historico: list[EventoHistorico] = []
    bitacora: list[EntradaBitacora] = []

    seleccion_id: str = ""
    modal_abierto: bool = False
    destino: str = DESTINOS[0]
    motivo: str = ""
    procesando: bool = False

    conexion: str = "Conectando"
    operador: str = "OP-01"
    modo_simulado: bool = api_client.MOCK

    filtro_tipo: str = "todos"
    filtro_dias: str = "30"

    _escucha: str = ""

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
        validadas = [a for a in self.alertas if a["estado"] != "pendiente"]
        if not validadas:
            return "—"
        return f"{sum(a['estado'] == 'confirmado' for a in validadas) / len(validadas):.0%}"

    @rx.var
    def camaras_activas(self) -> str:
        return f"{sum(c['activa'] for c in self.camaras)}/{len(self.camaras)}"

    # ---- Analítica --------------------------------------------------------

    def _historico_filtrado(self) -> list[tuple[datetime, EventoHistorico]]:
        desde = datetime.now().astimezone() - timedelta(days=int(self.filtro_dias))
        filtrado = []
        for evento in self.historico:
            if self.filtro_tipo != "todos" and evento["tipo"] != self.filtro_tipo:
                continue
            try:
                momento = datetime.fromisoformat(evento["timestamp"]).astimezone()
            except ValueError:
                continue
            if momento >= desde:
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

    @rx.var
    def rondines(self) -> list[Rondin]:
        """Prioriza cuadrante × franja por frecuencia histórica, pesando más lo reciente."""
        ahora = datetime.now().astimezone()
        puntaje: dict[tuple[str, str], float] = defaultdict(float)
        conteo: Counter[tuple[str, str]] = Counter()
        for momento, evento in self._historico_filtrado():
            clave = (evento["cuadrante"], _franja(momento.hour))
            puntaje[clave] += math.exp(-(ahora - momento).days / DECAIMIENTO_DIAS)
            conteo[clave] += 1
        mejores = sorted(puntaje.items(), key=lambda par: par[1], reverse=True)[:5]
        tope = mejores[0][1] if mejores else 1.0
        return [
            {
                "cuadrante": cuadrante,
                "franja": franja,
                "eventos": conteo[(cuadrante, franja)],
                "puntaje": f"{valor:.1f}",
                "ancho": f"{valor / tope:.0%}",
            }
            for (cuadrante, franja), valor in mejores
        ]

    # ---- Carga y alertas en vivo -----------------------------------------

    def _registrar(self, actor: str, accion: str, evento_id: str, detalle: str = "", folio: str = "", timestamp: str = ""):
        timestamp = timestamp or datetime.now().astimezone().isoformat(timespec="seconds")
        self.bitacora.insert(
            0,
            {
                "timestamp": timestamp.replace("T", " ")[:19],
                "actor": actor,
                "accion": accion,
                "evento_id": evento_id,
                "detalle": detalle,
                "folio": folio,
            },
        )

    def _agregar_alerta(self, evento: dict):
        alerta = normalizar_alerta(evento)
        if alerta["snapshot_url"].startswith("/"):
            alerta["snapshot_url"] = api_client.API_URL + alerta["snapshot_url"]
        if not alerta["id"] or self._indice(alerta["id"]) >= 0:
            return
        self.alertas.insert(0, alerta)
        del self.alertas[MAX_ALERTAS:]
        self._registrar(
            f"Edge {alerta['camara_id']}",
            "Detección",
            alerta["id"],
            f"{alerta['tipo_txt']} · severidad {alerta['sev_txt']} · confianza {alerta['confianza_txt']}",
            timestamp=alerta["timestamp"],
        )
        if not self.seleccion_id:
            self.seleccion_id = alerta["id"]
        if alerta["severidad"] == "critica" and alerta["estado"] == "pendiente" and not self.modal_abierto:
            self._abrir(alerta["id"])

    @rx.event
    async def iniciar(self):
        """Carga inicial (una vez por sesión) y arranque de la escucha en vivo."""
        if not self.camaras:
            try:
                self.camaras = await api_client.obtener_camaras()
                self.historico = await api_client.obtener_historico()
                self.bitacora = [
                    {"timestamp": "", "actor": "", "accion": "", "evento_id": "", "detalle": "", "folio": "", **e}
                    for e in await api_client.obtener_auditoria()
                ]
                for evento in reversed(await api_client.obtener_eventos()):
                    self._agregar_alerta(evento)
                if self.alertas and not self.modal_abierto:
                    self.seleccion_id = self.alertas[0]["id"]
            except httpx.HTTPError as error:
                self.conexion = "Sin API"
                yield rx.toast.error(f"No se pudo cargar desde {api_client.API_URL}: {error}")
        if self._escucha != ID_PROCESO:
            yield State.escuchar_alertas

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
                async with self:
                    if clase == "estado":
                        self.conexion = str(dato)
                    elif isinstance(dato, dict):
                        self._agregar_alerta(dato)
        finally:
            async with self:
                self._escucha = ""

    # ---- Validación humana ------------------------------------------------

    def _abrir(self, alerta_id: str):
        self.seleccion_id = alerta_id
        self.destino = DESTINOS[0]
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

    def _resolver(self, alerta_id: str, **cambios):
        i = self._indice(alerta_id)
        if i >= 0:
            self.alertas[i] = {**self.alertas[i], **cambios}
        self.procesando = False
        self.modal_abierto = False

    @rx.event
    async def confirmar(self):
        alerta = self.alerta_sel
        if alerta["estado"] != "pendiente" or self.procesando:
            return
        self.procesando = True
        yield
        try:
            resultado = await api_client.confirmar(alerta["id"], self.operador, self.destino)
        except httpx.HTTPError as error:
            self.procesando = False
            yield rx.toast.error(f"No se pudo despachar: {error}")
            return
        folio = str(resultado.get("folio", ""))
        self._resolver(alerta["id"], estado="confirmado", despacho=self.destino, folio=folio)
        self._registrar(
            f"Operador {self.operador}",
            "Confirmación y despacho",
            alerta["id"],
            f"Despachado a {self.destino}",
            folio,
            str(resultado.get("timestamp", "")),
        )
        yield rx.toast.success(f"Despachado a {self.destino} · folio {folio}")

    @rx.event
    async def descartar(self):
        alerta = self.alerta_sel
        if alerta["estado"] != "pendiente" or self.procesando:
            return
        if not self.motivo:
            yield rx.toast.warning("Selecciona un motivo para descartar la alerta.")
            return
        self.procesando = True
        yield
        try:
            resultado = await api_client.descartar(alerta["id"], self.operador, self.motivo)
        except httpx.HTTPError as error:
            self.procesando = False
            yield rx.toast.error(f"No se pudo descartar: {error}")
            return
        self._resolver(alerta["id"], estado="descartado", despacho=f"Descartada: {self.motivo}")
        self._registrar(
            f"Operador {self.operador}",
            "Descarte",
            alerta["id"],
            f"Motivo: {self.motivo}",
            timestamp=str(resultado.get("timestamp", "")),
        )
        yield rx.toast.info(f"Alerta {alerta['id']} descartada.")

