"""dashboard/components/node_territory_filters.py — Filtro geográfico de nodos ISP.

Mismo universo que antes -- mart.vw_dashboard_filtros_geograficos_nodo
(geografía CONALI derivada de coordenadas), NUNCA
get_territory_options()/mart.vw_dashboard_filtros_geograficos (geografía de
líneas reportadas). Confirmado con Iván 06-ago-2026 -- un nodo físico puede
servir a varias parroquias de líneas, no hay relación 1:1.

REDISEÑO (11-ago-2026, a pedido de Iván): se elimina el selector "Nivel
geográfico" -- Provincia, Cantón y Parroquia quedan siempre visibles, cada
uno de SELECCIÓN MÚLTIPLE e independiente entre sí (estilo segmentadores de
Power BI), no una jerarquía de un solo nivel a la vez como antes. Cantón se
sigue acotando a las provincias elegidas (si hay alguna elegida) y Parroquia
a los cantones elegidos, solo para reducir ruido en la lista -- pero el
filtrado real en SQL aplica los tres criterios de forma independiente
(AND entre dimensiones, OR dentro de cada lista): es posible, por ejemplo,
elegir una parroquia sin haber elegido su provincia primero.

NO comparte dcc.Store con territory_filters.py -- "shared-territory" es de
Evolución/Concentración (geografía de líneas). Las páginas de nodos usan su
propio store local ("nodo-shared-territory"), sincronizado solo entre ellas
(Mapa de Nodos y Discrepancias de Geografía). Su forma cambió de
{level, province, canton, parish, territory_id} (un solo valor por nivel) a
{provincias, cantones, parroquias} (listas), reflejando la selección
múltiple -- ver app.py para el valor inicial del Store.
"""
from __future__ import annotations

from dash import Input, Output, State, callback, dcc, html

from services.queries import get_node_territory_options


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
    @callback(
        Output(f"{prefix}-province", "options"),
        Output(f"{prefix}-province", "value"),
        Input("nodo-shared-territory", "modified_timestamp"),
        State("nodo-shared-territory", "data"),
        State(f"{prefix}-province", "value"),
    )
    def init_provinces(_ts, shared_data, current_value):
        options = get_node_territory_options("PROVINCIA")
        valores_validos = {o["value"] for o in options}
        # Al restaurar desde el store compartido (primera carga o al volver
        # de la otra página de nodos), usa lo guardado; en interacción
        # normal, respeta lo que el usuario ya tiene elegido en ESTE dropdown.
        deseado = current_value if current_value else (shared_data or {}).get("provincias", [])
        value = [v for v in (deseado or []) if v in valores_validos]
        return options, value

    @callback(
        Output(f"{prefix}-canton", "options"),
        Output(f"{prefix}-canton", "value"),
        Input(f"{prefix}-province", "value"),
        Input("nodo-shared-territory", "modified_timestamp"),
        State("nodo-shared-territory", "data"),
        State(f"{prefix}-canton", "value"),
    )
    def update_cantons(provincias, _ts, shared_data, current_value):
        # Sin provincia elegida: TODOS los cantones del país (no deshabilitado
        # como antes -- ya no hay jerarquía obligatoria, el usuario puede
        # empezar por Cantón directamente).
        options: list = []
        if provincias:
            for codigo in provincias:
                options.extend(get_node_territory_options("CANTON", province_code=codigo))
        else:
            options = get_node_territory_options("CANTON")
        valores_validos = {o["value"] for o in options}
        deseado = current_value if current_value else (shared_data or {}).get("cantones", [])
        value = [v for v in (deseado or []) if v in valores_validos]
        return options, value

    @callback(
        Output(f"{prefix}-parish", "options"),
        Output(f"{prefix}-parish", "value"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
        Input("nodo-shared-territory", "modified_timestamp"),
        State("nodo-shared-territory", "data"),
        State(f"{prefix}-parish", "value"),
    )
    def update_parishes(provincias, cantones, _ts, shared_data, current_value):
        # codigo_canton en INEC ya incluye el prefijo de provincia (ej. 1701
        # = Quito), es único a nivel nacional -- filtrar por canton_code solo
        # es suficiente, no hace falta combinarlo con provincia (y hacerlo
        # produciría duplicados si el usuario eligió varias provincias).
        options: list = []
        if cantones:
            for canton in cantones:
                options.extend(get_node_territory_options("PARROQUIA", canton_code=canton))
        elif provincias:
            for codigo in provincias:
                options.extend(get_node_territory_options("PARROQUIA", province_code=codigo))
        else:
            options = get_node_territory_options("PARROQUIA")
        valores_validos = {o["value"] for o in options}
        deseado = current_value if current_value else (shared_data or {}).get("parroquias", [])
        value = [v for v in (deseado or []) if v in valores_validos]
        return options, value

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
