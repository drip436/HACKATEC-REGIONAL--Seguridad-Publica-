from __future__ import annotations

from enum import StrEnum


class TipoSensor(StrEnum):
    CAMARA_IP = "camara_ip"
    CAMARA_USB = "camara_usb"
    SENSOR_PERIMETRAL = "sensor_perimetral"
    OTRO = "otro"


class EstadoOperativo(StrEnum):
    ACTIVO = "activo"
    MANTENIMIENTO = "mantenimiento"
    FALLA = "falla"
    INACTIVO = "inactivo"


class TipoEvento(StrEnum):
    TRASPASO_PERIMETRO = "traspaso_perimetro"
    AGLOMERACION = "aglomeracion"
    OBJETO_ABANDONADO = "objeto_abandonado"
    MERODEO = "merodeo"


# Vocabulario que emite el Módulo A (Edge AI) -> vocabulario canónico del backend.
ALIAS_TIPO_EVENTO: dict[str, TipoEvento] = {
    "INTRUSION_PERIMETRO": TipoEvento.TRASPASO_PERIMETRO,
    "TRASPASO_PERIMETRO": TipoEvento.TRASPASO_PERIMETRO,
    "AGLOMERACION": TipoEvento.AGLOMERACION,
    "OBJETO_ABANDONADO": TipoEvento.OBJETO_ABANDONADO,
    "MERODEO": TipoEvento.MERODEO,
}


class NivelPrioridad(StrEnum):
    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"
    CRITICA = "critica"


class EstadoValidacion(StrEnum):
    PENDIENTE = "pendiente"
    VALIDADO = "validado"
    DESCARTADO = "descartado_falsa_alarma"


class Dependencia(StrEnum):
    C4_MUNICIPAL = "C4 Municipal"
    PROTECCION_CIVIL = "Proteccion Civil"
    SEGURIDAD_CAMPUS = "Seguridad Campus"

    @property
    def miembro_xroad(self) -> str:
        """Identificador de miembro estilo X-Road: INSTANCIA/CLASE/MIEMBRO/SUBSISTEMA."""
        return _MIEMBROS_XROAD[self]


_MIEMBROS_XROAD: dict[Dependencia, str] = {
    Dependencia.C4_MUNICIPAL: "MX/GOB-MUN/C4/DESPACHO",
    Dependencia.PROTECCION_CIVIL: "MX/GOB-EST/PROTECCION-CIVIL/EMERGENCIAS",
    Dependencia.SEGURIDAD_CAMPUS: "MX/EDU/TECNM/SEGURIDAD-CAMPUS",
}


class EstadoEnvio(StrEnum):
    PENDIENTE = "pendiente"
    ENVIADO = "enviado"
    CONFIRMADO = "confirmado"


class AccionAuditoria(StrEnum):
    SENSOR_REGISTRADO = "sensor.registrado"
    SENSOR_ACTUALIZADO = "sensor.actualizado"
    EVENTO_RECIBIDO = "evento.recibido"
    EVENTO_VALIDADO = "evento.validado"
    EVENTO_DESCARTADO = "evento.descartado"
    DESPACHO_EMITIDO = "despacho.emitido"
    DESPACHO_CONFIRMADO = "despacho.confirmado"
    DESPACHO_FALLIDO = "despacho.fallido"
    DESPACHO_REINTENTADO = "despacho.reintentado"
    FEDERACION_RECIBIDA = "federacion.recibida"
    FEDERACION_RECHAZADA = "federacion.rechazada"
    AUDITORIA_CONSULTADA = "auditoria.consultada"
