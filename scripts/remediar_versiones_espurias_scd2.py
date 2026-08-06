"""
scripts/remediar_versiones_espurias_scd2.py

Remediación puntual del bug de _cambio_relevante() corregido el 07-ago-2026
(ver commit correspondiente en cargar_nodo_isp.py / cargar_dimensiones.py):
la comparación de claves con case distinto entre SQL Server y Postgres hacía
que CUALQUIER fila se detectara como "cambio relevante", siempre -- sin
importar si de verdad cambió algo.

Este script NO corrige la causa (ya corregida en el código de carga) --
colapsa las versiones espurias que ya quedaron escritas en staging antes del
fix. Fusiona SOLO versiones CONSECUTIVAS cuyo contenido es idéntico en las
columnas versionables reales -- si dos versiones consecutivas sí difieren en
una columna versionable (ej. opera realmente cambió), NO se tocan: eso es
historia real, no ruido del bug.

Alcance confirmado en producción (07-ago-2026):
  - staging.dim_nodo_isp: 8606 nodos, cada uno con exactamente 2 versiones
    (la original + 1 espuria de la única corrida repetida hasta ahora).
  - staging.dim_permiso_va_agregado: 1665 PEVA, cada uno con exactamente 7
    versiones (11655 = 1665 x 7 -- ninguna variación, el bug disparó en las
    7 corridas de Capa 1 que ha tenido este pipeline, sin excepción).

Uso:
    python remediar_versiones_espurias_scd2.py --dry-run   # reporte, no escribe nada
    python remediar_versiones_espurias_scd2.py --confirmar  # aplica de verdad

Sin --dry-run NI --confirmar, el script se niega a correr -- no hay default
implícito hacia "sí escribir".
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from datetime import datetime

from config import postgres_cursor

logger = logging.getLogger(__name__)
logging.basicConfig(level="INFO", format="%(asctime)s [%(levelname)s] %(message)s")

# (tabla, columna_sk, columna_llave_natural, columnas_versionables_reales)
OBJETIVOS = [
    (
        "dim_nodo_isp", "noisp_sk", "noisp_codigo",
        ["par_codigo", "estado", "tipoNodo", "latitud", "longitud", "verificado"],
    ),
    (
        "dim_permiso_va_agregado", "peva_sk", "peva_codigo",
        ["nombreComercial", "opera", "Resolucion"],
    ),
]


def _diagnosticar(pg_cur, tabla: str, llave_natural: str) -> None:
    pg_cur.execute(
        f"""
        SELECT COUNT(*) AS total_versiones, COUNT(DISTINCT {llave_natural}) AS total_llaves
        FROM staging.{tabla}
        """
    )
    fila = pg_cur.fetchone()
    promedio = fila["total_versiones"] / fila["total_llaves"] if fila["total_llaves"] else 0
    logger.info(
        "staging.%s: %s versiones totales, %s llaves distintas, promedio %.2f versiones/llave",
        tabla, fila["total_versiones"], fila["total_llaves"], promedio,
    )


def _colapsar_versiones_espurias(
        pg_cur, tabla: str, sk_col: str, llave_natural: str,
        columnas_comparar: list[str], dry_run: bool,
) -> tuple[int, int]:
    """
    Fusiona versiones CONSECUTIVAS (ordenadas por fecha_inicio_vigencia)
    cuyo contenido es idéntico en columnas_comparar. La versión más antigua
    del par absorbe el rango de vigencia de la más nueva (fecha_fin_vigencia,
    es_vigente); la más nueva se elimina. Se repite hasta que no queden
    pares consecutivos idénticos dentro de cada llave natural -- así una
    racha de 7 versiones idénticas se colapsa en 1, no solo de a pares.

    Comparación de columnas insensible a mayúsculas/minúsculas en las
    CLAVES del dict (mismo motivo que el fix de _cambio_relevante(): los
    nombres de columna en columnas_comparar vienen con el case de SQL
    Server, pero al leer de vuelta desde Postgres las claves del dict ya
    están todas en minúscula).
    """
    pg_cur.execute(f"SELECT * FROM staging.{tabla} ORDER BY {llave_natural}, fecha_inicio_vigencia")
    filas = pg_cur.fetchall()

    grupos: dict[str, list[dict]] = defaultdict(list)
    for fila in filas:
        grupos[fila[llave_natural]].append(dict(fila))

    total_colapsadas = 0
    llaves_afectadas = 0

    for llave, versiones in grupos.items():
        colapso_en_esta_llave = False
        i = 0
        while i < len(versiones) - 1:
            actual = versiones[i]
            siguiente = versiones[i + 1]
            identicas = all(
                actual.get(c.lower()) == siguiente.get(c.lower())
                for c in columnas_comparar
            )
            if not identicas:
                i += 1
                continue

            if not dry_run:
                pg_cur.execute(
                    f"""
                    UPDATE staging.{tabla}
                    SET fecha_fin_vigencia = %s, es_vigente = %s
                    WHERE {sk_col} = %s
                    """,
                    (siguiente["fecha_fin_vigencia"], siguiente["es_vigente"], actual[sk_col]),
                )
                pg_cur.execute(
                    f"DELETE FROM staging.{tabla} WHERE {sk_col} = %s",
                    (siguiente[sk_col],),
                )
            # Fusiona en memoria: 'actual' absorbe el rango de 'siguiente' y
            # se vuelve a comparar contra lo que antes era versiones[i+2] --
            # por eso NO se incrementa i aquí.
            actual["fecha_fin_vigencia"] = siguiente["fecha_fin_vigencia"]
            actual["es_vigente"] = siguiente["es_vigente"]
            versiones.pop(i + 1)
            total_colapsadas += 1
            colapso_en_esta_llave = True

        if colapso_en_esta_llave:
            llaves_afectadas += 1

    return total_colapsadas, llaves_afectadas


def remediar(dry_run: bool) -> None:
    with postgres_cursor(commit=not dry_run) as pg_cur:
        logger.info("=== Diagnóstico ANTES de remediar ===")
        for tabla, _, llave_natural, _ in OBJETIVOS:
            _diagnosticar(pg_cur, tabla, llave_natural)

        logger.info("=== %s ===", "Simulación (--dry-run, nada se escribe)" if dry_run else "Aplicando remediación")
        for tabla, sk_col, llave_natural, columnas in OBJETIVOS:
            colapsadas, llaves_afectadas = _colapsar_versiones_espurias(
                pg_cur, tabla, sk_col, llave_natural, columnas, dry_run
            )
            logger.info(
                "staging.%s: %s versiones espurias %s, %s llaves (%s) afectadas",
                tabla, colapsadas,
                "que se colapsarían" if dry_run else "colapsadas",
                llaves_afectadas, llave_natural,
            )

        if not dry_run:
            logger.info("=== Diagnóstico DESPUÉS de remediar ===")
            for tabla, _, llave_natural, _ in OBJETIVOS:
                _diagnosticar(pg_cur, tabla, llave_natural)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--dry-run", action="store_true", help="Solo reporta qué se colapsaría, no escribe nada")
    grupo.add_argument("--confirmar", action="store_true", help="Aplica la remediación de verdad")
    args = parser.parse_args(argv)

    remediar(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
