"""
sincronizar_codigos_administrativos.py — Alinea codigo_provincia,
codigo_ciudad y codigo_parroquia en staging.va_lineas_dedicadas_resumen
con el estado actual de dbo.Provincia/Ciudad/Parroquia en SQL Server,
SIN re-ejecutar la agregación completa de cargar_hechos_anio.py.

Por qué esto es seguro y mucho más barato que un reload completo:
------------------------------------------------------------------
Los tres códigos dependen ÚNICAMENTE de par_codigo (jerarquía
administrativa fija: parroquia -> ciudad/cantón -> provincia). No
dependen de periodoNumero, tipoEnlace, tipoCliente, ni ninguna otra
columna del agregado. Eso significa que el mapeo completo
(par_codigo -> codigo_provincia, codigo_ciudad, codigo_parroquia) es
pequeño y estático -- una fila por parroquia existente en SIETEL
(miles, no millones) -- y se puede traer de SQL Server UNA sola vez,
sin volver a escanear ni re-agregar dbo.VALineasDedicadas para cada
año histórico ya cargado.

NO es un script de un solo uso: es idempotente y reutilizable cada vez
que sea necesario re-sincronizar (ej. si INEC/SIETEL corrigen un código
de provincia/cantón/parroquia en el futuro) -- correrlo de nuevo no
duplica nada, solo actualiza. Vive permanentemente en scripts/, igual
que aplicar_esquema.py/cargar_dimensiones.py/validar_carga.py -- se
invoca por CLI bajo demanda, no está cableado al DAG.

NOTA (22-jul-2026): este UPDATE no toca hash_contenido -- por diseño,
codigo_provincia/ciudad/parroquia no están en COLUMNAS_HASH (ver
cargar_hechos_anio.py). Esto también significa que el trigger
staging.fn_registrar_correccion_resumen (definido en 01_ddl_postgres.sql)
NO va a generar entradas en staging.historial_correcciones cuando este
script corre -- correcto, porque esta sincronización no es una
"corrección de contenido", es completar/alinear metadata administrativa.

Este script NO reemplaza volver a correr cargar_hechos_anio(anio) para
años NUEVOS que aún no se han cargado -- esos ya traen los códigos
desde el primer INSERT, con la versión actualizada de
SQL_EXTRAER_HECHOS_ANIO. Este script es para el backfill inicial (años
ya cargados antes del 22-jul-2026) y para cualquier resincronización
futura si los códigos administrativos cambian en el origen.

Uso:
    python sincronizar_codigos_administrativos.py
"""
import logging
from datetime import datetime

from psycopg2.extras import execute_batch

from config import postgres_cursor, sqlserver_cursor

logger = logging.getLogger(__name__)

SQL_MAPEO_CODIGOS = """
    SELECT
        par.par_codigo,
        prov.codigo         AS codigo_provincia,
        ciu.codigoCiudad    AS codigo_ciudad,
        par.codigoParroquia AS codigo_parroquia
    FROM dbo.Parroquia par
    LEFT JOIN dbo.Ciudad    ciu  ON ciu.ciu_codigo  = par.ciu_codigo
    LEFT JOIN dbo.Provincia prov ON prov.pro_codigo = ciu.pro_codigo
"""

SQL_UPDATE_BACKFILL = """
    UPDATE staging.va_lineas_dedicadas_resumen
    SET codigo_provincia = %s,
        codigo_ciudad    = %s,
        codigo_parroquia = %s
    WHERE par_codigo = %s
"""


def sincronizar_codigos_administrativos():
    inicio = datetime.now()
    print(f"\n{'=' * 60}")
    print("SINCRONIZACIÓN — codigo_provincia / codigo_ciudad / codigo_parroquia")
    print(f"{'=' * 60}")

    print("Extrayendo mapeo par_codigo -> codigos de SQL Server...")
    with sqlserver_cursor() as ms_cur:
        ms_cur.execute(SQL_MAPEO_CODIGOS)
        mapeo = ms_cur.fetchall()

    print(f"  {len(mapeo):,} parroquias encontradas en SQL Server.")

    tuplas = [
        (fila["codigo_provincia"], fila["codigo_ciudad"],
         fila["codigo_parroquia"], fila["par_codigo"])
        for fila in mapeo
    ]

    print("Aplicando UPDATE por lotes en PostgreSQL...")
    with postgres_cursor() as pg_cur:
        execute_batch(pg_cur, SQL_UPDATE_BACKFILL, tuplas, page_size=500)

        # Verificación: cuántas filas quedaron sin código tras el backfill
        # (esperado: 0, salvo par_codigo huérfanos que no existan en
        # dbo.Parroquia -- dato a investigar aparte si aparece).
        pg_cur.execute(
            "SELECT COUNT(*) AS n FROM staging.va_lineas_dedicadas_resumen "
            "WHERE codigo_parroquia IS NULL"
        )
        sin_codigo = pg_cur.fetchone()["n"]

    duracion = (datetime.now() - inicio).total_seconds()
    print(f"{'-' * 60}")
    print(f"✅ Backfill completo en {duracion:.1f}s")
    if sin_codigo:
        print(f"⚠️  {sin_codigo:,} filas siguen sin codigo_parroquia -- "
              f"revisar par_codigo huérfanos (no existen en dbo.Parroquia)")
    else:
        print("   Todas las filas tienen codigo_parroquia asignado.")
    print(f"{'=' * 60}\n")

    logger.info(
        "Sincronización de códigos administrativos completa: %s parroquias mapeadas, "
        "%s filas sin código tras la sincronización.",
        len(mapeo), sin_codigo,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    sincronizar_codigos_administrativos()
