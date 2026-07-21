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
--
-- CAMBIO (20-jul-2026): columnas por rango renombradas de usuarios_dl/ul_*
-- a lineas_dl/ul_*. El área de Mercados necesita CONTEO DE LÍNEAS/CUENTAS
-- en cada rango, no SUM(numeroUsuarios) -- son magnitudes distintas (una
-- línea compartida reporta varios usuarios). total_lineas/total_usuarios
-- (los totales generales, no por rango) NO cambian. Ver migración
-- idempotente más abajo para instalaciones que ya tenían usuarios_dl/ul_*.
-- No se agrega fechaCreacion en este cambio (decisión explícita para no
-- forzar una reconstrucción adicional del índice de SQL Server).
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
    -- Volumen total (sin cambios: total_lineas = COUNT(*),
    -- total_usuarios = SUM(numeroUsuarios) del origen)
    total_lineas              INTEGER      NOT NULL,
    total_usuarios            INTEGER      NOT NULL,
    -- Rangos de velocidad de bajada (downLink, en Kbps en origen) —
    -- CONTEO DE LÍNEAS en cada rango, no de usuarios
    lineas_dl_sin_datos       INTEGER      NOT NULL DEFAULT 0,
    lineas_dl_menos_1mbps     INTEGER      NOT NULL DEFAULT 0,
    lineas_dl_1_10mbps        INTEGER      NOT NULL DEFAULT 0,
    lineas_dl_10_30mbps       INTEGER      NOT NULL DEFAULT 0,
    lineas_dl_30_100mbps      INTEGER      NOT NULL DEFAULT 0,
    lineas_dl_100mbps_1gbps   INTEGER      NOT NULL DEFAULT 0,
    lineas_dl_1gbps_o_mas     INTEGER      NOT NULL DEFAULT 0,
    -- Rangos de velocidad de subida (upLink, en Kbps en origen) —
    -- CONTEO DE LÍNEAS en cada rango, no de usuarios
    lineas_ul_sin_datos       INTEGER      NOT NULL DEFAULT 0,
    lineas_ul_menos_1mbps     INTEGER      NOT NULL DEFAULT 0,
    lineas_ul_1_10mbps        INTEGER      NOT NULL DEFAULT 0,
    lineas_ul_10_30mbps       INTEGER      NOT NULL DEFAULT 0,
    lineas_ul_30_100mbps      INTEGER      NOT NULL DEFAULT 0,
    lineas_ul_100mbps_1gbps   INTEGER      NOT NULL DEFAULT 0,
    lineas_ul_1gbps_o_mas     INTEGER      NOT NULL DEFAULT 0,
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

-- ----------------------------------------------------------------------------
-- Migración idempotente para tablas ya existentes (instalaciones previas
-- a este cambio, ej. la copia 172.20.1.74)
-- ----------------------------------------------------------------------------
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS hash_contenido VARCHAR(32);

-- Rename usuarios_dl/ul_* -> lineas_dl/ul_* si la columna vieja existe y
-- la nueva todavía no -- seguro de correr repetidamente y seguro de
-- correr también en una instalación nueva (donde ninguna de las dos
-- existe todavía, el bloque simplemente no hace nada porque CREATE TABLE
-- ya la creó con el nombre nuevo).
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
            WHERE table_schema = 'staging'
              AND table_name = 'va_lineas_dedicadas_resumen'
              AND column_name = lower(par[1])
        ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'staging'
              AND table_name = 'va_lineas_dedicadas_resumen'
              AND column_name = lower(par[2])
        ) THEN
            EXECUTE format(
                'ALTER TABLE staging.va_lineas_dedicadas_resumen RENAME COLUMN %I TO %I',
                par[1], par[2]
            );
            RAISE NOTICE 'Renombrada columna % -> %', par[1], par[2];
        END IF;
    END LOOP;
END $$;

-- Por si alguna instalación no tenía ni la columna vieja ni la nueva
-- (ej. tabla recién creada por CREATE TABLE IF NOT EXISTS en una corrida
-- concurrente rara) -- garantiza que las columnas nuevas existan.
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS lineas_dl_sin_datos INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS lineas_dl_menos_1mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS lineas_dl_1_10mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS lineas_dl_10_30mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS lineas_dl_30_100mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS lineas_dl_100mbps_1gbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS lineas_dl_1gbps_o_mas INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS lineas_ul_sin_datos INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS lineas_ul_menos_1mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS lineas_ul_1_10mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS lineas_ul_10_30mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS lineas_ul_30_100mbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS lineas_ul_100mbps_1gbps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE staging.va_lineas_dedicadas_resumen
    ADD COLUMN IF NOT EXISTS lineas_ul_1gbps_o_mas INTEGER NOT NULL DEFAULT 0;

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
    -- Rangos de velocidad de bajada (downLink) — conteo de líneas
    h.lineas_dl_sin_datos,
    h.lineas_dl_menos_1mbps,
    h.lineas_dl_1_10mbps,
    h.lineas_dl_10_30mbps,
    h.lineas_dl_30_100mbps,
    h.lineas_dl_100mbps_1gbps,
    h.lineas_dl_1gbps_o_mas,
    -- Rangos de velocidad de subida (upLink) — conteo de líneas
    h.lineas_ul_sin_datos,
    h.lineas_ul_menos_1mbps,
    h.lineas_ul_1_10mbps,
    h.lineas_ul_10_30mbps,
    h.lineas_ul_30_100mbps,
    h.lineas_ul_100mbps_1gbps,
    h.lineas_ul_1gbps_o_mas,
    -- Campos derivados de alta utilidad analítica (conteo de líneas)
    -- Banda ancha total (≥ 1 Mbps downLink)
    (h.lineas_dl_1_10mbps + h.lineas_dl_10_30mbps +
     h.lineas_dl_30_100mbps + h.lineas_dl_100mbps_1gbps +
     h.lineas_dl_1gbps_o_mas)       AS lineas_dl_banda_ancha,
    -- Ultra banda ancha (≥ 30 Mbps downLink, umbral UE)
    (h.lineas_dl_30_100mbps + h.lineas_dl_100mbps_1gbps +
     h.lineas_dl_1gbps_o_mas)       AS lineas_dl_ultra_banda_ancha,
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

Rangos de velocidad (downLink y upLink en Kbps en origen). Las columnas
lineas_dl/ul_* cuentan LÍNEAS/CUENTAS en cada rango (COUNT), no usuarios
finales -- para usuarios finales usar total_usuarios (agregado general,
no desglosado por rango):
  lineas_dl/ul_sin_datos    : NULL o 0 Kbps (no reportado)
  lineas_dl/ul_menos_1mbps  : < 1.024 Kbps (sin banda ancha básica)
  lineas_dl/ul_1_10mbps     : 1.024 – 10.239 Kbps (umbral ITU)
  lineas_dl/ul_10_30mbps    : 10.240 – 30.719 Kbps (umbral OCDE)
  lineas_dl/ul_30_100mbps   : 30.720 – 102.399 Kbps (umbral UE)
  lineas_dl/ul_100mbps_1gbps: 102.400 – 1.048.575 Kbps (ultra banda ancha)
  lineas_dl/ul_1gbps_o_mas  : >= 1.048.576 Kbps (gigabit)

Campos derivados precalculados (conteo de líneas):
  lineas_dl_banda_ancha      : suma de rangos >= 1 Mbps downLink
  lineas_dl_ultra_banda_ancha: suma de rangos >= 30 Mbps downLink (umbral UE)

Resolución de dimensiones ISP y PermisoVAgregado por vigencia temporal (SCD Tipo 2).';

-- ----------------------------------------------------------------------------
-- 6. VISTA — analitico.v_ultimo_periodo_reportado_detalle
-- ----------------------------------------------------------------------------
-- Última entrega detallada (por parroquia/tecnología/tipo de cliente) de
-- cada prestador vigente, cruzada con su estado administrativo ACTUAL
-- (dim_permiso_va_agregado.opera, es_vigente = true -- no el estado que
-- tenía en el momento del último reporte). Uso: estadísticas nacionales
-- de Mercados que combinan "último reporte" + "estado actual".
--
-- Prestadores con permiso vigente pero SIN ningún reporte histórico
-- aparecen con una sola fila y las columnas de período/geografía/métricas
-- en NULL -- no se excluyen. Usar la columna tiene_reportes para
-- distinguir ese caso explícitamente en vez de inferirlo de un NULL.
--
-- opera refleja el estado tal como lo vio la última corrida de
-- cargar_dimensiones.py (@monthly) -- no en tiempo real contra SIETEL.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analitico.v_ultimo_periodo_reportado_detalle AS
WITH ultimo AS (
    -- Último (anio, periodoNumero) en que cada peva_codigo reportó algo real
    SELECT DISTINCT ON (h.peva_codigo)
        h.peva_codigo,
        h.anio          AS ultimo_anio,
        h.periodoNumero AS ultimo_periodo_numero,
        h.periodoNombre AS ultimo_periodo_nombre
    FROM staging.va_lineas_dedicadas_resumen h
    ORDER BY h.peva_codigo, h.anio DESC, h.periodoNumero DESC
)
SELECT
    p.peva_codigo,
    p.nombreComercial,
    p.opera,                                    -- estado administrativo ACTUAL
    isp.isp_nombre,
    u.ultimo_anio,
    u.ultimo_periodo_numero,
    u.ultimo_periodo_nombre,
    (u.ultimo_anio IS NOT NULL)      AS tiene_reportes,  -- flag explícito para Power BI
    -- Detalle geográfico/tecnológico del último período (NULL si nunca reportó)
    h.par_codigo,
    h.par_nombre,
    h.ciu_nombre,
    h.pro_nombre,
    h.tipoEnlace,
    h.tipoCliente,
    h.nivelComparticion,
    h.portador,
    h.total_lineas,
    h.total_usuarios,
    h.lineas_dl_sin_datos,
    h.lineas_dl_menos_1mbps,
    h.lineas_dl_1_10mbps,
    h.lineas_dl_10_30mbps,
    h.lineas_dl_30_100mbps,
    h.lineas_dl_100mbps_1gbps,
    h.lineas_dl_1gbps_o_mas,
    h.lineas_ul_sin_datos,
    h.lineas_ul_menos_1mbps,
    h.lineas_ul_1_10mbps,
    h.lineas_ul_10_30mbps,
    h.lineas_ul_30_100mbps,
    h.lineas_ul_100mbps_1gbps,
    h.lineas_ul_1gbps_o_mas,
    (h.lineas_dl_1_10mbps + h.lineas_dl_10_30mbps + h.lineas_dl_30_100mbps +
     h.lineas_dl_100mbps_1gbps + h.lineas_dl_1gbps_o_mas)   AS lineas_dl_banda_ancha,
    (h.lineas_dl_30_100mbps + h.lineas_dl_100mbps_1gbps +
     h.lineas_dl_1gbps_o_mas)                                AS lineas_dl_ultra_banda_ancha
FROM staging.dim_permiso_va_agregado p
LEFT JOIN staging.dim_isp isp
    ON isp.isp_codigo = p.isp_codigo AND isp.es_vigente = true
LEFT JOIN ultimo u
    ON u.peva_codigo = p.peva_codigo
LEFT JOIN staging.va_lineas_dedicadas_resumen h
    ON h.peva_codigo      = u.peva_codigo
   AND h.anio             = u.ultimo_anio
   AND h.periodoNumero    = u.ultimo_periodo_numero
WHERE p.es_vigente = true;

COMMENT ON VIEW analitico.v_ultimo_periodo_reportado_detalle IS
'Última entrega detallada por prestador vigente (opción B): una fila por
cada combinación par_codigo/tipoEnlace/tipoCliente/nivelComparticion/
portador del ÚLTIMO período que ese peva_codigo reportó. Prestadores con
permiso vigente (dim_permiso_va_agregado.es_vigente = true) pero sin
ningún reporte histórico aparecen con una sola fila y las columnas de
período/geografía/métricas en NULL -- usar tiene_reportes para
distinguir explícitamente ese caso en vez de inferirlo de un NULL.
opera refleja el estado visto por la última corrida de
cargar_dimensiones.py (@monthly), no el estado en tiempo real de SIETEL.';