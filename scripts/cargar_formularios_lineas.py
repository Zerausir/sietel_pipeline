"""
Carga de dbo.VAFormularioLineasDedicadas -> staging.va_formulario_lineas_dedicadas.

AGREGADO 28-sep-2026. Es la cabecera de cada entrega trimestral del
formulario de líneas dedicadas, y el ÚNICO lugar de SIETEL donde queda
registrada una declaración "sin servicio" (tieneServicio='No',
numeroRegistros=0): esa entrega no genera ninguna fila en
dbo.VALineasDedicadas, así que el resto del pipeline no podía distinguir a
un prestador que declara formalmente que aún no tiene servicio (típico en
su primer año de permiso) de uno que nunca entregó nada. Caso que lo
reveló: DIGITEC S.A. Decisión de Mercados: clasificarlos como "sin
servicio", no como incumplimiento (ver mart.vw_prestadores_sin_reportar).

Snapshot completo en cada corrida (DELETE + INSERT en una sola
transacción): ~38K filas, sin historia que preservar -- SIETEL es la fuente
de verdad y el formulario puede corregirse en origen. peva_codigo se
normaliza a MAYÚSCULAS, mismo criterio que cargar_hechos_anio.py.
"""
import logging
from datetime import datetime

from psycopg2.extras import execute_values

from config import postgres_cursor, sqlserver_cursor

logger = logging.getLogger(__name__)

SQL_EXTRAER_FORMULARIOS = """
    SELECT
        fld_codigo,
        UPPER(peva_codigo) AS peva_codigo,
        anio, periodoNumero, periodoNombre,
        tieneServicio, numeroRegistros,
        fechaCarga, fechaModificacion, regional
    FROM dbo.VAFormularioLineasDedicadas
"""

COLUMNAS = [
    "fld_codigo", "peva_codigo", "anio", "periodoNumero", "periodoNombre",
    "tieneServicio", "numeroRegistros", "fechaCarga", "fechaModificacion", "regional",
]


def cargar_formularios_lineas():
    inicio = datetime.now()
    try:
        with sqlserver_cursor() as ms_cur:
            ms_cur.execute(SQL_EXTRAER_FORMULARIOS)
            filas = ms_cur.fetchall()

        # Protección: con 0 filas en origen no se vacía el destino -- lo más
        # probable es una falla de la fuente, no que SIETEL haya borrado
        # todos los formularios de su historia.
        if not filas:
            raise RuntimeError(
                "dbo.VAFormularioLineasDedicadas devolvió 0 filas -- se aborta para no vaciar "
                "staging.va_formulario_lineas_dedicadas por una posible falla de la fuente."
            )

        with postgres_cursor() as pg_cur:
            pg_cur.execute("DELETE FROM staging.va_formulario_lineas_dedicadas")
            execute_values(
                pg_cur,
                f"INSERT INTO staging.va_formulario_lineas_dedicadas ({', '.join(COLUMNAS)}) VALUES %s",
                [tuple(f[c] for c in COLUMNAS) for f in filas],
                page_size=5000,
            )

        sin_servicio = sum(1 for f in filas if f["tieneServicio"] == "No")
        _registrar_carga("formularios_lineas", len(filas), "EXITOSO", None, inicio)
        logger.info(
            "staging.va_formulario_lineas_dedicadas: %s formularios cargados (%s declaran 'sin servicio').",
            len(filas), sin_servicio,
        )
    except Exception as exc:
        _registrar_carga("formularios_lineas", 0, "FALLIDO", str(exc), inicio)
        logger.exception("Error cargando formularios de líneas dedicadas")
        raise


def _registrar_carga(tipo_carga, insertadas, estado, mensaje_error, fecha_inicio):
    with postgres_cursor() as cur:
        cur.execute(
            """
            INSERT INTO staging.control_cargas
                (tipo_carga, anio, filas_insertadas, filas_actualizadas,
                 estado, mensaje_error, fecha_inicio)
            VALUES (%s, NULL, %s, 0, %s, %s, %s)
            """,
            (tipo_carga, insertadas, estado, mensaje_error, fecha_inicio),
        )


if __name__ == "__main__":
    cargar_formularios_lineas()
