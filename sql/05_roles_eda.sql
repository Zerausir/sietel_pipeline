-- ============================================================================
-- sql/05_roles_eda.sql
-- Permisos del rol de solo lectura eda_lector, para EDA/ML exploratorio
-- (Jupyter Lab u otro cliente), separado de dashboard_lector.
--
-- POR QUÉ UN ROL SEPARADO Y NO REUTILIZAR dashboard_lector:
-- Mismo principio ya aplicado en todo el proyecto (dashboard_lector vs
-- dashboard_auth, mgonzalez vs sietel_user): un rol por consumidor de
-- propósito distinto, nunca compartir credenciales entre procesos. Un
-- notebook de EDA puede lanzar consultas pesadas/largas (agregaciones sobre
-- todo el histórico, exportes a pandas) que no queremos que compitan por
-- el mismo rol/monitoreo que usa el dashboard en producción -- si algo se
-- bloquea o hay que revocar acceso, afecta solo al EDA, no a OBTEL.
--
-- ESTE ARCHIVO NO CREA EL ROL. La creación de eda_lector (CREATE ROLE +
-- contraseña) se hace por línea de comandos, directamente en la VM --
-- documentar en "Creación de roles y usuarios de PostgreSQL —
-- sietel_pipeline.docx", igual que el resto de roles. Este archivo asume
-- que eda_lector YA EXISTE y falla con un error claro si no es así.
--
-- Requiere que mart_user ya exista (por el ALTER DEFAULT PRIVILEGES de
-- abajo) y que sql/00_roles_mart.sql ya se haya corrido.
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eda_lector') THEN
        RAISE EXCEPTION 'El rol eda_lector no existe. Créalo primero por línea de comandos -- ver Creación de roles y usuarios de PostgreSQL.docx';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mart_user') THEN
        RAISE EXCEPTION 'El rol mart_user no existe. Corre sql/00_roles_mart.sql primero.';
    END IF;
END $$;

-- Solo lectura sobre mart.* -- igual que dashboard_lector. eda_lector NO
-- tiene acceso a staging/analitico (esos son de sietel_user/Capa 1) ni a
-- auth (login del dashboard) ni a calidad (workflow de revisión manual,
-- fuera del alcance de un EDA/ML de líneas dedicadas).
GRANT USAGE ON SCHEMA mart TO eda_lector;
GRANT SELECT ON ALL TABLES IN SCHEMA mart TO eda_lector;
ALTER DEFAULT PRIVILEGES FOR ROLE mart_user IN SCHEMA mart
    GRANT SELECT ON TABLES TO eda_lector;
-- Mismo motivo que en sql/03_ddl_auth.sql y sql/04_ddl_calidad.sql: sin el
-- ALTER DEFAULT PRIVILEGES, cada DROP SCHEMA mart CASCADE + CREATE que hace
-- mart/aplicar_capa3.py deja a eda_lector sin acceso hasta la próxima vez
-- que se corra este archivo a mano.

-- Límite de tiempo por sesión, deliberado: un notebook de EDA puede quedar
-- una conexión abierta más tiempo del que Airflow/el dashboard necesitan.
-- 30 minutos es suficiente para una consulta pesada puntual sin arriesgar
-- una conexión colgada indefinidamente contra la misma instancia que sirve
-- producción.
ALTER ROLE eda_lector SET statement_timeout = '30min';
