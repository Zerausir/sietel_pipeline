"""
Aplica sql/12_ddl_siger.sql como siger_user y sincroniza
siger.parametro_universo_sai desde IDSTH_UNIVERSO_SAI, en una sola
transacción. Idempotente: seguro en cada corrida de dags/siger_pipeline.py
(mismo patrón que scripts/aplicar_esquema.py para staging/analitico).

No crea el esquema siger: debe existir y ser de siger_user (el DDL falla con
un mensaje claro si no -- ver sql/11_roles_siger.sql).
"""
import logging
import os

from psycopg2.extras import execute_values

from config_siger import IDSTH_UNIVERSO_SAI, postgres_cursor

logger = logging.getLogger(__name__)

_DDL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sql", "12_ddl_siger.sql")


def aplicar_esquema_siger():
    if not os.path.exists(_DDL_PATH):
        raise RuntimeError(
            f"No se encontró el DDL en {_DDL_PATH}. Verifica que sql/12_ddl_siger.sql esté en el "
            f"proyecto y que el volumen de Docker lo monte."
        )
    with open(_DDL_PATH, "r", encoding="utf-8") as f:
        ddl_sql = f.read()

    with postgres_cursor() as cur:
        cur.execute(ddl_sql)
        cur.execute("DELETE FROM siger.parametro_universo_sai")
        execute_values(
            cur,
            "INSERT INTO siger.parametro_universo_sai (idsth, descripcion) VALUES %s",
            sorted(IDSTH_UNIVERSO_SAI.items()),
        )

    logger.info(
        "Esquema siger aplicado; universo SAI = IDSTH %s.", sorted(IDSTH_UNIVERSO_SAI)
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    aplicar_esquema_siger()
