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

CAMBIO (16-jul-2026): certificación mes a mes.
-----------------------------------------------
cargar_hechos_anio.SQL_EXTRAER_HECHOS_ANIO cambió su firma de parámetros
de (anio,) a (anio, periodoNumero) para poder particionar la carga por
mes (ver cargar_hechos_anio.py). _certificar_contenido_por_anio importaba
y ejecutaba esa misma consulta con un solo parámetro -- sin este cambio,
la validación cruzada habría quedado rota (error de parámetros ODBC) la
próxima vez que corriera, de forma silenciosa hasta que fallara.

Este archivo ahora:
  1. Recalcula la certificación de contenido iterando los 12 meses,
     igual que la carga, en vez de un solo WHERE anio = ?.
  2. Imprime un reporte consolidado al final de validar_anios(), en el
     mismo estilo que el paso pipeline_validation de samm_pipeline
     (conteos + ✅/❌ por chequeo), en vez de solo lanzar una excepción
     con texto concatenado.
"""
import logging
from datetime import datetime

from cargar_hechos_anio import SQL_EXTRAER_HECHOS_ANIO, calcular_hash_fila, MESES_DEL_ANIO
from config import postgres_cursor, sqlserver_cursor

logger = logging.getLogger(__name__)


class ValidacionFallida(Exception):
    pass


def _contar_sqlserver_por_anio(anio: int) -> int:
    """
    Cuenta el número de filas del agregado (no del detalle crudo)
    que SQL Server produciría para el año dado. Equivale a contar
    combinaciones únicas del GROUP BY del SQL_EXTRAER_HECHOS_ANIO.

    Esta consulta es independiente de SQL_EXTRAER_HECHOS_ANIO (tiene su
    propio texto SQL con WHERE anio = ? solamente) -- no se ve afectada
    por el cambio de firma a (anio, mes) del punto anterior.
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
    Recalcula el hash del agregado desde SQL Server -- mes a mes, igual
    que la carga en cargar_hechos_anio.py -- y compara contra los hashes
    almacenados en Postgres al momento de la carga.

    Detecta tres tipos de discrepancia:
    - filas_con_contenido_distinto: misma llave natural, hash diferente
      (las métricas cambiaron en SQL Server después de la carga, o la
      carga insertó un valor incorrecto)
    - filas_faltantes_en_destino: existen en SQL Server pero no en Postgres
      (no debería ocurrir si el conteo ya coincidió, pero se verifica
      explícitamente para no asumir)
    """
    hashes_origen = {}
    with sqlserver_cursor() as cur:
        for mes in MESES_DEL_ANIO:
            cur.execute(SQL_EXTRAER_HECHOS_ANIO, (anio, mes))
            for f in cur.fetchall():
                hashes_origen[_make_key(f)] = calcular_hash_fila(f)

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


def _imprimir_reporte(resultados_por_anio: dict, problemas_vigencia: list):
    """
    Reporte consolidado al estilo pipeline_validation de samm_pipeline:
    conteos + ✅/❌ por chequeo, en vez de solo una excepción con texto
    concatenado. Se imprime siempre (éxito o fallo) para que quede
    visible en los logs de la tarea de Airflow.
    """
    print(f"\n{'=' * 70}")
    print("📊 REPORTE DE VALIDACIÓN — SIETEL PIPELINE")
    print(f"{'=' * 70}")

    if problemas_vigencia:
        print("  Dimensiones SCD (vigencia única)                                 ❌")
        for p in problemas_vigencia:
            print(f"    ⚠️  {p}")
    else:
        print("  Dimensiones SCD (vigencia única)                                 ✅")

    for anio, r in resultados_por_anio.items():
        conteo_ok = r["filas_origen"] == r["filas_destino"]
        contenido_ok = not r["distintas"] and not r["faltantes"]
        vista_ok = not r["duplicados_vista"]

        print(f"  ── Año {anio} " + "─" * (58 - len(str(anio))))
        print(
            f"    Conteo filas agregadas: {r['filas_origen']:,} (SQL Server) / "
            f"{r['filas_destino']:,} (PostgreSQL)"
            f"{'  ✅' if conteo_ok else '  ❌'}"
        )
        print(
            f"    Certificación de contenido (hash MD5): "
            f"{r['certificadas']:,}/{r['filas_origen']:,} idénticas"
            f"{'  ✅' if contenido_ok else '  ❌'}"
        )
        if r["distintas"]:
            print(f"      ⚠️  {len(r['distintas'])} fila(s) con contenido distinto")
        if r["faltantes"]:
            print(f"      ⚠️  {len(r['faltantes'])} fila(s) faltantes en PostgreSQL")
        print(
            f"    Vista analítico.v_lineas_dedicadas_resumen sin duplicados"
            f"{'  ✅' if vista_ok else '  ❌'}"
        )
        if r["duplicados_vista"]:
            print(f"      ⚠️  {len(r['duplicados_vista'])} combinación(es) duplicada(s)")

    print(f"{'=' * 70}")
    todo_ok = (
            not problemas_vigencia
            and all(
        r["filas_origen"] == r["filas_destino"]
        and not r["distintas"]
        and not r["faltantes"]
        and not r["duplicados_vista"]
        for r in resultados_por_anio.values()
    )
    )
    if todo_ok:
        print("✅ ESTADO: Validación cruzada exitosa — datos certificados como consistentes")
    else:
        print("❌ ESTADO: Validación cruzada encontró discrepancias — ver detalle arriba")
    print(f"{'=' * 70}\n")


def validar_anios(anios: list[int]):
    """
    Valida, para cada año recién cargado:
      1. Conteo de filas agregadas idéntico entre SQL Server y PostgreSQL.
      2. Hash MD5 de contenido idéntico fila a fila (certificación real de
         valores, no solo de cantidad), recalculado mes a mes.
      3. Dimensiones SCD Tipo 2 sin versiones vigentes duplicadas.
      4. Vista de consumo sin duplicados por JOIN de vigencia temporal.

    Lanza ValidacionFallida si encuentra cualquier discrepancia, haciendo
    que la tarea de Airflow quede roja en la UI en vez de silenciar el error.
    Registra el resultado en staging.control_cargas para auditoría histórica.
    Imprime siempre el reporte consolidado, haya o no errores.
    """
    inicio = datetime.now()
    errores = []
    resultados_por_anio = {}

    problemas_vigencia = _verificar_unicidad_vigencia()
    if problemas_vigencia:
        errores.extend(problemas_vigencia)

    for anio in anios:
        print(f"\nValidando año {anio}...")

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

        print(f"  Certificando contenido mes a mes (12 consultas a SQL Server)...")
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

        resultados_por_anio[anio] = {
            "filas_origen": filas_origen,
            "filas_destino": filas_destino,
            "certificadas": cert["filas_certificadas"],
            "distintas": cert["filas_con_contenido_distinto"],
            "faltantes": cert["filas_faltantes_en_destino"],
            "duplicados_vista": duplicados_vista,
        }

    _imprimir_reporte(resultados_por_anio, problemas_vigencia)

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
