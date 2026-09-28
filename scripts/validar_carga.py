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

CAMBIO (22-jul-2026): GROUP BY incompleto en _verificar_vista_sin_duplicados.
------------------------------------------------------------------------------
La verificación de "duplicados" en la vista de consumo agrupaba solo por
(peva_codigo, par_codigo, periodoNumero, tipoEnlace, tipoCliente) -- un
subconjunto de la llave natural real de 8 columnas. nivelComparticion
(14 valores distintos) y portador (138 valores distintos) quedaban fuera
del GROUP BY, así que filas legítimamente distintas que solo difieren en
esas dos columnas se contaban como "duplicados" falsos. Confirmado con
datos reales del año 2011: las 405 "duplicaciones" reportadas eran filas
válidas con distinto nivelComparticion (ej. 4:1, 5:1, 2:1) para el mismo
prestador/parroquia/período/tipoEnlace/tipoCliente. No había ningún
solapamiento real de vigencia en dim_isp / dim_permiso_va_agregado --
consistente con que esta era la primera carga de dimensiones jamás hecha
(todas las versiones insertadas en un solo lote, sin ningún cierre de
vigencia todavía). Corregido agregando nivelComparticion y portador tanto
al SELECT como al GROUP BY, para que la verificación use la llave natural
completa de 8 columnas y no reporte falsos positivos.
"""
import logging
from datetime import datetime

from cargar_hechos_anio import COLUMNAS_HASH, SQL_EXTRAER_HECHOS_ANIO, calcular_hash_fila, MESES_DEL_ANIO
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

    # CAMBIO (28-sep-2026): el hash de destino se RECALCULA desde los
    # valores realmente guardados en Postgres, no se toma hash_contenido tal
    # cual. Antes se comparaba "origen hoy" contra "el hash que Python
    # calculó del origen al cargar" -- una columna de métrica alterada en
    # Postgres después de la carga (UPDATE manual, bug de otro script) pasaba
    # la certificación sin ser detectada. Postgres devuelve las columnas en
    # minúscula; COLUMNAS_HASH usa el nombre de SQL Server.
    columnas_pg = ", ".join(c.lower() for c in COLUMNAS_HASH)
    hashes_destino = {}
    hash_guardado_inconsistente = []
    with postgres_cursor(commit=False) as cur:
        cur.execute(
            f"""
            SELECT {columnas_pg}, hash_contenido
            FROM staging.va_lineas_dedicadas_resumen
            WHERE anio = %s
            """,
            (anio,),
        )
        for r in cur.fetchall():
            valores = {c: r[c.lower()] for c in COLUMNAS_HASH}
            hash_real = calcular_hash_fila(valores)
            key = _make_key(r)
            hashes_destino[key] = hash_real
            if r["hash_contenido"] != hash_real:
                hash_guardado_inconsistente.append(str(key))

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

    # CAMBIO (28-sep-2026): filas en destino que SIETEL ya no produce --
    # antes solo se detectaban indirectamente por el conteo.
    sobrantes = [str(k) for k in hashes_destino.keys() - hashes_origen.keys()]

    return {
        "filas_certificadas": certificadas,
        "filas_con_contenido_distinto": distintas,
        "filas_faltantes_en_destino": faltantes,
        "filas_sobrantes_en_destino": sobrantes,
        "filas_hash_guardado_inconsistente": hash_guardado_inconsistente,
    }


def _certificar_completitud() -> list[str]:
    """
    AGREGADO 28-sep-2026: certifica que TODOS los prestadores de SIETEL
    están en PostgreSQL y que ningún hecho cargado se pierde antes de llegar
    a capa2/mart/dashboard. Antes solo se certificaban los hechos contra
    staging, así que una pérdida entre staging y la vista de consumo pasaba
    sin detectarse (caso real: CNT EP, jul-2015, 2.630 filas descartadas por
    el JOIN al tener el PEVA en minúsculas).

    Comprueba, en ambas direcciones cuando aplica:
      1. dbo.ISP vs staging.dim_isp (versiones vigentes).
      2. dbo.PermisoVAgregado vs staging.dim_permiso_va_agregado (vigentes).
      3. dbo.VAFormularioLineasDedicadas vs staging.va_formulario_lineas_dedicadas.
      4. Para TODOS los años (no solo los recién cargados): filas de
         staging.va_lineas_dedicadas_resumen == filas de
         analitico.v_lineas_dedicadas_resumen. Barato (~1 s): la vista es
         un INNER JOIN que no duplica (_verificar_vista_sin_duplicados),
         así que cualquier diferencia son filas descartadas.

    Los códigos se comparan en MAYÚSCULAS en ambos lados: SQL Server no
    distingue mayúsculas (Modern_Spanish_CI_AS) y el pipeline normaliza
    peva_codigo a mayúsculas.
    """
    problemas = []
    with sqlserver_cursor() as ms:
        ms.execute("SELECT UPPER(isp_codigo) AS k FROM dbo.ISP")
        isp_src = {r["k"] for r in ms.fetchall()}
        ms.execute("SELECT UPPER(peva_codigo) AS k FROM dbo.PermisoVAgregado")
        peva_src = {r["k"] for r in ms.fetchall()}
        ms.execute("SELECT fld_codigo AS k FROM dbo.VAFormularioLineasDedicadas")
        form_src = {r["k"] for r in ms.fetchall()}

    with postgres_cursor(commit=False) as cur:
        cur.execute("SELECT upper(isp_codigo) AS k FROM staging.dim_isp WHERE es_vigente")
        isp_pg = {r["k"] for r in cur.fetchall()}
        cur.execute("SELECT upper(peva_codigo) AS k FROM staging.dim_permiso_va_agregado WHERE es_vigente")
        peva_pg = {r["k"] for r in cur.fetchall()}
        cur.execute("SELECT fld_codigo AS k FROM staging.va_formulario_lineas_dedicadas")
        form_pg = {r["k"] for r in cur.fetchall()}
        cur.execute(
            """
            SELECT s.anio, s.n AS staging, COALESCE(v.n, 0) AS vista
            FROM (SELECT anio, COUNT(*) AS n FROM staging.va_lineas_dedicadas_resumen GROUP BY anio) s
            LEFT JOIN (SELECT anio, COUNT(*) AS n FROM analitico.v_lineas_dedicadas_resumen GROUP BY anio) v
                   USING (anio)
            WHERE s.n <> COALESCE(v.n, 0)
            ORDER BY s.anio
            """
        )
        perdidas_vista = cur.fetchall()

    for nombre, src, pg in (
        ("ISP (dbo.ISP / staging.dim_isp)", isp_src, isp_pg),
        ("PEVA (dbo.PermisoVAgregado / staging.dim_permiso_va_agregado)", peva_src, peva_pg),
        ("Formularios (dbo.VAFormularioLineasDedicadas / staging.va_formulario_lineas_dedicadas)",
         form_src, form_pg),
    ):
        faltan, sobran = sorted(src - pg), sorted(pg - src)
        if faltan:
            problemas.append(f"{nombre}: {len(faltan)} en SIETEL que faltan en PostgreSQL (ej. {faltan[:5]})")
        if sobran:
            problemas.append(f"{nombre}: {len(sobran)} vigentes en PostgreSQL que ya no existen en SIETEL "
                             f"(ej. {sobran[:5]})")
    for r in perdidas_vista:
        problemas.append(
            f"Año {r['anio']}: {r['staging'] - r['vista']} fila(s) de hechos en staging que NO llegan a "
            f"analitico.v_lineas_dedicadas_resumen (se pierden antes de capa2/mart/dashboard)"
        )
    return problemas


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

    IMPORTANTE: el GROUP BY debe usar la llave natural COMPLETA de 8
    columnas (peva_codigo, par_codigo, periodoNumero, anio, tipoEnlace,
    tipoCliente, nivelComparticion, portador). anio ya está fijado por el
    WHERE, así que basta con las 7 restantes. Antes faltaban
    nivelComparticion y portador -- eso hacía que filas legítimamente
    distintas (mismo prestador/parroquia/período/tipoEnlace/tipoCliente,
    pero distinto nivel de compartición o portador) se reportaran como
    "duplicados" falsos. Confirmado con datos reales de 2011 (ver CAMBIO
    22-jul-2026 en el docstring del módulo) antes de aplicar esta
    corrección.
    """
    with postgres_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT peva_codigo, par_codigo, periodoNumero,
                   tipoEnlace, tipoCliente, nivelComparticion, portador, COUNT(*) AS n
            FROM analitico.v_lineas_dedicadas_resumen
            WHERE anio = %s
            GROUP BY peva_codigo, par_codigo, periodoNumero,
                     tipoEnlace, tipoCliente, nivelComparticion, portador
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


def _imprimir_reporte(resultados_por_anio: dict, problemas_vigencia: list,
                      problemas_completitud: list | None = None):
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

    if problemas_completitud:
        print("  Completitud SIETEL -> PostgreSQL -> vista de consumo            ❌")
        for p in problemas_completitud:
            print(f"    ⚠️  {p}")
    else:
        print("  Completitud SIETEL -> PostgreSQL -> vista de consumo            ✅")

    for anio, r in resultados_por_anio.items():
        conteo_ok = r["filas_origen"] == r["filas_destino"]
        contenido_ok = (not r["distintas"] and not r["faltantes"]
                        and not r["sobrantes"] and not r["hash_inconsistente"])
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
        if r["sobrantes"]:
            print(f"      ⚠️  {len(r['sobrantes'])} fila(s) sobrantes en PostgreSQL (SIETEL ya no las produce)")
        if r["hash_inconsistente"]:
            print(f"      ⚠️  {len(r['hash_inconsistente'])} fila(s) con hash_contenido que no coincide con sus valores")
        print(
            f"    Vista analítico.v_lineas_dedicadas_resumen sin duplicados"
            f"{'  ✅' if vista_ok else '  ❌'}"
        )
        if r["duplicados_vista"]:
            print(f"      ⚠️  {len(r['duplicados_vista'])} combinación(es) duplicada(s)")

    print(f"{'=' * 70}")
    todo_ok = (
            not problemas_vigencia
            and not problemas_completitud
            and all(
        r["filas_origen"] == r["filas_destino"]
        and not r["distintas"]
        and not r["faltantes"]
        and not r["sobrantes"]
        and not r["hash_inconsistente"]
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
         valores, no solo de cantidad), recalculado mes a mes en origen y
         desde los valores guardados en destino; sin filas faltantes ni
         sobrantes, y hash_contenido consistente con sus propios valores.
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

    print("\nCertificando completitud SIETEL -> PostgreSQL -> vista de consumo...")
    problemas_completitud = _certificar_completitud()
    errores.extend(problemas_completitud)

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

        if cert["filas_sobrantes_en_destino"]:
            errores.append(
                f"Año {anio}: {len(cert['filas_sobrantes_en_destino'])} fila(s) "
                f"existen en PostgreSQL pero SIETEL ya no las produce "
                f"(ej. {cert['filas_sobrantes_en_destino'][0]})."
            )

        if cert["filas_hash_guardado_inconsistente"]:
            errores.append(
                f"Año {anio}: {len(cert['filas_hash_guardado_inconsistente'])} fila(s) "
                f"cuyo hash_contenido no coincide con sus propios valores guardados "
                f"(posible edición por fuera del pipeline, "
                f"ej. {cert['filas_hash_guardado_inconsistente'][0]})."
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
            "sobrantes": cert["filas_sobrantes_en_destino"],
            "hash_inconsistente": cert["filas_hash_guardado_inconsistente"],
            "duplicados_vista": duplicados_vista,
        }

    _imprimir_reporte(resultados_por_anio, problemas_vigencia, problemas_completitud)

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
