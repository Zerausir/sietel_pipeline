"""
mart/detectar_discrepancias_geografia_nodo.py

Parte B del geoprocesamiento de nodos ISP (conversación 06/07-ago-2026):
cruza la coordenada decimal de cada nodo (capa2.nodo_isp_geocodificado,
Parte A) contra las geometrías de parroquia (capa2.parroquias_geometria,
shapefile CONALI) vía punto-en-polígono, y compara la parroquia DERIVADA de
la coordenada contra la parroquia REPORTADA en SIETEL
(analitico.v_nodo_isp_vigente.codigo_parroquia, código INEC). Las
discrepancias quedan en calidad.discrepancias_geografia_nodo con el mismo
patrón de workflow humano persistente que calidad.conflictos_ruc_peva
(detectar_conflictos_peva.py): columnas derivadas de los datos de origen se
actualizan en cada corrida, columnas de revisión (estado_revision,
revisado_por, notas_revision, fecha_revision) solo se fijan la primera vez.

Mismo split que samm_pipeline (app/utils/spatial_mapper.py): geopandas no
se usa aquí -- las geometrías ya están en Postgres como GeoJSON (cargadas
una sola vez por mart/cargar_parroquias.py). Este script solo usa shapely
+ STRtree, sin geopandas, para el cruce punto-en-polígono en sí.

geometry.covers(point), NO point.within(geometry): covers() incluye la
frontera del polígono, within() la excluye -- un nodo capturado justo sobre
un límite parroquial (común en zonas urbanas densas) quedaría sin match con
within(). Mismo fix ya aplicado en samm_pipeline (FIX #5, 2026-03-20).

ALCANCE DELIBERADAMENTE ACOTADO -- tres categorías de nodo NO entran a
calidad.discrepancias_geografia_nodo, se reportan aparte en el log:
  - Coordenada inválida (es_coordenada_valida=false en Parte A): "no sé
    dónde está", no "sé dónde está y no coincide". Ya visible en
    capa2.nodo_isp_geocodificado.
  - Sin codigo_parroquia reportado (par_codigo huérfano en SIETEL, o nunca
    capturado): no hay con qué comparar el lado "reportado".
  - Sin match espacial (la coordenada, aunque válida y dentro del bounding
    box de Ecuador, no cae dentro de ningún polígono del shapefile -- ej.
    imprecisión en la frontera, o coordenada en el mar): no hay con qué
    comparar el lado "derivado". calidad.discrepancias_geografia_nodo exige
    NOT NULL en las columnas derivadas -- estos nodos no pueden insertarse
    ahí aunque quisiéramos.

LIMITACIÓN CONOCIDA, mismo patrón que calidad.conflictos_ruc_peva: si una
discrepancia ya registrada deja de serlo (SIETEL corrige el par_codigo, o
se corrige la coordenada), la fila NO se borra sola -- queda con
fecha_ultima_deteccion vieja hasta que alguien la revise manualmente.
Limpiar discrepancias resueltas es una tarea de revisión humana, no
automática -- mismo criterio ya aplicado a RUC/PEVA.

Uso:
    python detectar_discrepancias_geografia_nodo.py --dry-run
    python detectar_discrepancias_geografia_nodo.py
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv
from shapely.geometry import Point, shape
from shapely.strtree import STRtree
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

load_dotenv()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


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


SQL_NODOS = """
WITH isp_por_peva AS (
    -- Mismo patrón de colapso que detectar_conflictos_peva.py:
    -- v_ultimo_periodo_reportado_detalle tiene múltiples filas por PEVA.
    SELECT DISTINCT ON (v.peva_codigo)
        v.peva_codigo, v.isp_nombre
    FROM analitico.v_ultimo_periodo_reportado_detalle v
    WHERE v.peva_codigo IS NOT NULL
    ORDER BY v.peva_codigo, v.ultimo_anio DESC NULLS LAST, v.ultimo_periodo_numero DESC NULLS LAST
)
SELECT
    g.noisp_codigo, g.peva_codigo, g.noisp_nombre, g.tiponodo,
    g.latitud_decimal, g.longitud_decimal,
    n.codigo_parroquia AS codigo_parroquia_reportado,
    n.par_nombre AS parroquia_reportada_nombre,
    n.codigo_canton AS codigo_canton_reportado,
    n.ciu_nombre AS canton_reportado_nombre,
    n.codigo_provincia AS codigo_provincia_reportado,
    n.pro_nombre AS provincia_reportada_nombre,
    i.isp_nombre
FROM capa2.nodo_isp_geocodificado g
JOIN analitico.v_nodo_isp_vigente n ON n.noisp_codigo = g.noisp_codigo
LEFT JOIN isp_por_peva i ON i.peva_codigo = g.peva_codigo
WHERE g.es_coordenada_valida = true
"""

SQL_PARROQUIAS = """
SELECT codigo_parroquia, nombre_parroquia, codigo_canton, nombre_canton,
       codigo_provincia, nombre_provincia, geometria_geojson
FROM capa2.parroquias_geometria
"""

SQL_UPSERT = """
INSERT INTO calidad.discrepancias_geografia_nodo (
    noisp_codigo, peva_codigo, isp_nombre, noisp_nombre, tiponodo,
    latitud_decimal, longitud_decimal,
    par_codigo_reportado, parroquia_reportada_nombre,
    canton_reportado_nombre, provincia_reportada_nombre,
    codigo_parroquia_derivado, parroquia_derivada_nombre,
    codigo_canton_derivado, canton_derivado_nombre,
    codigo_provincia_derivado, provincia_derivada_nombre,
    estado_revision, revisado_por, notas_revision, fecha_revision,
    fecha_deteccion, fecha_ultima_deteccion
)
VALUES (
    :noisp_codigo, :peva_codigo, :isp_nombre, :noisp_nombre, :tiponodo,
    :latitud_decimal, :longitud_decimal,
    :codigo_parroquia_reportado, :parroquia_reportada_nombre,
    :canton_reportado_nombre, :provincia_reportada_nombre,
    :codigo_parroquia_derivado, :parroquia_derivada_nombre,
    :codigo_canton_derivado, :canton_derivado_nombre,
    :codigo_provincia_derivado, :provincia_derivada_nombre,
    'PENDIENTE', NULL, NULL, NULL,
    now(), now()
)
ON CONFLICT (noisp_codigo) DO UPDATE SET
    peva_codigo                = EXCLUDED.peva_codigo,
    isp_nombre                 = EXCLUDED.isp_nombre,
    noisp_nombre                = EXCLUDED.noisp_nombre,
    tiponodo                    = EXCLUDED.tiponodo,
    latitud_decimal             = EXCLUDED.latitud_decimal,
    longitud_decimal            = EXCLUDED.longitud_decimal,
    par_codigo_reportado         = EXCLUDED.par_codigo_reportado,
    parroquia_reportada_nombre   = EXCLUDED.parroquia_reportada_nombre,
    canton_reportado_nombre      = EXCLUDED.canton_reportado_nombre,
    provincia_reportada_nombre   = EXCLUDED.provincia_reportada_nombre,
    codigo_parroquia_derivado    = EXCLUDED.codigo_parroquia_derivado,
    parroquia_derivada_nombre    = EXCLUDED.parroquia_derivada_nombre,
    codigo_canton_derivado       = EXCLUDED.codigo_canton_derivado,
    canton_derivado_nombre       = EXCLUDED.canton_derivado_nombre,
    codigo_provincia_derivado    = EXCLUDED.codigo_provincia_derivado,
    provincia_derivada_nombre    = EXCLUDED.provincia_derivada_nombre,
    fecha_ultima_deteccion       = now()
    -- DELIBERADO: estado_revision, revisado_por, notas_revision y
    -- fecha_revision NO se tocan en el UPDATE -- preserva cualquier
    -- decisión humana ya registrada. Mismo patrón que conflictos_ruc_peva.
;
"""


def _cargar_indice_espacial(conn) -> tuple[STRtree, list[dict]]:
    """
    Carga capa2.parroquias_geometria, parsea cada GeoJSON UNA sola vez, y
    construye un STRtree -- mismo patrón que samm_pipeline
    (_load_region_geometries_cached). Cada metadato guarda su propia
    geometría ya parseada (clave "_geom") para no re-parsear JSON por cada
    nodo consultado después -- STRtree.query() devuelve índices
    posicionales, así que el orden de metadatos debe coincidir exactamente
    con el orden de geometrías usado para construir el árbol.
    """
    filas = conn.execute(text(SQL_PARROQUIAS)).mappings().all()
    geometrias = []
    metadatos = []
    for fila in filas:
        geojson = fila["geometria_geojson"]
        if isinstance(geojson, str):
            geojson = json.loads(geojson)
        geom = shape(geojson)
        geometrias.append(geom)
        metadato = dict(fila)
        metadato["_geom"] = geom
        metadatos.append(metadato)

    tree = STRtree(geometrias)
    logger.info("Índice espacial construido: %d parroquias.", len(geometrias))
    return tree, metadatos


def detectar_discrepancias_geografia_nodo(dry_run: bool = False) -> dict[str, int]:
    engine = _engine()
    resumen = {
        "procesados": 0, "coinciden": 0, "discrepancias": 0,
        "sin_codigo_reportado": 0, "sin_match_espacial": 0,
    }

    with engine.connect() as conn:
        tree, metadatos_parroquias = _cargar_indice_espacial(conn)

        nodos = conn.execute(text(SQL_NODOS)).mappings().all()
        logger.info("Nodos con coordenada válida a procesar: %d", len(nodos))

        sin_match_codigos: list[str] = []
        filas_a_escribir = []

        for nodo in nodos:
            resumen["procesados"] += 1
            punto = Point(nodo["longitud_decimal"], nodo["latitud_decimal"])  # (x=lon, y=lat)

            parroquia_derivada = None
            for idx in tree.query(punto):
                candidata = metadatos_parroquias[idx]
                if candidata["_geom"].covers(punto):
                    parroquia_derivada = candidata
                    break

            if parroquia_derivada is None:
                resumen["sin_match_espacial"] += 1
                sin_match_codigos.append(nodo["noisp_codigo"])
                continue

            if not nodo["codigo_parroquia_reportado"]:
                resumen["sin_codigo_reportado"] += 1
                continue

            if nodo["codigo_parroquia_reportado"] == parroquia_derivada["codigo_parroquia"]:
                resumen["coinciden"] += 1
                continue

            resumen["discrepancias"] += 1
            filas_a_escribir.append({
                "noisp_codigo": nodo["noisp_codigo"],
                "peva_codigo": nodo["peva_codigo"],
                "isp_nombre": nodo["isp_nombre"],
                "noisp_nombre": nodo["noisp_nombre"],
                "tiponodo": nodo["tiponodo"],
                "latitud_decimal": nodo["latitud_decimal"],
                "longitud_decimal": nodo["longitud_decimal"],
                "codigo_parroquia_reportado": nodo["codigo_parroquia_reportado"],
                "parroquia_reportada_nombre": nodo["parroquia_reportada_nombre"],
                "canton_reportado_nombre": nodo["canton_reportado_nombre"],
                "provincia_reportada_nombre": nodo["provincia_reportada_nombre"],
                "codigo_parroquia_derivado": parroquia_derivada["codigo_parroquia"],
                "parroquia_derivada_nombre": parroquia_derivada["nombre_parroquia"],
                "codigo_canton_derivado": parroquia_derivada["codigo_canton"],
                "canton_derivado_nombre": parroquia_derivada["nombre_canton"],
                "codigo_provincia_derivado": parroquia_derivada["codigo_provincia"],
                "provincia_derivada_nombre": parroquia_derivada["nombre_provincia"],
            })

    logger.info(
        "Resumen: %d procesados -- %d coinciden, %d discrepancias, "
        "%d sin código reportado, %d sin match espacial",
        resumen["procesados"], resumen["coinciden"], resumen["discrepancias"],
        resumen["sin_codigo_reportado"], resumen["sin_match_espacial"],
    )
    if filas_a_escribir:
        muestra = filas_a_escribir[:30]
        logger.warning(
            "Muestra de %d discrepancias (de %d totales) -- reportado vs. derivado, "
            "para verificar plausibilidad antes de confiar en el agregado:",
            len(muestra), len(filas_a_escribir),
        )
        for f in muestra:
            logger.warning(
                "  %s (%s): reportado=%s/%s/%s (cod=%s) -- derivado=%s/%s/%s (cod=%s)",
                f["noisp_codigo"], f["isp_nombre"],
                f["provincia_reportada_nombre"], f["canton_reportado_nombre"], f["parroquia_reportada_nombre"],
                f["codigo_parroquia_reportado"],
                f["provincia_derivada_nombre"], f["canton_derivado_nombre"], f["parroquia_derivada_nombre"],
                f["codigo_parroquia_derivado"],
            )
    if sin_match_codigos:
        logger.warning(
            "Nodos sin match espacial (coordenada válida pero fuera de todas las "
            "parroquias del shapefile) -- revisar manualmente: %s",
            sin_match_codigos[:50] if len(sin_match_codigos) > 50 else sin_match_codigos,
        )
        if len(sin_match_codigos) > 50:
            logger.warning("... y %d más (truncado a 50 en el log).", len(sin_match_codigos) - 50)

    if dry_run:
        logger.info("--dry-run: no se escribió nada en calidad.discrepancias_geografia_nodo.")
        return resumen

    with engine.begin() as conn:
        for fila in filas_a_escribir:
            conn.execute(text(SQL_UPSERT), fila)

    logger.info(
        "calidad.discrepancias_geografia_nodo actualizado: %d discrepancias.",
        len(filas_a_escribir),
    )
    return resumen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo reporta, no escribe en calidad.discrepancias_geografia_nodo")
    args = parser.parse_args(argv)

    detectar_discrepancias_geografia_nodo(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
