-- ============================================================
-- CAPA 3 ANALITICA PARA DASH / PLOTLY -- sql/02_ddl_mart.sql
-- Fuente:
--   capa2.lineas_dedicadas_consolidado
--
-- Corre como el rol mart_user (ver sql/00_roles_mart.sql), que es dueño
-- del esquema capa2 (Capa 2) y del esquema mart (Capa 3) -- separados
-- deliberadamente de "staging"/"analitico", que son propiedad de
-- sietel_user (sietel_pipeline). Dos pipelines, dos dueños de esquema,
-- sin mezclar privilegios.
--
-- CAMBIO respecto a la version anterior (revision profesional, 28-jul-2026):
--   - La fuente pasa de analitico.lineas_dedicadas_consolidado (una tabla
--     personal creada por un notebook manual en una base local) a
--     capa2.lineas_dedicadas_consolidado, generada por
--     mart/construir_capa2.py dentro de la MISMA base sietel_analitico.
--   - Seccion 9 (fact_lineas_geografia_mes): CORREGIDO un bug de
--     integridad de datos. La version anterior decidia MAX vs SUM
--     columna por columna, de forma independiente, para resolver
--     conflictos de multiples PEVA por RUC. Eso podia romper la
--     invariante SUM(rangos de velocidad) = total_lineas cuando un
--     prestador tenia PEVAs con valores genuinamente distintos en una
--     columna pero coincidentes por casualidad en otra. Ahora la
--     decision MAX-vs-SUM se toma UNA VEZ por grupo (prestador/periodo/
--     geografia) y se aplica de forma UNIFORME a todas las columnas.
--   - Seccion 17: agregada la validacion 17.8 que confirma la invariante
--     anterior -- el chequeo que habria detectado el bug si hubiera
--     existido antes.
--
-- REGLAS PRINCIPALES (sin cambios respecto al diseño original)
-- 1. Excluye por completo prestadores cuyo isp_nombre o
--    nombrecomercial contenga la palabra "prueba".
-- 2. Identifica al prestador por RUC limpio. Si no hay RUC,
--    utiliza PEVA como respaldo.
-- 3. Un mismo RUC puede tener varios PEVA:
--      - todos NULL            -> conserva NULL;
--      - solo uno con dato     -> conserva ese dato;
--      - valores iguales       -> conserva una sola vez;
--      - valores diferentes    -> los suma y deja trazabilidad
--                                 en audit_conflictos_peva.
--    Esta decision se aplica ahora a TODAS las columnas de metricas por
--    igual -- ver CAMBIO arriba.
-- 4. numero_prestadores incluye positivos, cero y NULL.
-- 5. Participacion e IHH usan solo prestadores con lineas > 0.
-- 6. Los cancelados dejan de aparecer cuando dejan de existir
--    en la capa 2.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS capa2;

-- ============================================================
-- 0. INDICES DE APOYO SOBRE LA CAPA 2
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_ldc_periodo
    ON capa2.lineas_dedicadas_consolidado (periodo);

CREATE INDEX IF NOT EXISTS idx_ldc_peva_periodo
    ON capa2.lineas_dedicadas_consolidado (
        (BTRIM(peva_codigo::text)),
        periodo DESC
    )
    WHERE peva_codigo IS NOT NULL
      AND BTRIM(peva_codigo::text) <> '';

CREATE INDEX IF NOT EXISTS idx_ldc_ruc_limpio_periodo
    ON capa2.lineas_dedicadas_consolidado (
        (
            NULLIF(
                REGEXP_REPLACE(
                    COALESCE(isp_ruc::text, ''),
                    '[^0-9]',
                    '',
                    'g'
                ),
                ''
            )
        ),
        periodo DESC
    );

CREATE INDEX IF NOT EXISTS idx_ldc_periodo_geografia
    ON capa2.lineas_dedicadas_consolidado (
        periodo,
        codigo_provincia,
        codigo_ciudad,
        codigo_parroquia
    );

CREATE INDEX IF NOT EXISTS idx_ldc_calidad_periodo
    ON capa2.lineas_dedicadas_consolidado (
        es_reportado,
        es_imputado,
        periodo
    );

ANALYZE capa2.lineas_dedicadas_consolidado;

BEGIN;

DROP SCHEMA IF EXISTS mart CASCADE;
CREATE SCHEMA mart;

-- ============================================================
-- 1. AUDITORIA DE PRESTADORES EXCLUIDOS POR "PRUEBA"
-- ============================================================

CREATE TABLE mart.audit_prestadores_prueba AS
SELECT
    NULLIF(
        REGEXP_REPLACE(
            COALESCE(isp_ruc::text, ''),
            '[^0-9]',
            '',
            'g'
        ),
        ''
    ) AS ruc_limpio,
    NULLIF(BTRIM(peva_codigo::text), '') AS peva_codigo,
    MAX(NULLIF(BTRIM(isp_nombre::text), '')) AS isp_nombre,
    MAX(NULLIF(BTRIM(nombrecomercial::text), '')) AS nombrecomercial,
    MIN(periodo)::date AS primer_periodo,
    MAX(periodo)::date AS ultimo_periodo,
    COUNT(*) AS filas_excluidas
FROM capa2.lineas_dedicadas_consolidado
WHERE COALESCE(isp_nombre::text, '') ILIKE '%prueba%'
   OR COALESCE(nombrecomercial::text, '') ILIKE '%prueba%'
GROUP BY
    NULLIF(
        REGEXP_REPLACE(
            COALESCE(isp_ruc::text, ''),
            '[^0-9]',
            '',
            'g'
        ),
        ''
    ),
    NULLIF(BTRIM(peva_codigo::text), '');

-- ============================================================
-- 2. FUENTE NORMALIZADA
-- ============================================================

CREATE MATERIALIZED VIEW mart.stg_fuente_normalizada AS
WITH base_raw AS (
    SELECT
        c.*,
        NULLIF(BTRIM(c.peva_codigo::text), '') AS peva_codigo_limpio,
        NULLIF(
            REGEXP_REPLACE(
                COALESCE(c.isp_ruc::text, ''),
                '[^0-9]',
                '',
                'g'
            ),
            ''
        ) AS ruc_limpio_original
    FROM capa2.lineas_dedicadas_consolidado c
    WHERE c.periodo IS NOT NULL
      AND c.peva_codigo IS NOT NULL
      AND BTRIM(c.peva_codigo::text) <> ''
),
ruc_prueba AS (
    SELECT DISTINCT ruc_limpio_original AS ruc_limpio
    FROM base_raw
    WHERE ruc_limpio_original IS NOT NULL
      AND (
          COALESCE(isp_nombre::text, '') ILIKE '%prueba%'
          OR COALESCE(nombrecomercial::text, '') ILIKE '%prueba%'
      )
),
peva_prueba AS (
    SELECT DISTINCT peva_codigo_limpio
    FROM base_raw
    WHERE peva_codigo_limpio IS NOT NULL
      AND (
          COALESCE(isp_nombre::text, '') ILIKE '%prueba%'
          OR COALESCE(nombrecomercial::text, '') ILIKE '%prueba%'
      )
),
base_filtrada AS (
    SELECT b.*
    FROM base_raw b
    WHERE NOT EXISTS (
        SELECT 1
        FROM ruc_prueba p
        WHERE p.ruc_limpio = b.ruc_limpio_original
    )
      AND NOT EXISTS (
        SELECT 1
        FROM peva_prueba p
        WHERE p.peva_codigo_limpio = b.peva_codigo_limpio
    )
),
mapa_ruc_peva AS (
    SELECT DISTINCT ON (peva_codigo_limpio)
        peva_codigo_limpio,
        ruc_limpio_original AS ruc_limpio_resuelto
    FROM base_filtrada
    WHERE ruc_limpio_original IS NOT NULL
    ORDER BY
        peva_codigo_limpio,
        periodo DESC,
        COALESCE(es_reportado, FALSE) DESC
)
SELECT
    b.*,
    COALESCE(
        b.ruc_limpio_original,
        m.ruc_limpio_resuelto
    ) AS ruc_limpio_resuelto,
    CASE
        WHEN COALESCE(
            b.ruc_limpio_original,
            m.ruc_limpio_resuelto
        ) IS NOT NULL
        THEN
            'RUC|' || COALESCE(
                b.ruc_limpio_original,
                m.ruc_limpio_resuelto
            )
        ELSE
            'PEVA|' || b.peva_codigo_limpio
    END AS prestador_id,
    'GEO|'
        || COALESCE(
            NULLIF(BTRIM(b.codigo_provincia::text), ''),
            'SIN_PROVINCIA'
        )
        || '|'
        || COALESCE(
            NULLIF(BTRIM(b.codigo_ciudad::text), ''),
            'SIN_CANTON'
        )
        || '|'
        || COALESCE(
            NULLIF(BTRIM(b.codigo_parroquia::text), ''),
            NULLIF(BTRIM(b.par_codigo::text), ''),
            'SIN_PARROQUIA'
        ) AS geografia_id,
    EXTRACT(YEAR FROM b.periodo)::integer * 100
        + EXTRACT(MONTH FROM b.periodo)::integer AS periodo_id
FROM base_filtrada b
LEFT JOIN mapa_ruc_peva m
  ON m.peva_codigo_limpio = b.peva_codigo_limpio;

CREATE INDEX idx_stg_fuente_periodo
    ON mart.stg_fuente_normalizada (periodo_id);

CREATE INDEX idx_stg_fuente_prestador
    ON mart.stg_fuente_normalizada (
        prestador_id,
        periodo_id
    );

CREATE INDEX idx_stg_fuente_peva
    ON mart.stg_fuente_normalizada (
        peva_codigo_limpio,
        periodo_id
    );

CREATE INDEX idx_stg_fuente_geografia
    ON mart.stg_fuente_normalizada (
        geografia_id,
        periodo_id
    );

-- ============================================================
-- 3. DIMENSION PERIODO
-- ============================================================

CREATE TABLE mart.dim_periodo (
    periodo_id       integer PRIMARY KEY,
    periodo          date NOT NULL UNIQUE,
    anio             integer NOT NULL,
    mes              integer NOT NULL CHECK (mes BETWEEN 1 AND 12),
    nombre_mes       text NOT NULL,
    trimestre        integer NOT NULL CHECK (trimestre BETWEEN 1 AND 4),
    anio_mes         text NOT NULL,
    anio_trimestre   text NOT NULL,
    inicio_trimestre date NOT NULL,
    fin_mes          date NOT NULL
);

INSERT INTO mart.dim_periodo (
    periodo_id,
    periodo,
    anio,
    mes,
    nombre_mes,
    trimestre,
    anio_mes,
    anio_trimestre,
    inicio_trimestre,
    fin_mes
)
SELECT
    EXTRACT(YEAR FROM gs.periodo)::integer * 100
        + EXTRACT(MONTH FROM gs.periodo)::integer,
    gs.periodo::date,
    EXTRACT(YEAR FROM gs.periodo)::integer,
    EXTRACT(MONTH FROM gs.periodo)::integer,
    CASE EXTRACT(MONTH FROM gs.periodo)::integer
        WHEN 1 THEN 'Enero'
        WHEN 2 THEN 'Febrero'
        WHEN 3 THEN 'Marzo'
        WHEN 4 THEN 'Abril'
        WHEN 5 THEN 'Mayo'
        WHEN 6 THEN 'Junio'
        WHEN 7 THEN 'Julio'
        WHEN 8 THEN 'Agosto'
        WHEN 9 THEN 'Septiembre'
        WHEN 10 THEN 'Octubre'
        WHEN 11 THEN 'Noviembre'
        WHEN 12 THEN 'Diciembre'
    END,
    EXTRACT(QUARTER FROM gs.periodo)::integer,
    TO_CHAR(gs.periodo, 'YYYY-MM'),
    EXTRACT(YEAR FROM gs.periodo)::integer::text
        || '-T'
        || EXTRACT(QUARTER FROM gs.periodo)::integer::text,
    DATE_TRUNC('quarter', gs.periodo)::date,
    (
        DATE_TRUNC('month', gs.periodo)
        + INTERVAL '1 month'
        - INTERVAL '1 day'
    )::date
FROM GENERATE_SERIES(
    (
        SELECT MIN(periodo)
        FROM mart.stg_fuente_normalizada
    )::timestamp,
    (
        SELECT MAX(periodo)
        FROM mart.stg_fuente_normalizada
    )::timestamp,
    INTERVAL '1 month'
) AS gs(periodo);

-- ============================================================
-- 4. DIMENSION PRESTADOR Y PUENTE PRESTADOR-PEVA
-- ============================================================

CREATE TABLE mart.dim_prestador (
    prestador_id              text PRIMARY KEY,
    ruc_limpio                text,
    isp_ruc                   text,
    peva_codigo_principal     text,
    cantidad_peva             integer NOT NULL,
    codigos_peva              text,
    isp_codigo                text,
    isp_nombre                text,
    nombrecomercial           text,
    isp_tipopersona           text,
    isp_regional              text,
    opera_actual              text,
    es_cancelado_actual       boolean NOT NULL DEFAULT FALSE,
    resolucion                text,
    fechapermiso_texto        text,
    fechapermiso              date,
    primer_periodo            date,
    ultimo_periodo            date,
    primer_periodo_reportado  date,
    ultimo_periodo_reportado  date
);

WITH ultimo_dato AS (
    SELECT DISTINCT ON (prestador_id)
        prestador_id,
        ruc_limpio_resuelto,
        NULLIF(BTRIM(isp_ruc::text), '') AS isp_ruc,
        peva_codigo_limpio,
        NULLIF(BTRIM(isp_codigo::text), '') AS isp_codigo,
        NULLIF(BTRIM(isp_nombre::text), '') AS isp_nombre,
        NULLIF(BTRIM(nombrecomercial::text), '') AS nombrecomercial,
        NULLIF(BTRIM(isp_tipopersona::text), '') AS isp_tipopersona,
        NULLIF(BTRIM(isp_regional::text), '') AS isp_regional,
        NULLIF(BTRIM(resolucion::text), '') AS resolucion,
        NULLIF(BTRIM(fechapermiso::text), '') AS fechapermiso_texto
    FROM mart.stg_fuente_normalizada
    ORDER BY
        prestador_id,
        periodo DESC,
        COALESCE(es_reportado, FALSE) DESC,
        (isp_nombre IS NOT NULL) DESC
),
rangos AS (
    SELECT
        prestador_id,
        MIN(periodo)::date AS primer_periodo,
        MAX(periodo)::date AS ultimo_periodo,
        MIN(periodo) FILTER (
            WHERE COALESCE(es_reportado, FALSE)
        )::date AS primer_periodo_reportado,
        MAX(periodo) FILTER (
            WHERE COALESCE(es_reportado, FALSE)
        )::date AS ultimo_periodo_reportado,
        COALESCE(
            BOOL_AND(es_cancelado_actual)
                FILTER (
                    WHERE es_cancelado_actual IS NOT NULL
                ),
            FALSE
        ) AS es_cancelado_actual,
        STRING_AGG(
            DISTINCT NULLIF(
                BTRIM(COALESCE(opera_actual, opera)::text),
                ''
            ),
            ', '
        ) AS opera_actual
    FROM mart.stg_fuente_normalizada
    GROUP BY prestador_id
),
pevas AS (
    SELECT
        prestador_id,
        COUNT(DISTINCT peva_codigo_limpio)::integer AS cantidad_peva,
        MIN(peva_codigo_limpio) AS peva_codigo_principal,
        STRING_AGG(
            DISTINCT peva_codigo_limpio,
            ', '
            ORDER BY peva_codigo_limpio
        ) AS codigos_peva
    FROM mart.stg_fuente_normalizada
    GROUP BY prestador_id
)
INSERT INTO mart.dim_prestador (
    prestador_id,
    ruc_limpio,
    isp_ruc,
    peva_codigo_principal,
    cantidad_peva,
    codigos_peva,
    isp_codigo,
    isp_nombre,
    nombrecomercial,
    isp_tipopersona,
    isp_regional,
    opera_actual,
    es_cancelado_actual,
    resolucion,
    fechapermiso_texto,
    fechapermiso,
    primer_periodo,
    ultimo_periodo,
    primer_periodo_reportado,
    ultimo_periodo_reportado
)
SELECT
    u.prestador_id,
    u.ruc_limpio_resuelto,
    COALESCE(u.isp_ruc, u.ruc_limpio_resuelto),
    p.peva_codigo_principal,
    p.cantidad_peva,
    p.codigos_peva,
    u.isp_codigo,
    u.isp_nombre,
    u.nombrecomercial,
    u.isp_tipopersona,
    u.isp_regional,
    r.opera_actual,
    r.es_cancelado_actual,
    u.resolucion,
    u.fechapermiso_texto,
    CASE
        WHEN u.fechapermiso_texto
            ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
        THEN LEFT(u.fechapermiso_texto, 10)::date
        WHEN u.fechapermiso_texto
            ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}'
        THEN TO_DATE(
            LEFT(u.fechapermiso_texto, 10),
            'DD/MM/YYYY'
        )
        ELSE NULL
    END,
    r.primer_periodo,
    r.ultimo_periodo,
    r.primer_periodo_reportado,
    r.ultimo_periodo_reportado
FROM ultimo_dato u
JOIN rangos r USING (prestador_id)
JOIN pevas p USING (prestador_id);

CREATE TABLE mart.bridge_prestador_peva (
    prestador_id text NOT NULL,
    peva_codigo  text NOT NULL,
    primer_periodo date,
    ultimo_periodo date,
    PRIMARY KEY (prestador_id, peva_codigo)
);

INSERT INTO mart.bridge_prestador_peva (
    prestador_id,
    peva_codigo,
    primer_periodo,
    ultimo_periodo
)
SELECT
    prestador_id,
    peva_codigo_limpio,
    MIN(periodo)::date,
    MAX(periodo)::date
FROM mart.stg_fuente_normalizada
GROUP BY
    prestador_id,
    peva_codigo_limpio;

CREATE INDEX idx_dim_prestador_nombre
    ON mart.dim_prestador (isp_nombre);

CREATE INDEX idx_dim_prestador_ruc
    ON mart.dim_prestador (ruc_limpio);

CREATE INDEX idx_dim_prestador_estado
    ON mart.dim_prestador (es_cancelado_actual);

CREATE INDEX idx_bridge_prestador_peva
    ON mart.bridge_prestador_peva (
        peva_codigo,
        prestador_id
    );

-- ============================================================
-- 5. DIMENSION GEOGRAFIA
-- ============================================================

CREATE TABLE mart.dim_geografia (
    geografia_id      text PRIMARY KEY,
    codigo_provincia  text,
    pro_nombre        text,
    codigo_canton     text,
    ciu_nombre        text,
    codigo_parroquia  text,
    par_codigo        text,
    par_nombre        text,
    regional_reporte  text
);

WITH ultima_geografia AS (
    SELECT DISTINCT ON (geografia_id)
        geografia_id,
        NULLIF(BTRIM(codigo_provincia::text), '') AS codigo_provincia,
        NULLIF(BTRIM(pro_nombre::text), '') AS pro_nombre,
        NULLIF(BTRIM(codigo_ciudad::text), '') AS codigo_canton,
        NULLIF(BTRIM(ciu_nombre::text), '') AS ciu_nombre,
        NULLIF(BTRIM(codigo_parroquia::text), '') AS codigo_parroquia,
        NULLIF(BTRIM(par_codigo::text), '') AS par_codigo,
        NULLIF(BTRIM(par_nombre::text), '') AS par_nombre,
        NULLIF(BTRIM(regional_reporte::text), '') AS regional_reporte
    FROM mart.stg_fuente_normalizada
    ORDER BY
        geografia_id,
        periodo DESC
)
INSERT INTO mart.dim_geografia
SELECT *
FROM ultima_geografia;

CREATE INDEX idx_dim_geografia_provincia
    ON mart.dim_geografia (codigo_provincia);

CREATE INDEX idx_dim_geografia_canton
    ON mart.dim_geografia (
        codigo_provincia,
        codigo_canton
    );

CREATE INDEX idx_dim_geografia_parroquia
    ON mart.dim_geografia (
        codigo_provincia,
        codigo_canton,
        codigo_parroquia
    );

-- ============================================================
-- 6. DIMENSION TERRITORIO Y PUENTE GEOGRAFICO
-- ============================================================

CREATE TABLE mart.dim_territorio (
    territorio_id       text PRIMARY KEY,
    nivel_geografico    text NOT NULL CHECK (
        nivel_geografico IN (
            'NACIONAL',
            'PROVINCIA',
            'CANTON',
            'PARROQUIA'
        )
    ),
    orden_nivel         integer NOT NULL,
    codigo_geografico   text,
    nombre_geografico   text NOT NULL,
    codigo_provincia    text,
    pro_nombre          text,
    codigo_canton       text,
    ciu_nombre          text,
    codigo_parroquia    text,
    par_nombre          text
);

INSERT INTO mart.dim_territorio VALUES (
    'NACIONAL|ECUADOR',
    'NACIONAL',
    0,
    'ECU',
    'Ecuador',
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL
);

INSERT INTO mart.dim_territorio
SELECT DISTINCT ON (codigo_provincia)
    'PROVINCIA|' || codigo_provincia,
    'PROVINCIA',
    1,
    codigo_provincia,
    COALESCE(pro_nombre, codigo_provincia),
    codigo_provincia,
    pro_nombre,
    NULL,
    NULL,
    NULL,
    NULL
FROM mart.dim_geografia
WHERE codigo_provincia IS NOT NULL
ORDER BY
    codigo_provincia,
    pro_nombre NULLS LAST;

INSERT INTO mart.dim_territorio
SELECT DISTINCT ON (
    codigo_provincia,
    codigo_canton
)
    'CANTON|'
        || codigo_provincia
        || '|'
        || codigo_canton,
    'CANTON',
    2,
    codigo_canton,
    COALESCE(ciu_nombre, codigo_canton),
    codigo_provincia,
    pro_nombre,
    codigo_canton,
    ciu_nombre,
    NULL,
    NULL
FROM mart.dim_geografia
WHERE codigo_provincia IS NOT NULL
  AND codigo_canton IS NOT NULL
ORDER BY
    codigo_provincia,
    codigo_canton,
    ciu_nombre NULLS LAST;

INSERT INTO mart.dim_territorio
SELECT DISTINCT ON (
    codigo_provincia,
    codigo_canton,
    COALESCE(
        codigo_parroquia,
        par_codigo
    )
)
    'PARROQUIA|'
        || codigo_provincia
        || '|'
        || codigo_canton
        || '|'
        || COALESCE(
            codigo_parroquia,
            par_codigo
        ),
    'PARROQUIA',
    3,
    COALESCE(
        codigo_parroquia,
        par_codigo
    ),
    COALESCE(
        par_nombre,
        codigo_parroquia,
        par_codigo
    ),
    codigo_provincia,
    pro_nombre,
    codigo_canton,
    ciu_nombre,
    COALESCE(
        codigo_parroquia,
        par_codigo
    ),
    par_nombre
FROM mart.dim_geografia
WHERE codigo_provincia IS NOT NULL
  AND codigo_canton IS NOT NULL
  AND COALESCE(
      codigo_parroquia,
      par_codigo
  ) IS NOT NULL
ORDER BY
    codigo_provincia,
    codigo_canton,
    COALESCE(
        codigo_parroquia,
        par_codigo
    ),
    par_nombre NULLS LAST;

CREATE TABLE mart.bridge_geografia_territorio (
    geografia_id  text NOT NULL,
    territorio_id text NOT NULL,
    PRIMARY KEY (
        geografia_id,
        territorio_id
    )
);

INSERT INTO mart.bridge_geografia_territorio
SELECT
    geografia_id,
    'NACIONAL|ECUADOR'
FROM mart.dim_geografia;

INSERT INTO mart.bridge_geografia_territorio
SELECT
    geografia_id,
    'PROVINCIA|' || codigo_provincia
FROM mart.dim_geografia
WHERE codigo_provincia IS NOT NULL;

INSERT INTO mart.bridge_geografia_territorio
SELECT
    geografia_id,
    'CANTON|'
        || codigo_provincia
        || '|'
        || codigo_canton
FROM mart.dim_geografia
WHERE codigo_provincia IS NOT NULL
  AND codigo_canton IS NOT NULL;

INSERT INTO mart.bridge_geografia_territorio
SELECT
    geografia_id,
    'PARROQUIA|'
        || codigo_provincia
        || '|'
        || codigo_canton
        || '|'
        || COALESCE(
            codigo_parroquia,
            par_codigo
        )
FROM mart.dim_geografia
WHERE codigo_provincia IS NOT NULL
  AND codigo_canton IS NOT NULL
  AND COALESCE(
      codigo_parroquia,
      par_codigo
  ) IS NOT NULL;

CREATE INDEX idx_dim_territorio_nivel
    ON mart.dim_territorio (
        nivel_geografico,
        nombre_geografico
    );

CREATE INDEX idx_dim_territorio_jerarquia
    ON mart.dim_territorio (
        codigo_provincia,
        codigo_canton,
        codigo_parroquia
    );

CREATE INDEX idx_bridge_territorio
    ON mart.bridge_geografia_territorio (
        territorio_id,
        geografia_id
    );

-- ============================================================
-- 7. PREAGREGACION POR PEVA, MES Y GEOGRAFIA
-- ============================================================

CREATE MATERIALIZED VIEW mart.stg_lineas_por_peva_geografia_mes AS
SELECT
    s.periodo_id,
    s.periodo::date AS periodo,
    s.prestador_id,
    s.peva_codigo_limpio AS peva_codigo,
    s.geografia_id,
    SUM(s.total_lineas::numeric) AS total_lineas,
        SUM(s.total_usuarios::numeric) AS total_usuarios,
        SUM(s.lineas_dl_sin_datos::numeric) AS lineas_dl_sin_datos,
        SUM(s.lineas_dl_menos_1mbps::numeric) AS lineas_dl_menos_1mbps,
        SUM(s.lineas_dl_1_10mbps::numeric) AS lineas_dl_1_10mbps,
        SUM(s.lineas_dl_10_30mbps::numeric) AS lineas_dl_10_30mbps,
        SUM(s.lineas_dl_30_100mbps::numeric) AS lineas_dl_30_100mbps,
        SUM(s.lineas_dl_100mbps_1gbps::numeric) AS lineas_dl_100mbps_1gbps,
        SUM(s.lineas_dl_1gbps_o_mas::numeric) AS lineas_dl_1gbps_o_mas,
        SUM(s.lineas_ul_sin_datos::numeric) AS lineas_ul_sin_datos,
        SUM(s.lineas_ul_menos_1mbps::numeric) AS lineas_ul_menos_1mbps,
        SUM(s.lineas_ul_1_10mbps::numeric) AS lineas_ul_1_10mbps,
        SUM(s.lineas_ul_10_30mbps::numeric) AS lineas_ul_10_30mbps,
        SUM(s.lineas_ul_30_100mbps::numeric) AS lineas_ul_30_100mbps,
        SUM(s.lineas_ul_100mbps_1gbps::numeric) AS lineas_ul_100mbps_1gbps,
        SUM(s.lineas_ul_1gbps_o_mas::numeric) AS lineas_ul_1gbps_o_mas,
        SUM(s.lineas_dl_banda_ancha::numeric) AS lineas_dl_banda_ancha,
        SUM(s.lineas_dl_ultra_banda_ancha::numeric) AS lineas_dl_ultra_banda_ancha,
    BOOL_OR(
        COALESCE(s.es_reportado, FALSE)
    ) AS tiene_reportado,
    BOOL_OR(
        COALESCE(s.es_imputado, FALSE)
    ) AS tiene_imputacion,
    BOOL_AND(
        COALESCE(s.es_reportado, FALSE)
    ) AS es_totalmente_reportado,
    COUNT(*) AS filas_origen
FROM mart.stg_fuente_normalizada s
GROUP BY
    s.periodo_id,
    s.periodo,
    s.prestador_id,
    s.peva_codigo_limpio,
    s.geografia_id;

CREATE UNIQUE INDEX uq_stg_lineas_peva_geo_mes
    ON mart.stg_lineas_por_peva_geografia_mes (
        periodo_id,
        prestador_id,
        peva_codigo,
        geografia_id
    );

-- ============================================================
-- 8. AUDITORIA DE PEVA CON VALORES DIFERENTES
-- ============================================================

CREATE MATERIALIZED VIEW mart.audit_conflictos_peva AS
SELECT
    p.periodo_id,
    p.periodo,
    p.prestador_id,
    p.geografia_id,
    COUNT(DISTINCT p.peva_codigo) AS cantidad_peva,
    STRING_AGG(
        DISTINCT p.peva_codigo,
        ', '
        ORDER BY p.peva_codigo
    ) AS codigos_peva,
    COUNT(DISTINCT p.total_lineas)
        FILTER (
            WHERE p.total_lineas IS NOT NULL
        ) AS valores_distintos_total_lineas,
    JSONB_AGG(
        JSONB_BUILD_OBJECT(
            'peva_codigo', p.peva_codigo,
            'total_lineas', p.total_lineas,
            'total_usuarios', p.total_usuarios
        )
        ORDER BY p.peva_codigo
    ) AS detalle_peva
FROM mart.stg_lineas_por_peva_geografia_mes p
GROUP BY
    p.periodo_id,
    p.periodo,
    p.prestador_id,
    p.geografia_id
HAVING COUNT(DISTINCT p.peva_codigo) > 1
   AND COUNT(DISTINCT p.total_lineas)
       FILTER (
           WHERE p.total_lineas IS NOT NULL
       ) > 1;

CREATE INDEX idx_audit_conflictos_prestador
    ON mart.audit_conflictos_peva (
        prestador_id,
        periodo_id
    );

-- ============================================================
-- 9. HECHO BASE RESUELTO POR PRESTADOR
-- ============================================================

CREATE MATERIALIZED VIEW mart.fact_lineas_geografia_mes AS
WITH agregados AS (
    SELECT
        p.periodo_id,
        p.prestador_id,
        p.geografia_id,
        MAX(p.periodo)::date AS periodo,
        COUNT(DISTINCT p.peva_codigo)::integer AS cantidad_peva,
        STRING_AGG(
            DISTINCT p.peva_codigo,
            ', '
            ORDER BY p.peva_codigo
        ) AS codigos_peva,
        COUNT(p.total_lineas) AS n_con_dato_total_lineas,
        COUNT(DISTINCT p.total_lineas)
            FILTER (WHERE p.total_lineas IS NOT NULL)
            AS valores_distintos_total_lineas,
        MAX(p.total_lineas) AS max_total_lineas,
        SUM(p.total_lineas) AS sum_total_lineas,
        MAX(p.total_usuarios) AS max_total_usuarios,
        SUM(p.total_usuarios) AS sum_total_usuarios,
        MAX(p.lineas_dl_sin_datos) AS max_lineas_dl_sin_datos,
        SUM(p.lineas_dl_sin_datos) AS sum_lineas_dl_sin_datos,
        MAX(p.lineas_dl_menos_1mbps) AS max_lineas_dl_menos_1mbps,
        SUM(p.lineas_dl_menos_1mbps) AS sum_lineas_dl_menos_1mbps,
        MAX(p.lineas_dl_1_10mbps) AS max_lineas_dl_1_10mbps,
        SUM(p.lineas_dl_1_10mbps) AS sum_lineas_dl_1_10mbps,
        MAX(p.lineas_dl_10_30mbps) AS max_lineas_dl_10_30mbps,
        SUM(p.lineas_dl_10_30mbps) AS sum_lineas_dl_10_30mbps,
        MAX(p.lineas_dl_30_100mbps) AS max_lineas_dl_30_100mbps,
        SUM(p.lineas_dl_30_100mbps) AS sum_lineas_dl_30_100mbps,
        MAX(p.lineas_dl_100mbps_1gbps) AS max_lineas_dl_100mbps_1gbps,
        SUM(p.lineas_dl_100mbps_1gbps) AS sum_lineas_dl_100mbps_1gbps,
        MAX(p.lineas_dl_1gbps_o_mas) AS max_lineas_dl_1gbps_o_mas,
        SUM(p.lineas_dl_1gbps_o_mas) AS sum_lineas_dl_1gbps_o_mas,
        MAX(p.lineas_ul_sin_datos) AS max_lineas_ul_sin_datos,
        SUM(p.lineas_ul_sin_datos) AS sum_lineas_ul_sin_datos,
        MAX(p.lineas_ul_menos_1mbps) AS max_lineas_ul_menos_1mbps,
        SUM(p.lineas_ul_menos_1mbps) AS sum_lineas_ul_menos_1mbps,
        MAX(p.lineas_ul_1_10mbps) AS max_lineas_ul_1_10mbps,
        SUM(p.lineas_ul_1_10mbps) AS sum_lineas_ul_1_10mbps,
        MAX(p.lineas_ul_10_30mbps) AS max_lineas_ul_10_30mbps,
        SUM(p.lineas_ul_10_30mbps) AS sum_lineas_ul_10_30mbps,
        MAX(p.lineas_ul_30_100mbps) AS max_lineas_ul_30_100mbps,
        SUM(p.lineas_ul_30_100mbps) AS sum_lineas_ul_30_100mbps,
        MAX(p.lineas_ul_100mbps_1gbps) AS max_lineas_ul_100mbps_1gbps,
        SUM(p.lineas_ul_100mbps_1gbps) AS sum_lineas_ul_100mbps_1gbps,
        MAX(p.lineas_ul_1gbps_o_mas) AS max_lineas_ul_1gbps_o_mas,
        SUM(p.lineas_ul_1gbps_o_mas) AS sum_lineas_ul_1gbps_o_mas,
        MAX(p.lineas_dl_banda_ancha) AS max_lineas_dl_banda_ancha,
        SUM(p.lineas_dl_banda_ancha) AS sum_lineas_dl_banda_ancha,
        MAX(p.lineas_dl_ultra_banda_ancha) AS max_lineas_dl_ultra_banda_ancha,
        SUM(p.lineas_dl_ultra_banda_ancha) AS sum_lineas_dl_ultra_banda_ancha,
        BOOL_OR(p.tiene_reportado) AS tiene_reportado,
        BOOL_OR(p.tiene_imputacion) AS tiene_imputacion,
        BOOL_AND(p.es_totalmente_reportado) AS es_totalmente_reportado,
        SUM(p.filas_origen) AS filas_origen
    FROM mart.stg_lineas_por_peva_geografia_mes p
    GROUP BY
        p.periodo_id,
        p.prestador_id,
        p.geografia_id
),
-- La decision MAX-vs-SUM se calcula UNA SOLA VEZ por grupo, usando
-- total_lineas como columna de referencia (es la que define si el
-- prestador tiene PEVAs con datos genuinamente distintos o no) -- y
-- se aplica de forma UNIFORME a TODAS las columnas de metricas en el
-- SELECT final. Esto es la correccion del bug original: la version
-- anterior tomaba esta decision columna por columna, lo que podia
-- romper la invariante SUM(rangos de velocidad) = total_lineas.
estado AS (
    SELECT
        periodo_id,
        prestador_id,
        geografia_id,
        CASE
            WHEN cantidad_peva = 1 THEN 'UN_SOLO_PEVA'
            WHEN n_con_dato_total_lineas = 0 THEN 'TODOS_SIN_DATO'
            WHEN valores_distintos_total_lineas <= 1 THEN 'PEVA_DUPLICADOS_MISMO_VALOR_O_UNICO'
            ELSE 'PEVA_VALORES_DIFERENTES_SUMADOS'
        END AS estado_resolucion_peva
    FROM agregados
)
SELECT
    a.periodo_id,
    a.periodo,
    a.prestador_id,
    a.geografia_id,
    a.cantidad_peva,
    a.codigos_peva,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_total_lineas
        ELSE a.max_total_lineas
    END AS total_lineas,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_total_usuarios
        ELSE a.max_total_usuarios
    END AS total_usuarios,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_lineas_dl_sin_datos
        ELSE a.max_lineas_dl_sin_datos
    END AS lineas_dl_sin_datos,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_lineas_dl_menos_1mbps
        ELSE a.max_lineas_dl_menos_1mbps
    END AS lineas_dl_menos_1mbps,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_lineas_dl_1_10mbps
        ELSE a.max_lineas_dl_1_10mbps
    END AS lineas_dl_1_10mbps,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_lineas_dl_10_30mbps
        ELSE a.max_lineas_dl_10_30mbps
    END AS lineas_dl_10_30mbps,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_lineas_dl_30_100mbps
        ELSE a.max_lineas_dl_30_100mbps
    END AS lineas_dl_30_100mbps,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_lineas_dl_100mbps_1gbps
        ELSE a.max_lineas_dl_100mbps_1gbps
    END AS lineas_dl_100mbps_1gbps,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_lineas_dl_1gbps_o_mas
        ELSE a.max_lineas_dl_1gbps_o_mas
    END AS lineas_dl_1gbps_o_mas,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_lineas_ul_sin_datos
        ELSE a.max_lineas_ul_sin_datos
    END AS lineas_ul_sin_datos,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_lineas_ul_menos_1mbps
        ELSE a.max_lineas_ul_menos_1mbps
    END AS lineas_ul_menos_1mbps,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_lineas_ul_1_10mbps
        ELSE a.max_lineas_ul_1_10mbps
    END AS lineas_ul_1_10mbps,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_lineas_ul_10_30mbps
        ELSE a.max_lineas_ul_10_30mbps
    END AS lineas_ul_10_30mbps,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_lineas_ul_30_100mbps
        ELSE a.max_lineas_ul_30_100mbps
    END AS lineas_ul_30_100mbps,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_lineas_ul_100mbps_1gbps
        ELSE a.max_lineas_ul_100mbps_1gbps
    END AS lineas_ul_100mbps_1gbps,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_lineas_ul_1gbps_o_mas
        ELSE a.max_lineas_ul_1gbps_o_mas
    END AS lineas_ul_1gbps_o_mas,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_lineas_dl_banda_ancha
        ELSE a.max_lineas_dl_banda_ancha
    END AS lineas_dl_banda_ancha,
    CASE
        WHEN e.estado_resolucion_peva = 'TODOS_SIN_DATO' THEN NULL::numeric
        WHEN e.estado_resolucion_peva = 'PEVA_VALORES_DIFERENTES_SUMADOS' THEN a.sum_lineas_dl_ultra_banda_ancha
        ELSE a.max_lineas_dl_ultra_banda_ancha
    END AS lineas_dl_ultra_banda_ancha,
    a.tiene_reportado,
    a.tiene_imputacion,
    a.es_totalmente_reportado,
    a.filas_origen,
    e.estado_resolucion_peva
FROM agregados a
JOIN estado e
  ON  e.periodo_id = a.periodo_id
  AND e.prestador_id = a.prestador_id
  AND e.geografia_id = a.geografia_id;

CREATE UNIQUE INDEX uq_fact_lineas_geografia_mes
    ON mart.fact_lineas_geografia_mes (
        periodo_id,
        prestador_id,
        geografia_id
    );

CREATE INDEX idx_fact_lineas_periodo
    ON mart.fact_lineas_geografia_mes (
        periodo_id
    );

CREATE INDEX idx_fact_lineas_prestador
    ON mart.fact_lineas_geografia_mes (
        prestador_id,
        periodo_id
    );

CREATE INDEX idx_fact_lineas_geografia
    ON mart.fact_lineas_geografia_mes (
        geografia_id,
        periodo_id
    );

CREATE INDEX idx_fact_lineas_resolucion
    ON mart.fact_lineas_geografia_mes (
        estado_resolucion_peva
    );

-- ============================================================
-- 10. HECHO BASE DE VELOCIDADES
-- ============================================================

CREATE MATERIALIZED VIEW mart.fact_lineas_velocidad_mes AS
SELECT
    f.periodo_id,
    f.periodo,
    f.prestador_id,
    f.geografia_id,
    v.tipo_velocidad,
    v.orden_rango,
    v.rango_velocidad,
    v.total_lineas_velocidad,
    CASE
        WHEN f.es_totalmente_reportado
        THEN v.total_lineas_velocidad
        ELSE 0::numeric
    END AS lineas_reportadas,
    CASE
        WHEN f.tiene_imputacion
        THEN v.total_lineas_velocidad
        ELSE 0::numeric
    END AS lineas_imputadas,
    f.tiene_imputacion,
    f.estado_resolucion_peva
FROM mart.fact_lineas_geografia_mes f
CROSS JOIN LATERAL (
    VALUES
        (
            'DESCARGA',
            1,
            'Sin datos',
            f.lineas_dl_sin_datos
        ),
        (
            'DESCARGA',
            2,
            'Menos de 1 Mbps',
            f.lineas_dl_menos_1mbps
        ),
        (
            'DESCARGA',
            3,
            '1 a 10 Mbps',
            f.lineas_dl_1_10mbps
        ),
        (
            'DESCARGA',
            4,
            '10 a 30 Mbps',
            f.lineas_dl_10_30mbps
        ),
        (
            'DESCARGA',
            5,
            '30 a 100 Mbps',
            f.lineas_dl_30_100mbps
        ),
        (
            'DESCARGA',
            6,
            '100 Mbps a 1 Gbps',
            f.lineas_dl_100mbps_1gbps
        ),
        (
            'DESCARGA',
            7,
            '1 Gbps o más',
            f.lineas_dl_1gbps_o_mas
        ),
        (
            'SUBIDA',
            1,
            'Sin datos',
            f.lineas_ul_sin_datos
        ),
        (
            'SUBIDA',
            2,
            'Menos de 1 Mbps',
            f.lineas_ul_menos_1mbps
        ),
        (
            'SUBIDA',
            3,
            '1 a 10 Mbps',
            f.lineas_ul_1_10mbps
        ),
        (
            'SUBIDA',
            4,
            '10 a 30 Mbps',
            f.lineas_ul_10_30mbps
        ),
        (
            'SUBIDA',
            5,
            '30 a 100 Mbps',
            f.lineas_ul_30_100mbps
        ),
        (
            'SUBIDA',
            6,
            '100 Mbps a 1 Gbps',
            f.lineas_ul_100mbps_1gbps
        ),
        (
            'SUBIDA',
            7,
            '1 Gbps o más',
            f.lineas_ul_1gbps_o_mas
        )
) AS v(
    tipo_velocidad,
    orden_rango,
    rango_velocidad,
    total_lineas_velocidad
);

CREATE UNIQUE INDEX uq_fact_lineas_velocidad_mes
    ON mart.fact_lineas_velocidad_mes (
        periodo_id,
        prestador_id,
        geografia_id,
        tipo_velocidad,
        orden_rango
    );

CREATE INDEX idx_fact_velocidad_periodo
    ON mart.fact_lineas_velocidad_mes (
        periodo_id,
        tipo_velocidad
    );

-- ============================================================
-- 11. RESUMEN DE EVOLUCION DEL MERCADO
-- ============================================================

CREATE MATERIALIZED VIEW mart.fact_resumen_mercado_mes AS
WITH prestador_territorio AS (
    SELECT
        f.periodo_id,
        b.territorio_id,
        f.prestador_id,
        SUM(f.total_lineas) AS total_lineas_prestador,
        SUM(f.total_usuarios) AS total_usuarios_prestador,
        SUM(
            CASE
                WHEN f.tiene_imputacion
                THEN 0
                ELSE COALESCE(f.total_lineas, 0)
            END
        ) AS lineas_reportadas_prestador,
        SUM(
            CASE
                WHEN f.tiene_imputacion
                THEN COALESCE(f.total_lineas, 0)
                ELSE 0
            END
        ) AS lineas_imputadas_prestador,
        BOOL_OR(f.tiene_imputacion)
            AS tiene_imputacion
    FROM mart.fact_lineas_geografia_mes f
    JOIN mart.bridge_geografia_territorio b
      ON b.geografia_id = f.geografia_id
    GROUP BY
        f.periodo_id,
        b.territorio_id,
        f.prestador_id
),
mercado AS (
    SELECT
        periodo_id,
        territorio_id,
        SUM(total_lineas_prestador)
            AS total_lineas,
        SUM(total_usuarios_prestador)
            AS total_usuarios,
        COUNT(*) AS numero_prestadores,
        COUNT(*) FILTER (
            WHERE total_lineas_prestador > 0
        ) AS numero_prestadores_con_lineas,
        COUNT(*) FILTER (
            WHERE total_lineas_prestador = 0
        ) AS numero_prestadores_cero,
        COUNT(*) FILTER (
            WHERE total_lineas_prestador IS NULL
        ) AS numero_prestadores_sin_dato,
        SUM(lineas_reportadas_prestador)
            AS lineas_reportadas,
        SUM(lineas_imputadas_prestador)
            AS lineas_imputadas,
        COUNT(*) FILTER (
            WHERE tiene_imputacion
        ) AS numero_prestadores_imputados
    FROM prestador_territorio
    GROUP BY
        periodo_id,
        territorio_id
),
con_fechas AS (
    SELECT
        m.*,
        d.periodo
    FROM mercado m
    JOIN mart.dim_periodo d
      ON d.periodo_id = m.periodo_id
)
SELECT
    a.periodo_id,
    a.territorio_id,
    a.total_lineas,
    a.total_usuarios,
    a.numero_prestadores,
    a.numero_prestadores_con_lineas,
    a.numero_prestadores_cero,
    a.numero_prestadores_sin_dato,
    a.numero_prestadores_imputados,
    a.lineas_reportadas,
    a.lineas_imputadas,
    ROUND(
        100.0
        * a.lineas_imputadas
        / NULLIF(a.total_lineas, 0),
        6
    ) AS porcentaje_imputado,
    a.total_lineas - pm.total_lineas
        AS diferencia_mensual_lineas,
    ROUND(
        100.0
        * (a.total_lineas - pm.total_lineas)
        / NULLIF(pm.total_lineas, 0),
        6
    ) AS variacion_mensual_porcentaje,
    a.total_lineas - pa.total_lineas
        AS diferencia_anual_lineas,
    ROUND(
        100.0
        * (a.total_lineas - pa.total_lineas)
        / NULLIF(pa.total_lineas, 0),
        6
    ) AS variacion_anual_porcentaje,
    a.numero_prestadores
        - pm.numero_prestadores
        AS diferencia_mensual_prestadores,
    a.numero_prestadores
        - pa.numero_prestadores
        AS diferencia_anual_prestadores
FROM con_fechas a
LEFT JOIN mart.dim_periodo dpm
  ON dpm.periodo = (
      a.periodo - INTERVAL '1 month'
  )::date
LEFT JOIN mercado pm
  ON pm.periodo_id = dpm.periodo_id
 AND pm.territorio_id = a.territorio_id
LEFT JOIN mart.dim_periodo dpa
  ON dpa.periodo = (
      a.periodo - INTERVAL '1 year'
  )::date
LEFT JOIN mercado pa
  ON pa.periodo_id = dpa.periodo_id
 AND pa.territorio_id = a.territorio_id;

CREATE UNIQUE INDEX uq_fact_resumen_mercado_mes
    ON mart.fact_resumen_mercado_mes (
        periodo_id,
        territorio_id
    );

CREATE INDEX idx_fact_resumen_territorio
    ON mart.fact_resumen_mercado_mes (
        territorio_id,
        periodo_id
    );

-- ============================================================
-- 12. RESUMEN DE VELOCIDADES
-- ============================================================

CREATE MATERIALIZED VIEW mart.fact_velocidad_mercado_mes AS
WITH mercado AS (
    SELECT
        f.periodo_id,
        b.territorio_id,
        f.tipo_velocidad,
        f.orden_rango,
        f.rango_velocidad,
        SUM(f.total_lineas_velocidad)
            AS total_lineas,
        SUM(f.lineas_reportadas)
            AS lineas_reportadas,
        SUM(f.lineas_imputadas)
            AS lineas_imputadas
    FROM mart.fact_lineas_velocidad_mes f
    JOIN mart.bridge_geografia_territorio b
      ON b.geografia_id = f.geografia_id
    GROUP BY
        f.periodo_id,
        b.territorio_id,
        f.tipo_velocidad,
        f.orden_rango,
        f.rango_velocidad
),
con_totales AS (
    SELECT
        m.*,
        SUM(m.total_lineas) OVER (
            PARTITION BY
                m.periodo_id,
                m.territorio_id,
                m.tipo_velocidad
        ) AS total_lineas_tipo,
        d.periodo
    FROM mercado m
    JOIN mart.dim_periodo d
      ON d.periodo_id = m.periodo_id
)
SELECT
    a.periodo_id,
    a.territorio_id,
    a.tipo_velocidad,
    a.orden_rango,
    a.rango_velocidad,
    a.total_lineas,
    a.total_lineas_tipo,
    ROUND(
        100.0
        * a.total_lineas
        / NULLIF(a.total_lineas_tipo, 0),
        6
    ) AS participacion_rango_porcentaje,
    a.lineas_reportadas,
    a.lineas_imputadas,
    ROUND(
        100.0
        * a.lineas_imputadas
        / NULLIF(a.total_lineas, 0),
        6
    ) AS porcentaje_imputado,
    a.total_lineas - pm.total_lineas
        AS diferencia_mensual,
    ROUND(
        100.0
        * (a.total_lineas - pm.total_lineas)
        / NULLIF(pm.total_lineas, 0),
        6
    ) AS variacion_mensual_porcentaje,
    a.total_lineas - pa.total_lineas
        AS diferencia_anual,
    ROUND(
        100.0
        * (a.total_lineas - pa.total_lineas)
        / NULLIF(pa.total_lineas, 0),
        6
    ) AS variacion_anual_porcentaje
FROM con_totales a
LEFT JOIN mart.dim_periodo dpm
  ON dpm.periodo = (
      a.periodo - INTERVAL '1 month'
  )::date
LEFT JOIN mercado pm
  ON pm.periodo_id = dpm.periodo_id
 AND pm.territorio_id = a.territorio_id
 AND pm.tipo_velocidad = a.tipo_velocidad
 AND pm.orden_rango = a.orden_rango
LEFT JOIN mart.dim_periodo dpa
  ON dpa.periodo = (
      a.periodo - INTERVAL '1 year'
  )::date
LEFT JOIN mercado pa
  ON pa.periodo_id = dpa.periodo_id
 AND pa.territorio_id = a.territorio_id
 AND pa.tipo_velocidad = a.tipo_velocidad
 AND pa.orden_rango = a.orden_rango;

CREATE UNIQUE INDEX uq_fact_velocidad_mercado_mes
    ON mart.fact_velocidad_mercado_mes (
        periodo_id,
        territorio_id,
        tipo_velocidad,
        orden_rango
    );

CREATE INDEX idx_fact_velocidad_mercado_filtro
    ON mart.fact_velocidad_mercado_mes (
        territorio_id,
        tipo_velocidad,
        periodo_id
    );

-- ============================================================
-- 13. PARTICIPACION DE MERCADO
-- ============================================================

CREATE MATERIALIZED VIEW mart.fact_participacion_mercado AS
WITH prestador_territorio AS (
    SELECT
        f.periodo_id,
        b.territorio_id,
        f.prestador_id,
        SUM(f.total_lineas)
            AS total_lineas_prestador,
        SUM(
            CASE
                WHEN f.tiene_imputacion
                THEN 0
                ELSE COALESCE(f.total_lineas, 0)
            END
        ) AS lineas_reportadas,
        SUM(
            CASE
                WHEN f.tiene_imputacion
                THEN COALESCE(f.total_lineas, 0)
                ELSE 0
            END
        ) AS lineas_imputadas,
        BOOL_OR(f.tiene_imputacion)
            AS tiene_imputacion
    FROM mart.fact_lineas_geografia_mes f
    JOIN mart.bridge_geografia_territorio b
      ON b.geografia_id = f.geografia_id
    GROUP BY
        f.periodo_id,
        b.territorio_id,
        f.prestador_id
),
totales AS (
    SELECT
        p.*,
        SUM(
            CASE
                WHEN p.total_lineas_prestador > 0
                THEN p.total_lineas_prestador
                ELSE 0
            END
        ) OVER (
            PARTITION BY
                p.periodo_id,
                p.territorio_id
        ) AS total_lineas_mercado
    FROM prestador_territorio p
),
ranking AS (
    SELECT
        t.*,
        CASE
            WHEN t.total_lineas_prestador > 0
            THEN ROW_NUMBER() OVER (
                PARTITION BY
                    t.periodo_id,
                    t.territorio_id
                ORDER BY
                    CASE
                        WHEN t.total_lineas_prestador > 0
                        THEN 0
                        ELSE 1
                    END,
                    t.total_lineas_prestador DESC NULLS LAST,
                    t.prestador_id
            )
        END AS ranking_prestador
    FROM totales t
)
SELECT
    periodo_id,
    territorio_id,
    prestador_id,
    total_lineas_prestador,
    total_lineas_mercado,
    CASE
        WHEN total_lineas_prestador > 0
         AND total_lineas_mercado > 0
        THEN ROUND(
            total_lineas_prestador
            / total_lineas_mercado,
            10
        )
    END AS participacion_decimal,
    CASE
        WHEN total_lineas_prestador > 0
         AND total_lineas_mercado > 0
        THEN ROUND(
            100.0
            * total_lineas_prestador
            / total_lineas_mercado,
            8
        )
    END AS participacion_porcentaje,
    CASE
        WHEN total_lineas_prestador > 0
         AND total_lineas_mercado > 0
        THEN ROUND(
            POWER(
                100.0
                * total_lineas_prestador
                / total_lineas_mercado,
                2
            ),
            8
        )
    END AS aporte_ihh,
    ranking_prestador,
    ranking_prestador = 1 AS es_lider,
    CASE
        WHEN total_lineas_prestador > 0
            THEN 'POSITIVO'
        WHEN total_lineas_prestador = 0
            THEN 'CERO'
        ELSE 'SIN_DATO'
    END AS estado_lineas,
    lineas_reportadas,
    lineas_imputadas,
    ROUND(
        100.0
        * lineas_imputadas
        / NULLIF(total_lineas_prestador, 0),
        6
    ) AS porcentaje_imputado_prestador,
    tiene_imputacion
FROM ranking;

CREATE UNIQUE INDEX uq_fact_participacion_mercado
    ON mart.fact_participacion_mercado (
        periodo_id,
        territorio_id,
        prestador_id
    );

CREATE INDEX idx_participacion_dashboard
    ON mart.fact_participacion_mercado (
        territorio_id,
        periodo_id,
        ranking_prestador
    );

CREATE INDEX idx_participacion_prestador
    ON mart.fact_participacion_mercado (
        prestador_id,
        periodo_id
    );

-- ============================================================
-- 14. IHH GEOGRAFICO
-- ============================================================

CREATE MATERIALIZED VIEW mart.fact_ihh_geografico AS
SELECT
    periodo_id,
    territorio_id,
    MAX(total_lineas_mercado)
        AS total_lineas_mercado,
    COUNT(*) AS numero_prestadores,
    COUNT(*) FILTER (
        WHERE total_lineas_prestador > 0
    ) AS numero_prestadores_con_lineas,
    COUNT(*) FILTER (
        WHERE total_lineas_prestador = 0
    ) AS numero_prestadores_cero,
    COUNT(*) FILTER (
        WHERE total_lineas_prestador IS NULL
    ) AS numero_prestadores_sin_dato,
    ROUND(
        COALESCE(
            SUM(aporte_ihh),
            0
        ),
        6
    ) AS ihh,
    MAX(prestador_id) FILTER (
        WHERE ranking_prestador = 1
    ) AS prestador_lider_id,
    MAX(participacion_porcentaje) FILTER (
        WHERE ranking_prestador = 1
    ) AS participacion_lider,
    ROUND(
        COALESCE(
            SUM(participacion_porcentaje)
                FILTER (
                    WHERE ranking_prestador <= 2
                ),
            0
        ),
        6
    ) AS cr2,
    ROUND(
        COALESCE(
            SUM(participacion_porcentaje)
                FILTER (
                    WHERE ranking_prestador <= 4
                ),
            0
        ),
        6
    ) AS cr4,
    SUM(lineas_reportadas)
        AS lineas_reportadas_mercado,
    SUM(lineas_imputadas)
        AS lineas_imputadas_mercado,
    ROUND(
        100.0
        * SUM(lineas_imputadas)
        / NULLIF(
            MAX(total_lineas_mercado),
            0
        ),
        6
    ) AS porcentaje_imputado_mercado,
    COUNT(*) FILTER (
        WHERE tiene_imputacion
    ) AS numero_prestadores_imputados
FROM mart.fact_participacion_mercado
GROUP BY
    periodo_id,
    territorio_id;

CREATE UNIQUE INDEX uq_fact_ihh_geografico
    ON mart.fact_ihh_geografico (
        periodo_id,
        territorio_id
    );

CREATE INDEX idx_ihh_territorio_periodo
    ON mart.fact_ihh_geografico (
        territorio_id,
        periodo_id
    );

-- ============================================================
-- 15. VISTAS PARA DASH
-- ============================================================

CREATE VIEW mart.vw_dashboard_evolucion AS
SELECT
    f.periodo_id,
    d.periodo,
    d.anio,
    d.mes,
    d.nombre_mes,
    d.trimestre,
    d.anio_mes,
    d.anio_trimestre,
    t.territorio_id,
    t.nivel_geografico,
    t.orden_nivel,
    t.codigo_geografico,
    t.nombre_geografico,
    t.codigo_provincia,
    t.pro_nombre,
    t.codigo_canton,
    t.ciu_nombre,
    t.codigo_parroquia,
    t.par_nombre,
    f.total_lineas,
    f.total_usuarios,
    f.numero_prestadores,
    f.numero_prestadores_con_lineas,
    f.numero_prestadores_cero,
    f.numero_prestadores_sin_dato,
    f.numero_prestadores_imputados,
    f.lineas_reportadas,
    f.lineas_imputadas,
    f.porcentaje_imputado,
    f.diferencia_mensual_lineas,
    f.variacion_mensual_porcentaje,
    f.diferencia_anual_lineas,
    f.variacion_anual_porcentaje,
    f.diferencia_mensual_prestadores,
    f.diferencia_anual_prestadores
FROM mart.fact_resumen_mercado_mes f
JOIN mart.dim_periodo d
  ON d.periodo_id = f.periodo_id
JOIN mart.dim_territorio t
  ON t.territorio_id = f.territorio_id;

CREATE VIEW mart.vw_dashboard_velocidades AS
SELECT
    f.periodo_id,
    d.periodo,
    d.anio,
    d.mes,
    d.nombre_mes,
    d.trimestre,
    d.anio_mes,
    t.territorio_id,
    t.nivel_geografico,
    t.codigo_geografico,
    t.nombre_geografico,
    t.codigo_provincia,
    t.pro_nombre,
    t.codigo_canton,
    t.ciu_nombre,
    t.codigo_parroquia,
    t.par_nombre,
    f.tipo_velocidad,
    f.orden_rango,
    f.rango_velocidad,
    f.total_lineas,
    f.total_lineas_tipo,
    f.participacion_rango_porcentaje,
    f.lineas_reportadas,
    f.lineas_imputadas,
    f.porcentaje_imputado,
    f.diferencia_mensual,
    f.variacion_mensual_porcentaje,
    f.diferencia_anual,
    f.variacion_anual_porcentaje
FROM mart.fact_velocidad_mercado_mes f
JOIN mart.dim_periodo d
  ON d.periodo_id = f.periodo_id
JOIN mart.dim_territorio t
  ON t.territorio_id = f.territorio_id;

CREATE VIEW mart.vw_dashboard_participacion AS
SELECT
    f.periodo_id,
    d.periodo,
    d.anio,
    d.mes,
    d.nombre_mes,
    d.trimestre,
    d.anio_mes,
    t.territorio_id,
    t.nivel_geografico,
    t.codigo_geografico,
    t.nombre_geografico,
    t.codigo_provincia,
    t.pro_nombre,
    t.codigo_canton,
    t.ciu_nombre,
    t.codigo_parroquia,
    t.par_nombre,
    f.prestador_id,
    p.ruc_limpio,
    p.isp_ruc,
    p.peva_codigo_principal,
    p.cantidad_peva,
    p.codigos_peva,
    p.isp_nombre,
    p.nombrecomercial,
    p.opera_actual,
    p.es_cancelado_actual,
    f.total_lineas_prestador,
    f.total_lineas_mercado,
    f.participacion_decimal,
    f.participacion_porcentaje,
    f.aporte_ihh,
    f.ranking_prestador,
    f.es_lider,
    f.estado_lineas,
    f.lineas_reportadas,
    f.lineas_imputadas,
    f.porcentaje_imputado_prestador,
    f.tiene_imputacion
FROM mart.fact_participacion_mercado f
JOIN mart.dim_periodo d
  ON d.periodo_id = f.periodo_id
JOIN mart.dim_territorio t
  ON t.territorio_id = f.territorio_id
JOIN mart.dim_prestador p
  ON p.prestador_id = f.prestador_id;

CREATE VIEW mart.vw_dashboard_ihh AS
SELECT
    f.periodo_id,
    d.periodo,
    d.anio,
    d.mes,
    d.nombre_mes,
    d.trimestre,
    d.anio_mes,
    t.territorio_id,
    t.nivel_geografico,
    t.codigo_geografico,
    t.nombre_geografico,
    t.codigo_provincia,
    t.pro_nombre,
    t.codigo_canton,
    t.ciu_nombre,
    t.codigo_parroquia,
    t.par_nombre,
    f.total_lineas_mercado,
    f.numero_prestadores,
    f.numero_prestadores_con_lineas,
    f.numero_prestadores_cero,
    f.numero_prestadores_sin_dato,
    f.ihh,
    f.prestador_lider_id,
    p.isp_nombre AS prestador_lider_nombre,
    p.nombrecomercial
        AS prestador_lider_nombrecomercial,
    f.participacion_lider,
    f.cr2,
    f.cr4,
    f.lineas_reportadas_mercado,
    f.lineas_imputadas_mercado,
    f.porcentaje_imputado_mercado,
    f.numero_prestadores_imputados
FROM mart.fact_ihh_geografico f
JOIN mart.dim_periodo d
  ON d.periodo_id = f.periodo_id
JOIN mart.dim_territorio t
  ON t.territorio_id = f.territorio_id
LEFT JOIN mart.dim_prestador p
  ON p.prestador_id = f.prestador_lider_id;

CREATE VIEW mart.vw_dashboard_filtros_geograficos AS
SELECT
    territorio_id,
    nivel_geografico,
    orden_nivel,
    codigo_geografico,
    nombre_geografico,
    codigo_provincia,
    pro_nombre,
    codigo_canton,
    ciu_nombre,
    codigo_parroquia,
    par_nombre
FROM mart.dim_territorio;

CREATE VIEW mart.vw_auditoria_resolucion_peva AS
SELECT
    estado_resolucion_peva,
    COUNT(*) AS filas,
    COUNT(DISTINCT prestador_id)
        AS prestadores,
    MIN(periodo) AS primer_periodo,
    MAX(periodo) AS ultimo_periodo
FROM mart.fact_lineas_geografia_mes
GROUP BY estado_resolucion_peva;

-- ============================================================
-- 16. ESTADISTICAS
-- ============================================================

ANALYZE mart.stg_fuente_normalizada;
ANALYZE mart.dim_periodo;
ANALYZE mart.dim_prestador;
ANALYZE mart.dim_geografia;
ANALYZE mart.dim_territorio;
ANALYZE mart.bridge_geografia_territorio;
ANALYZE mart.stg_lineas_por_peva_geografia_mes;
ANALYZE mart.audit_conflictos_peva;
ANALYZE mart.fact_lineas_geografia_mes;
ANALYZE mart.fact_lineas_velocidad_mes;
ANALYZE mart.fact_resumen_mercado_mes;
ANALYZE mart.fact_velocidad_mercado_mes;
ANALYZE mart.fact_participacion_mercado;
ANALYZE mart.fact_ihh_geografico;

-- ============================================================
-- 18. RE-OTORGAR ACCESO A dashboard_lector -- sobrevive a la reconstrucción
-- ============================================================
-- CRÍTICO: el DROP SCHEMA mart CASCADE del inicio de este archivo borra
-- TODOS los privilegios existentes sobre el esquema -- incluido el
-- GRANT USAGE y el ALTER DEFAULT PRIVILEGES que sql/03_ddl_auth.sql le
-- otorgó a dashboard_lector. Sin este bloque, CADA refresco de mart
-- (manual o vía dags/sietel_mart_pipeline.py) deja al dashboard sin
-- acceso de lectura hasta que alguien recuerde volver a correr
-- 03_ddl_auth.sql a mano -- confirmado como falla real en producción
-- (29-jul-2026, tras el primer refresco automatizado vía Airflow).
--
-- Condicionado a que el rol ya exista: en una instalación nueva donde
-- 02_ddl_mart.sql corre ANTES de que exista dashboard_lector, este bloque
-- simplemente no hace nada -- no rompe la construcción de mart por eso.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dashboard_lector') THEN
        GRANT USAGE ON SCHEMA mart TO dashboard_lector;
        GRANT SELECT ON ALL TABLES IN SCHEMA mart TO dashboard_lector;
        ALTER DEFAULT PRIVILEGES FOR ROLE mart_user IN SCHEMA mart
            GRANT SELECT ON TABLES TO dashboard_lector;
    END IF;
END $$;

COMMIT;

-- ============================================================
-- 17. VALIDACIONES POSTERIORES
-- ============================================================

-- 17.1. Prestadores excluidos por "prueba".
SELECT *
FROM mart.audit_prestadores_prueba
ORDER BY isp_nombre, peva_codigo;

-- 17.2. Conflictos PEVA con valores diferentes.
-- El script los suma y los conserva aquí para auditoría.
SELECT *
FROM mart.audit_conflictos_peva
ORDER BY periodo, prestador_id, geografia_id;

-- 17.3. Las participaciones positivas deben sumar 100 por mercado.
SELECT
    periodo_id,
    territorio_id,
    SUM(participacion_porcentaje)
        AS participacion_total
FROM mart.fact_participacion_mercado
WHERE total_lineas_prestador > 0
GROUP BY
    periodo_id,
    territorio_id
HAVING ABS(
    SUM(participacion_porcentaje) - 100
) > 0.001;

-- Resultado esperado: cero filas.

-- 17.4. El IHH debe encontrarse entre 0 y 10.000.
SELECT *
FROM mart.fact_ihh_geografico
WHERE ihh < 0
   OR ihh > 10000;

-- Resultado esperado: cero filas.

-- 17.5. El conteo total debe ser igual a sus tres categorías.
SELECT *
FROM mart.fact_resumen_mercado_mes
WHERE numero_prestadores
   <> numero_prestadores_con_lineas
      + numero_prestadores_cero
      + numero_prestadores_sin_dato;

-- Resultado esperado: cero filas.

-- 17.6. Comparación nacional rápida.
SELECT
    periodo,
    total_lineas,
    numero_prestadores,
    numero_prestadores_con_lineas,
    numero_prestadores_cero,
    numero_prestadores_sin_dato
FROM mart.vw_dashboard_evolucion
WHERE territorio_id = 'NACIONAL|ECUADOR'
ORDER BY periodo;

-- 17.7. Resumen de la resolución de múltiples PEVA.
SELECT *
FROM mart.vw_auditoria_resolucion_peva
ORDER BY estado_resolucion_peva;

-- 17.8. NUEVA (revisión profesional, 28-jul-2026).
-- La suma de los rangos de velocidad de descarga debe ser igual a
-- total_lineas, y lo mismo para subida -- esta es la invariante que el
-- bug original de resolución de múltiples PEVA podía romper (ver el
-- CAMBIO documentado al inicio del archivo). Con la corrección de la
-- sección 9 (decisión MAX/SUM unificada por grupo, no por columna),
-- esta consulta debe devolver siempre cero filas.
SELECT
    periodo_id,
    prestador_id,
    geografia_id,
    estado_resolucion_peva,
    total_lineas,
    (
        lineas_dl_sin_datos + lineas_dl_menos_1mbps + lineas_dl_1_10mbps
        + lineas_dl_10_30mbps + lineas_dl_30_100mbps
        + lineas_dl_100mbps_1gbps + lineas_dl_1gbps_o_mas
    ) AS suma_rangos_descarga,
    (
        lineas_ul_sin_datos + lineas_ul_menos_1mbps + lineas_ul_1_10mbps
        + lineas_ul_10_30mbps + lineas_ul_30_100mbps
        + lineas_ul_100mbps_1gbps + lineas_ul_1gbps_o_mas
    ) AS suma_rangos_subida
FROM mart.fact_lineas_geografia_mes
WHERE total_lineas IS NOT NULL
  AND (
        total_lineas <> (
            lineas_dl_sin_datos + lineas_dl_menos_1mbps + lineas_dl_1_10mbps
            + lineas_dl_10_30mbps + lineas_dl_30_100mbps
            + lineas_dl_100mbps_1gbps + lineas_dl_1gbps_o_mas
        )
     OR total_lineas <> (
            lineas_ul_sin_datos + lineas_ul_menos_1mbps + lineas_ul_1_10mbps
            + lineas_ul_10_30mbps + lineas_ul_30_100mbps
            + lineas_ul_100mbps_1gbps + lineas_ul_1gbps_o_mas
        )
  );

-- Resultado esperado: cero filas.