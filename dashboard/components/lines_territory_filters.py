"""dashboard/components/lines_territory_filters.py — Provincia/Cantón/Parroquia, multi-select, sin Nivel.

Filtro geográfico para el módulo Control -- geografía de LÍNEAS reportadas
(mart.dim_territorio, vía get_territory_options()), el mismo universo que
territory_filters.py (Evolución/Concentración), NO la geografía de nodos
ISP (components/node_territory_filters.py).

Es deliberadamente un módulo aparte, no una generalización de
node_territory_filters.py -- unificarlos exigiría parametrizar la función
de opciones (get_territory_options vs. get_node_territory_options) y
tocar mapa_nodos.py/discrepancias_geografia.py, que ya funcionan en
producción; la duplicación aquí es más segura que ese riesgo.

FILTRADO CRUZADO (13-ago-2026, a pedido de Iván): elegir un valor en
cualquiera de los tres selectores acota las opciones de los OTROS DOS,
no solo hacia abajo (Provincia→Cantón→Parroquia) como antes. Mismo
mecanismo y misma decisión de diseño que node_territory_filters.py --
ver el docstring de ese módulo para el porqué completo (evitar una
dependencia circular real en el grafo de callbacks de Dash, y no borrar
selecciones explícitas del usuario solo porque otro campo cambió).

Store final: {"provincias": [...], "cantones": [...], "parroquias": [...]}
-- NO comparte store con territory_filters.py (Nivel/single-select) ni con
node_territory_filters.py (geografía de nodos). Vive local a la página que
lo use (sin sincronización entre páginas -- Control es la única que lo usa
por ahora).
"""
from __future__ import annotations

from dash import Input, Output, callback, dcc, html

from services.queries import get_territory_hierarchy, opciones_geograficas_facetadas


def lines_territory_filter_layout(prefix: str) -> html.Div:
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


def register_lines_territory_callbacks(prefix: str) -> None:
    # --- Opciones: reaccionan a los DOS hermanos, filtrado cruzado real ---
    @callback(
        Output(f"{prefix}-province", "options"),
        Input(f"{prefix}-canton", "value"),
        Input(f"{prefix}-parish", "value"),
    )
    def opciones_provincia(cantones, parroquias):
        jerarquia = get_territory_hierarchy()
        return opciones_geograficas_facetadas(
            jerarquia, "codigo_provincia", "pro_nombre",
            {"codigo_canton": cantones or [], "codigo_parroquia": parroquias or []},
        )

    @callback(
        Output(f"{prefix}-canton", "options"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-parish", "value"),
    )
    def opciones_canton(provincias, parroquias):
        jerarquia = get_territory_hierarchy()
        return opciones_geograficas_facetadas(
            jerarquia, "codigo_canton", "ciu_nombre",
            {"codigo_provincia": provincias or [], "codigo_parroquia": parroquias or []},
        )

    @callback(
        Output(f"{prefix}-parish", "options"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
    )
    def opciones_parroquia(provincias, cantones):
        jerarquia = get_territory_hierarchy()
        return opciones_geograficas_facetadas(
            jerarquia, "codigo_parroquia", "par_nombre",
            {"codigo_provincia": provincias or [], "codigo_canton": cantones or []},
        )

    # --- Valor: sin store compartido entre páginas para Control (a
    # diferencia de node_territory_filters.py) -- no hace falta un
    # callback de "restaurar al montar", el valor inicial [] de cada
    # dropdown ya es correcto la primera vez que se abre Control. ---

    @callback(
        Output(f"{prefix}-territory-selection", "data"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
        Input(f"{prefix}-parish", "value"),
        prevent_initial_call=True,
    )
    def resolve_selection(provincias, cantones, parroquias):
        return {
            "provincias": provincias or [],
            "cantones": cantones or [],
            "parroquias": parroquias or [],
        }
