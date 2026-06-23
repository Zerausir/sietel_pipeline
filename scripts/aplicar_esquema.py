"""
Aplica el esquema de PostgreSQL (staging + analitico) de forma idempotente.

Este script ejecuta el archivo sql/01_ddl_postgres.sql completo contra la
base de datos analítica en cada corrida del DAG. Es seguro ejecutarlo
repetidamente porque el propio DDL está escrito con cláusulas idempotentes
(CREATE TABLE IF NOT EXISTS, CREATE INDEX IF NOT EXISTS, CREATE OR REPLACE
VIEW): si el esquema ya existe y tiene datos, este script no lo destruye
ni lo recrea -- simplemente no hace nada en las tablas que ya existen.

IMPORTANTE: este script asume que la base de datos (ej. "sietel_analitico")
YA EXISTE. PostgreSQL no permite crear una base de datos desde dentro de
una conexión que ya apunta a otra base, así que la creación de la base en
sí es un paso manual de aprovisionamiento de infraestructura, no algo que
este pipeline automatice. Ver README para el comando de creación inicial.
"""
import logging
import os

from config import postgres_cursor

logger = logging.getLogger(__name__)

_DDL_PATH = os.path.join(os.path.dirname(__file__), "..", "sql", "01_ddl_postgres.sql")


def aplicar_esquema():
    """
    Lee sql/01_ddl_postgres.sql y lo ejecuta completo contra la base
    analítica. Idempotente: seguro de correr en cada ejecución del DAG.
    """
    if not os.path.exists(_DDL_PATH):
        raise RuntimeError(
            f"No se encontró el archivo de DDL en {_DDL_PATH}. "
            f"Verifica que sql/01_ddl_postgres.sql esté presente en el proyecto "
            f"y que el volumen de Docker lo monte correctamente."
        )

    with open(_DDL_PATH, "r", encoding="utf-8") as f:
        ddl_sql = f.read()

    with postgres_cursor() as cur:
        cur.execute(ddl_sql)

    logger.info("Esquema de PostgreSQL aplicado correctamente (staging + analitico).")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    aplicar_esquema()
