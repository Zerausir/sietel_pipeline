-- ============================================================================
-- Permisos del rol mart_user sobre la base de datos (Capa 2/3)
-- Ejecutar UNA VEZ, ANTES de correr sql/02_ddl_mart.sql y sql/03_ddl_auth.sql
-- (03 hace referencia a este rol en el ALTER DEFAULT PRIVILEGES).
--
-- Sigue el mismo patrón que ya usan sietel_user (dueño de staging/analitico)
-- y mgonzalez (lector de analitico): un rol dueño que CREA los objetos, y
-- roles de consumo separados que solo LEEN. mart_user es el equivalente de
-- sietel_user, pero para el esquema mart.
--
-- ESTE ARCHIVO YA NO CREA EL ROL. La creación de mart_user (CREATE ROLE +
-- contraseña) se hace por línea de comandos, directamente en la VM --
-- documentado en "Creación de roles y usuarios de PostgreSQL — sietel_pipeline.docx".
-- Ese documento es la fuente de verdad de qué roles existen y cuándo se
-- crearon; este archivo asume que mart_user YA EXISTE al momento de
-- correrlo, y falla con un error claro si no es así.
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mart_user') THEN
        RAISE EXCEPTION 'El rol mart_user no existe. Créalo primero por línea de comandos -- ver Creación de roles y usuarios de PostgreSQL.docx';
    END IF;
END $$;

-- mart_user necesita crear/reemplazar el esquema completo (DROP SCHEMA
-- mart CASCADE + CREATE SCHEMA al inicio de 02_ddl_mart.sql), así que
-- necesita ser dueño de la base o tener CREATEDB/CREATEROLE no -- basta con
-- permiso de creación de esquemas en la base sietel_analitico:
GRANT CREATE ON DATABASE sietel_analitico TO mart_user;

-- El script mart/construir_capa2.py y mart/detectar_conflictos_peva.py se
-- conectan con este rol. Guardar la contraseña real solo en el .env de
-- esos procesos -- nunca en este archivo ni en Git.