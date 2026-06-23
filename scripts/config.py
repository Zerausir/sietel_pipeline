"""
Configuración y conexiones del pipeline SIETEL -> PostgreSQL.

Todas las credenciales se leen de variables de entorno (ver .env.example).
No se deben hardcodear credenciales en ningún script de este proyecto.
"""
import os
import logging
from contextlib import contextmanager

import pyodbc
import psycopg2
import psycopg2.extras

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Falta la variable de entorno requerida: {name}. "
            f"Revisa el archivo .env o la configuración de Airflow Connections."
        )
    return value


def get_sqlserver_connection():
    """
    Abre una conexión a SQL Server (SIETEL) usando pyodbc + el driver ODBC 18
    de Microsoft.

    Se eligió pyodbc sobre pymssql porque el servidor SIETEL exige una
    negociación TLS que FreeTDS (usado internamente por pymssql) rechaza
    durante el handshake, incluso con conectividad de red y credenciales
    correctas confirmadas. SSMS sí conecta porque usa el mismo stack TLS
    que el driver ODBC oficial de Microsoft.
    """
    driver = os.environ.get("SIETEL_SQLSERVER_ODBC_DRIVER", "ODBC Driver 18 for SQL Server")
    host = _require_env("SIETEL_SQLSERVER_HOST")
    port = os.environ.get("SIETEL_SQLSERVER_PORT", "1433")
    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={host},{port};"
        f"DATABASE={_require_env('SIETEL_SQLSERVER_DATABASE')};"
        f"UID={_require_env('SIETEL_SQLSERVER_USER')};"
        f"PWD={_require_env('SIETEL_SQLSERVER_PASSWORD')};"
        f"TrustServerCertificate=yes;"
        f"Encrypt=yes;"
    )
    return pyodbc.connect(conn_str, timeout=30)


class _DictCursorWrapper:
    """
    Envuelve un cursor de pyodbc para que fetchall()/fetchone() devuelvan
    dicts en vez de pyodbc.Row, manteniendo compatible el resto del código
    que accede a las filas como fila["nombre_columna"].
    """

    def __init__(self, cursor):
        self._cursor = cursor

    def _row_to_dict(self, row):
        if row is None:
            return None
        columns = [col[0] for col in self._cursor.description]
        return dict(zip(columns, row))

    def execute(self, *args, **kwargs):
        return self._cursor.execute(*args, **kwargs)

    def fetchall(self):
        return [self._row_to_dict(r) for r in self._cursor.fetchall()]

    def fetchone(self):
        return self._row_to_dict(self._cursor.fetchone())

    def __getattr__(self, name):
        return getattr(self._cursor, name)


def get_postgres_connection():
    """Abre una conexión a PostgreSQL (servidor analítico destino)."""
    return psycopg2.connect(
        host=_require_env("ANALITICO_PG_HOST"),
        port=os.environ.get("ANALITICO_PG_PORT", "5432"),
        user=_require_env("ANALITICO_PG_USER"),
        password=_require_env("ANALITICO_PG_PASSWORD"),
        dbname=_require_env("ANALITICO_PG_DATABASE"),
    )


@contextmanager
def postgres_cursor(commit: bool = True):
    conn = get_postgres_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def sqlserver_cursor():
    """Context manager que entrega un cursor de SQL Server (filas como dict) y cierra la conexión."""
    conn = get_sqlserver_connection()
    try:
        cur = _DictCursorWrapper(conn.cursor())
        yield cur
    finally:
        conn.close()


ANIO_INICIO_HISTORICO = 2011
ANIO_FIN_HISTORICO = 2026
