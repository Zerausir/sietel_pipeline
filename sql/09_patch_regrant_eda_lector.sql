-- ============================================================================
-- sql/09_patch_regrant_eda_lector.sql
--
-- Reotorga acceso a eda_lector tras un refresco de sietel_mart_pipeline que
-- borró USAGE ON SCHEMA mart (DROP SCHEMA mart CASCADE elimina TODOS los
-- privilegios sobre el esquema, incluidos los otorgados por
-- sql/05_roles_eda.sql). Mismo tipo de falla que ya afectó a
-- dashboard_lector el 29-jul-2026 -- ver sección 18 de sql/02_ddl_mart.sql.
--
-- Uso inmediato/manual. La corrección PERMANENTE va en
-- sql/02_ddl_mart.sql, sección 18 (ver bloque separado) para que no vuelva
-- a pasar en el próximo refresco automático.
-- ============================================================================

GRANT USAGE ON SCHEMA mart TO eda_lector;
GRANT SELECT ON ALL TABLES IN SCHEMA mart TO eda_lector;
ALTER DEFAULT PRIVILEGES FOR ROLE mart_user IN SCHEMA mart
    GRANT SELECT ON TABLES TO eda_lector;

-- Verificación:
--   SET ROLE eda_lector;
--   SELECT * FROM mart.dim_periodo LIMIT 1;
--   RESET ROLE;