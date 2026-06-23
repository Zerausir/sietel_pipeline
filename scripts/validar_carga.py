"""
Validación cruzada SQL Server (SIETEL) vs PostgreSQL (analítico).

Inspirado en el paso "pipeline_validation" de samm_pipeline, con una
diferencia deliberada: SAMM no puede comparar contra su origen SQL Server
en cada corrida (no es alcanzable desde donde corre Airflow), así que
valida solo la salud interna del destino y compara metadatos contra un
registro de la última corrida (pipeline_state). En SIETEL SÍ hay acceso
directo a SQL Server desde Airflow, así que esta validación compara
conteos reales contra el origen en cada ejecución del DAG -- una garantía
más fuerte que la de SAMM, posible gracias a esa diferencia de arquitectura.

Esta validación se ejecuta como ÚLTIMA tarea del DAG. Si encuentra una
discrepancia, la tarea de Airflow FALLA (lanza excepción) en vez de solo
loguear una advertencia -- así la corrida queda visiblemente roja en la UI
y dispara las alertas/reintentos configurados en el DAG, en vez de quedar
oculta en un log que nadie revisa.
"""
import logging
from datetime import datetime

from config import postgres_cursor, sqlserver_cursor

logger = logging.getLogger(__name__)


class ValidacionFallida(Exception):
    pass


def _contar_sqlserver_por_anio(anio: int) -> int:
    with sqlserver_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM dbo.VAReporteUsuariosCuentas WHERE anio = ?", (anio,)
        )
        return cur.fetchone()["n"]


def _contar_postgres_por_anio(anio: int) -> int:
    with postgres_cursor(commit=False) as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM staging.va_reporte_usuarios_cuentas WHERE anio = %s",
            (anio,),
        )
        return cur.fetchone()["n"]


def _verificar_unicidad_vigencia():
    """
    Mismo chequeo que tests/verificar_pipeline.py: ninguna llave natural
    debe tener más de una versión vigente simultánea en las dimensiones
    SCD Tipo 2. Una violación aquí indica un bug en cargar_dimensiones.py,
    no un problema de datos de origen.
    """
    problemas = []
    with postgres_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT isp_codigo, COUNT(*) AS n FROM staging.dim_isp
            WHERE es_vigente = true GROUP BY isp_codigo HAVING COUNT(*) > 1
            """
        )
        dup_isp = cur.fetchall()
        if dup_isp:
            problemas.append(f"dim_isp: {len(dup_isp)} isp_codigo con más de una versión vigente")

        cur.execute(
            """
            SELECT peva_codigo, COUNT(*) AS n FROM staging.dim_permiso_va_agregado
            WHERE es_vigente = true GROUP BY peva_codigo HAVING COUNT(*) > 1
            """
        )
        dup_permiso = cur.fetchall()
        if dup_permiso:
            problemas.append(
                f"dim_permiso_va_agregado: {len(dup_permiso)} peva_codigo con más de una versión vigente"
            )
    return problemas


def _verificar_vista_sin_duplicados(anio: int):
    with postgres_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT ruc_codigo, COUNT(*) AS n
            FROM analitico.v_usuarios_cuentas
            WHERE anio = %s
            GROUP BY ruc_codigo
            HAVING COUNT(*) > 1
            """,
            (anio,),
        )
        return cur.fetchall()


def _registrar_resultado(anio, estado, mensaje_error, fecha_inicio):
    with postgres_cursor() as cur:
        cur.execute(
            """
            INSERT INTO staging.control_cargas
                (tipo_carga, anio, filas_insertadas, filas_actualizadas,
                 estado, mensaje_error, fecha_inicio)
            VALUES ('validacion_cruzada', %s, NULL, NULL, %s, %s, %s)
            """,
            (anio, estado, mensaje_error, fecha_inicio),
        )


def validar_anios(anios: list[int]):
    """
    Valida, para cada año recién cargado:
      1. Que el conteo de filas en SQL Server coincida exactamente con el
         conteo en PostgreSQL (detecta filas perdidas o duplicadas).
      2. Que las dimensiones SCD Tipo 2 no tengan más de una versión
         vigente por llave natural.
      3. Que la vista de consumo no genere filas duplicadas por el JOIN de
         vigencia temporal.

    Lanza ValidacionFallida (y por lo tanto falla la tarea de Airflow) si
    encuentra cualquier discrepancia. Registra el resultado en
    staging.control_cargas (tipo_carga='validacion_cruzada') igual si pasa
    o si falla, para mantener un historial auditable de cada validación.
    """
    inicio = datetime.now()
    errores = []

    problemas_vigencia = _verificar_unicidad_vigencia()
    if problemas_vigencia:
        errores.extend(problemas_vigencia)

    for anio in anios:
        filas_origen = _contar_sqlserver_por_anio(anio)
        filas_destino = _contar_postgres_por_anio(anio)
        if filas_origen != filas_destino:
            errores.append(
                f"Año {anio}: SQL Server tiene {filas_origen} filas, "
                f"PostgreSQL tiene {filas_destino} (discrepancia de {abs(filas_origen - filas_destino)})"
            )
        else:
            logger.info("Año %s: %s filas en ambos lados, OK.", anio, filas_origen)

        duplicados_vista = _verificar_vista_sin_duplicados(anio)
        if duplicados_vista:
            errores.append(
                f"Año {anio}: la vista analitico.v_usuarios_cuentas devuelve más de una "
                f"fila para {len(duplicados_vista)} ruc_codigo (JOIN de vigencia temporal "
                f"matchea más de una versión)"
            )

    if errores:
        mensaje = "; ".join(errores)
        for anio in anios:
            _registrar_resultado(anio, "FALLIDO", mensaje, inicio)
        raise ValidacionFallida(
            f"Validación cruzada SQL Server vs PostgreSQL encontró {len(errores)} problema(s): {mensaje}"
        )

    for anio in anios:
        _registrar_resultado(anio, "EXITOSO", None, inicio)
    logger.info("Validación cruzada exitosa para los años: %s", anios)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Valida SQL Server vs PostgreSQL para los años dados.")
    parser.add_argument("--anios", type=int, nargs="+", required=True, help="Años a validar, ej. --anios 2025 2026")
    args = parser.parse_args()
    validar_anios(args.anios)
