"""dashboard/components/node_territory_filters.py — Filtro geográfico en cascada, para nodos ISP.

Mismo patrón visual y de callbacks que components/territory_filters.py --
pero apunta a get_node_territory_options() (mart.vw_dashboard_filtros_
geograficos_nodo, geografía CONALI derivada de coordenadas), NUNCA a
get_territory_options() (geografía de líneas reportadas). Universo
distinto, confirmado con Iván 06-ago-2026 -- un nodo físico puede servir a
varias parroquias de líneas, no hay relación 1:1.

NO comparte dcc.Store con territory_filters.py -- "shared-territory" es de
Evolución/Concentración (geografía de líneas). Las páginas de nodos usan su
propio store local ("nodo-shared-territory"), sincronizado solo entre ellas
(Mapa de Nodos y Discrepancias de Geografía), para no cruzar dos conceptos
de "territorio" distintos bajo la misma clave compartida.
"""
from __future__ import annotations

from dash import Input, Output, State, callback, dcc, html

from services.queries import get_node_territory_options

LEVEL_OPTIONS = [
    {"label": "Nacional", "value": "NACIONAL"},
    {"label": "Provincia", "value": "PROVINCIA"},
    {"label": "Cantón", "value": "CANTON"},
    {"label": "Parroquia", "value": "PARROQUIA"},
]


def node_territory_filter_layout(prefix: str) -> html.Div:
    return html.Div(
        className="territory-grid",
        children=[
            html.Div(
                className="filter-field",
                children=[
                    html.Label("Nivel geográfico"),
                    dcc.Dropdown(
                        id=f"{prefix}-level",
                        options=LEVEL_OPTIONS,
                        value="NACIONAL",
                        clearable=False,
                    ),
                ],
            ),
            html.Div(
                className="filter-field",
                children=[
                    html.Label("Provincia"),
                    dcc.Dropdown(id=f"{prefix}-province", disabled=True, clearable=False),
                ],
            ),
            html.Div(
                className="filter-field",
                children=[
                    html.Label("Cantón"),
                    dcc.Dropdown(id=f"{prefix}-canton", disabled=True, clearable=False),
                ],
            ),
            html.Div(
                className="filter-field",
                children=[
                    html.Label("Parroquia"),
                    dcc.Dropdown(id=f"{prefix}-parish", disabled=True, clearable=False),
                ],
            ),
            dcc.Store(id=f"{prefix}-territory-id", data="NACIONAL|ECUADOR"),
        ],
    )


def register_node_territory_callbacks(prefix: str) -> None:
    @callback(
        Output(f"{prefix}-level", "value"),
        Input("nodo-shared-territory", "data"),
    )
    def restore_level(shared_data):
        return (shared_data or {}).get("level", "NACIONAL")

    @callback(
        Output(f"{prefix}-province", "options"),
        Output(f"{prefix}-province", "value"),
        Output(f"{prefix}-province", "disabled"),
        Input(f"{prefix}-level", "value"),
        State("nodo-shared-territory", "data"),
    )
    def update_provinces(level: str, shared_data):
        enabled = level in {"PROVINCIA", "CANTON", "PARROQUIA"}
        if not enabled:
            return [], None, True
        options = get_node_territory_options("PROVINCIA")
        deseada = (shared_data or {}).get("province")
        valores_validos = {o["value"] for o in options}
        value = deseada if deseada in valores_validos else (options[0]["value"] if options else None)
        return options, value, False

    @callback(
        Output(f"{prefix}-canton", "options"),
        Output(f"{prefix}-canton", "value"),
        Output(f"{prefix}-canton", "disabled"),
        Input(f"{prefix}-level", "value"),
        Input(f"{prefix}-province", "value"),
        State("nodo-shared-territory", "data"),
    )
    def update_cantons(level: str, province: str | None, shared_data):
        enabled = level in {"CANTON", "PARROQUIA"} and bool(province)
        if not enabled:
            return [], None, True
        options = get_node_territory_options("CANTON", province_code=province)
        deseada = (shared_data or {}).get("canton")
        valores_validos = {o["value"] for o in options}
        value = deseada if deseada in valores_validos else (options[0]["value"] if options else None)
        return options, value, False

    @callback(
        Output(f"{prefix}-parish", "options"),
        Output(f"{prefix}-parish", "value"),
        Output(f"{prefix}-parish", "disabled"),
        Input(f"{prefix}-level", "value"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
        State("nodo-shared-territory", "data"),
    )
    def update_parishes(level: str, province: str | None, canton: str | None, shared_data):
        enabled = level == "PARROQUIA" and bool(province) and bool(canton)
        if not enabled:
            return [], None, True
        options = get_node_territory_options("PARROQUIA", province_code=province, canton_code=canton)
        deseada = (shared_data or {}).get("parish")
        valores_validos = {o["value"] for o in options}
        value = deseada if deseada in valores_validos else (options[0]["value"] if options else None)
        return options, value, False

    @callback(
        Output(f"{prefix}-territory-id", "data"),
        Output("nodo-shared-territory", "data", allow_duplicate=True),
        Input(f"{prefix}-level", "value"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
        Input(f"{prefix}-parish", "value"),
        State(f"{prefix}-territory-id", "data"),
        prevent_initial_call=True,
    )
    def resolve_territory(
            level: str,
            province: str | None,
            canton: str | None,
            parish: str | None,
            current: str,
    ):
        if level == "NACIONAL":
            territorio_id = "NACIONAL|ECUADOR"
        elif level == "PROVINCIA" and province:
            territorio_id = f"PROVINCIA|{province}"
        elif level == "CANTON" and province and canton:
            territorio_id = f"CANTON|{province}|{canton}"
        elif level == "PARROQUIA" and province and canton and parish:
            territorio_id = f"PARROQUIA|{province}|{canton}|{parish}"
        else:
            territorio_id = current or "NACIONAL|ECUADOR"

        compartido = {
            "level": level,
            "province": province,
            "canton": canton,
            "parish": parish,
            "territory_id": territorio_id,
        }
        return territorio_id, compartido
