"""
Carga de dimensiones versionadas (SCD Tipo 2): ISP y PermisoVAgregado.

Esta tarea se ejecuta UNA VEZ por corrida del pipeline (no una vez por año
histórico), porque SQL Server (SIETEL) solo expone el estado ACTUAL de
estas tablas -- no existe fuente para el valor histórico real anterior al
arranque de este pipeline. Ver advertencia en sql/01_ddl_postgres.sql.

Columnas que disparan una nueva versión (atributos "Tipo 2") se definen
explícitamente abajo, no se infieren comparando la fila completa, porque
columnas de metadata técnica (creadoPor, fechaModificacion, etc.) cambian
constantemente sin que eso represente un hecho de negocio versionable.

IMPORTANTE: esta lista de columnas versionables es una propuesta inicial
del equipo técnico (ver documento "Propuesta de Historizacion - Validacion
con Mercados"). Debe confirmarse/ajustarse con el área de Mercados antes de
considerarse definitiva.
"""
import logging
from datetime import datetime

from config import postgres_cursor, sqlserver_cursor

logger = logging.getLogger(__name__)

# Columnas de negocio que, al cambiar, disparan el cierre de la versión
# vigente y la apertura de una nueva.
COLUMNAS_VERSIONABLES_ISP = ["isp_nombre", "isp_ruc"]
COLUMNAS_VERSIONABLES_PERMISO = ["nombreComercial", "opera", "Resolucion"]

SQL_EXTRAER_ISP = """
    SELECT
        isp_codigo, isp_nombre, isp_ruc, isp_tipoPersona,
        isp_observacion, isp_telefono, regional, fechaModificacion
    FROM dbo.ISP
"""

SQL_EXTRAER_PERMISO = """
    SELECT
        peva_codigo, isp_codigo, nombreComercial, opera,
        fechaPermiso, Resolucion
    FROM dbo.PermisoVAgregado
"""


def _extraer_filas(cursor, sql):
    cursor.execute(sql)
    return cursor.fetchall()


def _obtener_vigentes(pg_cursor, tabla, llave_natural):
    pg_cursor.execute(
        f"SELECT * FROM staging.{tabla} WHERE es_vigente = true"
    )
    filas = pg_cursor.fetchall()
    return {fila[llave_natural]: fila for fila in filas}


def _cambio_relevante(fila_origen: dict, fila_vigente: dict, columnas: list) -> bool:
    for col in columnas:
        if fila_origen.get(col) != fila_vigente.get(col):
            return True
    return False


def cargar_dim_isp():
    inicio = datetime.now()
    insertadas = 0
    actualizadas = 0
    try:
        with sqlserver_cursor() as ms_cur, postgres_cursor() as pg_cur:
            filas_origen = _extraer_filas(ms_cur, SQL_EXTRAER_ISP)
            vigentes = _obtener_vigentes(pg_cur, "dim_isp", "isp_codigo")

            for fila in filas_origen:
                vigente = vigentes.get(fila["isp_codigo"])

                if vigente is None:
                    # ISP nunca cargado: primera versión. fecha_inicio_vigencia
                    # se fija deliberadamente muy en el pasado (no now()) para
                    # que los hechos históricos ya cargados en
                    # staging.va_reporte_usuarios_cuentas (que pueden ser de
                    # cualquier año desde 2011) puedan unirse correctamente
                    # contra esta primera versión en la vista de consumo. Si
                    # se usara now() como en versiones posteriores, todo el
                    # histórico anterior a la fecha de la primera carga del
                    # pipeline quedaría sin JOIN posible (huérfano).
                    pg_cur.execute(
                        """
                        INSERT INTO staging.dim_isp
                            (isp_codigo, isp_nombre, isp_ruc, isp_tipoPersona,
                             isp_observacion, isp_telefono, regional, fechaModificacion,
                             fecha_inicio_vigencia)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '1900-01-01')
                        """,
                        (
                            fila["isp_codigo"], fila["isp_nombre"], fila["isp_ruc"],
                            fila["isp_tipoPersona"], fila["isp_observacion"],
                            fila["isp_telefono"], fila["regional"], fila["fechaModificacion"],
                        ),
                    )
                    insertadas += 1
                    continue

                if _cambio_relevante(fila, vigente, COLUMNAS_VERSIONABLES_ISP):
                    # Cierra la versión vigente y abre una nueva
                    pg_cur.execute(
                        """
                        UPDATE staging.dim_isp
                        SET fecha_fin_vigencia = now(), es_vigente = false
                        WHERE isp_sk = %s
                        """,
                        (vigente["isp_sk"],),
                    )
                    pg_cur.execute(
                        """
                        INSERT INTO staging.dim_isp
                            (isp_codigo, isp_nombre, isp_ruc, isp_tipoPersona,
                             isp_observacion, isp_telefono, regional, fechaModificacion)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            fila["isp_codigo"], fila["isp_nombre"], fila["isp_ruc"],
                            fila["isp_tipoPersona"], fila["isp_observacion"],
                            fila["isp_telefono"], fila["regional"], fila["fechaModificacion"],
                        ),
                    )
                    actualizadas += 1
                else:
                    # Sin cambio en columnas versionables: actualiza en sitio
                    # los atributos no versionables (Tipo 1) de la fila vigente.
                    pg_cur.execute(
                        """
                        UPDATE staging.dim_isp
                        SET isp_observacion = %s, isp_telefono = %s,
                            regional = %s, fechaModificacion = %s
                        WHERE isp_sk = %s
                        """,
                        (
                            fila["isp_observacion"], fila["isp_telefono"],
                            fila["regional"], fila["fechaModificacion"],
                            vigente["isp_sk"],
                        ),
                    )

        _registrar_carga(
            "dimensiones", None, insertadas, actualizadas, "EXITOSO", None, inicio
        )
        logger.info(
            "dim_isp: %s ISP nuevos, %s nuevas versiones por cambio", insertadas, actualizadas
        )
    except Exception as exc:
        _registrar_carga("dimensiones", None, insertadas, actualizadas, "FALLIDO", str(exc), inicio)
        logger.exception("Error cargando dim_isp")
        raise


def cargar_dim_permiso_va_agregado():
    inicio = datetime.now()
    insertadas = 0
    actualizadas = 0
    try:
        with sqlserver_cursor() as ms_cur, postgres_cursor() as pg_cur:
            filas_origen = _extraer_filas(ms_cur, SQL_EXTRAER_PERMISO)
            vigentes = _obtener_vigentes(pg_cur, "dim_permiso_va_agregado", "peva_codigo")

            for fila in filas_origen:
                vigente = vigentes.get(fila["peva_codigo"])

                if vigente is None:
                    # Mismo criterio que en cargar_dim_isp: la primera versión
                    # debe ser vigente desde antes del histórico cargado, no
                    # desde el momento de la primera corrida del pipeline.
                    pg_cur.execute(
                        """
                        INSERT INTO staging.dim_permiso_va_agregado
                            (peva_codigo, isp_codigo, nombreComercial, opera,
                             fechaPermiso, Resolucion, fecha_inicio_vigencia)
                        VALUES (%s, %s, %s, %s, %s, %s, '1900-01-01')
                        """,
                        (
                            fila["peva_codigo"], fila["isp_codigo"], fila["nombreComercial"],
                            fila["opera"], fila["fechaPermiso"], fila["Resolucion"],
                        ),
                    )
                    insertadas += 1
                    continue

                if _cambio_relevante(fila, vigente, COLUMNAS_VERSIONABLES_PERMISO):
                    pg_cur.execute(
                        """
                        UPDATE staging.dim_permiso_va_agregado
                        SET fecha_fin_vigencia = now(), es_vigente = false
                        WHERE peva_sk = %s
                        """,
                        (vigente["peva_sk"],),
                    )
                    pg_cur.execute(
                        """
                        INSERT INTO staging.dim_permiso_va_agregado
                            (peva_codigo, isp_codigo, nombreComercial, opera,
                             fechaPermiso, Resolucion)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            fila["peva_codigo"], fila["isp_codigo"], fila["nombreComercial"],
                            fila["opera"], fila["fechaPermiso"], fila["Resolucion"],
                        ),
                    )
                    actualizadas += 1

        _registrar_carga(
            "dimensiones", None, insertadas, actualizadas, "EXITOSO", None, inicio
        )
        logger.info(
            "dim_permiso_va_agregado: %s nuevos, %s nuevas versiones por cambio",
            insertadas, actualizadas,
        )
    except Exception as exc:
        _registrar_carga("dimensiones", None, insertadas, actualizadas, "FALLIDO", str(exc), inicio)
        logger.exception("Error cargando dim_permiso_va_agregado")
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
    cargar_dim_isp()
    cargar_dim_permiso_va_agregado()
