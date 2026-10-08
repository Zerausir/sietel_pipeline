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
-- SIN IMPUTACIÓN (29-sep-2026, decisión metodológica): capa2 ya no
-- rellena huecos con el último valor conocido (LOCF) y este archivo ya no
-- tiene ninguna columna reportado/imputado. Toda cifra de líneas del mart
-- es exactamente lo reportado. Quién debía reportar un mes y no lo hizo
-- sale de mart.panel_reporte_prestador_mes (sección 9b), que no contiene
-- valores de líneas. La invariante bloqueante "sin columnas de
-- imputación" (17.0) impide reintroducirla por accidente.
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
        periodo DESC
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
        (isp_nombre IS NOT NULL) DESC
),
rangos AS (
    SELECT
        prestador_id,
        MIN(periodo)::date AS primer_periodo,
        MAX(periodo)::date AS ultimo_periodo,
        -- Sin imputación, todo período de capa2 es un período reportado:
        -- primer/ultimo_periodo_reportado coinciden con primer/ultimo_periodo.
        -- Se conservan ambos nombres porque los consumen vistas y dashboard.
        MIN(periodo)::date AS primer_periodo_reportado,
        MAX(periodo)::date AS ultimo_periodo_reportado,
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
-- 9b. PANEL DE OBLIGACION DE REPORTE (SIN VALORES)
-- ============================================================

-- Reemplaza la única función legítima que cumplían las filas imputadas:
-- saber QUIÉN DEBÍA reportar en un territorio y mes, y no lo hizo. Una fila
-- por (periodo, territorio, prestador) desde el primer hasta el último
-- reporte real del prestador en ese territorio; `reporto` indica si ese mes
-- exacto hubo reporte real. NO contiene ningún valor de líneas -- nada
-- se hereda ni se estima.
--
-- Es el denominador de la cobertura (fact_resumen_mercado_mes,
-- fact_participacion_mercado, fact_ihh_geografico) y la base de las filas
-- SIN_REPORTE_ESTE_MES de participación.
--
-- La ventana es por prestador y TERRITORIO, no por combinación
-- (tipoEnlace/tipoCliente/...): el LOCF anterior solo marcaba un hueco si la
-- MISMA combinación reaparecía después, así que un prestador que cambiaba
-- de combinación entre dos reportes quedaba fuera del denominador en el
-- mes que no reportó. Aquí cuenta como esperado.
--
-- Límite conocido (igual que antes): tras el ÚLTIMO reporte real de un
-- prestador no hay filas -- este panel no puede distinguir "salió del
-- mercado" de "dejó de reportar". Ese caso lo cubren
-- vw_prestadores_reporte_detenido y la alerta de prestador dominante
-- ausente (sección 14); quien nunca reportó, vw_prestadores_sin_reportar.

CREATE MATERIALIZED VIEW mart.panel_reporte_prestador_mes AS
WITH reporte AS (
    SELECT DISTINCT
        f.periodo_id,
        f.periodo,
        b.territorio_id,
        f.prestador_id
    FROM mart.fact_lineas_geografia_mes f
    JOIN mart.bridge_geografia_territorio b
      ON b.geografia_id = f.geografia_id
),
ventana AS (
    SELECT
        territorio_id,
        prestador_id,
        MIN(periodo) AS primer_periodo,
        MAX(periodo) AS ultimo_periodo
    FROM reporte
    GROUP BY
        territorio_id,
        prestador_id
)
SELECT
    d.periodo_id,
    d.periodo,
    v.territorio_id,
    v.prestador_id,
    (r.prestador_id IS NOT NULL) AS reporto
FROM ventana v
JOIN mart.dim_periodo d
  ON d.periodo BETWEEN v.primer_periodo AND v.ultimo_periodo
LEFT JOIN reporte r
  ON  r.periodo_id = d.periodo_id
  AND r.territorio_id = v.territorio_id
  AND r.prestador_id = v.prestador_id;

CREATE UNIQUE INDEX uq_panel_reporte_prestador_mes
    ON mart.panel_reporte_prestador_mes (
        periodo_id,
        territorio_id,
        prestador_id
    );

CREATE INDEX idx_panel_reporte_territorio
    ON mart.panel_reporte_prestador_mes (
        territorio_id,
        periodo_id
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

-- Solo cifras reportadas. La cobertura (cuántos de los prestadores
-- esperados en ese territorio y mes reportaron de verdad) viene del panel
-- de la sección 9b y acompaña siempre al total: un total bajo con
-- cobertura baja es falta de reporte, no caída del mercado. La base es el
-- panel para que un mes en que NADIE reportó siga apareciendo (con
-- cobertura 0), en vez de desaparecer de la serie.
CREATE MATERIALIZED VIEW mart.fact_resumen_mercado_mes AS
WITH prestador_territorio AS (
    SELECT
        f.periodo_id,
        b.territorio_id,
        f.prestador_id,
        SUM(f.total_lineas) AS total_lineas_prestador,
        SUM(f.total_usuarios) AS total_usuarios_prestador
    FROM mart.fact_lineas_geografia_mes f
    JOIN mart.bridge_geografia_territorio b
      ON b.geografia_id = f.geografia_id
    GROUP BY
        f.periodo_id,
        b.territorio_id,
        f.prestador_id
),
reportado AS (
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
        ) AS numero_prestadores_sin_dato
    FROM prestador_territorio
    GROUP BY
        periodo_id,
        territorio_id
),
esperado AS (
    SELECT
        periodo_id,
        territorio_id,
        COUNT(*) AS numero_prestadores_esperados
    FROM mart.panel_reporte_prestador_mes
    GROUP BY
        periodo_id,
        territorio_id
),
mercado AS (
    SELECT
        e.periodo_id,
        e.territorio_id,
        r.total_lineas,
        r.total_usuarios,
        COALESCE(r.numero_prestadores, 0) AS numero_prestadores,
        COALESCE(r.numero_prestadores_con_lineas, 0) AS numero_prestadores_con_lineas,
        COALESCE(r.numero_prestadores_cero, 0) AS numero_prestadores_cero,
        COALESCE(r.numero_prestadores_sin_dato, 0) AS numero_prestadores_sin_dato,
        e.numero_prestadores_esperados
    FROM esperado e
    LEFT JOIN reportado r
      ON r.periodo_id = e.periodo_id
     AND r.territorio_id = e.territorio_id
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
    a.numero_prestadores_esperados,
    ROUND(
        100.0
        * a.numero_prestadores
        / NULLIF(a.numero_prestadores_esperados, 0),
        4
    ) AS porcentaje_cobertura_prestadores,
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
            AS total_lineas
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

-- Práctica de autoridades de competencia (DOJ/FTC, Ofcom, ARCEP): la
-- participación y el IHH se calculan con lo que cada prestador reportó ese
-- mes exacto. Un prestador esperado (panel 9b) que no reportó queda FUERA
-- del índice, con estado SIN_REPORTE_ESTE_MES y sin ningún valor -- no se
-- le asigna 0% ni su último valor conocido.
--
-- El denominador es la suma de lo reportado por quienes reportaron ese
-- mes, consistente con el numerador.
CREATE MATERIALIZED VIEW mart.fact_participacion_mercado AS
WITH lineas_prestador AS (
    SELECT
        f.periodo_id,
        b.territorio_id,
        f.prestador_id,
        SUM(f.total_lineas)
            AS total_lineas_prestador
    FROM mart.fact_lineas_geografia_mes f
    JOIN mart.bridge_geografia_territorio b
      ON b.geografia_id = f.geografia_id
    GROUP BY
        f.periodo_id,
        b.territorio_id,
        f.prestador_id
),
prestador_territorio AS (
    SELECT
        p.periodo_id,
        p.territorio_id,
        p.prestador_id,
        p.reporto AS tiene_reportado,
        l.total_lineas_prestador
    FROM mart.panel_reporte_prestador_mes p
    LEFT JOIN lineas_prestador l
      ON l.periodo_id = p.periodo_id
     AND l.territorio_id = p.territorio_id
     AND l.prestador_id = p.prestador_id
),
mercado_reportado AS (
    SELECT
        periodo_id,
        territorio_id,
        SUM(total_lineas_prestador) FILTER (WHERE tiene_reportado)
            AS total_lineas_mercado_reportado,
        COUNT(*) FILTER (WHERE tiene_reportado)
            AS numero_prestadores_reportaron_periodo,
        COUNT(*)
            AS numero_prestadores_esperados_periodo
    FROM prestador_territorio
    GROUP BY periodo_id, territorio_id
),
con_mercado AS (
    SELECT
        p.*,
        m.total_lineas_mercado_reportado,
        m.numero_prestadores_reportaron_periodo,
        m.numero_prestadores_esperados_periodo
    FROM prestador_territorio p
    JOIN mercado_reportado m
      ON m.periodo_id = p.periodo_id
     AND m.territorio_id = p.territorio_id
),
ranking AS (
    SELECT
        c.*,
        CASE
            WHEN c.tiene_reportado
             AND c.total_lineas_prestador > 0
             AND c.total_lineas_mercado_reportado > 0
            THEN ROW_NUMBER() OVER (
                PARTITION BY
                    c.periodo_id,
                    c.territorio_id
                ORDER BY
                    c.total_lineas_prestador DESC NULLS LAST,
                    c.prestador_id
            )
        END AS ranking_prestador
    FROM con_mercado c
)
SELECT
    periodo_id,
    territorio_id,
    prestador_id,
    total_lineas_prestador,
    total_lineas_mercado_reportado AS total_lineas_mercado,
    CASE
        WHEN tiene_reportado
         AND total_lineas_prestador > 0
         AND total_lineas_mercado_reportado > 0
        THEN ROUND(total_lineas_prestador / total_lineas_mercado_reportado, 10)
    END AS participacion_decimal,
    CASE
        WHEN tiene_reportado
         AND total_lineas_prestador > 0
         AND total_lineas_mercado_reportado > 0
        THEN ROUND(100.0 * total_lineas_prestador / total_lineas_mercado_reportado, 8)
    END AS participacion_porcentaje,
    CASE
        WHEN tiene_reportado
         AND total_lineas_prestador > 0
         AND total_lineas_mercado_reportado > 0
        THEN ROUND(POWER(100.0 * total_lineas_prestador / total_lineas_mercado_reportado, 2), 8)
    END AS aporte_ihh,
    ranking_prestador,
    ranking_prestador = 1 AS es_lider,
    CASE
        WHEN NOT tiene_reportado THEN 'SIN_REPORTE_ESTE_MES'
        WHEN total_lineas_prestador > 0 THEN 'POSITIVO'
        WHEN total_lineas_prestador = 0 THEN 'CERO'
        ELSE 'SIN_DATO'
    END AS estado_lineas,
    tiene_reportado,
    numero_prestadores_reportaron_periodo,
    numero_prestadores_esperados_periodo,
    ROUND(
        100.0 * numero_prestadores_reportaron_periodo
        / NULLIF(numero_prestadores_esperados_periodo, 0),
        4
    ) AS porcentaje_cobertura_prestadores
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
-- ALERTA DE PRESTADOR DOMINANTE AUSENTE (agregado 05-ago-2026, EDA de
-- líneas dedicadas -- sección 9.10). NO modifica el IHH/CR2/CR4 en
-- absoluto -- es exclusivamente informativa, mismo principio que
-- porcentaje_cobertura_prestadores: el índice se calcula igual que siempre
-- (solo con lo reportado por quien reportó ese mes), y esta bandera
-- se agrega al lado para que nadie lo lea sin ese contexto.
--
-- Por qué hace falta además de porcentaje_cobertura_prestadores: esa
-- columna ya existe pero trata a todos los prestadores por igual -- no
-- distingue entre "faltaron 10 prestadores chicos" y "faltó el único
-- prestador que domina ese territorio". Verificado con datos reales
-- (CNT EP, 2012-2015): su ausencia hacía caer el IHH nacional de ~5.741 a
-- ~1.840 en promedio (9.10/9.11) mientras la cobertura de prestadores
-- seguía siendo ALTA (98.28%) -- es decir, el % de cobertura por sí solo
-- no habría alertado de nada en esos meses.
--
-- "Dominante" se define de forma objetiva y verificable con los propios
-- datos, no con un umbral inventado para este caso: cualquier prestador
-- que en ALGÚN período de su historia haya alcanzado >=30% de
-- participación real en ESE territorio específico (umbral estándar de
-- posición dominante en derecho de competencia). Es específico por
-- territorio, no solo nacional -- un prestador puede ser dominante en una
-- provincia pequeña sin serlo a nivel país (ver 9.13, dependencia de
-- provincias periféricas de CNT).
WITH
-- ACOTADO SOLO A NACIONAL (segunda corrección de alcance, 05-ago-2026):
-- se intentó primero acotar a NACIONAL + PROVINCIA, pero verificado en
-- producción que el nivel PROVINCIA tiene el MISMO problema que
-- cantón/parroquia, solo a otra escala -- prestadores chicos (ej.
-- TRANSTELCO S.A., con 388 meses marcados, más que los 292 de CNT)
-- superan 30% en provincias con pocos competidores y luego salen del
-- mercado para siempre, quedando marcados "ausente" perpetuamente. No es
-- rotación normal a nivel cantón/parroquia únicamente -- ocurre igual a
-- nivel provincia. El único caso que los hallazgos originales (9.10/9.11)
-- documentaron y cuantificaron con evidencia real es CNT a nivel NACIONAL
-- -- por eso la Parte A se acota estrictamente ahí. Detectar dominancia
-- provincial genuina (distinta de rotación de mercado) requeriría un
-- diseño más cuidadoso (ej. límite de tiempo a la alerta tras la salida,
-- o un piso de tamaño absoluto de mercado, no solo porcentaje) -- fuera
-- de alcance de este cambio puntual.
umbral_dominancia AS (
    SELECT DISTINCT territorio_id, prestador_id
    FROM mart.fact_participacion_mercado
    WHERE participacion_porcentaje >= 30
      AND territorio_id = 'NACIONAL|ECUADOR'
),
periodos_territorios AS (
    SELECT DISTINCT periodo_id, territorio_id
    FROM mart.fact_participacion_mercado
    WHERE territorio_id = 'NACIONAL|ECUADOR'
),
dominante_x_periodo AS (
    -- CORRECCIÓN (05-ago-2026, verificado en producción antes de comprometer
    -- el cambio): sin el filtro de dp.primer_periodo_reportado, un prestador
    -- que alcanzó >=30% de participación en cualquier momento de su
    -- historia (ej. CONECEL, MEGADATOS -- ambos entraron recién en
    -- 2020/2021) aparecía marcado como "ausente" en períodos ANTERIORES a
    -- su propia existencia en el sistema (ej. 2012-2013) -- falso positivo
    -- semántico: no estaban ausentes, todavía no operaban en este segmento.
    -- Mismo principio ya aplicado como año de gracia en
    -- vw_prestadores_sin_reportar -- no juzgar a un prestador por un
    -- período en que no tenía presencia/obligación todavía.
    SELECT
        pt.periodo_id,
        ud.territorio_id,
        ud.prestador_id,
        EXISTS (
            SELECT 1 FROM mart.fact_participacion_mercado fpm
            WHERE fpm.periodo_id = pt.periodo_id
              AND fpm.territorio_id = ud.territorio_id
              AND fpm.prestador_id = ud.prestador_id
              AND fpm.tiene_reportado
        ) AS reporto_este_periodo
    FROM umbral_dominancia ud
    JOIN periodos_territorios pt ON pt.territorio_id = ud.territorio_id
    JOIN mart.dim_prestador dp ON dp.prestador_id = ud.prestador_id
    WHERE dp.primer_periodo_reportado IS NOT NULL
      AND pt.periodo_id >= (
            EXTRACT(YEAR FROM dp.primer_periodo_reportado)::int * 100
            + EXTRACT(MONTH FROM dp.primer_periodo_reportado)::int
          )
),
alerta_dominante_ausente AS (
    SELECT
        dxp.periodo_id,
        dxp.territorio_id,
        BOOL_OR(NOT dxp.reporto_este_periodo) AS prestador_dominante_ausente,
        STRING_AGG(
            DISTINCT p.isp_nombre, ', ' ORDER BY p.isp_nombre
        ) FILTER (WHERE NOT dxp.reporto_este_periodo)
            AS prestadores_dominantes_ausentes_nombres
    FROM dominante_x_periodo dxp
    JOIN mart.dim_prestador p ON p.prestador_id = dxp.prestador_id
    GROUP BY dxp.periodo_id, dxp.territorio_id
),
agregado_base AS (
SELECT
    periodo_id,
    territorio_id,
    MAX(total_lineas_mercado)
        AS total_lineas_mercado,
    -- Conteos solo sobre quienes reportaron ese mes (los SIN_REPORTE del
    -- panel no tienen cifra); los esperados van en la cobertura de abajo.
    COUNT(*) FILTER (
        WHERE tiene_reportado
    ) AS numero_prestadores,
    COUNT(*) FILTER (
        WHERE tiene_reportado AND total_lineas_prestador > 0
    ) AS numero_prestadores_con_lineas,
    COUNT(*) FILTER (
        WHERE tiene_reportado AND total_lineas_prestador = 0
    ) AS numero_prestadores_cero,
    COUNT(*) FILTER (
        WHERE tiene_reportado AND total_lineas_prestador IS NULL
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
    -- COBERTURA (31-jul-2026): el IHH/CR2/CR4 de arriba se calculan SOLO
    -- sobre lo reportado ese mes exacto -- estas columnas dejan explícito
    -- CUÁNTOS de los prestadores esperados (panel 9b) quedan representados,
    -- para que el índice nunca se lea sin su contexto de completitud.
    MAX(numero_prestadores_reportaron_periodo) AS numero_prestadores_reportaron,
    MAX(numero_prestadores_esperados_periodo) AS numero_prestadores_esperados,
    ROUND(
        100.0
        * MAX(numero_prestadores_reportaron_periodo)
        / NULLIF(MAX(numero_prestadores_esperados_periodo), 0),
        4
    ) AS porcentaje_cobertura_prestadores
FROM mart.fact_participacion_mercado
GROUP BY
    periodo_id,
    territorio_id
)
SELECT
    b.*,
    COALESCE(a.prestador_dominante_ausente, FALSE) AS prestador_dominante_ausente,
    a.prestadores_dominantes_ausentes_nombres
FROM agregado_base b
LEFT JOIN alerta_dominante_ausente a
  ON a.periodo_id = b.periodo_id
 AND a.territorio_id = b.territorio_id;

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
    f.numero_prestadores_esperados,
    f.porcentaje_cobertura_prestadores,
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
    f.tiene_reportado,
    f.numero_prestadores_reportaron_periodo,
    f.numero_prestadores_esperados_periodo,
    f.porcentaje_cobertura_prestadores
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
    f.numero_prestadores_reportaron,
    f.numero_prestadores_esperados,
    f.porcentaje_cobertura_prestadores,
    f.prestador_dominante_ausente,
    f.prestadores_dominantes_ausentes_nombres
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

-- Puente de solo lectura hacia calidad.conflictos_ruc_peva (categorías A/B/C
-- de conflicto RUC/PEVA, ver mart/detectar_conflictos_peva.py) -- segundo
-- puente calidad->mart, mismo patrón que mart.vw_nodos_isp_mapa usa para
-- calidad.discrepancias_geografia_nodo (06-ago-2026). Sin CREATE OR REPLACE
-- aquí: el esquema mart se acaba de reconstruir desde cero en este archivo
-- (sección 1, DROP SCHEMA ... CASCADE), así que la vista nunca existe
-- todavía en este punto de la ejecución -- a diferencia de
-- sql/10_patch_vw_conflictos_ruc_peva.sql, que sí necesita CREATE OR REPLACE
-- porque se aplica contra un mart ya existente en producción.
--
-- estado_revision/revisado_por/notas_revision/fecha_revision reflejan el
-- workflow humano tal cual está en calidad -- esta vista NO permite
-- editarlos, la edición real ocurre fuera de OBTEL con el rol
-- calidad_revisor. Sin columnas de geografía ni territorio: un conflicto
-- RUC/PEVA no tiene ubicación física propia (no es un nodo).
--
-- El GRANT a dashboard_lector no va aquí -- ya lo cubre, sin cambios, la
-- sección 18 de este mismo archivo (GRANT SELECT ON ALL TABLES IN SCHEMA
-- mart TO dashboard_lector, que alcanza vistas también).
CREATE VIEW mart.vw_conflictos_ruc_peva AS
SELECT
    id,
    ruc_limpio,
    peva_a,
    peva_b,
    isp_nombre_a,
    isp_nombre_b,
    opera_a,
    opera_b,
    fecha_permiso_a,
    fecha_permiso_b,
    categoria,
    peva_legado_descartado,
    coexisten_en_periodo,
    accion_recomendada,
    estado_revision,
    revisado_por,
    notas_revision,
    fecha_revision,
    fecha_deteccion,
    fecha_ultima_deteccion
FROM calidad.conflictos_ruc_peva;

COMMENT ON VIEW mart.vw_conflictos_ruc_peva IS
'Puente de solo lectura hacia calidad.conflictos_ruc_peva (categorías A/B/C de conflicto RUC/PEVA, ver mart/detectar_conflictos_peva.py). estado_revision/revisado_por/notas_revision/fecha_revision reflejan el workflow humano tal cual está en calidad -- esta vista NO permite editarlos, la edición real ocurre fuera de OBTEL con el rol calidad_revisor. Sin columnas de geografía ni territorio: un conflicto RUC/PEVA no tiene ubicación física propia.';

-- Puente hacia calidad.conciliacion_siger_obtel (conciliación SIGER <->
-- SIETEL, 08-oct-2026). La tabla la crea sql/13_ddl_calidad_siger.sql
-- (siger_pipeline), que también crea esta vista; aquí solo se recrea tras el
-- DROP SCHEMA mart CASCADE, y SOLO si la tabla ya existe -- así mart no
-- depende de que siger_pipeline haya corrido alguna vez. Mismo SELECT que en
-- 13: si cambia uno, cambiar el otro.
DO $$
BEGIN
    IF to_regclass('calidad.conciliacion_siger_obtel') IS NOT NULL THEN
        EXECUTE 'CREATE VIEW mart.vw_conciliacion_siger_obtel AS SELECT * FROM calidad.conciliacion_siger_obtel';
        EXECUTE 'COMMENT ON VIEW mart.vw_conciliacion_siger_obtel IS ''Puente de solo lectura hacia calidad.conciliacion_siger_obtel (ver sql/13_ddl_calidad_siger.sql).''';
    END IF;
END $$;

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
ANALYZE mart.panel_reporte_prestador_mes;
ANALYZE mart.fact_lineas_velocidad_mes;
ANALYZE mart.fact_resumen_mercado_mes;
ANALYZE mart.fact_velocidad_mercado_mes;
ANALYZE mart.fact_participacion_mercado;
ANALYZE mart.fact_ihh_geografico;

-- ============================================================
-- VISTA ADICIONAL (fuera de secuencia, 30-jul-2026, a pedido del usuario):
-- vw_prestadores_sin_reportar -- prestadores con título habilitante
-- otorgado que JAMÁS han entregado ni un solo reporte real -- el caso de
-- incumplimiento más grave, invisible en toda la cadena capa2/mart porque
-- esa cadena se construye a partir de reportes reales (si nunca llegó
-- ninguno, el prestador simplemente no existe en capa2/fact_lineas_geografia_mes).
--
-- NOTA DE NUMERACIÓN: esta vista NO es la sección "17.9" -- ese número ya
-- pertenece a una validación de integridad distinta, más adelante en este
-- mismo archivo (después del COMMIT, dentro del bloque de validaciones
-- posteriores). Se etiqueta sin número de secuencia, deliberadamente, para
-- no chocar con esa numeración ya existente.
--
-- Fuente: analitico.v_ultimo_periodo_reportado_detalle, filtrando
-- tiene_reportes = FALSE (ya viene calculado en esa vista).
--
-- SIN GEOGRAFÍA: todas las columnas geográficas de la vista origen vienen
-- vacías para estos casos -- confirmado con datos reales (29-jul-2026):
-- SIETEL solo conoce la ubicación de un prestador a partir de su reporte
-- real (VALineasDedicadas especifica parroquia); si nunca reportó, no hay
-- forma de saber dónde. Por eso esta vista NO tiene columna de
-- geografía/territorio -- el consumo en el dashboard debe restringirse a
-- nivel Nacional únicamente.
--
-- fuera_de_gracia / clasificacion_incumplimiento (agregado 05-ago-2026,
-- promovido desde el EDA de líneas dedicadas -- secciones 9.4/9.6 del
-- notebook, ver EDA_sietel_lineas_dedicadas.ipynb):
--
-- El campo `opera` hereda la misma codificación heredada inconsistente ya
-- documentada en la sección 10 de las instrucciones del proyecto (mezcla
-- SI/NO/- con categorías descriptivas: Nuevo, Opera Normalmente,
-- Cancelación, Para Revocatoria, Opera Irregularmente, Otro Estado, "-").
-- Contar los 285 prestadores de esta vista como "285 casos de
-- incumplimiento" sin desagregar `opera` sobreestima el problema real --
-- verificado con datos de producción (05-ago-2026): de los 285, solo 104
-- son activo_sin_reportar (el número defendible de incumplimiento real),
-- 125 son no_operativo (cancelados/revocados -- nunca llegaron a operar,
-- universo administrativo distinto), y 56 quedan en zona_gris (estado
-- ambiguo, requiere revisión caso por caso, nunca se fuerzan a una
-- categoría por conveniencia estadística).
--
-- fuera_de_gracia usa la misma regla del año de gracia que
-- dashboard/services/queries.py:get_reporting_summary (un año calendario
-- desde fechapermiso, no desde el otorgamiento) -- NULL si fechapermiso es
-- NULL, para no asumir silenciosamente que un prestador sin fecha conocida
-- ya está en incumplimiento.
--
-- Esta vista NO filtra por fuera_de_gracia ni por clasificacion_incumplimiento
-- -- expone las 285 filas completas con las columnas calculadas, para que
-- cada consumidor decida el corte (ej. WHERE fuera_de_gracia AND
-- clasificacion_incumplimiento = 'activo_sin_reportar' para el número de
-- 104 verificado en el EDA).
--
-- "SIN SERVICIO" (28-sep-2026, decisión de Mercados): un PEVA sin ninguna
-- línea reportada que SÍ entregó el formulario de líneas dedicadas
-- declarando tieneServicio='No' NO está en incumplimiento -- declaró
-- formalmente que aún no tiene servicio (típico en el año que tiene para
-- iniciar operaciones desde su permiso). Antes el pipeline no leía el
-- formulario y lo mezclaba con quien nunca entregó nada. Caso que lo
-- reveló: DIGITEC S.A. La declaración tiene prioridad sobre `opera` al
-- clasificar (es evidencia del propio prestador); `opera` sigue visible.
-- Categorías resultantes:
--   sin_servicio          -- entregó formularios, TODOS "sin servicio".
--   servicio_sin_detalle  -- declaró "con servicio" en algún formulario
--                            pero SIETEL no tiene NINGUNA línea de detalle:
--                            inconsistencia de la fuente, para revisar.
--   activo_sin_reportar / no_operativo / zona_gris -- como antes, solo
--                            para quien NUNCA entregó el formulario.
-- Verificado en producción 28-sep-2026 (antes de la exclusión Grupo A de
-- abajo): de 419, 173 "sin servicio", 5 "servicio sin detalle", 241 nunca
-- entregaron nada.
CREATE VIEW mart.vw_prestadores_sin_reportar AS
SELECT
    v.peva_codigo,
    v.isp_nombre,
    v.isp_ruc,
    v.isp_tipopersona,
    v.opera,
    v.resolucion,
    v.fechapermiso,
    CASE
        WHEN v.fechapermiso IS NULL THEN NULL
        ELSE CURRENT_DATE >= (v.fechapermiso + INTERVAL '1 year')
    END AS fuera_de_gracia,
    CASE
        WHEN f.formularios_entregados > 0 AND f.formularios_con_servicio = 0 THEN 'sin_servicio'
        WHEN f.formularios_con_servicio > 0 THEN 'servicio_sin_detalle'
        WHEN v.opera IN ('Nuevo', 'Opera Normalmente', 'SI') THEN 'activo_sin_reportar'
        WHEN v.opera IN ('Cancelación', 'NO', 'Opera Irregularmente') THEN 'no_operativo'
        ELSE 'zona_gris'
    END AS clasificacion_incumplimiento,
    COALESCE(f.formularios_entregados, 0)   AS formularios_entregados,
    COALESCE(f.formularios_sin_servicio, 0) AS formularios_sin_servicio,
    COALESCE(f.formularios_con_servicio, 0) AS formularios_con_servicio,
    f.ultima_entrega                        AS ultima_entrega_formulario,
    f.ultimo_formulario_anio,
    f.ultimo_formulario_trimestre
FROM analitico.v_ultimo_periodo_reportado_detalle v
LEFT JOIN analitico.v_formularios_lineas_por_peva f ON f.peva_codigo = upper(v.peva_codigo)
WHERE v.tiene_reportes = FALSE
  -- CORRECCIÓN 28-sep-2026: excluye los PEVA legados del Grupo A
  -- (duplicado de migración de codificación, calidad.vw_pevas_excluidos) --
  -- ya se excluyen de capa2 por ser el MISMO prestador que otro PEVA que sí
  -- reporta, pero aquí se seguían contando como "nunca reportó". Verificado
  -- en producción 28-sep-2026: 5 PEVA legados dejan de contarse (419 -> 414
  -- filas); 3 tenían opera='SI' y fuera de gracia, así que el KPI
  -- activo_sin_reportar baja de 56 a 53. calidad.vw_pevas_excluidos ya
  -- existe en este punto: la tarea aplicar_ddl_calidad corre primero en el
  -- DAG.
  AND NOT EXISTS (
      SELECT 1 FROM calidad.vw_pevas_excluidos e WHERE e.peva_codigo = v.peva_codigo
  );

-- vw_prestadores_reporte_detenido (agregado 05-ago-2026, promovido desde el
-- EDA de líneas dedicadas -- secciones 9.11/9.12/9.13 del notebook, ver
-- EDA_sietel_lineas_dedicadas.ipynb).
--
-- Complemento de vw_prestadores_sin_reportar: mientras esa vista cubre a
-- quien JAMÁS reportó, esta cubre a quien SÍ reportó al menos una vez y
-- luego se detuvo -- caso descubierto en el EDA al investigar por qué CNT
-- EP (el operador estatal incumbente) no aparecía en el ranking de
-- participación de sep-2025 pese a haber tenido hasta 90% de participación
-- histórica. Resultó tener quince meses sin reportar (jul-2024 en
-- adelante), sin cierre a la fecha del análisis -- ver 9.11.
--
-- DELIBERADAMENTE SIN FILTRO DE UMBRAL NI DE FECHA DE CORTE EN LA VISTA
-- MISMA -- mismo principio que vw_prestadores_sin_reportar (que tampoco
-- filtra por fuera_de_gracia). El EDA usó un corte de >100.000 líneas
-- históricas para aislar la señal de ruido de prestadores pequeños, pero es
-- un umbral arbitrario de ESE análisis puntual -- no debe quedar fijo en la
-- vista para que otro consumo futuro (ej. alguien que sí quiera ver el
-- universo completo, incluyendo prestadores chicos) no tenga que
-- reconstruir la lógica desde cero. La vista expone TODOS los prestadores
-- con al menos un reporte real, con las columnas de magnitud y antigüedad
-- ya calculadas, para que cada consumidor decida su propio corte.
--
-- meses_desde_ultimo_reporte se calcula contra un PERÍODO DE REFERENCIA
-- CONFIABLE, no contra MAX(periodo) crudo -- corrección agregada 05-ago-2026
-- tras verificar en producción que usar MAX(periodo) sin ajuste produce
-- falsos positivos: cuando sietel_mart_pipeline avanza y carga meses nuevos,
-- los últimos ~3 meses todavía están incompletos por rezago normal de
-- reporte (mismo fenómeno ya documentado en 9.7). Confirmado con datos reales
-- (05-ago-2026): al cargar hasta dic-2025, 13 prestadores con último
-- reporte real en sep-2025 (exactamente 3 meses de rezago) aparecían como
-- "detenidos" cuando en realidad solo estaban esperando su próximo reporte
-- normal -- excluir ese margen reprodujo exactamente el universo de 18
-- verificado en el EDA original (31 - 13 = 18).
--
-- MARGEN_REZAGO_MESES = 3 es un valor fijo, no derivado dinámicamente de los
-- datos -- basado en la observación empírica de la sección 4/9.7 del EDA. Si
-- el patrón de rezago de carga cambia (ej. el pipeline empieza a cargar con
-- más o menos demora), este número debe reconsiderarse -- no es una
-- constante física, es una convención operativa de este pipeline.
CREATE VIEW mart.vw_prestadores_reporte_detenido AS
WITH periodo_confiable AS (
    SELECT (MAX(periodo) - INTERVAL '3 months')::date AS periodo
    FROM mart.fact_lineas_geografia_mes
)
SELECT
    p.prestador_id,
    p.isp_nombre,
    p.ruc_limpio,
    p.opera_actual,
    p.es_cancelado_actual,
    p.primer_periodo_reportado,
    p.ultimo_periodo_reportado,
    COALESCE(ultimo.lineas_reportadas, 0) AS lineas_ultimo_reporte,
    COALESCE(historico.total_lineas_historico, 0) AS total_lineas_historico,
    (
        EXTRACT(YEAR FROM pc.periodo)::int * 12 + EXTRACT(MONTH FROM pc.periodo)::int
    ) - (
        EXTRACT(YEAR FROM p.ultimo_periodo_reportado)::int * 12
        + EXTRACT(MONTH FROM p.ultimo_periodo_reportado)::int
    ) AS meses_desde_ultimo_reporte
FROM mart.dim_prestador p
CROSS JOIN periodo_confiable pc
LEFT JOIN LATERAL (
    SELECT SUM(f.total_lineas) AS lineas_reportadas
    FROM mart.fact_lineas_geografia_mes f
    WHERE f.prestador_id = p.prestador_id
      AND f.periodo = p.ultimo_periodo_reportado
) ultimo ON TRUE
LEFT JOIN LATERAL (
    SELECT SUM(f.total_lineas) AS total_lineas_historico
    FROM mart.fact_lineas_geografia_mes f
    WHERE f.prestador_id = p.prestador_id
) historico ON TRUE
WHERE p.primer_periodo_reportado IS NOT NULL;

-- ============================================================
-- 16b. NODOS ISP -- GEOGRAFIA Y MAPA (07-ago-2026)
-- ============================================================
-- Fuente: capa2.nodo_isp_geografia_resuelta (Parte A+B del geoprocesamiento
-- de nodos ISP -- mart/limpiar_coordenadas_nodo_isp.py +
-- mart/detectar_discrepancias_geografia_nodo.py). Geografía derivada de la
-- coordenada real vía shapefile CONALI, tratada como AUTORITATIVA frente a
-- par_codigo/dbo.Parroquia reportado en SIETEL -- confirmado con Iván
-- 07-ago-2026: dbo.Parroquia usa codificación INEC más vieja que CONALI
-- 2026 (ver docstring completo en detectar_discrepancias_geografia_nodo.py).
--
-- Universo completamente distinto de mart.dim_territorio/
-- bridge_geografia_territorio (geografía de LÍNEAS reportadas) -- un nodo
-- físico puede servir a varias parroquias de líneas, no hay relación 1:1.
-- Nunca se mezclan (confirmado con Iván 06-ago-2026).

CREATE TABLE mart.dim_territorio_nodo (
    territorio_id       text PRIMARY KEY,
    nivel_geografico    text NOT NULL CHECK (
        nivel_geografico IN ('NACIONAL', 'PROVINCIA', 'CANTON', 'PARROQUIA')
    ),
    orden_nivel         integer NOT NULL,
    codigo_geografico   text,
    nombre_geografico   text NOT NULL,
    codigo_provincia    text,
    nombre_provincia    text,
    codigo_canton       text,
    nombre_canton       text,
    codigo_parroquia    text,
    nombre_parroquia    text
);

INSERT INTO mart.dim_territorio_nodo VALUES (
    'NACIONAL|ECUADOR', 'NACIONAL', 0, 'ECU', 'Ecuador',
    NULL, NULL, NULL, NULL, NULL, NULL
);

INSERT INTO mart.dim_territorio_nodo
SELECT DISTINCT ON (codigo_provincia)
    'PROVINCIA|' || codigo_provincia,
    'PROVINCIA', 1,
    codigo_provincia, COALESCE(nombre_provincia, codigo_provincia),
    codigo_provincia, nombre_provincia,
    NULL, NULL, NULL, NULL
FROM capa2.nodo_isp_geografia_resuelta
WHERE codigo_provincia IS NOT NULL
ORDER BY codigo_provincia, nombre_provincia NULLS LAST;

INSERT INTO mart.dim_territorio_nodo
SELECT DISTINCT ON (codigo_provincia, codigo_canton)
    'CANTON|' || codigo_provincia || '|' || codigo_canton,
    'CANTON', 2,
    codigo_canton, COALESCE(nombre_canton, codigo_canton),
    codigo_provincia, nombre_provincia,
    codigo_canton, nombre_canton,
    NULL, NULL
FROM capa2.nodo_isp_geografia_resuelta
WHERE codigo_provincia IS NOT NULL AND codigo_canton IS NOT NULL
ORDER BY codigo_provincia, codigo_canton, nombre_canton NULLS LAST;

INSERT INTO mart.dim_territorio_nodo
SELECT DISTINCT ON (codigo_provincia, codigo_canton, codigo_parroquia)
    'PARROQUIA|' || codigo_provincia || '|' || codigo_canton || '|' || codigo_parroquia,
    'PARROQUIA', 3,
    codigo_parroquia, COALESCE(nombre_parroquia, codigo_parroquia),
    codigo_provincia, nombre_provincia,
    codigo_canton, nombre_canton,
    codigo_parroquia, nombre_parroquia
FROM capa2.nodo_isp_geografia_resuelta
WHERE codigo_provincia IS NOT NULL AND codigo_canton IS NOT NULL AND codigo_parroquia IS NOT NULL
ORDER BY codigo_provincia, codigo_canton, codigo_parroquia, nombre_parroquia NULLS LAST;

CREATE INDEX idx_dim_territorio_nodo_nivel ON mart.dim_territorio_nodo (nivel_geografico);

CREATE VIEW mart.vw_dashboard_filtros_geograficos_nodo AS
SELECT
    territorio_id, nivel_geografico, orden_nivel, codigo_geografico, nombre_geografico,
    codigo_provincia, nombre_provincia, codigo_canton, nombre_canton, codigo_parroquia, nombre_parroquia
FROM mart.dim_territorio_nodo;

-- Vista principal del mapa. LEFT JOIN hacia calidad.discrepancias_geografia_nodo
-- (no hacia mart) -- funciona porque esta vista corre con los privilegios del
-- DUEÑO (mart_user), que ya tiene acceso pleno a calidad por ser su dueño
-- también (ver README, tabla de roles) -- dashboard_lector NUNCA necesita
-- GRANT directo sobre calidad, solo SELECT sobre esta vista. Primer puente
-- calidad -> mart -> dashboard de este proyecto (antes no existía ninguno).
-- isp_nombre se resuelve vía analitico.v_ultimo_periodo_reportado_detalle
-- (mismo patrón que mart/detectar_discrepancias_geografia_nodo.py), NO vía
-- mart.bridge_prestador_peva/dim_prestador -- esa vista parte de TODO
-- dim_permiso_va_agregado (LEFT JOIN hacia los reportes), así que
-- isp_nombre queda poblado aunque el PEVA nunca haya reportado una sola
-- línea. bridge_prestador_peva/dim_prestador, en cambio, SOLO conoce PEVA
-- con reportes -- confirmado en producción 07-ago-2026: 515 de 7000 nodos
-- mostraban isp_nombre nulo (tooltip "null" en el mapa) por esta causa.
--
-- opera_actual SÍ sigue viniendo de dim_prestador (línea-reporte) a
-- propósito -- es un dato genuinamente derivado del último reporte, no un
-- hecho de identidad como isp_nombre. NULL ahí para quien nunca ha
-- reportado es correcto y honesto, no el mismo bug.
CREATE VIEW mart.vw_nodos_isp_mapa AS
WITH isp_por_peva AS (
    SELECT DISTINCT ON (v.peva_codigo)
        v.peva_codigo, v.isp_nombre
    FROM analitico.v_ultimo_periodo_reportado_detalle v
    WHERE v.peva_codigo IS NOT NULL
    ORDER BY v.peva_codigo, v.ultimo_anio DESC NULLS LAST, v.ultimo_periodo_numero DESC NULLS LAST
)
SELECT
    r.noisp_codigo,
    r.peva_codigo,
    i.isp_nombre,
    p.opera_actual,
    r.tiponodo,
    r.latitud_decimal,
    r.longitud_decimal,
    r.codigo_provincia,
    r.nombre_provincia,
    r.codigo_canton,
    r.nombre_canton,
    r.codigo_parroquia,
    r.nombre_parroquia,
    r.es_discrepancia,
    d.estado_revision,
    d.par_codigo_reportado,
    d.parroquia_reportada_nombre,
    d.canton_reportado_nombre,
    d.provincia_reportada_nombre,
    'PROVINCIA|' || r.codigo_provincia AS territorio_id_provincia,
    'CANTON|' || r.codigo_provincia || '|' || r.codigo_canton AS territorio_id_canton,
    'PARROQUIA|' || r.codigo_provincia || '|' || r.codigo_canton || '|' || r.codigo_parroquia AS territorio_id_parroquia
FROM capa2.nodo_isp_geografia_resuelta r
LEFT JOIN isp_por_peva i ON i.peva_codigo = r.peva_codigo
LEFT JOIN mart.bridge_prestador_peva bp ON bp.peva_codigo = r.peva_codigo
LEFT JOIN mart.dim_prestador p ON p.prestador_id = bp.prestador_id
LEFT JOIN calidad.discrepancias_geografia_nodo d ON d.noisp_codigo = r.noisp_codigo;

COMMENT ON VIEW mart.vw_nodos_isp_mapa IS
'Universo completo de nodos ISP con coordenada válida y match espacial (mart/detectar_discrepancias_geografia_nodo.py). Geografía CONALI, autoritativa. isp_nombre viene de analitico.v_ultimo_periodo_reportado_detalle (cubre PEVA sin reportes); opera_actual viene de mart.dim_prestador (línea-reporte, NULL legítimo si nunca reportó). es_discrepancia=true junto con par_codigo_reportado/etc NOT NULL indica que el par_codigo de SIETEL no coincide en cantón -- ver calidad.discrepancias_geografia_nodo para el workflow de revisión (solo lectura desde el dashboard, la revisión real ocurre fuera de OBTEL con el rol calidad_revisor).';

-- Geometría precomputada por nivel (parroquia/cantón/provincia), expuesta a
-- dashboard_lector (capa2 es privado de mart_user) -- necesaria para
-- dibujar el polígono semi-transparente del territorio seleccionado en el
-- mapa. Cantón y provincia YA vienen disueltas (gdf.dissolve() en
-- mart/cargar_parroquias.py, una sola vez al cargar el shapefile) -- el
-- dashboard NO hace ninguna unión de polígonos en tiempo de consulta,
-- confirmado en producción 07-ago-2026 que unir con shapely en cada
-- petición era demasiado lento a nivel cantón, y mucho más a nivel
-- provincia. Este proyecto no tiene PostGIS -- por eso la unión ocurre en
-- Python (geopandas), no en SQL.
CREATE VIEW mart.vw_geometria_territorio_nodo AS
SELECT nivel_geografico, codigo_territorio, nombre_territorio,
       geometria_geojson, lon_min, lat_min, lon_max, lat_max
FROM capa2.territorio_geometria_nodo;

COMMENT ON VIEW mart.vw_geometria_territorio_nodo IS
'Geometría GeoJSON precomputada por nivel geográfico (parroquia/cantón/provincia), para el polígono del mapa de nodos. Cantón y provincia ya vienen disueltas desde mart/cargar_parroquias.py (gdf.dissolve) -- el dashboard solo hace SELECT, nunca une polígonos en tiempo de consulta.';

-- ============================================================
-- 17b. VERSIÓN DEL MART (30-sep-2026)
-- ============================================================
-- Marca de la reconstrucción, dentro de la misma transacción: solo cambia
-- si el refresco completo hizo COMMIT. El dashboard la consulta para
-- vaciar su caché cuando hay un mart nuevo (dashboard/services/cache_mart.py),
-- en vez de servir resultados viejos hasta que expire (hasta 1 h).
CREATE TABLE mart.control_version AS
SELECT now() AS fecha_reconstruccion;

COMMENT ON TABLE mart.control_version IS
'Una fila: fecha de la última reconstrucción de mart (now() de la transacción de 02_ddl_mart.sql). El dashboard vacía su caché cuando cambia.';

-- ============================================================
-- 18. RE-OTORGAR ACCESO A dashboard_lector Y eda_lector -- sobrevive a la reconstrucción
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
-- eda_lector agregado aquí el 05-ago-2026 tras repetir EXACTAMENTE el
-- mismo fallo con el rol de EDA -- sql/05_roles_eda.sql le otorgó acceso
-- por fuera de este archivo, y el primer refresco de mart posterior lo
-- dejó sin USAGE ON SCHEMA, igual que le pasó a dashboard_lector antes.
-- Lección para cualquier rol de lectura futuro sobre mart: el GRANT tiene
-- que vivir AQUÍ, en este bloque condicional de 02_ddl_mart.sql -- no
-- alcanza con un script separado que se corre una sola vez.
--
-- Condicionado a que el rol ya exista: en una instalación nueva donde
-- 02_ddl_mart.sql corre ANTES de que exista dashboard_lector o eda_lector,
-- este bloque simplemente no hace nada para ese rol -- no rompe la
-- construcción de mart por eso.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dashboard_lector') THEN
        GRANT USAGE ON SCHEMA mart TO dashboard_lector;
        GRANT SELECT ON ALL TABLES IN SCHEMA mart TO dashboard_lector;
        ALTER DEFAULT PRIVILEGES FOR ROLE mart_user IN SCHEMA mart
            GRANT SELECT ON TABLES TO dashboard_lector;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eda_lector') THEN
        GRANT USAGE ON SCHEMA mart TO eda_lector;
        GRANT SELECT ON ALL TABLES IN SCHEMA mart TO eda_lector;
        ALTER DEFAULT PRIVILEGES FOR ROLE mart_user IN SCHEMA mart
            GRANT SELECT ON TABLES TO eda_lector;
    END IF;
    -- calidad_lector agregado 28-sep-2026: sql/07 y sql/08 le otorgaban
    -- SELECT sobre vistas de mart, pero ese GRANT se perdía en el siguiente
    -- DROP SCHEMA mart CASCADE -- mismo fallo ya documentado arriba para
    -- dashboard_lector y eda_lector (verificado: sin USAGE sobre mart).
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'calidad_lector') THEN
        GRANT USAGE ON SCHEMA mart TO calidad_lector;
        GRANT SELECT ON ALL TABLES IN SCHEMA mart TO calidad_lector;
        ALTER DEFAULT PRIVILEGES FOR ROLE mart_user IN SCHEMA mart
            GRANT SELECT ON TABLES TO calidad_lector;
    END IF;
END $$;

-- ============================================================
-- 17.0. INVARIANTES BLOQUEANTES (28-sep-2026) -- DENTRO de la transacción
-- ============================================================
-- Antes, las validaciones de la sección 17 eran SELECT después del COMMIT:
-- aplicar_capa3.py las ejecutaba pero nadie leía su resultado, así que un
-- mart inconsistente se publicaba igual. Aquí se verifican ANTES del
-- COMMIT: si alguna falla, RAISE EXCEPTION aborta la transacción completa
-- -- el DROP SCHEMA mart CASCADE del inicio también se revierte, así que el
-- dashboard sigue sirviendo el mart anterior (bueno) en vez de uno roto --
-- y la tarea aplicar_capa3 de sietel_mart_pipeline queda en rojo con el
-- detalle en el log.
--
-- Solo entran las validaciones con "resultado esperado: cero filas". Las
-- informativas (17.1, 17.2, 17.6, 17.7, 17.11) quedan abajo, como antes.
-- Todas pasaban en producción el 28-sep-2026, salvo la de capa2 (102
-- pares), que es justo el bug corregido ese día en construir_capa2.py y
-- que esta verificación habría detectado.
DO $$
DECLARE
    n       bigint;
    errores text[] := ARRAY[]::text[];
BEGIN
    -- capa2: una sola fila por (llave natural, periodo) -- si no, la
    -- consolidación de variantes de construir_capa2.py falló y se
    -- duplicarían métricas.
    SELECT COUNT(*) INTO n FROM (
        SELECT 1 FROM capa2.lineas_dedicadas_consolidado
        GROUP BY peva_codigo, par_codigo, tipoenlace, tipocliente,
                 nivelcomparticion, portador, periodo
        HAVING COUNT(*) > 1) x;
    IF n > 0 THEN errores := errores || format('capa2: %s (llave, periodo) repetidos', n); END IF;

    -- 17.3
    SELECT COUNT(*) INTO n FROM (
        SELECT 1 FROM mart.fact_participacion_mercado
        WHERE total_lineas_prestador > 0
        GROUP BY periodo_id, territorio_id
        HAVING ABS(SUM(participacion_porcentaje) - 100) > 0.001) x;
    IF n > 0 THEN errores := errores || format('17.3: %s mercados cuya participación no suma 100', n); END IF;

    -- 17.4
    SELECT COUNT(*) INTO n FROM mart.fact_ihh_geografico WHERE ihh < 0 OR ihh > 10000;
    IF n > 0 THEN errores := errores || format('17.4: %s IHH fuera de [0, 10000]', n); END IF;

    -- 17.5
    SELECT COUNT(*) INTO n FROM mart.fact_resumen_mercado_mes
    WHERE numero_prestadores <> numero_prestadores_con_lineas + numero_prestadores_cero + numero_prestadores_sin_dato;
    IF n > 0 THEN errores := errores || format('17.5: %s filas con conteo de prestadores inconsistente', n); END IF;

    -- 17.8
    SELECT COUNT(*) INTO n FROM mart.fact_lineas_geografia_mes
    WHERE total_lineas IS NOT NULL
      AND (total_lineas <> lineas_dl_sin_datos + lineas_dl_menos_1mbps + lineas_dl_1_10mbps
                          + lineas_dl_10_30mbps + lineas_dl_30_100mbps
                          + lineas_dl_100mbps_1gbps + lineas_dl_1gbps_o_mas
        OR total_lineas <> lineas_ul_sin_datos + lineas_ul_menos_1mbps + lineas_ul_1_10mbps
                          + lineas_ul_10_30mbps + lineas_ul_30_100mbps
                          + lineas_ul_100mbps_1gbps + lineas_ul_1gbps_o_mas);
    IF n > 0 THEN errores := errores || format('17.8: %s filas donde los rangos de velocidad no suman total_lineas', n); END IF;

    -- 17.9 (29-sep-2026): SIN IMPUTACIÓN. Ninguna columna de capa2 ni de
    -- mart puede volver a llevar datos o marcas de imputación -- si alguien
    -- reintroduce el relleno (LOCF u otro), el refresco se aborta aquí.
    -- pg_attribute y no information_schema.columns: este último NO lista
    -- las vistas materializadas, que son la mayoría de los hechos de mart.
    SELECT COUNT(*) INTO n
    FROM pg_attribute a
    JOIN pg_class t ON t.oid = a.attrelid
    JOIN pg_namespace ns ON ns.oid = t.relnamespace
    WHERE ns.nspname IN ('capa2', 'mart')
      AND t.relkind IN ('r', 'p', 'v', 'm')
      AND a.attnum > 0 AND NOT a.attisdropped
      AND t.relname NOT LIKE '%\_prev'
      AND (a.attname ILIKE '%imput%' OR a.attname IN ('es_reportado', 'grupo_carry'));
    IF n > 0 THEN errores := errores || format('17.9: %s columnas de imputación en capa2/mart', n); END IF;

    -- 17.10 (29-sep-2026): el panel de obligación (9b) es coherente con los
    -- hechos -- quien reportó según el panel es exactamente quien tiene
    -- filas reales, y nadie reporta más que los esperados.
    SELECT COUNT(*) INTO n FROM mart.fact_resumen_mercado_mes
    WHERE numero_prestadores > numero_prestadores_esperados
       OR numero_prestadores <> (
            SELECT COUNT(*) FROM mart.panel_reporte_prestador_mes p
            WHERE p.periodo_id = fact_resumen_mercado_mes.periodo_id
              AND p.territorio_id = fact_resumen_mercado_mes.territorio_id
              AND p.reporto);
    IF n > 0 THEN errores := errores || format('17.10: %s filas con panel de reporte incoherente', n); END IF;

    -- 17.12 (a)
    SELECT COUNT(*) INTO n FROM mart.fact_participacion_mercado
    WHERE (NOT tiene_reportado) AND (participacion_porcentaje IS NOT NULL OR aporte_ihh IS NOT NULL);
    IF n > 0 THEN errores := errores || format('17.12a: %s prestadores sin reporte real con participación/aporte IHH', n); END IF;

    -- 17.12 (b)
    SELECT COUNT(*) INTO n FROM mart.fact_ihh_geografico
    WHERE porcentaje_cobertura_prestadores < 0 OR porcentaje_cobertura_prestadores > 100
       OR cr2 > cr4 + 0.001 OR cr4 > 100.001;
    IF n > 0 THEN errores := errores || format('17.12b: %s filas con cobertura/CR2/CR4 fuera de rango', n); END IF;

    IF cardinality(errores) > 0 THEN
        RAISE EXCEPTION 'Invariantes de mart incumplidas -- se revierte el refresco, el mart anterior queda intacto: %',
            array_to_string(errores, '; ');
    END IF;
    RAISE NOTICE 'Invariantes de mart: todas OK.';
END $$;

COMMIT;

-- ============================================================
-- 17. VALIDACIONES POSTERIORES
-- ============================================================
-- NOTA (28-sep-2026): las que dicen "resultado esperado: cero filas" ya se
-- verifican de forma BLOQUEANTE en 17.0, antes del COMMIT. Se conservan
-- aquí como SELECT para diagnóstico manual (ver QUÉ filas fallan cuando
-- 17.0 aborta el refresco).

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

-- 17.9. SIN IMPUTACIÓN (29-sep-2026) -- ninguna columna de imputación en
-- capa2/mart (bloqueante en 17.0).
SELECT ns.nspname AS esquema, t.relname AS objeto, a.attname AS columna
FROM pg_attribute a
JOIN pg_class t ON t.oid = a.attrelid
JOIN pg_namespace ns ON ns.oid = t.relnamespace
WHERE ns.nspname IN ('capa2', 'mart')
  AND t.relkind IN ('r', 'p', 'v', 'm')
  AND a.attnum > 0 AND NOT a.attisdropped
  AND t.relname NOT LIKE '%\_prev'
  AND (a.attname ILIKE '%imput%' OR a.attname IN ('es_reportado', 'grupo_carry'));

-- Resultado esperado: cero filas.

-- 17.10. Cobertura nacional por mes: prestadores esperados (panel 9b) vs.
-- los que reportaron de verdad.
SELECT
    periodo,
    total_lineas,
    numero_prestadores,
    numero_prestadores_esperados,
    porcentaje_cobertura_prestadores
FROM mart.vw_dashboard_evolucion
WHERE territorio_id = 'NACIONAL|ECUADOR'
ORDER BY periodo;

-- 17.12. NUEVA (31-jul-2026) -- IHH/participación exclusivamente sobre
-- lo reportado. Verifica: (a) ningún prestador sin reporte real ese mes
-- tiene participación o aporte_ihh distinto de NULL; (b) la cobertura de
-- prestadores está siempre entre 0 y 100; (c) CR2 <= CR4 <= 100 siempre.
SELECT *
FROM mart.fact_participacion_mercado
WHERE (NOT tiene_reportado) AND (participacion_porcentaje IS NOT NULL OR aporte_ihh IS NOT NULL);

-- Resultado esperado: cero filas.

SELECT *
FROM mart.fact_ihh_geografico
WHERE porcentaje_cobertura_prestadores < 0
   OR porcentaje_cobertura_prestadores > 100
   OR cr2 > cr4 + 0.001
   OR cr4 > 100.001;

-- Resultado esperado: cero filas.