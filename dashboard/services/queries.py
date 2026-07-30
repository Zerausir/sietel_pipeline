"""dashboard/services/queries.py — Consultas cacheadas contra mart.*"""
from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy import text

from extensions import cache
from services.database import get_mart_engine


def _read(sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    with get_mart_engine().connect() as conn:
        return pd.read_sql_query(text(sql), conn, params=params or {})


@cache.memoize(timeout=900)
def get_periods() -> pd.DataFrame:
    """Catálogo de períodos (mart.dim_periodo) -- cambia poco, cache de 15 min."""
    return _read(
        """
        SELECT periodo_id, periodo, anio, mes, nombre_mes, anio_mes
        FROM mart.dim_periodo
        ORDER BY periodo_id
        """
    )


def resolve_period_id(date_value: str | None) -> int | None:
    """
    Convierte una fecha elegida en un selector de calendario (dcc.DatePickerSingle)
    al periodo_id mensual correspondiente en mart.dim_periodo. Los datos son
    mensuales -- se usa el año/mes de la fecha elegida, sin importar el día.
    Si la fecha cae fuera del rango disponible, se ajusta al extremo más cercano
    (el propio DatePickerSingle ya restringe min_date_allowed/max_date_allowed,
    esto es una segunda defensa, no la única).
    """
    if not date_value:
        return None
    periods = get_periods()
    if periods.empty:
        return None

    fecha = pd.to_datetime(date_value)
    coincidencia = periods[(periods["anio"] == fecha.year) & (periods["mes"] == fecha.month)]
    if not coincidencia.empty:
        return int(coincidencia.iloc[0]["periodo_id"])

    periods_ordenado = periods.sort_values("periodo_id")
    primero = periods_ordenado.iloc[0]
    ultimo = periods_ordenado.iloc[-1]
    if fecha < pd.to_datetime(primero["periodo"]):
        return int(primero["periodo_id"])
    return int(ultimo["periodo_id"])


@cache.memoize(timeout=900)
def get_territory_options(
        level: str,
        province_code: str | None = None,
        canton_code: str | None = None,
) -> list[dict[str, str]]:
    """
    Opciones para el filtro geográfico en cascada
    (components/territory_filters.py), desde mart.vw_dashboard_filtros_geograficos.
    """
    clauses = ["nivel_geografico = :level"]
    params: dict[str, Any] = {"level": level}

    if province_code:
        clauses.append("codigo_provincia = :province_code")
        params["province_code"] = province_code
    if canton_code:
        clauses.append("codigo_canton = :canton_code")
        params["canton_code"] = canton_code

    df = _read(
        f"""
        SELECT territorio_id,
               codigo_geografico,
               nombre_geografico,
               codigo_provincia,
               codigo_canton,
               codigo_parroquia
        FROM mart.vw_dashboard_filtros_geograficos
        WHERE {' AND '.join(clauses)}
        ORDER BY nombre_geografico
        """,
        params,
    )

    value_column = {
        "PROVINCIA": "codigo_provincia",
        "CANTON": "codigo_canton",
        "PARROQUIA": "codigo_parroquia",
    }.get(level, "territorio_id")

    return [
        {"label": str(row["nombre_geografico"]), "value": str(row[value_column])}
        for _, row in df.iterrows()
        if pd.notna(row[value_column])
    ]


@cache.memoize(timeout=300)
def get_provider_count_in_range(territory_id: str, start_period: int, end_period: int) -> int:
    """
    Cuenta prestadores DISTINTOS con AL MENOS UN REPORTE REAL (no imputado)
    dentro de TODO el rango Desde-Hasta -- a diferencia de "numero_prestadores"
    en vw_dashboard_evolucion, que es una fotografía de un solo mes.

    CORRECCIÓN (30-jul-2026): el filtro anterior era `total_lineas IS NOT
    NULL`, que incluye filas IMPUTADAS (relleno LOCF) -- no es lo mismo que
    "al menos un reporte real", que es lo que el texto del KPI afirma. Ahora
    filtra por tiene_reportado = TRUE explícitamente.

    Esto tampoco equivale a "título habilitante vigente" (un concepto
    administrativo de permisos, ajeno a esta tabla) -- es estrictamente
    "tuvo actividad reportada de verdad en algún mes de este rango".
    """
    df = _read(
        """
        SELECT COUNT(DISTINCT f.prestador_id) AS cantidad
        FROM mart.fact_lineas_geografia_mes f
        JOIN mart.bridge_geografia_territorio b ON b.geografia_id = f.geografia_id
        WHERE b.territorio_id = :territory_id
          AND f.periodo_id BETWEEN :start_period AND :end_period
          AND f.tiene_reportado = TRUE
        """,
        {"territory_id": territory_id, "start_period": start_period, "end_period": end_period},
    )
    if df.empty:
        return 0
    return int(df.iloc[0]["cantidad"])


@cache.memoize(timeout=900)
def get_operation_states() -> list[dict[str, str]]:
    """
    Estados de operación distintos, para el filtro 'Estado de operación'.
    dim_prestador.opera_actual puede traer varios valores separados por
    coma para un mismo prestador (si tiene más de un PEVA con estados
    distintos) -- se separan aquí para ofrecer una lista de opciones
    atómica y limpia en el filtro.
    """
    df = _read(
        """
        SELECT DISTINCT BTRIM(estado) AS estado
        FROM mart.dim_prestador, UNNEST(STRING_TO_ARRAY(opera_actual, ',')) AS estado
        WHERE opera_actual IS NOT NULL AND BTRIM(estado) <> ''
        ORDER BY 1
        """
    )
    return [{"label": row["estado"], "value": row["estado"]} for _, row in df.iterrows()]


@cache.memoize(timeout=900)
def get_provider_options(territory_id: str) -> list[dict[str, str]]:
    """Nombres de prestadores con presencia en el territorio, para el filtro 'Prestador'."""
    df = _read(
        """
        SELECT DISTINCT p.isp_nombre
        FROM mart.fact_lineas_geografia_mes f
        JOIN mart.bridge_geografia_territorio b ON b.geografia_id = f.geografia_id
        JOIN mart.dim_prestador p ON p.prestador_id = f.prestador_id
        WHERE b.territorio_id = :territory_id AND p.isp_nombre IS NOT NULL
        ORDER BY p.isp_nombre
        """,
        {"territory_id": territory_id},
    )
    return [{"label": row["isp_nombre"], "value": row["isp_nombre"]} for _, row in df.iterrows()]


@cache.memoize(timeout=300)
def get_evolution(territory_id: str, start_period: int, end_period: int) -> pd.DataFrame:
    return _read(
        """
        SELECT *
        FROM mart.vw_dashboard_evolucion
        WHERE territorio_id = :territory_id
          AND periodo_id BETWEEN :start_period AND :end_period
        ORDER BY periodo_id
        """,
        {"territory_id": territory_id, "start_period": start_period, "end_period": end_period},
    )


@cache.memoize(timeout=300)
def get_evolution_filtrado(
        territory_id: str,
        start_period: int,
        end_period: int,
        opera_estados: list[str] | None = None,
        isp_nombres: list[str] | None = None,
) -> pd.DataFrame:
    """
    Igual que get_evolution, pero agregando en tiempo de consulta desde
    fact_lineas_geografia_mes + dim_prestador, para poder filtrar por
    estado de operación y/o nombre de prestador ANTES de sumar --
    vw_dashboard_evolucion ya viene pre-agregada a nivel de territorio y
    no permite bajar a este nivel de detalle.

    opera_estados / isp_nombres aceptan LISTAS (selección múltiple) -- si
    se pasa una lista vacía o None, no se filtra por ese criterio.

    CORRECCIÓN (30-jul-2026, tras discusión con el usuario): se eliminó
    por completo el desglose "con líneas / sin dato" -- dependía de forma
    indirecta de la distinción reportado/imputado (un prestador con líneas
    > 0 podía ser 100% imputado), lo cual generaba una aparente
    contradicción frente al conteo de "reportaron". Ahora solo existe UN
    conteo de prestadores: los que tuvieron un reporte REAL ese mes
    (tiene_reportado = TRUE) -- nada de imputados, ni como categoría de
    desglose.

    Las columnas de comparación mes a mes (diferencia_mensual_lineas,
    variacion_mensual_porcentaje) se calculan en pandas (.diff()), no en
    SQL -- más simple que replicar el JOIN por fecha de fact_resumen_mercado_mes.
    """
    clauses = [
        "b.territorio_id = :territory_id",
        "f.periodo_id BETWEEN :start_period AND :end_period",
    ]
    params: dict[str, Any] = {
        "territory_id": territory_id,
        "start_period": start_period,
        "end_period": end_period,
    }
    if opera_estados:
        clauses.append(
            "EXISTS (SELECT 1 FROM unnest(:opera_estados::text[]) AS estado "
            "WHERE p.opera_actual ILIKE '%' || estado || '%')"
        )
        params["opera_estados"] = list(opera_estados)
    if isp_nombres:
        clauses.append("p.isp_nombre = ANY(:isp_nombres)")
        params["isp_nombres"] = list(isp_nombres)

    df = _read(
        f"""
        SELECT
            f.periodo_id,
            f.periodo,
            SUM(f.total_lineas) AS total_lineas,
            SUM(COALESCE(f.lineas_reportadas, 0)) AS lineas_reportadas,
            COUNT(DISTINCT f.prestador_id) FILTER (WHERE f.tiene_reportado) AS numero_prestadores
        FROM mart.fact_lineas_geografia_mes f
        JOIN mart.bridge_geografia_territorio b ON b.geografia_id = f.geografia_id
        JOIN mart.dim_prestador p ON p.prestador_id = f.prestador_id
        WHERE {' AND '.join(clauses)}
        GROUP BY f.periodo_id, f.periodo
        ORDER BY f.periodo_id
        """,
        params,
    )

    if df.empty:
        return df

    periods = get_periods()[["periodo_id", "anio_mes"]]
    df = df.merge(periods, on="periodo_id", how="left")

    df = df.sort_values("periodo_id").reset_index(drop=True)
    df["diferencia_mensual_lineas"] = df["lineas_reportadas"].diff()
    df["variacion_mensual_porcentaje"] = df["lineas_reportadas"].pct_change() * 100
    return df


@cache.memoize(timeout=300)
def get_velocities(
        territory_id: str,
        start_period: int,
        end_period: int,
        speed_type: str,
        opera_estados: list[str] | None = None,
        isp_nombres: list[str] | None = None,
) -> pd.DataFrame:
    """
    Igual que get_evolution_filtrado, pero para la composición por
    velocidad -- agrega en tiempo de consulta desde fact_lineas_velocidad_mes
    + dim_prestador para poder respetar los mismos filtros de Estado de
    operación / Prestador (antes solo usaba vw_dashboard_velocidades,
    pre-agregada, sin posibilidad de filtrar por prestador).
    """
    clauses = [
        "b.territorio_id = :territory_id",
        "v.periodo_id BETWEEN :start_period AND :end_period",
        "v.tipo_velocidad = :speed_type",
    ]
    params: dict[str, Any] = {
        "territory_id": territory_id,
        "start_period": start_period,
        "end_period": end_period,
        "speed_type": speed_type,
    }
    if opera_estados:
        clauses.append(
            "EXISTS (SELECT 1 FROM unnest(:opera_estados::text[]) AS estado "
            "WHERE p.opera_actual ILIKE '%' || estado || '%')"
        )
        params["opera_estados"] = list(opera_estados)
    if isp_nombres:
        clauses.append("p.isp_nombre = ANY(:isp_nombres)")
        params["isp_nombres"] = list(isp_nombres)

    df = _read(
        f"""
        SELECT
            v.periodo_id,
            v.periodo,
            v.tipo_velocidad,
            v.orden_rango,
            v.rango_velocidad,
            SUM(v.total_lineas_velocidad) AS total_lineas
        FROM mart.fact_lineas_velocidad_mes v
        JOIN mart.bridge_geografia_territorio b ON b.geografia_id = v.geografia_id
        JOIN mart.dim_prestador p ON p.prestador_id = v.prestador_id
        WHERE {' AND '.join(clauses)}
        GROUP BY v.periodo_id, v.periodo, v.tipo_velocidad, v.orden_rango, v.rango_velocidad
        ORDER BY v.periodo_id, v.orden_rango
        """,
        params,
    )

    if df.empty:
        return df

    df = df.sort_values(["rango_velocidad", "periodo_id"])
    df["diferencia_mensual"] = df.groupby("rango_velocidad")["total_lineas"].diff()
    return df.sort_values(["periodo_id", "orden_rango"]).reset_index(drop=True)


@cache.memoize(timeout=300)
def get_ihh(territory_id: str, start_period: int, end_period: int) -> pd.DataFrame:
    return _read(
        """
        SELECT *
        FROM mart.vw_dashboard_ihh
        WHERE territorio_id = :territory_id
          AND periodo_id BETWEEN :start_period AND :end_period
        ORDER BY periodo_id
        """,
        {"territory_id": territory_id, "start_period": start_period, "end_period": end_period},
    )


@cache.memoize(timeout=300)
def get_participation(territory_id: str, period_id: int) -> pd.DataFrame:
    return _read(
        """
        SELECT *
        FROM mart.vw_dashboard_participacion
        WHERE territorio_id = :territory_id
          AND periodo_id = :period_id
        ORDER BY ranking_prestador NULLS LAST, isp_nombre NULLS LAST
        """,
        {"territory_id": territory_id, "period_id": period_id},
    )


@cache.memoize(timeout=300)
def get_provider_history(
        territory_id: str,
        provider_id: str,
        start_period: int,
        end_period: int,
) -> pd.DataFrame:
    return _read(
        """
        SELECT periodo_id,
               periodo,
               anio_mes,
               prestador_id,
               isp_nombre,
               nombrecomercial,
               total_lineas_prestador,
               participacion_porcentaje,
               ranking_prestador,
               estado_lineas,
               porcentaje_imputado_prestador
        FROM mart.vw_dashboard_participacion
        WHERE territorio_id = :territory_id
          AND prestador_id = :provider_id
          AND periodo_id BETWEEN :start_period AND :end_period
        ORDER BY periodo_id
        """,
        {
            "territory_id": territory_id,
            "provider_id": provider_id,
            "start_period": start_period,
            "end_period": end_period,
        },
    )
