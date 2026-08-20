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

REDISEÑO (11-ago-2026): el selector "Nivel geográfico" se eliminó --
Provincia/Cantón/Parroquia son siempre visibles y de selección múltiple
(ver components/node_territory_filters.py). El territorio ya no es un
string único ("CANTON|17|1701"); es tres listas independientes.
"""
from __future__ import annotations

import plotly.graph_objects as go
from dash import Input, Output, State,callback, dcc, html, register_page
import dash_ag_grid as dag

from components.filters_shared import register_universal_opera_isp_sync, sync_armado_store
from components.node_territory_filters import node_territory_filter_layout, register_node_territory_callbacks
from components.ui import (
    PALETTE, chart_card, clean_records, compute_mapbox_view, empty_figure, error_panel, excel_download_button,
    mapbox_polygon_layers, page_header, register_excel_download_callback, style_figure,
)
from services.queries import (
    get_node_provider_options, get_node_types, get_nodos_mapa, get_operation_states, get_territory_geojson_multi,
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
            sync_armado_store(PREFIX),
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
            html.Div(
                style={"marginTop": "20px"},
                children=[
                    chart_card(
                        "Nodos por provincia (Top 15)", f"{PREFIX}-provincia-bar",
                        "Un mapa muestra densidad, no compara magnitudes con precisión -- esta barra sí.",
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
                    excel_download_button(f"{PREFIX}-grid"),
                ],
            ),
        ]
    )


register_node_territory_callbacks(PREFIX)
register_universal_opera_isp_sync(PREFIX, lambda: get_node_provider_options((), (), ()))
register_excel_download_callback(f"{PREFIX}-grid", "detalle_de_nodos.xlsx")


@callback(
    Output(f"{PREFIX}-isp-nombre", "options"),
    Input(f"{PREFIX}-territory-selection", "data"),
    State(f"{PREFIX}-isp-nombre", "value"),
    State("shared-filters", "data"),
)
def update_isp_options(
        seleccion,
        valores_actuales,
        shared_data,
):
    """
    Actualiza las opciones de Prestador sin perder el valor universal.

    Approach:
    Obtener las opciones correspondientes al territorio CONALI y agregar
    cualquier Prestador actualmente seleccionado que no esté dentro del
    resultado filtrado.

    Reasoning:
    El valor universal y el universo de opciones son responsabilidades
    diferentes. El Prestador puede estar seleccionado desde otro módulo y
    debe seguir siendo representable en el Dropdown.

    Test Cases:
    - Sin Prestador compartido -> comportamiento normal.
    - Prestador compartido presente en el territorio -> aparece normalmente.
    - Prestador compartido ausente del territorio -> se conserva como opción
      seleccionada para no perder el estado universal.
    """

    seleccion = seleccion or {}

    provincias = tuple(
        seleccion.get("provincias") or ()
    )
    cantones = tuple(
        seleccion.get("cantones") or ()
    )
    parroquias = tuple(
        seleccion.get("parroquias") or ()
    )

    opciones = get_node_provider_options(
        provincias,
        cantones,
        parroquias,
    )

    valores_actuales = valores_actuales or []
    valores_compartidos = (
            (shared_data or {}).get("isp_nombres", []) or []
    )

    valores_a_conservar = (
            set(valores_actuales)
            | set(valores_compartidos)
    )

    existentes = {
        str(opcion["value"])
        for opcion in opciones
    }

    for valor in valores_a_conservar:
        if str(valor) not in existentes:
            opciones.append(
                {
                    "label": str(valor),
                    "value": valor,
                }
            )

    return opciones


@callback(
    Output(f"{PREFIX}-map", "figure"),
    Output(f"{PREFIX}-provincia-bar", "figure"),
    Output(f"{PREFIX}-grid", "rowData"),
    Output(f"{PREFIX}-message", "children"),
    Input(f"{PREFIX}-territory-selection", "data"),
    Input(f"{PREFIX}-tipo-nodo", "value"),
    Input(f"{PREFIX}-opera-estado", "value"),
    Input(f"{PREFIX}-isp-nombre", "value"),
)
def update_map(seleccion, tipo_nodos, opera_estados, isp_nombres):
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
            solo_discrepancias=False,
        )
    except Exception as exc:
        vacio = empty_figure(f"No fue posible consultar los nodos: {exc}")
        return vacio, vacio, [], ""

    # Esta página solo muestra geografía "en orden" -- las discrepancias
    # tienen su propia página, con el detalle reportado-vs-derivado.
    df = df[df["es_discrepancia"] == False]  # noqa: E712 -- comparación explícita con booleano de pandas/SQL

    if df.empty:
        vacio = empty_figure("No hay nodos para los filtros seleccionados")
        return vacio, vacio, [], "0 nodos"

    fig = go.Figure()
    for tipo, color in COLOR_TIPO_NODO.items():
        subset = df[df["tiponodo"].str.strip().str.upper() == tipo]
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

    otros = df[~df["tiponodo"].str.strip().str.upper().isin(COLOR_TIPO_NODO.keys())]
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

    # Auto-zoom: si hay algún territorio elegido, se centra y ajusta el
    # zoom al/los polígono(s) real(es) del territorio (provincia/cantón/
    # parroquia), no solo a los nodos visibles -- así el mapa no queda
    # descentrado si el filtro deja pocos puntos en una esquina del
    # territorio. Sin ningún territorio elegido, sin polígono (rellenar
    # todo el país no aporta nada visualmente), se usa el rango de los
    # nodos mostrados.
    resultado_geojson = get_territory_geojson_multi(provincias, cantones, parroquias)
    mapbox_layout: dict = {"style": "open-street-map"}
    if resultado_geojson:
        geojsons, (lon_min, lat_min, lon_max, lat_max) = resultado_geojson
        center, zoom = compute_mapbox_view(lat_min, lat_max, lon_min, lon_max)
        layers = []
        for geojson in geojsons:
            layers.extend(mapbox_polygon_layers(geojson, PALETTE["navy"]))
        mapbox_layout["layers"] = layers
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

    territorio_txt = (
        f"{len(provincias)} provincia(s), {len(cantones)} cantón(es), {len(parroquias)} parroquia(s)"
        if (provincias or cantones or parroquias) else "Nacional"
    )
    message = f"{len(df):,} nodos mostrados · Territorio: {territorio_txt}".replace(",", ".")

    # Barra horizontal, no otro mapa/torta -- un mapa comunica densidad
    # espacial bien, pero compara MAGNITUDES mal (el ojo no mide área/
    # densidad de puntos con precisión); una barra ordenada sí permite
    # comparar "¿cuánto más tiene Pichincha que Guayas?" de un vistazo.
    conteo_provincia = (
        df["nombre_provincia"].value_counts().head(15).sort_values()
    )
    provincia_fig = go.Figure(go.Bar(
        x=conteo_provincia.values, y=conteo_provincia.index, orientation="h",
        marker_color=PALETTE["blue"],
        hovertemplate="%{y}: %{x}<extra></extra>",
    ))
    style_figure(provincia_fig, height=420, hovermode="closest")
    provincia_fig.update_xaxes(title="Nodos")
    provincia_fig.update_yaxes(title="")

    return fig, provincia_fig, clean_records(df), message
