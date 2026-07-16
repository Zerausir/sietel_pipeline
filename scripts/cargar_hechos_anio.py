"""
Carga de la tabla de hechos staging.va_lineas_dedicadas_resumen, un año
a la vez (parametrizado por el DAG).

FUENTE: dbo.VALineasDedicadas (SQL Server)
DESTINO: staging.va_lineas_dedicadas_resumen (PostgreSQL local)

ESTRATEGIA — AGREGADO EN ORIGEN:
La agregación se realiza en SQL Server antes de transferir, reduciendo
272M filas históricas a ~50K-200K filas por año. El índice compuesto
IX_VALineasDedicadas_Analitico (anio, periodoNumero, peva_codigo,
par_codigo) cubre el filtro y el GROUP BY. Reducción de red: 99%+.

CLASIFICACIÓN POR RANGOS DE VELOCIDAD (downLink y upLink en Kbps):
Rangos definidos a partir de la distribución real del mercado ecuatoriano
verificada con datos de diciembre 2025 (2.917.304 líneas):

  < 1 Mbps      (< 1.024 Kbps)  → sin banda ancha básica, brecha digital
  1 - 10 Mbps   (1.024 - 10.239 Kbps) → banda ancha básica (umbral ITU)
  10 - 30 Mbps  (10.240 - 30.719 Kbps) → banda ancha media (umbral OCDE)
  30 - 100 Mbps (30.720 - 102.399 Kbps) → banda ancha avanzada (umbral UE)
  100 Mbps - 1 Gbps (102.400 - 1.048.575 Kbps) → ultra banda ancha
  ≥ 1 Gbps      (>= 1.048.576 Kbps) → gigabit (segmento premium)
  Sin datos     (NULL o 0) → no reportado

Distribución diciembre 2025 verificada:
  < 1 Mbps:        40.436 líneas / 174.060 usuarios
  1-10 Mbps:       53.729 líneas / 322.022 usuarios
  10-30 Mbps:     114.084 líneas / 4.459.022 usuarios
  30-100 Mbps:    316.076 líneas / 4.978.130 usuarios
  100 Mbps-1 Gbps: 2.223.155 líneas / 14.332.328 usuarios
  ≥ 1 Gbps:       169.824 líneas / 1.990.096 usuarios

GROUP BY: peva_codigo, par_codigo, periodoNumero, periodoNombre, anio,
          tipoEnlace, tipoCliente, nivelComparticion, portador
Cardinalidad verificada enero 2025: tipoEnlace(4), tipoCliente(3),
nivelComparticion(14), portador(138) → granularidad manejable.
upLink(1.457) y downLink(955) → NO en GROUP BY, se convierten en métricas.
"""
import argparse
import hashlib
import logging
from datetime import datetime

from config import postgres_cursor, sqlserver_cursor

logger = logging.getLogger(__name__)

COLUMNAS_HASH = [
    "peva_codigo", "par_codigo", "periodoNumero", "anio",
    "tipoEnlace", "tipoCliente", "nivelComparticion", "portador",
    "total_lineas", "total_usuarios",
    # Rangos downLink
    "usuarios_dl_sin_datos",
    "usuarios_dl_menos_1mbps",
    "usuarios_dl_1_10mbps",
    "usuarios_dl_10_30mbps",
    "usuarios_dl_30_100mbps",
    "usuarios_dl_100mbps_1gbps",
    "usuarios_dl_1gbps_o_mas",
    # Rangos upLink
    "usuarios_ul_sin_datos",
    "usuarios_ul_menos_1mbps",
    "usuarios_ul_1_10mbps",
    "usuarios_ul_10_30mbps",
    "usuarios_ul_30_100mbps",
    "usuarios_ul_100mbps_1gbps",
    "usuarios_ul_1gbps_o_mas",
]


def calcular_hash_fila(fila: dict) -> str:
    valores = [
        str(fila.get(col)) if fila.get(col) is not None else "NULL"
        for col in COLUMNAS_HASH
    ]
    return hashlib.md5("|".join(valores).encode("utf-8")).hexdigest()


SQL_EXTRAER_HECHOS_ANIO = """
    SELECT
        ld.peva_codigo,
        ld.par_codigo,
        ld.periodoNumero,
        ld.periodoNombre,
        ld.anio,
        ld.tipoEnlace,
        ld.tipoCliente,
        ld.nivelComparticion,
        ld.portador,
        ld.regional,
        prov.pro_nombre,
        ciu.ciu_nombre,
        par.par_nombre,
        -- Volumen total
        COUNT(*)                                                    AS total_lineas,
        SUM(ld.numeroUsuarios)                                      AS total_usuarios,

        -- ── Clasificación por downLink (velocidad de bajada) ──────────────
        -- Sin datos: NULL o 0 Kbps — no reportado por el prestador
        SUM(CASE WHEN ld.downLink IS NULL OR ld.downLink = 0
                 THEN ld.numeroUsuarios ELSE 0 END)                 AS usuarios_dl_sin_datos,
        -- < 1 Mbps: sin banda ancha básica, brecha digital
        SUM(CASE WHEN ld.downLink > 0 AND ld.downLink < 1024
                 THEN ld.numeroUsuarios ELSE 0 END)                 AS usuarios_dl_menos_1mbps,
        -- 1 – 10 Mbps: banda ancha básica (umbral mínimo ITU)
        SUM(CASE WHEN ld.downLink >= 1024 AND ld.downLink < 10240
                 THEN ld.numeroUsuarios ELSE 0 END)                 AS usuarios_dl_1_10mbps,
        -- 10 – 30 Mbps: banda ancha media (umbral básico OCDE)
        SUM(CASE WHEN ld.downLink >= 10240 AND ld.downLink < 30720
                 THEN ld.numeroUsuarios ELSE 0 END)                 AS usuarios_dl_10_30mbps,
        -- 30 – 100 Mbps: banda ancha avanzada (umbral UE)
        SUM(CASE WHEN ld.downLink >= 30720 AND ld.downLink < 102400
                 THEN ld.numeroUsuarios ELSE 0 END)                 AS usuarios_dl_30_100mbps,
        -- 100 Mbps – 1 Gbps: ultra banda ancha (segmento dominante en Ecuador)
        SUM(CASE WHEN ld.downLink >= 102400 AND ld.downLink < 1048576
                 THEN ld.numeroUsuarios ELSE 0 END)                 AS usuarios_dl_100mbps_1gbps,
        -- ≥ 1 Gbps: gigabit (segmento premium)
        SUM(CASE WHEN ld.downLink >= 1048576
                 THEN ld.numeroUsuarios ELSE 0 END)                 AS usuarios_dl_1gbps_o_mas,

        -- ── Clasificación por upLink (velocidad de subida) ────────────────
        SUM(CASE WHEN ld.upLink IS NULL OR ld.upLink = 0
                 THEN ld.numeroUsuarios ELSE 0 END)                 AS usuarios_ul_sin_datos,
        SUM(CASE WHEN ld.upLink > 0 AND ld.upLink < 1024
                 THEN ld.numeroUsuarios ELSE 0 END)                 AS usuarios_ul_menos_1mbps,
        SUM(CASE WHEN ld.upLink >= 1024 AND ld.upLink < 10240
                 THEN ld.numeroUsuarios ELSE 0 END)                 AS usuarios_ul_1_10mbps,
        SUM(CASE WHEN ld.upLink >= 10240 AND ld.upLink < 30720
                 THEN ld.numeroUsuarios ELSE 0 END)                 AS usuarios_ul_10_30mbps,
        SUM(CASE WHEN ld.upLink >= 30720 AND ld.upLink < 102400
                 THEN ld.numeroUsuarios ELSE 0 END)                 AS usuarios_ul_30_100mbps,
        SUM(CASE WHEN ld.upLink >= 102400 AND ld.upLink < 1048576
                 THEN ld.numeroUsuarios ELSE 0 END)                 AS usuarios_ul_100mbps_1gbps,
        SUM(CASE WHEN ld.upLink >= 1048576
                 THEN ld.numeroUsuarios ELSE 0 END)                 AS usuarios_ul_1gbps_o_mas

    FROM dbo.VALineasDedicadas ld
    LEFT JOIN dbo.Parroquia par  ON par.par_codigo  = ld.par_codigo
    LEFT JOIN dbo.Ciudad    ciu  ON ciu.ciu_codigo  = par.ciu_codigo
    LEFT JOIN dbo.Provincia prov ON prov.pro_codigo = ciu.pro_codigo
    WHERE ld.anio = ?
    GROUP BY
        ld.peva_codigo, ld.par_codigo, ld.periodoNumero,
        ld.periodoNombre, ld.anio, ld.tipoEnlace,
        ld.tipoCliente, ld.nivelComparticion, ld.portador,
        ld.regional, prov.pro_nombre, ciu.ciu_nombre, par.par_nombre
"""

SQL_UPSERT_HECHOS = """
    INSERT INTO staging.va_lineas_dedicadas_resumen (
        peva_codigo, par_codigo, periodoNumero, periodoNombre, anio,
        tipoEnlace, tipoCliente, nivelComparticion, portador, regional,
        pro_nombre, ciu_nombre, par_nombre,
        total_lineas, total_usuarios,
        usuarios_dl_sin_datos, usuarios_dl_menos_1mbps,
        usuarios_dl_1_10mbps, usuarios_dl_10_30mbps,
        usuarios_dl_30_100mbps, usuarios_dl_100mbps_1gbps,
        usuarios_dl_1gbps_o_mas,
        usuarios_ul_sin_datos, usuarios_ul_menos_1mbps,
        usuarios_ul_1_10mbps, usuarios_ul_10_30mbps,
        usuarios_ul_30_100mbps, usuarios_ul_100mbps_1gbps,
        usuarios_ul_1gbps_o_mas,
        hash_contenido
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    ON CONFLICT (peva_codigo, par_codigo, periodoNumero, anio,
                 tipoEnlace, tipoCliente, nivelComparticion, portador)
    DO UPDATE SET
        periodoNombre             = EXCLUDED.periodoNombre,
        regional                  = EXCLUDED.regional,
        pro_nombre                = EXCLUDED.pro_nombre,
        ciu_nombre                = EXCLUDED.ciu_nombre,
        par_nombre                = EXCLUDED.par_nombre,
        total_lineas              = EXCLUDED.total_lineas,
        total_usuarios            = EXCLUDED.total_usuarios,
        usuarios_dl_sin_datos     = EXCLUDED.usuarios_dl_sin_datos,
        usuarios_dl_menos_1mbps   = EXCLUDED.usuarios_dl_menos_1mbps,
        usuarios_dl_1_10mbps      = EXCLUDED.usuarios_dl_1_10mbps,
        usuarios_dl_10_30mbps     = EXCLUDED.usuarios_dl_10_30mbps,
        usuarios_dl_30_100mbps    = EXCLUDED.usuarios_dl_30_100mbps,
        usuarios_dl_100mbps_1gbps = EXCLUDED.usuarios_dl_100mbps_1gbps,
        usuarios_dl_1gbps_o_mas   = EXCLUDED.usuarios_dl_1gbps_o_mas,
        usuarios_ul_sin_datos     = EXCLUDED.usuarios_ul_sin_datos,
        usuarios_ul_menos_1mbps   = EXCLUDED.usuarios_ul_menos_1mbps,
        usuarios_ul_1_10mbps      = EXCLUDED.usuarios_ul_1_10mbps,
        usuarios_ul_10_30mbps     = EXCLUDED.usuarios_ul_10_30mbps,
        usuarios_ul_30_100mbps    = EXCLUDED.usuarios_ul_30_100mbps,
        usuarios_ul_100mbps_1gbps = EXCLUDED.usuarios_ul_100mbps_1gbps,
        usuarios_ul_1gbps_o_mas   = EXCLUDED.usuarios_ul_1gbps_o_mas,
        hash_contenido            = EXCLUDED.hash_contenido,
        fecha_carga               = now()
"""


def cargar_hechos_anio(anio: int):
    inicio = datetime.now()
    filas_procesadas = 0
    try:
        with sqlserver_cursor() as ms_cur, postgres_cursor() as pg_cur:
            ms_cur.execute(SQL_EXTRAER_HECHOS_ANIO, (anio,))
            filas = ms_cur.fetchall()

            for fila in filas:
                hash_fila = calcular_hash_fila(fila)
                pg_cur.execute(
                    SQL_UPSERT_HECHOS,
                    (
                        fila["peva_codigo"], fila["par_codigo"],
                        fila["periodoNumero"], fila["periodoNombre"],
                        fila["anio"], fila["tipoEnlace"],
                        fila["tipoCliente"], fila["nivelComparticion"],
                        fila["portador"], fila["regional"],
                        fila["pro_nombre"], fila["ciu_nombre"],
                        fila["par_nombre"],
                        fila["total_lineas"], fila["total_usuarios"],
                        fila["usuarios_dl_sin_datos"],
                        fila["usuarios_dl_menos_1mbps"],
                        fila["usuarios_dl_1_10mbps"],
                        fila["usuarios_dl_10_30mbps"],
                        fila["usuarios_dl_30_100mbps"],
                        fila["usuarios_dl_100mbps_1gbps"],
                        fila["usuarios_dl_1gbps_o_mas"],
                        fila["usuarios_ul_sin_datos"],
                        fila["usuarios_ul_menos_1mbps"],
                        fila["usuarios_ul_1_10mbps"],
                        fila["usuarios_ul_10_30mbps"],
                        fila["usuarios_ul_30_100mbps"],
                        fila["usuarios_ul_100mbps_1gbps"],
                        fila["usuarios_ul_1gbps_o_mas"],
                        hash_fila,
                    ),
                )
                filas_procesadas += 1

        _registrar_carga("hechos_anual", anio, filas_procesadas, 0, "EXITOSO", None, inicio)
        logger.info("Año %s: %s filas agregadas procesadas.", anio, filas_procesadas)

    except Exception as exc:
        _registrar_carga("hechos_anual", anio, filas_procesadas, 0, "FALLIDO", str(exc), inicio)
        logger.exception("Error cargando hechos del año %s", anio)
        raise


def _registrar_carga(tipo_carga, anio, insertadas, actualizadas, estado, mensaje_error, fecha_inicio):
    with postgres_cursor() as cur:
        cur.execute(
            """
            INSERT INTO staging.control_cargas
                (tipo_carga, anio, filas_insertadas, filas_actualizadas,
                 estado, mensaje_error, fecha_inicio)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (tipo_carga, anio, insertadas, actualizadas, estado, mensaje_error, fecha_inicio),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Carga agregado anual de dbo.VALineasDedicadas hacia "
                    "staging.va_lineas_dedicadas_resumen."
    )
    parser.add_argument("--anio", type=int, required=True, help="Año a cargar, ej. 2025")
    args = parser.parse_args()
    cargar_hechos_anio(args.anio)
