"""dashboard/pages/discrepancias_geografia.py — Nodos ISP con discrepancia de geografía.

SOLO LECTURA -- el estado de revisión (estado_revision) se muestra tal cual
está en calidad.discrepancias_geografia_nodo, pero esta página NO permite
editarlo. La revisión real (confirmar, descartar, dejar notas) ocurre fuera
de OBTEL, con el rol calidad_revisor -- decisión confirmada con Iván
06-ago-2026 (opción A: cero roles nuevos, cero cambios al modelo de
permisos de dashboard_lector, que solo tiene SELECT).

Muestra nodos con es_discrepancia=true en mart.vw_nodos_isp_mapa: el cantón
derivado de la coordenada (shapefile CONALI, autoritativo) no coincide con
el cantón reportado en SIETEL (dbo.Parroquia, codificación INEC más vieja).
Ver docstring completo en mart/detectar_discrepancias_geografia_nodo.py
para la justificación de comparar por cantón, no por parroquia exacta.
"""
from __future__ import annotations

import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html, register_page
import dash_ag_grid as dag

from components.node_territory_filters import node_territory_filter_layout, register_node_territory_callbacks
from components.ui import PALETTE, clean_records, compute_mapbox_view, empty_figure, error_panel, mapbox_polygon_layers, \
    page_header
from services.queries import (
    get_node_provider_options, get_node_types, get_nodos_mapa, get_operation_states, get_territory_geojson,
)

register_page(__name__, path="/sai/discrepancias-geografia", name="Discrepancias de geografía", order=3)
PREFIX = "dnodo"


def layout():
    try:
        tipo_nodo_options = get_node_types()
    except Exception as exc:
        return html.Div([page_header("Discrepancias de geografía", ""), error_panel(str(exc))])

    return html.Div(
        children=[
            page_header(
                "Discrepancias de geografía de nodos",
                "Nodos cuyo cantón reportado en SIETEL no coincide con el cantón real de su coordenada "
                "(shapefile CONALI). Solo lectura -- la revisión y resolución ocurren fuera de este dashboard.",
            ),
            html.Section(
                className="filter-panel",
                children=[
                    node_territory_filter_layout(PREFIX),
                    html.Div(
                        className="territory-grid",
                        children=[
                            html.Div(
                                className="filter-field",
                                children=[
                                    html.Label("Tipo de nodo"),
                                    dcc.Dropdown(
                                        id=f"{PREFIX}-tipo-nodo",
                                        options=tipo_nodo_options,
                                        value=[],
                                        multi=True,
                                        placeholder="Todos",
                                    ),
                                ],
                            ),
                            html.Div(
                                className="filter-field",
                                children=[
                                    html.Label("Estado de operación"),
                                    dcc.Dropdown(
                                        id=f"{PREFIX}-opera-estado",
                                        options=get_operation_states(),
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
                                        id=f"{PREFIX}-isp-nombre",
                                        options=[],
                                        value=[],
                                        multi=True,
                                        placeholder="Todos",
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(id=f"{PREFIX}-message", className="data-message"),
            html.Section(
                className="chart-card",
                children=[
                    html.Div(
                        className="chart-header",
                        children=[
                            html.H3("Ubicación real de nodos con discrepancia", className="chart-title"),
                            html.P(
                                "Posición real de la coordenada (derivada de CONALI) -- no la posición "
                                "reportada, que puede corresponder a otro cantón.",
                                className="chart-subtitle",
                            ),
                        ],
                    ),
                    dcc.Loading(
                        dcc.Graph(
                            id=f"{PREFIX}-map",
                            config={"displaylogo": False, "scrollZoom": True},
                        ),
                        type="circle",
                    ),
                ],
            ),
            html.Section(
                className="chart-card",
                style={"marginTop": "20px"},
                children=[
                    html.Div(
                        className="chart-header",
                        children=[
                            html.H3("Detalle de discrepancias", className="chart-title"),
                            html.P(
                                "estado_revision refleja el estado de revisión humana (calidad_revisor), "
                                "solo lectura desde aquí.",
                                className="chart-subtitle",
                            ),
                        ],
                    ),
                    dag.AgGrid(
                        id=f"{PREFIX}-grid",
                        columnDefs=[
                            {"field": "noisp_codigo", "headerName": "Código de nodo", "minWidth": 190},
                            {"field": "isp_nombre", "headerName": "Prestador", "minWidth": 220, "flex": 2},
                            {"field": "tiponodo", "headerName": "Tipo", "width": 110},
                            {"field": "provincia_reportada_nombre", "headerName": "Provincia (reportada)",
                             "minWidth": 150},
                            {"field": "canton_reportado_nombre", "headerName": "Cantón (reportado)", "minWidth": 150},
                            {"field": "parroquia_reportada_nombre", "headerName": "Parroquia (reportada)",
                             "minWidth": 170},
                            {"field": "nombre_provincia", "headerName": "Provincia (real)", "minWidth": 150},
                            {"field": "nombre_canton", "headerName": "Cantón (real)", "minWidth": 150},
                            {"field": "nombre_parroquia", "headerName": "Parroquia (real)", "minWidth": 170},
                            {"field": "estado_revision", "headerName": "Estado de revisión", "minWidth": 160},
                        ],
                        rowData=[],
                        defaultColDef={"sortable": True, "filter": True, "resizable": True},
                        dashGridOptions={"theme": "themeBalham", "pagination": True, "paginationPageSize": 20,
                                         "animateRows": True},
                        columnSize="responsiveSizeToFit",
                        style={"height": "480px", "width": "100%"},
                    ),
                ],
            ),
        ]
    )


register_node_territory_callbacks(PREFIX)


@callback(
    Output(f"{PREFIX}-isp-nombre", "options"),
    Input(f"{PREFIX}-territory-id", "data"),
)
def update_isp_options(territory_id: str):
    if not territory_id:
        return []
    return get_node_provider_options(territory_id)


@callback(
    Output(f"{PREFIX}-map", "figure"),
    Output(f"{PREFIX}-grid", "rowData"),
    Output(f"{PREFIX}-message", "children"),
    Input(f"{PREFIX}-territory-id", "data"),
    Input(f"{PREFIX}-tipo-nodo", "value"),
    Input(f"{PREFIX}-opera-estado", "value"),
    Input(f"{PREFIX}-isp-nombre", "value"),
)
def update_discrepancias(territory_id, tipo_nodos, opera_estados, isp_nombres):
    try:
        df = get_nodos_mapa(
            territory_id=territory_id,
            tipo_nodos=tipo_nodos or None,
            opera_estados=opera_estados or None,
            isp_nombres=isp_nombres or None,
            solo_discrepancias=True,
        )
    except Exception as exc:
        return empty_figure(f"No fue posible consultar las discrepancias: {exc}"), [], ""

    if df.empty:
        return empty_figure("No hay discrepancias para los filtros seleccionados"), [], "0 discrepancias"

    fig = go.Figure(go.Scattermapbox(
        lat=df["latitud_decimal"],
        lon=df["longitud_decimal"],
        mode="markers",
        marker={"size": 9, "color": PALETTE["red"]},
        text=(
                df["isp_nombre"].fillna("Prestador sin reportes de líneas") + " — reportado: " + df[
            "canton_reportado_nombre"].fillna("?")
                + " / real: " + df["nombre_canton"].fillna("?")
        ),
        hovertemplate="%{text}<br>Lat: %{lat:.5f} Lon: %{lon:.5f}<extra></extra>",
    ))

    resultado_geojson = get_territory_geojson(territory_id)
    mapbox_layout: dict = {"style": "open-street-map"}
    if resultado_geojson:
        geojson, (lon_min, lat_min, lon_max, lat_max) = resultado_geojson
        center, zoom = compute_mapbox_view(lat_min, lat_max, lon_min, lon_max)
        mapbox_layout["layers"] = mapbox_polygon_layers(geojson, PALETTE["navy"])
    else:
        center, zoom = compute_mapbox_view(
            df["latitud_decimal"].min(), df["latitud_decimal"].max(),
            df["longitud_decimal"].min(), df["longitud_decimal"].max(),
        )
    mapbox_layout["center"] = center
    mapbox_layout["zoom"] = zoom

    fig.update_layout(
        mapbox=mapbox_layout,
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        height=480,
    )

    message = f"{len(df):,} discrepancias mostradas · Territorio: {territory_id}".replace(",", ".")
    return fig, clean_records(df), message
