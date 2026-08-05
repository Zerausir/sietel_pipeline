-- ============================================================================
-- sql/06_patch_vw_prestadores_sin_reportar.sql
--
-- Parche puntual para aplicar en producción SIN esperar al próximo refresco
-- completo de sietel_mart_pipeline (que haría DROP SCHEMA mart CASCADE +
-- reconstrucción completa -- innecesario y arriesgado solo para este cambio).
--
-- Agrega dos columnas calculadas a mart.vw_prestadores_sin_reportar:
--   - fuera_de_gracia: boolean, NULL si fechapermiso es NULL. Misma regla del
--     año de gracia que dashboard/services/queries.py:get_reporting_summary.
--   - clasificacion_incumplimiento: text, uno de
--     'activo_sin_reportar' / 'no_operativo' / 'zona_gris'.
--
-- Justificación completa y hallazgos que motivan este cambio: ver comentario
-- en sql/02_ddl_mart.sql (sección de vw_prestadores_sin_reportar) y
-- EDA_sietel_lineas_dedicadas.ipynb, secciones 9.4/9.6.
--
-- IMPORTANTE: este parche debe reflejarse también en sql/02_ddl_mart.sql (ya
-- hecho en la copia entregada junto a este archivo) para que sobreviva al
-- próximo DROP SCHEMA CASCADE. Este archivo es un atajo operativo, NO
-- reemplaza la fuente de verdad del DDL completo.
--
-- CREATE OR REPLACE VIEW no afecta los GRANT ya otorgados sobre el objeto
-- (a diferencia de DROP + CREATE) -- dashboard_lector y calidad_lector
-- conservan su acceso de lectura sin necesidad de volver a otorgar permisos.
-- ============================================================================

CREATE OR REPLACE VIEW mart.vw_prestadores_sin_reportar AS
SELECT
    peva_codigo,
    isp_nombre,
    isp_ruc,
    isp_tipopersona,
    opera,
    resolucion,
    fechapermiso,
    CASE
        WHEN fechapermiso IS NULL THEN NULL
        ELSE CURRENT_DATE >= (fechapermiso + INTERVAL '1 year')
    END AS fuera_de_gracia,
    CASE
        WHEN opera IN ('Nuevo', 'Opera Normalmente', 'SI') THEN 'activo_sin_reportar'
        WHEN opera IN ('Cancelación', 'NO', 'Opera Irregularmente') THEN 'no_operativo'
        ELSE 'zona_gris'
    END AS clasificacion_incumplimiento
FROM analitico.v_ultimo_periodo_reportado_detalle
WHERE tiene_reportes = FALSE;

-- Verificación esperada tras aplicar (debe coincidir con el EDA, 05-ago-2026):
--   SELECT clasificacion_incumplimiento, COUNT(*)
--   FROM mart.vw_prestadores_sin_reportar
--   WHERE fuera_de_gracia
--   GROUP BY clasificacion_incumplimiento;
--
--   Esperado: activo_sin_reportar=104, no_operativo=125, zona_gris=56
