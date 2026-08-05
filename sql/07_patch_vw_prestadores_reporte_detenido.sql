-- ============================================================================
-- sql/07_patch_vw_prestadores_reporte_detenido.sql
--
-- Parche puntual para aplicar en producción SIN esperar al próximo refresco
-- completo de sietel_mart_pipeline. Crea/reemplaza
-- mart.vw_prestadores_reporte_detenido -- complemento de
-- vw_prestadores_sin_reportar (jamás reportaron) para prestadores que SÍ
-- reportaron al menos una vez y luego se detuvieron.
--
-- CORREGIDO 05-ago-2026 (misma fecha de la primera versión): la primera
-- versión de este parche usaba MAX(periodo) crudo como referencia para
-- meses_desde_ultimo_reporte. Verificado en producción tras aplicarla contra
-- datos ya avanzados a dic-2025: producía 13 falsos positivos (prestadores
-- con último reporte real en sep-2025, exactamente 3 meses de rezago normal
-- de carga -- ver 9.7 -- marcados como "detenidos" sin serlo). Esta versión
-- usa un período de referencia confiable (MAX(periodo) menos 3 meses de
-- margen) en su lugar. Si ya aplicaste la primera versión de este archivo,
-- correr esta sobreescribe la vista sin problema (CREATE OR REPLACE).
--
-- Justificación completa: ver comentario en sql/02_ddl_mart.sql (sección
-- de vw_prestadores_reporte_detenido) y EDA_sietel_lineas_dedicadas.ipynb,
-- secciones 9.7, 9.11/9.12/9.13 (caso CNT EP).
-- ============================================================================

CREATE OR REPLACE VIEW mart.vw_prestadores_reporte_detenido AS
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
    SELECT SUM(f.lineas_reportadas) AS lineas_reportadas
    FROM mart.fact_lineas_geografia_mes f
    WHERE f.prestador_id = p.prestador_id
      AND f.periodo = p.ultimo_periodo_reportado
) ultimo ON TRUE
LEFT JOIN LATERAL (
    SELECT SUM(f.lineas_reportadas) AS total_lineas_historico
    FROM mart.fact_lineas_geografia_mes f
    WHERE f.prestador_id = p.prestador_id
) historico ON TRUE
WHERE p.primer_periodo_reportado IS NOT NULL;

-- Respaldo de permisos.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dashboard_lector') THEN
        GRANT SELECT ON mart.vw_prestadores_reporte_detenido TO dashboard_lector;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'calidad_lector') THEN
        GRANT SELECT ON mart.vw_prestadores_reporte_detenido TO calidad_lector;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eda_lector') THEN
        GRANT SELECT ON mart.vw_prestadores_reporte_detenido TO eda_lector;
    END IF;
END $$;

-- Verificación tras aplicar esta versión corregida:
--   SELECT COUNT(*) FROM mart.vw_prestadores_reporte_detenido
--   WHERE opera_actual = 'Opera Normalmente' AND es_cancelado_actual = FALSE
--     AND total_lineas_historico > 100000 AND meses_desde_ultimo_reporte >= 3;
--
--   Esperado, con datos hasta dic-2025 (periodo_confiable = sep-2025):
--   18 filas -- el grupo de 13 con ultimo_periodo_reportado = 2025-09-01
--   debe salir ahora con meses_desde_ultimo_reporte = 0 (excluido del
--   filtro >= 3 automáticamente, sin necesidad de una lista de exclusión
--   manual). CORPORACION NACIONAL DE TELECOMUNICACIONES CNT EP debe seguir
--   apareciendo con lineas_ultimo_reporte = 394716.
--
-- Si en el futuro MAX(periodo) avanza más allá de dic-2025, este conteo de
-- 18 puede cambiar de forma legítima (CNT sigue sin retomar -> se suman
-- casos; algún prestador de los 18 retoma -> se resta) -- eso ya no sería
-- un falso positivo, sería el hallazgo evolucionando con datos nuevos.