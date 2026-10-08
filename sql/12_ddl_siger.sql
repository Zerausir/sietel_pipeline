-- ============================================================================
-- sql/12_ddl_siger.sql
-- Réplica de SIGER_V3 en el esquema siger (dueño siger_user) + vistas SAI.
--
-- Lo aplica siger/aplicar_esquema_siger.py (tarea aplicar_esquema_siger de
-- dags/siger_pipeline.py), conectado COMO siger_user, en cada corrida.
-- Idempotente: CREATE TABLE/INDEX IF NOT EXISTS, CREATE OR REPLACE VIEW,
-- GRANT/REVOKE. NO crea el esquema (siger_user no tiene CREATE sobre la
-- base -- el esquema ya existe, ver sql/11_roles_siger.sql).
--
-- TABLAS CRUDAS = COPIA FIEL, sin filtros de servicio, estado ni
-- eliminación: todos los servicios (incluida radiodifusión/TV), todos los
-- estados, y las filas de facturación con ELIMINADO = 1. Cualquier filtro
-- (universo SAI, VIGENTE, activos) vive SOLO en las vistas. Columnas = las
-- que SIGER deja consultar (permisos por columna, ver
-- siger/config_siger.py); texto como TEXT sin recortar (char viene con
-- relleno), float(53) -> DOUBLE PRECISION, smalldatetime/datetime ->
-- TIMESTAMP(6), bit -> BOOLEAN. Más hash_contenido (MD5 de las columnas de
-- origen, siger/hash_siger.py) y fecha_carga.
--
-- Carga: snapshot completo por reemplazo en una sola transacción
-- (TRUNCATE + INSERT por lotes + certificación + COMMIT) -- ver
-- siger/cargar_siger.py. Sin UPSERT: lección del incidente del 25-sep-2026
-- (filas huérfanas que el UPSERT nunca borró).
--
-- VISTAS: CREATE OR REPLACE (no DROP + CREATE): calidad.hallazgos_siger_obtel
-- no depende de ellas (es una tabla), pero así ningún objeto de mart_user
-- que las lea se borra por CASCADE. Limitación de CREATE OR REPLACE VIEW:
-- solo se pueden AGREGAR columnas al final; para reordenar o quitar,
-- DROP VIEW manual una vez.
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'siger') THEN
        RAISE EXCEPTION 'El esquema siger no existe. Debe crearlo un superusuario (CREATE SCHEMA siger AUTHORIZATION siger_user) -- ver sql/11_roles_siger.sql.';
    END IF;
    IF (SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'siger') <> current_user THEN
        RAISE EXCEPTION 'Este archivo debe aplicarse como el dueño del esquema siger (siger_user), no como %.', current_user;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mart_user') THEN
        RAISE EXCEPTION 'El rol mart_user no existe -- ver sql/00_roles_mart.sql.';
    END IF;
END $$;

-- ----------------------------------------------------------------------------
-- 1. Catálogo de servicios -- dbo.SERVICIO_TH (40 filas al 05-oct-2026)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS siger.servicio_th (
    idsth            INTEGER PRIMARY KEY,
    abreviatura      TEXT,
    descripcion      TEXT,
    hash_contenido   VARCHAR(32) NOT NULL,
    fecha_carga      TIMESTAMP   NOT NULL DEFAULT now()
);
COMMENT ON TABLE siger.servicio_th IS
'Copia fiel de SIGER_V3 dbo.SERVICIO_TH (todos los tipos de servicio, incluida radiodifusión/TV). IDTSV y ELIMINACION no se replican: permiso denegado.';

-- ----------------------------------------------------------------------------
-- 2. Títulos habilitantes -- dbo.TITULO_HABILITANTE (34.278 filas al 05-oct-2026)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS siger.titulo_habilitante (
    thsecuencial     BIGINT PRIMARY KEY,   -- float en SIGER; se verifica entero al cargar
    idsth            INTEGER,
    thtomo           TEXT,                 -- texto SIEMPRE ('010', '13708A', '08f02v')
    thfoja           TEXT,
    ucp_concnum      TEXT,
    thfechasus       TIMESTAMP(6),
    thfechavig       TIMESTAMP(6),
    thestado         TEXT,
    -- Derivada: LTRIM(RTRIM(THTOMO)) || '-' || LTRIM(RTRIM(THFOJA)); '-' sin tomo-foja.
    contrato_key     TEXT        NOT NULL,
    hash_contenido   VARCHAR(32) NOT NULL,
    fecha_carga      TIMESTAMP   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_siger_titulo_idsth ON siger.titulo_habilitante (idsth);
CREATE INDEX IF NOT EXISTS ix_siger_titulo_concnum ON siger.titulo_habilitante (btrim(ucp_concnum));
CREATE INDEX IF NOT EXISTS ix_siger_titulo_contrato ON siger.titulo_habilitante (upper(contrato_key));
COMMENT ON TABLE siger.titulo_habilitante IS
'Copia fiel de SIGER_V3 dbo.TITULO_HABILITANTE: todos los servicios y estados, sin filtros. Solo columnas con permiso (THPAGINA, THACTA, THUSUARIO, THRESOLUCION, THNUMERO_TRAMITE, etc. denegadas). contrato_key = tomo-foja recortados (''-'' = sin tomo-foja, no enlaza con facturación). Un contrato puede agrupar varios títulos de servicios distintos: la facturación se enlaza por contrato, el análisis SAI por título.';

-- ----------------------------------------------------------------------------
-- 3. Concesionarios -- dbo.VISTA_CONCESIONARIOS (27.280 filas al 05-oct-2026)
--    DATOS PERSONALES (LOPDP): ~10.700 personas naturales identificadas por
--    cédula. Acceso restringido: ver sección 7.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS siger.concesionario (
    ucp_concnum      TEXT,
    nombres          TEXT,
    ci_ruc           TEXT,
    ruc              TEXT,                 -- char(13) en SIGER: se guarda con su relleno
    -- Derivadas (siger/reglas.py: resolver_ruc)
    ruc_resuelto     TEXT,
    ruc_origen       TEXT        NOT NULL
        CHECK (ruc_origen IN ('ruc', 'ci_ruc_13', 'cedula_001', 'sin_ruc')),
    hash_contenido   VARCHAR(32) NOT NULL,
    fecha_carga      TIMESTAMP   NOT NULL DEFAULT now()
);
-- Sin PK: la vista de origen no garantiza unicidad (hoy 27.280 códigos
-- únicos); validar_siger lo reporta en vez de hacer fallar la copia.
CREATE INDEX IF NOT EXISTS ix_siger_concesionario_concnum ON siger.concesionario (btrim(ucp_concnum));
CREATE INDEX IF NOT EXISTS ix_siger_concesionario_ruc ON siger.concesionario (ruc_resuelto);
COMMENT ON TABLE siger.concesionario IS
'Copia fiel de SIGER_V3 dbo.VISTA_CONCESIONARIOS, solo columnas con permiso (ucp_concnum, nombres, ci_ruc, ruc; ubicación, contacto y tipo denegados). Contiene DATOS PERSONALES (LOPDP): sin SELECT para mart_user ni roles del dashboard -- usar siger.v_concesionario_basico. ruc_resuelto/ruc_origen: regla de siger/reglas.py (ruc 13 díg. > ci_ruc 13 díg. > cédula 10 díg. + 001 > sin_ruc).';

-- ----------------------------------------------------------------------------
-- 4. Facturación por uso del espectro -- dbo.NR_PARAMETROS_FACTURACION
--    (~2,56 M filas al 05-oct-2026; historia desde 2023-02-01; sin
--    radiodifusión/TV). Incluye ELIMINADO = 1: activo = COALESCE(eliminado,
--    false) = false, solo en vistas. Sin llave natural confiable.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS siger.facturacion_espectro (
    client_code           TEXT NOT NULL,
    nt_id                 DOUBLE PRECISION NOT NULL,
    cod_servicio          TEXT,
    nom_servicio          TEXT,
    tipo_uso              TEXT,
    contrato              TEXT,
    fecha_contrato        TIMESTAMP(6),
    tipo_solicitud        TEXT,
    st_id1                DOUBLE PRECISION,
    estacion_a            TEXT,
    provincia_a           TEXT,
    canton_a              TEXT,
    parroquia_a           TEXT,
    cod_parroq_a          TEXT,
    ubicacion_a           TEXT,
    ivap_a                DOUBLE PRECISION,
    zona_prioriza_a       TEXT,
    beta_a                DOUBLE PRECISION,
    valor_est_a           DOUBLE PRECISION,
    st_id2                DOUBLE PRECISION,
    estacion_b            TEXT,
    provincia_b           TEXT,
    canton_b              TEXT,
    parroquia_b           TEXT,
    cod_parroq_b          TEXT,
    ubicacion_b           TEXT,
    ivap_b                DOUBLE PRECISION,
    zona_prioriza_b       TEXT,
    beta_b                DOUBLE PRECISION,
    valor_est_b           DOUBLE PRECISION,
    frec_tx               DOUBLE PRECISION,
    frec_rx               DOUBLE PRECISION,
    alfa_tx               DOUBLE PRECISION,
    alfa_rx               DOUBLE PRECISION,
    bw_asignado           DOUBLE PRECISION,
    beta                  DOUBLE PRECISION,
    potencia              DOUBLE PRECISION,
    ganancia              DOUBLE PRECISION,
    altura_efectiva       DOUBLE PRECISION,
    ivap                  DOUBLE PRECISION,
    distancia             DOUBLE PRECISION,
    latitud               TEXT,
    longitud              TEXT,
    lat_g                 DOUBLE PRECISION,
    lat_min               DOUBLE PRECISION,
    lat_seg               DOUBLE PRECISION,
    lat_n_s               TEXT,
    lon_g                 DOUBLE PRECISION,
    lon_min               DOUBLE PRECISION,
    lon_seg               DOUBLE PRECISION,
    lon_w                 TEXT,
    tipo_estacion         TEXT,
    tec_sma               TEXT,
    descuento_rb          DOUBLE PRECISION,
    densidad_pob          TEXT,
    fac_propagacion       DOUBLE PRECISION,
    zona_prioriza         TEXT,
    tipo_uso_sitio        TEXT,
    categoria             TEXT,
    modulacion            TEXT,
    val_modulacion        DOUBLE PRECISION,
    fec                   DOUBLE PRECISION,
    velocidad_tx          DOUBLE PRECISION,
    satelite              TEXT,
    cob_satelital         TEXT,
    fcs                   DOUBLE PRECISION,
    no_horas_op           INTEGER,
    no_frec               INTEGER,
    no_operadores         INTEGER,
    no_constelaciones     INTEGER,
    no_estaciones         INTEGER,
    factor_red_sm         DOUBLE PRECISION,
    serv_asociado         TEXT,
    cod_serv_aso          TEXT,
    desc_serv_aso         TEXT,
    cod_enlace            DOUBLE PRECISION,
    per                   DOUBLE PRECISION,
    x                     DOUBLE PRECISION,
    factor_p              DOUBLE PRECISION,
    factor_k              DOUBLE PRECISION,
    fve                   DOUBLE PRECISION,
    tipo_equipo           TEXT,
    na                    INTEGER,
    nd                    INTEGER,
    nv                    INTEGER,
    factor_a              DOUBLE PRECISION,
    factor_u              DOUBLE PRECISION,
    tipo_sistema          TEXT,
    cod_seg               TEXT,
    no_reg_mdba           TEXT,
    fecha_operacion       TIMESTAMP(6),
    val_udbl              DOUBLE PRECISION,
    sbu                   DOUBLE PRECISION,
    cod_siratv            TEXT,
    coef_tcs              DOUBLE PRECISION,
    valor_ec              DOUBLE PRECISION,
    fecha_facturacion     TIMESTAMP(6) NOT NULL,
    ecuacion              TEXT,
    eliminado             BOOLEAN,
    -- Derivadas (siger/reglas.py)
    contrato_key          TEXT,                -- CONTRATO recortado; NULL si vacío
    tipo_enlace           TEXT NOT NULL
        CHECK (tipo_enlace IN ('TOMO_FOJA', 'TRAMITE', 'SIN_CONTRATO', 'SIN_MATCH')),
    hash_contenido        VARCHAR(32) NOT NULL,
    fecha_carga           TIMESTAMP   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_siger_facturacion_contrato ON siger.facturacion_espectro (upper(contrato_key));
CREATE INDEX IF NOT EXISTS ix_siger_facturacion_cliente ON siger.facturacion_espectro (btrim(client_code));
CREATE INDEX IF NOT EXISTS ix_siger_facturacion_fecha ON siger.facturacion_espectro (fecha_facturacion);
CREATE INDEX IF NOT EXISTS ix_siger_facturacion_servicio ON siger.facturacion_espectro (cod_servicio);
COMMENT ON TABLE siger.facturacion_espectro IS
'Copia fiel de SIGER_V3 dbo.NR_PARAMETROS_FACTURACION (las 99 columnas), incluidas las filas con ELIMINADO = 1 (activo = COALESCE(eliminado, false) = false, nunca eliminado = false). COD_SERVICIO/NOM_SERVICIO tal cual (variantes "(r)" = uso reservado; no se fusionan). tipo_enlace: TOMO_FOJA (contrato = tomo-foja de un título, sin distinguir mayúsculas), TRAMITE (ARCOTEL-..., requeriría THNUMERO_TRAMITE, denegada), SIN_CONTRATO (NULL/vacío, ej. TCS), SIN_MATCH.';

-- ----------------------------------------------------------------------------
-- 5. Universo SAI -- parámetro de las vistas derivadas (NUNCA de la extracción)
--    Fuente única: siger/config_siger.py IDSTH_UNIVERSO_SAI; la sincroniza
--    siger/aplicar_esquema_siger.py después de aplicar este archivo.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS siger.parametro_universo_sai (
    idsth        INTEGER PRIMARY KEY,
    descripcion  TEXT NOT NULL
);
COMMENT ON TABLE siger.parametro_universo_sai IS
'IDSTH que forman el universo SAI de las vistas derivadas (9, 33, 31; se EXCLUYE 8 VALOR AGREGADO: agregadores de SMS, contenido móvil y rastreo vehicular). Se sincroniza desde siger/config_siger.py IDSTH_UNIVERSO_SAI en cada corrida -- editar allí, no aquí.';

-- ----------------------------------------------------------------------------
-- 5b. Huella de la fuente (08-oct-2026) -- detección de cambios
--     Una fila por tabla (tipo_carga) con la huella de SIGER tomada antes de
--     extraer el último snapshot confirmado. La escribe siger/cargar_siger.py
--     en la MISMA transacción del snapshot; validar_siger.py borra la de una
--     tabla que no certifica, para que se recargue. Ver siger/huella_siger.py.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS siger.huella_fuente (
    tabla           TEXT        PRIMARY KEY,   -- tipo_carga: siger_servicios, siger_titulos...
    filas           BIGINT      NOT NULL,      -- COUNT_BIG(*) en SIGER
    checksum        INTEGER,                   -- CHECKSUM_AGG(BINARY_CHECKSUM(columnas)); NULL si 0 filas
    columnas        TEXT        NOT NULL,      -- MD5 de la lista de columnas replicadas
    fecha_registro  TIMESTAMP   NOT NULL DEFAULT now()
);
COMMENT ON TABLE siger.huella_fuente IS
'Huella (conteo + CHECKSUM_AGG) de cada tabla de SIGER_V3 en su último snapshot confirmado. Si la huella actual coincide, siger_pipeline no recarga la tabla. Borrar una fila fuerza su recarga en la próxima corrida.';

-- ----------------------------------------------------------------------------
-- 6. Vistas derivadas
-- ----------------------------------------------------------------------------

-- Títulos del universo SAI (nivel TÍTULO). es_vigente compara sin
-- distinguir mayúsculas ni espacios, igual que SQL Server.
CREATE OR REPLACE VIEW siger.v_titulo_sai AS
SELECT
    t.thsecuencial,
    t.idsth,
    s.descripcion                                  AS servicio,
    btrim(t.ucp_concnum)                           AS ucp_concnum,
    t.thtomo,
    t.thfoja,
    t.contrato_key,
    (t.contrato_key <> '-')                        AS con_tomo_foja,
    t.thestado,
    (upper(btrim(t.thestado)) = 'VIGENTE')         AS es_vigente,
    t.thfechavig,
    t.thfechasus
FROM siger.titulo_habilitante t
JOIN siger.parametro_universo_sai u ON u.idsth = t.idsth
LEFT JOIN siger.servicio_th s ON s.idsth = t.idsth;

COMMENT ON VIEW siger.v_titulo_sai IS
'Títulos habilitantes del universo SAI (siger.parametro_universo_sai), todos los estados. con_tomo_foja = contrato_key <> ''-''.';

-- Prestadores SAI a nivel de RUC (unidad de análisis = concesionario/RUC,
-- no título). Una fila por ruc_resuelto con al menos un título SAI (en
-- cualquier estado); los concesionarios sin RUC resuelto quedan en filas
-- propias con clave_prestador = 'SIN_RUC:<ucp_concnum>'.
-- Título de referencia: el vigente CON tomo-foja de mayor THFECHAVIG
-- (patrón validado: 97,1 % tiene uno con tomo-foja + 0-2 marginales sin
-- tomo-foja con la misma THFECHAVIG). Anomalías (§3.8) se MARCAN, no se corrigen.
CREATE OR REPLACE VIEW siger.v_prestador_sai AS
WITH t AS (
    SELECT
        ts.*,
        c.ruc_resuelto,
        c.ruc_origen,
        c.nombres,
        COALESCE(c.ruc_resuelto, 'SIN_RUC:' || COALESCE(ts.ucp_concnum, '?')) AS clave_prestador
    FROM siger.v_titulo_sai ts
    LEFT JOIN siger.concesionario c ON btrim(c.ucp_concnum) = ts.ucp_concnum
),
ref AS (
    SELECT DISTINCT ON (clave_prestador)
        clave_prestador,
        thsecuencial  AS thsecuencial_referencia,
        contrato_key  AS contrato_referencia,
        idsth         AS idsth_referencia
    FROM t
    WHERE es_vigente AND con_tomo_foja
    ORDER BY clave_prestador, thfechavig DESC NULLS LAST, thsecuencial DESC
)
SELECT
    t.clave_prestador,
    MAX(t.ruc_resuelto)                                               AS ruc_resuelto,
    string_agg(DISTINCT t.ruc_origen, ',' ORDER BY t.ruc_origen)      AS ruc_origen,
    COALESCE(bool_or(t.ruc_origen = 'cedula_001'), false)             AS algun_ruc_por_cedula_001,
    array_agg(DISTINCT t.ucp_concnum ORDER BY t.ucp_concnum)          AS ucp_concnums,
    string_agg(DISTINCT t.nombres, ' | ' ORDER BY t.nombres)          AS nombres,
    bool_or(t.es_vigente)                                             AS tiene_sai_vigente,
    COUNT(*)                                                          AS titulos_sai,
    COUNT(*) FILTER (WHERE t.es_vigente)                              AS titulos_sai_vigentes,
    array_agg(DISTINCT t.idsth ORDER BY t.idsth) FILTER (WHERE t.es_vigente) AS idsth_vigentes,
    MAX(t.thfechavig) FILTER (WHERE t.es_vigente)                     AS vigencia_max,
    ref.thsecuencial_referencia,
    ref.contrato_referencia,
    ref.idsth_referencia,
    -- Anomalías (§3.8)
    COALESCE(COUNT(DISTINCT t.thfechavig) FILTER (WHERE t.es_vigente) > 1, false) AS anom_vigencias_distintas,
    COALESCE(bool_or(t.es_vigente) AND NOT bool_or(t.es_vigente AND t.con_tomo_foja), false)
                                                                      AS anom_solo_sin_tomo_foja,
    (COUNT(*) FILTER (WHERE t.es_vigente AND t.con_tomo_foja) > 1)    AS anom_varios_con_tomo_foja
FROM t
LEFT JOIN ref ON ref.clave_prestador = t.clave_prestador
GROUP BY t.clave_prestador, ref.thsecuencial_referencia, ref.contrato_referencia, ref.idsth_referencia;

COMMENT ON VIEW siger.v_prestador_sai IS
'Una fila por RUC resuelto con al menos un título SAI (cualquier estado). tiene_sai_vigente = algún título SAI con THESTADO VIGENTE. vigencia_max = MAX(THFECHAVIG) de los vigentes. Título de referencia = vigente con tomo-foja de mayor THFECHAVIG. algun_ruc_por_cedula_001 permite filtrar los RUC deducidos de la cédula. Banderas anom_* marcan, no corrigen.';

-- Facturación enlazada a contrato: una fila por fila de facturación (sin
-- multiplicar filas: un contrato puede tener varios títulos). Nivel
-- CONTRATO, no se mezcla con el nivel título de v_prestador_sai.
-- cliente_coincide (solo TOMO_FOJA): algún título de ese contrato tiene
-- UCP_CONCNUM = CLIENT_CODE. false = posible cesión o error; no se filtra.
CREATE OR REPLACE VIEW siger.v_facturacion_contrato AS
SELECT
    f.*,
    (COALESCE(f.eliminado, false) = false) AS activo,
    CASE WHEN f.tipo_enlace = 'TOMO_FOJA' THEN EXISTS (
        SELECT 1
        FROM siger.titulo_habilitante t
        WHERE upper(t.contrato_key) = upper(f.contrato_key)
          AND btrim(t.ucp_concnum) = btrim(f.client_code)
    ) END                                  AS cliente_coincide
FROM siger.facturacion_espectro f;

COMMENT ON VIEW siger.v_facturacion_contrato IS
'Facturación de espectro con activo (ELIMINADO NULL o 0) y cliente_coincide (solo para tipo_enlace TOMO_FOJA: CLIENT_CODE = UCP_CONCNUM de algún título del contrato). No filtra nada.';

-- Concesionarios sin datos de contacto: lo único de siger.concesionario que
-- ve mart_user. (Ubicación y tipo de concesionario no se pueden incluir:
-- SIGER deniega esas columnas.)
CREATE OR REPLACE VIEW siger.v_concesionario_basico AS
SELECT
    btrim(c.ucp_concnum) AS ucp_concnum,
    c.nombres,
    c.ruc_resuelto,
    c.ruc_origen
FROM siger.concesionario c;

COMMENT ON VIEW siger.v_concesionario_basico IS
'Proyección mínima de siger.concesionario para mart_user (LOPDP): código, nombre, RUC resuelto y su origen. Sin cédula ni RUC crudos.';

-- ----------------------------------------------------------------------------
-- 7. Permisos (LOPDP)
-- ----------------------------------------------------------------------------
-- mart_user recibe SELECT automático sobre toda tabla/vista nueva de
-- siger_user en siger (ALTER DEFAULT PRIVILEGES, sql/11_roles_siger.sql).
-- siger.concesionario es la excepción: datos personales -> se revoca, en
-- cada corrida (idempotente). Los GRANT explícitos de las vistas refuerzan
-- el default privilege por si la vista existía antes de configurarlo.
-- Ningún rol del dashboard recibe nada aquí (validar_siger lo verifica).
REVOKE ALL ON siger.concesionario FROM mart_user;
GRANT SELECT ON siger.v_concesionario_basico TO mart_user;
GRANT SELECT ON siger.v_titulo_sai           TO mart_user;
GRANT SELECT ON siger.v_prestador_sai        TO mart_user;
GRANT SELECT ON siger.v_facturacion_contrato TO mart_user;
