"""dashboard/services/queries.py — Consultas cacheadas contra mart.*"""
from __future__ import annotations

import json
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


def _lines_territory_clauses(
        geografia_column: str,
        provincias: tuple[str, ...],
        cantones: tuple[str, ...],
        parroquias: tuple[str, ...],
) -> tuple[str, dict[str, Any]]:
    """
    Fragmento EXISTS para filtrar mart.fact_lineas_geografia_mes (u otra
    tabla con columna geografia_id) por Provincia/Cantón/Parroquia,
    selección múltiple e independiente (AND entre dimensiones, OR dentro
    de cada lista) -- mismo principio que _node_territory_clauses(), pero
    correlacionado vía bridge_geografia_territorio + dim_territorio en vez
    de columnas planas (fact_lineas_geografia_mes no las tiene).

    UN SOLO EXISTS combinando las tres condiciones activas, no tres EXISTS
    separados -- mart.dim_territorio denormaliza codigo_provincia/canton
    hacia abajo (una fila de nivel PARROQUIA también trae su
    codigo_provincia y codigo_canton), así que un EXISTS combinado
    encuentra correctamente la fila más específica que satisface todos los
    filtros activos a la vez, sin multiplicar geografia_column (que sí
    ocurriría con un JOIN plano, porque bridge_geografia_territorio tiene
    una fila por NIVEL para el mismo geografia_id).

    Devuelve ("", {}) si no hay ningún filtro activo -- el llamador debe
    omitir la cláusula en ese caso (no agregar "AND EXISTS(...)" vacío).
    """
    condiciones = []
    params: dict[str, Any] = {}
    if provincias:
        condiciones.append("dt.codigo_provincia = ANY(:territorio_provincias)")
        params["territorio_provincias"] = list(provincias)
    if cantones:
        condiciones.append("dt.codigo_canton = ANY(:territorio_cantones)")
        params["territorio_cantones"] = list(cantones)
    if parroquias:
        condiciones.append("dt.codigo_parroquia = ANY(:territorio_parroquias)")
        params["territorio_parroquias"] = list(parroquias)

    if not condiciones:
        return "", {}

    fragmento = (
        f"EXISTS (SELECT 1 FROM mart.bridge_geografia_territorio b "
        f"JOIN mart.dim_territorio dt ON dt.territorio_id = b.territorio_id "
        f"WHERE b.geografia_id = {geografia_column} AND {' AND '.join(condiciones)})"
    )
    return fragmento, params


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


@cache.memoize(timeout=300)
def get_reporting_summary(
        territory_id: str,
        start_period: int,
        end_period: int,
        opera_estados: list[str] | None = None,
        isp_nombres: list[str] | None = None,
        incluir_nunca_reportaron: bool = False,
) -> dict[str, float]:
    """
    Resumen de cumplimiento de entrega de reportes:
      - total_prestadores: TODOS los prestadores con presencia HASTA la
        fecha 'Hasta' (con o sin reporte real). Usa SOLO el límite
        superior del rango, NO el límite inferior.
      - celdas_esperadas / celdas_reportadas: para CADA prestador, para
        CADA mes del rango Desde-Hasta en el que ya tenía obligación de
        reportar (ver regla del año de gracia), se cuenta como "celda
        esperada" -- SIN IMPORTAR si ese prestador tiene o no una fila en
        fact_lineas_geografia_mes ese mes.
      - tasa_entrega_porcentaje: celdas_reportadas / celdas_esperadas * 100.

    CORRECCIÓN (30-jul-2026, tercera revisión del usuario): la versión
    anterior de esta función excluía por completo a los prestadores que
    JAMÁS han entregado ni un solo reporte real -- ni del total, ni de la
    tasa. Eso contradecía el propio nombre del KPI "Total de prestadores
    (con o sin reportes)" (que promete incluir a quien no tiene reportes,
    pero no lo hacía), y dejaba la tasa de entrega artificialmente alta al
    ignorar el caso de incumplimiento más grave.

    Con incluir_nunca_reportaron=True, se fusiona la población de
    mart.vw_prestadores_sin_reportar (prestadores con título habilitante
    pero cero reportes en toda su historia) directamente en el cálculo:
      - Se suman a total_prestadores.
      - Aportan celdas_esperadas por cada mes del rango en el que ya
        tenían obligación (misma regla del año de gracia, usando su
        propio fechapermiso).
      - Aportan CERO a celdas_reportadas -- por definición, nunca han
        reportado, así que ningún mes suyo puede contar como entregado.

    SOLO A NIVEL NACIONAL: mart.vw_prestadores_sin_reportar no tiene
    columna de geografía (SIETEL no conoce la ubicación de un prestador
    que nunca reportó). El llamador (evolucion.py) debe pasar
    incluir_nunca_reportaron=True únicamente cuando territory_id sea
    'NACIONAL|ECUADOR' -- para cualquier otro nivel, esta población es
    estructuralmente invisible por falta de geografía, no por un límite
    de esta función.

    REGLA DEL AÑO DE GRACIA: la obligación de reportar de un prestador NO
    empieza el día del título habilitante, sino un año calendario después
    -- ej. título otorgado el 15/08/2021 => el primer reporte OBLIGATORIO
    es el de agosto de 2022. Si fechapermiso es NULL, se asume sin
    obligación conocida y se cuentan todos los meses del rango para ese
    prestador (no se penaliza por falta de este dato, tampoco se inventa).
    """
    clauses_registro = [
        "b.territorio_id = :territory_id",
        "f.periodo_id <= :end_period",
    ]
    clauses_nunca = ["1 = 1"]
    params: dict[str, Any] = {
        "territory_id": territory_id,
        "start_period": start_period,
        "end_period": end_period,
    }
    if opera_estados:
        clauses_registro.append(
            "EXISTS (SELECT 1 FROM unnest(:opera_estados ::text[]) AS estado "
            "WHERE p.opera_actual ILIKE '%' || estado || '%')"
        )
        clauses_nunca.append(
            "EXISTS (SELECT 1 FROM unnest(:opera_estados ::text[]) AS estado "
            "WHERE v.opera ILIKE '%' || estado || '%')"
        )
        params["opera_estados"] = list(opera_estados)
    if isp_nombres:
        clauses_registro.append("p.isp_nombre = ANY(:isp_nombres)")
        clauses_nunca.append("v.isp_nombre = ANY(:isp_nombres)")
        params["isp_nombres"] = list(isp_nombres)

    sql_nunca_reportaron = "SELECT peva_codigo AS prestador_id, fechapermiso FROM mart.vw_prestadores_sin_reportar v WHERE 1 = 0"
    if incluir_nunca_reportaron:
        sql_nunca_reportaron = (
            f"SELECT v.peva_codigo AS prestador_id, v.fechapermiso "
            f"FROM mart.vw_prestadores_sin_reportar v WHERE {' AND '.join(clauses_nunca)}"
        )

    df = _read(
        f"""
        WITH registro_total AS (
            SELECT DISTINCT f.prestador_id
            FROM mart.fact_lineas_geografia_mes f
            JOIN mart.bridge_geografia_territorio b ON b.geografia_id = f.geografia_id
            JOIN mart.dim_prestador p ON p.prestador_id = f.prestador_id
            WHERE {' AND '.join(clauses_registro)}
              AND f.tiene_reportado = TRUE
        ),
        nunca_reportaron AS (
            {sql_nunca_reportaron}
        ),
        periodos_rango AS (
            SELECT periodo_id
            FROM mart.dim_periodo
            WHERE periodo_id BETWEEN :start_period AND :end_period
        ),
        prestador_con_obligacion AS (
            SELECT
                r.prestador_id,
                CASE
                    WHEN p.fechapermiso IS NULL THEN NULL
                    ELSE (
                        EXTRACT(YEAR FROM (p.fechapermiso + INTERVAL '1 year'))::int * 100
                        + EXTRACT(MONTH FROM (p.fechapermiso + INTERVAL '1 year'))::int
                    )
                END AS periodo_inicio_obligacion
            FROM registro_total r
            JOIN mart.dim_prestador p ON p.prestador_id = r.prestador_id
        ),
        nunca_con_obligacion AS (
            SELECT
                n.prestador_id,
                CASE
                    WHEN n.fechapermiso IS NULL THEN NULL
                    ELSE (
                        EXTRACT(YEAR FROM (n.fechapermiso + INTERVAL '1 year'))::int * 100
                        + EXTRACT(MONTH FROM (n.fechapermiso + INTERVAL '1 year'))::int
                    )
                END AS periodo_inicio_obligacion
            FROM nunca_reportaron n
        ),
        -- El cruce completo: TODO prestador (con o sin reportes previos)
        -- x TODO mes del rango en el que ya tenía obligación -- sin
        -- importar si tiene o no una fila real en fact_lineas_geografia_mes.
        celdas_esperadas_calc AS (
            SELECT pco.prestador_id, pr.periodo_id
            FROM prestador_con_obligacion pco
            CROSS JOIN periodos_rango pr
            WHERE pco.periodo_inicio_obligacion IS NULL
               OR pr.periodo_id >= pco.periodo_inicio_obligacion
        ),
        celdas_esperadas_nunca AS (
            SELECT nco.prestador_id, pr.periodo_id
            FROM nunca_con_obligacion nco
            CROSS JOIN periodos_rango pr
            WHERE nco.periodo_inicio_obligacion IS NULL
               OR pr.periodo_id >= nco.periodo_inicio_obligacion
        ),
        reportes_reales AS (
            SELECT DISTINCT f.prestador_id, f.periodo_id
            FROM mart.fact_lineas_geografia_mes f
            JOIN mart.bridge_geografia_territorio b ON b.geografia_id = f.geografia_id
            WHERE b.territorio_id = :territory_id
              AND f.periodo_id BETWEEN :start_period AND :end_period
              AND f.tiene_reportado = TRUE
        )
        SELECT
            (SELECT COUNT(*) FROM registro_total) + (SELECT COUNT(*) FROM nunca_reportaron)
                AS total_prestadores,
            (SELECT COUNT(*) FROM celdas_esperadas_calc) + (SELECT COUNT(*) FROM celdas_esperadas_nunca)
                AS celdas_esperadas,
            (
                -- Los prestadores de "nunca_reportaron" NUNCA aparecen aquí
                -- por definición -- aportan cero celdas reportadas, tal
                -- como deben.
                SELECT COUNT(*)
                FROM celdas_esperadas_calc cec
                JOIN reportes_reales rr
                  ON rr.prestador_id = cec.prestador_id AND rr.periodo_id = cec.periodo_id
            ) AS celdas_reportadas
        """,
        params,
    )

    if df.empty or df.iloc[0]["celdas_esperadas"] in (0, None):
        return {"total_prestadores": 0, "celdas_esperadas": 0, "celdas_reportadas": 0, "tasa_entrega_porcentaje": None}

    fila = df.iloc[0]
    tasa = (fila["celdas_reportadas"] / fila["celdas_esperadas"] * 100) if fila["celdas_esperadas"] else None
    return {
        "total_prestadores": int(fila["total_prestadores"]),
        "celdas_esperadas": int(fila["celdas_esperadas"]),
        "celdas_reportadas": int(fila["celdas_reportadas"]),
        "tasa_entrega_porcentaje": float(tasa) if tasa is not None else None,
    }


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
            "EXISTS (SELECT 1 FROM unnest(:opera_estados ::text[]) AS estado "
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
    # DIAGNÓSTICO TEMPORAL (15-ago-2026) -- Iván reporta que filtrar por
    # "1000TEL CIA. LTDA." en Evolución no cambia los datos (sigue
    # mostrando el total sin filtrar), pero SÍ funciona con "MEGADATOS
    # S.A." y con la misma consulta corrida a mano contra la base. Esto
    # imprime a stdout (visible en `docker logs`) si la función REALMENTE
    # se ejecuta y qué devuelve -- si este print nunca aparece al elegir
    # "1000TEL CIA. LTDA.", es un cache hit de Flask-Caching (SimpleCache,
    # por proceso -- 2 workers de gunicorn) devolviendo un resultado
    # viejo sin volver a correr la consulta. Si SÍ aparece con los datos
    # correctos, el problema está más adelante (en cómo evolucion.py usa
    # el resultado), no aquí. QUITAR una vez diagnosticado.
    print(
        f"[DEBUG get_evolution_filtrado] territory_id={territory_id!r} isp_nombres={isp_nombres!r} "
        f"filas_resultado={len(df)} suma_lineas_reportadas={df['lineas_reportadas'].sum() if not df.empty else 0}",
        flush=True,
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
            "EXISTS (SELECT 1 FROM unnest(:opera_estados ::text[]) AS estado "
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
               tiene_reportado
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


@cache.memoize(timeout=300)
def get_prestadores_sin_reportar(
        opera_estados: list[str] | None = None,
        isp_nombres: list[str] | None = None,
) -> int:
    """
    Cuenta prestadores con título habilitante otorgado que JAMÁS han
    entregado ni un solo reporte real -- el caso de incumplimiento más
    grave, y el único que get_reporting_summary no puede ver (esa consulta
    solo conoce prestadores que ya aparecen en capa2/fact_lineas_geografia_mes,
    lo que por construcción exige al menos un reporte real).

    SIN GEOGRAFÍA A PROPÓSITO: mart.vw_prestadores_sin_reportar no tiene
    columna de territorio -- confirmado con datos reales (29-jul-2026) que
    SIETEL no conoce la ubicación de un prestador que nunca reportó (la
    geografía solo se registra en el reporte real mismo). Por eso esta
    función NO acepta territory_id -- el consumidor (evolucion.py) debe
    mostrar "sin datos disponibles" para cualquier nivel distinto de
    Nacional, no filtrar por geografía aquí (sería inventar un filtro
    sobre una columna que no existe).
    """
    clauses = ["1 = 1"]
    params: dict[str, Any] = {}
    if opera_estados:
        clauses.append(
            "EXISTS (SELECT 1 FROM unnest(:opera_estados ::text[]) AS estado "
            "WHERE v.opera ILIKE '%' || estado || '%')"
        )
        params["opera_estados"] = list(opera_estados)
    if isp_nombres:
        clauses.append("v.isp_nombre = ANY(:isp_nombres)")
        params["isp_nombres"] = list(isp_nombres)

    df = _read(
        f"""
        SELECT COUNT(*) AS cantidad
        FROM mart.vw_prestadores_sin_reportar v
        WHERE {' AND '.join(clauses)}
        """,
        params,
    )
    if df.empty:
        return 0
    return int(df.iloc[0]["cantidad"])


def _filtros_participacion(opera_estados: list[str] | None, isp_nombres: list[str] | None):
    """Cláusulas y parámetros compartidos por get_participation_filtrado y get_ihh_filtrado."""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if opera_estados:
        clauses.append(
            "EXISTS (SELECT 1 FROM unnest(:opera_estados ::text[]) AS estado "
            "WHERE p.opera_actual ILIKE '%' || estado || '%')"
        )
        params["opera_estados"] = list(opera_estados)
    if isp_nombres:
        clauses.append("p.isp_nombre = ANY(:isp_nombres)")
        params["isp_nombres"] = list(isp_nombres)
    return clauses, params


@cache.memoize(timeout=300)
def get_participation_filtrado(
        territory_id: str,
        period_id: int,
        opera_estados: list[str] | None = None,
        isp_nombres: list[str] | None = None,
) -> pd.DataFrame:
    """
    Igual que get_participation, pero recalculando ranking/participación/
    aporte_ihh EN VIVO sobre el subconjunto filtrado por Estado de
    operación / Prestador -- mart.vw_dashboard_participacion ya viene
    pre-calculada sobre TODO el universo de prestadores del territorio, sin
    posibilidad de excluir antes de calcular el mercado.

    Replica exactamente la misma metodología ya aplicada en
    fact_participacion_mercado (31-jul-2026): solo lineas_reportadas de
    quien reportó ese mes exacto, denominador (mercado) recalculado de
    forma consistente sobre el mismo subconjunto filtrado -- nunca sobre
    el total sin filtrar mientras el numerador sí está filtrado.
    """
    clauses_extra, params = _filtros_participacion(opera_estados, isp_nombres)
    clauses = ["b.territorio_id = :territory_id", "f.periodo_id = :period_id", *clauses_extra]
    params.update({"territory_id": territory_id, "period_id": period_id})

    return _read(
        f"""
        WITH base AS (
            SELECT
                f.prestador_id,
                SUM(f.total_lineas) AS total_lineas_prestador,
                SUM(COALESCE(f.lineas_reportadas, 0)) AS lineas_reportadas,
                SUM(COALESCE(f.lineas_imputadas, 0)) AS lineas_imputadas,
                BOOL_OR(f.tiene_reportado) AS tiene_reportado
            FROM mart.fact_lineas_geografia_mes f
            JOIN mart.bridge_geografia_territorio b ON b.geografia_id = f.geografia_id
            JOIN mart.dim_prestador p ON p.prestador_id = f.prestador_id
            WHERE {' AND '.join(clauses)}
            GROUP BY f.prestador_id
        ),
        mercado AS (
            SELECT
                SUM(lineas_reportadas) FILTER (WHERE tiene_reportado) AS total_mercado,
                COUNT(*) FILTER (WHERE tiene_reportado) AS n_reportaron,
                COUNT(*) AS n_total
            FROM base
        ),
        ranking AS (
            SELECT
                b.*,
                m.total_mercado, m.n_reportaron, m.n_total,
                CASE
                    WHEN b.tiene_reportado AND b.lineas_reportadas > 0 AND m.total_mercado > 0
                    THEN ROW_NUMBER() OVER (ORDER BY b.lineas_reportadas DESC NULLS LAST, b.prestador_id)
                END AS ranking_prestador
            FROM base b
            CROSS JOIN mercado m
        )
        SELECT
            r.prestador_id,
            p.ruc_limpio, p.isp_ruc, p.peva_codigo_principal, p.cantidad_peva, p.codigos_peva,
            p.isp_nombre, p.nombrecomercial, p.opera_actual, p.es_cancelado_actual,
            r.total_lineas_prestador,
            r.total_mercado AS total_lineas_mercado,
            CASE WHEN r.tiene_reportado AND r.lineas_reportadas > 0 AND r.total_mercado > 0
                THEN ROUND(r.lineas_reportadas / r.total_mercado, 10) END AS participacion_decimal,
            CASE WHEN r.tiene_reportado AND r.lineas_reportadas > 0 AND r.total_mercado > 0
                THEN ROUND(100.0 * r.lineas_reportadas / r.total_mercado, 8) END AS participacion_porcentaje,
            CASE WHEN r.tiene_reportado AND r.lineas_reportadas > 0 AND r.total_mercado > 0
                THEN ROUND(POWER(100.0 * r.lineas_reportadas / r.total_mercado, 2), 8) END AS aporte_ihh,
            r.ranking_prestador,
            r.ranking_prestador = 1 AS es_lider,
            CASE
                WHEN NOT r.tiene_reportado THEN 'SIN_REPORTE_ESTE_MES'
                WHEN r.lineas_reportadas > 0 THEN 'POSITIVO'
                WHEN r.lineas_reportadas = 0 THEN 'CERO'
                ELSE 'SIN_DATO'
            END AS estado_lineas,
            r.lineas_reportadas, r.lineas_imputadas, r.tiene_reportado,
            r.n_reportaron AS numero_prestadores_reportaron_periodo,
            r.n_total AS numero_prestadores_totales_periodo,
            ROUND(100.0 * r.n_reportaron / NULLIF(r.n_total, 0), 4) AS porcentaje_cobertura_prestadores
        FROM ranking r
        JOIN mart.dim_prestador p ON p.prestador_id = r.prestador_id
        ORDER BY r.ranking_prestador NULLS LAST, p.isp_nombre NULLS LAST
        """,
        params,
    )


@cache.memoize(timeout=300)
def get_ihh_filtrado(
        territory_id: str,
        start_period: int,
        end_period: int,
        opera_estados: list[str] | None = None,
        isp_nombres: list[str] | None = None,
) -> pd.DataFrame:
    """
    Igual que get_ihh, pero recalculando el IHH/CR2/CR4 mes a mes EN VIVO
    sobre el subconjunto filtrado -- mismo principio que
    get_participation_filtrado, aplicado a toda la serie de tiempo.
    """
    clauses_extra, params = _filtros_participacion(opera_estados, isp_nombres)
    clauses = [
        "b.territorio_id = :territory_id",
        "f.periodo_id BETWEEN :start_period AND :end_period",
        *clauses_extra,
    ]
    params.update({"territory_id": territory_id, "start_period": start_period, "end_period": end_period})

    df = _read(
        f"""
        WITH base AS (
            SELECT
                f.periodo_id,
                f.prestador_id,
                SUM(COALESCE(f.lineas_reportadas, 0)) AS lineas_reportadas,
                SUM(COALESCE(f.lineas_imputadas, 0)) AS lineas_imputadas,
                BOOL_OR(f.tiene_reportado) AS tiene_reportado
            FROM mart.fact_lineas_geografia_mes f
            JOIN mart.bridge_geografia_territorio b ON b.geografia_id = f.geografia_id
            JOIN mart.dim_prestador p ON p.prestador_id = f.prestador_id
            WHERE {' AND '.join(clauses)}
            GROUP BY f.periodo_id, f.prestador_id
        ),
        mercado AS (
            SELECT
                periodo_id,
                SUM(lineas_reportadas) FILTER (WHERE tiene_reportado) AS total_mercado,
                COUNT(*) FILTER (WHERE tiene_reportado) AS n_reportaron,
                COUNT(*) AS n_total
            FROM base
            GROUP BY periodo_id
        ),
        con_mercado AS (
            SELECT b.*, m.total_mercado, m.n_reportaron, m.n_total
            FROM base b
            JOIN mercado m ON m.periodo_id = b.periodo_id
        ),
        ranking AS (
            SELECT
                c.*,
                CASE
                    WHEN c.tiene_reportado AND c.lineas_reportadas > 0 AND c.total_mercado > 0
                    THEN ROW_NUMBER() OVER (
                        PARTITION BY c.periodo_id
                        ORDER BY c.lineas_reportadas DESC NULLS LAST, c.prestador_id
                    )
                END AS ranking_prestador,
                CASE WHEN c.tiene_reportado AND c.lineas_reportadas > 0 AND c.total_mercado > 0
                    THEN ROUND(POWER(100.0 * c.lineas_reportadas / c.total_mercado, 2), 8) END AS aporte_ihh,
                CASE WHEN c.tiene_reportado AND c.lineas_reportadas > 0 AND c.total_mercado > 0
                    THEN ROUND(100.0 * c.lineas_reportadas / c.total_mercado, 8) END AS participacion_porcentaje
            FROM con_mercado c
        ),
        agregado AS (
            SELECT
                r.periodo_id,
                MAX(r.total_mercado) AS total_lineas_mercado,
                MAX(r.n_total) AS numero_prestadores,
                COUNT(*) FILTER (WHERE r.tiene_reportado AND r.lineas_reportadas > 0) AS numero_prestadores_con_lineas,
                ROUND(COALESCE(SUM(r.aporte_ihh), 0), 6) AS ihh,
                MAX(r.prestador_id) FILTER (WHERE r.ranking_prestador = 1) AS prestador_lider_id,
                MAX(r.participacion_porcentaje) FILTER (WHERE r.ranking_prestador = 1) AS participacion_lider,
                ROUND(COALESCE(SUM(r.participacion_porcentaje) FILTER (WHERE r.ranking_prestador <= 2), 0), 6) AS cr2,
                ROUND(COALESCE(SUM(r.participacion_porcentaje) FILTER (WHERE r.ranking_prestador <= 4), 0), 6) AS cr4,
                SUM(r.lineas_reportadas) AS lineas_reportadas_mercado,
                SUM(r.lineas_imputadas) AS lineas_imputadas_mercado,
                MAX(r.n_reportaron) AS numero_prestadores_reportaron,
                MAX(r.n_total) AS numero_prestadores_registrados,
                ROUND(100.0 * MAX(r.n_reportaron) / NULLIF(MAX(r.n_total), 0), 4) AS porcentaje_cobertura_prestadores
            FROM ranking r
            GROUP BY r.periodo_id
        )
        SELECT
            a.*,
            p.isp_nombre AS prestador_lider_nombre,
            p.nombrecomercial AS prestador_lider_nombrecomercial
        FROM agregado a
        LEFT JOIN mart.dim_prestador p ON p.prestador_id = a.prestador_lider_id
        ORDER BY a.periodo_id
        """,
        params,
    )

    if df.empty:
        return df

    periods = get_periods()[["periodo_id", "periodo", "anio", "mes", "nombre_mes", "anio_mes"]]
    df = df.merge(periods, on="periodo_id", how="left")
    return df.sort_values("periodo_id").reset_index(drop=True)


# ============================================================
# NODOS ISP -- geografía y discrepancias (07-ago-2026)
# ============================================================
# Universo DISTINTO de get_territory_options/get_provider_options -- esos
# operan sobre geografía de LÍNEAS reportadas (mart.dim_territorio,
# bridge_geografia_territorio). Un nodo físico puede servir a varias
# parroquias de líneas, no hay relación 1:1 -- nunca se mezclan (confirmado
# con Iván 06-ago-2026). Fuente: mart.vw_nodos_isp_mapa, geografía CONALI.

@cache.memoize(timeout=900)
def get_node_territory_options(
        level: str,
        province_code: str | None = None,
        canton_code: str | None = None,
) -> list[dict[str, str]]:
    """Opciones para el filtro geográfico en cascada del mapa de nodos."""
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
        SELECT territorio_id, codigo_geografico, nombre_geografico,
               codigo_provincia, codigo_canton, codigo_parroquia
        FROM mart.vw_dashboard_filtros_geograficos_nodo
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


@cache.memoize(timeout=900)
def get_node_types() -> list[dict[str, str]]:
    """
    Valores distintos de tiponodo, para el filtro 'Tipo de nodo'.

    CORRECCIÓN (11-ago-2026): el dropdown mostraba "PRIMARIO"/"SECUNDARIO"
    duplicados -- confirmado que la causa es variación de mayúsculas/
    espacios en blanco en el propio dato (ej. "PRIMARIO" vs "PRIMARIO " o
    "Primario"), que SQL DISTINCT trata como valores genuinamente distintos
    aunque se vean iguales en pantalla. BTRIM+UPPER normaliza para la LISTA
    de opciones -- el valor real sigue siendo el original, así que el
    filtro en get_nodos_mapa normaliza de la misma forma al comparar, no
    solo al listar (ver ese WHERE). Esto NO altera el dato fuente
    (capa2.nodo_isp_geografia_resuelta) -- solo cómo se agrupa para
    mostrar y filtrar, igual que ya se hace con opera_actual en
    get_operation_states.
    """
    df = _read(
        """
        SELECT DISTINCT UPPER(BTRIM(tiponodo)) AS tiponodo
        FROM mart.vw_nodos_isp_mapa
        WHERE tiponodo IS NOT NULL AND BTRIM(tiponodo) <> ''
        ORDER BY 1
        """
    )
    return [{"label": row["tiponodo"], "value": row["tiponodo"]} for _, row in df.iterrows()]


def _node_territory_clauses(
        provincias: list[str] | None,
        cantones: list[str] | None,
        parroquias: list[str] | None,
) -> tuple[list[str], dict[str, Any]]:
    """
    Cláusulas SQL para el filtro geográfico de nodos, REDISEÑADO 11-ago-2026:
    Provincia/Cantón/Parroquia ya no son una jerarquía de un solo nivel
    (antes: territory_id como "CANTON|17|1701") -- son tres listas
    independientes, cada una de selección múltiple. AND entre las tres
    dimensiones, OR dentro de cada lista (mismo patrón que tipo_nodos/
    isp_nombres en get_nodos_mapa) -- estilo segmentadores de Power BI.
    Una lista vacía o None no filtra por esa dimensión.
    """
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if provincias:
        clauses.append("codigo_provincia = ANY(:provincias)")
        params["provincias"] = list(provincias)
    if cantones:
        clauses.append("codigo_canton = ANY(:cantones)")
        params["cantones"] = list(cantones)
    if parroquias:
        clauses.append("codigo_parroquia = ANY(:parroquias)")
        params["parroquias"] = list(parroquias)
    return clauses, params


@cache.memoize(timeout=900)
def get_node_provider_options(
        provincias: tuple[str, ...] = (),
        cantones: tuple[str, ...] = (),
        parroquias: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    """
    Nombres de prestadores con nodos en el territorio, para el filtro
    'Prestador'. Los argumentos son tuplas (no listas) porque
    @cache.memoize necesita argumentos hasheables -- el llamador convierte
    con tuple(lista) antes de invocar.
    """
    clauses, params = _node_territory_clauses(list(provincias), list(cantones), list(parroquias))
    clauses.insert(0, "isp_nombre IS NOT NULL")

    df = _read(
        f"""
        SELECT DISTINCT isp_nombre
        FROM mart.vw_nodos_isp_mapa
        WHERE {' AND '.join(clauses)}
        ORDER BY isp_nombre
        """,
        params,
    )
    return [{"label": row["isp_nombre"], "value": row["isp_nombre"]} for _, row in df.iterrows()]


@cache.memoize(timeout=180)
def get_nodos_mapa(
        provincias: tuple[str, ...] = (),
        cantones: tuple[str, ...] = (),
        parroquias: tuple[str, ...] = (),
        tipo_nodos: tuple[str, ...] = (),
        opera_estados: tuple[str, ...] = (),
        isp_nombres: tuple[str, ...] = (),
        solo_discrepancias: bool = False,
) -> pd.DataFrame:
    """
    Universo de nodos para el mapa (o la tabla de discrepancias, con
    solo_discrepancias=True). Todos los argumentos de lista son tuplas (no
    listas) por el mismo motivo que get_node_provider_options --
    @cache.memoize exige argumentos hasheables.

    tipo_nodos compara contra UPPER(BTRIM(tiponodo)) -- igual que
    get_node_types(), para que un valor elegido en el dropdown (ya
    normalizado) encuentre TODAS sus variantes de mayúsculas/espacios en
    el dato real, no solo la variante exacta que quedó cacheada en la
    lista de opciones.

    opera_actual puede traer varios estados separados por coma para un
    mismo prestador (mismo caso que dim_prestador.opera_actual en
    get_operation_states) -- se filtra con ILIKE ANY sobre patrones
    '%estado%', suficiente para un filtro de UI, sin replicar el UNNEST
    exacto de las páginas de líneas.
    """
    clauses, params = _node_territory_clauses(list(provincias), list(cantones), list(parroquias))

    if tipo_nodos:
        clauses.append("UPPER(BTRIM(tiponodo)) = ANY(:tipo_nodos)")
        params["tipo_nodos"] = list(tipo_nodos)

    if isp_nombres:
        clauses.append("isp_nombre = ANY(:isp_nombres)")
        params["isp_nombres"] = list(isp_nombres)

    if opera_estados:
        clauses.append("opera_actual ILIKE ANY(:opera_patrones)")
        params["opera_patrones"] = [f"%{estado}%" for estado in opera_estados]

    if solo_discrepancias:
        clauses.append("es_discrepancia = TRUE")

    where = " AND ".join(clauses) if clauses else "TRUE"
    return _read(f"SELECT * FROM mart.vw_nodos_isp_mapa WHERE {where}", params)


@cache.memoize(timeout=900)
def get_territory_geojson_multi(
        provincias: tuple[str, ...] = (),
        cantones: tuple[str, ...] = (),
        parroquias: tuple[str, ...] = (),
) -> tuple[list[dict], tuple[float, float, float, float]] | None:
    """
    Geometría (GeoJSON) de TODOS los territorios seleccionados, para los
    polígonos semi-transparentes del mapa de nodos -- rediseñado 11-ago-2026
    para selección múltiple (antes: un solo territory_id). Devuelve
    (lista_de_geojson, bounds combinados) o None si no hay nada seleccionado
    (a nivel Nacional no se dibuja polígono -- rellenar todo el país no
    aporta nada visualmente).

    Precedencia "el nivel más específico elegido gana": si hay parroquias
    elegidas, se dibujan esas parroquias (ignorando cantones/provincias
    elegidos como polígono -- igual se siguen aplicando como filtro de
    datos en get_nodos_mapa, esto es solo la capa visual); si no, cantones;
    si no, provincias. Elegir combinaciones inconsistentes (ej. una
    parroquia que no pertenece a la provincia también elegida) es válido
    para el filtro AND de datos, pero aquí solo se dibuja el nivel más
    fino -- una limitación visual aceptada, no un bug del filtro de datos.
    """
    if parroquias:
        nivel, codigos = "PARROQUIA", list(parroquias)
    elif cantones:
        nivel, codigos = "CANTON", list(cantones)
    elif provincias:
        nivel, codigos = "PROVINCIA", list(provincias)
    else:
        return None

    df = _read(
        """
        SELECT geometria_geojson, lon_min, lat_min, lon_max, lat_max
        FROM mart.vw_geometria_territorio_nodo
        WHERE nivel_geografico = :nivel AND codigo_territorio = ANY(:codigos)
        """,
        {"nivel": nivel, "codigos": codigos},
    )
    if df.empty:
        return None

    geojsons = []
    lon_min = lat_min = float("inf")
    lon_max = lat_max = float("-inf")
    for _, fila in df.iterrows():
        geojson = fila["geometria_geojson"]
        if isinstance(geojson, str):
            geojson = json.loads(geojson)
        geojsons.append(geojson)
        lon_min = min(lon_min, float(fila["lon_min"]))
        lat_min = min(lat_min, float(fila["lat_min"]))
        lon_max = max(lon_max, float(fila["lon_max"]))
        lat_max = max(lat_max, float(fila["lat_max"]))

    return geojsons, (lon_min, lat_min, lon_max, lat_max)


# ============================================================
# CONTROL -- inconsistencias para revisión (11-ago-2026)
# ============================================================
# Reutiliza vistas ya existentes y probadas en producción
# (vw_prestadores_sin_reportar, vw_prestadores_reporte_detenido) más una
# consulta nueva de variación mes a mes -- ninguna requiere cambios de DDL
# en mart, solo lectura sobre lo que ya existe.

@cache.memoize(timeout=300)
def get_prestadores_nunca_reportaron_detalle(
        opera_estados: tuple[str, ...] = (),
        isp_nombres: tuple[str, ...] = (),
) -> pd.DataFrame:
    """
    Detalle completo (no solo el conteo) de mart.vw_prestadores_sin_reportar,
    para la tabla de Control -- get_prestadores_sin_reportar() (más arriba)
    ya existía para el KPI de Evolución, pero solo devuelve un COUNT.

    SOLO acepta Estado de operación / Prestador -- NO territorio ni período.
    La vista fuente no tiene columna de geografía (SIETEL no conoce la
    ubicación de un prestador que nunca reportó, documentado en la propia
    vista) ni de período (es "alguna vez reportó, sí/no", no una serie de
    tiempo) -- no son columnas que falten agregar aquí, son datos que
    genuinamente no existen para filtrar.
    """
    clauses = ["1 = 1"]
    params: dict[str, Any] = {}
    if opera_estados:
        clauses.append(
            "EXISTS (SELECT 1 FROM unnest(:opera_estados ::text[]) AS estado "
            "WHERE opera ILIKE '%' || estado || '%')"
        )
        params["opera_estados"] = list(opera_estados)
    if isp_nombres:
        clauses.append("isp_nombre = ANY(:isp_nombres)")
        params["isp_nombres"] = list(isp_nombres)

    return _read(
        f"""
        SELECT peva_codigo, isp_nombre, isp_ruc, isp_tipopersona, opera,
               resolucion, fechapermiso, fuera_de_gracia, clasificacion_incumplimiento
        FROM mart.vw_prestadores_sin_reportar
        WHERE {' AND '.join(clauses)}
        ORDER BY fuera_de_gracia DESC NULLS LAST, fechapermiso NULLS LAST
        """,
        params,
    )


@cache.memoize(timeout=300)
def get_prestadores_reporte_detenido_detalle(
        meses_minimo: int = 1,
        provincias: tuple[str, ...] = (),
        cantones: tuple[str, ...] = (),
        parroquias: tuple[str, ...] = (),
        start_period: int | None = None,
        end_period: int | None = None,
        opera_estados: tuple[str, ...] = (),
        isp_nombres: tuple[str, ...] = (),
) -> pd.DataFrame:
    """
    Detalle de mart.vw_prestadores_reporte_detenido, filtrado por
    meses_desde_ultimo_reporte >= meses_minimo -- la vista misma NO trae
    umbral (documentado en su propio COMMENT), a propósito, para que cada
    consumidor decida su corte; este es el corte del módulo Control, no un
    valor fijo en mart.

    provincias/cantones/parroquias filtran por "reportó AL MENOS UNA VEZ
    en algún geografia_id de ese territorio" (EXISTS contra
    fact_lineas_geografia_mes/bridge_geografia_territorio/dim_territorio,
    selección múltiple e independiente -- ver _lines_territory_clauses())
    -- la vista fuente no tiene geografía propia (es un resumen por
    prestador, sin desglose geográfico), así que esto es una aproximación
    razonable, no la geografía de su último reporte específico.

    start_period/end_period filtran por ultimo_periodo_reportado dentro
    del rango (vía mart.dim_periodo.periodo, la fecha real del período) --
    "¿prestadores cuyo último reporte cayó en esta ventana?", distinto de
    "meses_minimo" (que es cuánto tiempo llevan detenidos desde HOY).
    """
    clauses = ["meses_desde_ultimo_reporte >= :meses_minimo"]
    params: dict[str, Any] = {"meses_minimo": meses_minimo}

    territorio_sql, territorio_params = _lines_territory_clauses(
        "f.geografia_id", provincias, cantones, parroquias,
    )
    if territorio_sql:
        # CORRECCIÓN (12-ago-2026): antes decía "f.prestador_id = prestador_id"
        # -- ese "prestador_id" suelto lo resolvía Postgres contra f (la
        # tabla MÁS INTERNA que también tiene una columna prestador_id),
        # no contra pr (la tabla exterior que se quiere correlacionar).
        # La condición terminaba siendo "f.prestador_id = f.prestador_id"
        # -- una tautología, siempre verdadera -- así que el EXISTS
        # preguntaba "¿existe ALGUNA fila en ese territorio en toda la
        # tabla nacional?" en vez de "¿ESTE prestador reportó ahí?".
        # Confirmado en producción: filas_resultado se quedaba en 548 sin
        # importar el territorio elegido. Ahora "pr" alias explícito la
        # tabla exterior, sin ambigüedad posible.
        clauses.append(
            f"EXISTS (SELECT 1 FROM mart.fact_lineas_geografia_mes f "
            f"WHERE f.prestador_id = pr.prestador_id AND {territorio_sql})"
        )
        params.update(territorio_params)
    if start_period is not None and end_period is not None:
        clauses.append(
            "ultimo_periodo_reportado BETWEEN "
            "(SELECT periodo FROM mart.dim_periodo WHERE periodo_id = :start_period) "
            "AND (SELECT periodo FROM mart.dim_periodo WHERE periodo_id = :end_period)"
        )
        params["start_period"] = start_period
        params["end_period"] = end_period
    if opera_estados:
        clauses.append(
            "EXISTS (SELECT 1 FROM unnest(:opera_estados ::text[]) AS estado "
            "WHERE opera_actual ILIKE '%' || estado || '%')"
        )
        params["opera_estados"] = list(opera_estados)
    if isp_nombres:
        clauses.append("isp_nombre = ANY(:isp_nombres)")
        params["isp_nombres"] = list(isp_nombres)

    return _read(
        f"""
        SELECT prestador_id, isp_nombre, ruc_limpio, opera_actual, es_cancelado_actual,
               primer_periodo_reportado, ultimo_periodo_reportado,
               lineas_ultimo_reporte, total_lineas_historico, meses_desde_ultimo_reporte
        FROM mart.vw_prestadores_reporte_detenido pr
        WHERE {' AND '.join(clauses)}
        ORDER BY meses_desde_ultimo_reporte DESC, total_lineas_historico DESC
        """,
        params,
    )


@cache.memoize(timeout=300)
def get_variacion_mensual_anomala(
        start_period: int,
        end_period: int,
        umbral_porcentaje: float = 30.0,
        provincias: tuple[str, ...] = (),
        cantones: tuple[str, ...] = (),
        parroquias: tuple[str, ...] = (),
        opera_estados: tuple[str, ...] = (),
        isp_nombres: tuple[str, ...] = (),
) -> pd.DataFrame:
    """
    Variación mes a mes de cuentas reportadas, por prestador, dentro del
    rango -- SOLO entre pares de meses consecutivos donde el prestador
    tiene_reportado=TRUE en AMBOS meses (mismo principio metodológico que
    IHH/participación: nunca mezclar "dejó de reportar" -- ya cubierto por
    get_prestadores_reporte_detenido_detalle -- con "reportó de verdad un
    cambio real"). Un salto grande entre un mes reportado y uno imputado no
    es una variación real, es artefacto del relleno LOCF -- se excluye
    explícitamente filtrando por tiene_reportado en ambos extremos del par.

    umbral_porcentaje filtra el resultado a |variación| >= umbral, para que
    la tabla no se llene de ruido de variaciones normales -- 30% es un
    punto de partida razonable para señalar algo revisable, no un límite
    validado estadísticamente; el filtro de la página permite ajustarlo.

    provincias/cantones/parroquias (selección múltiple e independiente,
    ver _lines_territory_clauses()) RECALCULAN la suma de cuentas dentro
    de ese territorio antes de comparar mes a mes (no filtran después) --
    mismo principio que get_evolution_filtrado: la variación detectada es
    "¿este prestador cambió mucho lo que reporta EN ESE TERRITORIO?", no
    su total nacional. opera_estados/isp_nombres sí filtran por identidad
    del prestador después de calcular (no cambian la suma).
    """
    params: dict[str, Any] = {"start_period": start_period, "end_period": end_period, "umbral": umbral_porcentaje}

    territorio_sql, territorio_params = _lines_territory_clauses("f.geografia_id", provincias, cantones, parroquias)
    territorio_where = f"AND {territorio_sql}" if territorio_sql else ""
    params.update(territorio_params)

    outer_clauses = []
    if opera_estados:
        outer_clauses.append(
            "EXISTS (SELECT 1 FROM unnest(:opera_estados ::text[]) AS estado "
            "WHERE p.opera_actual ILIKE '%' || estado || '%')"
        )
        params["opera_estados"] = list(opera_estados)
    if isp_nombres:
        outer_clauses.append("p.isp_nombre = ANY(:isp_nombres)")
        params["isp_nombres"] = list(isp_nombres)
    outer_where = ("AND " + " AND ".join(outer_clauses)) if outer_clauses else ""

    df = _read(
        f"""
        WITH serie AS (
            SELECT
                f.prestador_id,
                f.periodo_id,
                f.periodo,
                SUM(COALESCE(f.lineas_reportadas, 0)) AS lineas_reportadas,
                BOOL_OR(f.tiene_reportado) AS tiene_reportado
            FROM mart.fact_lineas_geografia_mes f
            WHERE f.periodo_id BETWEEN :start_period AND :end_period
            {territorio_where}
            GROUP BY f.prestador_id, f.periodo_id, f.periodo
        ),
        con_lag AS (
            SELECT
                s.*,
                LAG(s.lineas_reportadas) OVER (PARTITION BY s.prestador_id ORDER BY s.periodo_id) AS lineas_mes_anterior,
                LAG(s.tiene_reportado) OVER (PARTITION BY s.prestador_id ORDER BY s.periodo_id) AS reporto_mes_anterior
            FROM serie s
        )
        SELECT
            c.prestador_id,
            p.isp_nombre,
            p.ruc_limpio,
            c.periodo,
            c.lineas_mes_anterior,
            c.lineas_reportadas,
            (c.lineas_reportadas - c.lineas_mes_anterior) AS diferencia,
            CASE WHEN c.lineas_mes_anterior > 0
                THEN ROUND(100.0 * (c.lineas_reportadas - c.lineas_mes_anterior) / c.lineas_mes_anterior, 2)
            END AS variacion_porcentaje
        FROM con_lag c
        JOIN mart.dim_prestador p ON p.prestador_id = c.prestador_id
        WHERE c.tiene_reportado = TRUE
          AND c.reporto_mes_anterior = TRUE
          AND c.lineas_mes_anterior IS NOT NULL
          AND c.lineas_mes_anterior > 0
          AND ABS(100.0 * (c.lineas_reportadas - c.lineas_mes_anterior) / c.lineas_mes_anterior) >= :umbral
          {outer_where}
        ORDER BY ABS(c.lineas_reportadas - c.lineas_mes_anterior) DESC
        """,
        params,
    )
    if df.empty:
        return df
    periods = get_periods()[["periodo_id", "anio_mes"]]
    df["periodo_id"] = pd.to_datetime(df["periodo"]).dt.year * 100 + pd.to_datetime(df["periodo"]).dt.month
    df = df.merge(periods, on="periodo_id", how="left")
    return df


@cache.memoize(timeout=300)
def get_churn_history(territory_id: str, end_period: int, meses: int = 12) -> pd.DataFrame:
    """
    Historial reciente de "prestadores que dejaron de reportar cada mes"
    (churn), para el sparkline de "Dejaron de reportar este mes" en
    Evolución -- ese KPI era un número aislado sin ningún gráfico en la
    página que mostrara su tendencia (a diferencia de "Cuentas
    reportadas", que ya tiene su línea completa debajo).

    Acotado a los últimos `meses` períodos terminando en end_period, NO al
    rango Desde-Hasta completo (que puede cubrir 15 años) -- un sparkline
    es contexto reciente, no un historial completo; calcularlo sobre 180
    meses sería costoso para una tendencia que además sería ilegible a ese
    tamaño de todas formas.

    "activo" = tiene_reportado Y al menos una cuenta reportada ese mes,
    vía LAG() sobre mart.vw_dashboard_participacion -- mismo patrón que
    get_variacion_mensual_anomala. El primer período de la ventana no
    tiene mes anterior DENTRO de la ventana, así que su churn queda en 0
    en vez del valor real (subestima ese único punto) -- aceptable para
    una tendencia reciente, no para una cifra certificada.
    """
    meses = max(2, int(meses))
    df = _read(
        f"""
        WITH ancla AS (
            SELECT periodo FROM mart.dim_periodo WHERE periodo_id = :end_period
        ),
        serie AS (
            SELECT
                vp.periodo_id,
                vp.prestador_id,
                (vp.tiene_reportado AND COALESCE(vp.total_lineas_prestador, 0) > 0) AS activo
            FROM mart.vw_dashboard_participacion vp, ancla
            WHERE vp.territorio_id = :territory_id
              AND vp.periodo BETWEEN (ancla.periodo - INTERVAL '{meses} months') AND ancla.periodo
        ),
        con_lag AS (
            SELECT
                periodo_id, prestador_id, activo,
                LAG(activo) OVER (PARTITION BY prestador_id ORDER BY periodo_id) AS activo_anterior
            FROM serie
        )
        SELECT
            c.periodo_id,
            d.anio_mes,
            COUNT(*) FILTER (WHERE c.activo_anterior = TRUE AND c.activo = FALSE) AS churn
        FROM con_lag c
        JOIN mart.dim_periodo d ON d.periodo_id = c.periodo_id
        GROUP BY c.periodo_id, d.anio_mes
        ORDER BY c.periodo_id
        """,
        {"territory_id": territory_id, "end_period": end_period},
    )
    return df


# ============================================================
# FILTRADO CRUZADO (bidireccional) de selectores geográficos
# ============================================================
# A pedido del usuario (13-ago-2026): elegir una Parroquia debe acotar
# también las opciones de Cantón/Provincia, no solo al revés (que ya
# funcionaba). Se resuelve con una tabla de referencia completa
# Provincia-Cantón-Parroquia (pequeña, ~1.000 filas) cacheada una hora y
# filtrada en memoria con pandas -- evita escribir una consulta SQL
# distinta por cada combinación posible de filtros activos.

@cache.memoize(timeout=3600)
def get_territory_hierarchy() -> pd.DataFrame:
    """
    Provincia-Cantón-Parroquia completos, geografía de LÍNEAS
    (mart.dim_territorio vía vw_dashboard_filtros_geograficos) -- para el
    filtrado cruzado de components/lines_territory_filters.py (Control).
    """
    return _read(
        """
        SELECT codigo_provincia, pro_nombre, codigo_canton, ciu_nombre, codigo_parroquia, par_nombre
        FROM mart.vw_dashboard_filtros_geograficos
        WHERE nivel_geografico = 'PARROQUIA'
        """
    )


@cache.memoize(timeout=3600)
def get_node_territory_hierarchy() -> pd.DataFrame:
    """
    Igual que get_territory_hierarchy() pero para geografía de NODOS
    (mart.dim_territorio_nodo vía vw_dashboard_filtros_geograficos_nodo) --
    para el filtrado cruzado de components/node_territory_filters.py
    (Mapa de nodos, Discrepancias de geografía).
    """
    return _read(
        """
        SELECT codigo_provincia, nombre_provincia, codigo_canton, nombre_canton, codigo_parroquia, nombre_parroquia
        FROM mart.vw_dashboard_filtros_geograficos_nodo
        WHERE nivel_geografico = 'PARROQUIA'
        """
    )


def opciones_geograficas_facetadas(
        jerarquia: pd.DataFrame,
        columna_codigo: str,
        columna_nombre: str,
        filtros: dict[str, list[str]],
) -> list[dict[str, str]]:
    """
    Opciones para UN nivel del filtro geográfico (Provincia/Cantón/
    Parroquia), acotadas por lo elegido en los OTROS dos niveles --
    filtrado cruzado real, no solo hacia abajo. `filtros` es
    {columna_del_otro_nivel: [códigos elegidos]}; nunca debe incluir
    columna_codigo (no tiene sentido acotar un nivel por su propio valor).

    Deduplicado por código -- `jerarquia` trae una fila por PARROQUIA, así
    que un mismo cantón aparece repetido una vez por cada una de sus
    parroquias.

    Función pura, sin acceso a base de datos -- se llama con
    get_territory_hierarchy()/get_node_territory_hierarchy() ya resueltas
    (cacheadas), reutilizable por ambos filtros geográficos del dashboard.
    """
    df = jerarquia
    for columna, codigos in filtros.items():
        if codigos:
            df = df[df[columna].isin(codigos)]
    opciones = (
        df[[columna_codigo, columna_nombre]]
        .dropna()
        .drop_duplicates(subset=[columna_codigo])
        .sort_values(columna_nombre)
    )
    return [
        {"label": str(fila[columna_nombre]), "value": str(fila[columna_codigo])}
        for _, fila in opciones.iterrows()
    ]


# ============================================================
# Versiones "multiselect" para Control (14-ago-2026)
# ============================================================
# Duplican get_evolution_filtrado/get_provider_count_in_range/
# get_reporting_summary/get_churn_history para el filtro geográfico
# multi-select e independiente de Control (Provincia/Cantón/Parroquia,
# SIN Nivel) -- NO reemplazan a las originales, que Evolución sigue
# usando con su propio modelo de territory_id único + Nivel. Duplicadas a
# propósito: mismo criterio que lines_territory_filters.py vs
# node_territory_filters.py -- tocar las funciones originales arriesgaría
# páginas que ya funcionan en producción por evitar unas líneas repetidas.
#
# get_churn_history_multiselect() NO puede reusar
# mart.vw_dashboard_participacion/fact_participacion_mercado como la
# original -- esa vista materializada está pre-agregada por territorio_id
# ÚNICO (join contra bridge_geografia_territorio en tiempo de
# CONSTRUCCIÓN del mart, no de consulta), no es descomponible a una
# combinación independiente de Provincia/Cantón/Parroquia. Se recalcula
# "activo" directo desde mart.fact_lineas_geografia_mes, mismo patrón que
# get_variacion_mensual_anomala.
#
# get_reporting_summary_multiselect() NO incluye la población "nunca han
# reportado" (parámetro incluir_nunca_reportaron del original) -- Control
# ya tiene su propia sección dedicada a eso, con más detalle; agregarla
# aquí también sería el mismo número repetido en la misma página.

@cache.memoize(timeout=300)
def get_evolution_filtrado_multiselect(
        provincias: tuple[str, ...],
        cantones: tuple[str, ...],
        parroquias: tuple[str, ...],
        start_period: int,
        end_period: int,
        opera_estados: tuple[str, ...] = (),
        isp_nombres: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Ver get_evolution_filtrado() -- misma lógica, filtro geográfico multi-select de Control."""
    territorio_sql, territorio_params = _lines_territory_clauses("f.geografia_id", provincias, cantones, parroquias)
    territorio_where = f"AND {territorio_sql}" if territorio_sql else ""

    clauses = ["f.periodo_id BETWEEN :start_period AND :end_period"]
    params: dict[str, Any] = {"start_period": start_period, "end_period": end_period}
    params.update(territorio_params)
    if opera_estados:
        clauses.append(
            "EXISTS (SELECT 1 FROM unnest(:opera_estados ::text[]) AS estado "
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
        JOIN mart.dim_prestador p ON p.prestador_id = f.prestador_id
        WHERE {' AND '.join(clauses)}
          {territorio_where}
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
def get_provider_count_in_range_multiselect(
        provincias: tuple[str, ...],
        cantones: tuple[str, ...],
        parroquias: tuple[str, ...],
        start_period: int,
        end_period: int,
) -> int:
    """Ver get_provider_count_in_range() -- misma lógica, filtro geográfico multi-select de Control."""
    territorio_sql, territorio_params = _lines_territory_clauses("f.geografia_id", provincias, cantones, parroquias)
    territorio_where = f"AND {territorio_sql}" if territorio_sql else ""
    params: dict[str, Any] = {"start_period": start_period, "end_period": end_period}
    params.update(territorio_params)
    df = _read(
        f"""
        SELECT COUNT(DISTINCT f.prestador_id) AS cantidad
        FROM mart.fact_lineas_geografia_mes f
        WHERE f.periodo_id BETWEEN :start_period AND :end_period
          AND f.tiene_reportado = TRUE
          {territorio_where}
        """,
        params,
    )
    if df.empty:
        return 0
    return int(df.iloc[0]["cantidad"])


@cache.memoize(timeout=300)
def get_reporting_summary_multiselect(
        provincias: tuple[str, ...],
        cantones: tuple[str, ...],
        parroquias: tuple[str, ...],
        start_period: int,
        end_period: int,
        opera_estados: tuple[str, ...] = (),
        isp_nombres: tuple[str, ...] = (),
        incluir_nunca_reportaron: bool = False,
) -> dict[str, float]:
    """
    Ver get_reporting_summary() -- misma lógica (incluida la regla del año
    de gracia y la fusión opcional con "nunca han reportado"), con el
    filtro geográfico multi-select de Control.

    CORRECCIÓN (14-ago-2026): la primera versión de esta función omitía
    por completo la fusión con incluir_nunca_reportaron -- confirmado en
    producción: con Control sin ningún territorio elegido (equivalente a
    "Nacional"), "Total de prestadores" mostraba 1.369 y Evolución (mismo
    filtro) mostraba 1.654 -- la diferencia exacta, 285, es el propio
    "Total" de la sección "Nunca han reportado" que ya existe más abajo
    en esta misma página. No es un cálculo distinto entre páginas, era
    lógica faltante. `incluir_nunca_reportaron` sigue sin exponerse como
    tarjeta KPI aparte en el bloque duplicado (esa decisión no cambia,
    Control ya tiene su propia sección con más detalle) -- solo se
    restaura su efecto en estos dos números, para que coincidan con
    Evolución bajo el mismo filtro.
    """
    territorio_sql, territorio_params = _lines_territory_clauses("f.geografia_id", provincias, cantones, parroquias)
    territorio_where = f"AND {territorio_sql}" if territorio_sql else ""

    clauses_registro = ["f.periodo_id <= :end_period"]
    clauses_nunca = ["1 = 1"]
    params: dict[str, Any] = {"start_period": start_period, "end_period": end_period}
    params.update(territorio_params)
    if opera_estados:
        clauses_registro.append(
            "EXISTS (SELECT 1 FROM unnest(:opera_estados ::text[]) AS estado "
            "WHERE p.opera_actual ILIKE '%' || estado || '%')"
        )
        clauses_nunca.append(
            "EXISTS (SELECT 1 FROM unnest(:opera_estados ::text[]) AS estado "
            "WHERE v.opera ILIKE '%' || estado || '%')"
        )
        params["opera_estados"] = list(opera_estados)
    if isp_nombres:
        clauses_registro.append("p.isp_nombre = ANY(:isp_nombres)")
        clauses_nunca.append("v.isp_nombre = ANY(:isp_nombres)")
        params["isp_nombres"] = list(isp_nombres)

    sql_nunca_reportaron = (
        "SELECT peva_codigo AS prestador_id, fechapermiso FROM mart.vw_prestadores_sin_reportar v WHERE 1 = 0"
    )
    if incluir_nunca_reportaron:
        sql_nunca_reportaron = (
            f"SELECT v.peva_codigo AS prestador_id, v.fechapermiso "
            f"FROM mart.vw_prestadores_sin_reportar v WHERE {' AND '.join(clauses_nunca)}"
        )

    df = _read(
        f"""
        WITH registro_total AS (
            SELECT DISTINCT f.prestador_id
            FROM mart.fact_lineas_geografia_mes f
            JOIN mart.dim_prestador p ON p.prestador_id = f.prestador_id
            WHERE {' AND '.join(clauses_registro)}
              {territorio_where}
              AND f.tiene_reportado = TRUE
        ),
        nunca_reportaron AS (
            {sql_nunca_reportaron}
        ),
        periodos_rango AS (
            SELECT periodo_id
            FROM mart.dim_periodo
            WHERE periodo_id BETWEEN :start_period AND :end_period
        ),
        prestador_con_obligacion AS (
            SELECT
                r.prestador_id,
                CASE
                    WHEN p.fechapermiso IS NULL THEN NULL
                    ELSE (
                        EXTRACT(YEAR FROM (p.fechapermiso + INTERVAL '1 year'))::int * 100
                        + EXTRACT(MONTH FROM (p.fechapermiso + INTERVAL '1 year'))::int
                    )
                END AS periodo_inicio_obligacion
            FROM registro_total r
            JOIN mart.dim_prestador p ON p.prestador_id = r.prestador_id
        ),
        nunca_con_obligacion AS (
            SELECT
                n.prestador_id,
                CASE
                    WHEN n.fechapermiso IS NULL THEN NULL
                    ELSE (
                        EXTRACT(YEAR FROM (n.fechapermiso + INTERVAL '1 year'))::int * 100
                        + EXTRACT(MONTH FROM (n.fechapermiso + INTERVAL '1 year'))::int
                    )
                END AS periodo_inicio_obligacion
            FROM nunca_reportaron n
        ),
        celdas_esperadas_calc AS (
            SELECT pco.prestador_id, pr.periodo_id
            FROM prestador_con_obligacion pco
            CROSS JOIN periodos_rango pr
            WHERE pco.periodo_inicio_obligacion IS NULL
               OR pr.periodo_id >= pco.periodo_inicio_obligacion
        ),
        celdas_esperadas_nunca AS (
            SELECT nco.prestador_id, pr.periodo_id
            FROM nunca_con_obligacion nco
            CROSS JOIN periodos_rango pr
            WHERE nco.periodo_inicio_obligacion IS NULL
               OR pr.periodo_id >= nco.periodo_inicio_obligacion
        ),
        reportes_reales AS (
            SELECT DISTINCT f.prestador_id, f.periodo_id
            FROM mart.fact_lineas_geografia_mes f
            WHERE f.periodo_id BETWEEN :start_period AND :end_period
              AND f.tiene_reportado = TRUE
              {territorio_where}
        )
        SELECT
            (SELECT COUNT(*) FROM registro_total) + (SELECT COUNT(*) FROM nunca_reportaron)
                AS total_prestadores,
            (SELECT COUNT(*) FROM celdas_esperadas_calc) + (SELECT COUNT(*) FROM celdas_esperadas_nunca)
                AS celdas_esperadas,
            (
                SELECT COUNT(*)
                FROM celdas_esperadas_calc cec
                JOIN reportes_reales rr
                  ON rr.prestador_id = cec.prestador_id AND rr.periodo_id = cec.periodo_id
            ) AS celdas_reportadas
        """,
        params,
    )

    if df.empty or df.iloc[0]["celdas_esperadas"] in (0, None):
        return {"total_prestadores": 0, "celdas_esperadas": 0, "celdas_reportadas": 0, "tasa_entrega_porcentaje": None}

    fila = df.iloc[0]
    tasa = (fila["celdas_reportadas"] / fila["celdas_esperadas"] * 100) if fila["celdas_esperadas"] else None
    return {
        "total_prestadores": int(fila["total_prestadores"]),
        "celdas_esperadas": int(fila["celdas_esperadas"]),
        "celdas_reportadas": int(fila["celdas_reportadas"]),
        "tasa_entrega_porcentaje": float(tasa) if tasa is not None else None,
    }


@cache.memoize(timeout=300)
def get_churn_history_multiselect(
        provincias: tuple[str, ...],
        cantones: tuple[str, ...],
        parroquias: tuple[str, ...],
        end_period: int,
        meses: int = 12,
) -> pd.DataFrame:
    """
    Ver get_churn_history() -- NO usa mart.vw_dashboard_participacion (ver
    docstring de esta sección, esa vista no es descomponible al filtro
    multi-select de Control). Recalcula "activo" directo desde
    mart.fact_lineas_geografia_mes, agregado por prestador y mes dentro
    del territorio elegido, mismo patrón que get_variacion_mensual_anomala.
    """
    meses = max(2, int(meses))
    territorio_sql, territorio_params = _lines_territory_clauses("f.geografia_id", provincias, cantones, parroquias)
    territorio_where = f"AND {territorio_sql}" if territorio_sql else ""
    params: dict[str, Any] = {"end_period": end_period}
    params.update(territorio_params)

    df = _read(
        f"""
        WITH ancla AS (
            SELECT periodo FROM mart.dim_periodo WHERE periodo_id = :end_period
        ),
        serie AS (
            SELECT
                f.periodo_id,
                f.prestador_id,
                (BOOL_OR(f.tiene_reportado) AND SUM(COALESCE(f.lineas_reportadas, 0)) > 0) AS activo
            FROM mart.fact_lineas_geografia_mes f, ancla
            WHERE f.periodo BETWEEN (ancla.periodo - INTERVAL '{meses} months') AND ancla.periodo
              {territorio_where}
            GROUP BY f.periodo_id, f.prestador_id
        ),
        con_lag AS (
            SELECT
                periodo_id, prestador_id, activo,
                LAG(activo) OVER (PARTITION BY prestador_id ORDER BY periodo_id) AS activo_anterior
            FROM serie
        )
        SELECT
            c.periodo_id,
            d.anio_mes,
            COUNT(*) FILTER (WHERE c.activo_anterior = TRUE AND c.activo = FALSE) AS churn
        FROM con_lag c
        JOIN mart.dim_periodo d ON d.periodo_id = c.periodo_id
        GROUP BY c.periodo_id, d.anio_mes
        ORDER BY c.periodo_id
        """,
        params,
    )
    return df


# ============================================================
# Puntos 2.6 y 9.6 del EDA (14-ago-2026): "Universo consolidado de
# incumplimiento activo" y "dependencia geográfica de prestador
# dominante ausente" -- información que hasta ahora solo existía en el
# notebook de análisis, sin ningún equivalente en el dashboard real.
# ============================================================

def get_universo_incumplimiento_consolidado(
        opera_estados: tuple[str, ...] = (),
        isp_nombres: tuple[str, ...] = (),
) -> dict[str, int]:
    """
    Suma "nunca han reportado, activos" (mismo criterio que Control/
    Evolución -- clasificacion_incumplimiento == 'activo_sin_reportar') +
    "reportaron y detuvieron, materialmente relevantes" -- sin
    solapamiento por construcción (mart.vw_prestadores_sin_reportar
    excluye por definición a cualquiera que aparezca en
    fact_lineas_geografia_mes).

    "Materialmente relevante" usa el MISMO umbral fijo del EDA (sección
    2.5), NO el "meses_minimo" ajustable de la sección "Reporte detenido"
    de Control -- es un criterio de materialidad deliberadamente distinto
    para este KPI ejecutivo específico: opera_actual == "Opera
    Normalmente", no cancelado, más de 100.000 cuentas en su historial, y
    al menos 3 meses sin reportar. Reproduce exactamente 104 + 18 = 122,
    verificado contra el propio EDA.
    """
    detalle_nunca = get_prestadores_nunca_reportaron_detalle(opera_estados, isp_nombres)
    nunca_reporto = int(
        (detalle_nunca["clasificacion_incumplimiento"] == "activo_sin_reportar").sum()
    ) if not detalle_nunca.empty else 0

    detenido = get_prestadores_reporte_detenido_detalle(
        3, opera_estados=opera_estados, isp_nombres=isp_nombres,
    )
    if not detenido.empty:
        historico = pd.to_numeric(detenido["total_lineas_historico"], errors="coerce")
        meses = pd.to_numeric(detenido["meses_desde_ultimo_reporte"], errors="coerce")
        relevantes = detenido[
            (detenido["opera_actual"] == "Opera Normalmente")
            & (~detenido["es_cancelado_actual"].astype(bool))
            & (historico > 100000)
            & (meses >= 3)
            ]
        reporto_y_detuvo = len(relevantes)
    else:
        reporto_y_detuvo = 0

    return {
        "nunca_reporto": nunca_reporto,
        "reporto_y_detuvo": reporto_y_detuvo,
        "total": nunca_reporto + reporto_y_detuvo,
    }


@cache.memoize(timeout=300)
def get_dependencia_geografica_dominante_ausente(periodo_id: int) -> pd.DataFrame:
    """
    Generaliza el caso CNT del EDA (sección 9.6, que hardcodeaba el
    nombre del prestador y el período '2024-06-01' encontrados a mano) a
    CUALQUIER prestador marcado prestador_dominante_ausente a nivel
    NACIONAL en el período dado -- para que la métrica siga siendo
    correcta si CNT retoma el reporte, o si en el futuro otro prestador
    cae en el mismo patrón.

    Por provincia: cuántas cuentas se reportan HOY (sin el/los prestador
    ausente, que por definición no está incluido), cuántas reportaba ESE
    prestador la última vez que sí reportó, y qué % de la suma de ambas
    representaría si volviera a reportar -- mismo cálculo que el EDA
    (ultimo_reporte / (lineas_reportadas + ultimo_reporte) * 100), sobre
    datos vivos, no un snapshot fijo en el código.

    Umbral de dominancia (>=30% de participación histórica a nivel
    NACIONAL) idéntico al que ya usa mart.fact_ihh_geografico -- no se
    reinventa aquí, se referencia la misma definición vigente en la base.
    """
    return _read(
        """
        WITH umbral_dominancia AS (
            SELECT DISTINCT prestador_id
            FROM mart.fact_participacion_mercado
            WHERE participacion_porcentaje >= 30 AND territorio_id = 'NACIONAL|ECUADOR'
        ),
        ausentes AS (
            SELECT ud.prestador_id
            FROM umbral_dominancia ud
            WHERE NOT EXISTS (
                SELECT 1 FROM mart.fact_participacion_mercado fpm
                WHERE fpm.periodo_id = :periodo_id AND fpm.territorio_id = 'NACIONAL|ECUADOR'
                  AND fpm.prestador_id = ud.prestador_id AND fpm.tiene_reportado
            )
        ),
        ultimo_periodo_ausente AS (
            SELECT a.prestador_id, MAX(fpm.periodo_id) AS ultimo_periodo_con_reporte
            FROM ausentes a
            JOIN mart.fact_participacion_mercado fpm
              ON fpm.prestador_id = a.prestador_id AND fpm.territorio_id = 'NACIONAL|ECUADOR'
             AND fpm.tiene_reportado
            WHERE fpm.periodo_id < :periodo_id
            GROUP BY a.prestador_id
        ),
        huella_ausente AS (
            SELECT g.pro_nombre AS provincia, SUM(f.lineas_reportadas) AS cuentas_ausente
            FROM ultimo_periodo_ausente u
            JOIN mart.fact_lineas_geografia_mes f
              ON f.prestador_id = u.prestador_id AND f.periodo_id = u.ultimo_periodo_con_reporte
            JOIN mart.dim_geografia g ON g.geografia_id = f.geografia_id
            GROUP BY g.pro_nombre
        ),
        totales_actuales AS (
            SELECT g.pro_nombre AS provincia, SUM(f.lineas_reportadas) AS cuentas_actuales
            FROM mart.fact_lineas_geografia_mes f
            JOIN mart.dim_geografia g ON g.geografia_id = f.geografia_id
            WHERE f.periodo_id = :periodo_id AND f.tiene_reportado = TRUE
            GROUP BY g.pro_nombre
        )
        SELECT
            COALESCE(t.provincia, h.provincia) AS provincia,
            COALESCE(t.cuentas_actuales, 0) AS cuentas_actuales,
            COALESCE(h.cuentas_ausente, 0) AS cuentas_ausente,
            CASE
                WHEN (COALESCE(t.cuentas_actuales, 0) + COALESCE(h.cuentas_ausente, 0)) > 0
                THEN ROUND(
                    100.0 * COALESCE(h.cuentas_ausente, 0)
                    / (COALESCE(t.cuentas_actuales, 0) + COALESCE(h.cuentas_ausente, 0)), 1
                )
                ELSE 0
            END AS pct_potencial_subestimado
        FROM totales_actuales t
        FULL OUTER JOIN huella_ausente h ON h.provincia = t.provincia
        WHERE COALESCE(h.cuentas_ausente, 0) > 0
        ORDER BY pct_potencial_subestimado DESC
        """,
        {"periodo_id": periodo_id},
    )
