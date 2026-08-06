"""
mart/cargar_parroquias.py

Carga el shapefile de parroquias de CONALI (mart/data/shapefiles/parroquial/
ORGANIZACION_TERRITORIAL_PARROQUIAL.shp -- ver README.md en esa carpeta para
el esquema de atributos y cómo llega ahí) a capa2.parroquias_geometria, como
GeoJSON. Mismo patrón que samm_pipeline (app/data_to_server/
load_geographic_regions.py): geopandas se usa AQUÍ, una sola vez, para leer
el shapefile -- el cruce punto-en-polígono en sí (mart/
detectar_discrepancias_geografia_nodo.py) usa shapely + STRtree sin
geopandas, contra las geometrías ya cargadas en Postgres.

Vive en capa2, no en mart: mart se reconstruye completo (DROP SCHEMA CASCADE)
en cada corrida de aplicar_capa3.py -- recargar 1.052 geometrías (~223 MB de
shapefile) en cada refresco sería un desperdicio. capa2 persiste entre
corridas, igual que capa2.lineas_dedicadas_consolidado y
capa2.nodo_isp_geocodificado.

Carga IDEMPOTENTE: si la tabla ya tiene datos, no hace nada -- mismo
criterio que should_insert_geographic_data() en samm_pipeline. Para forzar
una recarga (ej. CONALI publica una actualización), usar --forzar.

Uso:
    python cargar_parroquias.py                # carga solo si está vacía
    python cargar_parroquias.py --forzar        # recarga aunque ya tenga datos
    python cargar_parroquias.py --dry-run       # solo valida el shapefile, no escribe
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

import geopandas as gpd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

load_dotenv()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RUTA_SHAPEFILE = (
        Path(__file__).resolve().parent
        / "data" / "shapefiles" / "parroquial" / "ORGANIZACION_TERRITORIAL_PARROQUIAL.shp"
)

# Columnas de atributos confirmadas leyendo el .dbf real (06-ago-2026) --
# ver mart/data/shapefiles/parroquial/README.md. Si CONALI cambia el
# esquema en una actualización futura, este script debe fallar explícito
# (KeyError), no adivinar un nombre de columna parecido.
COLUMNAS_REQUERIDAS = [
    "DPA_PARROQ", "DPA_DESPAR", "DPA_CANTON", "DPA_DESCAN",
    "DPA_PROVIN", "DPA_DESPRO", "DPA_ANIO",
]


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


_SENTENCIAS_DDL = [
    "CREATE SCHEMA IF NOT EXISTS capa2;",
    """
    CREATE TABLE IF NOT EXISTS capa2.parroquias_geometria (
        codigo_parroquia    VARCHAR(20) PRIMARY KEY,
        nombre_parroquia    VARCHAR(150) NOT NULL,
        codigo_canton       VARCHAR(20) NOT NULL,
        nombre_canton       VARCHAR(150) NOT NULL,
        codigo_provincia    VARCHAR(20) NOT NULL,
        nombre_provincia    VARCHAR(150) NOT NULL,
        anio_corte          VARCHAR(4),
        geometria_geojson   JSONB NOT NULL,
        fuente              VARCHAR(100) NOT NULL DEFAULT 'CONALI',
        fecha_carga         TIMESTAMP NOT NULL DEFAULT now()
    );
    """,
    "CREATE INDEX IF NOT EXISTS ix_parroquias_geometria_canton ON capa2.parroquias_geometria (codigo_canton);",
    "CREATE INDEX IF NOT EXISTS ix_parroquias_geometria_provincia ON capa2.parroquias_geometria (codigo_provincia);",
    """
    COMMENT ON TABLE capa2.parroquias_geometria IS
    'Geometrías de parroquias de Ecuador, fuente CONALI (ver mart/data/shapefiles/parroquial/README.md para el detalle y la fecha de corte). Cargada una sola vez por mart/cargar_parroquias.py (idempotente) -- no se recarga en cada refresco de mart. Códigos VARCHAR(20), no numéricos de ancho fijo: CONALI incluye zonas especiales (en disputa/en estudio, insulares) con texto en vez de código INEC de 2/4/6 dígitos -- ver log de la carga para el listado de códigos no estándar detectados. Consumida por mart/detectar_discrepancias_geografia_nodo.py via shapely + STRtree, sin geopandas en tiempo de cruce.';
    """,
]

_PATRON_PROVINCIA = re.compile(r"^\d{2}$")
_PATRON_CANTON = re.compile(r"^\d{4}$")
_PATRON_PARROQUIA = re.compile(r"^\d{6}$")


def _reportar_codigos_no_estandar(gdf) -> None:
    """
    Reporta (no excluye) parroquias cuyo código no sigue el patrón INEC
    esperado (provincia 2 dígitos, cantón 4, parroquia 6) -- CONALI incluye
    zonas especiales (ej. 'ISLA', '900651 ZONA EN ESTUDIO...') que no
    encajan en ese patrón. No se descartan: si un nodo cae dentro de una de
    estas zonas, el cruce espacial (Parte B) lo va a marcar como
    discrepancia frente a cualquier par_codigo real reportado -- lo cual es
    correcto, no un error del cruce -- pero conviene saber de antemano
    cuántas y cuáles son estas zonas antes de interpretar esos resultados.
    """
    anomalos = gdf[
        ~gdf["DPA_PROVIN"].astype(str).str.match(_PATRON_PROVINCIA)
        | ~gdf["DPA_CANTON"].astype(str).str.match(_PATRON_CANTON)
        | ~gdf["DPA_PARROQ"].astype(str).str.match(_PATRON_PARROQUIA)
        ]
    if anomalos.empty:
        logger.info("Todos los códigos siguen el patrón INEC estándar (provincia 2 dígitos / cantón 4 / parroquia 6).")
        return

    logger.warning(
        "%s parroquia(s) con código fuera del patrón INEC estándar -- se cargan igual, tal cual las reporta CONALI:",
        len(anomalos),
    )
    for _, row in anomalos.iterrows():
        logger.warning(
            "  parroquia=%r canton=%r provincia=%r nombre_parroquia=%r",
            row["DPA_PARROQ"], row["DPA_CANTON"], row["DPA_PROVIN"], row["DPA_DESPAR"],
        )


def _tabla_tiene_datos(engine) -> bool:
    with engine.connect() as conn:
        existe = conn.execute(
            text("SELECT TO_REGCLASS('capa2.parroquias_geometria') IS NOT NULL")
        ).scalar_one()
        if not existe:
            return False
        total = conn.execute(text("SELECT COUNT(*) FROM capa2.parroquias_geometria")).scalar_one()
        return total > 0


def cargar_parroquias(forzar: bool = False, dry_run: bool = False) -> None:
    if not RUTA_SHAPEFILE.exists():
        raise FileNotFoundError(
            f"No se encontró {RUTA_SHAPEFILE}. Ver mart/data/shapefiles/parroquial/README.md "
            f"para el comando scp de transferencia -- el shapefile nunca viaja por Git."
        )

    logger.info("Leyendo shapefile: %s", RUTA_SHAPEFILE)
    gdf = gpd.read_file(RUTA_SHAPEFILE)
    logger.info("Shapefile leído: %s parroquias, CRS declarado: %s", len(gdf), gdf.crs)

    faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in gdf.columns]
    if faltantes:
        raise KeyError(
            f"El shapefile no tiene las columnas esperadas: {faltantes}. "
            f"Columnas disponibles: {list(gdf.columns)}. "
            f"¿Cambió el esquema de CONALI? Actualiza COLUMNAS_REQUERIDAS y "
            f"mart/data/shapefiles/parroquial/README.md antes de continuar."
        )

    # Mismo criterio de seguridad que samm_pipeline: si el CRS no está
    # declarado, no asumir en silencio -- registrar la advertencia y asumir
    # WGS84 (EPSG:4326) explícitamente, que es lo que espera shapely/STRtree
    # más adelante (coordenadas ya vienen en WGS84 desde
    # limpiar_coordenadas_nodo_isp.py).
    if gdf.crs is None:
        logger.warning(
            "El shapefile no declara un sistema de coordenadas (.prj vacío o ausente). "
            "Asumiendo WGS84 (EPSG:4326) -- confirmar que esto es correcto antes de usar los resultados."
        )
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        logger.info("Reproyectando de %s a WGS84 (EPSG:4326)...", gdf.crs)
        gdf = gdf.to_crs("EPSG:4326")

    # Validez geométrica -- un shapefile de fuente oficial puede igual traer
    # polígonos inválidos (auto-intersecciones al digitalizar). No se
    # "arreglan" en silencio (buffer(0) es una corrección común pero altera
    # la geometría reportada por CONALI) -- se reportan, y quedan fuera de
    # esta carga hasta que alguien decida qué hacer con ellos.
    invalidas = gdf[~gdf.geometry.is_valid]
    if not invalidas.empty:
        codigos_invalidos = invalidas["DPA_PARROQ"].tolist()
        logger.warning(
            "%s parroquia(s) con geometría inválida, EXCLUIDAS de esta carga: %s",
            len(invalidas), codigos_invalidos,
        )
        gdf = gdf[gdf.geometry.is_valid]

    _reportar_codigos_no_estandar(gdf)

    registros = [
        {
            "codigo_parroquia": row["DPA_PARROQ"],
            "nombre_parroquia": row["DPA_DESPAR"],
            "codigo_canton": row["DPA_CANTON"],
            "nombre_canton": row["DPA_DESCAN"],
            "codigo_provincia": row["DPA_PROVIN"],
            "nombre_provincia": row["DPA_DESPRO"],
            "anio_corte": row["DPA_ANIO"],
            "geometria_geojson": json.dumps(row.geometry.__geo_interface__),
        }
        for _, row in gdf.iterrows()
    ]

    logger.info("%s parroquias listas para cargar (tras excluir inválidas).", len(registros))

    if dry_run:
        logger.info("--dry-run: shapefile validado, no se escribió nada.")
        return

    engine = _engine()

    if _tabla_tiene_datos(engine) and not forzar:
        logger.info(
            "capa2.parroquias_geometria ya tiene datos -- carga omitida (idempotente). "
            "Usa --forzar para recargar."
        )
        return

    with engine.begin() as conn:
        for sentencia in _SENTENCIAS_DDL:
            conn.execute(text(sentencia))
        conn.execute(text("TRUNCATE TABLE capa2.parroquias_geometria;"))
        conn.execute(
            text("""
                INSERT INTO capa2.parroquias_geometria (
                    codigo_parroquia, nombre_parroquia, codigo_canton, nombre_canton,
                    codigo_provincia, nombre_provincia, anio_corte, geometria_geojson
                ) VALUES (
                    :codigo_parroquia, :nombre_parroquia, :codigo_canton, :nombre_canton,
                    :codigo_provincia, :nombre_provincia, :anio_corte, CAST(:geometria_geojson AS JSONB)
                )
            """),
            registros,
        )

    logger.info("capa2.parroquias_geometria cargada: %s parroquias.", len(registros))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forzar", action="store_true", help="Recarga aunque la tabla ya tenga datos")
    parser.add_argument("--dry-run", action="store_true", help="Solo valida el shapefile, no escribe nada")
    args = parser.parse_args(argv)

    cargar_parroquias(forzar=args.forzar, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
