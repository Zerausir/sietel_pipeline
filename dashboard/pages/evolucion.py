"""dashboard/pages/evolucion.py — Evolución del mercado: cuentas, prestadores, velocidades."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html, register_page

from components.filters_shared import register_shared_filters_callbacks, shared_filters_layout
from components.territory_filters import register_territory_callbacks, territory_filter_layout
from components.ui import (
    PALETTE,
    chart_card,
    empty_figure,
    error_panel,
    filters_summary_bar,
    format_number,
    format_signed,
    kpi_card,
    month_year_picker,
    page_header,
    register_filters_summary_callback,
    register_month_year_picker_callback,
    style_figure,
)
from services.queries import (
    get_evolution_filtrado,
    get_participation,
    get_periods,
    get_prestadores_sin_reportar,
    get_provider_count_in_range,
    get_reporting_summary,
    get_velocities,
    resolve_period_id,
)

register_page(__name__, path="/sai/evolucion", name="Evolución", order=1)
PREFIX = "evo"


def _period_options():
    periods = get_periods()
    if periods.empty:
        raise RuntimeError("mart.dim_periodo no contiene registros.")
    options = [{"label": row.anio_mes, "value": int(row.periodo_id)} for row in periods.itertuples()]
    min_period = int(periods["periodo_id"].min())
    max_period = int(periods["periodo_id"].max())
    return options, min_period, max_period


def layout():
    try:
        _, min_period, max_period = _period_options()
    except Exception as exc:
        return html.Div([page_header("Evolución del mercado", ""), error_panel(str(exc))])

    return html.Div(
        children=[
            page_header(
                "Evolución del mercado",
                "Cuentas reportadas, prestadores y cambios en la composición por velocidad.",
            ),
            html.Section(
                className="filter-panel",
                children=[
                    territory_filter_layout(PREFIX),
                    html.Div(
                        className="period-grid four-periods",
                        children=[
                            month_year_picker("evo-start-period", "Desde", min_period, min_period, max_period),
                            month_year_picker("evo-end-period", "Hasta", max_period, min_period, max_period),
                        ],
                    ),
                    shared_filters_layout(PREFIX),
                    html.Div(
                        className="filter-field",
                        style={"marginTop": "14px", "maxWidth": "260px"},
                        children=[
                            html.Label("Velocidad"),
                            dcc.RadioItems(
                                id="evo-speed-type",
                                options=[
                                    {"label": "Descarga", "value": "DESCARGA"},
                                    {"label": "Subida", "value": "SUBIDA"},
                                ],
                                value="DESCARGA",
                                inline=True,
                                className="radio-group",
                            ),
                        ],
                    ),
                ],
            ),
            filters_summary_bar("evo-filters-summary"),
            html.Div(id="evo-message", className="data-message"),
            html.H3(id="evo-titulo-estado-actual", children="Estado actual"),
            html.Section(
                className="kpi-grid four",
                children=[
                    kpi_card("Cuentas reportadas (último período)", "evo-kpi-lines", "evo-kpi-lines-note"),
                    kpi_card("Prestadores que reportaron", "evo-kpi-providers", "evo-kpi-providers-note"),
                    kpi_card("Cambio mensual (reportadas)", "evo-kpi-change", "evo-kpi-change-note"),
                    kpi_card("Dejaron de reportar este mes", "evo-kpi-churn", "evo-kpi-churn-note"),
                ],
            ),
            html.H3(id="evo-titulo-resumen-rango", children="Resumen del rango seleccionado"),
            html.Section(
                className="kpi-grid four",
                children=[
                    kpi_card("Prestadores con actividad en el rango", "evo-kpi-rango-prestadores",
                             "evo-kpi-rango-prestadores-note"),
                    kpi_card("Total de prestadores (con o sin reportes)", "evo-kpi-rango-total",
                             "evo-kpi-rango-total-note"),
                    kpi_card("Tasa de entrega de reportes", "evo-kpi-rango-tasa",
                             "evo-kpi-rango-tasa-note"),
                    kpi_card("Nunca han reportado", "evo-kpi-nunca-reportaron",
                             "evo-kpi-nunca-reportaron-note"),
                ],
            ),
            html.Section(
                className="chart-grid two",
                children=[
                    chart_card("Cuentas reportadas por mes", "evo-lines-chart",
                               "Solo datos reales (reportados) -- no incluye relleno interior (imputado)."),
                    chart_card("Prestadores que reportaron", "evo-providers-chart",
                               "Cantidad de prestadores con al menos un reporte real cada mes."),
                    chart_card("Composición por velocidad", "evo-speed-composition-chart",
                               "Distribución mensual por rango de velocidad."),
                    chart_card("Diferencia mensual por velocidad", "evo-speed-difference-chart",
                               "Cambio absoluto frente al mes anterior para el último período visible."),
                ],
            ),
        ]
    )


register_territory_callbacks(PREFIX)
register_shared_filters_callbacks(PREFIX)
register_month_year_picker_callback("evo-start-period")
register_month_year_picker_callback("evo-end-period")
register_filters_summary_callback(PREFIX)


@callback(
    Output("evo-kpi-lines", "children"),
    Output("evo-kpi-lines-note", "children"),
    Output("evo-kpi-providers", "children"),
    Output("evo-kpi-providers-note", "children"),
    Output("evo-kpi-change", "children"),
    Output("evo-kpi-change-note", "children"),
    Output("evo-kpi-churn", "children"),
    Output("evo-kpi-churn-note", "children"),
    Output("evo-lines-chart", "figure"),
    Output("evo-providers-chart", "figure"),
    Output("evo-speed-composition-chart", "figure"),
    Output("evo-speed-difference-chart", "figure"),
    Output("evo-message", "children"),
    Output("evo-titulo-estado-actual", "children"),
    Output("evo-titulo-resumen-rango", "children"),
    Output("evo-kpi-rango-prestadores", "children"),
    Output("evo-kpi-rango-prestadores-note", "children"),
    Output("evo-kpi-rango-total", "children"),
    Output("evo-kpi-rango-total-note", "children"),
    Output("evo-kpi-rango-tasa", "children"),
    Output("evo-kpi-rango-tasa-note", "children"),
    Output("evo-kpi-nunca-reportaron", "children"),
    Output("evo-kpi-nunca-reportaron-note", "children"),
    Input("evo-territory-id", "data"),
    Input("evo-start-period", "data"),
    Input("evo-end-period", "data"),
    Input("evo-speed-type", "value"),
    Input("evo-opera-estado", "value"),
    Input("evo-isp-nombre", "value"),
)
def update_evolution(
        territory_id: str,
        start_period: int | None,
        end_period: int | None,
        speed_type: str,
        opera_estados: list[str] | None,
        isp_nombres: list[str] | None,
):
    opera_estados = opera_estados or []
    isp_nombres = isp_nombres or []

    if not territory_id or start_period is None or end_period is None:
        figures = [empty_figure("Seleccione todos los filtros") for _ in range(4)]
        return ("—", "", "—", "", "—", "", "—", "", *figures, "", "Estado actual",
                "Resumen del rango seleccionado", "—", "", "—", "", "—", "", "—", "")

    start_period, end_period = sorted((int(start_period), int(end_period)))

    try:
        evolution = get_evolution_filtrado(territory_id, start_period, end_period, opera_estados, isp_nombres)
        velocities = get_velocities(territory_id, start_period, end_period, speed_type, opera_estados, isp_nombres)
    except Exception as exc:
        figures = [empty_figure("Error al consultar PostgreSQL") for _ in range(4)]
        return ("—", "", "—", "", "—", "", "—", "", *figures, str(exc), "Estado actual",
                "Resumen del rango seleccionado", "—", "", "—", "", "—", "", "—", "")

    if evolution.empty:
        figures = [empty_figure() for _ in range(4)]
        return ("—", "", "—", "", "—", "", "—", "", *figures,
                "No existen datos para este territorio, período y filtros seleccionados.",
                "Estado actual", "Resumen del rango seleccionado", "—", "", "—", "", "—", "", "—", "")

    evolution = evolution.copy()
    evolution["periodo"] = pd.to_datetime(evolution["periodo"])
    numeric_columns = [
        "total_lineas", "lineas_reportadas", "numero_prestadores",
        "diferencia_mensual_lineas", "variacion_mensual_porcentaje",
    ]
    for column in numeric_columns:
        if column in evolution:
            evolution[column] = pd.to_numeric(evolution[column], errors="coerce")

    latest = evolution.sort_values("periodo_id").iloc[-1]
    latest_label = str(latest.get("anio_mes", ""))

    lines_value = format_number(latest.get("lineas_reportadas"))
    lines_note = f"Período {latest_label}"

    providers_value = format_number(latest.get("numero_prestadores"))
    providers_note = f"Con reporte real en {latest_label}"

    change_value = format_signed(latest.get("diferencia_mensual_lineas"))
    change_note = f"{format_signed(latest.get('variacion_mensual_porcentaje'), 2, '%')} respecto al mes anterior (sobre reportadas)"

    # "Dejaron de reportar este mes": prestadores con líneas positivas en el
    # período anterior que ya NO aparecen en el último. periodo_id se
    # codifica como anio*100+mes -- se usa aritmética de fecha real
    # (no periodo_id - 1) para hallar el mes anterior correctamente en
    # cualquier enero.
    churn_value, churn_note = "—", ""
    try:
        periodo_actual_id = int(latest["periodo_id"])
        fecha_mes_anterior = (latest["periodo"] - pd.DateOffset(months=1)).date().isoformat()
        periodo_anterior_id = resolve_period_id(fecha_mes_anterior)
        actuales = get_participation(territory_id, periodo_actual_id)
        anteriores = get_participation(territory_id,
                                       periodo_anterior_id) if periodo_anterior_id is not None else pd.DataFrame()
        if not actuales.empty and not anteriores.empty:
            activos_anterior = set(
                anteriores.loc[
                    pd.to_numeric(anteriores["total_lineas_prestador"], errors="coerce").fillna(0) > 0, "prestador_id"]
            )
            activos_actual = set(
                actuales.loc[
                    pd.to_numeric(actuales["total_lineas_prestador"], errors="coerce").fillna(0) > 0, "prestador_id"]
            )
            desaparecieron = activos_anterior - activos_actual
            churn_value = format_number(len(desaparecieron))
            churn_note = f"De {format_number(len(activos_anterior))} activos en el mes anterior"
    except Exception:
        churn_value, churn_note = "—", "No se pudo calcular"

    lines_fig = px.bar(
        evolution, x="periodo", y="lineas_reportadas",
        labels={"lineas_reportadas": "Cuentas reportadas", "periodo": "Período"},
    )
    lines_fig.update_traces(marker_color=PALETTE["blue"])
    style_figure(lines_fig, hovermode="x unified")
    lines_fig.update_yaxes(title="Cuentas reportadas", tickformat=",")

    providers_fig = px.bar(
        evolution, x="periodo", y="numero_prestadores",
        labels={"numero_prestadores": "Prestadores que reportaron", "periodo": "Período"},
    )
    providers_fig.update_traces(marker_color=PALETTE["blue"])
    style_figure(providers_fig, hovermode="x unified")
    providers_fig.update_yaxes(title="Prestadores", rangemode="tozero")

    if velocities.empty:
        speed_comp_fig = empty_figure("No existen datos de velocidad")
        speed_diff_fig = empty_figure("No existen diferencias de velocidad")
    else:
        velocities = velocities.copy()
        velocities["periodo"] = pd.to_datetime(velocities["periodo"])
        velocities["total_lineas"] = pd.to_numeric(velocities["total_lineas"], errors="coerce").fillna(0)
        velocities["diferencia_mensual"] = pd.to_numeric(velocities["diferencia_mensual"], errors="coerce")

        speed_comp_fig = px.area(
            velocities, x="periodo", y="total_lineas", color="rango_velocidad",
            category_orders={
                "rango_velocidad": velocities.sort_values("orden_rango")["rango_velocidad"].drop_duplicates().tolist()
            },
            labels={"total_lineas": "Cuentas", "periodo": "Período", "rango_velocidad": "Rango"},
        )
        style_figure(speed_comp_fig)
        speed_comp_fig.update_yaxes(tickformat=",")

        latest_speed_period = velocities["periodo_id"].max()
        latest_speed = velocities[velocities["periodo_id"] == latest_speed_period].sort_values("orden_rango")
        speed_diff_fig = go.Figure(
            go.Bar(
                x=latest_speed["rango_velocidad"], y=latest_speed["diferencia_mensual"],
                marker_color=[
                    PALETTE["teal"] if pd.notna(value) and value >= 0 else PALETTE["red"]
                    for value in latest_speed["diferencia_mensual"]
                ],
                hovertemplate="%{x}<br>Diferencia: %{y:,.0f}<extra></extra>",
            )
        )
        style_figure(speed_diff_fig, hovermode="closest")
        speed_diff_fig.update_xaxes(tickangle=-25)
        speed_diff_fig.update_yaxes(title="Diferencia mensual", tickformat=",")

    filtros_txt = []
    if opera_estados:
        filtros_txt.append(f"Estado: {', '.join(opera_estados)}")
    if isp_nombres:
        filtros_txt.append(f"Prestador: {', '.join(isp_nombres)}")
    filtros_sufijo = f" · Filtros: {'; '.join(filtros_txt)}" if filtros_txt else ""
    message = f"Territorio: {territory_id} · Último período visible: {latest_label}{filtros_sufijo}"

    titulo_estado_actual = f"Estado actual — {latest_label}"

    primero = evolution.sort_values("periodo_id").iloc[0]
    rango_desde_label = str(primero.get("anio_mes", ""))
    rango_hasta_label = latest_label
    titulo_resumen_rango = f"Resumen del rango seleccionado — {rango_desde_label} a {rango_hasta_label}"

    try:
        cantidad_rango = get_provider_count_in_range(territory_id, start_period, end_period)
        rango_prestadores_value = format_number(cantidad_rango)
        rango_prestadores_note = (
            f"Con al menos un reporte real entre {rango_desde_label} y {rango_hasta_label}. "
            "En rangos amplios (varios años), este número tiende a coincidir con el total de "
            "prestadores presentes -- casi todos tienen al menos un reporte real en algún punto. "
            "No equivale a título habilitante vigente."
        )
    except Exception:
        rango_prestadores_value, rango_prestadores_note = "—", "No se pudo calcular"

    incluir_nunca = territory_id == "NACIONAL|ECUADOR"
    try:
        resumen = get_reporting_summary(
            territory_id, start_period, end_period, opera_estados, isp_nombres,
            incluir_nunca_reportaron=incluir_nunca,
        )
        rango_total_value = format_number(resumen["total_prestadores"])
        if incluir_nunca:
            rango_total_note = (
                f"Con o sin reportes (incluye a quienes nunca han reportado), "
                f"registrados hasta {rango_hasta_label}."
            )
        else:
            rango_total_note = (
                f"Con al menos un reporte real, registrados hasta {rango_hasta_label}. "
                "No incluye a quienes nunca han reportado -- ese dato solo existe a nivel Nacional."
            )

        tasa = resumen["tasa_entrega_porcentaje"]
        rango_tasa_value = f"{format_number(tasa, 1)}%" if tasa is not None else "—"
        if incluir_nunca:
            rango_tasa_note = (
                f"{format_number(resumen['celdas_reportadas'])} de {format_number(resumen['celdas_esperadas'])} "
                "meses-prestador con reporte real, contados desde que cumplen un año del título "
                "habilitante. INCLUYE a quienes nunca han reportado ni una sola vez -- aportan "
                "meses esperados sin ningún mes entregado, arrastrando la tasa hacia abajo."
            )
        else:
            rango_tasa_note = (
                f"{format_number(resumen['celdas_reportadas'])} de {format_number(resumen['celdas_esperadas'])} "
                "meses-prestador con reporte real, contados desde que cumplen un año del título "
                "habilitante. No incluye a quienes nunca han reportado -- ese dato solo existe a "
                "nivel Nacional."
            )
    except Exception:
        rango_total_value, rango_total_note = "—", "No se pudo calcular"
        rango_tasa_value, rango_tasa_note = "—", "No se pudo calcular"

    if territory_id == "NACIONAL|ECUADOR":
        try:
            nunca_reportaron_value = format_number(get_prestadores_sin_reportar(opera_estados, isp_nombres))
            nunca_reportaron_note = (
                "Título habilitante otorgado, cero reportes en toda su historia. "
                "Solo disponible a nivel Nacional -- SIETEL no registra la geografía "
                "de un prestador que nunca llegó a reportar."
            )
        except Exception:
            nunca_reportaron_value, nunca_reportaron_note = "—", "No se pudo calcular"
    else:
        nunca_reportaron_value = "Sin datos disponibles"
        nunca_reportaron_note = "Este indicador solo existe a nivel Nacional -- cambie el Nivel geográfico para verlo."

    return (
        lines_value, lines_note,
        providers_value, providers_note,
        change_value, change_note,
        churn_value, churn_note,
        lines_fig, providers_fig, speed_comp_fig, speed_diff_fig,
        message,
        titulo_estado_actual, titulo_resumen_rango,
        rango_prestadores_value, rango_prestadores_note,
        rango_total_value, rango_total_note,
        rango_tasa_value, rango_tasa_note,
        nunca_reportaron_value, nunca_reportaron_note,
    )
