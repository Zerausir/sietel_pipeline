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


def get_sqlserver_connection(prefijo: str = "SIETEL", timeout_consulta: int | None = None):
    """
    Abre una conexión a SQL Server (SIETEL) usando pyodbc + el driver ODBC 18
    de Microsoft.

    CAMBIO (05-oct-2026): parametrizada para reutilizarla con SIGER_V3 (otro
    servidor, otras credenciales -- ver siger/config_siger.py). `prefijo`
    elige el juego de variables {prefijo}_SQLSERVER_HOST/PORT/DATABASE/USER/
    PASSWORD; el driver y las opciones TLS son los mismos para ambos. Con los
    valores por defecto el comportamiento para SIETEL no cambia.
    `timeout_consulta` (segundos) fija conn.timeout: tiempo límite de CADA
    consulta en pyodbc, distinto del timeout=30 de login de abajo. None =
    sin límite (comportamiento anterior).

    Se eligió pyodbc sobre pymssql porque el servidor SIETEL exige una
    negociación TLS que FreeTDS (usado internamente por pymssql) rechaza
    durante el handshake, incluso con conectividad de red y credenciales
    correctas confirmadas. SSMS sí conecta porque usa el mismo stack TLS
    que el driver ODBC oficial de Microsoft.

    RIESGO ACEPTADO (documentado 28-sep-2026): TrustServerCertificate=yes
    cifra el canal pero NO valida el certificado del servidor, así que no
    protege contra un intermediario (MITM) en la red entre Airflow y
    SIETEL. Se suma a UnsafeLegacyRenegotiation en docker/Dockerfile.
    Ambos son exigencias del servidor SIETEL actual (certificado no
    verificable por el contenedor, sin renegociación segura RFC 5746), no
    elecciones de este pipeline. La mitigación real es del lado de SIETEL:
    un certificado emitido por una CA de confianza (y entonces cambiar a
    TrustServerCertificate=no) y soporte de renegociación segura. Las
    credenciales viajan cifradas igual; el riesgo es de suplantación del
    servidor dentro de la red interna.
    """
    driver = os.environ.get("SIETEL_SQLSERVER_ODBC_DRIVER", "ODBC Driver 18 for SQL Server")
    host = _require_env(f"{prefijo}_SQLSERVER_HOST")
    port = os.environ.get(f"{prefijo}_SQLSERVER_PORT", "1433")
    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={host},{port};"
        f"DATABASE={_require_env(f'{prefijo}_SQLSERVER_DATABASE')};"
        f"UID={_require_env(f'{prefijo}_SQLSERVER_USER')};"
        f"PWD={_require_env(f'{prefijo}_SQLSERVER_PASSWORD')};"
        f"TrustServerCertificate=yes;"
        f"Encrypt=yes;"
    )
    conn = pyodbc.connect(conn_str, timeout=30)
    if timeout_consulta is not None:
        conn.timeout = timeout_consulta
    return conn


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

    def fetchmany(self, size: int):
        """Lote de filas como dicts -- para extracciones grandes sin fetchall() (SIGER)."""
        return [self._row_to_dict(r) for r in self._cursor.fetchmany(size)]

    def __getattr__(self, name):
        return getattr(self._cursor, name)


def get_postgres_connection(env_usuario: str = "ANALITICO_PG_USER",
                            env_password: str = "ANALITICO_PG_PASSWORD"):
    """
    Abre una conexión a PostgreSQL (servidor analítico destino).

    CAMBIO (05-oct-2026): env_usuario/env_password eligen qué variables de
    entorno aportan las credenciales (SIGER usa SIGER_PG_USER/PASSWORD, rol
    siger_user); host/puerto/base siempre son ANALITICO_PG_*. Por defecto,
    sietel_user como antes.
    """
    return psycopg2.connect(
        host=_require_env("ANALITICO_PG_HOST"),
        port=os.environ.get("ANALITICO_PG_PORT", "5432"),
        user=_require_env(env_usuario),
        password=_require_env(env_password),
        dbname=_require_env("ANALITICO_PG_DATABASE"),
    )


@contextmanager
def postgres_cursor(commit: bool = True, env_usuario: str = "ANALITICO_PG_USER",
                    env_password: str = "ANALITICO_PG_PASSWORD"):
    conn = get_postgres_connection(env_usuario, env_password)
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
def sqlserver_cursor(prefijo: str = "SIETEL", timeout_consulta: int | None = None):
    """Context manager que entrega un cursor de SQL Server (filas como dict) y cierra la conexión."""
    conn = get_sqlserver_connection(prefijo, timeout_consulta)
    try:
        cur = _DictCursorWrapper(conn.cursor())
        yield cur
    finally:
        conn.close()


ANIO_INICIO_HISTORICO = 2011
ANIO_FIN_HISTORICO = 2025
