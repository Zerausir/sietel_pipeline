-- ============================================================================
-- sql/11_roles_siger.sql
-- Rol siger_user y esquema siger (réplica de SIGER_V3) -- SOLO DOCUMENTACIÓN.
--
-- ⚠️  NO RE-EJECUTAR. Estos comandos YA se ejecutaron en VM1 el 05-oct-2026
-- (como superusuario postgres). Este archivo existe como referencia para
-- reconstruir el entorno desde cero, con el mismo estilo que
-- sql/00_roles_mart.sql. El pipeline (siger/aplicar_esquema_siger.py) NUNCA
-- lo ejecuta: corre como siger_user, que no tiene CREATE sobre la base y no
-- podría crear el esquema ni el rol.
--
-- Mismo principio que el resto del proyecto: un rol dueño que CREA los
-- objetos (siger_user, como sietel_user para staging/analitico o mart_user
-- para mart/capa2/calidad) y roles de consumo separados que solo LEEN. Otro
-- servidor de origen, otras credenciales: siger_user no comparte contraseña
-- con ningún otro proceso.
--
-- La contraseña real va SOLO en el .env (SIGER_PG_PASSWORD), nunca aquí.
-- ============================================================================

-- 1. Rol de login (ejecutado por línea de comandos, como el resto de roles --
--    ver "Creación de roles y usuarios de PostgreSQL — sietel_pipeline.docx"):
--
--   sudo -u postgres psql -c "CREATE ROLE siger_user LOGIN PASSWORD '<contraseña>';"

-- 2. Conexión a la base y esquema propio (siger_user NO recibe CREATE sobre
--    la base: solo puede crear objetos dentro de siger):
--
--   GRANT CONNECT ON DATABASE sietel_analitico TO siger_user;
--   CREATE SCHEMA siger AUTHORIZATION siger_user;

-- 3. Auditoría de cargas en staging.control_cargas (dueño sietel_user):
--    siger_user registra sus cargas con tipo_carga propio (siger_*), sin
--    poder modificar ni borrar las de SIETEL.
--
--   GRANT USAGE ON SCHEMA staging TO siger_user;
--   GRANT SELECT, INSERT ON staging.control_cargas TO siger_user;
--   GRANT USAGE ON SEQUENCE staging.control_cargas_id_seq TO siger_user;

-- 4. Lectura para mart_user (cruce con OBTEL en calidad). ALTER DEFAULT
--    PRIVILEGES ... ON TABLES cubre tablas Y vistas que siger_user cree en
--    siger. La excepción (siger.concesionario, datos personales -- LOPDP) se
--    revoca en sql/12_ddl_siger.sql, que mart_user lee solo vía
--    siger.v_concesionario_basico.
--
--   GRANT USAGE ON SCHEMA siger TO mart_user;
--   ALTER DEFAULT PRIVILEGES FOR ROLE siger_user IN SCHEMA siger
--       GRANT SELECT ON TABLES TO mart_user;
--
--    Ningún rol del dashboard (dashboard_lector, dashboard_auth,
--    calidad_lector, calidad_revisor, eda_lector) recibe acceso a siger.

-- 5. pg_hba.conf (VM1) -- siger_user desde VM2 (Airflow) y desde la estación
--    de trabajo; luego `sudo systemctl reload postgresql`:
--
--   host    sietel_analitico    siger_user    192.168.129.51/32    scram-sha-256
--   host    sietel_analitico    siger_user    192.168.137.50/32    scram-sha-256

-- Verificación (solo lectura) desde el contenedor de Airflow:
--   docker compose exec airflow-scheduler python /opt/airflow/siger/probar_conexion.py --pg
