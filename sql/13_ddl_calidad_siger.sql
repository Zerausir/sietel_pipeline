-- ============================================================================
-- sql/13_ddl_calidad_siger.sql
-- Hallazgos del cruce SIGER (títulos SAI vigentes) <-> OBTEL (prestadores
-- de SIETEL), con workflow de revisión humana persistente. Corre como
-- mart_user (dueño de calidad), aplicado por siger/construir_cruce_obtel.py
-- (tarea construir_cruce_obtel de dags/siger_pipeline.py) en cada corrida.
--
-- Mismo patrón que calidad.conflictos_ruc_peva (sql/04_ddl_calidad.sql): es
-- una TABLA, no una vista, porque guarda decisiones humanas (estado_revision,
-- revisado_por, notas_revision, fecha_revision) que NUNCA se pisan en las
-- corridas siguientes. El cruce no corrige nada: solo registra.
--
-- Llave: (tipo_hallazgo, ruc_limpio), con ruc_limpio = la MISMA
-- normalización que usa mart/detectar_conflictos_peva.py (SQL_RUC_LIMPIO).
-- Un hallazgo que deja de detectarse NO se borra (conserva su revisión):
-- queda con sigue_detectado = false.
--
-- Solo snapshot de RUC/nombre/códigos: ningún teléfono, correo ni dirección
-- (SIGER ni siquiera los deja leer). calidad_lector y eda_lector la ven por
-- los default privileges de calidad (sql/04_ddl_calidad.sql, sql/05_roles_eda.sql).
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'calidad') THEN
        RAISE EXCEPTION 'El esquema calidad no existe -- aplicar sql/04_ddl_calidad.sql primero (sietel_mart_pipeline).';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'calidad_revisor') THEN
        RAISE EXCEPTION 'El rol calidad_revisor no existe -- ver Creación de roles y usuarios de PostgreSQL.docx';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS calidad.hallazgos_siger_obtel (
    id                       BIGSERIAL PRIMARY KEY,

    tipo_hallazgo            VARCHAR(30) NOT NULL
        CHECK (tipo_hallazgo IN (
            -- RUC con título SAI vigente en SIGER sin ningún PEVA vigente en OBTEL
            'SIGER_SAI_SIN_OBTEL',
            -- prestador que reporta en OBTEL sin título SAI vigente en SIGER
            'OBTEL_SIN_SAI_VIGENTE'
        )),
    ruc_limpio               VARCHAR(20) NOT NULL,
    detalle                  VARCHAR(30) NOT NULL
        CHECK (detalle IN (
            'SIN_PEVA_EN_OBTEL',        -- SIGER_SAI_SIN_OBTEL
            'RUC_NO_EXISTE_EN_SIGER',   -- OBTEL_SIN_SAI_VIGENTE: ningún concesionario con ese RUC
            'SIN_TITULO_SAI',           -- OBTEL_SIN_SAI_VIGENTE: concesionario sin títulos SAI
            'SAI_NO_VIGENTE'            -- OBTEL_SIN_SAI_VIGENTE: títulos SAI, ninguno vigente
        )),

    -- Snapshot de SIGER (informativo, se actualiza en cada corrida)
    -- ruc_por_cedula_001: el RUC de SIGER se dedujo de la cédula (+ '001'),
    -- no venía como RUC -- permite filtrar esos casos.
    ruc_por_cedula_001       BOOLEAN NOT NULL DEFAULT false,
    nombres_siger            TEXT,
    ucp_concnums             TEXT,
    titulos_sai_vigentes     INTEGER,
    idsth_vigentes           TEXT,
    vigencia_max             TIMESTAMP,
    contrato_referencia      TEXT,

    -- Snapshot de OBTEL (analitico.v_ultimo_periodo_reportado_detalle)
    pevas_obtel              TEXT,
    isp_nombre_obtel         TEXT,
    reporta_en_obtel         BOOLEAN,
    ultimo_anio_obtel        INTEGER,
    -- OBTEL no aplica la regla cédula + '001': un isp_ruc de 10 dígitos en
    -- SIETEL aparece aquí como hallazgo; esta columna lo deja ver.
    longitud_ruc_obtel       INTEGER,

    sigue_detectado          BOOLEAN NOT NULL DEFAULT true,

    -- ── Workflow humano -- NUNCA se sobreescribe en corridas posteriores ──
    estado_revision          VARCHAR(30) NOT NULL DEFAULT 'PENDIENTE'
        CHECK (estado_revision IN ('PENDIENTE', 'CONFIRMADO_MANUAL', 'DESCARTADO_MANUAL')),
    revisado_por             VARCHAR(100),
    notas_revision           TEXT,
    fecha_revision           TIMESTAMP,

    fecha_deteccion          TIMESTAMP NOT NULL DEFAULT now(),
    fecha_ultima_deteccion   TIMESTAMP NOT NULL DEFAULT now(),

    UNIQUE (tipo_hallazgo, ruc_limpio)
);

-- Mismo motivo que en sql/04_ddl_calidad.sql (incidente 07-ago-2026): si
-- alguna vez se aplicara como postgres, mart_user debe seguir siendo dueño.
ALTER TABLE calidad.hallazgos_siger_obtel OWNER TO mart_user;

COMMENT ON TABLE calidad.hallazgos_siger_obtel IS
'Cruce SIGER (títulos SAI vigentes, siger.v_prestador_sai) vs OBTEL (prestadores de SIETEL, analitico.v_ultimo_periodo_reportado_detalle) por ruc_limpio (misma normalización que mart/detectar_conflictos_peva.py). Recalculado en cada corrida de siger_pipeline via UPSERT (siger/construir_cruce_obtel.py): las columnas de workflow se preservan; lo que deja de detectarse queda con sigue_detectado = false. No corrige nada.';

CREATE INDEX IF NOT EXISTS ix_hallazgos_siger_obtel_estado
    ON calidad.hallazgos_siger_obtel (estado_revision);
CREATE INDEX IF NOT EXISTS ix_hallazgos_siger_obtel_tipo
    ON calidad.hallazgos_siger_obtel (tipo_hallazgo, detalle) WHERE sigue_detectado;

-- calidad_lector ya ve la tabla por el ALTER DEFAULT PRIVILEGES de
-- sql/04_ddl_calidad.sql. El UPDATE por columna del revisor NO se hereda
-- por default privileges: se otorga explícito (igual que en 04).
GRANT UPDATE (estado_revision, revisado_por, notas_revision, fecha_revision)
    ON calidad.hallazgos_siger_obtel TO calidad_revisor;
