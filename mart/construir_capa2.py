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
propia limpieza y resuelve prestador_id/geografia_id). Esta versión ya no
precomputa prestador_id ni geografia_id: conserva la combinación completa
de 6 columnas -- exactamente la llave natural documentada de
dbo.VALineasDedicadas / va_lineas_dedicadas_resumen.

SIN IMPUTACIÓN (29-sep-2026, decisión metodológica): capa2 contiene
EXCLUSIVAMENTE lo que los prestadores reportaron. Versiones anteriores
rellenaban los huecos interiores de cada combinación con el último valor
conocido (LOCF) y marcaban cada fila con es_reportado/es_imputado. Se
eliminó por completo porque:
  - el faltante de un prestador que deja de reportar es no aleatorio
    (MNAR): heredar su último valor supone "sin cambios" cuando lo más
    probable es lo contrario;
  - cuando un prestador SÍ entregó su reporte pero omitió una
    combinación (parroquia/tipo de enlace...), lo más probable es un cero
    estructural, no un faltante -- el LOCF inventaba líneas ahí;
  - los totales mixtos (reportado + imputado) terminaban usándose en
    cálculos del dashboard que debían ser solo reportados.
Quién DEBÍA reportar en cada mes y no lo hizo ya no se deduce de filas
imputadas: lo resuelve mart.panel_reporte_prestador_mes (sección 9b de
sql/02_ddl_mart.sql), que no contiene ningún valor de líneas.

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


# Columnas de ATRIBUTOS del PEVA/ISP/parroquia -- constantes dentro de
# cada (llave natural, periodo), se consolidan con MAX/BOOL_OR.
COLUMNAS_ATRIBUTOS = [
    "isp_codigo", "isp_ruc", "isp_nombre", "isp_tipopersona", "isp_regional",
    "nombrecomercial", "opera", "resolucion", "fechapermiso",
    "codigo_provincia", "codigo_ciudad", "codigo_parroquia",
    "pro_nombre", "ciu_nombre", "par_nombre", "regional_reporte",
    "opera_actual", "es_cancelado_actual",
]

# Columnas de MÉTRICAS -- se suman al consolidar variantes de la misma
# llave (ver CTE "reportado" más abajo).
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

# Llave natural de capa2 -- misma granularidad
# que dbo.VALineasDedicadas / staging.va_lineas_dedicadas_resumen.
LLAVE_NATURAL = ["peva_codigo", "par_codigo", "tipoenlace", "tipocliente", "nivelcomparticion", "portador"]


def _sentencias_construccion() -> list[str]:
    llave_sql = ", ".join(LLAVE_NATURAL)
    bloque_atributos_agregados = "\n".join(
        f"            BOOL_OR({c}) AS {c}," if c == "es_cancelado_actual" else f"            MAX({c}) AS {c},"
        for c in COLUMNAS_ATRIBUTOS
    )
    bloque_metricas_sumadas = ",\n".join(f"            SUM({c}) AS {c}" for c in COLUMNAS_METRICAS)

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
    reportado_crudo AS (
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
    -- CORRECCIÓN (28-sep-2026): SIETEL reporta algunos valores de la llave
    -- con espacios al inicio (ej. ' NEDETEL S.A.' y 'NEDETEL S.A.' en el
    -- mismo PEVA/parroquia/mes -- SQL Server los trata como distintos). El
    -- BTRIM de arriba los unifica en la MISMA llave y el MISMO período.
    -- Confirmado en producción: 102 pares, 96 llaves descuadradas contra
    -- la fuente, -19.346 líneas netas (2024-2026) cuando no se
    -- consolidaban. Aquí se consolidan sumando las métricas, de modo que
    -- quede exactamente una fila por (llave, periodo). Los atributos son
    -- de PEVA/ISP/parroquia, constantes dentro del grupo -- MAX es seguro.
    reportado AS (
        SELECT
            {llave_sql}, periodo,
{bloque_atributos_agregados}
{bloque_metricas_sumadas}
        FROM reportado_crudo
        GROUP BY {llave_sql}, periodo
    )
    SELECT * FROM reportado
    """

    return [
        "CREATE SCHEMA IF NOT EXISTS capa2;",
        "DROP TABLE IF EXISTS capa2._lineas_dedicadas_consolidado_next;",
        crear_tabla_next,
        f"CREATE INDEX ON capa2._lineas_dedicadas_consolidado_next ({', '.join(LLAVE_NATURAL)}, periodo);",
        "CREATE INDEX ON capa2._lineas_dedicadas_consolidado_next (periodo);",
        "CREATE INDEX ON capa2._lineas_dedicadas_consolidado_next (peva_codigo);",
        "CREATE INDEX ON capa2._lineas_dedicadas_consolidado_next (isp_ruc);",
        # CASCADE agregado 07-ago-2026: si aplicar_capa3.py falla DESPUÉS de
        # que este script haga su "swap" (current -> _prev, next -> current)
        # pero ANTES de reconstruir mart -- confirmado en producción, causa
        # real: capa2.territorio_geometria_nodo faltante bloqueó
        # aplicar_capa3 -- las vistas materializadas de mart quedan
        # apuntando al objeto físico que ahora se llama "_prev" (Postgres
        # las ata por OID al crearlas, no por nombre; un RENAME no las
        # "seudo-actualiza"). La siguiente corrida de este script entonces
        # no puede borrar "_prev" sin CASCADE. Es seguro: TODAS esas vistas
        # materializadas las reconstruye aplicar_capa3.py desde cero
        # (DROP SCHEMA mart CASCADE) en cada corrida de todas formas -- este
        # CASCADE solo adelanta ese mismo borrado, nunca pierde datos reales
        # (capa2._lineas_dedicadas_consolidado_prev es explícitamente
        # desechable, "por si hay que comparar o revertir", nunca la única
        # copia de nada).
        "DROP TABLE IF EXISTS capa2.lineas_dedicadas_consolidado_prev CASCADE;",
        """ALTER TABLE IF EXISTS capa2.lineas_dedicadas_consolidado
               RENAME TO lineas_dedicadas_consolidado_prev;""",
        """ALTER TABLE capa2._lineas_dedicadas_consolidado_next
               RENAME TO lineas_dedicadas_consolidado;""",
    ]


def _sql_conteo_dry_run() -> str:
    llave_select = (
        "v.peva_codigo, v.par_codigo, "
        "BTRIM(v.tipoenlace) AS tipoenlace, BTRIM(v.tipocliente) AS tipocliente, "
        "BTRIM(v.nivelcomparticion) AS nivelcomparticion, BTRIM(v.portador) AS portador"
    )
    return f"""
    WITH reportado AS (
        SELECT DISTINCT
            {llave_select},
            MAKE_DATE(v.anio::int, v.periodoNumero::int, 1) AS periodo
        FROM analitico.v_lineas_dedicadas_resumen v
        WHERE v.peva_codigo NOT IN (SELECT peva_codigo FROM calidad.vw_pevas_excluidos)
    )
    SELECT COUNT(*) AS filas_reportadas
    FROM reportado;
    """


def construir_capa2(dry_run: bool = False) -> None:
    """
    Función invocable directamente (sin CLI/argparse) -- la que importa
    dags/sietel_mart_pipeline.py.
    """
    engine = _engine()

    if dry_run:
        with engine.connect() as conn:
            fila = conn.execute(text(_sql_conteo_dry_run())).mappings().one()
        logger.info("Filas (llave natural, periodo) reportadas: %s", fila["filas_reportadas"])
        logger.info("--dry-run: no se escribió nada.")
        return

    with engine.begin() as conn:
        for sentencia in _sentencias_construccion():
            conn.execute(text(sentencia))

    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM capa2.lineas_dedicadas_consolidado")).scalar_one()

    logger.info("capa2.lineas_dedicadas_consolidado construida: %s filas, todas reportadas (sin imputación).",
                total)
    logger.info(
        "Tabla anterior conservada en capa2.lineas_dedicadas_consolidado_prev por si hay que comparar o revertir.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo cuenta filas, no crea ni reemplaza capa2.lineas_dedicadas_consolidado")
    args = parser.parse_args(argv)

    construir_capa2(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
