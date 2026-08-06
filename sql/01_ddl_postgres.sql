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
--
-- CASCADE agregado 06-ago-2026: mart.vw_prestadores_sin_reportar (KPI
-- "prestadores que nunca han reportado" del dashboard) depende de esta
-- vista -- FK_VAPorcenRecCapaci... no, esto no es SQL Server, es la propia
-- vista de mart -- ver sql/02_ddl_mart.sql linea ~2288, unica dependencia
-- cruzada confirmada de mart hacia analitico (grep sobre todo el archivo).
-- Sin CASCADE, aplicar_esquema.py falla con DependentObjectsStillExist en
-- CUALQUIER corrida de Capa 1 posterior a que Capa 2/3 haya construido
-- mart -- confirmado en produccion 06-ago-2026 al ejecutar aplicar_esquema
-- por primera vez desde que mart.vw_prestadores_sin_reportar existe.
--
-- EFECTO SECUNDARIO IMPORTANTE, operativo, no solo de este archivo:
-- CASCADE elimina mart.vw_prestadores_sin_reportar junto con esta vista.
-- aplicar_esquema.py (Capa 1) NO reconstruye mart -- eso es exclusivo de
-- aplicar_capa3.py (Capa 2/3, DAG sietel_mart_pipeline). Es decir: toda
-- corrida de Capa 1 que llegue a este DROP deja el KPI "prestadores sin
-- reportar" del dashboard roto hasta que alguien dispare manualmente
-- sietel_mart_pipeline despues. Esto NO esta resuelto todavia a nivel de
-- orquestacion (ver conversacion 06-ago-2026) -- pendiente decidir entre:
-- (a) paso de runbook manual "correr mart_pipeline despues de Capa 1",
-- (b) TriggerDagRunOperator al final de sietel_usuarios_cuentas_pipeline,
-- (c) que aplicar_esquema.py solo haga DROP+CREATE cuando la definicion
-- de la vista realmente cambio, no en cada corrida.
DROP VIEW IF EXISTS analitico.v_ultimo_periodo_reportado_detalle CASCADE;

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
-- 6b. GRANT a mart_user sobre vistas de analitico -- 06-ago-2026
-- ============================================================================
-- DROP VIEW + CREATE VIEW (secciones 5 y 6, ambas incondicionales en cada
-- corrida de aplicar_esquema.py) resetea los permisos de la vista a los del
-- dueño (sietel_user) -- borra cualquier GRANT previo, incluido el que
-- necesita mart_user para leerlas desde mart/detectar_conflictos_peva.py y
-- mart/construir_capa2.py. Antes esto vivía solo como comentario/paso manual
-- en sql/04_ddl_calidad.sql -- confirmado en producción 06-ago-2026 que se
-- pierde en cualquier corrida de Capa 1 posterior al GRANT manual, no solo
-- cuando hay CASCADE de por medio. Se integra aquí, en el propio DDL
-- idempotente de Capa 1, para que no dependa de que alguien recuerde
-- re-ejecutar un paso manual documentado en otro archivo.
--
-- Guardado con IF EXISTS sobre el rol: este archivo (01_ddl_postgres.sql)
-- es el DDL de Capa 1 y debe poder aplicarse en un entorno donde Capa 2/3
-- (mart_user) todavía no se haya aprovisionado.
--
-- GRANT explícito (cubre las vistas que existen HOY) + ALTER DEFAULT
-- PRIVILEGES (cubre cualquier vista/tabla que sietel_user cree en analitico
-- de aquí en adelante, sin depender de mantener esta lista actualizada a
-- mano) -- mismo patrón que 03_ddl_auth.sql ya usa para dashboard_lector
-- sobre el esquema mart. Sin el ALTER DEFAULT PRIVILEGES, agregar una
-- vista nueva a este archivo en el futuro y olvidar añadirla a la lista de
-- GRANT explícitos repetiría este mismo incidente (06-ago-2026).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mart_user') THEN
        GRANT USAGE ON SCHEMA analitico TO mart_user;
        GRANT SELECT ON analitico.v_ultimo_periodo_reportado_detalle TO mart_user;
        GRANT SELECT ON analitico.v_lineas_dedicadas_resumen TO mart_user;
        ALTER DEFAULT PRIVILEGES FOR ROLE sietel_user IN SCHEMA analitico
            GRANT SELECT ON TABLES TO mart_user;
    END IF;
END $$;

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

-- ============================================================================
-- 8. DIMENSION NodoISP (SCD Tipo 2) -- 06-ago-2026
-- ============================================================================
-- Fuente: dbo.NodoISP exclusivamente. dbo.NodoISP_Auxiliar queda fuera a
-- propósito -- EDA dirigido (06-ago-2026) confirmó que está congelada desde
-- 2014-07-03 (max fechaCreacion/fechaModificacion) y que sus 366 peva_codigo
-- ya están cubiertos por NodoISP (0 PEVA exclusivos de Auxiliar). Es un
-- remanente de migración, no una fuente paralela viva.
--
-- SCD Tipo 2 por el mismo motivo que dim_isp / dim_permiso_va_agregado:
-- SIETEL solo expone el estado ACTUAL del nodo. Un cambio de par_codigo,
-- estado (ACTIVO/CANCELADO), tipoNodo o coordenadas es un hecho de negocio
-- versionable -- sobrescribirlo en sitio ocultaría historia relevante para
-- auditoría (mismo principio que capa2/mart: nunca enmascarar).
--
-- IMPORTANTE: igual que COLUMNAS_VERSIONABLES_ISP/PERMISO, la lista de
-- columnas versionables de abajo (ver scripts/cargar_nodo_isp.py) es una
-- propuesta inicial, no confirmada formalmente con Mercados.
--
-- latitud/longitud se preservan tal cual las reporta SIETEL (nvarchar,
-- formato DMS libre, potencialmente sucio) -- Capa 1 certifica y extrae,
-- no transforma. La conversión a decimal y el cruce espacial contra el
-- shapefile de parroquias son responsabilidad de Capa 2/3 (mart), igual
-- que el resto de la limpieza de negocio de este pipeline.

CREATE TABLE IF NOT EXISTS staging.dim_nodo_isp (
    noisp_sk                 BIGSERIAL PRIMARY KEY,
    noisp_codigo              VARCHAR(50)  NOT NULL,
    peva_codigo               VARCHAR(50)  NOT NULL,
    par_codigo                VARCHAR(50),
    noisp_nombre              VARCHAR(50),
    noisp_fechaInicio         TIMESTAMP,
    noisp_oficioSenatel       VARCHAR(50),
    estado                    VARCHAR(50),
    tipoNodo                  VARCHAR(50),
    direccion                 TEXT,
    latitud                   VARCHAR(20),
    longitud                  VARCHAR(20),
    verificado                VARCHAR(2),
    observacion               TEXT,
    regional                  VARCHAR(50),
    fechaModificacion         TIMESTAMP,
    par_nombre                VARCHAR(100),
    codigo_parroquia          VARCHAR(50),
    ciu_nombre                VARCHAR(100),
    codigo_canton             VARCHAR(50),
    pro_nombre                VARCHAR(100),
    codigo_provincia          VARCHAR(50),
    fecha_inicio_vigencia     TIMESTAMP    NOT NULL DEFAULT now(),
    fecha_fin_vigencia        TIMESTAMP,
    es_vigente                BOOLEAN      NOT NULL DEFAULT true,
    fecha_carga                TIMESTAMP    NOT NULL DEFAULT now(),
    UNIQUE (noisp_codigo, fecha_inicio_vigencia)
);
CREATE INDEX IF NOT EXISTS ix_dim_nodo_isp_codigo_vigente ON staging.dim_nodo_isp (noisp_codigo) WHERE es_vigente = true;
CREATE INDEX IF NOT EXISTS ix_dim_nodo_isp_peva_vigente ON staging.dim_nodo_isp (peva_codigo) WHERE es_vigente = true;

-- Códigos INEC de parroquia/cantón/provincia (07-ago-2026) -- faltaban en
-- la versión original de esta tabla; mismo criterio ya aplicado a
-- va_lineas_dedicadas_resumen (sección 1): son metadata derivada de
-- par_codigo para cruce con fuentes externas (aquí, el shapefile CONALI de
-- Parte B), no forman parte de ninguna llave natural. ADD COLUMN IF NOT
-- EXISTS porque staging.dim_nodo_isp ya tenía 8.606 filas cargadas en
-- producción cuando se detectó la falta (necesarias para
-- mart/detectar_discrepancias_geografia_nodo.py, que compara esto contra
-- DPA_PARROQ del shapefile).
ALTER TABLE staging.dim_nodo_isp ADD COLUMN IF NOT EXISTS par_nombre VARCHAR(100);
ALTER TABLE staging.dim_nodo_isp ADD COLUMN IF NOT EXISTS codigo_parroquia VARCHAR(50);
ALTER TABLE staging.dim_nodo_isp ADD COLUMN IF NOT EXISTS ciu_nombre VARCHAR(100);
ALTER TABLE staging.dim_nodo_isp ADD COLUMN IF NOT EXISTS codigo_canton VARCHAR(50);
ALTER TABLE staging.dim_nodo_isp ADD COLUMN IF NOT EXISTS pro_nombre VARCHAR(100);
ALTER TABLE staging.dim_nodo_isp ADD COLUMN IF NOT EXISTS codigo_provincia VARCHAR(50);

COMMENT ON TABLE staging.dim_nodo_isp IS
'Dimensión SCD Tipo 2 de nodos de acceso de ISP (dbo.NodoISP). NodoISP_Auxiliar excluido a propósito -- ver EDA 06-ago-2026, congelada desde 2014 y sin cobertura exclusiva. latitud/longitud crudas (nvarchar, DMS libre) -- sin limpiar, sin cruce geográfico; eso vive en Capa 2/3. codigo_parroquia/codigo_canton/codigo_provincia son códigos INEC (no confundir con par_codigo/ciu_codigo/pro_codigo, PKs internas de SIETEL) -- agregados 07-ago-2026 para cruce contra el shapefile CONALI.';

-- ============================================================================
-- 9. VISTA — analitico.v_nodo_isp_vigente -- 06-ago-2026
-- ============================================================================
-- Interfaz de consumo de staging.dim_nodo_isp para Capa 2/3, mismo patrón
-- que analitico.v_lineas_dedicadas_resumen / v_ultimo_periodo_reportado_detalle:
-- Capa 2/3 nunca lee staging.* directamente, solo vistas de analitico.
-- Gracias al ALTER DEFAULT PRIVILEGES de la sección 6b, mart_user ya tiene
-- SELECT sobre esta vista automáticamente, sin GRANT adicional.
DROP VIEW IF EXISTS analitico.v_nodo_isp_vigente;

CREATE VIEW analitico.v_nodo_isp_vigente AS
SELECT
    n.noisp_sk, n.noisp_codigo, n.peva_codigo, n.par_codigo, n.noisp_nombre,
    n.noisp_fechaInicio, n.noisp_oficioSenatel, n.estado, n.tipoNodo,
    n.direccion, n.latitud, n.longitud, n.verificado, n.observacion,
    n.regional, n.fechaModificacion,
    n.par_nombre, n.codigo_parroquia, n.ciu_nombre, n.codigo_canton,
    n.pro_nombre, n.codigo_provincia
FROM staging.dim_nodo_isp n
WHERE n.es_vigente = true;

COMMENT ON VIEW analitico.v_nodo_isp_vigente IS
'Nodos de acceso ISP vigentes (dbo.NodoISP, sin NodoISP_Auxiliar). latitud/longitud crudas, sin limpiar -- la conversión DMS->decimal y validación viven en mart/limpiar_coordenadas_nodo_isp.py (Capa 2/3). codigo_parroquia/codigo_canton/codigo_provincia son códigos INEC (07-ago-2026), para cruce contra el shapefile CONALI en mart/detectar_discrepancias_geografia_nodo.py.';

COMMENT ON VIEW analitico.v_nodo_isp_vigente IS
'Nodos de acceso ISP vigentes (dbo.NodoISP, sin NodoISP_Auxiliar). latitud/longitud crudas, sin limpiar -- la conversión DMS->decimal y validación viven en mart/limpiar_coordenadas_nodo_isp.py (Capa 2/3).';