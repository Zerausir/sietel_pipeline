"""dashboard/components/node_territory_filters.py — Filtro geográfico de nodos ISP.

Mismo universo que antes -- mart.vw_dashboard_filtros_geograficos_nodo
(geografía CONALI derivada de coordenadas), NUNCA
get_territory_options()/mart.vw_dashboard_filtros_geograficos (geografía de
líneas reportadas). Confirmado con Iván 06-ago-2026 -- un nodo físico puede
servir a varias parroquias de líneas, no hay relación 1:1.

REDISEÑO (11-ago-2026, a pedido de Iván): se elimina el selector "Nivel
geográfico" -- Provincia, Cantón y Parroquia quedan siempre visibles, cada
uno de SELECCIÓN MÚLTIPLE e independiente entre sí (estilo segmentadores de
Power BI), no una jerarquía de un solo nivel a la vez como antes.

FILTRADO CRUZADO (13-ago-2026, a pedido de Iván): antes, Cantón se acotaba
a la Provincia elegida y Parroquia al Cantón/Provincia elegidos, pero NUNCA
al revés -- elegir una Parroquia sin tocar Provincia dejaba el selector de
Provincia mostrando las 26 opciones completas, no solo la que corresponde.
Ahora los tres niveles se acotan entre sí en cualquier dirección (ver
services.queries.opciones_geograficas_facetadas()).

DECISIÓN DE DISEÑO IMPORTANTE, no un descuido: el filtrado cruzado SOLO
acota las OPCIONES visibles de los otros dos selectores -- nunca borra un
VALOR que el usuario ya eligió, aunque ese valor deje de aparecer en la
lista visible del selector cruzado. Dos razones, no una sola:
  1. Borrar automáticamente una selección explícita del usuario porque
     OTRO campo cambió es una sorpresa desagradable -- Iván pidió "que se
     acoten las opciones", no "que se me borre lo que elegí".
  2. Es estructuralmente necesario: si Output(Provincia.value) dependiera
     de Input(Cantón.value) Y Output(Cantón.value) dependiera de
     Input(Provincia.value) al mismo tiempo, Dash detecta esto como una
     DEPENDENCIA CIRCULAR real en su grafo de callbacks (no en tiempo de
     ejecución -- en el grafo estático, sin importar qué tan inofensiva
     sea la lógica interna) y la aplicación no arrancaría. Por eso las
     opciones y el valor de cada selector viven en callbacks SEPARADOS:
     las opciones reaccionan a los hermanos (Input), el valor solo se
     restaura desde el store compartido al montar la página (nunca desde
     un hermano) -- ver register_node_territory_callbacks() más abajo.

NO comparte dcc.Store con territory_filters.py -- "shared-territory" es de
Evolución/Concentración (geografía de líneas). Las páginas de nodos usan su
propio store local ("nodo-shared-territory"), sincronizado solo entre ellas
(Mapa de Nodos y Discrepancias de Geografía). Su forma es
{provincias, cantones, parroquias} (listas), reflejando la selección
múltiple -- ver app.py para el valor inicial del Store.
"""
from __future__ import annotations

import dash
from dash import Input, Output, State, callback, dcc, html

from services.queries import get_node_territory_hierarchy, opciones_geograficas_facetadas


def node_territory_filter_layout(prefix: str) -> html.Div:
    return html.Div(
        className="territory-grid",
        children=[
            html.Div(
                className="filter-field",
                children=[
                    html.Label("Provincia"),
                    dcc.Dropdown(
                        id=f"{prefix}-province", options=[], value=[], multi=True, placeholder="Todas",
                    ),
                ],
            ),
            html.Div(
                className="filter-field",
                children=[
                    html.Label("Cantón"),
                    dcc.Dropdown(
                        id=f"{prefix}-canton", options=[], value=[], multi=True, placeholder="Todos",
                    ),
                ],
            ),
            html.Div(
                className="filter-field",
                children=[
                    html.Label("Parroquia"),
                    dcc.Dropdown(
                        id=f"{prefix}-parish", options=[], value=[], multi=True, placeholder="Todas",
                    ),
                ],
            ),
            dcc.Store(id=f"{prefix}-territory-selection", data={"provincias": [], "cantones": [], "parroquias": []}),
        ],
    )


def register_node_territory_callbacks(prefix: str) -> None:
    # --- Opciones: reaccionan a los DOS hermanos, filtrado cruzado real ---
    @callback(
        Output(f"{prefix}-province", "options"),
        Input(f"{prefix}-canton", "value"),
        Input(f"{prefix}-parish", "value"),
    )
    def opciones_provincia(cantones, parroquias):
        jerarquia = get_node_territory_hierarchy()
        return opciones_geograficas_facetadas(
            jerarquia, "codigo_provincia", "nombre_provincia",
            {"codigo_canton": cantones or [], "codigo_parroquia": parroquias or []},
        )

    @callback(
        Output(f"{prefix}-canton", "options"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-parish", "value"),
    )
    def opciones_canton(provincias, parroquias):
        jerarquia = get_node_territory_hierarchy()
        return opciones_geograficas_facetadas(
            jerarquia, "codigo_canton", "nombre_canton",
            {"codigo_provincia": provincias or [], "codigo_parroquia": parroquias or []},
        )

    @callback(
        Output(f"{prefix}-parish", "options"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
    )
    def opciones_parroquia(provincias, cantones):
        jerarquia = get_node_territory_hierarchy()
        return opciones_geograficas_facetadas(
            jerarquia, "codigo_parroquia", "nombre_parroquia",
            {"codigo_provincia": provincias or [], "codigo_canton": cantones or []},
        )

    # --- Valor: SOLO se restaura desde el store compartido al montar la
    # página (nunca desde un hermano) -- ver el docstring del módulo para
    # por qué esto tiene que vivir separado de las opciones.
    #
    # Se valida contra la jerarquía COMPLETA (todos los códigos reales),
    # no contra el "options" actual del propio selector vía State -- ese
    # State podría leerse ANTES de que opciones_provincia()/opciones_canton()/
    # opciones_parroquia() hayan corrido en la primera carga (Dash no
    # garantiza el orden de ejecución entre un State y el callback que
    # produce ese valor, solo entre Input/Output). Validar contra la
    # jerarquía completa evita esa carrera por completo -- cualquier
    # código real pasa, cualquier código inválido se descarta igual. ---
    def _restaurar_valor(campo: str, columna_codigo: str):
        @callback(
            Output(f"{prefix}-{campo}", "value"),
            Input("nodo-shared-territory", "modified_timestamp"),
            State("nodo-shared-territory", "data"),
            State(f"{prefix}-{campo}", "value"),
        )
        def restaurar(_ts, shared_data, current_value):
            if current_value:
                return dash.no_update
            clave = {"province": "provincias", "canton": "cantones", "parish": "parroquias"}[campo]
            deseado = (shared_data or {}).get(clave, [])
            jerarquia = get_node_territory_hierarchy()
            valores_validos = set(jerarquia[columna_codigo].dropna().astype(str).unique())
            return [v for v in deseado if v in valores_validos]

        return restaurar

    _restaurar_valor("province", "codigo_provincia")
    _restaurar_valor("canton", "codigo_canton")
    _restaurar_valor("parish", "codigo_parroquia")

    @callback(
        Output(f"{prefix}-territory-selection", "data"),
        Output("nodo-shared-territory", "data", allow_duplicate=True),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
        Input(f"{prefix}-parish", "value"),
        prevent_initial_call=True,
    )
    def resolve_selection(provincias, cantones, parroquias):
        seleccion = {
            "provincias": provincias or [],
            "cantones": cantones or [],
            "parroquias": parroquias or [],
        }
        return seleccion, seleccion
