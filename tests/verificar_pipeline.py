"""
Script de verificación del pipeline SIETEL -> PostgreSQL.

No es una suite de unit tests (no hay mocks de SQL Server); son pruebas de
integración que validan, contra el entorno real, que:
  1. Las conexiones a SQL Server y PostgreSQL funcionan.
  2. El DDL de PostgreSQL fue aplicado (existen las tablas/vistas esperadas).
  3. Las dimensiones SCD Tipo 2 no tienen más de una fila vigente por llave
     natural (violación de invariante = bug en cargar_dimensiones.py).
  4. Los totales agregados de hechos cargados coinciden, año por año, con
     los totales correspondientes en SQL Server (detecta filas perdidas o
     duplicadas durante la carga).
  5. La vista de consumo analitico.v_usuarios_cuentas no genera filas
     duplicadas por el JOIN de vigencia temporal (un error común en SCD
     Tipo 2 es un JOIN que matchea contra más de una versión).

Uso:
    python tests/verificar_pipeline.py --anio 2026
    python tests/verificar_pipeline.py --anio 2026 --verbose
"""
import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from config import postgres_cursor, sqlserver_cursor  # noqa: E402

logger = logging.getLogger("verificar_pipeline")

TABLAS_ESPERADAS = [
    "staging.va_reporte_usuarios_cuentas",
    "staging.dim_isp",
    "staging.dim_permiso_va_agregado",
    "staging.control_cargas",
]
VISTAS_ESPERADAS = ["analitico.v_usuarios_cuentas"]


class FalloVerificacion(Exception):
    pass


def verificar_conectividad():
    logger.info("[1/5] Verificando conectividad...")
    try:
        with sqlserver_cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as exc:
        raise FalloVerificacion(f"No se pudo conectar a SQL Server (SIETEL): {exc}")

    try:
        with postgres_cursor(commit=False) as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as exc:
        raise FalloVerificacion(f"No se pudo conectar a PostgreSQL analítico: {exc}")
    logger.info("    OK: ambas conexiones responden.")


def verificar_ddl_aplicado():
    logger.info("[2/5] Verificando que el DDL fue aplicado...")
    with postgres_cursor(commit=False) as cur:
        for tabla in TABLAS_ESPERADAS:
            esquema, nombre = tabla.split(".")
            cur.execute(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
                """,
                (esquema, nombre),
            )
            if cur.fetchone() is None:
                raise FalloVerificacion(f"Tabla esperada no existe: {tabla}. ¿Se corrió sql/01_ddl_postgres.sql?")
        for vista in VISTAS_ESPERADAS:
            esquema, nombre = vista.split(".")
            cur.execute(
                """
                SELECT 1 FROM information_schema.views
                WHERE table_schema = %s AND table_name = %s
                """,
                (esquema, nombre),
            )
            if cur.fetchone() is None:
                raise FalloVerificacion(f"Vista esperada no existe: {vista}")
    logger.info("    OK: todas las tablas y vistas esperadas existen.")


def verificar_unicidad_vigencia():
    logger.info("[3/5] Verificando invariante SCD Tipo 2 (máximo 1 versión vigente por llave natural)...")
    with postgres_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT isp_codigo, COUNT(*) AS n
            FROM staging.dim_isp WHERE es_vigente = true
            GROUP BY isp_codigo HAVING COUNT(*) > 1
            """
        )
        duplicados_isp = cur.fetchall()
        if duplicados_isp:
            raise FalloVerificacion(
                f"dim_isp tiene {len(duplicados_isp)} isp_codigo con más de una versión vigente "
                f"simultánea (ejemplo: {duplicados_isp[0]['isp_codigo']}). Revisar cargar_dimensiones.py."
            )

        cur.execute(
            """
            SELECT peva_codigo, COUNT(*) AS n
            FROM staging.dim_permiso_va_agregado WHERE es_vigente = true
            GROUP BY peva_codigo HAVING COUNT(*) > 1
            """
        )
        duplicados_permiso = cur.fetchall()
        if duplicados_permiso:
            raise FalloVerificacion(
                f"dim_permiso_va_agregado tiene {len(duplicados_permiso)} peva_codigo con más de "
                f"una versión vigente simultánea (ejemplo: {duplicados_permiso[0]['peva_codigo']})."
            )
    logger.info("    OK: invariante de vigencia única se cumple en ambas dimensiones.")


def verificar_totales_anio(anio: int):
    logger.info("[4/5] Verificando totales agregados del año %s (SQL Server vs. PostgreSQL)...", anio)
    with sqlserver_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM dbo.VAReporteUsuariosCuentas WHERE anio = %s", (anio,)
        )
        filas_origen = cur.fetchone()["n"]

    with postgres_cursor(commit=False) as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM staging.va_reporte_usuarios_cuentas WHERE anio = %s", (anio,)
        )
        filas_destino = cur.fetchone()["n"]

    if filas_origen != filas_destino:
        raise FalloVerificacion(
            f"Discrepancia de conteo para año {anio}: SQL Server tiene {filas_origen} filas, "
            f"PostgreSQL tiene {filas_destino}. Revisar si la carga de ese año falló a mitad de "
            f"camino (ver staging.control_cargas) o si se insertaron filas duplicadas/perdidas."
        )
    logger.info("    OK: %s filas en ambos lados para el año %s.", filas_origen, anio)


def verificar_vista_sin_duplicados(anio: int):
    logger.info("[5/5] Verificando que la vista de consumo no duplica filas por el JOIN de vigencia...")
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
        duplicados = cur.fetchall()
        if duplicados:
            raise FalloVerificacion(
                f"La vista analitico.v_usuarios_cuentas devuelve más de una fila para "
                f"{len(duplicados)} ruc_codigo del año {anio} (ejemplo: {duplicados[0]['ruc_codigo']}). "
                f"Esto indica que el JOIN de vigencia temporal contra dim_isp/dim_permiso_va_agregado "
                f"está matcheando más de una versión -- revisar las condiciones de fecha_inicio/"
                f"fecha_fin_vigencia en sql/01_ddl_postgres.sql."
            )
    logger.info("    OK: la vista no produce duplicados para el año %s.", anio)


def main():
    parser = argparse.ArgumentParser(description="Verifica la integridad del pipeline SIETEL -> PostgreSQL.")
    parser.add_argument("--anio", type=int, required=True, help="Año a verificar contra SQL Server, ej. 2026")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    verificaciones = [
        verificar_conectividad,
        verificar_ddl_aplicado,
        verificar_unicidad_vigencia,
        lambda: verificar_totales_anio(args.anio),
        lambda: verificar_vista_sin_duplicados(args.anio),
    ]

    fallos = []
    for verificacion in verificaciones:
        try:
            verificacion()
        except FalloVerificacion as exc:
            logger.error("    FALLO: %s", exc)
            fallos.append(str(exc))

    print()
    if fallos:
        print(f"RESULTADO: {len(fallos)} verificación(es) fallaron.")
        for f in fallos:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("RESULTADO: todas las verificaciones pasaron correctamente.")
        sys.exit(0)


if __name__ == "__main__":
    main()
