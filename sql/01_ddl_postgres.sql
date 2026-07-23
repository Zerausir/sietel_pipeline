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
--
-- CAMBIO (22-jul-2026): codigo_provincia, codigo_ciudad, codigo_parroquia.
-- Códigos administrativos (Provincia.codigo, Ciudad.codigoCiudad,
-- Parroquia.codigoParroquia en SQL Server, los tres nvarchar(50)) para
-- cruzar con las tablas del INEC. VARCHAR en Postgres, no INTEGER, para no
-- perder ceros a la izquierda (ej. "01", "0801"). No forman parte de
-- COLUMNAS_HASH en cargar_hechos_anio.py -- mismo criterio ya aplicado a
-- pro_nombre/ciu_nombre/par_nombre (atributos descriptivos de tablas de
-- lookup, no de la llave natural ni de las métricas medidas).
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
    codigo_provincia          VARCHAR(50),
    codigo_ciudad             VARCHAR(50),
    codigo_parroquia          VARCHAR(50),
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

-- Códigos administrativos para cruce con INEC (22-jul-2026). ADD COLUMN
-- IF NOT EXISTS para instalaciones ya existentes; ya están en el
-- CREATE TABLE de arriba para instalaciones nuevas.
ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS codigo_provincia VARCHAR(50);
ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS codigo_ciudad VARCHAR(50);
ALTER TABLE staging.va_lineas_dedicadas_resumen ADD COLUMN IF NOT EXISTS codigo_parroquia VARCHAR(50);

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
    h.codigo_provincia, h.codigo_ciudad, h.codigo_parroquia,
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
'Vista de consumo del módulo Usuarios y Cuentas de Internet Fijo. lineas_dl/ul_* cuentan LÍNEAS (COUNT), no usuarios -- para usuarios finales usar total_usuarios. codigo_provincia/codigo_ciudad/codigo_parroquia son para cruce con INEC. Recreada con DROP VIEW + CREATE VIEW para poder reordenar columnas libremente.';

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
    h.codigo_provincia, h.codigo_ciudad, h.codigo_parroquia,
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
'Última entrega detallada por prestador vigente. tiene_reportes distingue prestadores sin reportes. opera refleja el estado de la última corrida de cargar_dimensiones.py. codigo_provincia/codigo_ciudad/codigo_parroquia son para cruce con INEC.';

-- ============================================================================
-- 7. HISTORIAL DE CORRECCIONES (22-jul-2026)
-- ============================================================================
-- Decisión: la tabla de hechos NO se versiona completa (SCD Tipo 2 como las
-- dimensiones) -- el costo de filtrar "solo vigente" en millones de filas
-- históricas no se justifica frente al uso real (siempre se consume el
-- último dato cargado). En su lugar, se registra CUÁNDO el contenido de una
-- fila cambia entre una carga y otra, vía un trigger a nivel de base de
-- datos -- captura el cambio sin importar qué script dispare el UPDATE
-- (cargar_hechos_anio.py, un backfill puntual, una recarga manual).
--
-- IMPORTANTE: esto NO distingue una corrección real de un prestador
-- (cambió su reporte de un período ya cerrado) de un reprocesamiento
-- nuestro (arreglamos un bug de fórmula y recargamos el año) -- ambos
-- casos generan una entrada aquí. Esa distinción de causa queda en
-- staging.control_cargas + el historial de Git de por qué se relanzó
-- ese año, no en esta tabla.
--
-- Solo se registra cuando hash_contenido REALMENTE cambia -- un UPSERT
-- que no modifica ningún valor medido (ej. el backfill de
-- codigo_provincia/ciudad/parroquia, que no toca hash_contenido) no
-- genera entrada aquí.

CREATE TABLE IF NOT EXISTS staging.historial_correcciones (
    id                  BIGSERIAL PRIMARY KEY,
    resumen_id          BIGINT       NOT NULL,
    peva_codigo         VARCHAR(50)  NOT NULL,
    par_codigo          VARCHAR(50)  NOT NULL,
    periodoNumero       INTEGER      NOT NULL,
    anio                INTEGER      NOT NULL,
    tipoEnlace          VARCHAR(50),
    tipoCliente         VARCHAR(50),
    nivelComparticion   VARCHAR(50),
    portador            VARCHAR(100),
    hash_anterior       VARCHAR(32)  NOT NULL,
    hash_nuevo          VARCHAR(32)  NOT NULL,
    valores_anteriores  JSONB        NOT NULL,
    fecha_deteccion     TIMESTAMP    NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_historial_correcciones_anio ON staging.historial_correcciones (anio, periodoNumero);
CREATE INDEX IF NOT EXISTS ix_historial_correcciones_peva ON staging.historial_correcciones (peva_codigo);

COMMENT ON TABLE staging.historial_correcciones IS
'Registro de cambios de contenido en staging.va_lineas_dedicadas_resumen, detectados por trigger cuando hash_contenido difiere entre la fila vieja y la nueva. valores_anteriores es un snapshot completo (JSONB) de la fila antes de sobreescribirse. No distingue corrección real de origen vs. reprocesamiento propio -- ver control_cargas y Git para esa distinción.';

CREATE OR REPLACE FUNCTION staging.fn_registrar_correccion_resumen()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.hash_contenido IS DISTINCT FROM NEW.hash_contenido THEN
        INSERT INTO staging.historial_correcciones (
            resumen_id, peva_codigo, par_codigo, periodoNumero, anio,
            tipoEnlace, tipoCliente, nivelComparticion, portador,
            hash_anterior, hash_nuevo, valores_anteriores
        ) VALUES (
            OLD.id, OLD.peva_codigo, OLD.par_codigo, OLD.periodoNumero, OLD.anio,
            OLD.tipoEnlace, OLD.tipoCliente, OLD.nivelComparticion, OLD.portador,
            OLD.hash_contenido, NEW.hash_contenido, to_jsonb(OLD)
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_registrar_correccion_resumen ON staging.va_lineas_dedicadas_resumen;
CREATE TRIGGER trg_registrar_correccion_resumen
    BEFORE UPDATE ON staging.va_lineas_dedicadas_resumen
    FOR EACH ROW
    EXECUTE FUNCTION staging.fn_registrar_correccion_resumen();