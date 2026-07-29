from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from extensions import cache
from services.database import get_mart_engine


@cache.memoize()
def obtener_territorios(nivel_geografico: str | None = None) -> pd.DataFrame:
    """
    Opciones para los selectores de geografía, desde
    mart.vw_dashboard_filtros_geograficos. Cacheado -- la lista de
    territorios solo cambia cuando corre sietel_mart_pipeline, no en cada
    click del usuario.
    """
    sql = "SELECT * FROM mart.vw_dashboard_filtros_geograficos"
    params = {}
    if nivel_geografico:
        sql += " WHERE nivel_geografico = :nivel"
        params["nivel"] = nivel_geografico
    sql += " ORDER BY orden_nivel, nombre_geografico"

    with get_mart_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


@cache.memoize()
def obtener_evolucion(territorio_id: str) -> pd.DataFrame:
    """Serie histórica mensual para un territorio, desde mart.vw_dashboard_evolucion."""
    sql = text(
        """
        SELECT
            periodo, anio, mes, nombre_mes, anio_mes,
            total_lineas, total_usuarios,
            numero_prestadores, numero_prestadores_con_lineas,
            numero_prestadores_cero, numero_prestadores_sin_dato,
            numero_prestadores_imputados,
            lineas_reportadas, lineas_imputadas, porcentaje_imputado,
            diferencia_mensual_lineas, variacion_mensual_porcentaje,
            diferencia_anual_lineas, variacion_anual_porcentaje
        FROM mart.vw_dashboard_evolucion
        WHERE territorio_id = :territorio_id
        ORDER BY periodo
        """
    )
    with get_mart_engine().connect() as conn:
        return pd.read_sql(sql, conn, params={"territorio_id": territorio_id})
