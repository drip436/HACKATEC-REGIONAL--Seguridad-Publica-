-- =============================================================================
-- SentinelOps · Esquema de base de datos para Supabase (PostgreSQL)
--
-- Cómo usarlo: Supabase → SQL Editor → New query → pegar todo → Run.
-- Es idempotente: se puede ejecutar más de una vez sin romper nada.
--
-- Debe coincidir con PROYECTO_HACKATEC_REGIONAL/BACKEND/models/tablas.py.
-- (El backend también crea todo esto solo al arrancar; este script sirve para
-- prepararlo de antemano y revisarlo en Supabase.)
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. Inventario de cámaras y sensores
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS camaras_sensores (
    id                SERIAL PRIMARY KEY,
    codigo            VARCHAR(64)  NOT NULL,
    nombre_ubicacion  VARCHAR(200) NOT NULL,
    tipo_sensor       VARCHAR(32)  NOT NULL,
    estado_operativo  VARCHAR(32)  NOT NULL,
    ip_rtsp_url       VARCHAR(500),
    latitud           DOUBLE PRECISION NOT NULL,
    longitud          DOUBLE PRECISION NOT NULL,
    creado_en         TIMESTAMPTZ  NOT NULL,
    actualizado_en    TIMESTAMPTZ  NOT NULL,
    CONSTRAINT ck_camaras_sensores_tipo_sensor
        CHECK (tipo_sensor IN ('camara_ip', 'camara_usb', 'sensor_perimetral', 'otro')),
    CONSTRAINT ck_camaras_sensores_estado_operativo
        CHECK (estado_operativo IN ('activo', 'mantenimiento', 'falla', 'inactivo')),
    CONSTRAINT ck_camaras_sensores_lat CHECK (latitud BETWEEN -90 AND 90),
    CONSTRAINT ck_camaras_sensores_lng CHECK (longitud BETWEEN -180 AND 180)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_camaras_sensores_codigo ON camaras_sensores (codigo);

-- -----------------------------------------------------------------------------
-- 2. Eventos detectados por el Edge AI (solo metadatos, nunca biometría)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eventos_detectados (
    id                   SERIAL PRIMARY KEY,
    sensor_id            INTEGER      NOT NULL REFERENCES camaras_sensores (id),
    tipo_evento          VARCHAR(32)  NOT NULL,
    nivel_prioridad      VARCHAR(16)  NOT NULL,
    estado_validacion    VARCHAR(32)  NOT NULL,
    operador_id          VARCHAR(64),
    notas_validacion     VARCHAR(500),
    metadata_json        JSON         NOT NULL,
    evidencia_url        VARCHAR(300),
    latitud              DOUBLE PRECISION NOT NULL,
    longitud             DOUBLE PRECISION NOT NULL,
    payload_hash_sha256  VARCHAR(64)  NOT NULL UNIQUE,  -- llave de idempotencia
    fecha_deteccion      TIMESTAMPTZ  NOT NULL,
    recibido_en          TIMESTAMPTZ  NOT NULL,
    validado_en          TIMESTAMPTZ,
    CONSTRAINT ck_eventos_detectados_tipo_evento
        CHECK (tipo_evento IN ('traspaso_perimetro', 'aglomeracion', 'objeto_abandonado', 'merodeo')),
    CONSTRAINT ck_eventos_detectados_nivel_prioridad
        CHECK (nivel_prioridad IN ('baja', 'media', 'alta', 'critica')),
    CONSTRAINT ck_eventos_detectados_estado_validacion
        CHECK (estado_validacion IN ('pendiente', 'validado', 'descartado_falsa_alarma'))
);
CREATE INDEX IF NOT EXISTS ix_eventos_detectados_sensor_id       ON eventos_detectados (sensor_id);
CREATE INDEX IF NOT EXISTS ix_eventos_detectados_fecha_deteccion ON eventos_detectados (fecha_deteccion);
CREATE INDEX IF NOT EXISTS ix_eventos_estado_fecha               ON eventos_detectados (estado_validacion, fecha_deteccion);

-- -----------------------------------------------------------------------------
-- 3. Despachos federados (X-Road simulado) hacia dependencias
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS despachos_interoperables (
    id                       SERIAL PRIMARY KEY,
    evento_id                INTEGER      NOT NULL REFERENCES eventos_detectados (id),
    dependencia_destino      VARCHAR(64)  NOT NULL,
    estado_envio             VARCHAR(16)  NOT NULL,
    solicitado_por           VARCHAR(64)  NOT NULL,
    instrucciones            VARCHAR(500),
    token_interoperabilidad  TEXT,
    token_jti                VARCHAR(64) UNIQUE,  -- anti-replay
    payload_hash             VARCHAR(64),
    acuse_recibo             JSON,
    timestamp_despacho       TIMESTAMPTZ  NOT NULL,
    confirmado_en            TIMESTAMPTZ,
    CONSTRAINT ck_despachos_interoperables_dependencia_destino
        CHECK (dependencia_destino IN ('C4 Municipal', 'Proteccion Civil', 'Seguridad Campus')),
    CONSTRAINT ck_despachos_interoperables_estado_envio
        CHECK (estado_envio IN ('pendiente', 'enviado', 'confirmado')),
    CONSTRAINT uq_despacho_evento_dependencia UNIQUE (evento_id, dependencia_destino)
);
CREATE INDEX IF NOT EXISTS ix_despachos_interoperables_evento_id          ON despachos_interoperables (evento_id);
CREATE INDEX IF NOT EXISTS ix_despachos_interoperables_timestamp_despacho ON despachos_interoperables (timestamp_despacho);

-- -----------------------------------------------------------------------------
-- 4. Bitácora de auditoría: append-only y encadenada por SHA-256
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bitacora_auditoria (
    id                   SERIAL PRIMARY KEY,
    accion               VARCHAR(64)  NOT NULL,
    usuario_o_nodo       VARCHAR(128) NOT NULL,
    ip_origen            VARCHAR(64)  NOT NULL,
    entidad              VARCHAR(64)  NOT NULL,
    entidad_id           VARCHAR(64),
    detalle_json         JSON         NOT NULL,
    payload_hash_sha256  VARCHAR(64)  NOT NULL,
    hash_anterior        VARCHAR(64)  NOT NULL,
    hash_registro        VARCHAR(64)  NOT NULL UNIQUE,
    timestamp_inmutable  TIMESTAMPTZ  NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bitacora_auditoria_accion              ON bitacora_auditoria (accion);
CREATE INDEX IF NOT EXISTS ix_bitacora_auditoria_timestamp_inmutable ON bitacora_auditoria (timestamp_inmutable);

-- Nadie (ni siquiera el dueño de la tabla) puede modificar, borrar ni vaciar la bitácora.
CREATE OR REPLACE FUNCTION fn_bitacora_append_only() RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    RAISE EXCEPTION 'bitacora_auditoria es append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_bitacora_append_only ON bitacora_auditoria;
CREATE TRIGGER trg_bitacora_append_only
    BEFORE UPDATE OR DELETE ON bitacora_auditoria
    FOR EACH ROW EXECUTE FUNCTION fn_bitacora_append_only();

DROP TRIGGER IF EXISTS trg_bitacora_no_truncate ON bitacora_auditoria;
CREATE TRIGGER trg_bitacora_no_truncate
    BEFORE TRUNCATE ON bitacora_auditoria
    FOR EACH STATEMENT EXECUTE FUNCTION fn_bitacora_append_only();

-- -----------------------------------------------------------------------------
-- 4b. Atención en campo: unidad (patrulla simulada) enviada al lugar del evento
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS atenciones_campo (
    id                SERIAL PRIMARY KEY,
    evento_id         INTEGER      NOT NULL UNIQUE REFERENCES eventos_detectados (id),
    unidad            VARCHAR(32)  NOT NULL,
    estado            VARCHAR(16)  NOT NULL,
    solicitado_por    VARCHAR(64)  NOT NULL,
    origen_lat        DOUBLE PRECISION NOT NULL,
    origen_lng        DOUBLE PRECISION NOT NULL,
    destino_lat       DOUBLE PRECISION NOT NULL,
    destino_lng       DOUBLE PRECISION NOT NULL,
    ruta              JSON         NOT NULL,  -- [[lat, lng], ...] por calles (OSRM)
    ruta_por_calles   BOOLEAN      NOT NULL,
    distancia_m       DOUBLE PRECISION NOT NULL,
    duracion_s        DOUBLE PRECISION NOT NULL,
    despachada_en     TIMESTAMPTZ  NOT NULL,
    llegada_estimada  TIMESTAMPTZ  NOT NULL,
    llegada_en        TIMESTAMPTZ,           -- se llena cuando la unidad llega: caso resuelto
    CONSTRAINT ck_atenciones_campo_estado CHECK (estado IN ('en_camino', 'resuelto'))
);
CREATE INDEX IF NOT EXISTS ix_atenciones_campo_despachada_en    ON atenciones_campo (despachada_en);
CREATE INDEX IF NOT EXISTS ix_atenciones_campo_llegada_estimada ON atenciones_campo (llegada_estimada);

-- -----------------------------------------------------------------------------
-- 5. Seguridad de Supabase: cerrar la API REST pública
--
-- Supabase publica las tablas de "public" en su API REST, accesible con la llave
-- anon (que es pública). RLS activado SIN políticas = esa API no puede leer ni
-- escribir nada. El backend se conecta con el usuario "postgres" (dueño de las
-- tablas) por la cadena de conexión, así que no le afecta.
-- -----------------------------------------------------------------------------
ALTER TABLE camaras_sensores         ENABLE ROW LEVEL SECURITY;
ALTER TABLE eventos_detectados       ENABLE ROW LEVEL SECURITY;
ALTER TABLE despachos_interoperables ENABLE ROW LEVEL SECURITY;
ALTER TABLE atenciones_campo         ENABLE ROW LEVEL SECURITY;
ALTER TABLE bitacora_auditoria       ENABLE ROW LEVEL SECURITY;

COMMIT;
