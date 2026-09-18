-- ============================================================================
-- sql/10_patch_vw_conflictos_ruc_peva.sql
--
-- Parche puntual para aplicar en producción SIN esperar al próximo refresco
-- completo de sietel_mart_pipeline (que haría DROP SCHEMA mart CASCADE +
-- reconstrucción completa -- innecesario y arriesgado solo para este cambio,
-- mismo criterio que los parches 06-09).
--
-- Agrega mart.vw_conflictos_ruc_peva -- primer puente calidad->mart para
-- calidad.conflictos_ruc_peva (categorías A/B/C de conflicto RUC/PEVA, ver
-- sql/04_ddl_calidad.sql). El otro workflow de calidad
-- (calidad.discrepancias_geografia_nodo) ya tiene su puente desde 06-ago-2026
-- (mart.vw_nodos_isp_mapa) -- este parche cierra la misma brecha para
-- conflictos_ruc_peva, que hasta ahora no era visible desde el dashboard.
--
-- MISMA DECISIÓN DE ARQUITECTURA YA CONFIRMADA (06-ago-2026, ver docstring
-- de dashboard/pages/discrepancias_geografia.py): opción A, cero roles
-- nuevos, cero cambios al modelo de permisos de dashboard_lector (que solo
-- tiene SELECT sobre mart.*). calidad_lector/calidad_revisor siguen siendo
-- los únicos roles con acceso directo al esquema calidad -- el dashboard
-- nunca se conecta ahí. Esta vista es SOLO LECTURA: no expone ninguna forma
-- de escribir estado_revision/revisado_por/notas_revision/fecha_revision
-- desde el dashboard -- esa edición sigue ocurriendo fuera de OBTEL, con el
-- rol calidad_revisor, exactamente igual que discrepancias_geografia_nodo.
--
-- SIN GEOGRAFÍA NI TERRITORIO: a diferencia de discrepancias_geografia_nodo
-- (que sí tiene coordenada), un conflicto RUC/PEVA no tiene ubicación propia
-- -- es un hallazgo a nivel de RUC/PEVA, no de nodo físico. La página del
-- dashboard que consume esta vista no debe tener filtro de territorio, mismo
-- límite ya documentado para mart.vw_prestadores_sin_reportar.
--
-- APLICAR: conectado como mart_user (dueño real del esquema mart) --
-- IMPORTANTE, ver el incidente de propiedad ya documentado en el encabezado
-- de sql/04_ddl_calidad.sql: si este archivo se corre con
-- `sudo -u postgres psql -f ...` en vez de conectado como mart_user, la
-- vista queda accesible igual (CREATE VIEW no bloquea lectura por dueño con
-- GRANT explícito), pero rompe la convención de propiedad del resto del
-- esquema -- confirmar con `\dn+ mart` o `\d+ mart.vw_conflictos_ruc_peva`
-- después de aplicar.
--
--   psql -h 192.168.129.50 -U mart_user -d sietel_analitico \
--        -f /tmp/10_patch_vw_conflictos_ruc_peva.sql
--
-- IMPORTANTE: este parche debe reflejarse también en sql/02_ddl_mart.sql
-- para que sobreviva al próximo DROP SCHEMA CASCADE -- ver el snippet e
-- instrucciones de inserción entregados junto a este archivo (va inmediatamente
-- después de CREATE VIEW mart.vw_auditoria_resolucion_peva, sección 15). Este
-- archivo es un atajo operativo, NO reemplaza la fuente de verdad del DDL
-- completo -- mismo criterio que sql/06_patch_vw_prestadores_sin_reportar.sql.
-- ============================================================================

CREATE OR REPLACE VIEW mart.vw_conflictos_ruc_peva AS
SELECT
    id,
    ruc_limpio,
    peva_a,
    peva_b,
    isp_nombre_a,
    isp_nombre_b,
    opera_a,
    opera_b,
    fecha_permiso_a,
    fecha_permiso_b,
    categoria,
    peva_legado_descartado,
    coexisten_en_periodo,
    accion_recomendada,
    estado_revision,
    revisado_por,
    notas_revision,
    fecha_revision,
    fecha_deteccion,
    fecha_ultima_deteccion
FROM calidad.conflictos_ruc_peva;

COMMENT ON VIEW mart.vw_conflictos_ruc_peva IS
'Puente de solo lectura hacia calidad.conflictos_ruc_peva (categorías A/B/C de conflicto RUC/PEVA, ver mart/detectar_conflictos_peva.py). estado_revision/revisado_por/notas_revision/fecha_revision reflejan el workflow humano tal cual está en calidad -- esta vista NO permite editarlos, la edición real ocurre fuera de OBTEL con el rol calidad_revisor. Sin columnas de geografía ni territorio: un conflicto RUC/PEVA no tiene ubicación física propia.';

-- ============================================================================
-- RE-OTORGAR A dashboard_lector -- mismo patrón que los parches 07/08:
-- CREATE OR REPLACE VIEW no toca los GRANT ya existentes sobre el objeto,
-- pero como esta vista es NUEVA (primera vez que se crea), necesita su
-- primer GRANT explícito, igual que cualquier objeto nuevo del esquema mart.
-- ============================================================================
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dashboard_lector') THEN
        GRANT SELECT ON mart.vw_conflictos_ruc_peva TO dashboard_lector;
    END IF;
END $$;

-- Verificación esperada tras aplicar:
--   SELECT categoria, estado_revision, COUNT(*)
--   FROM mart.vw_conflictos_ruc_peva
--   GROUP BY categoria, estado_revision
--   ORDER BY categoria, estado_revision;
--
--   Y confirmar que dashboard_lector puede leerla:
--   psql -h 192.168.129.50 -U dashboard_lector -d sietel_analitico \
--        -c "SELECT COUNT(*) FROM mart.vw_conflictos_ruc_peva;"