"""
Detección de cambios en SIGER_V3 (08-oct-2026): evita recargar una tabla
cuyo contenido no cambió desde el último snapshot certificado.

Mismo criterio que scripts/detectar_cambios.py para SIETEL: una "huella"
barata calculada en SQL Server -- COUNT_BIG(*) y CHECKSUM_AGG(BINARY_CHECKSUM)
de las columnas que se replican -- comparada contra siger.huella_fuente, que
guarda la huella tomada ANTES de extraer el último snapshot confirmado. Se
escribe en la MISMA transacción que el snapshot (ver cargar_siger.py): si la
carga se revierte, la huella vieja queda y el siguiente chequeo vuelve a ver
la diferencia. Si SIGER cambia durante la extracción, la huella guardada
queda vieja y la próxima corrida recarga (a lo sumo una recarga de más).

La huella NO certifica contenido (eso lo hacen la certificación previa al
COMMIT y validar_siger.py); solo responde "¿cambió algo?". Limitaciones,
cubiertas por la recarga completa semanal (DIA_RECARGA_COMPLETA) y por
forzar_recarga en dag_run.conf:
  - CHECKSUM_AGG puede no ver dos cambios que se compensan exactamente;
  - BINARY_CHECKSUM ignora columnas text/ntext/image/xml;
  - un cambio en siger/reglas.py no cambia la huella, pero sí las columnas
    derivadas: tras desplegarlo, forzar la recarga.

Cuándo se recarga una tabla (decidir_recarga, función pura -- ver
tests/test_siger_reglas.py):
  - forzar (día de recarga completa o forzar_recarga en conf);
  - no hay huella guardada (primera corrida, o validar_siger la invalidó);
  - cambió la lista de columnas replicadas;
  - cambió el conteo o el checksum en SIGER;
  - el destino no tiene las filas que dice la huella (alterado por fuera);
  - una tabla de la que depende se recargó (facturación calcula tipo_enlace
    contra los contrato_key de los títulos).
"""
import hashlib
import logging

from config_siger import COLUMNAS_PERMITIDAS, sqlserver_cursor

logger = logging.getLogger(__name__)


def firma_columnas(objeto: str) -> str:
    """MD5 de la lista de columnas replicadas: si cambia, la huella vieja no aplica."""
    return hashlib.md5(",".join(COLUMNAS_PERMITIDAS[objeto]).encode("utf-8")).hexdigest()


def sql_huella(objeto: str) -> str:
    """Conteo + checksum referenciando SOLO columnas permitidas (permisos por
    columna: un COUNT(*) directo o una columna denegada harían fallar todo)."""
    cols = ", ".join(f"[{c}]" for c in COLUMNAS_PERMITIDAS[objeto])
    return (f"SELECT COUNT_BIG(*) AS filas, CHECKSUM_AGG(BINARY_CHECKSUM({cols})) AS checksum "
            f"FROM (SELECT {cols} FROM {objeto}) t")


def tomar_huella(objeto: str) -> dict:
    with sqlserver_cursor() as cur:
        cur.execute(sql_huella(objeto))
        r = cur.fetchone()
    return {
        "filas": int(r["filas"]),
        "checksum": None if r["checksum"] is None else int(r["checksum"]),
        "columnas": firma_columnas(objeto),
    }


def leer_huella(pg_cur, tipo_carga: str) -> dict | None:
    pg_cur.execute(
        "SELECT filas, checksum, columnas FROM siger.huella_fuente WHERE tabla = %s", (tipo_carga,)
    )
    r = pg_cur.fetchone()
    return None if r is None else {"filas": int(r[0]), "checksum": r[1], "columnas": r[2]}


def guardar_huella(pg_cur, tipo_carga: str, huella: dict) -> None:
    """Upsert dentro de la transacción del snapshot (no hace COMMIT)."""
    pg_cur.execute(
        """
        INSERT INTO siger.huella_fuente (tabla, filas, checksum, columnas, fecha_registro)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT (tabla) DO UPDATE
            SET filas = EXCLUDED.filas, checksum = EXCLUDED.checksum,
                columnas = EXCLUDED.columnas, fecha_registro = EXCLUDED.fecha_registro
        """,
        (tipo_carga, huella["filas"], huella["checksum"], huella["columnas"]),
    )


def invalidar_huellas(pg_cur, tipos_carga: list[str]) -> None:
    """Borra huellas para que la próxima corrida recargue esas tablas."""
    pg_cur.execute("DELETE FROM siger.huella_fuente WHERE tabla = ANY(%s)", (list(tipos_carga),))


def decidir_recarga(actual: dict, guardada: dict | None, n_destino: int,
                    forzar: bool = False, dependencia_recargada: bool = False) -> str | None:
    """Motivo para recargar la tabla, o None si no cambió nada."""
    if forzar:
        return "recarga completa forzada"
    if guardada is None:
        return "sin huella guardada"
    if actual["columnas"] != guardada["columnas"]:
        return "cambió la lista de columnas replicadas"
    if actual["filas"] != guardada["filas"]:
        return f"conteo en SIGER {guardada['filas']:,} -> {actual['filas']:,}"
    if actual["checksum"] != guardada["checksum"]:
        return "contenido modificado en SIGER (checksum distinto)"
    if n_destino != guardada["filas"]:
        return f"el destino tiene {n_destino:,} filas y la huella {guardada['filas']:,}"
    if dependencia_recargada:
        return "se recargó una tabla de la que depende"
    return None
