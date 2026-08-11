"""dashboard/components/lines_territory_filters.py — Provincia/Cantón/Parroquia, multi-select, sin Nivel.

Filtro geográfico para el módulo Control -- geografía de LÍNEAS reportadas
(mart.dim_territorio, vía get_territory_options()), el mismo universo que
territory_filters.py (Evolución/Concentración), NO la geografía de nodos
ISP (components/node_territory_filters.py).

CORRECCIÓN (12-ago-2026): el primer intento de este filtro reusó
territory_filter_layout() de components/territory_filters.py tal cual --
eso trae "Nivel geográfico" y selección de un solo valor por nivel, que
Iván explícitamente NO pidió para Control. Lo que pidió es el mismo patrón
ya usado en Mapa de nodos/Discrepancias de geografía: Provincia, Cantón y
Parroquia siempre visibles, cada uno de selección múltiple e independiente
(sin jerarquía obligatoria) -- ver components/node_territory_filters.py,
que sigue exactamente ese mismo patrón pero sobre geografía de nodos.

Es deliberadamente un módulo aparte, no una generalización de
node_territory_filters.py -- unificarlos exigiría parametrizar la función
de opciones (get_territory_options vs. get_node_territory_options) y
tocar mapa_nodos.py/discrepancias_geografia.py, que ya funcionan en
producción; la duplicación aquí es más segura que ese riesgo.

Store final: {"provincias": [...], "cantones": [...], "parroquias": [...]}
-- NO comparte store con territory_filters.py (Nivel/single-select) ni con
node_territory_filters.py (geografía de nodos). Vive local a la página que
lo use (sin sincronización entre páginas -- Control es la única que lo usa
por ahora).
"""
from __future__ import annotations

from dash import Input, Output, callback, dcc, html

from services.queries import get_territory_options


def lines_territory_filter_layout(prefix: str) -> html.Div:
    return html.Div(
        className="territory-grid",
        children=[
            html.Div(
                className="filter-field",
                children=[
                    html.Label("Provincia"),
                    dcc.Dropdown(
                        id=f"{prefix}-province", options=get_territory_options("PROVINCIA"), value=[], multi=True,
                        placeholder="Todas",
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
    @callback(
        Output(f"{prefix}-canton", "options"),
        Input(f"{prefix}-province", "value"),
    )
    def update_cantons(provincias):
        if provincias:
            opciones = []
            for codigo in provincias:
                opciones.extend(get_territory_options("CANTON", province_code=codigo))
            return opciones
        return get_territory_options("CANTON")

    @callback(
        Output(f"{prefix}-parish", "options"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
    )
    def update_parishes(provincias, cantones):
        # codigo_canton en INEC ya incluye el prefijo de provincia (ej.
        # 1701 = Quito), es único a nivel nacional -- filtrar por
        # canton_code solo es suficiente, no hace falta combinarlo con
        # provincia (y hacerlo produciría duplicados si el usuario eligió
        # varias provincias). Mismo razonamiento que node_territory_filters.py.
        if cantones:
            opciones = []
            for canton in cantones:
                opciones.extend(get_territory_options("PARROQUIA", canton_code=canton))
            return opciones
        if provincias:
            opciones = []
            for codigo in provincias:
                opciones.extend(get_territory_options("PARROQUIA", province_code=codigo))
            return opciones
        return get_territory_options("PARROQUIA")

    @callback(
        Output(f"{prefix}-territory-selection", "data"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
        Input(f"{prefix}-parish", "value"),
    )
    def resolve_selection(provincias, cantones, parroquias):
        return {
            "provincias": provincias or [],
            "cantones": cantones or [],
            "parroquias": parroquias or [],
        }
