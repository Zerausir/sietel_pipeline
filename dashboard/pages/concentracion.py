"""dashboard/pages/concentracion.py — IHH, participación y concentración de mercado."""
from __future__ import annotations

import dash_ag_grid as dag
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html, register_page

from components.filters_shared import register_shared_filters_callbacks, shared_filters_layout
from components.territory_filters import register_territory_callbacks, territory_filter_layout
from components.ui import (
    PALETTE,
    chart_card,
    clean_records,
    empty_figure,
    error_panel,
    format_number,
    kpi_card,
    month_year_dropdown,
    page_header,
    style_figure,
)
from services.queries import (
    get_ihh,
    get_ihh_filtrado,
    get_participation,
    get_participation_filtrado,
    get_periods,
    get_provider_history,
)

register_page(__name__, path="/concentracion", name="IHH y participación", order=1)
PREFIX = "con"


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
        period_options, min_period, max_period = _period_options()
    except Exception as exc:
        return html.Div([page_header("Concentración de mercado", ""), error_panel(str(exc))])

    return html.Div(
        children=[
            page_header(
                "Concentración y participación",
                "Evolución histórica del IHH, concentración acumulada y posición de cada prestador, "
                "calculados exclusivamente sobre datos reportados -- sin relleno interior (imputado).",
            ),
            html.Section(
                className="filter-panel",
                children=[
                    territory_filter_layout(PREFIX),
                    html.Div(
                        className="period-grid four-periods",
                        children=[
                            month_year_dropdown("con-start-period", "Historia desde", period_options, min_period),
                            month_year_dropdown("con-end-period", "Historia hasta", period_options, max_period),
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
                    shared_filters_layout(PREFIX),
                ],
            ),
            html.Div(id="con-message", className="data-message"),
            html.Section(
                className="kpi-grid six",
                children=[
                    kpi_card("IHH", "con-kpi-ihh", "con-kpi-ihh-note"),
                    kpi_card("Cobertura del índice", "con-kpi-cobertura", "con-kpi-cobertura-note"),
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
                               "Calculado solo sobre prestadores con reporte real cada mes."),
                    chart_card("Participación por prestador", "con-participation-chart",
                               "Principales prestadores del período seleccionado, solo datos reales."),
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
                            html.P(
                                "Incluye TODOS los prestadores del territorio, incluso quienes no "
                                "reportaron ese mes exacto (columna 'Estado') -- para auditoría de "
                                "cobertura, no solo los que entran en el cálculo del IHH.",
                                className="chart-subtitle",
                            ),
                        ],
                    ),
                    dag.AgGrid(
                        id="con-participation-grid",
                        columnDefs=[
                            {"field": "ranking_prestador", "headerName": "Pos.", "width": 85},
                            {"field": "isp_nombre", "headerName": "Prestador", "minWidth": 260, "flex": 2},
                            {"field": "ruc_limpio", "headerName": "RUC", "minWidth": 150},
                            {"field": "cantidad_peva", "headerName": "PEVA", "width": 95},
                            {"field": "total_lineas_prestador", "headerName": "Líneas (real + imputado)",
                             "type": "numericColumn", "minWidth": 170},
                            {"field": "lineas_reportadas", "headerName": "Líneas reportadas",
                             "type": "numericColumn", "minWidth": 150},
                            {"field": "participacion_porcentaje", "headerName": "Participación %",
                             "type": "numericColumn", "minWidth": 150},
                            {"field": "aporte_ihh", "headerName": "Aporte IHH", "type": "numericColumn",
                             "minWidth": 135},
                            {"field": "estado_lineas", "headerName": "Estado", "minWidth": 150},
                        ],
                        rowData=[],
                        defaultColDef={"sortable": True, "filter": True, "resizable": True},
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
register_shared_filters_callbacks(PREFIX)


@callback(
    Output("con-provider", "options"),
    Output("con-provider", "value"),
    Input("con-territory-id", "data"),
    Input("con-current-period", "value"),
    Input("con-opera-estado", "value"),
    Input("con-isp-nombre", "value"),
)
def update_provider_options(territory_id: str, period_id: int, opera_estados: list[str] | None,
                            isp_nombres: list[str] | None):
    if not territory_id or period_id is None:
        return [], None
    opera_estados = opera_estados or []
    isp_nombres = isp_nombres or []
    try:
        if opera_estados or isp_nombres:
            df = get_participation_filtrado(territory_id, int(period_id), opera_estados, isp_nombres)
        else:
            df = get_participation(territory_id, int(period_id))
    except Exception:
        return [], None
    if df.empty:
        return [], None

    df = df.copy()
    df["provider_label"] = df["isp_nombre"].fillna(df["nombrecomercial"]).fillna(df["prestador_id"])
    options = [{"label": str(row.provider_label), "value": str(row.prestador_id)} for row in df.itertuples()]
    positive = df[pd.to_numeric(df["lineas_reportadas"], errors="coerce").fillna(0) > 0]
    selected = str(positive.iloc[0]["prestador_id"]) if not positive.empty else str(df.iloc[0]["prestador_id"])
    return options, selected


@callback(
    Output("con-kpi-ihh", "children"),
    Output("con-kpi-ihh-note", "children"),
    Output("con-kpi-cobertura", "children"),
    Output("con-kpi-cobertura-note", "children"),
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
    Input("con-start-period", "value"),
    Input("con-end-period", "value"),
    Input("con-current-period", "value"),
    Input("con-opera-estado", "value"),
    Input("con-isp-nombre", "value"),
)
def update_concentration(
        territory_id: str,
        start_period: int | None,
        end_period: int | None,
        current_period: int | None,
        opera_estados: list[str] | None,
        isp_nombres: list[str] | None,
):
    opera_estados = opera_estados or []
    isp_nombres = isp_nombres or []

    empty_figures = [empty_figure() for _ in range(3)]
    empty_return = ("—", "", "—", "", "—", "", "—", "", "—", "", "—", "", *empty_figures, [], "")
    if not territory_id or None in (start_period, end_period, current_period):
        return empty_return

    start_period, end_period = sorted((int(start_period), int(end_period)))
    current_period = int(current_period)
    hay_filtros = bool(opera_estados) or bool(isp_nombres)

    try:
        if hay_filtros:
            ihh = get_ihh_filtrado(territory_id, start_period, end_period, opera_estados, isp_nombres)
            participation = get_participation_filtrado(territory_id, current_period, opera_estados, isp_nombres)
        else:
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
        "ihh", "numero_prestadores_reportaron", "numero_prestadores_registrados",
        "porcentaje_cobertura_prestadores", "participacion_lider", "cr2", "cr4",
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
    ihh_note = (
        f"Período {selected_label} · Calculado exclusivamente sobre líneas reportadas (dato real) -- "
        "ningún prestador sin reporte ese mes entra al cálculo, ni en cero ni con su último valor conocido."
    )

    cobertura = selected_row.get("porcentaje_cobertura_prestadores")
    cobertura_value = f"{format_number(cobertura, 1)}%" if pd.notna(cobertura) else "—"
    cobertura_note = (
        f"{format_number(selected_row.get('numero_prestadores_reportaron'))} de "
        f"{format_number(selected_row.get('numero_prestadores_registrados'))} prestadores registrados "
        f"reportaron este mes -- el IHH de al lado se calculó solo sobre ellos. Una cobertura baja "
        "significa que el índice representa una porción menor del mercado real ese mes."
    )

    leader_value = str(leader_name)
    leader_note = "Prestador con mayor participación, entre quienes reportaron"
    leader_share_value = f"{format_number(selected_row.get('participacion_lider'), 2)}%"
    leader_share_note = "Participación del principal prestador (sobre el mercado reportado)"
    cr2_value = f"{format_number(selected_row.get('cr2'), 2)}%"
    cr2_note = "Participación conjunta de los dos primeros (sobre el mercado reportado)"
    cr4_value = f"{format_number(selected_row.get('cr4'), 2)}%"
    cr4_note = "Participación conjunta de los cuatro primeros (sobre el mercado reportado)"

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
            "total_lineas_prestador", "lineas_reportadas", "participacion_porcentaje", "aporte_ihh",
            "ranking_prestador",
        ]:
            participation[column] = pd.to_numeric(participation[column], errors="coerce")

        positive = participation[participation["ranking_prestador"].notna()].copy()
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
        participation_fig.update_xaxes(title="Participación (%, solo reportadas)")
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
            "total_lineas_prestador", "lineas_reportadas", "participacion_porcentaje", "aporte_ihh",
            "estado_lineas",
        ]
        grid_rows = clean_records(participation[grid_columns])

    filtros_txt = []
    if opera_estados:
        filtros_txt.append(f"Estado: {', '.join(opera_estados)}")
    if isp_nombres:
        filtros_txt.append(f"Prestador: {', '.join(isp_nombres)}")
    filtros_sufijo = f" · Filtros: {'; '.join(filtros_txt)}" if filtros_txt else ""
    message = (
        f"Territorio: {territory_id} · "
        f"Período de participación: {selected_label} · "
        f"Cobertura: {cobertura_value}{filtros_sufijo}"
    )

    return (
        ihh_value, ihh_note,
        cobertura_value, cobertura_note,
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
    Input("con-start-period", "value"),
    Input("con-end-period", "value"),
)
def update_provider_history(territory_id: str, provider_id: str | None, start_period: int | None,
                            end_period: int | None):
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
            name="Participación (%, solo reportadas)", line={"color": PALETTE["blue"], "width": 3}, yaxis="y",
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
