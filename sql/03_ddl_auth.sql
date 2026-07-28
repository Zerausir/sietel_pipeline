-- ============================================================================
-- DDL — Autenticación del dashboard SIETEL (Flask-Login + bcrypt)
-- Vive en la misma base sietel_analitico (VM1), esquema propio "auth",
-- separado de "staging"/"analitico" (pipeline) y de "mart" (Capa 2/3).
--
-- POR QUÉ DOS ROLES DISTINTOS PARA EL MISMO CONTENEDOR (no uno solo con más
-- permisos): el dashboard necesita LEER mart.* pero también ESCRIBIR en la
-- tabla de usuarios (ultimo_acceso, altas/bajas). Un solo rol con ambos
-- permisos amplía la superficie de ataque en las dos direcciones. Con dos
-- roles separados, comprometer la sesión de lectura analítica no da acceso
-- a usuarios, y viceversa.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.usuarios_dashboard (
    id                BIGSERIAL PRIMARY KEY,
    username          VARCHAR(50)  NOT NULL UNIQUE,
    password_hash     VARCHAR(100) NOT NULL,
    nombre_completo   VARCHAR(150) NOT NULL,
    activo            BOOLEAN      NOT NULL DEFAULT true,
    ultimo_acceso     TIMESTAMP,
    fecha_creacion    TIMESTAMP    NOT NULL DEFAULT now(),
    fecha_desactivado TIMESTAMP
);

COMMENT ON TABLE auth.usuarios_dashboard IS
'Usuarios internos autorizados a entrar al dashboard SIETEL. Sin autorregistro -- altas, bajas y reseteo de contraseña se hacen exclusivamente vía dashboard/scripts/gestionar_usuarios.py. password_hash es bcrypt, nunca texto plano.';

CREATE INDEX IF NOT EXISTS ix_usuarios_dashboard_activo
    ON auth.usuarios_dashboard (activo);

-- ============================================================================
-- ROLES DE POSTGRESQL PARA EL CONTENEDOR DEL DASHBOARD
-- ============================================================================
-- Ejecutar una sola vez como superusuario. Las contraseñas se generan aparte
-- y se guardan en el .env del contenedor de VM2 -- NUNCA en este archivo ni
-- en Git.

-- 1) Lector analítico: SELECT únicamente sobre mart.* (Capa 2/3).
--    No toca staging/analitico (eso es exclusivo de sietel_pipeline) ni auth.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dashboard_lector') THEN
        CREATE ROLE dashboard_lector LOGIN PASSWORD 'CAMBIAR_ANTES_DE_APLICAR';
    END IF;
END $$;

GRANT USAGE ON SCHEMA mart TO dashboard_lector;
GRANT SELECT ON ALL TABLES IN SCHEMA mart TO dashboard_lector;
ALTER DEFAULT PRIVILEGES FOR ROLE mart_owner IN SCHEMA mart
    GRANT SELECT ON TABLES TO dashboard_lector;
-- NOTA: reemplazar "mart_owner" por el rol que efectivamente cree/refresque
-- los objetos de mart (el mismo patrón de ALTER DEFAULT PRIVILEGES que ya
-- se usó para mgonzalez en el esquema analitico -- ver Instrucciones del
-- Proyecto, sección de PostgreSQL). Sin esto, un refresco de mart vuelve a
-- dejar a dashboard_lector sin acceso a las vistas recién recreadas.

-- 2) Escritor de autenticación: SELECT/INSERT/UPDATE únicamente sobre la
--    tabla de usuarios. Sin acceso a mart, staging ni analitico.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dashboard_auth') THEN
        CREATE ROLE dashboard_auth LOGIN PASSWORD 'CAMBIAR_ANTES_DE_APLICAR';
    END IF;
END $$;

GRANT USAGE ON SCHEMA auth TO dashboard_auth;
GRANT SELECT, INSERT, UPDATE ON auth.usuarios_dashboard TO dashboard_auth;
GRANT USAGE, SELECT ON SEQUENCE auth.usuarios_dashboard_id_seq TO dashboard_auth;

-- El script de administración (gestionar_usuarios.py) corre con un tercer
-- rol, con dueño real de la tabla (o superusuario puntual) -- no con
-- dashboard_auth -- porque desactivar/reactivar usuarios es una operación
-- administrativa fuera del ciclo normal de login de la app.
