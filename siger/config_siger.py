"""
Configuración y conexiones del pipeline SIGER_V3 -> PostgreSQL (esquema siger).

Reutiliza scripts/config.py (mismo driver ODBC 18, mismas opciones TLS ya
probadas con SIETEL, misma carga de .env) en vez de duplicar la lógica de
conexión: solo cambia el juego de variables de entorno.
  - SQL Server SIGER: SIGER_SQLSERVER_HOST/PORT/DATABASE/USER/PASSWORD.
  - PostgreSQL: host/puerto/base de ANALITICO_PG_*, credenciales de
    SIGER_PG_USER/SIGER_PG_PASSWORD (rol siger_user, dueño del esquema siger).

PERMISOS POR COLUMNA (verificados 05-oct-2026): en SIGER_V3 el usuario de
lectura tiene permisos a nivel de COLUMNA. Cualquier columna denegada en un
SELECT hace fallar toda la consulta (error 230), por eso NUNCA se usa
SELECT * y cada objeto lleva su lista explícita de columnas permitidas.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from config import postgres_cursor as _postgres_cursor  # noqa: E402
from config import sqlserver_cursor as _sqlserver_cursor  # noqa: E402

# Tiempo límite de CADA consulta a SQL Server (pyodbc conn.timeout), aparte
# del timeout de login. Holgado para la extracción completa de
# NR_PARAMETROS_FACTURACION (~2,48 M filas); ajustar con lo medido.
TIMEOUT_CONSULTA_S = 3600

# Columnas permitidas por objeto (§2 de la instrucción, verificadas
# 05-oct-2026 con el usuario de lectura). Denegadas -- NO agregar aquí:
#   TITULO_HABILITANTE: THUSUARIO, TTHSECUENCIAL, STHSECUENCIAL, THFECHASUS,
#     THRESOLUCION, THFECHARES, THTITULO, THCUERPO, THCOBERTURA,
#     THUSUARIOREG, THFECHAREG, THNUMERO_TRAMITE, THCONTRATO_RENOVADO
#   SERVICIO_TH: IDTSV, ELIMINACION
COLUMNAS_PERMITIDAS = {
    "dbo.TITULO_HABILITANTE": [
        "THSECUENCIAL", "IDSTH", "THTOMO", "THFOJA", "THPAGINA", "THACTA",
        "UCP_CONCNUM", "THESTADO", "THFECHAVIG",
    ],
    "dbo.SERVICIO_TH": ["IDSTH", "ABREVIATURA", "DESCRIPCION"],
    "dbo.VISTA_CONCESIONARIOS": [
        "ucp_concnum", "nombres", "ci_ruc", "ruc", "prvnnombre", "cantnombre",
        "parrnombre", "ucci_ciudad", "direccion", "telefono1", "telefono2",
        "ucpn_telefocasa", "telefono3", "ucp_fax", "ucp_email", "ucp_direccorre",
        "ucpn_certivota", "parrcodi", "ucp_usafrec", "ucp_tipoconc", "ucpj_tipo",
        "prvnregional",
    ],
    # Todas las columnas están permitidas (~100). La lista fija se cierra en
    # la fase 2 con el volcado de INFORMATION_SCHEMA de probar_conexion.py;
    # hasta entonces None = "tomar la lista de INFORMATION_SCHEMA.COLUMNS".
    "dbo.NR_PARAMETROS_FACTURACION": None,
}

# Columna NOT NULL de cada objeto usada para contar sin referenciar columnas
# denegadas (COUNT_BIG sobre una subconsulta de una columna permitida).
COLUMNA_CONTEO = {
    "dbo.TITULO_HABILITANTE": "THSECUENCIAL",
    "dbo.SERVICIO_TH": "IDSTH",
    "dbo.VISTA_CONCESIONARIOS": "ucp_concnum",
    "dbo.NR_PARAMETROS_FACTURACION": None,  # cualquiera: todas permitidas
}

# Universo SAI -- SOLO para las vistas derivadas (siger.v_titulo_sai,
# siger.v_prestador_sai), NUNCA para la extracción ni para las tablas
# crudas, que replican todos los servicios. Fuente única: la fase 2
# sincroniza esta constante en la tabla siger.parametro_universo_sai.
# Se EXCLUYE IDSTH 8 (VALOR AGREGADO): sus titulares son agregadores de SMS,
# contenido móvil y rastreo vehicular, no acceso a internet.
IDSTH_UNIVERSO_SAI = {
    9: "SERVICIO DE ACCESO A INTERNET",
    33: "VALOR AGREGADO DE INTERNET",
    31: "VALOR AGREGADO DE INTERNET ACTUALMENTE SAI",
}

# Protección del snapshot por reemplazo: si el conteo nuevo cae más de esta
# fracción respecto al snapshot anterior, se aborta sin tocar el destino.
UMBRAL_CAIDA_MAXIMA = 0.20

# Filas por lote en fetchmany / inserción.
TAMANO_LOTE = 10_000


class PermisoDenegado(RuntimeError):
    pass


def sqlserver_cursor(timeout_consulta: int | None = TIMEOUT_CONSULTA_S):
    """Cursor de SQL Server SIGER_V3 (filas como dict), con tiempo límite de consulta."""
    return _sqlserver_cursor(prefijo="SIGER", timeout_consulta=timeout_consulta)


def postgres_cursor(commit: bool = True):
    """Cursor de PostgreSQL analítico conectado como siger_user."""
    return _postgres_cursor(commit=commit, env_usuario="SIGER_PG_USER", env_password="SIGER_PG_PASSWORD")


def columnas_de_origen(cur, objeto: str) -> list[dict]:
    """
    Metadatos de columnas del objeto según INFORMATION_SCHEMA.COLUMNS (solo
    lista las columnas sobre las que el usuario tiene algún permiso).
    """
    esquema, nombre = objeto.split(".")
    cur.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
               NUMERIC_PRECISION, NUMERIC_SCALE, DATETIME_PRECISION,
               IS_NULLABLE, ORDINAL_POSITION
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
        """,
        (esquema, nombre),
    )
    return cur.fetchall()


def columnas_con_select_segun_catalogo(cur, objeto: str) -> set[str]:
    """
    Columnas (en minúscula) con SELECT según fn_my_permissions. SOLO
    DIAGNÓSTICO: la primera corrida de probar_conexion.py (05-oct-2026)
    mostró que en SIGER_V3 puede no coincidir con lo que SQL Server
    realmente permite consultar -- la prueba que manda es el SELECT real de
    verificar_permisos().
    """
    cur.execute(
        "SELECT subentity_name FROM fn_my_permissions(?, 'OBJECT') "
        "WHERE permission_name = 'SELECT' AND subentity_name <> ''",
        (objeto,),
    )
    return {r["subentity_name"].lower() for r in cur.fetchall()}


def columnas_denegadas(cur, objeto: str, columnas: list[str]) -> list[str]:
    """
    Prueba EMPÍRICA columna por columna: SELECT TOP 0 [col] FROM objeto. SQL
    Server verifica permisos al compilar la consulta aunque no devuelva
    filas, así que una columna denegada falla aquí con el mismo error 230 que
    haría fallar la extracción. Devuelve las columnas que fallan.
    """
    denegadas = []
    for c in columnas:
        try:
            cur.execute(f"SELECT TOP 0 [{c}] FROM {objeto}")
            cur.fetchall()
        except Exception:
            denegadas.append(c)
    return denegadas


def verificar_permisos(cur, objeto: str, columnas: list[str]) -> None:
    """
    Verifica que se pueda consultar CADA columna de la lista (prueba
    empírica, ver columnas_denegadas) y luego todas juntas con un SELECT
    TOP 0 de las columnas exactas. Falla con PermisoDenegado indicando qué
    columna(s) están denegadas -- en vez del error 230 genérico de SQL
    Server a mitad de una extracción.
    """
    denegadas = columnas_denegadas(cur, objeto, columnas)
    if denegadas:
        raise PermisoDenegado(
            f"{objeto}: SQL Server deniega SELECT sobre la(s) columna(s) {', '.join(denegadas)} "
            f"(SELECT TOP 0 falla). Revisar los permisos por columna en SIGER_V3 con Informática "
            f"antes de cargar."
        )
    lista = ", ".join(f"[{c}]" for c in columnas)
    try:
        cur.execute(f"SELECT TOP 0 {lista} FROM {objeto}")
        cur.fetchall()
    except Exception as exc:
        raise PermisoDenegado(
            f"{objeto}: cada columna se puede consultar por separado, pero el SELECT TOP 0 "
            f"conjunto falló: {exc}"
        ) from exc
