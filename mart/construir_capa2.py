"""
mart/construir_capa2.py

Reemplaza a Datos.ipynb. Construye capa2.lineas_dedicadas_consolidado
directamente en sietel_analitico (VM1, mismo host que analitico/mart), sin
salir nunca a una base personal.

CORRECCION IMPORTANTE (28-jul-2026, tras revisión profesional): la primera
versión de este script colapsaba las filas a granularidad
(prestador_id, geografia_id, periodo) y precomputaba esos dos campos --
pero sql/02_ddl_mart.sql, que YA ESTABA EN PRODUCCIÓN, espera exactamente
lo contrario: capa2 debe conservar la MISMA granularidad que la fuente
cruda -- una fila por (peva_codigo, par_codigo, periodo, tipoEnlace,
tipoCliente, nivelComparticion, portador) -- con isp_ruc y peva_codigo SIN
limpiar (mart.stg_fuente_normalizada, sección 2 de 02_ddl_mart.sql, hace su
propia limpieza y resuelve prestador_id/geografia_id), y con columnas
es_reportado/es_imputado que mart.stg_lineas_por_peva_geografia_mes
(sección 7) consume directamente. Esta versión corrige eso: ya no
precomputa prestador_id ni geografia_id, y el relleno de huecos interiores
(LOCF) opera sobre la combinación completa de 6 columnas -- exactamente la
llave natural documentada de dbo.VALineasDedicadas / va_lineas_dedicadas_resumen --
en vez de una llave agregada que rompía la sección 7 de 02_ddl_mart.sql.

CAMBIO METODOLÓGICO DELIBERADO respecto al notebook original (documentado
para revisión de Mercados -- ver discusión completa en el hilo de trabajo):
  - El notebook original rellenaba (LOCF) desde el último reporte real
    HACIA ADELANTE, indefinidamente, hasta una fecha de corte hardcodeada.
    Este script SOLO rellena huecos INTERIORES -- entre el primer y el
    último reporte real de cada combinación (peva_codigo, par_codigo,
    tipoEnlace, tipoCliente, nivelComparticion, portador). NUNCA
    extrapola más allá del último reporte real.
  - Cada fila queda marcada con es_reportado / es_imputado, visibles para
    el futuro dashboard de consistencia de datos.
  - Esto NO resuelve, por sí solo, si interpolar huecos interiores es
    aceptable para el uso regulatorio de este dato -- eso lo sigue
    debiendo confirmar Mercados.

EXCLUSIÓN aplicada en este script (además de lo que ya excluye Capa 3 por
su cuenta -- ver sección 2 de 02_ddl_mart.sql, ruc_prueba/peva_prueba):
  - PEVA del Grupo A ya confirmados como duplicado de migración de
    codificación (calidad.vw_pevas_excluidos) -- correr
    mart/detectar_conflictos_peva.py ANTES de este script. Esta exclusión
    es EXCLUSIVA de este script; 02_ddl_mart.sql no conoce el esquema
    calidad.

Deliberadamente NO se filtran aquí los prestadores de "prueba" -- Capa 3
(02_ddl_mart.sql, sección 2) ya lo hace de forma autoritativa a partir de
isp_nombre/nombrecomercial. Duplicar ese filtro en dos lugares es
exactamente el tipo de regla repetida que ya causó una divergencia real
antes en este proyecto (ver ANIO_INICIO_HISTORICO en sietel_pipeline).

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


# Columnas de ATRIBUTOS que se transportan como snapshot atómico durante el
# relleno de huecos interiores (constantes dentro de cada grupo de llave
# natural, pero pueden variar de una carga a otra -- ej. isp_nombre tras un
# cambio de razón social).
COLUMNAS_ATRIBUTOS = [
    "isp_codigo", "isp_ruc", "isp_nombre", "isp_tipopersona", "isp_regional",
    "nombrecomercial", "opera", "resolucion", "fechapermiso",
    "codigo_provincia", "codigo_ciudad", "codigo_parroquia",
    "pro_nombre", "ciu_nombre", "par_nombre", "regional_reporte",
    "opera_actual", "es_cancelado_actual",
]

# Columnas de MÉTRICAS -- mismo principio de snapshot atómico (nunca
# columna por columna de forma independiente).
COLUMNAS_METRICAS = [
    "total_lineas", "total_usuarios",
    "lineas_dl_sin_datos", "lineas_dl_menos_1mbps", "lineas_dl_1_10mbps",
    "lineas_dl_10_30mbps", "lineas_dl_30_100mbps", "lineas_dl_100mbps_1gbps",
    "lineas_dl_1gbps_o_mas",
    "lineas_ul_sin_datos", "lineas_ul_menos_1mbps", "lineas_ul_1_10mbps",
    "lineas_ul_10_30mbps", "lineas_ul_30_100mbps", "lineas_ul_100mbps_1gbps",
    "lineas_ul_1gbps_o_mas",
    "lineas_dl_banda_ancha", "lineas_dl_ultra_banda_ancha",
]

COLUMNAS_SNAPSHOT = COLUMNAS_ATRIBUTOS + COLUMNAS_METRICAS

# Llave natural para el relleno de huecos interiores -- misma granularidad
# que dbo.VALineasDedicadas / staging.va_lineas_dedicadas_resumen.
LLAVE_NATURAL = ["peva_codigo", "par_codigo", "tipoenlace", "tipocliente", "nivelcomparticion", "portador"]


def _sentencias_construccion() -> list[str]:
    bloque_snapshot = "\n".join(f"    FIRST_VALUE({c}) OVER w AS {c}," for c in COLUMNAS_SNAPSHOT)
    llave_sql = ", ".join(LLAVE_NATURAL)

    crear_tabla_next = f"""
    CREATE TABLE capa2._lineas_dedicadas_consolidado_next AS
    WITH opera_actual_por_peva AS (
        -- Estado ACTUAL del PEVA (distinto de v.opera, que es el estado
        -- histórico capturado en cada reporte mensual). Se toma de
        -- v_ultimo_periodo_reportado_detalle, que tiene múltiples filas
        -- por peva_codigo (una por geografía/tipo de enlace del último
        -- período) -- se colapsa a una fila por PEVA antes de usarla,
        -- mismo patrón ya validado en detectar_conflictos_peva.py.
        SELECT DISTINCT ON (u.peva_codigo)
            u.peva_codigo,
            u.opera AS opera_actual
        FROM analitico.v_ultimo_periodo_reportado_detalle u
        WHERE u.peva_codigo IS NOT NULL
        ORDER BY u.peva_codigo, u.ultimo_anio DESC NULLS LAST, u.ultimo_periodo_numero DESC NULLS LAST
    ),
    reportado AS (
        SELECT
            v.peva_codigo,
            v.par_codigo,
            BTRIM(v.tipoEnlace) AS tipoenlace,
            BTRIM(v.tipoCliente) AS tipocliente,
            BTRIM(v.nivelComparticion) AS nivelcomparticion,
            BTRIM(v.portador) AS portador,
            MAKE_DATE(v.anio::int, v.periodoNumero::int, 1) AS periodo,
            v.isp_codigo, v.isp_ruc, v.isp_nombre, v.isp_tipoPersona AS isp_tipopersona,
            v.isp_regional, v.nombreComercial AS nombrecomercial,
            v.opera, v.Resolucion AS resolucion, v.fechaPermiso AS fechapermiso,
            v.codigo_provincia, v.codigo_ciudad, v.codigo_parroquia,
            v.pro_nombre, v.ciu_nombre, v.par_nombre, v.regional_reporte,
            oa.opera_actual,
            -- Limitación deliberada: solo reconoce la marca explícita de
            -- cancelación en el texto categórico actual. NO intenta
            -- interpretar los códigos heredados SI/NO/- de opera (ver
            -- hallazgo ya documentado en sietel_pipeline) -- esos casos
            -- quedan como es_cancelado_actual = false, no como una
            -- adivinanza.
            (oa.opera_actual ILIKE '%cancelac%') AS es_cancelado_actual,
            v.total_lineas, v.total_usuarios,
            v.lineas_dl_sin_datos, v.lineas_dl_menos_1mbps, v.lineas_dl_1_10mbps,
            v.lineas_dl_10_30mbps, v.lineas_dl_30_100mbps, v.lineas_dl_100mbps_1gbps,
            v.lineas_dl_1gbps_o_mas,
            v.lineas_ul_sin_datos, v.lineas_ul_menos_1mbps, v.lineas_ul_1_10mbps,
            v.lineas_ul_10_30mbps, v.lineas_ul_30_100mbps, v.lineas_ul_100mbps_1gbps,
            v.lineas_ul_1gbps_o_mas,
            v.lineas_dl_banda_ancha, v.lineas_dl_ultra_banda_ancha
        FROM analitico.v_lineas_dedicadas_resumen v
        LEFT JOIN opera_actual_por_peva oa ON oa.peva_codigo = v.peva_codigo
        WHERE v.peva_codigo NOT IN (SELECT peva_codigo FROM calidad.vw_pevas_excluidos)
    ),
    series AS (
        SELECT {llave_sql}, MIN(periodo) AS periodo_min, MAX(periodo) AS periodo_max
        FROM reportado
        GROUP BY {llave_sql}
    ),
    -- Calendario FIJO y pequeño (0 a 240 meses = 20 años de margen), en vez
    -- de un generate_series() correlacionado por fila (LATERAL). Con
    -- límites literales, Postgres estima su cardinalidad con precisión
    -- (~241 filas, sabido de antemano) -- con el LATERAL anterior, el
    -- planificador asumía 1000 filas por cada una de las ~94,000
    -- combinaciones (43 millones), cuando el promedio real es ~24. Esa
    -- mala estimación forzaba un Sort gigantesco antes del Merge Join.
    calendario AS (
        SELECT gs AS indice_mes
        FROM generate_series(0, 240) AS gs
    ),
    spine AS (
        SELECT
            s.{", s.".join(LLAVE_NATURAL)},
            (s.periodo_min + (c.indice_mes || ' months')::interval)::date AS periodo
        FROM series s
        JOIN calendario c
          ON c.indice_mes <= (
                (DATE_PART('year', s.periodo_max) - DATE_PART('year', s.periodo_min)) * 12
                + (DATE_PART('month', s.periodo_max) - DATE_PART('month', s.periodo_min))
             )
    ),
    combinado AS (
        SELECT
            sp.{", sp.".join(LLAVE_NATURAL)},
            sp.periodo,
            r.isp_codigo, r.isp_ruc, r.isp_nombre, r.isp_tipopersona, r.isp_regional,
            r.nombrecomercial, r.opera, r.resolucion, r.fechapermiso,
            r.codigo_provincia, r.codigo_ciudad, r.codigo_parroquia,
            r.pro_nombre, r.ciu_nombre, r.par_nombre, r.regional_reporte,
            r.opera_actual, r.es_cancelado_actual,
            r.total_lineas, r.total_usuarios,
            r.lineas_dl_sin_datos, r.lineas_dl_menos_1mbps, r.lineas_dl_1_10mbps,
            r.lineas_dl_10_30mbps, r.lineas_dl_30_100mbps, r.lineas_dl_100mbps_1gbps,
            r.lineas_dl_1gbps_o_mas,
            r.lineas_ul_sin_datos, r.lineas_ul_menos_1mbps, r.lineas_ul_1_10mbps,
            r.lineas_ul_10_30mbps, r.lineas_ul_30_100mbps, r.lineas_ul_100mbps_1gbps,
            r.lineas_ul_1gbps_o_mas,
            r.lineas_dl_banda_ancha, r.lineas_dl_ultra_banda_ancha,
            (r.peva_codigo IS NOT NULL) AS es_reportado
        FROM spine sp
        LEFT JOIN reportado r
          ON {" AND ".join(f"COALESCE(r.{c}, '§SIN_VALOR§') = COALESCE(sp.{c}, '§SIN_VALOR§')" for c in LLAVE_NATURAL)}
         AND r.periodo = sp.periodo
    ),
    agrupado AS (
        SELECT
            *,
            COUNT(CASE WHEN es_reportado THEN 1 END) OVER (
                PARTITION BY {", ".join(LLAVE_NATURAL)} ORDER BY periodo
            ) AS grupo_carry
        FROM combinado
    )
    SELECT
        {", ".join(LLAVE_NATURAL)},
        periodo,
{bloque_snapshot}
        es_reportado,
        (FIRST_VALUE(periodo) OVER w <> periodo) AS es_imputado
    FROM agrupado
    WINDOW w AS (PARTITION BY {", ".join(LLAVE_NATURAL)}, grupo_carry ORDER BY periodo)
    """

    return [
        "CREATE SCHEMA IF NOT EXISTS capa2;",
        "DROP TABLE IF EXISTS capa2._lineas_dedicadas_consolidado_next;",
        crear_tabla_next,
        f"CREATE INDEX ON capa2._lineas_dedicadas_consolidado_next ({', '.join(LLAVE_NATURAL)}, periodo);",
        "CREATE INDEX ON capa2._lineas_dedicadas_consolidado_next (periodo);",
        "CREATE INDEX ON capa2._lineas_dedicadas_consolidado_next (peva_codigo);",
        "CREATE INDEX ON capa2._lineas_dedicadas_consolidado_next (isp_ruc);",
        "DROP TABLE IF EXISTS capa2.lineas_dedicadas_consolidado_prev;",
        """ALTER TABLE IF EXISTS capa2.lineas_dedicadas_consolidado
               RENAME TO lineas_dedicadas_consolidado_prev;""",
        """ALTER TABLE capa2._lineas_dedicadas_consolidado_next
               RENAME TO lineas_dedicadas_consolidado;""",
    ]


def _sql_conteo_dry_run() -> str:
    llave_sql = ", ".join(LLAVE_NATURAL)
    llave_select = (
        "v.peva_codigo, v.par_codigo, "
        "BTRIM(v.tipoenlace) AS tipoenlace, BTRIM(v.tipocliente) AS tipocliente, "
        "BTRIM(v.nivelcomparticion) AS nivelcomparticion, BTRIM(v.portador) AS portador"
    )
    return f"""
    WITH reportado AS (
        SELECT
            {llave_select},
            MAKE_DATE(v.anio::int, v.periodoNumero::int, 1) AS periodo
        FROM analitico.v_lineas_dedicadas_resumen v
        WHERE v.peva_codigo NOT IN (SELECT peva_codigo FROM calidad.vw_pevas_excluidos)
    ),
    series AS (
        SELECT {llave_sql}, MIN(periodo) AS periodo_min, MAX(periodo) AS periodo_max,
               COUNT(*) AS filas_reales
        FROM reportado
        GROUP BY {llave_sql}
    )
    SELECT
        COUNT(*) AS combinaciones,
        SUM(filas_reales) AS filas_reales_totales,
        SUM(
            (DATE_PART('year', periodo_max) - DATE_PART('year', periodo_min)) * 12
            + (DATE_PART('month', periodo_max) - DATE_PART('month', periodo_min)) + 1
        )::bigint AS filas_totales_tras_relleno_interior
    FROM series;
    """


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo cuenta filas, no crea ni reemplaza capa2.lineas_dedicadas_consolidado")
    args = parser.parse_args()

    engine = _engine()

    if args.dry_run:
        with engine.connect() as conn:
            fila = conn.execute(text(_sql_conteo_dry_run())).mappings().one()
        reales = fila["filas_reales_totales"]
        total = fila["filas_totales_tras_relleno_interior"]
        logger.info("Combinaciones (peva/par/tipoEnlace/tipoCliente/nivelComparticion/portador): %s",
                    fila["combinaciones"])
        logger.info("Filas reales (reportadas de verdad): %s", reales)
        logger.info("Filas totales tras relleno interior (reales + imputadas): %s", total)
        logger.info("Filas que serían imputadas (huecos interiores): %s",
                    (total - reales) if (total is not None and reales is not None) else None)
        if reales is not None and total is not None and total < reales:
            logger.error(
                "INCONSISTENCIA: el total tras relleno es MENOR que las filas reales -- no debería pasar nunca. No confíes en este resultado, avisa antes de continuar.")
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
    logger.info(
        "Tabla anterior conservada en capa2.lineas_dedicadas_consolidado_prev por si hay que comparar o revertir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
