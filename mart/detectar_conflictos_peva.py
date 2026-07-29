"""
mart/detectar_conflictos_peva.py

Detecta prestadores (RUC) con múltiples PEVA, los clasifica, y resuelve
automáticamente el Grupo A (duplicado por migración de codificación de
"opera") -- confirmado confiable el 28-jul-2026 tras revisión manual de 6
casos reales. Los Grupos B y C se registran para revisión humana, nunca se
resuelven solos.

SOSTENIBILIDAD: este script es idempotente y preserva el workflow humano.
Cada corrida hace UPSERT sobre calidad.conflictos_ruc_peva:
  - Columnas derivadas de los datos de origen (categoria, nombres, fechas,
    coexistencia) SIEMPRE se actualizan -- reflejan el estado actual de
    SIETEL.
  - Columnas de workflow (estado_revision, revisado_por, notas_revision,
    fecha_revision) SOLO se fijan la primera vez que aparece un par. Una
    vez que una persona confirma o descarta un caso, correr este script de
    nuevo NUNCA revierte esa decisión.

Se ejecuta como parte de mart/aplicar_capa3.py, ANTES de construir
capa2.lineas_dedicadas_consolidado, para que los PEVA del Grupo A ya
confirmados se excluyan antes de llegar a la agregación (ver
calidad.vw_pevas_excluidos).

Uso:
    python detectar_conflictos_peva.py            # detecta y resuelve
    python detectar_conflictos_peva.py --dry-run  # solo reporta, no escribe
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

load_dotenv()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Códigos de "opera" heredados de la migración -- ver hallazgo ya
# documentado en sietel_pipeline (9/1665 registros con esta codificación
# vieja mezclada con las categorías descriptivas actuales).
CODIGOS_OPERA_LEGADO = {"SI", "NO", "-"}


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def _engine():
    url = URL.create(
        drivername="postgresql+psycopg",
        username=_require_env("MART_USER_USER"),
        password=_require_env("MART_USER_PASSWORD"),
        host=_require_env("ANALITICO_PG_HOST"),
        port=int(os.environ.get("ANALITICO_PG_PORT", "5432")),
        database=os.environ.get("ANALITICO_PG_DATABASE", "sietel_analitico"),
    )
    return create_engine(url, connect_args={"connect_timeout": 10})


SQL_PARES_CANDIDATOS = """
WITH pevas_por_ruc AS (
    -- Una fila por peva_codigo -- v_ultimo_periodo_reportado_detalle tiene
    -- múltiples filas por PEVA (una por geografía/tipo de enlace del
    -- último período), hay que colapsar antes de comparar. Ver el bug
    -- encontrado y corregido en el diagnóstico manual del 28-jul-2026.
    SELECT DISTINCT ON (v.peva_codigo)
        NULLIF(REGEXP_REPLACE(COALESCE(v.isp_ruc::text, ''), '[^0-9]', '', 'g'), '') AS ruc_limpio,
        v.peva_codigo,
        v.isp_nombre,
        v.opera,
        v.fechaPermiso AS fecha_permiso
    FROM analitico.v_ultimo_periodo_reportado_detalle v
    WHERE v.peva_codigo IS NOT NULL
      AND COALESCE(v.isp_nombre::text, '') NOT ILIKE '%prueba%'
      AND COALESCE(v.nombreComercial::text, '') NOT ILIKE '%prueba%'
    ORDER BY v.peva_codigo, v.ultimo_anio DESC NULLS LAST, v.ultimo_periodo_numero DESC NULLS LAST
),
ruc_multi AS (
    SELECT ruc_limpio
    FROM pevas_por_ruc
    WHERE ruc_limpio IS NOT NULL
    GROUP BY ruc_limpio
    HAVING COUNT(DISTINCT peva_codigo) > 1
)
SELECT
    a.ruc_limpio,
    a.peva_codigo AS peva_a, a.isp_nombre AS isp_nombre_a, a.opera AS opera_a, a.fecha_permiso AS fecha_a,
    b.peva_codigo AS peva_b, b.isp_nombre AS isp_nombre_b, b.opera AS opera_b, b.fecha_permiso AS fecha_b
FROM pevas_por_ruc a
JOIN pevas_por_ruc b
  ON a.ruc_limpio = b.ruc_limpio
 AND a.peva_codigo < b.peva_codigo
WHERE a.ruc_limpio IN (SELECT ruc_limpio FROM ruc_multi);
"""

SQL_COEXISTEN = """
SELECT 1
FROM analitico.v_lineas_dedicadas_resumen ra
JOIN analitico.v_lineas_dedicadas_resumen rb
  ON ra.anio = rb.anio AND ra.periodoNumero = rb.periodoNumero
WHERE ra.peva_codigo = :peva_a AND rb.peva_codigo = :peva_b
LIMIT 1;
"""

SQL_UPSERT = """
INSERT INTO calidad.conflictos_ruc_peva (
    ruc_limpio, peva_a, peva_b,
    isp_nombre_a, isp_nombre_b, opera_a, opera_b, fecha_permiso_a, fecha_permiso_b,
    categoria, peva_legado_descartado, coexisten_en_periodo, accion_recomendada,
    estado_revision, revisado_por, notas_revision, fecha_revision,
    fecha_deteccion, fecha_ultima_deteccion
)
VALUES (
    :ruc_limpio, :peva_a, :peva_b,
    :isp_nombre_a, :isp_nombre_b, :opera_a, :opera_b, :fecha_a, :fecha_b,
    :categoria, :peva_legado_descartado, :coexisten_en_periodo, :accion_recomendada,
    :estado_revision_inicial, :revisado_por_inicial, :notas_revision_inicial, :fecha_revision_inicial,
    now(), now()
)
ON CONFLICT (ruc_limpio, peva_a, peva_b) DO UPDATE SET
    isp_nombre_a           = EXCLUDED.isp_nombre_a,
    isp_nombre_b           = EXCLUDED.isp_nombre_b,
    opera_a                = EXCLUDED.opera_a,
    opera_b                = EXCLUDED.opera_b,
    fecha_permiso_a        = EXCLUDED.fecha_permiso_a,
    fecha_permiso_b        = EXCLUDED.fecha_permiso_b,
    categoria              = EXCLUDED.categoria,
    peva_legado_descartado = EXCLUDED.peva_legado_descartado,
    coexisten_en_periodo   = EXCLUDED.coexisten_en_periodo,
    accion_recomendada     = EXCLUDED.accion_recomendada,
    fecha_ultima_deteccion = now()
    -- DELIBERADO: estado_revision, revisado_por, notas_revision y
    -- fecha_revision NO se tocan en el UPDATE -- preserva cualquier
    -- decisión humana ya registrada. Solo se fijan en el INSERT inicial.
;
"""


def _es_legado(opera: str | None) -> bool:
    return (opera or "").strip().upper() in CODIGOS_OPERA_LEGADO


def clasificar(par: dict, coexisten: bool) -> dict:
    nombre_a = (par["isp_nombre_a"] or "").strip().lower()
    nombre_b = (par["isp_nombre_b"] or "").strip().lower()
    mismo_nombre_exacto = nombre_a == nombre_b
    # Señal adicional, deliberadamente más amplia que la igualdad exacta de
    # texto: si cualquiera de los dos nombres trae la marca "cancelad..."
    # (ej. "ARROYO VERA JORGE BYRON - CANCELADO", "SKYWEB cancelado 2011"),
    # es evidencia explícita de que ese registro es un permiso cerrado del
    # MISMO titular, aunque el texto completo no sea idéntico al del PEVA
    # vigente. Confirmado con los casos reales de Skyweb y Arroyo Vera
    # (28-jul-2026) -- la igualdad exacta de texto los clasificaba
    # incorrectamente como Grupo C (nombres distintos).
    marca_cancelacion_en_nombre = "cancelad" in nombre_a or "cancelad" in nombre_b
    mismo_titular = mismo_nombre_exacto or marca_cancelacion_en_nombre

    legado_a = _es_legado(par["opera_a"])
    legado_b = _es_legado(par["opera_b"])

    if mismo_nombre_exacto and (legado_a != legado_b):
        categoria = "A_DUPLICADO_MIGRACION_CODIFICACION"
        peva_legado = par["peva_a"] if legado_a else par["peva_b"]
        return {
            "categoria": categoria,
            "peva_legado_descartado": peva_legado,
            "accion_recomendada": "DESCARTAR_LEGADO",
            "estado_revision_inicial": "CONFIRMADO_AUTOMATICO",
            "revisado_por_inicial": "sistema (regla A confirmada 28-jul-2026)",
            "notas_revision_inicial": (
                "Mismo isp_nombre, un lado con codificación heredada de 'opera' "
                f"({par['opera_a'] if legado_a else par['opera_b']!r}). Se descarta "
                f"{peva_legado} y se conserva el registro con codificación categórica."
            ),
            "fecha_revision_inicial": date.today(),
        }

    if mismo_titular:
        categoria = "B_SECUENCIA_MISMO_TITULAR"
        if coexisten:
            accion = "REVISION_MANUAL_SIETEL"
            estado_inicial = "PENDIENTE"
        else:
            accion = "SIN_CONFLICTO_NO_COEXISTEN"
            estado_inicial = "CONFIRMADO_AUTOMATICO"
        return {
            "categoria": categoria,
            "peva_legado_descartado": None,
            "accion_recomendada": accion,
            "estado_revision_inicial": estado_inicial,
            "revisado_por_inicial": "sistema" if not coexisten else None,
            "notas_revision_inicial": (
                "Mismo titular (nombre igual o con marca de cancelación explícita), fechas de permiso distintas, "
                "nunca coexisten "
                "reportando en el mismo período -- no hay conflicto real que resolver."
                if not coexisten
                else None
            ),
            "fecha_revision_inicial": date.today() if not coexisten else None,
        }

    return {
        "categoria": "C_NOMBRES_DISTINTOS_MISMO_RUC",
        "peva_legado_descartado": None,
        "accion_recomendada": "REVISION_MANUAL_SIETEL",
        "estado_revision_inicial": "PENDIENTE",
        "revisado_por_inicial": None,
        "notas_revision_inicial": None,
        "fecha_revision_inicial": None,
    }


def detectar_conflictos_peva(dry_run: bool = False) -> dict[str, int]:
    """
    Función invocable directamente (sin CLI/argparse) -- la que importa
    dags/sietel_mart_pipeline.py, igual que scripts/cargar_hechos_anio.py
    expone cargar_hechos_anio(anio) para su propio DAG.

    Devuelve el resumen de clasificación {categoria: cantidad}.
    """
    engine = _engine()
    resumen = {"A_DUPLICADO_MIGRACION_CODIFICACION": 0, "B_SECUENCIA_MISMO_TITULAR": 0,
               "C_NOMBRES_DISTINTOS_MISMO_RUC": 0}

    with engine.connect() as conn:
        pares = conn.execute(text(SQL_PARES_CANDIDATOS)).mappings().all()
        logger.info("Pares candidatos encontrados: %d", len(pares))

        filas_a_escribir = []
        for par in pares:
            coexisten = conn.execute(
                text(SQL_COEXISTEN), {"peva_a": par["peva_a"], "peva_b": par["peva_b"]}
            ).one_or_none() is not None

            clasificacion = clasificar(dict(par), coexisten)
            resumen[clasificacion["categoria"]] += 1

            filas_a_escribir.append(
                {
                    "ruc_limpio": par["ruc_limpio"],
                    "peva_a": par["peva_a"],
                    "peva_b": par["peva_b"],
                    "isp_nombre_a": par["isp_nombre_a"],
                    "isp_nombre_b": par["isp_nombre_b"],
                    "opera_a": par["opera_a"],
                    "opera_b": par["opera_b"],
                    "fecha_a": par["fecha_a"],
                    "fecha_b": par["fecha_b"],
                    "coexisten_en_periodo": coexisten,
                    **clasificacion,
                }
            )

    logger.info(
        "Clasificación: Grupo A=%d (auto-resuelto), Grupo B=%d, Grupo C=%d",
        resumen["A_DUPLICADO_MIGRACION_CODIFICACION"],
        resumen["B_SECUENCIA_MISMO_TITULAR"],
        resumen["C_NOMBRES_DISTINTOS_MISMO_RUC"],
    )

    if dry_run:
        logger.info("--dry-run: no se escribió nada en calidad.conflictos_ruc_peva.")
        return resumen

    with engine.begin() as conn:
        for fila in filas_a_escribir:
            conn.execute(text(SQL_UPSERT), fila)

    logger.info("calidad.conflictos_ruc_peva actualizado: %d pares.", len(filas_a_escribir))
    logger.info(
        "Los PEVA del Grupo A confirmados quedan disponibles en calidad.vw_pevas_excluidos "
        "para que construir_capa2.py los excluya antes de agregar."
    )
    return resumen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo reporta, no escribe en calidad.conflictos_ruc_peva")
    args = parser.parse_args(argv)

    detectar_conflictos_peva(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
