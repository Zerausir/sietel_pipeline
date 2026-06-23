-- ============================================================================
-- DDL PostgreSQL - Pipeline Analítico SIETEL (Módulo Usuarios y Cuentas)
-- ============================================================================
-- Convenciones:
--   - Esquema "staging": replica nombres de columna EXACTOS de SQL Server.
--     No se traduce ni renombra nada aquí (decisión explícita del proyecto).
--   - Esquema "analitico": vistas de consumo, eventual renombrado a términos
--     de negocio se hace en una capa posterior, NO en este DDL.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS analitico;

-- ----------------------------------------------------------------------------
-- 1. TABLA DE HECHOS
--    Una fila por (peva_codigo, par_codigo, tipo_enlace, anio, mes).
--    NO incluye isp_nombre/isp_ruc/opera/etc. -- esas viven en las dimensiones
--    versionadas (ver mas abajo) para evitar duplicar el mismo valor de texto
--    en cientos de miles de filas historicas.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staging.va_reporte_usuarios_cuentas (
    id                  BIGSERIAL PRIMARY KEY,
    ruc_codigo          INTEGER NOT NULL,          -- PK de origen (SQL Server), se conserva como referencia
    peva_codigo         VARCHAR(50) NOT NULL,
    par_codigo          VARCHAR(50) NOT NULL,
    anio                INTEGER NOT NULL,
    mesNumero           INTEGER NOT NULL,
    mesNombre           VARCHAR(50) NOT NULL,
    actualizado         VARCHAR(10) NOT NULL,
    -- Geografia desnormalizada (catalogo estable, no versionado, ver seccion 1.3)
    pro_nombre          VARCHAR(50),
    ciu_nombre          VARCHAR(50),
    par_nombre          VARCHAR(100),
    -- Metricas de cuentas
    c_du_r              INTEGER NOT NULL,
    c_du_c              INTEGER NOT NULL,
    c_du_total          INTEGER NOT NULL,
    c_d_r               INTEGER NOT NULL,
    c_d_c               INTEGER NOT NULL,
    c_d_ci              INTEGER NOT NULL,
    c_d_total           INTEGER NOT NULL,
    c_total_cuentas     INTEGER NOT NULL,
    c_total_r           INTEGER NOT NULL,
    c_total_c           INTEGER NOT NULL,
    tipo_enlace         VARCHAR(50) NOT NULL,
    -- Metricas de usuarios
    u_du_r              INTEGER NOT NULL,
    u_du_c              INTEGER NOT NULL,
    u_du_total          INTEGER NOT NULL,
    u_d_r               INTEGER NOT NULL,
    u_d_c               INTEGER NOT NULL,
    u_d_ci              INTEGER NOT NULL,
    u_d_total           INTEGER NOT NULL,
    u_total_usuarios    INTEGER NOT NULL,
    u_total_r           INTEGER NOT NULL,
    u_total_c           INTEGER NOT NULL,
    u_total_ci          INTEGER NOT NULL,
    -- Metadata de carga
    fecha_carga         TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (ruc_codigo)
);

CREATE INDEX IF NOT EXISTS ix_hechos_anio_mes ON staging.va_reporte_usuarios_cuentas (anio, mesNumero);
CREATE INDEX IF NOT EXISTS ix_hechos_peva_codigo ON staging.va_reporte_usuarios_cuentas (peva_codigo);
CREATE INDEX IF NOT EXISTS ix_hechos_par_codigo ON staging.va_reporte_usuarios_cuentas (par_codigo);

-- ----------------------------------------------------------------------------
-- 2. DIMENSION ISP (SCD Tipo 2)
--    NOTA IMPORTANTE: SIETEL solo expone el estado ACTUAL de ISP; no existe
--    fuente para reconstruir el valor histórico real previo al inicio de
--    este pipeline. Las columnas marcadas "SI versionar" en el documento de
--    validación con Mercados solo comenzarán a generar historial real a
--    partir de la primera vez que cambien DESPUÉS de empezar a correr este
--    pipeline. Antes de eso, existe una única versión por ISP (snapshot
--    inicial), no el histórico verdadero de SIETEL.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staging.dim_isp (
    isp_sk                  BIGSERIAL PRIMARY KEY,
    isp_codigo              VARCHAR(50) NOT NULL,
    isp_nombre              VARCHAR(100),
    isp_ruc                 VARCHAR(50),
    isp_tipoPersona         VARCHAR(50),
    isp_observacion         TEXT,
    isp_telefono            VARCHAR(20),
    regional                VARCHAR(50),
    fechaModificacion       TIMESTAMP,              -- la que ya trae SIETEL, sin modificar
    fecha_inicio_vigencia   TIMESTAMP NOT NULL DEFAULT now(),
    fecha_fin_vigencia      TIMESTAMP,
    es_vigente              BOOLEAN NOT NULL DEFAULT true,
    fecha_carga             TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (isp_codigo, fecha_inicio_vigencia)
);

CREATE INDEX IF NOT EXISTS ix_dim_isp_codigo_vigente
    ON staging.dim_isp (isp_codigo)
    WHERE es_vigente = true;

-- ----------------------------------------------------------------------------
-- 3. DIMENSION PermisoVAgregado (SCD Tipo 2)
--    Misma advertencia que dim_isp respecto al histórico anterior al
--    arranque del pipeline.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staging.dim_permiso_va_agregado (
    peva_sk                 BIGSERIAL PRIMARY KEY,
    peva_codigo             VARCHAR(50) NOT NULL,
    isp_codigo              VARCHAR(50) NOT NULL,
    nombreComercial         VARCHAR(50),
    opera                   VARCHAR(50),
    fechaPermiso            TIMESTAMP,
    Resolucion              VARCHAR(50),
    fecha_inicio_vigencia   TIMESTAMP NOT NULL DEFAULT now(),
    fecha_fin_vigencia      TIMESTAMP,
    es_vigente              BOOLEAN NOT NULL DEFAULT true,
    fecha_carga             TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (peva_codigo, fecha_inicio_vigencia)
);

CREATE INDEX IF NOT EXISTS ix_dim_permiso_codigo_vigente
    ON staging.dim_permiso_va_agregado (peva_codigo)
    WHERE es_vigente = true;

-- ----------------------------------------------------------------------------
-- 4. CONTROL DE CARGAS
--    Permite que el DAG sepa que años ya se cargaron exitosamente, para que
--    una corrida fallida a mitad de camino se pueda reanudar sin repetir
--    años ya completados, y para llevar un registro auditable de cada carga.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staging.control_cargas (
    id                  BIGSERIAL PRIMARY KEY,
    tipo_carga          VARCHAR(50) NOT NULL,       -- 'hechos_anual' | 'dimensiones' | 'validacion_cruzada'
    anio                INTEGER,                     -- NULL cuando tipo_carga = 'dimensiones'
    filas_insertadas    INTEGER,
    filas_actualizadas  INTEGER,
    estado              VARCHAR(20) NOT NULL,        -- 'EXITOSO' | 'FALLIDO'
    mensaje_error       TEXT,
    fecha_inicio        TIMESTAMP NOT NULL,
    fecha_fin           TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_control_cargas_tipo_anio
    ON staging.control_cargas (tipo_carga, anio);

-- ----------------------------------------------------------------------------
-- 5. VISTA DE CONSUMO
--    Une los hechos con la versión de dimensión vigente EN LA FECHA del
--    hecho (anio/mesNumero), no con el estado actual sin más.
--    Para fechas anteriores al arranque del pipeline, esto resuelve contra
--    la única versión disponible (la primera capturada) -- ver advertencia
--    en el comentario de columna mas abajo.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analitico.v_usuarios_cuentas AS
SELECT
    h.id,
    h.ruc_codigo,
    h.anio,
    h.mesNumero,
    h.mesNombre,
    h.actualizado,
    h.pro_nombre,
    h.ciu_nombre,
    h.par_nombre,
    h.tipo_enlace,
    h.c_du_r, h.c_du_c, h.c_du_total,
    h.c_d_r, h.c_d_c, h.c_d_ci, h.c_d_total,
    h.c_total_cuentas, h.c_total_r, h.c_total_c,
    h.u_du_r, h.u_du_c, h.u_du_total,
    h.u_d_r, h.u_d_c, h.u_d_ci, h.u_d_total,
    h.u_total_usuarios, h.u_total_r, h.u_total_c, h.u_total_ci,
    isp.isp_codigo,
    isp.isp_nombre,
    isp.isp_ruc,
    isp.isp_tipoPersona,
    isp.regional               AS isp_regional,
    p.peva_codigo,
    p.nombreComercial,
    p.opera,
    p.Resolucion,
    p.fechaPermiso
FROM staging.va_reporte_usuarios_cuentas h
INNER JOIN staging.dim_permiso_va_agregado p
    ON p.peva_codigo = h.peva_codigo
    AND make_date(h.anio, h.mesNumero, 1) >= p.fecha_inicio_vigencia::date
    AND (p.fecha_fin_vigencia IS NULL OR make_date(h.anio, h.mesNumero, 1) < p.fecha_fin_vigencia::date)
INNER JOIN staging.dim_isp isp
    ON isp.isp_codigo = p.isp_codigo
    AND make_date(h.anio, h.mesNumero, 1) >= isp.fecha_inicio_vigencia::date
    AND (isp.fecha_fin_vigencia IS NULL OR make_date(h.anio, h.mesNumero, 1) < isp.fecha_fin_vigencia::date);

COMMENT ON VIEW analitico.v_usuarios_cuentas IS
'Vista de consumo del modulo Usuarios y Cuentas. El JOIN contra dim_isp y '
'dim_permiso_va_agregado resuelve la version VIGENTE EN LA FECHA del hecho '
'(anio/mes), no el estado actual. ADVERTENCIA: para periodos anteriores a la '
'fecha de arranque de este pipeline, SIETEL no provee el valor historico '
'real de isp_nombre/isp_ruc/opera -- estas filas se resuelven contra la '
'unica version disponible (el snapshot inicial capturado al arrancar el '
'pipeline), no contra el valor que realmente era vigente en SIETEL en esa '
'fecha pasada. Ver documento "Propuesta de Historizacion - Validacion con '
'Mercados" para el detalle de esta limitacion.';