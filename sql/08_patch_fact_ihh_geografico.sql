-- ============================================================================
-- sql/08_patch_fact_ihh_geografico.sql (v4 -- acotado solo a NACIONAL)
--
-- Parche puntual para aplicar en producción SIN esperar al próximo refresco
-- completo de sietel_mart_pipeline. Agrega detección de "prestador
-- dominante ausente" a mart.fact_ihh_geografico -- Parte A del cambio #4
-- de la verificación de repo (05-ago-2026), ver comentario completo en
-- sql/02_ddl_mart.sql y EDA_sietel_lineas_dedicadas.ipynb secciones 9.10/9.11.
--
-- HISTORIAL DE CORRECCIONES (las tres detectadas en producción antes de
-- comprometer el cambio, no en el EDA -- cada una verificada con datos
-- reales antes de la siguiente):
--   v1 -> v2: sin acotar por primer_periodo_reportado del prestador,
--     CONECEL/MEGADATOS (entraron en 2020/2021) aparecían "ausentes" en
--     2012-2013, antes de existir en el sistema.
--   v2 -> v3: sin acotar por nivel geográfico, la alerta se disparaba de
--     forma casi permanente en cantones/parroquias pequeños (ej. COMM &
--     NET S.A., decenas de meses marcados en varias parroquias).
--   v3 -> v4: se intentó acotar a NACIONAL + PROVINCIA, pero verificado
--     que PROVINCIA tiene el MISMO problema (TRANSTELCO S.A. con 388
--     meses marcados, más que los 292 de CNT) -- prestadores chicos
--     superan 30% en provincias con pocos competidores y salen del
--     mercado para siempre. v4 acota estrictamente a NACIONAL, el único
--     nivel donde los hallazgos originales (9.10/9.11) documentaron y
--     cuantificaron un caso real con evidencia (CNT). Detectar dominancia
--     provincial genuina (distinta de rotación de mercado) requeriría un
--     diseño más cuidadoso -- fuera de alcance de este cambio.
--
-- SOLO INFORMATIVO -- no modifica el cálculo de IHH/CR2/CR4 en absoluto.
-- Agrega dos columnas: prestador_dominante_ausente (boolean) y
-- prestadores_dominantes_ausentes_nombres (text).
--
-- DISTINTO A LOS PARCHES ANTERIORES (06, 07): fact_ihh_geografico es una
-- VISTA MATERIALIZADA -- PostgreSQL no soporta CREATE OR REPLACE
-- MATERIALIZED VIEW. Este parche: 1) DROP ... CASCADE (se lleva consigo
-- SOLO vw_dashboard_ihh); 2) recrea fact_ihh_geografico; 3) recrea sus
-- índices; 4) recrea vw_dashboard_ihh; 5) re-otorga permisos.
--
-- Si ya aplicaste v1, v2 o v3, correr esta v4 sobreescribe todo de nuevo
-- sin problema (mismo patrón DROP+CREATE).
-- ============================================================================

DROP MATERIALIZED VIEW IF EXISTS mart.fact_ihh_geografico CASCADE;

CREATE MATERIALIZED VIEW mart.fact_ihh_geografico AS
-- ALERTA DE PRESTADOR DOMINANTE AUSENTE (agregado 05-ago-2026, EDA de
-- líneas dedicadas -- sección 9.10). NO modifica el IHH/CR2/CR4 en
-- absoluto -- es exclusivamente informativa, mismo principio que
-- porcentaje_cobertura_prestadores: el índice se calcula igual que siempre
-- (solo con lineas_reportadas de quien reportó ese mes), y esta bandera
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
    ) AS numero_prestadores_imputados,
    -- COBERTURA (31-jul-2026): el IHH/CR2/CR4 de arriba se calculan SOLO
    -- sobre lineas_reportadas de quien reportó ese mes exacto -- estas
    -- columnas dejan explícito CUÁNTO del universo conocido queda
    -- representado, para que el índice nunca se lea sin su contexto de
    -- completitud (mismo principio ya aplicado en Evolución con
    -- "% de prestadores que reportaron").
    MAX(numero_prestadores_reportaron_periodo) AS numero_prestadores_reportaron,
    MAX(numero_prestadores_totales_periodo) AS numero_prestadores_registrados,
    ROUND(
        100.0
        * MAX(numero_prestadores_reportaron_periodo)
        / NULLIF(MAX(numero_prestadores_totales_periodo), 0),
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
    f.numero_prestadores_imputados,
    f.numero_prestadores_reportaron,
    f.numero_prestadores_registrados,
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

-- Respaldo de permisos.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dashboard_lector') THEN
        GRANT SELECT ON mart.fact_ihh_geografico TO dashboard_lector;
        GRANT SELECT ON mart.vw_dashboard_ihh TO dashboard_lector;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'calidad_lector') THEN
        GRANT SELECT ON mart.fact_ihh_geografico TO calidad_lector;
        GRANT SELECT ON mart.vw_dashboard_ihh TO calidad_lector;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eda_lector') THEN
        GRANT SELECT ON mart.fact_ihh_geografico TO eda_lector;
        GRANT SELECT ON mart.vw_dashboard_ihh TO eda_lector;
    END IF;
END $$;

-- Verificación tras aplicar v4:
--
-- 1) Ya NO debe haber ninguna fila con prestador_dominante_ausente fuera
--    de NACIONAL:
--   SELECT COUNT(*) FROM mart.fact_ihh_geografico
--   WHERE prestador_dominante_ausente AND territorio_id != 'NACIONAL|ECUADOR';
--   Esperado: 0.
--
-- 2) El caso CNT (9.10/9.11) debe seguir intacto:
--   SELECT periodo_id, ihh, prestador_dominante_ausente,
--          prestadores_dominantes_ausentes_nombres
--   FROM mart.vw_dashboard_ihh
--   WHERE territorio_id = 'NACIONAL|ECUADOR'
--     AND periodo_id IN (201210, 201211, 201301, 201302, 201304, 201305,
--                         201307, 201308, 201507)
--   ORDER BY periodo_id;
--   Esperado: 9 filas, solo CNT.
--
-- 3) Total nacional -- debe volver a ser 42, el mismo número ya verificado
--    antes de que se descubriera el problema de cantón/parroquia/provincia:
--   SELECT COUNT(*) FROM mart.vw_dashboard_ihh
--   WHERE territorio_id = 'NACIONAL|ECUADOR' AND prestador_dominante_ausente;
--   Esperado: 42.
--
-- Si los tres coinciden, el cambio queda listo para comprometer -- ya no
-- hace falta seguir revisando otros niveles, el alcance quedó
-- deliberadamente limitado a NACIONAL únicamente.