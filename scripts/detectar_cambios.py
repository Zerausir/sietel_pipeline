"""
Detección de información nueva o corregida en SIETEL (30-sep-2026).

Calcula en SQL Server una "huella" barata por (anio, periodoNumero) de las
dos tablas que alimentan los hechos -- dbo.VALineasDedicadas y
dbo.VAFormularioLineasDedicadas -- y la compara contra
staging.huella_fuente, que guarda la huella de lo último cargado y
certificado.

Qué se recarga según lo que cambió:
  - lineas:      solo los meses (anio, periodoNumero) nuevos, distintos o
                 que desaparecieron del origen. _cargar_mes reemplaza un mes
                 de forma exacta e idempotente (upsert + borrado de
                 obsoletos, auditado en staging.historial_correcciones), y
                 validar_carga certifica solo esos meses.
  - formularios: ningún mes de hechos -- el pipeline ya recarga el snapshot
                 completo de formularios en cada corrida; basta con correrlo.
En ambos casos capa2 y mart se reconstruyen completos: dependen de toda la
historia (primer/último período de cada prestador, "reporte detenido",
LAG() del dashboard...).

La huella NO certifica contenido (eso lo hace validar_carga.py); solo
responde "¿cambió algo desde la última carga?":
  - lineas:      COUNT_BIG(*), SUM(numeroUsuarios) y CHECKSUM_AGG de las
                 columnas que entran al agregado.
  - formularios: COUNT_BIG(*), SUM(numeroRegistros), CHECKSUM_AGG y la
                 fecha de carga/modificación más reciente.
CHECKSUM_AGG puede no ver dos cambios que se compensan exactamente; por
eso va junto al conteo y la suma, y la validación cruzada de cada carga
sigue siendo la certificación real.

Uso:
    python detectar_cambios.py              # solo informa qué cambió
    python detectar_cambios.py --sembrar    # guarda la huella actual completa
                                            # (primera vez, cuando PostgreSQL
                                            # ya está al día)
"""
import argparse
import logging
from datetime import datetime

from config import postgres_cursor, sqlserver_cursor

logger = logging.getLogger(__name__)

# periodoNumero 1..12: los mismos meses que puede cargar cargar_hechos_anio
# (MESES_DEL_ANIO). Un período fuera de ese rango nunca se carga, así que
# incluirlo lo marcaría como "cambiado" en cada corrida.
SQL_HUELLA_LINEAS = """
    SELECT
        'lineas'                                   AS fuente,
        anio,
        periodoNumero                              AS periodo_numero,
        COUNT_BIG(*)                               AS filas,
        SUM(CAST(numeroUsuarios AS BIGINT))        AS suma,
        CHECKSUM_AGG(BINARY_CHECKSUM(
            peva_codigo, par_codigo, periodoNombre, tipoEnlace, tipoCliente,
            nivelComparticion, portador, regional, numeroUsuarios,
            downLink, upLink))                     AS checksum,
        CAST(NULL AS DATETIME)                     AS max_fecha
    FROM dbo.VALineasDedicadas
    WHERE periodoNumero BETWEEN 1 AND 12
    GROUP BY anio, periodoNumero
"""

SQL_HUELLA_FORMULARIOS = """
    SELECT
        'formularios'                                  AS fuente,
        anio,
        periodoNumero                                  AS periodo_numero,
        COUNT_BIG(*)                                   AS filas,
        SUM(CAST(numeroRegistros AS BIGINT))           AS suma,
        CHECKSUM_AGG(BINARY_CHECKSUM(
            fld_codigo, peva_codigo, periodoNombre, tieneServicio,
            numeroRegistros, regional))                AS checksum,
        MAX(COALESCE(fechaModificacion, fechaCarga))   AS max_fecha
    FROM dbo.VAFormularioLineasDedicadas
    GROUP BY anio, periodoNumero
"""

CAMPOS_COMPARADOS = ("filas", "suma", "checksum", "max_fecha")


def _normalizar(fila: dict) -> dict:
    """Fila de huella serializable (XCom de Airflow) y comparable entre
    SQL Server y PostgreSQL: enteros como int y fechas como texto ISO."""
    max_fecha = fila["max_fecha"]
    if isinstance(max_fecha, datetime):
        max_fecha = max_fecha.isoformat()
    return {
        "fuente": fila["fuente"],
        "anio": int(fila["anio"]),
        "periodo_numero": int(fila["periodo_numero"]),
        "filas": int(fila["filas"]),
        "suma": None if fila["suma"] is None else int(fila["suma"]),
        "checksum": None if fila["checksum"] is None else int(fila["checksum"]),
        "max_fecha": max_fecha,
    }


def tomar_huella() -> list[dict]:
    """Huella actual de SIETEL, una fila por fuente y (anio, periodoNumero)."""
    with sqlserver_cursor() as cur:
        filas = []
        for sql in (SQL_HUELLA_LINEAS, SQL_HUELLA_FORMULARIOS):
            cur.execute(sql)
            filas.extend(cur.fetchall())
    # Filas con anio o período NULL en origen no son cargables -- se ignoran.
    return [_normalizar(f) for f in filas if f["anio"] is not None and f["periodo_numero"] is not None]


def leer_huella_guardada() -> list[dict]:
    with postgres_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT fuente, anio, periodo_numero, filas, suma, checksum, max_fecha
            FROM staging.huella_fuente
            """
        )
        return [_normalizar(f) for f in cur.fetchall()]


def comparar_huellas(actual: list[dict], guardada: list[dict]) -> dict:
    """
    Qué cambió entre la huella guardada y la actual. Función pura -- ver
    tests/test_detectar_cambios.py. Devuelve:
      periodos:    [[anio, mes], ...] de lineas nuevos, distintos o que
                   desaparecieron del origen, ordenados.
      formularios: True si cambió cualquier período de formularios.
    """
    def indexar(huella):
        return {
            (f["fuente"], f["anio"], f["periodo_numero"]): tuple(f[c] for c in CAMPOS_COMPARADOS)
            for f in huella
        }

    idx_actual = indexar(actual)
    idx_guardada = indexar(guardada)
    distintas = {
        clave for clave in idx_actual.keys() | idx_guardada.keys()
        if idx_actual.get(clave) != idx_guardada.get(clave)
    }
    return {
        "periodos": [[anio, mes] for anio, mes in sorted({(a, m) for f, a, m in distintas if f == "lineas"})],
        "formularios": any(f == "formularios" for f, _, _ in distintas),
    }


def agrupar_por_anio(periodos: list[list[int]]) -> list[dict]:
    """[[2025, 12], [2026, 1], [2026, 2]] -> [{"anio": 2025, "meses": [12]},
    {"anio": 2026, "meses": [1, 2]}]: una carga (tarea mapeada) por año."""
    meses_por_anio: dict[int, set[int]] = {}
    for anio, mes in periodos:
        meses_por_anio.setdefault(int(anio), set()).add(int(mes))
    return [{"anio": anio, "meses": sorted(meses)} for anio, meses in sorted(meses_por_anio.items())]


def guardar_huella(huella: list[dict], lotes: list[dict] | None = None):
    """
    Guarda en staging.huella_fuente lo que quedó cargado y certificado:
      - lineas: solo los meses de los lotes cargados. Los demás conservan su
        huella vieja, así una diferencia pendiente se sigue detectando.
      - formularios: todos, porque el pipeline recarga el snapshot completo
        de formularios en cada corrida.
    lotes=None (--sembrar) reemplaza la huella completa.
    """
    if lotes is None:
        periodos = {(f["anio"], f["periodo_numero"]) for f in huella if f["fuente"] == "lineas"}
    else:
        periodos = {(lote["anio"], mes) for lote in lotes for mes in lote["meses"]}

    filas = [
        f for f in huella
        if f["fuente"] == "formularios" or (f["anio"], f["periodo_numero"]) in periodos
    ]
    with postgres_cursor() as cur:
        if lotes is None:
            cur.execute("DELETE FROM staging.huella_fuente")
        else:
            cur.execute("DELETE FROM staging.huella_fuente WHERE fuente = 'formularios'")
            anios, meses = zip(*periodos) if periodos else ((), ())
            cur.execute(
                """
                DELETE FROM staging.huella_fuente
                WHERE fuente = 'lineas'
                  AND (anio, periodo_numero) IN (SELECT * FROM unnest(%s::int[], %s::int[]))
                """,
                (list(anios), list(meses)),
            )
        for f in filas:
            cur.execute(
                """
                INSERT INTO staging.huella_fuente
                    (fuente, anio, periodo_numero, filas, suma, checksum, max_fecha)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (f["fuente"], f["anio"], f["periodo_numero"], f["filas"],
                 f["suma"], f["checksum"], f["max_fecha"]),
            )
    logger.info("Huella guardada: %d meses de líneas + formularios (%d filas).", len(periodos), len(filas))


def detectar_cambios() -> dict:
    """
    Compara la huella actual de SIETEL contra la última cargada (ver
    comparar_huellas). Si staging.huella_fuente está vacía, falla en vez de
    disparar una recarga histórica completa: hay que sembrarla primero.
    """
    inicio = datetime.now()
    guardada = leer_huella_guardada()
    if not guardada:
        raise RuntimeError(
            "staging.huella_fuente está vacía -- siémbrala con "
            "'python scripts/detectar_cambios.py --sembrar' antes de activar la detección."
        )
    cambios = comparar_huellas(tomar_huella(), guardada)
    logger.info("Cambios en SIETEL: meses de líneas %s, formularios %s",
                cambios["periodos"] or "ninguno", "sí" if cambios["formularios"] else "no")
    _registrar_deteccion(cambios, inicio)
    return cambios


def _describir(cambios: dict) -> str | None:
    partes = []
    if cambios["periodos"]:
        partes.append("Meses: " + ", ".join(f"{a}-{m:02d}" for a, m in cambios["periodos"]))
    if cambios["formularios"]:
        partes.append("Formularios modificados")
    return "; ".join(partes) or None


def _registrar_deteccion(cambios, fecha_inicio):
    descripcion = _describir(cambios)
    with postgres_cursor() as cur:
        cur.execute(
            """
            INSERT INTO staging.control_cargas
                (tipo_carga, anio, filas_insertadas, filas_actualizadas,
                 estado, mensaje_error, fecha_inicio)
            VALUES ('deteccion_cambios', NULL, NULL, NULL, %s, %s, %s)
            """,
            ("CAMBIOS" if descripcion else "SIN_CAMBIOS", descripcion, fecha_inicio),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Detecta información nueva o corregida en SIETEL")
    parser.add_argument("--sembrar", action="store_true",
                        help="Guarda la huella actual completa sin cargar nada")
    args = parser.parse_args()

    if args.sembrar:
        guardar_huella(tomar_huella())
    else:
        guardada = leer_huella_guardada()
        if not guardada:
            print("staging.huella_fuente está vacía -- ejecuta con --sembrar.")
        else:
            print(_describir(comparar_huellas(tomar_huella(), guardada)) or "Sin cambios.")
