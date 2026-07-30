"""dashboard/pages/evolucion.py — Evolución del mercado: líneas, prestadores, velocidades."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html, register_page

from components.territory_filters import register_territory_callbacks, territory_filter_layout
from components.ui import (
    PALETTE,
    chart_card,
    empty_figure,
    error_panel,
    format_number,
    format_signed,
    kpi_card,
    page_header,
    style_figure,
)
from services.queries import (
    get_evolution_filtrado,
    get_operation_states,
    get_participation,
    get_periods,
    get_provider_count_in_range,
    get_provider_options,
    get_velocities,
    resolve_period_id,
)

register_page(__name__, path="/", name="Evolución", order=0)
PREFIX = "evo"


def _period_configuration():
    periods = get_periods()
    if periods.empty:
        raise RuntimeError("mart.dim_periodo no contiene registros.")
    min_row = periods.loc[periods["periodo_id"].idxmin()]
    max_row = periods.loc[periods["periodo_id"].idxmax()]
    min_date = str(pd.Timestamp(min_row["periodo"]).date())
    max_date = str(pd.Timestamp(max_row["periodo"]).date())
    return min_date, max_date


def layout():
    try:
        min_date, max_date = _period_configuration()
    except Exception as exc:
        return html.Div([page_header("Evolución del mercado", ""), error_panel(str(exc))])

    estados_operacion = get_operation_states()

    return html.Div(
        children=[
            page_header(
                "Evolución del mercado",
                "Líneas reportadas, prestadores y cambios en la composición por velocidad.",
            ),
            html.Section(
                className="filter-panel",
                children=[
                    territory_filter_layout(PREFIX),
                    html.Div(
                        className="period-grid four-periods",
                        children=[
                            html.Div(
                                className="filter-field",
                                children=[
                                    html.Label("Desde"),
                                    dcc.DatePickerSingle(
                                        id="evo-start-period",
                                        min_date_allowed=min_date,
                                        max_date_allowed=max_date,
                                        initial_visible_month=min_date,
                                        date=min_date,
                                        display_format="YYYY-MM",
                                        clearable=False,
                                    ),
                                ],
                            ),
                            html.Div(
                                className="filter-field",
                                children=[
                                    html.Label("Hasta"),
                                    dcc.DatePickerSingle(
                                        id="evo-end-period",
                                        min_date_allowed=min_date,
                                        max_date_allowed=max_date,
                                        initial_visible_month=max_date,
                                        date=max_date,
                                        display_format="YYYY-MM",
                                        clearable=False,
                                    ),
                                ],
                            ),
                            html.Div(
                                className="filter-field",
                                children=[
                                    html.Label("Estado de operación"),
                                    dcc.Dropdown(
                                        id="evo-opera-estado",
                                        options=estados_operacion,
                                        value=[],
                                        multi=True,
                                        placeholder="Todos",
                                    ),
                                ],
                            ),
                            html.Div(
                                className="filter-field",
                                children=[
                                    html.Label("Prestador"),
                                    dcc.Dropdown(
                                        id="evo-isp-nombre",
                                        options=[],
                                        value=[],
                                        multi=True,
                                        placeholder="Todos",
                                    ),
                                ],
                            ),
                        ],
                    ),
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
            html.Div(id="evo-message", className="data-message"),
            html.H3(id="evo-titulo-estado-actual", children="Estado actual"),
            html.Section(
                className="kpi-grid four",
                children=[
                    kpi_card("Líneas reportadas (último período)", "evo-kpi-lines", "evo-kpi-lines-note"),
                    kpi_card("Prestadores que reportaron", "evo-kpi-providers", "evo-kpi-providers-note"),
                    kpi_card("Cambio mensual (reportadas)", "evo-kpi-change", "evo-kpi-change-note"),
                    kpi_card("Dejaron de reportar este mes", "evo-kpi-churn", "evo-kpi-churn-note"),
                ],
            ),
            html.H3(id="evo-titulo-resumen-rango", children="Resumen del rango seleccionado"),
            html.Section(
                className="kpi-grid one",
                children=[
                    kpi_card("Prestadores con actividad en el rango", "evo-kpi-rango-prestadores",
                             "evo-kpi-rango-prestadores-note"),
                ],
            ),
            html.Section(
                className="chart-grid two",
                children=[
                    chart_card("Líneas reportadas por mes", "evo-lines-chart",
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


@callback(
    Output("evo-isp-nombre", "options"),
    Input("evo-territory-id", "data"),
)
def update_provider_filter_options(territory_id: str):
    if not territory_id:
        return []
    return get_provider_options(territory_id)


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
    Input("evo-territory-id", "data"),
    Input("evo-start-period", "date"),
    Input("evo-end-period", "date"),
    Input("evo-speed-type", "value"),
    Input("evo-opera-estado", "value"),
    Input("evo-isp-nombre", "value"),
)
def update_evolution(
        territory_id: str,
        start_date: str,
        end_date: str,
        speed_type: str,
        opera_estados: list[str] | None,
        isp_nombres: list[str] | None,
):
    start_period = resolve_period_id(start_date)
    end_period = resolve_period_id(end_date)
    opera_estados = opera_estados or []
    isp_nombres = isp_nombres or []

    if not territory_id or start_period is None or end_period is None:
        figures = [empty_figure("Seleccione todos los filtros") for _ in range(4)]
        return ("—", "", "—", "", "—", "", "—", "", *figures, "", "Estado actual",
                "Resumen del rango seleccionado", "—", "")

    start_period, end_period = sorted((int(start_period), int(end_period)))

    try:
        evolution = get_evolution_filtrado(territory_id, start_period, end_period, opera_estados, isp_nombres)
        velocities = get_velocities(territory_id, start_period, end_period, speed_type, opera_estados, isp_nombres)
    except Exception as exc:
        figures = [empty_figure("Error al consultar PostgreSQL") for _ in range(4)]
        return ("—", "", "—", "", "—", "", "—", "", *figures, str(exc), "Estado actual",
                "Resumen del rango seleccionado", "—", "")

    if evolution.empty:
        figures = [empty_figure() for _ in range(4)]
        return ("—", "", "—", "", "—", "", "—", "", *figures,
                "No existen datos para este territorio, período y filtros seleccionados.",
                "Estado actual", "Resumen del rango seleccionado", "—", "")

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

    # "Prestadores que reportaron" -- CORRECCIÓN (30-jul-2026, tras
    # discusión con el usuario): antes existían dos números que parecían
    # contradecirse ("246 con líneas" vs "238 reportaron"), porque "con
    # líneas" incluía prestadores 100% imputados (con total_lineas > 0
    # heredado por LOCF, pero sin ningún reporte real ese mes). Ahora solo
    # existe UN conteo de prestadores: los que reportaron de verdad. Nada
    # de imputados, ni como categoría de desglose.
    providers_value = format_number(latest.get("numero_prestadores"))
    providers_note = f"Con reporte real en {latest_label}"

    change_value = format_signed(latest.get("diferencia_mensual_lineas"))
    change_note = f"{format_signed(latest.get('variacion_mensual_porcentaje'), 2, '%')} respecto al mes anterior (sobre reportadas)"

    # "Dejaron de reportar este mes": prestadores con líneas positivas en el
    # período anterior que ya NO aparecen en el último. periodo_id se
    # codifica como anio*100+mes -- se usa aritmética de fecha real
    # (no periodo_id - 1) para hallar el mes anterior correctamente en
    # cualquier enero (ver auditoría completa, 29-jul-2026).
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

    # Gráfico de barras -- SOLO reportadas (dato real). No se muestra el
    # total mezclado con imputados ni una serie de "imputadas" por
    # separado: cuando un prestador grande deja de reportar, mostrar un
    # numero "imputado" sugiere una falsa precisión sobre algo que en
    # realidad no se sabe. La caída en la barra es la señal honesta.
    lines_fig = px.bar(
        evolution, x="periodo", y="lineas_reportadas",
        labels={"lineas_reportadas": "Líneas reportadas", "periodo": "Período"},
    )
    lines_fig.update_traces(marker_color=PALETTE["blue"])
    style_figure(lines_fig, hovermode="x unified")
    lines_fig.update_yaxes(title="Líneas reportadas", tickformat=",")

    providers_fig = go.Figure()
    providers_fig.add_trace(
        go.Scatter(
            x=evolution["periodo"], y=evolution["numero_prestadores"], mode="lines+markers",
            name="Prestadores que reportaron", line={"color": PALETTE["blue"], "width": 3},
        )
    )
    style_figure(providers_fig)
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
            labels={"total_lineas": "Líneas", "periodo": "Período", "rango_velocidad": "Rango"},
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

    return (
        lines_value, lines_note,
        providers_value, providers_note,
        change_value, change_note,
        churn_value, churn_note,
        lines_fig, providers_fig, speed_comp_fig, speed_diff_fig,
        message,
        titulo_estado_actual, titulo_resumen_rango,
        rango_prestadores_value, rango_prestadores_note,
    )
