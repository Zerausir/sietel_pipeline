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
from services.queries import get_evolution, get_periods, get_velocities

register_page(__name__, path="/", name="Evolución", order=0)
PREFIX = "evo"


def _period_configuration():
    periods = get_periods()
    if periods.empty:
        raise RuntimeError("mart.dim_periodo no contiene registros.")
    options = [{"label": row.anio_mes, "value": int(row.periodo_id)} for row in periods.itertuples()]
    return options, int(periods.periodo_id.min()), int(periods.periodo_id.max())


def layout():
    try:
        period_options, min_period, max_period = _period_configuration()
    except Exception as exc:
        return html.Div([page_header("Evolución del mercado", ""), error_panel(str(exc))])

    return html.Div(
        children=[
            page_header(
                "Evolución del mercado",
                "Líneas, prestadores y cambios en la composición por velocidad.",
            ),
            html.Section(
                className="filter-panel",
                children=[
                    territory_filter_layout(PREFIX),
                    html.Div(
                        className="period-grid",
                        children=[
                            html.Div(
                                className="filter-field",
                                children=[
                                    html.Label("Desde"),
                                    dcc.Dropdown(
                                        id="evo-start-period", options=period_options,
                                        value=min_period, clearable=False,
                                    ),
                                ],
                            ),
                            html.Div(
                                className="filter-field",
                                children=[
                                    html.Label("Hasta"),
                                    dcc.Dropdown(
                                        id="evo-end-period", options=period_options,
                                        value=max_period, clearable=False,
                                    ),
                                ],
                            ),
                            html.Div(
                                className="filter-field",
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
                ],
            ),
            html.Div(id="evo-message", className="data-message"),
            html.Section(
                className="kpi-grid four",
                children=[
                    kpi_card("Líneas en el último período", "evo-kpi-lines", "evo-kpi-lines-note"),
                    kpi_card("Prestadores presentes", "evo-kpi-providers", "evo-kpi-providers-note"),
                    kpi_card("Cambio mensual de líneas", "evo-kpi-change", "evo-kpi-change-note"),
                    kpi_card("Información imputada", "evo-kpi-imputed", "evo-kpi-imputed-note"),
                ],
            ),
            html.Section(
                className="chart-grid two",
                children=[
                    chart_card("Evolución de líneas", "evo-lines-chart", "Total de líneas y proporción reportada/imputada."),
                    chart_card("Evolución de prestadores", "evo-providers-chart", "Prestadores presentes y prestadores con líneas positivas."),
                    chart_card("Composición por velocidad", "evo-speed-composition-chart", "Distribución mensual por rango de velocidad."),
                    chart_card("Diferencia mensual por velocidad", "evo-speed-difference-chart", "Cambio absoluto frente al mes anterior para el último período visible."),
                ],
            ),
        ]
    )


register_territory_callbacks(PREFIX)


@callback(
    Output("evo-kpi-lines", "children"),
    Output("evo-kpi-lines-note", "children"),
    Output("evo-kpi-providers", "children"),
    Output("evo-kpi-providers-note", "children"),
    Output("evo-kpi-change", "children"),
    Output("evo-kpi-change-note", "children"),
    Output("evo-kpi-imputed", "children"),
    Output("evo-kpi-imputed-note", "children"),
    Output("evo-lines-chart", "figure"),
    Output("evo-providers-chart", "figure"),
    Output("evo-speed-composition-chart", "figure"),
    Output("evo-speed-difference-chart", "figure"),
    Output("evo-message", "children"),
    Input("evo-territory-id", "data"),
    Input("evo-start-period", "value"),
    Input("evo-end-period", "value"),
    Input("evo-speed-type", "value"),
)
def update_evolution(territory_id: str, start_period: int, end_period: int, speed_type: str):
    if not territory_id or start_period is None or end_period is None:
        figures = [empty_figure("Seleccione todos los filtros") for _ in range(4)]
        return ("—", "", "—", "", "—", "", "—", "", *figures, "")

    start_period, end_period = sorted((int(start_period), int(end_period)))

    try:
        evolution = get_evolution(territory_id, start_period, end_period)
        velocities = get_velocities(territory_id, start_period, end_period, speed_type)
    except Exception as exc:
        figures = [empty_figure("Error al consultar PostgreSQL") for _ in range(4)]
        return ("—", "", "—", "", "—", "", "—", "", *figures, str(exc))

    if evolution.empty:
        figures = [empty_figure() for _ in range(4)]
        return ("—", "", "—", "", "—", "", "—", "", *figures, "No existen datos para este territorio y período.")

    evolution = evolution.copy()
    evolution["periodo"] = pd.to_datetime(evolution["periodo"])
    numeric_columns = [
        "total_lineas", "lineas_reportadas", "lineas_imputadas",
        "numero_prestadores", "numero_prestadores_con_lineas", "numero_prestadores_sin_dato",
        "diferencia_mensual_lineas", "variacion_mensual_porcentaje", "porcentaje_imputado",
    ]
    for column in numeric_columns:
        if column in evolution:
            evolution[column] = pd.to_numeric(evolution[column], errors="coerce")

    latest = evolution.sort_values("periodo_id").iloc[-1]
    latest_label = str(latest.get("anio_mes", ""))

    lines_value = format_number(latest.get("total_lineas"))
    lines_note = f"Período {latest_label}"
    providers_value = format_number(latest.get("numero_prestadores"))
    providers_note = (
        f"{format_number(latest.get('numero_prestadores_con_lineas'))} con líneas · "
        f"{format_number(latest.get('numero_prestadores_sin_dato'))} sin dato"
    )
    change_value = format_signed(latest.get("diferencia_mensual_lineas"))
    change_note = f"{format_signed(latest.get('variacion_mensual_porcentaje'), 2, '%')} respecto al mes anterior"
    imputed_value = (
        f"{format_number(latest.get('porcentaje_imputado'), 2)}%"
        if pd.notna(latest.get("porcentaje_imputado")) else "—"
    )
    imputed_note = f"{format_number(latest.get('lineas_imputadas'))} líneas imputadas"

    lines_fig = go.Figure()
    lines_fig.add_trace(
        go.Scatter(
            x=evolution["periodo"], y=evolution["total_lineas"], mode="lines+markers",
            name="Total de líneas", line={"color": PALETTE["blue"], "width": 3},
        )
    )
    if "lineas_reportadas" in evolution:
        lines_fig.add_trace(
            go.Scatter(
                x=evolution["periodo"], y=evolution["lineas_reportadas"], mode="lines",
                name="Reportadas", line={"color": PALETTE["teal"], "width": 2, "dash": "dot"},
            )
        )
    if "lineas_imputadas" in evolution:
        lines_fig.add_trace(
            go.Scatter(
                x=evolution["periodo"], y=evolution["lineas_imputadas"], mode="lines",
                name="Imputadas", line={"color": PALETTE["orange"], "width": 2, "dash": "dash"},
            )
        )
    style_figure(lines_fig)
    lines_fig.update_yaxes(title="Número de líneas", tickformat=",")

    providers_fig = go.Figure()
    providers_fig.add_trace(
        go.Scatter(
            x=evolution["periodo"], y=evolution["numero_prestadores"], mode="lines+markers",
            name="Prestadores presentes", line={"color": PALETTE["blue"], "width": 3},
        )
    )
    providers_fig.add_trace(
        go.Scatter(
            x=evolution["periodo"], y=evolution["numero_prestadores_con_lineas"], mode="lines+markers",
            name="Con líneas positivas", line={"color": PALETTE["cyan"], "width": 2},
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

    message = f"Territorio: {latest.get('nombre_geografico', territory_id)} · Último período visible: {latest_label}"

    return (
        lines_value, lines_note,
        providers_value, providers_note,
        change_value, change_note,
        imputed_value, imputed_note,
        lines_fig, providers_fig, speed_comp_fig, speed_diff_fig,
        message,
    )
