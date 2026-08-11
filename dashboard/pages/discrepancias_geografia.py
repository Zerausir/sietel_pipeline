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

REDISEÑO (11-ago-2026): el selector "Nivel geográfico" se eliminó -- mismo
cambio que pages/mapa_nodos.py, ver components/node_territory_filters.py.
"""
from __future__ import annotations

import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html, register_page
import dash_ag_grid as dag

from components.node_territory_filters import node_territory_filter_layout, register_node_territory_callbacks
from components.ui import (
    PALETTE, chart_card, clean_records, compute_mapbox_view, empty_figure, error_panel, excel_download_button,
    mapbox_polygon_layers, page_header, register_excel_download_callback, style_figure,
)
from services.queries import (
    get_node_provider_options, get_node_types, get_nodos_mapa, get_operation_states, get_territory_geojson_multi,
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
                className="chart-grid two",
                style={"marginTop": "20px"},
                children=[
                    chart_card(
                        "Discrepancias por provincia real (Top 15)", f"{PREFIX}-provincia-bar",
                        "Un mapa muestra densidad, no compara magnitudes con precisión -- esta barra sí.",
                    ),
                    chart_card(
                        "Estado de revisión", f"{PREFIX}-estado-bar",
                        "Cuánto de la cola pendiente ya se procesó -- revisión ocurre fuera de OBTEL "
                        "(rol calidad_revisor), esto es solo el conteo.",
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
                    excel_download_button(f"{PREFIX}-grid"),
                ],
            ),
        ]
    )


register_node_territory_callbacks(PREFIX)
register_excel_download_callback(f"{PREFIX}-grid", "detalle_de_discrepancias.xlsx")


@callback(
    Output(f"{PREFIX}-isp-nombre", "options"),
    Input(f"{PREFIX}-territory-selection", "data"),
)
def update_isp_options(seleccion):
    seleccion = seleccion or {}
    return get_node_provider_options(
        tuple(seleccion.get("provincias") or ()),
        tuple(seleccion.get("cantones") or ()),
        tuple(seleccion.get("parroquias") or ()),
    )


@callback(
    Output(f"{PREFIX}-map", "figure"),
    Output(f"{PREFIX}-provincia-bar", "figure"),
    Output(f"{PREFIX}-estado-bar", "figure"),
    Output(f"{PREFIX}-grid", "rowData"),
    Output(f"{PREFIX}-message", "children"),
    Input(f"{PREFIX}-territory-selection", "data"),
    Input(f"{PREFIX}-tipo-nodo", "value"),
    Input(f"{PREFIX}-opera-estado", "value"),
    Input(f"{PREFIX}-isp-nombre", "value"),
)
def update_discrepancias(seleccion, tipo_nodos, opera_estados, isp_nombres):
    seleccion = seleccion or {}
    provincias = tuple(seleccion.get("provincias") or ())
    cantones = tuple(seleccion.get("cantones") or ())
    parroquias = tuple(seleccion.get("parroquias") or ())

    try:
        df = get_nodos_mapa(
            provincias=provincias,
            cantones=cantones,
            parroquias=parroquias,
            tipo_nodos=tuple(tipo_nodos or ()),
            opera_estados=tuple(opera_estados or ()),
            isp_nombres=tuple(isp_nombres or ()),
            solo_discrepancias=True,
        )
    except Exception as exc:
        vacio = empty_figure(f"No fue posible consultar las discrepancias: {exc}")
        return vacio, vacio, vacio, [], ""

    if df.empty:
        vacio = empty_figure("No hay discrepancias para los filtros seleccionados")
        return vacio, vacio, vacio, [], "0 discrepancias"

    fig = go.Figure(go.Scattermapbox(
        lat=df["latitud_decimal"],
        lon=df["longitud_decimal"],
        mode="markers",
        marker={"size": 9, "color": PALETTE["red"]},
        text=(
                df["isp_nombre"].fillna("Prestador sin nombre registrado") + " — reportado: " + df[
            "canton_reportado_nombre"].fillna("?")
                + " / real: " + df["nombre_canton"].fillna("?")
        ),
        hovertemplate="%{text}<br>Lat: %{lat:.5f} Lon: %{lon:.5f}<extra></extra>",
    ))

    resultado_geojson = get_territory_geojson_multi(provincias, cantones, parroquias)
    mapbox_layout: dict = {"style": "open-street-map"}
    if resultado_geojson:
        geojsons, (lon_min, lat_min, lon_max, lat_max) = resultado_geojson
        center, zoom = compute_mapbox_view(lat_min, lat_max, lon_min, lon_max)
        layers = []
        for geojson in geojsons:
            layers.extend(mapbox_polygon_layers(geojson, PALETTE["navy"]))
        mapbox_layout["layers"] = layers
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

    territorio_txt = (
        f"{len(provincias)} provincia(s), {len(cantones)} cantón(es), {len(parroquias)} parroquia(s)"
        if (provincias or cantones or parroquias) else "Nacional"
    )
    message = f"{len(df):,} discrepancias mostradas · Territorio: {territorio_txt}".replace(",", ".")

    conteo_provincia = df["nombre_provincia"].value_counts().head(15).sort_values()
    provincia_fig = go.Figure(go.Bar(
        x=conteo_provincia.values, y=conteo_provincia.index, orientation="h",
        marker_color=PALETTE["red"],
        hovertemplate="%{y}: %{x}<extra></extra>",
    ))
    style_figure(provincia_fig, height=380, hovermode="closest")
    provincia_fig.update_xaxes(title="Discrepancias")
    provincia_fig.update_yaxes(title="")

    # Categórica, pocos valores esperados (PENDIENTE y los estados que
    # calidad_revisor haya usado) -- barras, mismo criterio que la
    # distribución por clasificación en Control: comparar conteos exactos,
    # no proporciones de un círculo.
    conteo_estado = df["estado_revision"].fillna("Sin estado").value_counts().sort_values()
    estado_fig = go.Figure(go.Bar(
        x=conteo_estado.values, y=conteo_estado.index, orientation="h",
        marker_color=PALETTE["cyan"],
        hovertemplate="%{y}: %{x}<extra></extra>",
    ))
    style_figure(estado_fig, height=380, hovermode="closest")
    estado_fig.update_xaxes(title="Discrepancias")
    estado_fig.update_yaxes(title="")

    return fig, provincia_fig, estado_fig, clean_records(df), message
