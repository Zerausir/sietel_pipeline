"""dashboard/pages/sma_datos.py — Módulo SMA: Calidad de Datos móviles.

Espejo del reporte "Calidad Datos" de Power BI (capturas del 21-ago-2026),
sobre samm_pipeline (samm_db, vista public.grafana_mobile_geo_view) -- NO
sobre mart.* de sietel_analitico, universo de datos completamente
distinto. Ver services/queries_sma.py para las advertencias sobre nombres
de columna no verificados contra el DDL real.

Filtros sincronizados con sma_voz.py vía "sma-shared-filters" (ver
components/sma_filters.py) -- nunca con las páginas de SAI.
"""
from __future__ import annotations

import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html, register_page
import dash_ag_grid as dag

from components.sma_filters import register_sma_filter_callbacks, sma_filter_layout
from components.ui import (
    PALETTE, chart_card, clean_records, compute_mapbox_view, empty_figure, error_panel, excel_download_button,
    page_header, register_excel_download_callback, style_figure,
)
from services.queries_sma import SMA_ROW_LIMIT, get_sma_mobile_map, get_sma_mobile_summary

register_page(__name__, path="/sma/datos", name="Calidad de Datos móviles", order=10)
PREFIX = "smad"


def layout():
    return html.Div(
        children=[
            page_header(
                "Calidad de Datos móviles",
                "Sesiones de datos por operadora: totales, velocidades promedio, sesiones HTTP fallidas y "
                "throughput geolocalizado. Fuente: samm_pipeline (grafana_mobile_geo_view).",
            ),
            sma_filter_layout(PREFIX),
            html.Div(id=f"{PREFIX}-message", className="data-message"),
            html.Div(
                className="kpi-grid",
                style={"display": "grid", "gridTemplateColumns": "repeat(5, 1fr)", "gap": "16px"},
                children=[
                    chart_card("Totales por operadora", f"{PREFIX}-totales-bar",
                               "Total de cargas, descargas y sus fallidas, por operadora."),
                    chart_card("Promedio de descarga (Mbps)", f"{PREFIX}-dl-bar", "Promedio por operadora."),
                    chart_card("Promedio de carga (Mbps)", f"{PREFIX}-ul-bar", "Promedio por operadora."),
                    chart_card("% Sesiones HTTP fallidas", f"{PREFIX}-pct-http-bar",
                               "Recalculado sobre el total de sesiones de cada operadora."),
                    chart_card("% Cumplimiento DL (≥3.8 Mbps)", f"{PREFIX}-pct-cumplimiento-bar",
                               "Sesiones de descarga exitosas con throughput ≥3.8 Mbps, sobre el total con "
                               "throughput medido -- réplica exacta de la medida DAX original."),
                ],
            ),
            html.Section(
                className="chart-card",
                style={"marginTop": "20px"},
                children=[
                    html.Div(
                        className="chart-header",
                        children=[
                            html.H3("Throughput geolocalizado", className="chart-title"),
                            html.P(
                                f"Color según Mbps de la sesión. Muestra aleatoria de hasta "
                                f"{SMA_ROW_LIMIT:,} sesiones repartida en todo el período filtrado "
                                "dentro del filtro activo -- acotar por fecha/territorio si el mensaje de "
                                "truncado aparece.".replace(",", "."),
                                className="chart-subtitle",
                            ),
                        ],
                    ),
                    dcc.Loading(
                        dcc.Graph(id=f"{PREFIX}-map", config={"displaylogo": False, "scrollZoom": True}),
                        type="circle",
                    ),
                ],
            ),
            html.Section(
                className="chart-card",
                style={"marginTop": "20px"},
                children=[
                    html.Div(className="chart-header", children=[html.H3("Detalle por operadora",
                                                                         className="chart-title")]),
                    dag.AgGrid(
                        id=f"{PREFIX}-grid",
                        columnDefs=[
                            {"field": "operador", "headerName": "Operadora", "minWidth": 160},
                            {"field": "total_descargas", "headerName": "Total DL", "type": "numericColumn"},
                            {"field": "total_cargas", "headerName": "Total UL", "type": "numericColumn"},
                            {"field": "descargas_fallidas", "headerName": "DL Fallidas", "type": "numericColumn"},
                            {"field": "cargas_fallidas", "headerName": "UL Fallidas", "type": "numericColumn"},
                            {"field": "promedio_descarga_mbps", "headerName": "Prom. DL (Mbps)",
                             "type": "numericColumn"},
                            {"field": "promedio_carga_mbps", "headerName": "Prom. UL (Mbps)",
                             "type": "numericColumn"},
                            {"field": "pct_sesiones_http_fallidas", "headerName": "% HTTP fallidas",
                             "type": "numericColumn"},
                            {"field": "pct_cumplimiento_dl", "headerName": "% Cumplimiento DL (≥3.8 Mbps)",
                             "type": "numericColumn"},
                        ],
                        rowData=[],
                        defaultColDef={"sortable": True, "filter": True, "resizable": True},
                        dashGridOptions={"theme": "themeBalham", "animateRows": True, "pagination": True,
                                         "paginationPageSize": 10},
                        columnSize="responsiveSizeToFit",
                        style={"height": "300px", "width": "100%"},
                    ),
                    excel_download_button(f"{PREFIX}-grid"),
                ],
            ),
        ]
    )


register_sma_filter_callbacks(PREFIX)
register_excel_download_callback(f"{PREFIX}-grid", "sma_calidad_datos_por_operadora.xlsx")


def _filtros(operadoras, czos, provincias, cantones, parroquias, tecnologias, numero, f_ini, f_fin):
    return dict(
        operadoras=tuple(operadoras or ()), czos=tuple(czos or ()),
        provincias=tuple(provincias or ()), cantones=tuple(cantones or ()), parroquias=tuple(parroquias or ()),
        tecnologias=tuple(tecnologias or ()), numero=numero or None,
        fecha_inicio=f_ini, fecha_fin=f_fin,
    )


@callback(
    Output(f"{PREFIX}-totales-bar", "figure"),
    Output(f"{PREFIX}-dl-bar", "figure"),
    Output(f"{PREFIX}-ul-bar", "figure"),
    Output(f"{PREFIX}-pct-http-bar", "figure"),
    Output(f"{PREFIX}-pct-cumplimiento-bar", "figure"),
    Output(f"{PREFIX}-grid", "rowData"),
    Output(f"{PREFIX}-message", "children"),
    Input(f"{PREFIX}-operadora", "value"), Input(f"{PREFIX}-czo", "value"),
    Input(f"{PREFIX}-provincia", "value"), Input(f"{PREFIX}-canton", "value"),
    Input(f"{PREFIX}-parroquia", "value"), Input(f"{PREFIX}-tecnologia", "value"),
    Input(f"{PREFIX}-numero", "value"),
    Input(f"{PREFIX}-fecha-inicial", "date"), Input(f"{PREFIX}-fecha-final", "date"),
)
def actualizar_resumen(operadoras, czos, provincias, cantones, parroquias, tecnologias, numero, f_ini, f_fin):
    filtros = _filtros(operadoras, czos, provincias, cantones, parroquias, tecnologias, numero, f_ini, f_fin)
    try:
        df = get_sma_mobile_summary(**filtros)
    except Exception as exc:
        vacio = empty_figure(f"No fue posible consultar samm_db: {exc}")
        return vacio, vacio, vacio, vacio, vacio, [], ""

    if df.empty:
        vacio = empty_figure("No hay sesiones para los filtros seleccionados")
        return vacio, vacio, vacio, vacio, vacio, [], "0 sesiones"

    totales_fig = go.Figure()
    for columna, nombre, color in [
        ("total_cargas", "Total Cargas", PALETTE["blue"]),
        ("total_descargas", "Total Descargas", PALETTE["navy"]),
        ("cargas_fallidas", "Cargas Fallidas", PALETTE["orange"]),
        ("descargas_fallidas", "Descargas Fallidas", PALETTE["red"]),
    ]:
        totales_fig.add_trace(go.Bar(x=df["operador"], y=df[columna], name=nombre, marker_color=color))
    style_figure(totales_fig, height=340, hovermode="x unified")
    totales_fig.update_layout(barmode="group", legend={"orientation": "h", "y": 1.15})

    dl_fig = go.Figure(go.Bar(x=df["operador"], y=df["promedio_descarga_mbps"], marker_color=PALETTE["blue"]))
    style_figure(dl_fig, height=340)
    dl_fig.update_yaxes(title="Mbps")

    ul_fig = go.Figure(go.Bar(x=df["operador"], y=df["promedio_carga_mbps"], marker_color=PALETTE["teal"]))
    style_figure(ul_fig, height=340)
    ul_fig.update_yaxes(title="Mbps")

    pct_fig = go.Figure(go.Bar(x=df["operador"], y=df["pct_sesiones_http_fallidas"], marker_color=PALETTE["red"]))
    style_figure(pct_fig, height=340)
    pct_fig.update_yaxes(title="%")

    pct_cumple_fig = go.Figure(
        go.Bar(x=df["operador"], y=df["pct_cumplimiento_dl"], marker_color=PALETTE["teal"])
    )
    style_figure(pct_cumple_fig, height=340)
    pct_cumple_fig.update_yaxes(title="%")

    total_sesiones = int(df["total_descargas"].sum() + df["total_cargas"].sum())
    mensaje = f"{total_sesiones:,} sesiones (descarga+carga) · {len(df)} operadora(s)".replace(",", ".")
    return totales_fig, dl_fig, ul_fig, pct_fig, pct_cumple_fig, clean_records(df), mensaje


@callback(
    Output(f"{PREFIX}-map", "figure"),
    Input(f"{PREFIX}-operadora", "value"), Input(f"{PREFIX}-czo", "value"),
    Input(f"{PREFIX}-provincia", "value"), Input(f"{PREFIX}-canton", "value"),
    Input(f"{PREFIX}-parroquia", "value"), Input(f"{PREFIX}-tecnologia", "value"),
    Input(f"{PREFIX}-numero", "value"),
    Input(f"{PREFIX}-fecha-inicial", "date"), Input(f"{PREFIX}-fecha-final", "date"),
)
def actualizar_mapa(operadoras, czos, provincias, cantones, parroquias, tecnologias, numero, f_ini, f_fin):
    filtros = _filtros(operadoras, czos, provincias, cantones, parroquias, tecnologias, numero, f_ini, f_fin)
    try:
        df = get_sma_mobile_map(**filtros)
    except Exception as exc:
        return empty_figure(f"No fue posible consultar el mapa: {exc}")

    if df.empty:
        return empty_figure("No hay sesiones georreferenciadas para los filtros seleccionados")

    fig = go.Figure(go.Scattermap(
        lat=df["latitud"], lon=df["longitud"], mode="markers",
        marker={
            "size": 8,
            "color": df["throughput_mbps"],
            # Escala FIJA 0-100 (no auto-rango sobre el mínimo/máximo real de
            # la selección) -- paradas normalizadas sobre ese rango de 100:
            # 0/100=0 (rojo), 5/100=0.05 (amarillo), 12/100=0.12 (verde) --
            # y verde se mantiene desde ahí hasta 100, no es un punto medio.
            "colorscale": [
                [0.00, PALETTE["red"]],
                [0.05, "#f2d600"],
                [0.12, PALETTE["teal"]],
                [1.00, PALETTE["teal"]],
            ],
            "cmin": 0,
            "cmax": 100,
            "showscale": True,
            "colorbar": {"title": "Mbps"},
        },
        text=(
                df["operador"].fillna("") + " — " + df["tecnologia_final"].fillna("") + " — "
                + df["provincia"].fillna("") + "/" + df["canton"].fillna("") + "/" + df["parroquia"].fillna("")
        ),
        hovertemplate="%{text}<br>Throughput: %{marker.color:.2f} Mbps<extra></extra>",
    ))
    center, zoom = compute_mapbox_view(
        df["latitud"].min(), df["latitud"].max(), df["longitud"].min(), df["longitud"].max(),
    )
    fig.update_layout(
        map={"style": "open-street-map", "center": center, "zoom": zoom},
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        height=520,
    )
    return fig
