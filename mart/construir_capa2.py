"""
mart/construir_capa2.py

Reemplaza a Datos.ipynb. Construye capa2.lineas_dedicadas_consolidado
directamente en sietel_analitico (VM1, mismo host que analitico/mart), sin
salir nunca a una base personal.

CAMBIO METODOLÓGICO DELIBERADO respecto al notebook original (documentado
para revisión de Mercados -- no es una decisión que tome solo, es la que
elimina el riesgo más grave sin necesitar todavía la confirmación completa
del punto pendiente sobre imputación):
  - El notebook original rellenaba (LOCF) desde el último reporte real
    HACIA ADELANTE, indefinidamente, hasta una fecha de corte hardcodeada
    ("2025-12"). Un prestador sin reportar hace 18 meses aparecía con
    datos "vigentes" idénticos a los de hace año y medio, sin ninguna
    bandera de antigüedad, y la fecha de corte quedaba obsoleta apenas
    pasaba un mes.
  - Este script SOLO rellena huecos INTERIORES -- entre el primer y el
    último reporte real de cada combinación (prestador_id, geografia_id).
    NUNCA extrapola más allá del último reporte real: si un prestador no
    ha reportado en los últimos N meses, esos meses simplemente no
    aparecen en capa2 -- no se inventa un valor para lo que no se sabe.
  - Cada fila queda marcada con es_imputado y meses_desde_ultimo_reporte_real,
    visibles para el futuro dashboard de consistencia de datos.
  - Esto NO resuelve, por sí solo, si interpolar huecos interiores es
    aceptable para el uso regulatorio de este dato -- eso lo sigue
    debiendo confirmar Mercados (ver Instrucciones del Proyecto). Lo que
    sí elimina de raíz es el riesgo de proyección indefinida hacia el
    futuro sin ningún límite, que era el problema más grave encontrado.

EXCLUSIONES aplicadas (mismo criterio que sql/02_ddl_mart.sql):
  - Prestadores/PEVA cuyo nombre contenga "prueba".
  - PEVA del Grupo A ya confirmados como duplicado de migración de
    codificación (calidad.vw_pevas_excluidos) -- correr
    mart/detectar_conflictos_peva.py ANTES de este script.

Uso:
    python construir_capa2.py --dry-run   # solo cuenta filas, no escribe
    python construir_capa2.py             # construye/reemplaza capa2.lineas_dedicadas_consolidado
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

load_dotenv()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def _engine():
    url = URL.create(
        drivername="postgresql+psycopg",
        username=_require_env("MART_USER_USER"),
        password=_require_env("MART_USER_PASSWORD"),
        host=_require_env("ANALITICO_PG_HOST"),
        port=int(os.environ.get("ANALITICO_PG_PORT", "5432")),
        database=os.environ.get("ANALITICO_PG_DATABASE", "sietel_analitico"),
    )
    return create_engine(url, connect_args={"connect_timeout": 10})


# Columnas que se transportan como UN SOLO snapshot atómico durante el
# relleno de huecos interiores -- nunca columna por columna de forma
# independiente (mismo principio aplicado en la corrección de
# fact_lineas_geografia_mes en sql/02_ddl_mart.sql).
COLUMNAS_SNAPSHOT = [
    "peva_codigo", "isp_nombre", "opera", "fechapermiso",
    "codigo_provincia", "codigo_ciudad", "codigo_parroquia",
    "pro_nombre", "ciu_nombre", "par_nombre",
    "tipoenlace", "tipocliente", "nivelcomparticion", "portador",
    "total_lineas", "total_usuarios",
    "lineas_dl_sin_datos", "lineas_dl_menos_1mbps", "lineas_dl_1_10mbps",
    "lineas_dl_10_30mbps", "lineas_dl_30_100mbps", "lineas_dl_100mbps_1gbps",
    "lineas_dl_1gbps_o_mas",
    "lineas_ul_sin_datos", "lineas_ul_menos_1mbps", "lineas_ul_1_10mbps",
    "lineas_ul_10_30mbps", "lineas_ul_30_100mbps", "lineas_ul_100mbps_1gbps",
    "lineas_ul_1gbps_o_mas",
    "lineas_dl_banda_ancha", "lineas_dl_ultra_banda_ancha",
]


def _sentencias_construccion() -> list[str]:
    bloque_snapshot = "\n".join(f"    FIRST_VALUE({c}) OVER w AS {c}," for c in COLUMNAS_SNAPSHOT)

    crear_tabla_next = f"""
    CREATE TABLE capa2._lineas_dedicadas_consolidado_next AS
    WITH reportado AS (
        SELECT
            NULLIF(REGEXP_REPLACE(COALESCE(v.isp_ruc::text, ''), '[^0-9]', '', 'g'), '') AS ruc_limpio,
            v.peva_codigo,
            v.par_codigo AS geografia_id,
            MAKE_DATE(v.anio::int, v.periodoNumero::int, 1) AS periodo,
            v.isp_nombre, v.opera, v.fechaPermiso AS fechapermiso,
            v.codigo_provincia, v.codigo_ciudad, v.codigo_parroquia,
            v.pro_nombre, v.ciu_nombre, v.par_nombre,
            v.tipoEnlace AS tipoenlace, v.tipoCliente AS tipocliente,
            v.nivelComparticion AS nivelcomparticion, v.portador,
            v.total_lineas, v.total_usuarios,
            v.lineas_dl_sin_datos, v.lineas_dl_menos_1mbps, v.lineas_dl_1_10mbps,
            v.lineas_dl_10_30mbps, v.lineas_dl_30_100mbps, v.lineas_dl_100mbps_1gbps,
            v.lineas_dl_1gbps_o_mas,
            v.lineas_ul_sin_datos, v.lineas_ul_menos_1mbps, v.lineas_ul_1_10mbps,
            v.lineas_ul_10_30mbps, v.lineas_ul_30_100mbps, v.lineas_ul_100mbps_1gbps,
            v.lineas_ul_1gbps_o_mas,
            v.lineas_dl_banda_ancha, v.lineas_dl_ultra_banda_ancha
        FROM analitico.v_lineas_dedicadas_resumen v
        WHERE COALESCE(v.isp_nombre::text, '') NOT ILIKE '%prueba%'
          AND COALESCE(v.nombreComercial::text, '') NOT ILIKE '%prueba%'
          AND v.peva_codigo NOT IN (SELECT peva_codigo FROM calidad.vw_pevas_excluidos)
    ),
    con_prestador AS (
        SELECT
            COALESCE(ruc_limpio, peva_codigo) AS prestador_id,
            *
        FROM reportado
    ),
    series AS (
        SELECT prestador_id, geografia_id, MIN(periodo) AS periodo_min, MAX(periodo) AS periodo_max
        FROM con_prestador
        GROUP BY prestador_id, geografia_id
    ),
    spine AS (
        SELECT s.prestador_id, s.geografia_id, gs.periodo::date AS periodo
        FROM series s
        CROSS JOIN LATERAL generate_series(s.periodo_min, s.periodo_max, interval '1 month') AS gs(periodo)
    ),
    combinado AS (
        SELECT
            sp.prestador_id,
            sp.geografia_id,
            sp.periodo,
            r.peva_codigo, r.isp_nombre, r.opera, r.fechapermiso,
            r.codigo_provincia, r.codigo_ciudad, r.codigo_parroquia,
            r.pro_nombre, r.ciu_nombre, r.par_nombre,
            r.tipoenlace, r.tipocliente, r.nivelcomparticion, r.portador,
            r.total_lineas, r.total_usuarios,
            r.lineas_dl_sin_datos, r.lineas_dl_menos_1mbps, r.lineas_dl_1_10mbps,
            r.lineas_dl_10_30mbps, r.lineas_dl_30_100mbps, r.lineas_dl_100mbps_1gbps,
            r.lineas_dl_1gbps_o_mas,
            r.lineas_ul_sin_datos, r.lineas_ul_menos_1mbps, r.lineas_ul_1_10mbps,
            r.lineas_ul_10_30mbps, r.lineas_ul_30_100mbps, r.lineas_ul_100mbps_1gbps,
            r.lineas_ul_1gbps_o_mas,
            r.lineas_dl_banda_ancha, r.lineas_dl_ultra_banda_ancha
        FROM spine sp
        LEFT JOIN con_prestador r
          ON r.prestador_id = sp.prestador_id
         AND r.geografia_id = sp.geografia_id
         AND r.periodo = sp.periodo
    ),
    agrupado AS (
        SELECT
            *,
            COUNT(peva_codigo) OVER (
                PARTITION BY prestador_id, geografia_id ORDER BY periodo
            ) AS grupo_carry
        FROM combinado
    )
    SELECT
        prestador_id,
        geografia_id,
        periodo,
{bloque_snapshot}
        (FIRST_VALUE(periodo) OVER w <> periodo) AS es_imputado,
        ((DATE_PART('year', periodo) - DATE_PART('year', FIRST_VALUE(periodo) OVER w)) * 12
            + (DATE_PART('month', periodo) - DATE_PART('month', FIRST_VALUE(periodo) OVER w)))::int
            AS meses_desde_ultimo_reporte_real
    FROM agrupado
    WINDOW w AS (PARTITION BY prestador_id, geografia_id, grupo_carry ORDER BY periodo)
    """

    # Lista de sentencias INDIVIDUALES -- se ejecutan una por una (no todas
    # en un solo execute()) porque el driver psycopg no garantiza soportar
    # múltiples sentencias separadas por ";" en una sola llamada. Todas
    # corren dentro de la MISMA transacción (ver main()), lo que preserva
    # el renombrado atómico: ningún lector externo ve un estado a medias,
    # la tabla vieja sigue respondiendo hasta el COMMIT final.
    return [
        "CREATE SCHEMA IF NOT EXISTS capa2;",
        "DROP TABLE IF EXISTS capa2._lineas_dedicadas_consolidado_next;",
        crear_tabla_next,
        "CREATE INDEX ON capa2._lineas_dedicadas_consolidado_next (prestador_id, geografia_id, periodo);",
        "CREATE INDEX ON capa2._lineas_dedicadas_consolidado_next (periodo);",
        "DROP TABLE IF EXISTS capa2.lineas_dedicadas_consolidado_prev;",
        """ALTER TABLE IF EXISTS capa2.lineas_dedicadas_consolidado
               RENAME TO lineas_dedicadas_consolidado_prev;""",
        """ALTER TABLE capa2._lineas_dedicadas_consolidado_next
               RENAME TO lineas_dedicadas_consolidado;""",
    ]


SQL_CONTEO_DRY_RUN = """
WITH reportado AS (
    SELECT
        NULLIF(REGEXP_REPLACE(COALESCE(v.isp_ruc::text, ''), '[^0-9]', '', 'g'), '') AS ruc_limpio,
        v.peva_codigo, v.par_codigo AS geografia_id,
        MAKE_DATE(v.anio::int, v.periodoNumero::int, 1) AS periodo
    FROM analitico.v_lineas_dedicadas_resumen v
    WHERE COALESCE(v.isp_nombre::text, '') NOT ILIKE '%prueba%'
      AND COALESCE(v.nombreComercial::text, '') NOT ILIKE '%prueba%'
      AND v.peva_codigo NOT IN (SELECT peva_codigo FROM calidad.vw_pevas_excluidos)
),
con_prestador AS (
    SELECT COALESCE(ruc_limpio, peva_codigo) AS prestador_id, *
    FROM reportado
),
series AS (
    SELECT prestador_id, geografia_id, MIN(periodo) AS periodo_min, MAX(periodo) AS periodo_max,
           COUNT(*) AS filas_reales
    FROM con_prestador
    GROUP BY prestador_id, geografia_id
)
SELECT
    COUNT(*) AS combinaciones_prestador_geografia,
    SUM(filas_reales) AS filas_reales_totales,
    SUM(
        (DATE_PART('year', periodo_max) - DATE_PART('year', periodo_min)) * 12
        + (DATE_PART('month', periodo_max) - DATE_PART('month', periodo_min)) + 1
    )::bigint AS filas_totales_tras_relleno_interior
FROM series;
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Solo cuenta filas, no crea ni reemplaza capa2.lineas_dedicadas_consolidado")
    args = parser.parse_args()

    engine = _engine()

    if args.dry_run:
        with engine.connect() as conn:
            fila = conn.execute(text(SQL_CONTEO_DRY_RUN)).mappings().one()
        logger.info("Combinaciones prestador/geografía: %s", fila["combinaciones_prestador_geografia"])
        logger.info("Filas reales (reportadas de verdad): %s", fila["filas_reales_totales"])
        logger.info("Filas totales tras relleno interior (reales + imputadas): %s", fila["filas_totales_tras_relleno_interior"])
        imputadas = fila["filas_totales_tras_relleno_interior"] - fila["filas_reales_totales"]
        logger.info("Filas que serían imputadas (huecos interiores): %s", imputadas)
        logger.info("--dry-run: no se escribió nada.")
        return 0

    with engine.begin() as conn:
        for sentencia in _sentencias_construccion():
            conn.execute(text(sentencia))

    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM capa2.lineas_dedicadas_consolidado")).scalar_one()
        imputadas = conn.execute(
            text("SELECT COUNT(*) FROM capa2.lineas_dedicadas_consolidado WHERE es_imputado")
        ).scalar_one()

    logger.info("capa2.lineas_dedicadas_consolidado construida: %s filas totales, %s imputadas (%.1f%%).",
                total, imputadas, 100 * imputadas / total if total else 0)
    logger.info("Tabla anterior conservada en capa2.lineas_dedicadas_consolidado_prev por si hay que comparar o revertir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
