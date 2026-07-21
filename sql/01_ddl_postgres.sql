-- ============================================================================
-- DDL PostgreSQL - Pipeline Analítico SIETEL (Módulo Usuarios y Cuentas)
-- Fuente: dbo.VALineasDedicadas (SQL Server)
-- ============================================================================
-- NOTA SOBRE VISTAS (21-jul-2026): las vistas analíticas se recrean con
-- DROP VIEW IF EXISTS + CREATE VIEW, no con CREATE OR REPLACE VIEW.
-- PostgreSQL solo permite que CREATE OR REPLACE VIEW agregue columnas al
-- FINAL de la lista existente -- no permite insertar, reordenar ni
-- renombrar en medio (resuelve por posición ordinal, no por nombre).
-- Como estas vistas siguen evolucionando, DROP + CREATE es más robusto.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS analitico;

-- 1. TABLA DE HECHOS — staging.va_lineas_dedicadas_resumen
CREATE TABLE IF NOT EXISTS staging.va_lineas_dedicadas_resumen (
    id                        BIGSERIAL PRIMARY KEY,
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
    pro_nombre                VARCHAR(50),
    ciu_nombre                VARCHAR(50),
    par_nombre                VARCHAR(100),
    total_lineas              INTEGER      NOT NULL,
    total_usuarios            INTEGER      NOT NULL,
    lineas_dl_sin_datos       INTEGER      NOT NULL DEFAULT 0,
    lineas_dl_menos_1mbps     INTEGER      NOT NULL DEFAULT 0,
    lineas_dl_1_10mbps        INTEGER      NOT NULL DEFAULT 0,
    lineas_dl_10_30mbps       INTEGER      NOT NULL DEFAULT 0,
    lineas_dl_30_100mbps      INTEGER      NOT NULL DEFAULT 0,
    lineas_dl_100mbps_1gbps   INTEGER      NOT NULL DEFAULT 0,
    lineas_dl_1gbps_o_mas     INTEGER      NOT NULL DEFAULT 0,
    lineas_ul_sin_datos       INTEGER      NOT NULL DEFAULT 0,
    lineas_ul_menos_1mbps     INTEGER      NOT NULL DEFAULT 0,
    lineas_ul_1_10mbps        INTEGER      NOT NULL DEFAULT 0,
    lineas_ul_10_30mbps       INTEGER      NOT NULL DEFAULT 0,
    lineas_ul_30_100mbps      INTEGER      NOT NULL DEFAULT 0,
    lineas_ul_100mbps_1gbps   INTEGER      NOT NULL DEFAULT 0,
    lineas_ul_1gbps_o_mas     INTEGER      NOT NULL DEFAULT 0,
    hash_contenido            VARCHAR(32),
    fecha_carga               TIMESTAMP    NOT NULL DEFAULT now(),
    CONSTRAINT uq_resumen_natural UNIQUE (
        peva_codigo, par_codigo, periodoNumero, anio,
        tipoEnlace, tipoCliente, nivelComparticion, portador
    )
);

CREATE INDEX IF NOT EXISTS ix_resumen_anio_periodo ON staging.va_lineas_dedicadas_resumen (anio, periodoNumero);
CREATE INDEX IF NOT EXISTS ix_resumen_peva ON staging.va_lineas_dedicadas_resumen (peva_codigo);
CREATE INDEX IF NOT EXISTS ix_resumen_par ON staging.va_lineas_dedicadas_resumen (par_codigo);
CREATE INDEX IF NOT EXISTS ix_resumen_pro_nombre ON staging.va_lineas_dedicadas_resumen (pro_nombre);

ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS hash_contenido VARCHAR(32);

DO $$
DECLARE
    pares TEXT[][] := ARRAY[
        ARRAY['usuarios_dl_sin_datos',     'lineas_dl_sin_datos'],
        ARRAY['usuarios_dl_menos_1mbps',   'lineas_dl_menos_1mbps'],
        ARRAY['usuarios_dl_1_10mbps',      'lineas_dl_1_10mbps'],
        ARRAY['usuarios_dl_10_30mbps',     'lineas_dl_10_30mbps'],
        ARRAY['usuarios_dl_30_100mbps',    'lineas_dl_30_100mbps'],
        ARRAY['usuarios_dl_100mbps_1gbps', 'lineas_dl_100mbps_1gbps'],
        ARRAY['usuarios_dl_1gbps_o_mas',   'lineas_dl_1gbps_o_mas'],
        ARRAY['usuarios_ul_sin_datos',     'lineas_ul_sin_datos'],
        ARRAY['usuarios_ul_menos_1mbps',   'lineas_ul_menos_1mbps'],
        ARRAY['usuarios_ul_1_10mbps',      'lineas_ul_1_10mbps'],
        ARRAY['usuarios_ul_10_30mbps',     'lineas_ul_10_30mbps'],
        ARRAY['usuarios_ul_30_100mbps',    'lineas_ul_30_100mbps'],
        ARRAY['usuarios_ul_100mbps_1gbps', 'lineas_ul_100mbps_1gbps'],
        ARRAY['usuarios_ul_1gbps_o_mas',   'lineas_ul_1gbps_o_mas']
    ];
    par TEXT[];
BEGIN
    FOREACH par SLICE 1 IN ARRAY pares
    LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'staging' AND table_name = 'va_lineas_dedicadas_resumen'
              AND column_name = lower(par[1])
        ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'staging' AND table_name = 'va_lineas_dedicadas_resumen'
              AND column_name = lower(par[2])
        ) THEN
            EXECUTE format('ALTER TABLE staging.va_lineas_dedicadas_resumen RENAME COLUMN %I TO %I', par[1], par[2]);
            RAISE NOTICE 'Renombrada columna % -> %', par[1], par[2];
        END IF;
    END LOOP;
END $$;

ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS lineas_dl_sin_datos INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS lineas_dl_menos_1mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS lineas_dl_1_10mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS lineas_dl_10_30mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS lineas_dl_30_100mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS lineas_dl_100mbps_1gbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS lineas_dl_1gbps_o_mas INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS lineas_ul_sin_datos INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS lineas_ul_menos_1mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS lineas_ul_1_10mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS lineas_ul_10_30mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS lineas_ul_30_100mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS lineas_ul_100mbps_1gbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS lineas_ul_1gbps_o_mas INTEGER NOT NULL DEFAULT 0;

-- 2. DIMENSION ISP (SCD Tipo 2)
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
CREATE INDEX IF NOT EXISTS ix_dim_isp_codigo_vigente ON staging.dim_isp (isp_codigo) WHERE es_vigente = true;

-- 3. DIMENSION PermisoVAgregado (SCD Tipo 2)
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
CREATE INDEX IF NOT EXISTS ix_dim_permiso_codigo_vigente ON staging.dim_permiso_va_agregado (peva_codigo) WHERE es_vigente = true;

-- 4. CONTROL DE CARGAS
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
CREATE INDEX IF NOT EXISTS ix_control_cargas_tipo_anio ON staging.control_cargas (tipo_carga, anio);

-- 5. VISTA DE CONSUMO — analitico.v_lineas_dedicadas_resumen
DROP VIEW IF EXISTS analitico.v_lineas_dedicadas_resumen;

CREATE VIEW analitico.v_lineas_dedicadas_resumen AS
SELECT
    h.anio, h.periodoNumero, h.periodoNombre,
    isp.isp_codigo, isp.isp_nombre, isp.isp_ruc, isp.isp_tipoPersona,
    isp.regional AS isp_regional,
    p.peva_codigo, p.nombreComercial, p.opera, p.Resolucion, p.fechaPermiso,
    h.par_codigo, h.par_nombre, h.ciu_nombre, h.pro_nombre,
    h.regional AS regional_reporte,
    h.tipoEnlace, h.tipoCliente, h.nivelComparticion, h.portador,
    h.total_lineas, h.total_usuarios,
    h.lineas_dl_sin_datos, h.lineas_dl_menos_1mbps, h.lineas_dl_1_10mbps,
    h.lineas_dl_10_30mbps, h.lineas_dl_30_100mbps, h.lineas_dl_100mbps_1gbps, h.lineas_dl_1gbps_o_mas,
    h.lineas_ul_sin_datos, h.lineas_ul_menos_1mbps, h.lineas_ul_1_10mbps,
    h.lineas_ul_10_30mbps, h.lineas_ul_30_100mbps, h.lineas_ul_100mbps_1gbps, h.lineas_ul_1gbps_o_mas,
    (h.lineas_dl_1_10mbps + h.lineas_dl_10_30mbps + h.lineas_dl_30_100mbps +
     h.lineas_dl_100mbps_1gbps + h.lineas_dl_1gbps_o_mas) AS lineas_dl_banda_ancha,
    (h.lineas_dl_30_100mbps + h.lineas_dl_100mbps_1gbps + h.lineas_dl_1gbps_o_mas) AS lineas_dl_ultra_banda_ancha,
    h.fecha_carga
FROM staging.va_lineas_dedicadas_resumen h
INNER JOIN staging.dim_permiso_va_agregado p
    ON  p.peva_codigo = h.peva_codigo
    AND make_date(h.anio, h.periodoNumero, 1) >= p.fecha_inicio_vigencia::date
    AND (p.fecha_fin_vigencia IS NULL OR make_date(h.anio, h.periodoNumero, 1) < p.fecha_fin_vigencia::date)
INNER JOIN staging.dim_isp isp
    ON  isp.isp_codigo = p.isp_codigo
    AND make_date(h.anio, h.periodoNumero, 1) >= isp.fecha_inicio_vigencia::date
    AND (isp.fecha_fin_vigencia IS NULL OR make_date(h.anio, h.periodoNumero, 1) < isp.fecha_fin_vigencia::date);

COMMENT ON VIEW analitico.v_lineas_dedicadas_resumen IS
'Vista de consumo del módulo Usuarios y Cuentas de Internet Fijo. lineas_dl/ul_* cuentan LÍNEAS (COUNT), no usuarios -- para usuarios finales usar total_usuarios. Recreada con DROP VIEW + CREATE VIEW para poder reordenar columnas libremente.';

-- 6. VISTA — analitico.v_ultimo_periodo_reportado_detalle
DROP VIEW IF EXISTS analitico.v_ultimo_periodo_reportado_detalle;

CREATE VIEW analitico.v_ultimo_periodo_reportado_detalle AS
WITH ultimo AS (
    SELECT DISTINCT ON (h.peva_codigo)
        h.peva_codigo, h.anio AS ultimo_anio,
        h.periodoNumero AS ultimo_periodo_numero, h.periodoNombre AS ultimo_periodo_nombre
    FROM staging.va_lineas_dedicadas_resumen h
    ORDER BY h.peva_codigo, h.anio DESC, h.periodoNumero DESC
)
SELECT
    p.peva_codigo, p.nombreComercial, p.opera, p.Resolucion, p.fechaPermiso,
    isp.isp_nombre, isp.isp_ruc, isp.isp_tipoPersona, isp.regional AS isp_regional,
    u.ultimo_anio, u.ultimo_periodo_numero, u.ultimo_periodo_nombre,
    (u.ultimo_anio IS NOT NULL) AS tiene_reportes,
    h.par_codigo, h.par_nombre, h.ciu_nombre, h.pro_nombre,
    h.tipoEnlace, h.tipoCliente, h.nivelComparticion, h.portador,
    h.total_lineas, h.total_usuarios,
    h.lineas_dl_sin_datos, h.lineas_dl_menos_1mbps, h.lineas_dl_1_10mbps,
    h.lineas_dl_10_30mbps, h.lineas_dl_30_100mbps, h.lineas_dl_100mbps_1gbps, h.lineas_dl_1gbps_o_mas,
    h.lineas_ul_sin_datos, h.lineas_ul_menos_1mbps, h.lineas_ul_1_10mbps,
    h.lineas_ul_10_30mbps, h.lineas_ul_30_100mbps, h.lineas_ul_100mbps_1gbps, h.lineas_ul_1gbps_o_mas,
    (h.lineas_dl_1_10mbps + h.lineas_dl_10_30mbps + h.lineas_dl_30_100mbps +
     h.lineas_dl_100mbps_1gbps + h.lineas_dl_1gbps_o_mas) AS lineas_dl_banda_ancha,
    (h.lineas_dl_30_100mbps + h.lineas_dl_100mbps_1gbps + h.lineas_dl_1gbps_o_mas) AS lineas_dl_ultra_banda_ancha
FROM staging.dim_permiso_va_agregado p
LEFT JOIN staging.dim_isp isp ON isp.isp_codigo = p.isp_codigo AND isp.es_vigente = true
LEFT JOIN ultimo u ON u.peva_codigo = p.peva_codigo
LEFT JOIN staging.va_lineas_dedicadas_resumen h
    ON h.peva_codigo = u.peva_codigo AND h.anio = u.ultimo_anio AND h.periodoNumero = u.ultimo_periodo_numero
WHERE p.es_vigente = true;

COMMENT ON VIEW analitico.v_ultimo_periodo_reportado_detalle IS
'Última entrega detallada por prestador vigente. tiene_reportes distingue prestadores sin reportes. opera refleja el estado de la última corrida de cargar_dimensiones.py.';