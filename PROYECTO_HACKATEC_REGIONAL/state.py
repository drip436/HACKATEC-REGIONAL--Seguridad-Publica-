"""Estado del panel de supervisión SentinelOps."""

import math
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import TypedDict

import reflex as rx

from . import api_client, campus
from .modelos import (
    ALERTA_VACIA,
    DESTINOS,
    TIPOS,
    TODOS,
    Alerta,
    Camara,
    Cuadrante,
    EntradaBitacora,
    EventoHistorico,
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

    def _agregar_alerta(self, evento: dict):
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
        if alerta["severidad"] == "critica" and alerta["estado"] == "pendiente" and not self.modal_abierto:
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
            except api_client.ErrorAPI as error:
                self.conexion = "Sin API"
                yield rx.toast.error(str(error))
            if self.alertas and not self.modal_abierto:
                self.seleccion_id = self.alertas[0]["id"]
        if self._escucha != ID_PROCESO:
            yield State.escuchar_alertas

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
                async with self:
                    if clase == "estado":
                        self.conexion = str(dato)
                    elif clase == "alerta" and isinstance(dato, dict):
                        self._agregar_alerta(dato)
                        sensor_nuevo = all(c["id"] != dato.get("camara_id") for c in self.camaras)
                    elif clase == "cambio" and isinstance(dato, dict):
                        cambio = dict(dato)
                        self._aplicar_cambio(cambio.pop("id"), **cambio)
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
