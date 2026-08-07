"""dashboard/pages/mapa_nodos.py — Mapa nacional de nodos ISP (geografía en orden).

Muestra únicamente nodos SIN discrepancia de geografía (es_discrepancia=false
en mart.vw_nodos_isp_mapa) -- los que sí discrepan tienen su propia página,
components/discrepancias_geografia.py, con el detalle reportado-vs-derivado
que aquí no aplica (aquí ambos lados coinciden por definición).

Geografía CONALI (derivada de coordenadas), NUNCA la geografía de líneas
reportadas (mart.dim_territorio) -- universo distinto, un nodo físico puede
servir a varias parroquias de líneas. Confirmado con Iván 06-ago-2026.

Filtros: mismos conceptos que Evolución (territorio, Estado de operación,
Prestador) más Tipo de nodo, exclusivo de esta página -- a pedido de Iván
06-ago-2026. Sincronizados solo entre esta página y Discrepancias de
Geografía (nodo-shared-territory en app.py), nunca con Evolución/
Concentración.
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

register_page(__name__, path="/sai/mapa-nodos", name="Mapa de nodos", order=2)
PREFIX = "mnodo"

# PRIMARIO/SECUNDARIO son los dos valores observados en producción -- otros
# valores (o NULL) caen en "muted", visibles pero sin insinuar una categoría
# que no se confirmó.
COLOR_TIPO_NODO = {
    "PRIMARIO": PALETTE["blue"],
    "SECUNDARIO": PALETTE["teal"],
}


def layout():
    try:
        tipo_nodo_options = get_node_types()
    except Exception as exc:
        return html.Div([page_header("Mapa de nodos", ""), error_panel(str(exc))])

    return html.Div(
        children=[
            page_header(
                "Mapa de nodos",
                "Ubicación geográfica de nodos de acceso ISP, sin discrepancia frente a lo reportado en SIETEL.",
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
                            html.H3("Ubicación de nodos", className="chart-title"),
                            html.P(
                                "Azul: nodo primario. Verde azulado: nodo secundario. "
                                "Solo nodos con coordenada válida y sin discrepancia de cantón.",
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
                        children=[html.H3("Detalle de nodos", className="chart-title")],
                    ),
                    dag.AgGrid(
                        id=f"{PREFIX}-grid",
                        columnDefs=[
                            {"field": "noisp_codigo", "headerName": "Código de nodo", "minWidth": 200},
                            {"field": "isp_nombre", "headerName": "Prestador", "minWidth": 240, "flex": 2},
                            {"field": "tiponodo", "headerName": "Tipo", "width": 120},
                            {"field": "nombre_provincia", "headerName": "Provincia", "minWidth": 140},
                            {"field": "nombre_canton", "headerName": "Cantón", "minWidth": 140},
                            {"field": "nombre_parroquia", "headerName": "Parroquia", "minWidth": 160},
                            {"field": "latitud_decimal", "headerName": "Latitud", "type": "numericColumn",
                             "minWidth": 120},
                            {"field": "longitud_decimal", "headerName": "Longitud", "type": "numericColumn",
                             "minWidth": 120},
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
def update_map(territory_id, tipo_nodos, opera_estados, isp_nombres):
    try:
        df = get_nodos_mapa(
            territory_id=territory_id,
            tipo_nodos=tipo_nodos or None,
            opera_estados=opera_estados or None,
            isp_nombres=isp_nombres or None,
            solo_discrepancias=False,
        )
    except Exception as exc:
        return empty_figure(f"No fue posible consultar los nodos: {exc}"), [], ""

    # Esta página solo muestra geografía "en orden" -- las discrepancias
    # tienen su propia página, con el detalle reportado-vs-derivado.
    df = df[df["es_discrepancia"] == False]  # noqa: E712 -- comparación explícita con booleano de pandas/SQL

    if df.empty:
        return empty_figure("No hay nodos para los filtros seleccionados"), [], "0 nodos"

    fig = go.Figure()
    for tipo, color in COLOR_TIPO_NODO.items():
        subset = df[df["tiponodo"] == tipo]
        if subset.empty:
            continue
        fig.add_trace(go.Scattermapbox(
            lat=subset["latitud_decimal"],
            lon=subset["longitud_decimal"],
            mode="markers",
            marker={"size": 8, "color": color},
            name=tipo.title(),
            text=subset["isp_nombre"].fillna("Prestador sin nombre registrado") + " — " + subset[
                "nombre_parroquia"].fillna(""),
            hovertemplate="%{text}<br>Lat: %{lat:.5f} Lon: %{lon:.5f}<extra></extra>",
        ))

    otros = df[~df["tiponodo"].isin(COLOR_TIPO_NODO.keys())]
    if not otros.empty:
        fig.add_trace(go.Scattermapbox(
            lat=otros["latitud_decimal"],
            lon=otros["longitud_decimal"],
            mode="markers",
            marker={"size": 8, "color": PALETTE["muted"]},
            name="Otro / sin tipo",
            text=otros["isp_nombre"].fillna("Prestador sin nombre registrado") + " — " + otros[
                "nombre_parroquia"].fillna(""),
            hovertemplate="%{text}<br>Lat: %{lat:.5f} Lon: %{lon:.5f}<extra></extra>",
        ))

    # Auto-zoom: si hay un territorio distinto de Nacional, se centra y
    # ajusta el zoom al polígono real del territorio (provincia/cantón/
    # parroquia), no solo a los nodos visibles -- así el mapa no queda
    # descentrado si el filtro deja pocos puntos en una esquina del
    # territorio. A nivel Nacional, sin polígono (rellenar todo el país no
    # aporta nada visualmente), se usa el rango de los nodos mostrados.
    resultado_geojson = get_territory_geojson(territory_id)
    mapbox_layout: dict = {"style": "open-street-map"}
    if resultado_geojson:
        geojson, (lon_min, lat_min, lon_max, lat_max) = resultado_geojson
        center, zoom = compute_mapbox_view(lat_min, lat_max, lon_min, lon_max)
        mapbox_layout["layers"] = mapbox_polygon_layers(geojson, PALETTE["navy"])
    elif not df.empty:
        center, zoom = compute_mapbox_view(
            df["latitud_decimal"].min(), df["latitud_decimal"].max(),
            df["longitud_decimal"].min(), df["longitud_decimal"].max(),
        )
    else:
        center, zoom = {"lat": -1.5, "lon": -78.5}, 5.2
    mapbox_layout["center"] = center
    mapbox_layout["zoom"] = zoom

    fig.update_layout(
        mapbox=mapbox_layout,
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        height=560,
        legend={"orientation": "h", "y": 1.02, "x": 0},
    )

    message = f"{len(df):,} nodos mostrados · Territorio: {territory_id}".replace(",", ".")
    return fig, clean_records(df), message
