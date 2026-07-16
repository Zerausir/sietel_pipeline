"""
Script de verificación del pipeline SIETEL -> PostgreSQL.

No es una suite de unit tests (no hay mocks de SQL Server); son pruebas de
integración que validan, contra el entorno real, que:
  1. Las conexiones a SQL Server y PostgreSQL funcionan.
  2. El DDL de PostgreSQL fue aplicado (existen las tablas/vistas esperadas
     del módulo "Usuarios y Cuentas — Internet Fijo" basado en
     dbo.VALineasDedicadas).
  3. La validación cruzada certificada pasa para el/los año(s) indicado(s):
     conteo de filas agregadas, hash MD5 de contenido fila a fila,
     invariante de vigencia única en las dimensiones SCD Tipo 2, y ausencia
     de duplicados en la vista de consumo.

     Este paso delega en scripts/validar_carga.validar_anios() -- la misma
     función que corre dentro de la tarea `validar_carga` del DAG -- en vez
     de reimplementar la comparación. Antes este script tenía su propia
     copia de la verificación de conteo/vista, y esa copia apuntaba a
     dbo.VAReporteUsuariosCuentas / analitico.v_usuarios_cuentas, tablas de
     un módulo anterior que ya no existen en el esquema actual (el pipeline
     migró su fuente a dbo.VALineasDedicadas -- ver
     Informe_Hallazgos_SIETEL.docx sobre por qué VAReporteUsuariosCuentas
     se descartó como fuente auditable). Esa copia quedó obsoleta y
     fallaría en el paso de verificación de DDL contra el esquema vigente.

Uso:
    python tests/verificar_pipeline.py --anios 2026
    python tests/verificar_pipeline.py --anios 2024 2025 2026 --verbose

CAMBIO DE INTERFAZ: antes era `--anio <int>` (un solo año). Ahora es
`--anios <int> [<int> ...]` (uno o más años), para poder pasarle a
validar_anios() la misma lista de años que recibiría la tarea del DAG.
"""
import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from config import postgres_cursor, sqlserver_cursor  # noqa: E402
from validar_carga import validar_anios, ValidacionFallida  # noqa: E402

logger = logging.getLogger("verificar_pipeline")

TABLAS_ESPERADAS = [
    "staging.va_lineas_dedicadas_resumen",
    "staging.dim_isp",
    "staging.dim_permiso_va_agregado",
    "staging.control_cargas",
]
VISTAS_ESPERADAS = ["analitico.v_lineas_dedicadas_resumen"]


class FalloVerificacion(Exception):
    pass


def verificar_conectividad():
    logger.info("[1/3] Verificando conectividad...")
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
    logger.info("[2/3] Verificando que el DDL fue aplicado...")
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


def verificar_validacion_cruzada(anios: list[int]):
    """
    Delega en validar_carga.validar_anios(): conteo + hash MD5 de contenido
    + invariante SCD Tipo 2 + vista sin duplicados, para cada año en anios.
    Es la misma certificación que corre la tarea `validar_carga` del DAG.
    """
    logger.info("[3/3] Corriendo validación cruzada certificada para año(s) %s...", anios)
    validar_anios(anios)
    logger.info("    OK: validación cruzada certificada exitosa para %s.", anios)


def main():
    parser = argparse.ArgumentParser(description="Verifica la integridad del pipeline SIETEL -> PostgreSQL.")
    parser.add_argument(
        "--anios", type=int, nargs="+", required=True,
        help="Año(s) a verificar contra SQL Server, ej. --anios 2026 o --anios 2024 2025 2026",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    fallos = []

    for verificacion in (verificar_conectividad, verificar_ddl_aplicado):
        try:
            verificacion()
        except FalloVerificacion as exc:
            logger.error("    FALLO: %s", exc)
            fallos.append(str(exc))

    # Solo corre la validación certificada si conectividad y DDL están OK;
    # si esos fallan, correr validar_anios solo produciría el mismo error
    # de conexión o de tabla inexistente, con menos contexto.
    if not fallos:
        try:
            verificar_validacion_cruzada(args.anios)
        except ValidacionFallida as exc:
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
