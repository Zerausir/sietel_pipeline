"""
Carga de la tabla de hechos staging.va_reporte_usuarios_cuentas, un año a
la vez (parametrizado por el DAG con el rango ANIO_INICIO_HISTORICO..
ANIO_FIN_HISTORICO).

A diferencia del query original usado en SSMS, este SELECT NO incluye
isp_nombre/isp_ruc/opera/nombreComercial/etc. -- esas columnas se resuelven
en la vista analitico.v_usuarios_cuentas mediante JOIN contra las
dimensiones versionadas (staging.dim_isp / staging.dim_permiso_va_agregado).
Incluir esas columnas aquí duplicaría el mismo texto en cientos de miles de
filas históricas sin aportar valor analítico (ver discusión de diseño).

La carga es idempotente: usa ON CONFLICT (ruc_codigo) DO UPDATE, por lo que
reintentar la carga de un año ya cargado no duplica filas.

CERTIFICACIÓN DE CONTENIDO (no solo de identidad):
Cada fila lleva un hash_contenido (MD5) calculado de forma determinista
sobre sus columnas de métricas, en COLUMNAS_HASH, en el mismo orden tanto
al extraer de SQL Server como al insertar en PostgreSQL. Esto certifica
que el VALOR de cada fila migrada es idéntico al de origen -- un COUNT(*)
igual entre ambos lados no garantiza esto (dos filas distintas con el
mismo conteo total podrían tener valores corruptos sin que el conteo lo
detecte). Mismo principio que el "GUARANTEE MODE" de samm_pipeline
(app/utils/postgres_handler.py): SAMM genera un ID determinista (MD5)
sobre campos de negocio para garantizar mapeo 1:1 fila-a-registro; aquí el
ID natural ya existe (ruc_codigo, PK de origen), así que el hash certifica
contenido en vez de identidad -- scripts/validar_carga.py compara estos
hashes entre SQL Server y PostgreSQL para detectar cualquier corrupción de
valores que un simple conteo de filas no revelaría.
"""
import argparse
import hashlib
import logging
from datetime import datetime

from config import postgres_cursor, sqlserver_cursor

logger = logging.getLogger(__name__)

# Orden FIJO y determinista de columnas sobre las que se calcula el hash.
# Debe ser idéntico en cargar_hechos_anio.py y validar_carga.py -- un
# cambio en este orden invalida la comparación de hashes existentes.
COLUMNAS_HASH = [
    "peva_codigo", "par_codigo", "anio", "mesNumero", "tipo_enlace",
    "c_du_r", "c_du_c", "c_du_total",
    "c_d_r", "c_d_c", "c_d_ci", "c_d_total",
    "c_total_cuentas", "c_total_r", "c_total_c",
    "u_du_r", "u_du_c", "u_du_total",
    "u_d_r", "u_d_c", "u_d_ci", "u_d_total",
    "u_total_usuarios", "u_total_r", "u_total_c", "u_total_ci",
]


def calcular_hash_fila(fila: dict) -> str:
    """
    Calcula un hash MD5 determinista sobre COLUMNAS_HASH de una fila.

    Usa "|" como separador y str(None) explícito para valores nulos, de
    modo que el mismo conjunto de valores produzca siempre el mismo hash,
    sin ambigüedad por cómo cada driver (pyodbc vs psycopg2) representa
    internamente los tipos.
    """
    valores = [str(fila.get(col)) if fila.get(col) is not None else "NULL" for col in COLUMNAS_HASH]
    cadena = "|".join(valores)
    return hashlib.md5(cadena.encode("utf-8")).hexdigest()


SQL_EXTRAER_HECHOS_ANIO = """
    SELECT
        r.ruc_codigo,
        r.peva_codigo,
        r.par_codigo,
        r.anio,
        r.mesNumero,
        r.mesNombre,
        r.actualizado,
        prov.pro_nombre,
        ciu.ciu_nombre,
        par.par_nombre,
        r.tipo_enlace,
        r.c_du_r, r.c_du_c, r.c_du_total,
        r.c_d_r, r.c_d_c, r.c_d_ci, r.c_d_total,
        r.c_total_cuentas, r.c_total_r, r.c_total_c,
        r.u_du_r, r.u_du_c, r.u_du_total,
        r.u_d_r, r.u_d_c, r.u_d_ci, r.u_d_total,
        r.u_total_usuarios, r.u_total_r, r.u_total_c, r.u_total_ci
    FROM dbo.VAReporteUsuariosCuentas r
    LEFT JOIN dbo.Parroquia par ON par.par_codigo = r.par_codigo
    LEFT JOIN dbo.Ciudad ciu ON ciu.ciu_codigo = par.ciu_codigo
    LEFT JOIN dbo.Provincia prov ON prov.pro_codigo = ciu.pro_codigo
    WHERE r.anio = ?
"""

SQL_UPSERT_HECHOS = """
    INSERT INTO staging.va_reporte_usuarios_cuentas (
        ruc_codigo, peva_codigo, par_codigo, anio, mesNumero, mesNombre,
        actualizado, pro_nombre, ciu_nombre, par_nombre, tipo_enlace,
        c_du_r, c_du_c, c_du_total, c_d_r, c_d_c, c_d_ci, c_d_total,
        c_total_cuentas, c_total_r, c_total_c,
        u_du_r, u_du_c, u_du_total, u_d_r, u_d_c, u_d_ci, u_d_total,
        u_total_usuarios, u_total_r, u_total_c, u_total_ci,
        hash_contenido
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s
    )
    ON CONFLICT (ruc_codigo) DO UPDATE SET
        peva_codigo = EXCLUDED.peva_codigo,
        par_codigo = EXCLUDED.par_codigo,
        actualizado = EXCLUDED.actualizado,
        pro_nombre = EXCLUDED.pro_nombre,
        ciu_nombre = EXCLUDED.ciu_nombre,
        par_nombre = EXCLUDED.par_nombre,
        tipo_enlace = EXCLUDED.tipo_enlace,
        c_du_r = EXCLUDED.c_du_r, c_du_c = EXCLUDED.c_du_c, c_du_total = EXCLUDED.c_du_total,
        c_d_r = EXCLUDED.c_d_r, c_d_c = EXCLUDED.c_d_c, c_d_ci = EXCLUDED.c_d_ci,
        c_d_total = EXCLUDED.c_d_total,
        c_total_cuentas = EXCLUDED.c_total_cuentas, c_total_r = EXCLUDED.c_total_r,
        c_total_c = EXCLUDED.c_total_c,
        u_du_r = EXCLUDED.u_du_r, u_du_c = EXCLUDED.u_du_c, u_du_total = EXCLUDED.u_du_total,
        u_d_r = EXCLUDED.u_d_r, u_d_c = EXCLUDED.u_d_c, u_d_ci = EXCLUDED.u_d_ci,
        u_d_total = EXCLUDED.u_d_total,
        u_total_usuarios = EXCLUDED.u_total_usuarios, u_total_r = EXCLUDED.u_total_r,
        u_total_c = EXCLUDED.u_total_c, u_total_ci = EXCLUDED.u_total_ci,
        hash_contenido = EXCLUDED.hash_contenido,
        fecha_carga = now()
"""


def cargar_hechos_anio(anio: int):
    inicio = datetime.now()
    filas_procesadas = 0
    try:
        with sqlserver_cursor() as ms_cur, postgres_cursor() as pg_cur:
            ms_cur.execute(SQL_EXTRAER_HECHOS_ANIO, (anio,))
            filas = ms_cur.fetchall()

            for fila in filas:
                hash_fila = calcular_hash_fila(fila)
                pg_cur.execute(
                    SQL_UPSERT_HECHOS,
                    (
                        fila["ruc_codigo"], fila["peva_codigo"], fila["par_codigo"],
                        fila["anio"], fila["mesNumero"], fila["mesNombre"], fila["actualizado"],
                        fila["pro_nombre"], fila["ciu_nombre"], fila["par_nombre"], fila["tipo_enlace"],
                        fila["c_du_r"], fila["c_du_c"], fila["c_du_total"],
                        fila["c_d_r"], fila["c_d_c"], fila["c_d_ci"], fila["c_d_total"],
                        fila["c_total_cuentas"], fila["c_total_r"], fila["c_total_c"],
                        fila["u_du_r"], fila["u_du_c"], fila["u_du_total"],
                        fila["u_d_r"], fila["u_d_c"], fila["u_d_ci"], fila["u_d_total"],
                        fila["u_total_usuarios"], fila["u_total_r"], fila["u_total_c"], fila["u_total_ci"],
                        hash_fila,
                    ),
                )
                filas_procesadas += 1

        _registrar_carga("hechos_anual", anio, filas_procesadas, 0, "EXITOSO", None, inicio)
        logger.info("Año %s: %s filas procesadas (insertadas o actualizadas)", anio, filas_procesadas)
    except Exception as exc:
        _registrar_carga("hechos_anual", anio, filas_procesadas, 0, "FALLIDO", str(exc), inicio)
        logger.exception("Error cargando hechos del año %s", anio)
        raise


def _registrar_carga(tipo_carga, anio, insertadas, actualizadas, estado, mensaje_error, fecha_inicio):
    with postgres_cursor() as cur:
        cur.execute(
            """
            INSERT INTO staging.control_cargas
                (tipo_carga, anio, filas_insertadas, filas_actualizadas,
                 estado, mensaje_error, fecha_inicio)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (tipo_carga, anio, insertadas, actualizadas, estado, mensaje_error, fecha_inicio),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Carga hechos VAReporteUsuariosCuentas de un año específico.")
    parser.add_argument("--anio", type=int, required=True, help="Año a cargar, ej. 2011")
    args = parser.parse_args()
    cargar_hechos_anio(args.anio)
