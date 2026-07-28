-- ============================================================================
-- Rol dueño de los objetos del esquema mart (Capa 2/3)
-- Ejecutar UNA VEZ, como superusuario, ANTES de correr sql/02_ddl_mart.sql
-- y ANTES de sql/03_ddl_auth.sql (03 hace referencia a este rol en el
-- ALTER DEFAULT PRIVILEGES).
--
-- Sigue el mismo patrón que ya usan sietel_user (dueño de staging/analitico)
-- y mgonzalez (lector de analitico): un rol dueño que CREA los objetos, y
-- roles de consumo separados que solo LEEN. mart_user es el equivalente de
-- sietel_user, pero para el esquema mart.
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mart_user') THEN
        CREATE ROLE mart_user LOGIN PASSWORD 'CAMBIAR_ANTES_DE_APLICAR';
    END IF;
END $$;

-- mart_user necesita crear/reemplazar el esquema completo (DROP SCHEMA
-- mart CASCADE + CREATE SCHEMA al inicio de 02_ddl_mart.sql), así que
-- necesita ser dueño de la base o tener CREATEDB/CREATEROLE no -- basta con
-- permiso de creación de esquemas en la base sietel_analitico:
GRANT CREATE ON DATABASE sietel_analitico TO mart_user;

-- El script mart/aplicar_capa3.py (que reemplaza a Capa3.sql corrido a
-- mano) se conecta con este rol. Guardar la contraseña real solo en el
-- .env de ese proceso -- nunca en este archivo ni en Git.
