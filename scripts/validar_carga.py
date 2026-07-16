"""
Validación cruzada SQL Server vs PostgreSQL para el módulo de hechos
pre-agregados (staging.va_lineas_dedicadas_resumen).

Recalcula el mismo agregado desde SQL Server y compara contra lo
almacenado en Postgres — certifica que el valor de cada fila agregada
es idéntico al origen, no solo que el COUNT de filas coincide.

La clave de comparación es la llave natural del agregado:
(peva_codigo, par_codigo, periodoNumero, anio, tipoEnlace,
 tipoCliente, nivelComparticion, portador)
que coincide con la CONSTRAINT uq_resumen_natural definida en el DDL.
"""
import logging
from datetime import datetime

from cargar_hechos_anio import SQL_EXTRAER_HECHOS_ANIO, calcular_hash_fila
from config import postgres_cursor, sqlserver_cursor

logger = logging.getLogger(__name__)


class ValidacionFallida(Exception):
    pass


def _contar_sqlserver_por_anio(anio: int) -> int:
    """
    Cuenta el número de filas del agregado (no del detalle crudo)
    que SQL Server produciría para el año dado. Equivale a contar
    combinaciones únicas del GROUP BY del SQL_EXTRAER_HECHOS_ANIO.
    """
    with sqlserver_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS n FROM (
                SELECT peva_codigo, par_codigo, periodoNumero, anio,
                       tipoEnlace, tipoCliente, nivelComparticion, portador
                FROM dbo.VALineasDedicadas
                WHERE anio = ?
                GROUP BY peva_codigo, par_codigo, periodoNumero, anio,
                         tipoEnlace, tipoCliente, nivelComparticion, portador
            ) AS agg
            """,
            (anio,),
        )
        return cur.fetchone()["n"]


def _contar_postgres_por_anio(anio: int) -> int:
    with postgres_cursor(commit=False) as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM staging.va_lineas_dedicadas_resumen WHERE anio = %s",
            (anio,),
        )
        return cur.fetchone()["n"]


def _make_key(fila: dict) -> tuple:
    """
    Construye la llave natural del agregado desde una fila, tanto de
    SQL Server como de Postgres. Los campos de texto pueden venir como
    None — se normalizan a la cadena 'NULL' para comparación consistente.
    """
    return (
        fila.get("peva_codigo") or "NULL",
        fila.get("par_codigo") or "NULL",
        fila.get("periodoNumero") or fila.get("periodonumero"),
        fila.get("anio"),
        str(fila.get("tipoEnlace") or fila.get("tipoenlace") or "NULL"),
        str(fila.get("tipoCliente") or fila.get("tipocliente") or "NULL"),
        str(fila.get("nivelComparticion") or fila.get("nivelcomparticion") or "NULL"),
        str(fila.get("portador") or "NULL"),
    )


def _certificar_contenido_por_anio(anio: int) -> dict:
    """
    Recalcula el hash del agregado desde SQL Server y compara contra
    los hashes almacenados en Postgres al momento de la carga.

    Detecta tres tipos de discrepancia:
    - filas_con_contenido_distinto: misma llave natural, hash diferente
      (las métricas cambiaron en SQL Server después de la carga, o la
      carga insertó un valor incorrecto)
    - filas_faltantes_en_destino: existen en SQL Server pero no en Postgres
      (no debería ocurrir si el conteo ya coincidió, pero se verifica
      explícitamente para no asumir)
    """
    with sqlserver_cursor() as cur:
        cur.execute(SQL_EXTRAER_HECHOS_ANIO, (anio,))
        filas_origen = cur.fetchall()

    hashes_origen = {
        _make_key(f): calcular_hash_fila(f)
        for f in filas_origen
    }

    with postgres_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT peva_codigo, par_codigo, periodonumero, anio,
                   tipoenlace, tipocliente, nivelcomparticion, portador,
                   hash_contenido
            FROM staging.va_lineas_dedicadas_resumen
            WHERE anio = %s
            """,
            (anio,),
        )
        hashes_destino = {
            _make_key(r): r["hash_contenido"]
            for r in cur.fetchall()
        }

    certificadas = 0
    distintas = []
    faltantes = []

    for key, hash_o in hashes_origen.items():
        hash_d = hashes_destino.get(key)
        if hash_d is None:
            faltantes.append(str(key))
        elif hash_d != hash_o:
            distintas.append(str(key))
        else:
            certificadas += 1

    return {
        "filas_certificadas": certificadas,
        "filas_con_contenido_distinto": distintas,
        "filas_faltantes_en_destino": faltantes,
    }


def _verificar_unicidad_vigencia():
    """
    Verifica que las dimensiones SCD Tipo 2 no tengan más de una versión
    vigente por llave natural. Una violación indica un bug en
    cargar_dimensiones.py, no un problema de datos de origen.
    """
    problemas = []
    with postgres_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT isp_codigo, COUNT(*) AS n FROM staging.dim_isp
            WHERE es_vigente = true
            GROUP BY isp_codigo
            HAVING COUNT(*) > 1
            """
        )
        dup = cur.fetchall()
        if dup:
            problemas.append(
                f"dim_isp: {len(dup)} isp_codigo con más de una versión vigente"
            )

        cur.execute(
            """
            SELECT peva_codigo, COUNT(*) AS n FROM staging.dim_permiso_va_agregado
            WHERE es_vigente = true
            GROUP BY peva_codigo
            HAVING COUNT(*) > 1
            """
        )
        dup = cur.fetchall()
        if dup:
            problemas.append(
                f"dim_permiso_va_agregado: {len(dup)} peva_codigo con más de una versión vigente"
            )
    return problemas


def _verificar_vista_sin_duplicados(anio: int):
    """
    Verifica que la vista de consumo no duplique combinaciones por el JOIN
    de vigencia temporal con las dimensiones SCD Tipo 2.
    Una fila duplicada en la vista indica que el JOIN matchea más de una
    versión de dimensión para el mismo período de hecho.
    """
    with postgres_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT peva_codigo, par_codigo, periodoNumero,
                   tipoEnlace, tipoCliente, COUNT(*) AS n
            FROM analitico.v_lineas_dedicadas_resumen
            WHERE anio = %s
            GROUP BY peva_codigo, par_codigo, periodoNumero,
                     tipoEnlace, tipoCliente
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
      1. Conteo de filas agregadas idéntico entre SQL Server y PostgreSQL.
      2. Hash MD5 de contenido idéntico fila a fila (certificación real de
         valores, no solo de cantidad).
      3. Dimensiones SCD Tipo 2 sin versiones vigentes duplicadas.
      4. Vista de consumo sin duplicados por JOIN de vigencia temporal.

    Lanza ValidacionFallida si encuentra cualquier discrepancia, haciendo
    que la tarea de Airflow quede roja en la UI en vez de silenciar el error.
    Registra el resultado en staging.control_cargas para auditoría histórica.
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
                f"Año {anio}: SQL Server tiene {filas_origen} filas agregadas, "
                f"PostgreSQL tiene {filas_destino} "
                f"(discrepancia de {abs(filas_origen - filas_destino)})"
            )
        else:
            logger.info("Año %s: %s filas agregadas en ambos lados, OK.", anio, filas_origen)

        cert = _certificar_contenido_por_anio(anio)
        logger.info(
            "Año %s: %s filas certificadas con contenido idéntico al origen.",
            anio, cert["filas_certificadas"],
        )

        if cert["filas_con_contenido_distinto"]:
            errores.append(
                f"Año {anio}: {len(cert['filas_con_contenido_distinto'])} fila(s) "
                f"tienen contenido DISTINTO entre SQL Server y PostgreSQL "
                f"(los valores de las métricas no coinciden con el origen)."
            )

        if cert["filas_faltantes_en_destino"]:
            errores.append(
                f"Año {anio}: {len(cert['filas_faltantes_en_destino'])} fila(s) "
                f"existen en SQL Server pero no en PostgreSQL."
            )

        duplicados_vista = _verificar_vista_sin_duplicados(anio)
        if duplicados_vista:
            errores.append(
                f"Año {anio}: la vista analitico.v_lineas_dedicadas_resumen "
                f"devuelve duplicados en {len(duplicados_vista)} combinación(es) "
                f"(JOIN de vigencia temporal matchea más de una versión de dimensión)."
            )

    if errores:
        mensaje = "; ".join(errores)
        for anio in anios:
            _registrar_resultado(anio, "FALLIDO", mensaje, inicio)
        raise ValidacionFallida(
            f"Validación cruzada encontró {len(errores)} problema(s): {mensaje}"
        )

    for anio in anios:
        _registrar_resultado(anio, "EXITOSO", None, inicio)
    logger.info(
        "Validación cruzada (conteo + contenido + dimensiones + vista) "
        "exitosa para los años: %s", anios
    )


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    parser = argparse.ArgumentParser(
        description="Valida SQL Server vs PostgreSQL para los años dados."
    )
    parser.add_argument(
        "--anios", type=int, nargs="+", required=True,
        help="Años a validar, ej. --anios 2024 2025"
    )
    args = parser.parse_args()
    validar_anios(args.anios)
