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

AGREGADO 07-ago-2026: también precalcula y guarda las geometrías DISUELTAS
de cantón y provincia (capa2.territorio_geometria_nodo, vía
gdf.dissolve() de geopandas) -- confirmado en producción que unir decenas/
cientos de parroquias con shapely EN CADA PETICIÓN del dashboard (nivel
cantón) o CIENTOS por petición (nivel provincia) era demasiado lento,
dejando la página del mapa esperando varios segundos. Se calcula una sola
vez aquí, junto con la carga del shapefile -- el dashboard solo hace un
SELECT directo (services/queries.py:get_territory_geojson), sin shapely.

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
    """
    CREATE TABLE IF NOT EXISTS capa2.territorio_geometria_nodo (
        nivel_geografico    VARCHAR(20) NOT NULL,
        codigo_territorio   VARCHAR(20) NOT NULL,
        nombre_territorio   VARCHAR(150) NOT NULL,
        geometria_geojson   JSONB NOT NULL,
        lon_min DOUBLE PRECISION NOT NULL,
        lat_min DOUBLE PRECISION NOT NULL,
        lon_max DOUBLE PRECISION NOT NULL,
        lat_max DOUBLE PRECISION NOT NULL,
        fecha_carga         TIMESTAMP NOT NULL DEFAULT now(),
        PRIMARY KEY (nivel_geografico, codigo_territorio)
    );
    """,
    """
    COMMENT ON TABLE capa2.territorio_geometria_nodo IS
    'Geometrías PRECALCULADAS por nivel geográfico (parroquia/cantón/provincia) para el mapa de nodos del dashboard -- cantón y provincia se arman con gdf.dissolve() (geopandas) UNA VEZ AQUÍ, no en cada petición del dashboard. Antes se unían con shapely en services/queries.py al momento de la consulta -- confirmado en producción 07-ago-2026 que era demasiado lento (varios segundos por petición a nivel provincia). Poblada junto con capa2.parroquias_geometria, misma idempotencia.';
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


def _contar_vertices(geom) -> int:
    """Cuenta vértices totales de un Polygon/MultiPolygon, para medir el
    efecto de simplify() antes/después -- no es una estimación, es exacta."""
    if geom.geom_type == "Polygon":
        return len(geom.exterior.coords) + sum(len(interior.coords) for interior in geom.interiors)
    if geom.geom_type == "MultiPolygon":
        return sum(_contar_vertices(g) for g in geom.geoms)
    return 0


# Tolerancia de simplify() en GRADOS (mismo sistema de coordenadas que el
# resto del pipeline, WGS84) -- 0.001° ≈ 111 m en el ecuador. Mayor
# tolerancia en niveles más grandes: una provincia con el detalle de costa
# completo de CONALI puede tener decenas de miles de vértices -- suficiente
# para colgar el navegador al dibujarla en Mapbox GL (confirmado en
# producción 07-ago-2026, "La página no responde" al elegir Provincia,
# incluso con la consulta SQL ya siendo instantánea). SOLO afecta
# capa2.territorio_geometria_nodo (geometría de DISPLAY del mapa) -- NUNCA
# capa2.parroquias_geometria, que alimenta el cruce punto-en-polígono real
# en mart/detectar_discrepancias_geografia_nodo.py y ahí sí necesita
# precisión completa, sin simplificar.
_TOLERANCIA_SIMPLIFY = {"PARROQUIA": 0.0005, "CANTON": 0.001, "PROVINCIA": 0.002}


def _geojson_simplificado(geom, nivel: str) -> tuple[str, int, int]:
    """Simplifica una sola vez y devuelve (geojson, vertices_antes, vertices_despues)."""
    vertices_antes = _contar_vertices(geom)
    simplificada = geom.simplify(_TOLERANCIA_SIMPLIFY[nivel], preserve_topology=True)
    vertices_despues = _contar_vertices(simplificada)
    return json.dumps(simplificada.__geo_interface__), vertices_antes, vertices_despues
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

    # Verificación idempotente PRIMERO, antes de leer el shapefile -- no
    # después. Confirmado en producción 07-ago-2026: la versión anterior
    # leía/reproyectaba el .shp de 223 MB completo (~35-40s) y RECIÉN
    # entonces comprobaba si hacía falta -- desperdiciando ese trabajo en
    # cada corrida mensual del DAG una vez que la tabla ya tiene datos.
    # --dry-run sigue leyendo el shapefile igual (para eso sirve: validar
    # sin escribir), pero una corrida normal ya cargada debe salir casi
    # instantáneo, sin tocar el archivo.
    if not dry_run:
        engine = _engine()
        if _tabla_tiene_datos(engine) and not forzar:
            logger.info(
                "capa2.parroquias_geometria ya tiene datos -- carga omitida (idempotente), "
                "sin leer el shapefile. Usa --forzar para recargar."
            )
            return

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

    # Geometrías disueltas de cantón y provincia -- gdf.dissolve() usa
    # shapely.ops.unary_union internamente, pero UNA SOLA VEZ aquí, no en
    # cada petición del dashboard (ver docstring del módulo).
    logger.info("Disolviendo geometrías por cantón y provincia (gdf.dissolve)...")

    registros_territorio = []
    vertices_antes_total = 0
    vertices_despues_total = 0

    parroquias_gdf = gdf.copy()
    parroquias_gdf["nivel_geografico"] = "PARROQUIA"
    for _, row in parroquias_gdf.iterrows():
        lon_min, lat_min, lon_max, lat_max = row.geometry.bounds
        geojson_simplificado, v_antes, v_despues = _geojson_simplificado(row.geometry, "PARROQUIA")
        vertices_antes_total += v_antes
        vertices_despues_total += v_despues
        registros_territorio.append({
            "nivel_geografico": "PARROQUIA",
            "codigo_territorio": row["DPA_PARROQ"],
            "nombre_territorio": row["DPA_DESPAR"],
            "geometria_geojson": geojson_simplificado,
            "lon_min": lon_min, "lat_min": lat_min, "lon_max": lon_max, "lat_max": lat_max,
        })

    cantones_gdf = gdf.dissolve(by=["DPA_PROVIN", "DPA_CANTON"], aggfunc={"DPA_DESCAN": "first"}).reset_index()
    for _, row in cantones_gdf.iterrows():
        lon_min, lat_min, lon_max, lat_max = row.geometry.bounds
        geojson_simplificado, v_antes, v_despues = _geojson_simplificado(row.geometry, "CANTON")
        vertices_antes_total += v_antes
        vertices_despues_total += v_despues
        registros_territorio.append({
            "nivel_geografico": "CANTON",
            "codigo_territorio": row["DPA_CANTON"],
            "nombre_territorio": row["DPA_DESCAN"],
            "geometria_geojson": geojson_simplificado,
            "lon_min": lon_min, "lat_min": lat_min, "lon_max": lon_max, "lat_max": lat_max,
        })
    logger.info("%s cantones disueltos.", len(cantones_gdf))

    provincias_gdf = gdf.dissolve(by="DPA_PROVIN", aggfunc={"DPA_DESPRO": "first"}).reset_index()
    for _, row in provincias_gdf.iterrows():
        lon_min, lat_min, lon_max, lat_max = row.geometry.bounds
        geojson_simplificado, v_antes, v_despues = _geojson_simplificado(row.geometry, "PROVINCIA")
        vertices_antes_total += v_antes
        vertices_despues_total += v_despues
        registros_territorio.append({
            "nivel_geografico": "PROVINCIA",
            "codigo_territorio": row["DPA_PROVIN"],
            "nombre_territorio": row["DPA_DESPRO"],
            "geometria_geojson": geojson_simplificado,
            "lon_min": lon_min, "lat_min": lat_min, "lon_max": lon_max, "lat_max": lat_max,
        })
    logger.info("%s provincias disueltas.", len(provincias_gdf))

    reduccion_pct = (
        100 * (1 - vertices_despues_total / vertices_antes_total) if vertices_antes_total else 0
    )
    logger.info(
        "Simplificación de geometría de display: %s vértices -> %s vértices (%.1f%% de reducción). "
        "capa2.parroquias_geometria (cruce punto-en-polígono) NO se toca -- geometría completa, sin simplificar.",
        vertices_antes_total, vertices_despues_total, reduccion_pct,
    )

    if dry_run:
        logger.info("--dry-run: shapefile validado, no se escribió nada.")
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
        conn.execute(text("TRUNCATE TABLE capa2.territorio_geometria_nodo;"))
        conn.execute(
            text("""
                INSERT INTO capa2.territorio_geometria_nodo (
                    nivel_geografico, codigo_territorio, nombre_territorio,
                    geometria_geojson, lon_min, lat_min, lon_max, lat_max
                ) VALUES (
                    :nivel_geografico, :codigo_territorio, :nombre_territorio,
                    CAST(:geometria_geojson AS JSONB), :lon_min, :lat_min, :lon_max, :lat_max
                )
            """),
            registros_territorio,
        )

    logger.info(
        "capa2.parroquias_geometria cargada: %s parroquias. "
        "capa2.territorio_geometria_nodo cargada: %s registros (%s parroquia + %s cantón + %s provincia).",
        len(registros), len(registros_territorio), len(parroquias_gdf), len(cantones_gdf), len(provincias_gdf),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forzar", action="store_true", help="Recarga aunque la tabla ya tenga datos")
    parser.add_argument("--dry-run", action="store_true", help="Solo valida el shapefile, no escribe nada")
    args = parser.parse_args(argv)

    cargar_parroquias(forzar=args.forzar, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
