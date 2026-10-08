"""
siger/construir_cruce_obtel.py — Cruce SIGER (títulos SAI vigentes) <-> OBTEL
(prestadores de SIETEL) como hallazgos de calidad revisables, en
calidad.hallazgos_siger_obtel. Corre como mart_user (dueño de calidad).

Reutiliza, sin copiarlas:
  - SQL_RUC_LIMPIO y _engine() de mart/detectar_conflictos_peva.py: la MISMA
    normalización de RUC (solo dígitos) y la misma conexión de mart_user;
  - _aplicar_archivo() de mart/aplicar_capa3.py para aplicar
    sql/13_ddl_calidad_siger.sql (idempotente).

Lados del cruce (por ruc_limpio):
  SIGER -> siger.v_prestador_sai (RUC con algún título SAI vigente) y
           siger.v_concesionario_basico (si el RUC existe en SIGER, y si se
           dedujo de la cédula: ruc_por_cedula_001).
  OBTEL -> analitico.v_ultimo_periodo_reportado_detalle.isp_ruc, el mismo
           campo y el mismo filtro de "prueba" que detectar_conflictos_peva.py,
           colapsado a una fila por PEVA.
Hallazgos:
  SIGER_SAI_SIN_OBTEL   -- RUC con SAI vigente en SIGER sin ningún PEVA vigente en OBTEL.
  OBTEL_SIN_SAI_VIGENTE -- RUC de un prestador que REPORTA en OBTEL sin SAI
                           vigente en SIGER (detalle: RUC_NO_EXISTE_EN_SIGER,
                           SIN_TITULO_SAI o SAI_NO_VIGENTE).
No corrige nada. UPSERT que preserva el workflow humano; lo que deja de
detectarse queda con sigue_detectado = false.

En la misma transacción reemplaza calidad.conciliacion_siger_obtel (08-oct-
2026): una fila por RUC con lo que COINCIDE y lo que no en nombre, estado y
reporte (siger/conciliacion.py). La lee el dashboard vía
mart.vw_conciliacion_siger_obtel.

Uso:
    python construir_cruce_obtel.py            # recalcula y escribe
    python construir_cruce_obtel.py --dry-run  # recalcula, reporta y hace ROLLBACK
"""
import argparse
import logging
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mart"))

from sqlalchemy import text  # noqa: E402

from aplicar_capa3 import _aplicar_archivo  # noqa: E402
from conciliacion import SQL_OBTEL, SQL_SIGER_CONC, SQL_SIGER_TITULOS, construir_filas  # noqa: E402
from detectar_conflictos_peva import SQL_RUC_LIMPIO, _engine  # noqa: E402

logger = logging.getLogger(__name__)

RUTA_SQL = Path(__file__).resolve().parent.parent / "sql" / "13_ddl_calidad_siger.sql"


def _rl(col: str) -> str:
    return SQL_RUC_LIMPIO.format(col=col)


SQL_MARCAR_NO_DETECTADOS = "UPDATE calidad.hallazgos_siger_obtel SET sigue_detectado = false WHERE sigue_detectado"

SQL_UPSERT_HALLAZGOS = f"""
WITH obtel AS (
    -- Una fila por PEVA (la vista tiene una por geografía/tipo de enlace del
    -- último período) -- mismo colapso y filtro que detectar_conflictos_peva.py.
    SELECT DISTINCT ON (v.peva_codigo)
        {_rl("v.isp_ruc")} AS ruc_limpio,
        v.peva_codigo,
        v.isp_nombre,
        v.tiene_reportes,
        v.ultimo_anio
    FROM analitico.v_ultimo_periodo_reportado_detalle v
    WHERE v.peva_codigo IS NOT NULL
      AND COALESCE(v.isp_nombre::text, '') NOT ILIKE '%prueba%'
      AND COALESCE(v.nombreComercial::text, '') NOT ILIKE '%prueba%'
    ORDER BY v.peva_codigo, v.ultimo_anio DESC NULLS LAST, v.ultimo_periodo_numero DESC NULLS LAST
),
obtel_ruc AS (
    SELECT
        ruc_limpio,
        string_agg(DISTINCT peva_codigo, ', ' ORDER BY peva_codigo)  AS pevas,
        string_agg(DISTINCT isp_nombre, ' | ' ORDER BY isp_nombre)   AS isp_nombre,
        bool_or(tiene_reportes)                                      AS reporta,
        MAX(ultimo_anio)                                             AS ultimo_anio,
        MAX(length(ruc_limpio))                                      AS longitud
    FROM obtel
    WHERE ruc_limpio IS NOT NULL
    GROUP BY ruc_limpio
),
siger_conc AS (
    SELECT
        {_rl("c.ruc_resuelto")}                                       AS ruc_limpio,
        bool_or(c.ruc_origen = 'cedula_001')                          AS por_cedula,
        string_agg(DISTINCT c.nombres, ' | ' ORDER BY c.nombres)      AS nombres,
        string_agg(DISTINCT c.ucp_concnum, ', ' ORDER BY c.ucp_concnum) AS concnums
    FROM siger.v_concesionario_basico c
    WHERE c.ruc_resuelto IS NOT NULL
    GROUP BY 1
),
siger_sai AS (
    SELECT
        {_rl("p.ruc_resuelto")}                      AS ruc_limpio,
        p.tiene_sai_vigente,
        p.titulos_sai_vigentes,
        array_to_string(p.idsth_vigentes, ',')       AS idsth_vigentes,
        p.vigencia_max,
        p.contrato_referencia
    FROM siger.v_prestador_sai p
    WHERE p.ruc_resuelto IS NOT NULL
),
hallazgos AS (
    SELECT 'SIGER_SAI_SIN_OBTEL' AS tipo_hallazgo, s.ruc_limpio, 'SIN_PEVA_EN_OBTEL' AS detalle
    FROM siger_sai s
    WHERE s.tiene_sai_vigente
      AND NOT EXISTS (SELECT 1 FROM obtel_ruc o WHERE o.ruc_limpio = s.ruc_limpio)
    UNION ALL
    SELECT 'OBTEL_SIN_SAI_VIGENTE', o.ruc_limpio,
           CASE
               WHEN NOT EXISTS (SELECT 1 FROM siger_conc c WHERE c.ruc_limpio = o.ruc_limpio)
                   THEN 'RUC_NO_EXISTE_EN_SIGER'
               WHEN EXISTS (SELECT 1 FROM siger_sai s WHERE s.ruc_limpio = o.ruc_limpio)
                   THEN 'SAI_NO_VIGENTE'
               ELSE 'SIN_TITULO_SAI'
           END
    FROM obtel_ruc o
    WHERE o.reporta
      AND NOT EXISTS (SELECT 1 FROM siger_sai s WHERE s.ruc_limpio = o.ruc_limpio AND s.tiene_sai_vigente)
)
INSERT INTO calidad.hallazgos_siger_obtel (
    tipo_hallazgo, ruc_limpio, detalle,
    ruc_por_cedula_001, nombres_siger, ucp_concnums,
    titulos_sai_vigentes, idsth_vigentes, vigencia_max, contrato_referencia,
    pevas_obtel, isp_nombre_obtel, reporta_en_obtel, ultimo_anio_obtel, longitud_ruc_obtel,
    sigue_detectado, fecha_deteccion, fecha_ultima_deteccion
)
SELECT
    h.tipo_hallazgo, h.ruc_limpio, h.detalle,
    COALESCE(c.por_cedula, false), c.nombres, c.concnums,
    s.titulos_sai_vigentes, s.idsth_vigentes, s.vigencia_max, s.contrato_referencia,
    o.pevas, o.isp_nombre, o.reporta, o.ultimo_anio, o.longitud,
    true, now(), now()
FROM hallazgos h
LEFT JOIN siger_conc c ON c.ruc_limpio = h.ruc_limpio
LEFT JOIN siger_sai  s ON s.ruc_limpio = h.ruc_limpio
LEFT JOIN obtel_ruc  o ON o.ruc_limpio = h.ruc_limpio
ON CONFLICT (tipo_hallazgo, ruc_limpio) DO UPDATE SET
    detalle                = EXCLUDED.detalle,
    ruc_por_cedula_001     = EXCLUDED.ruc_por_cedula_001,
    nombres_siger          = EXCLUDED.nombres_siger,
    ucp_concnums           = EXCLUDED.ucp_concnums,
    titulos_sai_vigentes   = EXCLUDED.titulos_sai_vigentes,
    idsth_vigentes         = EXCLUDED.idsth_vigentes,
    vigencia_max           = EXCLUDED.vigencia_max,
    contrato_referencia    = EXCLUDED.contrato_referencia,
    pevas_obtel            = EXCLUDED.pevas_obtel,
    isp_nombre_obtel       = EXCLUDED.isp_nombre_obtel,
    reporta_en_obtel       = EXCLUDED.reporta_en_obtel,
    ultimo_anio_obtel      = EXCLUDED.ultimo_anio_obtel,
    longitud_ruc_obtel     = EXCLUDED.longitud_ruc_obtel,
    sigue_detectado        = true,
    fecha_ultima_deteccion = now()
    -- estado_revision, revisado_por, notas_revision, fecha_revision: NUNCA
    -- se tocan aquí (decisión humana, ver sql/13_ddl_calidad_siger.sql).
"""

SQL_RESUMEN = """
SELECT tipo_hallazgo, detalle, COUNT(*) AS n,
       COUNT(*) FILTER (WHERE ruc_por_cedula_001) AS por_cedula_001,
       COUNT(*) FILTER (WHERE estado_revision <> 'PENDIENTE') AS revisados
FROM calidad.hallazgos_siger_obtel
WHERE sigue_detectado
GROUP BY tipo_hallazgo, detalle
ORDER BY tipo_hallazgo, detalle
"""


COLUMNAS_CONCILIACION = [
    "ruc_limpio", "categoria", "en_sietel", "en_siger", "nombre_sietel", "nombre_siger",
    "similitud_nombre", "nivel_nombre", "pevas_sietel", "opera_sietel", "estado_sietel",
    "reporta_sietel", "ultimo_periodo_sietel", "ucp_concnums", "ruc_por_cedula_001",
    "estado_siger", "estados_siger", "idsth_siger", "vigencia_siger", "titulos_sai",
    "coincide_estado", "coincide_reporte",
]

SQL_INSERT_CONCILIACION = (
    f"INSERT INTO calidad.conciliacion_siger_obtel ({', '.join(COLUMNAS_CONCILIACION)}) "
    f"VALUES ({', '.join(':' + c for c in COLUMNAS_CONCILIACION)})"
)


def _reemplazar_conciliacion(conn) -> Counter:
    """Recalcula la conciliación completa y reemplaza la tabla (sin COMMIT)."""
    def leer(sql):
        return [dict(r) for r in conn.execute(text(sql)).mappings().all()]

    filas = construir_filas(leer(SQL_OBTEL), leer(SQL_SIGER_CONC), leer(SQL_SIGER_TITULOS))
    conn.execute(text("DELETE FROM calidad.conciliacion_siger_obtel"))
    if filas:
        conn.execute(text(SQL_INSERT_CONCILIACION), filas)
    return Counter(f["categoria"] for f in filas)


def construir_cruce_obtel(dry_run: bool = False) -> list[dict]:
    """
    Aplica el DDL (idempotente) y recalcula los hallazgos en una sola
    transacción. Protección: si cualquiera de los dos lados está vacío
    (siger sin cargar, o analitico recién borrado por CASCADE) se aborta en
    vez de marcar todo como hallazgo.
    """
    _aplicar_archivo(RUTA_SQL)
    engine = _engine()
    with engine.connect() as conn:
        n_sai = conn.execute(text(
            "SELECT COUNT(*) FROM siger.v_prestador_sai WHERE tiene_sai_vigente")).scalar_one()
        n_obtel = conn.execute(text(
            "SELECT COUNT(*) FROM analitico.v_ultimo_periodo_reportado_detalle")).scalar_one()
        if not n_sai or not n_obtel:
            raise RuntimeError(
                f"Cruce SIGER-OBTEL abortado: {n_sai} prestadores SAI vigentes en siger y {n_obtel} filas "
                f"en analitico.v_ultimo_periodo_reportado_detalle -- uno de los lados está vacío."
            )
        conn.execute(text(SQL_MARCAR_NO_DETECTADOS))
        conn.execute(text(SQL_UPSERT_HALLAZGOS))
        resumen = [dict(r) for r in conn.execute(text(SQL_RESUMEN)).mappings().all()]
        categorias = _reemplazar_conciliacion(conn)
        if dry_run:
            conn.rollback()
        else:
            conn.commit()

    print(f"\n{'=' * 70}\nCRUCE SIGER ↔ OBTEL — calidad.hallazgos_siger_obtel"
          f"{' (DRY-RUN, sin escribir)' if dry_run else ''}\n{'=' * 70}")
    print(f"  {n_sai:,} RUC con SAI vigente en SIGER")
    for r in resumen:
        print(f"  {r['tipo_hallazgo']:<24} {r['detalle']:<24} {r['n']:>6,}  "
              f"(cédula+001: {r['por_cedula_001']}, ya revisados: {r['revisados']})")
    print(f"\n  Conciliación por RUC ({sum(categorias.values()):,} RUC):")
    for categoria, n in categorias.most_common():
        print(f"    {categoria:<26} {n:>6,}")
    logger.info("Cruce SIGER-OBTEL %s: %s; conciliación %s", "simulado" if dry_run else "actualizado",
                resumen, dict(categorias))
    return resumen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="Recalcula y reporta, pero hace ROLLBACK (no escribe hallazgos).")
    args = parser.parse_args(argv)
    construir_cruce_obtel(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
