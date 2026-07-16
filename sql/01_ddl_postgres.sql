-- ============================================================================
-- DDL PostgreSQL - Pipeline Analítico SIETEL (Módulo Usuarios y Cuentas)
-- Fuente: dbo.VALineasDedicadas (SQL Server)
-- ============================================================================
-- Rangos de velocidad definidos a partir de la distribución real del mercado
-- ecuatoriano (diciembre 2025, 2.917.304 líneas verificadas):
--
--   Sin datos    : NULL o 0 Kbps — no reportado por el prestador
--   < 1 Mbps     : < 1.024 Kbps — sin banda ancha básica (brecha digital)
--   1 – 10 Mbps  : 1.024 – 10.239 Kbps — banda ancha básica (umbral ITU)
--   10 – 30 Mbps : 10.240 – 30.719 Kbps — banda ancha media (umbral OCDE)
--   30 – 100 Mbps: 30.720 – 102.399 Kbps — banda ancha avanzada (umbral UE)
--   100 Mbps-1G  : 102.400 – 1.048.575 Kbps — ultra banda ancha
--   ≥ 1 Gbps     : >= 1.048.576 Kbps — gigabit (segmento premium)
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS analitico;

-- ----------------------------------------------------------------------------
-- 1. TABLA DE HECHOS — staging.va_lineas_dedicadas_resumen
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staging.va_lineas_dedicadas_resumen (
    id                        BIGSERIAL PRIMARY KEY,
    -- Claves de negocio (GROUP BY en origen)
    peva_codigo               VARCHAR(50)  NOT NULL,
    par_codigo                VARCHAR(50)  NOT NULL,
    periodoNumero             INTEGER      NOT NULL,
    periodoNombre             VARCHAR(20)  NOT NULL,
    anio                      INTEGER      NOT NULL,
    tipoEnlace                VARCHAR(50),
    tipoCliente               VARCHAR(50),
    nivelComparticion         VARCHAR(50),
    portador                  VARCHAR(100),
    regional                  VARCHAR(50),
    -- Geografía desnormalizada
    pro_nombre                VARCHAR(50),
    ciu_nombre                VARCHAR(50),
    par_nombre                VARCHAR(100),
    -- Volumen total
    total_lineas              INTEGER      NOT NULL,
    total_usuarios            INTEGER      NOT NULL,
    -- Rangos de velocidad de bajada (downLink, en Kbps en origen)
    usuarios_dl_sin_datos     INTEGER      NOT NULL DEFAULT 0,
    usuarios_dl_menos_1mbps   INTEGER      NOT NULL DEFAULT 0,
    usuarios_dl_1_10mbps      INTEGER      NOT NULL DEFAULT 0,
    usuarios_dl_10_30mbps     INTEGER      NOT NULL DEFAULT 0,
    usuarios_dl_30_100mbps    INTEGER      NOT NULL DEFAULT 0,
    usuarios_dl_100mbps_1gbps INTEGER      NOT NULL DEFAULT 0,
    usuarios_dl_1gbps_o_mas   INTEGER      NOT NULL DEFAULT 0,
    -- Rangos de velocidad de subida (upLink, en Kbps en origen)
    usuarios_ul_sin_datos     INTEGER      NOT NULL DEFAULT 0,
    usuarios_ul_menos_1mbps   INTEGER      NOT NULL DEFAULT 0,
    usuarios_ul_1_10mbps      INTEGER      NOT NULL DEFAULT 0,
    usuarios_ul_10_30mbps     INTEGER      NOT NULL DEFAULT 0,
    usuarios_ul_30_100mbps    INTEGER      NOT NULL DEFAULT 0,
    usuarios_ul_100mbps_1gbps INTEGER      NOT NULL DEFAULT 0,
    usuarios_ul_1gbps_o_mas   INTEGER      NOT NULL DEFAULT 0,
    -- Certificación de integridad
    hash_contenido            VARCHAR(32),
    -- Metadata de carga
    fecha_carga               TIMESTAMP    NOT NULL DEFAULT now(),
    CONSTRAINT uq_resumen_natural UNIQUE (
        peva_codigo, par_codigo, periodoNumero, anio,
        tipoEnlace, tipoCliente, nivelComparticion, portador
    )
);

CREATE INDEX IF NOT EXISTS ix_resumen_anio_periodo
    ON staging.va_lineas_dedicadas_resumen (anio, periodoNumero);
CREATE INDEX IF NOT EXISTS ix_resumen_peva
    ON staging.va_lineas_dedicadas_resumen (peva_codigo);
CREATE INDEX IF NOT EXISTS ix_resumen_par
    ON staging.va_lineas_dedicadas_resumen (par_codigo);
CREATE INDEX IF NOT EXISTS ix_resumen_pro_nombre
    ON staging.va_lineas_dedicadas_resumen (pro_nombre);

-- Migración idempotente para tablas ya existentes
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS hash_contenido VARCHAR(32);
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS usuarios_dl_sin_datos INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS usuarios_dl_menos_1mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS usuarios_dl_1_10mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS usuarios_dl_10_30mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS usuarios_dl_30_100mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS usuarios_dl_100mbps_1gbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS usuarios_dl_1gbps_o_mas INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS usuarios_ul_sin_datos INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS usuarios_ul_menos_1mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS usuarios_ul_1_10mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS usuarios_ul_10_30mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS usuarios_ul_30_100mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS usuarios_ul_100mbps_1gbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS usuarios_ul_1gbps_o_mas INTEGER NOT NULL DEFAULT 0;

-- ----------------------------------------------------------------------------
-- 2. DIMENSION ISP (SCD Tipo 2)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staging.dim_isp (
    isp_sk                  BIGSERIAL PRIMARY KEY,
    isp_codigo              VARCHAR(50)  NOT NULL,
    isp_nombre              VARCHAR(100),
    isp_ruc                 VARCHAR(50),
    isp_tipoPersona         VARCHAR(50),
    isp_observacion         TEXT,
    isp_telefono            VARCHAR(20),
    regional                VARCHAR(50),
    fechaModificacion       TIMESTAMP,
    fecha_inicio_vigencia   TIMESTAMP    NOT NULL DEFAULT now(),
    fecha_fin_vigencia      TIMESTAMP,
    es_vigente              BOOLEAN      NOT NULL DEFAULT true,
    fecha_carga             TIMESTAMP    NOT NULL DEFAULT now(),
    UNIQUE (isp_codigo, fecha_inicio_vigencia)
);

CREATE INDEX IF NOT EXISTS ix_dim_isp_codigo_vigente
    ON staging.dim_isp (isp_codigo)
    WHERE es_vigente = true;

-- ----------------------------------------------------------------------------
-- 3. DIMENSION PermisoVAgregado (SCD Tipo 2)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staging.dim_permiso_va_agregado (
    peva_sk                 BIGSERIAL PRIMARY KEY,
    peva_codigo             VARCHAR(50)  NOT NULL,
    isp_codigo              VARCHAR(50)  NOT NULL,
    nombreComercial         VARCHAR(50),
    opera                   VARCHAR(50),
    fechaPermiso            TIMESTAMP,
    Resolucion              VARCHAR(50),
    fecha_inicio_vigencia   TIMESTAMP    NOT NULL DEFAULT now(),
    fecha_fin_vigencia      TIMESTAMP,
    es_vigente              BOOLEAN      NOT NULL DEFAULT true,
    fecha_carga             TIMESTAMP    NOT NULL DEFAULT now(),
    UNIQUE (peva_codigo, fecha_inicio_vigencia)
);

CREATE INDEX IF NOT EXISTS ix_dim_permiso_codigo_vigente
    ON staging.dim_permiso_va_agregado (peva_codigo)
    WHERE es_vigente = true;

-- ----------------------------------------------------------------------------
-- 4. CONTROL DE CARGAS
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staging.control_cargas (
    id                  BIGSERIAL PRIMARY KEY,
    tipo_carga          VARCHAR(50)  NOT NULL,
    anio                INTEGER,
    filas_insertadas    INTEGER,
    filas_actualizadas  INTEGER,
    estado              VARCHAR(20)  NOT NULL,
    mensaje_error       TEXT,
    fecha_inicio        TIMESTAMP    NOT NULL,
    fecha_fin           TIMESTAMP    NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_control_cargas_tipo_anio
    ON staging.control_cargas (tipo_carga, anio);

-- ----------------------------------------------------------------------------
-- 5. VISTA DE CONSUMO — analitico.v_lineas_dedicadas_resumen
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analitico.v_lineas_dedicadas_resumen AS
SELECT
    h.anio,
    h.periodoNumero,
    h.periodoNombre,
    -- Dimensión ISP
    isp.isp_codigo,
    isp.isp_nombre,
    isp.isp_ruc,
    isp.isp_tipoPersona,
    isp.regional                    AS isp_regional,
    -- Dimensión Permiso
    p.peva_codigo,
    p.nombreComercial,
    p.opera,
    p.Resolucion,
    p.fechaPermiso,
    -- Geografía
    h.par_codigo,
    h.par_nombre,
    h.ciu_nombre,
    h.pro_nombre,
    h.regional                      AS regional_reporte,
    -- Clasificación de la línea
    h.tipoEnlace,
    h.tipoCliente,
    h.nivelComparticion,
    h.portador,
    -- Volumen total
    h.total_lineas,
    h.total_usuarios,
    -- Rangos de velocidad de bajada (downLink)
    h.usuarios_dl_sin_datos,
    h.usuarios_dl_menos_1mbps,
    h.usuarios_dl_1_10mbps,
    h.usuarios_dl_10_30mbps,
    h.usuarios_dl_30_100mbps,
    h.usuarios_dl_100mbps_1gbps,
    h.usuarios_dl_1gbps_o_mas,
    -- Rangos de velocidad de subida (upLink)
    h.usuarios_ul_sin_datos,
    h.usuarios_ul_menos_1mbps,
    h.usuarios_ul_1_10mbps,
    h.usuarios_ul_10_30mbps,
    h.usuarios_ul_30_100mbps,
    h.usuarios_ul_100mbps_1gbps,
    h.usuarios_ul_1gbps_o_mas,
    -- Campos derivados de alta utilidad analítica
    -- Banda ancha total (≥ 1 Mbps downLink)
    (h.usuarios_dl_1_10mbps + h.usuarios_dl_10_30mbps +
     h.usuarios_dl_30_100mbps + h.usuarios_dl_100mbps_1gbps +
     h.usuarios_dl_1gbps_o_mas)     AS usuarios_dl_banda_ancha,
    -- Ultra banda ancha (≥ 30 Mbps downLink, umbral UE)
    (h.usuarios_dl_30_100mbps + h.usuarios_dl_100mbps_1gbps +
     h.usuarios_dl_1gbps_o_mas)     AS usuarios_dl_ultra_banda_ancha,
    h.fecha_carga
FROM staging.va_lineas_dedicadas_resumen h
INNER JOIN staging.dim_permiso_va_agregado p
    ON  p.peva_codigo = h.peva_codigo
    AND make_date(h.anio, h.periodoNumero, 1) >= p.fecha_inicio_vigencia::date
    AND (p.fecha_fin_vigencia IS NULL
         OR make_date(h.anio, h.periodoNumero, 1) < p.fecha_fin_vigencia::date)
INNER JOIN staging.dim_isp isp
    ON  isp.isp_codigo = p.isp_codigo
    AND make_date(h.anio, h.periodoNumero, 1) >= isp.fecha_inicio_vigencia::date
    AND (isp.fecha_fin_vigencia IS NULL
         OR make_date(h.anio, h.periodoNumero, 1) < isp.fecha_fin_vigencia::date);

COMMENT ON VIEW analitico.v_lineas_dedicadas_resumen IS
'Vista de consumo del módulo Usuarios y Cuentas de Internet Fijo.
Fuente: dbo.VALineasDedicadas (SQL Server SIETEL).
Dato pre-agregado en SQL Server por (peva_codigo, par_codigo, periodoNumero,
anio, tipoEnlace, tipoCliente, nivelComparticion, portador).

Rangos de velocidad (downLink y upLink en Kbps en origen):
  usuarios_dl/ul_sin_datos    : NULL o 0 Kbps (no reportado)
  usuarios_dl/ul_menos_1mbps  : < 1.024 Kbps (sin banda ancha básica)
  usuarios_dl/ul_1_10mbps     : 1.024 – 10.239 Kbps (umbral ITU)
  usuarios_dl/ul_10_30mbps    : 10.240 – 30.719 Kbps (umbral OCDE)
  usuarios_dl/ul_30_100mbps   : 30.720 – 102.399 Kbps (umbral UE)
  usuarios_dl/ul_100mbps_1gbps: 102.400 – 1.048.575 Kbps (ultra banda ancha)
  usuarios_dl/ul_1gbps_o_mas  : >= 1.048.576 Kbps (gigabit)

Campos derivados precalculados:
  usuarios_dl_banda_ancha      : suma de rangos >= 1 Mbps downLink
  usuarios_dl_ultra_banda_ancha: suma de rangos >= 30 Mbps downLink (umbral UE)

Resolución de dimensiones ISP y PermisoVAgregado por vigencia temporal (SCD Tipo 2).';