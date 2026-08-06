-- ============================================================================
-- sql/04_ddl_calidad.sql
-- Esquema de calidad de datos: hallazgos de conflictos RUC/PEVA, con workflow
-- de revisión persistente. Corre como mart_user (mismo dueño que capa2/mart).
--
-- POR QUÉ ES UN ESQUEMA APARTE Y NO UNA VISTA DENTRO DE mart:
-- mart es reconstruible desde cero en cada refresco (DROP CASCADE + CREATE).
-- calidad.conflictos_ruc_peva NO puede perder datos en un refresco -- ahí
-- vive el trabajo humano de revisión (quién confirmó qué, y por qué). Por
-- eso es una TABLA persistente en su propio esquema, actualizada por UPSERT
-- (mart/detectar_conflictos_peva.py), nunca recreada desde cero.
--
-- SOSTENIBILIDAD: cada vez que se re-detectan conflictos, el UPSERT solo
-- toca las columnas derivadas de los datos de origen (categoria, fechas,
-- nombres, coexistencia). Las columnas de workflow (estado_revision,
-- revisado_por, notas_revision, fecha_revision) SOLO se fijan la primera
-- vez que aparece un par -- nunca se sobreescriben en corridas posteriores.
-- Así, una decisión humana no se pierde ni se resetea cuando vuelve a correr
-- el detector.
--
-- ESTE ARCHIVO YA NO CREA ROLES. La creación de calidad_lector y
-- calidad_revisor (CREATE ROLE + contraseña) se hace por línea de comandos,
-- directamente en la VM -- documentado en
-- "Creación de roles y usuarios de PostgreSQL — sietel_pipeline.docx".
-- Este archivo asume que ambos roles YA EXISTEN, y falla con un error claro
-- si no es así.
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'calidad_lector') THEN
        RAISE EXCEPTION 'El rol calidad_lector no existe. Créalo primero por línea de comandos -- ver Creación de roles y usuarios de PostgreSQL.docx';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'calidad_revisor') THEN
        RAISE EXCEPTION 'El rol calidad_revisor no existe. Créalo primero por línea de comandos -- ver Creación de roles y usuarios de PostgreSQL.docx';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mart_user') THEN
        RAISE EXCEPTION 'El rol mart_user no existe. Corre sql/00_roles_mart.sql primero.';
    END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS calidad;

-- mart_user necesita leer las vistas fuente de sietel_pipeline para poder
-- detectar los conflictos -- esto lo otorga sietel_user (dueño de analitico),
-- NO mart_user sobre sí mismo. Ejecutar como sietel_user o superusuario:
--
--   GRANT USAGE ON SCHEMA analitico TO mart_user;
--   GRANT SELECT ON analitico.v_ultimo_periodo_reportado_detalle TO mart_user;
--   GRANT SELECT ON analitico.v_lineas_dedicadas_resumen TO mart_user;
--
-- Sin este GRANT, mart/detectar_conflictos_peva.py falla por permisos --
-- confirmar que se aplicó antes de correr el script por primera vez.

CREATE TABLE IF NOT EXISTS calidad.conflictos_ruc_peva (
    id                      BIGSERIAL PRIMARY KEY,

    ruc_limpio              VARCHAR(20)  NOT NULL,
    peva_a                  VARCHAR(50)  NOT NULL,
    peva_b                  VARCHAR(50)  NOT NULL,

    -- Snapshot de los datos de origen en la última detección -- se
    -- actualiza en cada corrida, es informativo, no es workflow.
    isp_nombre_a            TEXT,
    isp_nombre_b            TEXT,
    opera_a                 VARCHAR(50),
    opera_b                 VARCHAR(50),
    fecha_permiso_a         DATE,
    fecha_permiso_b         DATE,

    -- Clasificación automática (ver mart/detectar_conflictos_peva.py):
    --   A_DUPLICADO_MIGRACION_CODIFICACION -- mismo isp_nombre, un lado con
    --       codificación heredada de "opera" (SI/NO/-), el otro categórica.
    --       Resolución automática: se descarta el PEVA con codificación
    --       heredada, se conserva el categórico. Confiable -- confirmado
    --       con 6 casos reales revisados manualmente (28-jul-2026).
    --   B_SECUENCIA_MISMO_TITULAR -- mismo isp_nombre, ambos con
    --       codificación categórica, fechas de permiso distintas. Requiere
    --       verificar si coexisten reportando en el mismo período.
    --   C_NOMBRES_DISTINTOS_MISMO_RUC -- isp_nombre distinto en cada PEVA
    --       bajo el mismo RUC. Sin regla automática posible -- siempre va
    --       a revisión manual.
    categoria               VARCHAR(50) NOT NULL
        CHECK (categoria IN (
            'A_DUPLICADO_MIGRACION_CODIFICACION',
            'B_SECUENCIA_MISMO_TITULAR',
            'C_NOMBRES_DISTINTOS_MISMO_RUC'
        )),

    -- Solo aplica a categoria A: cuál de los dos PEVA se excluye de
    -- capa2.lineas_dedicadas_consolidado por tener codificación heredada.
    peva_legado_descartado  VARCHAR(50),

    -- Solo relevante para categoria B: si alguna vez ambos PEVA reportaron
    -- en el mismo (anio, periodoNumero). Si es false, no hay conflicto real
    -- que resolver -- nunca compiten por el mismo período.
    coexisten_en_periodo    BOOLEAN NOT NULL DEFAULT false,

    accion_recomendada      VARCHAR(50) NOT NULL
        CHECK (accion_recomendada IN (
            'DESCARTAR_LEGADO',
            'SIN_CONFLICTO_NO_COEXISTEN',
            'REVISION_MANUAL_SIETEL'
        )),

    -- ── Workflow humano -- NUNCA se sobreescribe en corridas posteriores ──
    estado_revision         VARCHAR(30) NOT NULL DEFAULT 'PENDIENTE'
        CHECK (estado_revision IN (
            'PENDIENTE', 'CONFIRMADO_AUTOMATICO', 'CONFIRMADO_MANUAL', 'DESCARTADO_MANUAL'
        )),
    revisado_por            VARCHAR(100),
    notas_revision          TEXT,
    fecha_revision          TIMESTAMP,

    fecha_deteccion         TIMESTAMP NOT NULL DEFAULT now(),
    fecha_ultima_deteccion  TIMESTAMP NOT NULL DEFAULT now(),

    UNIQUE (ruc_limpio, peva_a, peva_b)
);

COMMENT ON TABLE calidad.conflictos_ruc_peva IS
'Hallazgos de RUC con múltiples PEVA en conflicto. Recalculado en cada refresco de mart via UPSERT (mart/detectar_conflictos_peva.py) -- las columnas de workflow (estado_revision, revisado_por, notas_revision, fecha_revision) se preservan entre corridas y solo las edita una persona, nunca el script automático tras la primera detección.';

CREATE INDEX IF NOT EXISTS ix_conflictos_ruc_peva_estado
    ON calidad.conflictos_ruc_peva (estado_revision);

CREATE INDEX IF NOT EXISTS ix_conflictos_ruc_peva_categoria
    ON calidad.conflictos_ruc_peva (categoria);

-- Vista de conveniencia: qué PEVA deben excluirse de capa2 por ser el lado
-- legado de un duplicado ya confirmado -- la consume construir_capa2.py.
CREATE OR REPLACE VIEW calidad.vw_pevas_excluidos AS
SELECT
    peva_legado_descartado AS peva_codigo,
    ruc_limpio,
    categoria,
    estado_revision
FROM calidad.conflictos_ruc_peva
WHERE categoria = 'A_DUPLICADO_MIGRACION_CODIFICACION'
  AND estado_revision IN ('CONFIRMADO_AUTOMATICO', 'CONFIRMADO_MANUAL')
  AND peva_legado_descartado IS NOT NULL;

-- ============================================================================
-- PERMISOS de los roles del dashboard de consistencia (ya deben existir)
-- ============================================================================

-- Lector: ve todo, para las gráficas/tablas del dashboard de consistencia.
GRANT USAGE ON SCHEMA calidad TO calidad_lector;
GRANT SELECT ON ALL TABLES IN SCHEMA calidad TO calidad_lector;
ALTER DEFAULT PRIVILEGES FOR ROLE mart_user IN SCHEMA calidad
    GRANT SELECT ON TABLES TO calidad_lector;

-- Revisor: lee todo, pero SOLO puede escribir las columnas de workflow --
-- no puede tocar categoria, accion_recomendada ni ningún campo derivado de
-- los datos de origen. Privilegio a nivel de columna, no de tabla completa.
GRANT USAGE ON SCHEMA calidad TO calidad_revisor;
GRANT SELECT ON ALL TABLES IN SCHEMA calidad TO calidad_revisor;
GRANT UPDATE (estado_revision, revisado_por, notas_revision, fecha_revision)
    ON calidad.conflictos_ruc_peva TO calidad_revisor;
ALTER DEFAULT PRIVILEGES FOR ROLE mart_user IN SCHEMA calidad
    GRANT SELECT ON TABLES TO calidad_revisor;

-- ============================================================================
-- DISCREPANCIAS DE GEOGRAFÍA DE NODO ISP -- 06-ago-2026
-- ============================================================================
-- Mismo patrón de workflow persistente que calidad.conflictos_ruc_peva (ver
-- comentario al inicio del archivo) -- la única diferencia estructural es la
-- llave natural: una fila por NODO (noisp_codigo), no por par de PEVA.
--
-- Alcance deliberadamente ACOTADO: esta tabla solo registra nodos donde el
-- cruce espacial SÍ pudo calcularse (coordenada válida) pero la parroquia
-- derivada de la coordenada no coincide con la parroquia reportada en
-- SIETEL. Los nodos con coordenada inválida/no convertible (ver
-- capa2.nodo_isp_geocodificado.es_coordenada_valida) son un problema
-- distinto -- "no sé dónde está" vs. "sé dónde está y no coincide" -- y no
-- se mezclan en la misma cola de revisión humana.
--
-- Poblada por mart/detectar_discrepancias_geografia_nodo.py (Parte B del
-- geoprocesamiento de nodos ISP, pendiente del shapefile CONALI
-- ORGANIZACION_TERRITORIAL_PARROQUIAL -- ver conversación 06-ago-2026).
CREATE TABLE IF NOT EXISTS calidad.discrepancias_geografia_nodo (
    id                          BIGSERIAL PRIMARY KEY,

    noisp_codigo                VARCHAR(50) NOT NULL UNIQUE,
    peva_codigo                 VARCHAR(50) NOT NULL,

    -- Snapshot informativo, actualizado en cada corrida -- no es workflow.
    isp_nombre                  TEXT,
    noisp_nombre                VARCHAR(50),
    tiponodo                     VARCHAR(50),
    latitud_decimal              DOUBLE PRECISION NOT NULL,
    longitud_decimal             DOUBLE PRECISION NOT NULL,

    -- Geografía REPORTADA en SIETEL (dbo.NodoISP.par_codigo -> dbo.Parroquia).
    par_codigo_reportado         VARCHAR(50),
    parroquia_reportada_nombre   VARCHAR(100),
    canton_reportado_nombre      VARCHAR(50),
    provincia_reportada_nombre   VARCHAR(50),

    -- Geografía DERIVADA de la coordenada (shapefile CONALI, punto-en-polígono).
    codigo_parroquia_derivado    VARCHAR(50) NOT NULL,
    parroquia_derivada_nombre    VARCHAR(100) NOT NULL,
    codigo_canton_derivado       VARCHAR(50) NOT NULL,
    canton_derivado_nombre       VARCHAR(100) NOT NULL,
    codigo_provincia_derivado    VARCHAR(50) NOT NULL,
    provincia_derivada_nombre    VARCHAR(100) NOT NULL,

    -- ── Workflow humano -- NUNCA se sobreescribe en corridas posteriores ──
    estado_revision              VARCHAR(30) NOT NULL DEFAULT 'PENDIENTE'
        CHECK (estado_revision IN (
            'PENDIENTE', 'CONFIRMADO_DISCREPANCIA', 'DESCARTADO_MANUAL'
        )),
    revisado_por                 VARCHAR(100),
    notas_revision                TEXT,
    fecha_revision                TIMESTAMP,

    fecha_deteccion               TIMESTAMP NOT NULL DEFAULT now(),
    fecha_ultima_deteccion        TIMESTAMP NOT NULL DEFAULT now()
);

COMMENT ON TABLE calidad.discrepancias_geografia_nodo IS
'Nodos ISP donde la parroquia derivada de latitud/longitud (shapefile CONALI, punto-en-poligono) no coincide con la parroquia reportada en SIETEL. Recalculado en cada refresco via UPSERT (mart/detectar_discrepancias_geografia_nodo.py, Parte B, pendiente del shapefile) -- columnas de workflow preservadas entre corridas, igual que calidad.conflictos_ruc_peva. No incluye nodos con coordenada invalida (ver capa2.nodo_isp_geocodificado.es_coordenada_valida) -- causa raiz distinta.';

CREATE INDEX IF NOT EXISTS ix_discrepancias_geografia_nodo_estado
    ON calidad.discrepancias_geografia_nodo (estado_revision);

CREATE INDEX IF NOT EXISTS ix_discrepancias_geografia_nodo_peva
    ON calidad.discrepancias_geografia_nodo (peva_codigo);

-- Mismo patrón de permisos que conflictos_ruc_peva: calidad_lector ve todo
-- (ya cubierto por el ALTER DEFAULT PRIVILEGES general de arriba, que
-- aplica a CUALQUIER tabla futura de mart_user en el esquema calidad).
-- calidad_revisor necesita el UPDATE de columnas explícito de nuevo aquí --
-- a diferencia de SELECT, un privilegio a nivel de columna NO se hereda vía
-- ALTER DEFAULT PRIVILEGES a una tabla nueva.
GRANT UPDATE (estado_revision, revisado_por, notas_revision, fecha_revision)
    ON calidad.discrepancias_geografia_nodo TO calidad_revisor;