r"""dashboard/services/queries_sma.py — Consultas del módulo SMA (samm_pipeline).

REESCRITURA (26-ago-2026): la primera versión de este archivo asumía
nombres de columna leídos únicamente del panel de campos de Power BI
(sin distinguir columna real de medida DAX) -- Iván señaló correctamente
que eso no iba a funcionar. Esta versión usa las medidas DAX REALES que
compartió (capturas de "Herramientas de medición" de "% Cumplimiento DL",
"% Sesiones HTTP Fallidas", "DL/UL Fallidas", "Total DL/UL", "Promedio
DL/UL (Mbps)"), que exponen los nombres de columna verdaderos de
public.grafana_mobile_geo_view:

    DatasourceId, SessionId, SessionType, EndServiceStatus, ThroughputMbps,
    SimOperator (además de Operator, EndLatitude/EndLongitude,
    StartRadioTechnology/EndRadioTechnology, Provincia/Cantón/Parroquia,
    CZO, StartTime/EndTime, PhoneNumber/IMEI/IMSI -- del panel de campos,
    no usados en ninguna medida DAX vista hasta ahora).

GRANO REAL DE LA VISTA (deducido de las propias medidas, no supuesto):
public.grafana_mobile_geo_view NO tiene una fila por sesión -- puede
tener VARIAS filas por (DatasourceId, SessionId) (de ahí que cada medida
de conteo envuelva su FILTER en SUMMARIZE(..., DatasourceId, SessionId)
para no contar la misma sesión más de una vez). Las medidas de PROMEDIO
("Promedio DL/UL (Mbps)"), en cambio, NO hacen ese SUMMARIZE -- agregan
CALCULATE(AVERAGE(ThroughputMbps), ...) directo sobre las filas
filtradas. Esta réplica en SQL mantiene esa misma asimetría
deliberadamente (fidelidad a la definición original de Iván en Power BI),
aunque signifique que "Promedio DL/UL" SÍ puede estar sesgado por
sesiones con más muestras/filas que otras -- si eso no es lo que se
quiere, es una decisión de Iván sobre la métrica, no un bug de esta
consulta.

SessionType observado: "HTTP Download" / "HTTP Post" (no "HTTP Upload").
EndServiceStatus observado: "Succeeded" / "Failed" (el %-fallidas de las
medidas DAX solo suma estos dos estados -- si existe un tercer estado,
esas sesiones quedan fuera del denominador, igual que en el DAX
original).

CAMPO DE AGRUPACIÓN POR "OPERADORA" -- CONFIRMADO por Iván (26-ago-2026):
es "SimOperator", no "Operator". Coincide con lo que ya delataban las
medidas "Promedio Máximos/Mínimos DL" (AVERAGEX(VALUES(SimOperator),
...)) -- el resto de medidas simplemente no lo hacían explícito porque
son escalares sin agrupación propia, la agrupación la ponía el visual de
Power BI. Todo este archivo agrupa por SimOperator; "Operator" no se usa
en ninguna consulta.

MÓDULO VOZ (grafana_voice_geo_view): PAUSADO. No se reescribe en esta
pasada porque no tengo el DAX real de sus medidas (Total Llamadas,
Llamadas Caídas/Bloqueadas/Establecidas/Fallidas, % No establecidas, %
Caídas, AqmSessionEndAqmCallQuality) -- las funciones anteriores para
Voz se retiran de este archivo para no exponer números fabricados en el
dashboard. dashboard/pages/sma_voz.py queda como aviso, sin consultar la
base, hasta que compartas las medidas DAX de Calidad Voz igual que
hiciste para Datos.

DECISIÓN DE PRIVACIDAD (se mantiene): PhoneNumber, IMEI e IMSI no se
exponen en agregados ni en detalle -- "Número" es búsqueda exacta, nunca
listado completo.

LÍMITE DE FILAS: el mapa trae como máximo SMA_ROW_LIMIT filas, muestreadas
aleatoriamente sobre TODO el rango filtrado (no las más recientes -- ver
get_sma_mobile_map() para el detalle) -- sin visibilidad de índices reales
de samm_db,
acotar por fecha/territorio si aparece el mensaje de truncado.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy import text

from extensions import cache
from services.database import get_sma_engine

SMA_ROW_LIMIT = 20_000
VW_MOBILE = "public.grafana_mobile_geo_view"


def _read(sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    with get_sma_engine().connect() as conn:
        return pd.read_sql_query(text(sql), conn, params=params or {})


def _mobile_filters_sql(
        operadoras: tuple[str, ...],
        czos: tuple[str, ...],
        provincias: tuple[str, ...],
        cantones: tuple[str, ...],
        parroquias: tuple[str, ...],
        tecnologias: tuple[str, ...],
        numero: str | None,
        fecha_inicio: str | None,
        fecha_fin: str | None,
) -> tuple[str, dict[str, Any]]:
    """
    WHERE compartido por las consultas de Datos móviles. Tecnología filtra
    por EndRadioTechnology (tecnología AL FINAL de la sesión) -- ver
    get_sma_technology_options() para la misma decisión documentada.
    Rango de fecha sobre EndTime, no StartTime -- mismo criterio.
    """
    clauses: list[str] = []
    params: dict[str, Any] = {}

    if operadoras:
        clauses.append('"SimOperator" = ANY(:operadoras)')
        params["operadoras"] = list(operadoras)
    if czos:
        clauses.append('"CZO" = ANY(:czos)')
        params["czos"] = list(czos)
    if provincias:
        clauses.append('"Provincia" = ANY(:provincias)')
        params["provincias"] = list(provincias)
    if cantones:
        clauses.append('"Cantón" = ANY(:cantones)')
        params["cantones"] = list(cantones)
    if parroquias:
        clauses.append('"Parroquia" = ANY(:parroquias)')
        params["parroquias"] = list(parroquias)
    if tecnologias:
        clauses.append('"EndRadioTechnology" = ANY(:tecnologias)')
        params["tecnologias"] = list(tecnologias)
    if numero:
        clauses.append('"PhoneNumber" = :numero')
        params["numero"] = numero
    if fecha_inicio:
        clauses.append('"EndTime" >= :fecha_inicio')
        params["fecha_inicio"] = fecha_inicio
    if fecha_fin:
        clauses.append('"EndTime" <= :fecha_fin')
        params["fecha_fin"] = fecha_fin

    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(clauses), params


# ============================================================
# Opciones de filtro
# ============================================================

@cache.memoize(timeout=900)
def get_sma_operator_options() -> list[dict[str, str]]:
    df = _read(f'SELECT DISTINCT "SimOperator" FROM {VW_MOBILE} WHERE "SimOperator" IS NOT NULL ORDER BY 1')
    return [{"label": v, "value": v} for v in df["SimOperator"]]


@cache.memoize(timeout=900)
def get_sma_czo_options() -> list[dict[str, str]]:
    df = _read(f'SELECT DISTINCT "CZO" FROM {VW_MOBILE} WHERE "CZO" IS NOT NULL ORDER BY 1')
    return [{"label": v, "value": v} for v in df["CZO"]]


@cache.memoize(timeout=900)
def get_sma_technology_options() -> list[dict[str, str]]:
    """EndRadioTechnology -- ver advertencia del módulo sobre esta decisión."""
    df = _read(
        f'SELECT DISTINCT "EndRadioTechnology" FROM {VW_MOBILE} '
        f'WHERE "EndRadioTechnology" IS NOT NULL ORDER BY 1'
    )
    return [{"label": v, "value": v} for v in df["EndRadioTechnology"]]


@cache.memoize(timeout=900)
def opciones_geograficas_sma(
        nivel: str,
        provincias: tuple[str, ...] = (),
        cantones: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    """Filtro cruzado por TEXTO (Provincia/Cantón/Parroquia) -- sin código INEC visible en esta vista."""
    columna = {"PROVINCIA": "Provincia", "CANTON": "Cantón", "PARROQUIA": "Parroquia"}[nivel]
    clauses = [f'"{columna}" IS NOT NULL']
    params: dict[str, Any] = {}
    if provincias:
        clauses.append('"Provincia" = ANY(:provincias)')
        params["provincias"] = list(provincias)
    if cantones:
        clauses.append('"Cantón" = ANY(:cantones)')
        params["cantones"] = list(cantones)
    df = _read(
        f'SELECT DISTINCT "{columna}" FROM {VW_MOBILE} WHERE {" AND ".join(clauses)} ORDER BY 1',
        params,
    )
    return [{"label": v, "value": v} for v in df[columna]]


# ============================================================
# Calidad de Datos móviles -- lógica EXACTA de las medidas DAX
# compartidas el 26-ago-2026 (ver advertencia del módulo)
# ============================================================

@cache.memoize(timeout=300)
def get_sma_mobile_summary(
        operadoras: tuple[str, ...] = (), czos: tuple[str, ...] = (),
        provincias: tuple[str, ...] = (), cantones: tuple[str, ...] = (),
        parroquias: tuple[str, ...] = (), tecnologias: tuple[str, ...] = (),
        numero: str | None = None, fecha_inicio: str | None = None, fecha_fin: str | None = None,
) -> pd.DataFrame:
    """
    Una fila por Operador, replicando exactamente:
      - "Total DL"/"Total UL": sesiones DISTINTAS (DatasourceId, SessionId)
        con SessionType = 'HTTP Download'/'HTTP Post'.
      - "DL Fallidas"/"UL Fallidas": igual, + EndServiceStatus = 'Failed'.
      - "Promedio DL/UL (Mbps)": AVERAGE(ThroughputMbps) SIN deduplicar
        por sesión, filtrado a EndServiceStatus = 'Succeeded' (misma
        asimetría que el DAX original -- ver advertencia del módulo).
      - "% Sesiones HTTP Fallidas": 100 * (dl_failed+ul_failed) /
        (dl_failed+ul_failed+dl_success+ul_success), sobre sesiones
        DISTINTAS.
      - "% Cumplimiento DL (>=3.8 Mbps)": sesiones DISTINTAS de descarga
        EXITOSA con throughput no nulo y >= 3.8, sobre sesiones DISTINTAS
        de descarga con throughput no nulo (SIN filtrar por estado en el
        denominador -- así está el DAX original).
    """
    where_sql, params = _mobile_filters_sql(
        operadoras, czos, provincias, cantones, parroquias, tecnologias, numero, fecha_inicio, fecha_fin,
    )
    return _read(
        f"""
        WITH sesiones AS (
            SELECT DISTINCT
                "SimOperator" AS operador,
                "DatasourceId" AS datasource_id,
                "SessionId" AS session_id,
                "SessionType" AS session_type,
                "EndServiceStatus" AS end_service_status,
                "ThroughputMbps" AS throughput_mbps
            FROM {VW_MOBILE}
            {where_sql}
        ),
        resumen_sesiones AS (
            SELECT
                operador,
                COUNT(*) FILTER (WHERE session_type = 'HTTP Download') AS total_descargas,
                COUNT(*) FILTER (WHERE session_type = 'HTTP Post') AS total_cargas,
                COUNT(*) FILTER (WHERE session_type = 'HTTP Download'
                                        AND end_service_status = 'Failed') AS descargas_fallidas,
                COUNT(*) FILTER (WHERE session_type = 'HTTP Post'
                                        AND end_service_status = 'Failed') AS cargas_fallidas,
                COUNT(*) FILTER (WHERE session_type = 'HTTP Download'
                                        AND end_service_status = 'Succeeded') AS descargas_exitosas,
                COUNT(*) FILTER (WHERE session_type = 'HTTP Post'
                                        AND end_service_status = 'Succeeded') AS cargas_exitosas,
                COUNT(*) FILTER (WHERE session_type = 'HTTP Download'
                                        AND throughput_mbps IS NOT NULL) AS descargas_con_throughput,
                COUNT(*) FILTER (
                    WHERE session_type = 'HTTP Download' AND end_service_status = 'Succeeded'
                      AND throughput_mbps IS NOT NULL AND throughput_mbps >= 3.8
                ) AS descargas_cumplen_3_8
            FROM sesiones
            GROUP BY operador
        ),
        promedios AS (
            SELECT
                "SimOperator" AS operador,
                AVG("ThroughputMbps") FILTER (
                    WHERE "SessionType" = 'HTTP Download' AND "EndServiceStatus" = 'Succeeded'
                ) AS promedio_descarga_mbps,
                AVG("ThroughputMbps") FILTER (
                    WHERE "SessionType" = 'HTTP Post' AND "EndServiceStatus" = 'Succeeded'
                ) AS promedio_carga_mbps
            FROM {VW_MOBILE}
            {where_sql}
            GROUP BY "SimOperator"
        )
        SELECT
            r.operador,
            r.total_descargas, r.total_cargas, r.descargas_fallidas, r.cargas_fallidas,
            p.promedio_descarga_mbps, p.promedio_carga_mbps,
            CASE WHEN (r.descargas_fallidas + r.cargas_fallidas + r.descargas_exitosas + r.cargas_exitosas) > 0
                 THEN ROUND(
                     100.0 * (r.descargas_fallidas + r.cargas_fallidas)
                     / (r.descargas_fallidas + r.cargas_fallidas + r.descargas_exitosas + r.cargas_exitosas), 2
                 )
            END AS pct_sesiones_http_fallidas,
            CASE WHEN r.descargas_con_throughput > 0
                 THEN ROUND(100.0 * r.descargas_cumplen_3_8 / r.descargas_con_throughput, 2)
            END AS pct_cumplimiento_dl
        FROM resumen_sesiones r
        LEFT JOIN promedios p ON p.operador = r.operador
        ORDER BY r.operador
        """,
        params,
    )


@cache.memoize(timeout=300)
def get_sma_mobile_map(
        operadoras: tuple[str, ...] = (), czos: tuple[str, ...] = (),
        provincias: tuple[str, ...] = (), cantones: tuple[str, ...] = (),
        parroquias: tuple[str, ...] = (), tecnologias: tuple[str, ...] = (),
        numero: str | None = None, fecha_inicio: str | None = None, fecha_fin: str | None = None,
) -> pd.DataFrame:
    """
    Un punto por FILA (no por sesión -- el mapa necesita cada posición
    geolocalizada, a diferencia de los conteos de sesión de arriba).

    MUESTREO (31-ago-2026): antes traía los SMA_ROW_LIMIT registros más
    RECIENTES (ORDER BY "EndTime" DESC) -- sesgaba el mapa hacia el final
    del rango de fechas filtrado. Un primer intento de corregirlo con una
    CTE (calcular la proporción SMA_ROW_LIMIT/total y aplicar
    random() < proporción) resultó innecesariamente compleja -- en la
    prueba de Iván contra samm_db real devolvió 0 filas, sin poder
    reproducir la falla con datos sintéticos, así que se descarta esa
    versión en vez de seguir depurándola. Esta es la forma simple y
    estándar de Postgres para una muestra aleatoria: ORDER BY random()
    LIMIT -- una sola pasada, sin CTE, sin CROSS JOIN, sin parámetro
    repetido tres veces. Verificado contra Postgres real (no simulado)
    antes de entregarla.
    """
    where_sql, params = _mobile_filters_sql(
        operadoras, czos, provincias, cantones, parroquias, tecnologias, numero, fecha_inicio, fecha_fin,
    )
    condicion_geo = '"EndLatitude" IS NOT NULL AND "EndLongitude" IS NOT NULL AND "ThroughputMbps" IS NOT NULL'
    where_sql = f"{where_sql} AND {condicion_geo}" if where_sql else f"WHERE {condicion_geo}"
    params["row_limit"] = SMA_ROW_LIMIT
    return _read(
        f"""
        SELECT
            "SimOperator" AS operador,
            "EndLatitude" AS latitud,
            "EndLongitude" AS longitud,
            "ThroughputMbps" AS throughput_mbps,
            "StartRadioTechnology" AS tecnologia_inicial,
            "EndRadioTechnology" AS tecnologia_final,
            "Provincia" AS provincia,
            "Cantón" AS canton,
            "Parroquia" AS parroquia,
            "StartTime" AS fecha_inicial,
            "EndTime" AS fecha_final
        FROM {VW_MOBILE}
        {where_sql}
        ORDER BY random()
        LIMIT :row_limit
        """,
        params,
    )
