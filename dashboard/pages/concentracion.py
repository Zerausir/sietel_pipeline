"""dashboard/pages/concentracion.py — IHH, participación y concentración de mercado."""
from __future__ import annotations

import dash_ag_grid as dag
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html, register_page

from components.territory_filters import register_territory_callbacks, territory_filter_layout
from components.ui import (
    PALETTE,
    chart_card,
    clean_records,
    empty_figure,
    error_panel,
    format_number,
    kpi_card,
    page_header,
    style_figure,
)
from services.queries import get_ihh, get_participation, get_periods, get_provider_history, resolve_period_id

register_page(__name__, path="/concentracion", name="IHH y participación", order=1)
PREFIX = "con"


def _period_configuration():
    periods = get_periods()
    if periods.empty:
        raise RuntimeError("mart.dim_periodo no contiene registros.")
    options = [{"label": row.anio_mes, "value": int(row.periodo_id)} for row in periods.itertuples()]
    min_row = periods.loc[periods["periodo_id"].idxmin()]
    max_row = periods.loc[periods["periodo_id"].idxmax()]
    min_date = str(pd.Timestamp(min_row["periodo"]).date())
    max_date = str(pd.Timestamp(max_row["periodo"]).date())
    return options, min_date, max_date, int(periods.periodo_id.max())


def layout():
    try:
        period_options, min_date, max_date, max_period = _period_configuration()
    except Exception as exc:
        return html.Div([page_header("Concentración de mercado", ""), error_panel(str(exc))])

    return html.Div(
        children=[
            page_header(
                "Concentración y participación",
                "Evolución histórica del IHH, concentración acumulada y posición de cada prestador.",
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
                                    html.Label("Historia desde"),
                                    dcc.DatePickerSingle(
                                        id="con-start-period",
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
                                    html.Label("Historia hasta"),
                                    dcc.DatePickerSingle(
                                        id="con-end-period",
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
                                    html.Label("Período de participación"),
                                    dcc.Dropdown(id="con-current-period", options=period_options, value=max_period,
                                                 clearable=False),
                                ],
                            ),
                            html.Div(
                                className="filter-field",
                                children=[
                                    html.Label("Prestador para evolución"),
                                    dcc.Dropdown(
                                        id="con-provider", options=[], value=None,
                                        placeholder="Seleccione un prestador", clearable=True,
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(id="con-message", className="data-message"),
            html.Section(
                className="kpi-grid six",
                children=[
                    kpi_card("IHH", "con-kpi-ihh", "con-kpi-ihh-note"),
                    kpi_card("Prestadores presentes", "con-kpi-providers", "con-kpi-providers-note"),
                    kpi_card("Líder", "con-kpi-leader", "con-kpi-leader-note"),
                    kpi_card("Participación líder", "con-kpi-leader-share", "con-kpi-leader-share-note"),
                    kpi_card("CR2", "con-kpi-cr2", "con-kpi-cr2-note"),
                    kpi_card("CR4", "con-kpi-cr4", "con-kpi-cr4-note"),
                ],
            ),
            html.Section(
                className="chart-grid two",
                children=[
                    chart_card("Evolución histórica del IHH", "con-ihh-chart",
                               "Índice calculado sobre prestadores con líneas positivas."),
                    chart_card("Participación por prestador", "con-participation-chart",
                               "Principales prestadores del período seleccionado."),
                    chart_card("Aporte individual al IHH", "con-contribution-chart",
                               "Contribución de cada prestador al índice del mercado."),
                    chart_card("Evolución del prestador seleccionado", "con-provider-history-chart",
                               "Participación y líneas dentro del territorio seleccionado."),
                ],
            ),
            html.Section(
                className="table-card",
                children=[
                    html.Div(
                        className="chart-header",
                        children=[
                            html.H3("Detalle de participación", className="chart-title"),
                            html.P("Incluye prestadores con líneas positivas, cero y sin dato.",
                                   className="chart-subtitle"),
                        ],
                    ),
                    dag.AgGrid(
                        id="con-participation-grid",
                        columnDefs=[
                            {"field": "ranking_prestador", "headerName": "Pos.", "width": 85},
                            {"field": "isp_nombre", "headerName": "Prestador", "minWidth": 260, "flex": 2},
                            {"field": "ruc_limpio", "headerName": "RUC", "minWidth": 150},
                            {"field": "cantidad_peva", "headerName": "PEVA", "width": 95},
                            {"field": "total_lineas_prestador", "headerName": "Líneas", "type": "numericColumn",
                             "minWidth": 130},
                            {"field": "participacion_porcentaje", "headerName": "Participación %",
                             "type": "numericColumn", "minWidth": 150},
                            {"field": "aporte_ihh", "headerName": "Aporte IHH", "type": "numericColumn",
                             "minWidth": 135},
                            {"field": "estado_lineas", "headerName": "Estado", "minWidth": 120},
                            {"field": "porcentaje_imputado_prestador", "headerName": "Imputado %",
                             "type": "numericColumn", "minWidth": 135},
                        ],
                        rowData=[],
                        defaultColDef={"sortable": True, "filter": True, "resizable": True},
                        # theme + columnSize explícitos -- requerido por AGENTS.md para toda
                        # instancia de AgGrid (el proyecto original usaba className="ag-theme-quartz"
                        # sin esto, desviación ya señalada en la revisión profesional del 28-jul-2026).
                        dashGridOptions={"theme": "themeBalham", "pagination": True, "paginationPageSize": 20,
                                         "animateRows": True},
                        columnSize="responsiveSizeToFit",
                        style={"height": "560px", "width": "100%"},
                    ),
                ],
            ),
        ]
    )


register_territory_callbacks(PREFIX)


@callback(
    Output("con-provider", "options"),
    Output("con-provider", "value"),
    Input("con-territory-id", "data"),
    Input("con-current-period", "value"),
)
def update_provider_options(territory_id: str, period_id: int):
    if not territory_id or period_id is None:
        return [], None
    try:
        df = get_participation(territory_id, int(period_id))
    except Exception:
        return [], None
    if df.empty:
        return [], None

    df = df.copy()
    df["provider_label"] = df["isp_nombre"].fillna(df["nombrecomercial"]).fillna(df["prestador_id"])
    options = [{"label": str(row.provider_label), "value": str(row.prestador_id)} for row in df.itertuples()]
    positive = df[pd.to_numeric(df["total_lineas_prestador"], errors="coerce").fillna(0) > 0]
    selected = str(positive.iloc[0]["prestador_id"]) if not positive.empty else str(df.iloc[0]["prestador_id"])
    return options, selected


@callback(
    Output("con-kpi-ihh", "children"),
    Output("con-kpi-ihh-note", "children"),
    Output("con-kpi-providers", "children"),
    Output("con-kpi-providers-note", "children"),
    Output("con-kpi-leader", "children"),
    Output("con-kpi-leader-note", "children"),
    Output("con-kpi-leader-share", "children"),
    Output("con-kpi-leader-share-note", "children"),
    Output("con-kpi-cr2", "children"),
    Output("con-kpi-cr2-note", "children"),
    Output("con-kpi-cr4", "children"),
    Output("con-kpi-cr4-note", "children"),
    Output("con-ihh-chart", "figure"),
    Output("con-participation-chart", "figure"),
    Output("con-contribution-chart", "figure"),
    Output("con-participation-grid", "rowData"),
    Output("con-message", "children"),
    Input("con-territory-id", "data"),
    Input("con-start-period", "date"),
    Input("con-end-period", "date"),
    Input("con-current-period", "value"),
)
def update_concentration(territory_id: str, start_date: str, end_date: str, current_period: int):
    start_period = resolve_period_id(start_date)
    end_period = resolve_period_id(end_date)

    empty_figures = [empty_figure() for _ in range(3)]
    empty_return = ("—", "", "—", "", "—", "", "—", "", "—", "", "—", "", *empty_figures, [], "")
    if not territory_id or None in (start_period, end_period, current_period):
        return empty_return

    start_period, end_period = sorted((int(start_period), int(end_period)))
    current_period = int(current_period)

    try:
        ihh = get_ihh(territory_id, start_period, end_period)
        participation = get_participation(territory_id, current_period)
    except Exception as exc:
        values = list(empty_return)
        values[-1] = str(exc)
        return tuple(values)

    if ihh.empty:
        values = list(empty_return)
        values[-1] = "No existen datos de IHH para los filtros seleccionados."
        return tuple(values)

    ihh = ihh.copy()
    ihh["periodo"] = pd.to_datetime(ihh["periodo"])
    for column in [
        "ihh", "numero_prestadores", "numero_prestadores_con_lineas", "numero_prestadores_sin_dato",
        "participacion_lider", "cr2", "cr4", "porcentaje_imputado_mercado",
    ]:
        if column in ihh:
            ihh[column] = pd.to_numeric(ihh[column], errors="coerce")

    exact = ihh[ihh["periodo_id"] == current_period]
    selected_row = exact.iloc[-1] if not exact.empty else ihh.iloc[-1]
    selected_label = str(selected_row.get("anio_mes", ""))

    leader_name = selected_row.get("prestador_lider_nombre")
    if pd.isna(leader_name) or not leader_name:
        leader_name = selected_row.get("prestador_lider_nombrecomercial")
    leader_name = leader_name if pd.notna(leader_name) and leader_name else "—"

    ihh_value = format_number(selected_row.get("ihh"), 1)
    ihh_note = f"Período {selected_label}"
    providers_value = format_number(selected_row.get("numero_prestadores"))
    providers_note = (
        f"{format_number(selected_row.get('numero_prestadores_con_lineas'))} con líneas · "
        f"{format_number(selected_row.get('numero_prestadores_sin_dato'))} sin dato"
    )
    leader_value = str(leader_name)
    leader_note = "Prestador con mayor participación"
    leader_share_value = f"{format_number(selected_row.get('participacion_lider'), 2)}%"
    leader_share_note = "Participación del principal prestador"
    cr2_value = f"{format_number(selected_row.get('cr2'), 2)}%"
    cr2_note = "Participación conjunta de los dos primeros"
    cr4_value = f"{format_number(selected_row.get('cr4'), 2)}%"
    cr4_note = "Participación conjunta de los cuatro primeros"

    ihh_fig = go.Figure()
    ihh_fig.add_trace(
        go.Scatter(
            x=ihh["periodo"], y=ihh["ihh"], mode="lines+markers", name="IHH",
            line={"color": PALETTE["blue"], "width": 3},
            fill="tozeroy", fillcolor="rgba(20, 100, 244, 0.08)",
        )
    )
    style_figure(ihh_fig)
    ihh_fig.update_yaxes(title="IHH", rangemode="tozero")

    if participation.empty:
        participation_fig = empty_figure("No hay participación para el período seleccionado")
        contribution_fig = empty_figure("No hay aportes al IHH para el período seleccionado")
        grid_rows = []
    else:
        participation = participation.copy()
        participation["provider_label"] = (
            participation["isp_nombre"].fillna(participation["nombrecomercial"]).fillna(participation["prestador_id"])
        )
        for column in [
            "total_lineas_prestador", "participacion_porcentaje", "aporte_ihh",
            "porcentaje_imputado_prestador", "ranking_prestador",
        ]:
            participation[column] = pd.to_numeric(participation[column], errors="coerce")

        positive = participation[participation["total_lineas_prestador"].fillna(0) > 0].copy()
        positive = positive.sort_values("participacion_porcentaje", ascending=False)
        top = positive.head(15).sort_values("participacion_porcentaje")

        participation_fig = go.Figure(
            go.Bar(
                x=top["participacion_porcentaje"], y=top["provider_label"], orientation="h",
                marker_color=PALETTE["blue"],
                hovertemplate="%{y}<br>Participación: %{x:.2f}%<extra></extra>",
            )
        )
        style_figure(participation_fig, height=420, hovermode="closest")
        participation_fig.update_xaxes(title="Participación (%)")
        participation_fig.update_yaxes(title="")

        contribution_top = positive.head(15).sort_values("aporte_ihh")
        contribution_fig = go.Figure(
            go.Bar(
                x=contribution_top["aporte_ihh"], y=contribution_top["provider_label"], orientation="h",
                marker_color=PALETTE["cyan"],
                hovertemplate="%{y}<br>Aporte IHH: %{x:.2f}<extra></extra>",
            )
        )
        style_figure(contribution_fig, height=420, hovermode="closest")
        contribution_fig.update_xaxes(title="Aporte al IHH")
        contribution_fig.update_yaxes(title="")

        grid_columns = [
            "ranking_prestador", "isp_nombre", "ruc_limpio", "cantidad_peva",
            "total_lineas_prestador", "participacion_porcentaje", "aporte_ihh",
            "estado_lineas", "porcentaje_imputado_prestador",
        ]
        grid_rows = clean_records(participation[grid_columns])

    message = (
        f"Territorio: {selected_row.get('nombre_geografico', territory_id)} · "
        f"Período de participación: {selected_label} · "
        f"Imputado: {format_number(selected_row.get('porcentaje_imputado_mercado'), 2)}%"
    )

    return (
        ihh_value, ihh_note,
        providers_value, providers_note,
        leader_value, leader_note,
        leader_share_value, leader_share_note,
        cr2_value, cr2_note,
        cr4_value, cr4_note,
        ihh_fig, participation_fig, contribution_fig,
        grid_rows, message,
    )


@callback(
    Output("con-provider-history-chart", "figure"),
    Input("con-territory-id", "data"),
    Input("con-provider", "value"),
    Input("con-start-period", "date"),
    Input("con-end-period", "date"),
)
def update_provider_history(territory_id: str, provider_id: str | None, start_date: str, end_date: str):
    start_period = resolve_period_id(start_date)
    end_period = resolve_period_id(end_date)

    if not territory_id or not provider_id or start_period is None or end_period is None:
        return empty_figure("Seleccione un prestador")

    start_period, end_period = sorted((int(start_period), int(end_period)))
    try:
        history = get_provider_history(territory_id, provider_id, start_period, end_period)
    except Exception:
        return empty_figure("Error al consultar la historia del prestador")
    if history.empty:
        return empty_figure("El prestador no tiene registros en el período")

    history = history.copy()
    history["periodo"] = pd.to_datetime(history["periodo"])
    history["participacion_porcentaje"] = pd.to_numeric(history["participacion_porcentaje"], errors="coerce")
    history["total_lineas_prestador"] = pd.to_numeric(history["total_lineas_prestador"], errors="coerce")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=history["periodo"], y=history["participacion_porcentaje"], mode="lines+markers",
            name="Participación (%)", line={"color": PALETTE["blue"], "width": 3}, yaxis="y",
        )
    )
    fig.add_trace(
        go.Bar(
            x=history["periodo"], y=history["total_lineas_prestador"], name="Líneas",
            marker_color="rgba(0, 167, 196, 0.30)", yaxis="y2",
        )
    )
    style_figure(fig)
    fig.update_layout(
        yaxis={"title": "Participación (%)", "gridcolor": "#e6edf4"},
        yaxis2={"title": "Líneas", "overlaying": "y", "side": "right", "showgrid": False},
        barmode="overlay",
    )
    return fig
