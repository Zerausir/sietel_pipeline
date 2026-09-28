"""
mart/aplicar_capa3.py

Aplica sql/02_ddl_mart.sql completo contra sietel_analitico, como mart_user.
Reemplaza la ejecución manual por SSH + scp + psql -f que se usó para
validar este archivo en producción (28-jul-2026).

POR QUÉ ESTE SCRIPT USA psycopg DIRECTO, NO SQLAlchemy (a diferencia de
detectar_conflictos_peva.py y construir_capa2.py -- ver discusión completa
en el hilo de trabajo, no es una inconsistencia sin explicar):

02_ddl_mart.sql es un archivo de ~2000 líneas con su propio BEGIN;/COMMIT;
embebido, múltiples sentencias, y podría incluir bloques DO $$...$$ en el
futuro. Partirlo en sentencias individuales del lado del cliente (como sí
hace construir_capa2.py, con 8 sentencias simples y conocidas de antemano)
sería frágil aquí: cualquier ";" dentro de un literal de texto o un bloque
$$...$$ rompería el corte. La forma correcta de ejecutar un archivo .sql
completo -- la misma que usa `psql -f` por debajo -- es enviarlo entero al
protocolo simple de PostgreSQL y dejar que el propio servidor lo separe en
sentencias. Eso requiere una conexión psycopg cruda en modo autocommit
(SQLAlchemy normalmente usa el protocolo de sentencias preparadas,
pensado para consultas parametrizadas, no para scripts completos).

autocommit=True en psycopg NO significa "sin transacción" -- solo significa
que psycopg no envuelve cada sentencia en una transacción implícita del
lado del cliente. El BEGIN;/COMMIT; que ya trae el propio archivo sigue
gobernando la transacción real en el servidor, exactamente igual que
cuando se corre con `psql -f` a mano.

Uso:
    python aplicar_capa3.py
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import psycopg

load_dotenv()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RUTA_SQL = Path(__file__).resolve().parent.parent / "sql" / "02_ddl_mart.sql"
RUTA_SQL_CALIDAD = Path(__file__).resolve().parent.parent / "sql" / "04_ddl_calidad.sql"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def _conninfo() -> str:
    return psycopg.conninfo.make_conninfo(
        host=_require_env("ANALITICO_PG_HOST"),
        port=int(os.environ.get("ANALITICO_PG_PORT", "5432")),
        dbname=os.environ.get("ANALITICO_PG_DATABASE", "sietel_analitico"),
        user=_require_env("MART_USER_USER"),
        password=_require_env("MART_USER_PASSWORD"),
    )


def _aplicar_archivo(ruta: Path) -> None:
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontró {ruta} -- ¿el repo está completo en esta ruta?")

    sql_completo = ruta.read_text(encoding="utf-8")
    logger.info("Aplicando %s (%d líneas) contra sietel_analitico como mart_user...",
                ruta.name, sql_completo.count("\n"))

    with psycopg.connect(_conninfo(), autocommit=True, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(sql_completo)

    logger.info("%s aplicado correctamente.", ruta.name)


def aplicar() -> None:
    """Aplica sql/02_ddl_mart.sql (Capa 3 completa)."""
    _aplicar_archivo(RUTA_SQL)


def aplicar_calidad() -> None:
    """
    Aplica sql/04_ddl_calidad.sql (esquema calidad: tablas de workflow
    humano, calidad.vw_pevas_excluidos y permisos) -- AGREGADO 28-sep-2026
    para que ningún cambio a ese archivo dependa de un `psql -f` manual.
    Seguro en cada corrida: el archivo es idempotente (CREATE ... IF NOT
    EXISTS, CREATE OR REPLACE VIEW, GRANT) y NUNCA borra ni recrea las
    tablas con revisiones humanas. Todos los objetos de calidad pertenecen
    a mart_user (verificado en producción 28-sep-2026), así que este mismo
    rol puede aplicarlo.
    """
    _aplicar_archivo(RUTA_SQL_CALIDAD)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)  # sin opciones propias todavía -- placeholder para --dry-run futuro si aplica

    try:
        aplicar()
    except psycopg.Error as exc:
        logger.error("Falló la aplicación de %s: %s", RUTA_SQL.name, exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
